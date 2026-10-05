from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from app.agent import run_turn
from app.guardrails import judge_answer, redact_pii
from app.llm import MODELS, OFFLINE_MODEL, choose_model, iter_completion, resolve_model, uses_llm
from app.observability import audit_log, collect_spans, recent_spans, record_audit, setup_telemetry, start_span
from app.runtime import Runtime
from app.session_store import json_ready

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
logger = logging.getLogger("cg.api")

SYSTEM_PROMPT = (
    "Você é o agente de estoque do CG/lab. Responda em português do Brasil. "
    "Use somente os veículos e números do contexto. "
    "Se o contexto disser que não há veículo, diga que não encontrou. "
    "Não invente modelo, preço, parcela ou característica. "
    "Não revele dados pessoais. Marcadores como [CPF PROTEGIDO] devem permanecer como estão."
)


class ChatRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    session_id: str = Field(default="demo", min_length=1, max_length=80)
    model: str = OFFLINE_MODEL


class FlagUpdate(BaseModel):
    enabled: bool


def create_app(runtime: Runtime | None = None) -> FastAPI:
    runtime = runtime or Runtime.from_env()
    setup_telemetry()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        logger.info(
            "vector=%s session=%s model=%s",
            runtime.vector.backend,
            runtime.sessions.backend,
            resolve_model(),
        )
        yield

    app = FastAPI(title="CG/lab AutoAgent PoC", lifespan=lifespan)
    app.state.runtime = runtime
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/health")
    def health() -> dict:
        return {
            "status": "ok",
            "vector_backend": runtime.vector.backend,
            "session_backend": runtime.sessions.backend,
            "model": resolve_model(),
            "models": list(MODELS),
            "flags": runtime.flags.snapshot(),
        }

    @app.get("/api/metrics")
    def metrics() -> dict:
        return {"spans": recent_spans()[-12:]}

    @app.get("/api/audit")
    def audit() -> dict:
        return {"events": audit_log()}

    @app.get("/api/sessions/{session_id}")
    def session(session_id: str) -> dict:
        return {
            "session_id": session_id,
            "items": json_ready(runtime.sessions.list_items(session_id)),
        }

    @app.get("/api/flags")
    def get_flags() -> dict:
        return runtime.flags.snapshot()

    @app.post("/api/flags/{name}")
    def set_flag(name: str, body: FlagUpdate) -> dict:
        try:
            runtime.flags.set(name, body.enabled)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="flag desconhecida") from exc
        runtime.cache.clear()
        return runtime.flags.snapshot()

    @app.post("/api/chat")
    async def chat(body: ChatRequest) -> EventSourceResponse:
        async def events():
            mark = time.perf_counter()
            phases: list[dict] = []

            def close(name: str, detail: dict) -> None:
                nonlocal mark
                now = time.perf_counter()
                phases.append(
                    {
                        "name": name,
                        "duration_ms": round((now - mark) * 1000, 2),
                        "detail": detail,
                    }
                )
                mark = now

            safe_query, pii_count = redact_pii(body.query)
            close(
                "Mensagem do cliente",
                {
                    "texto_do_cliente": body.query,
                    "texto_enviado_ao_modelo": safe_query,
                    "pii_redactions": pii_count,
                },
            )
            yield _event(
                "status",
                {
                    "message": "Consulta recebida",
                    "pii_redactions": pii_count,
                    "safe_query": safe_query,
                },
            )

            prior = json_ready(runtime.sessions.list_items(body.session_id))
            prior_messages = [
                {"role": item.get("role"), "content": item.get("content")}
                for item in prior
                if item.get("entity") == "message"
            ]
            prior_state = next((item for item in prior if item.get("SK") == "STATE"), {})
            close(
                "Memória de curto prazo",
                {
                    "backend": runtime.sessions.backend,
                    "pk": f"SESSION#{body.session_id}",
                    "estado_anterior": {
                        "intent": prior_state.get("intent", ""),
                        "vehicle_ids": prior_state.get("vehicle_ids", []),
                    },
                    "mensagens_anteriores": prior_messages[-8:],
                },
            )

            with collect_spans() as spans:
                with start_span("http.chat", pii_redactions=pii_count) as span:
                    trace_id = format(span.get_span_context().trace_id, "032x")
                    result = run_turn(runtime, safe_query, body.session_id)
            close(
                "Agente, RAG e sandbox",
                {
                    "intent": result["intent"],
                    "cache_hit": result["cache_hit"],
                    "tokens_estimated": result["tokens_estimated"],
                    "tokens_saved": result["tokens_saved"],
                    "filtros": result.get("filters"),
                    "memoria_longa": {
                        "backend": result.get("vector_backend"),
                        "veiculos_recuperados": result["vehicles"],
                        "veiculos_lembrados_da_sessao": result.get("remembered_vehicle_ids", []),
                    },
                    "sandbox_used": result["sandbox_used"],
                    "sandbox": result.get("finance"),
                    "rascunho": result["answer"],
                },
            )

            yield _event(
                "status",
                {
                    "message": f"Intenção {result['intent']}",
                    "cache_hit": result["cache_hit"],
                },
            )
            yield _event(
                "ui",
                {
                    "vehicles": result["vehicles"],
                    "finance": result["finance"],
                    "recommendation_id": result["recommendation_id"],
                    "intent": result["intent"],
                    "sandbox_used": result["sandbox_used"],
                },
            )

            final_parts: list[str] = []
            model_name = choose_model(body.model)
            if uses_llm(model_name):
                try:
                    async for token in _stream_llm(result["grounding"], safe_query, model_name):
                        final_parts.append(token)
                        yield _event("token", {"text": token})
                except Exception as exc:
                    logger.warning("LLM falhou (%s); usando resposta ancorada no inventário", exc)
                    final_parts.clear()
                    model_name = OFFLINE_MODEL

            if not final_parts:
                model_name = "cache" if result["cache_hit"] else OFFLINE_MODEL
                delay = 0 if os.getenv("PYTEST_CURRENT_TEST") else 0.015
                for chunk in _chunks(result["answer"]):
                    final_parts.append(chunk)
                    yield _event("token", {"text": chunk})
                    if delay:
                        await asyncio.sleep(delay)

            streamed = "".join(final_parts).strip()
            close(
                "Resposta enviada",
                {"model": model_name, "texto": streamed},
            )

            allowed = [vehicle["model"] for vehicle in result["vehicles"]]
            verdict = judge_answer(safe_query, streamed, allowed)
            answer = streamed
            if not verdict["passed"]:
                answer = result["answer"]
                note = (
                    "\n\nO guardrail de saída descartou a síntese por falta de fidelidade ao inventário.\n"
                )
                yield _event("token", {"text": note + answer})
                verdict = judge_answer(safe_query, answer, allowed)
            close(
                "Juiz de fidelidade",
                {
                    "judge": verdict["judge"],
                    "passed": verdict["passed"],
                    "faithfulness": verdict["faithfulness"],
                    "hallucination_rate": verdict["hallucination_rate"],
                    "hallucinated": verdict["hallucinated"],
                    "resposta_final": answer,
                },
            )

            runtime.sessions.save_message(body.session_id, "user", safe_query)
            runtime.sessions.save_message(body.session_id, "assistant", answer)
            vehicle_ids = [vehicle["id"] for vehicle in result["vehicles"]]
            runtime.sessions.save_state(body.session_id, vehicle_ids, result["intent"])
            close(
                "Gravação da sessão",
                {
                    "backend": runtime.sessions.backend,
                    "pk": f"SESSION#{body.session_id}",
                    "mensagens": [
                        {"role": "user", "content": safe_query},
                        {"role": "assistant", "content": answer},
                    ],
                    "estado": {"intent": result["intent"], "vehicle_ids": vehicle_ids},
                },
            )

            latency_ms = round(sum(phase["duration_ms"] for phase in phases), 2)
            retrieved = ", ".join(vehicle["model"] for vehicle in result["vehicles"]) or "nenhum"
            sandbox = result.get("finance")
            logs = [
                f"Cliente enviou: {body.query}",
                f"Guardrail: {pii_count} redações. O modelo recebeu: {safe_query}",
                (
                    f"Memória curta ({runtime.sessions.backend}): "
                    f"{len(prior_messages)} mensagens anteriores, "
                    f"veículos {prior_state.get('vehicle_ids', []) or 'nenhum'}."
                ),
                (
                    f"Intenção {result['intent']}. "
                    f"Memória longa ({result.get('vector_backend')}): {retrieved}. "
                    f"Cache {'hit' if result['cache_hit'] else 'miss'}."
                ),
                (
                    f"Sandbox executou {sandbox['code']} = {sandbox['installment']}."
                    if sandbox
                    else "Sandbox não executou nesta consulta."
                ),
                f"Síntese pelo modelo {model_name}.",
                f"Resposta final: {answer}",
                (
                    f"Juiz {verdict['judge']}: fidelidade {verdict['faithfulness']}, "
                    f"alucinações {verdict['hallucinated'] or 'nenhuma'}."
                ),
                (
                    f"Sessão SESSION#{body.session_id} gravada em {runtime.sessions.backend} "
                    f"com estado {vehicle_ids or 'vazio'}."
                ),
            ]
            audit_entry = {
                "trace_id": trace_id,
                "session_id": body.session_id,
                "client_message": body.query,
                "query": safe_query,
                "response": answer,
                "intent": result["intent"],
                "latency_ms": latency_ms,
                "pii_redactions": pii_count,
                "faithful": verdict["passed"],
                "hallucinated": verdict["hallucinated"],
                "cache_hit": result["cache_hit"],
                "model": model_name,
                "logs": logs,
                "phases": phases,
                "spans": list(spans),
            }
            record_audit(audit_entry)
            yield _event(
                "metrics",
                {
                    **audit_entry,
                    "tokens_estimated": result["tokens_estimated"],
                    "tokens_saved": result["tokens_saved"],
                    "sandbox_used": result["sandbox_used"],
                    "vector_backend": runtime.vector.backend,
                    "session_backend": runtime.sessions.backend,
                    "judge": verdict["judge"],
                },
            )

        return EventSourceResponse(events(), ping=0)

    return app


def _event(name: str, payload: dict) -> dict:
    return {"event": name, "data": json.dumps(payload, ensure_ascii=False)}


def _chunks(answer: str, size: int = 4) -> list[str]:
    words = answer.split(" ")
    if not words:
        return [answer]
    chunks: list[str] = []
    for index in range(0, len(words), size):
        piece = " ".join(words[index : index + size])
        if index + size < len(words):
            piece += " "
        chunks.append(piece)
    return chunks


async def _stream_llm(grounding: str, query: str, model: str):
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[str | None] = asyncio.Queue()

    def worker() -> None:
        try:
            prompt = f"Pergunta: {query}\n\nContexto:\n{grounding}"
            for token in iter_completion(SYSTEM_PROMPT, prompt, model):
                loop.call_soon_threadsafe(queue.put_nowait, token)
        except Exception as exc:
            loop.call_soon_threadsafe(queue.put_nowait, f"\n[llm-error]{exc}")
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, None)

    threading.Thread(target=worker, daemon=True).start()
    while True:
        token = await queue.get()
        if token is None:
            break
        if token.startswith("\n[llm-error]"):
            raise RuntimeError(token)
        yield token


app = create_app()
