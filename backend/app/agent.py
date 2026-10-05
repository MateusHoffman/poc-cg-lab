from __future__ import annotations

import json
import time
from dataclasses import asdict
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from app.catalog import VEHICLES
from app.observability import start_span
from app.runtime import Runtime
from app.sandbox import run_sandbox
from app.search import (
    MONTHLY_RATE,
    decision_score,
    parse_filters,
    parse_finance,
    rank_vehicles,
)
from app.text import brl, fold

CACHE_TTL_SECONDS = 120


class AgentState(TypedDict, total=False):
    query: str
    session_id: str
    intent: str
    vehicles: list
    finance: dict | None
    recommendation_id: str | None
    sandbox_used: bool
    answer: str
    grounding: str


def classify(query: str) -> str:
    folded = fold(query)
    filters = parse_filters(query)
    if any(word in folded for word in ("financ", "parcela", "juros", "simule", "simular", "prestacao")):
        return "finance"
    if "compar" in folded or " versus " in folded or " vs " in folded or len(filters.models) >= 2:
        return "compare"
    if any(word in folded for word in ("melhor", "recomend", "vale a pena", "escolher", "decid")):
        return "decide"
    return "explore"


def _by_ids(ids: list[str]) -> list[dict]:
    catalog = {vehicle["id"]: vehicle for vehicle in VEHICLES}
    return [dict(catalog[vehicle_id]) for vehicle_id in ids if vehicle_id in catalog]


def _search(runtime: Runtime, query: str, limit: int) -> list[dict]:
    with start_span("tool.vector_search", limit=limit):
        return rank_vehicles(query, runtime.vector.scores(query), limit)


def _empty_payload(vehicles: list[dict]) -> dict:
    return {
        "vehicles": vehicles,
        "finance": None,
        "recommendation_id": None,
        "sandbox_used": False,
    }


def _render_line(vehicle: dict) -> str:
    transmission = "automático" if vehicle["transmission"] == "automatico" else "manual"
    distance = f"{vehicle['km']:,}".replace(",", ".")
    return (
        f"{vehicle['brand']} {vehicle['model']} {vehicle['year']} por {brl(vehicle['price'])}, "
        f"{distance} km, {vehicle['fuel']}, câmbio {transmission}, "
        f"{vehicle['body']}, {vehicle['city']}"
    )


def _render_answer(state: AgentState) -> str:
    vehicles = state.get("vehicles") or []
    intent = state.get("intent")
    if intent == "finance" and not state.get("finance"):
        if not vehicles:
            return (
                "Não encontrei um veículo do inventário para simular. "
                "Diga o modelo, por exemplo Polo em 48x."
            )
        return (
            "A ferramenta de sandbox financeiro está desligada pela feature flag finance-sandbox. "
            "A busca no inventário continua disponível."
        )
    if intent == "compare":
        if len(vehicles) < 2:
            return (
                "Preciso de dois modelos do inventário para comparar. "
                "Cite os nomes, por exemplo Polo e Onix, ou faça uma busca antes."
            )
        left, right = vehicles[0], vehicles[1]
        cheaper = left if left["price"] <= right["price"] else right
        lower_km = left if left["km"] <= right["km"] else right
        if left["year"] == right["year"]:
            year_note = f"Os dois são {left['year']}"
        else:
            newer = left if left["year"] > right["year"] else right
            year_note = f"O mais novo é o {newer['model']}"
        return (
            f"Comparando {_render_line(left)}.\n"
            f"E {_render_line(right)}.\n"
            f"O mais barato é o {cheaper['model']}. {year_note}. "
            f"A menor quilometragem é a do {lower_km['model']}."
        )
    if intent == "finance":
        vehicle = vehicles[0]
        finance = state["finance"]
        assert finance is not None
        down_percent = int(finance["down_ratio"] * 100)
        return (
            f"Simulação do {vehicle['brand']} {vehicle['model']} {vehicle['year']} "
            f"em {finance['months']}x, entrada de {down_percent}% ({brl(finance['down_payment'])}).\n"
            f"Valor financiado: {brl(finance['principal'])}. Taxa de referência: 1,49% ao mês.\n"
            f"Parcela estimada pelo sandbox: {brl(finance['installment'])}.\n"
            f"Expressão executada: {finance['code']}"
        )
    if intent == "decide":
        if not vehicles:
            return "Não encontrei candidatos no inventário para recomendar."
        best = next(vehicle for vehicle in vehicles if vehicle["id"] == state.get("recommendation_id"))
        others = [vehicle["model"] for vehicle in vehicles if vehicle["id"] != best["id"]]
        extra = ""
        if others:
            extra = " Os outros candidatos considerados foram: " + ", ".join(others) + "."
        distance = f"{best['km']:,}".replace(",", ".")
        return (
            f"Recomendo o {best['brand']} {best['model']} {best['year']} por {brl(best['price'])}. "
            f"Entre os {len(vehicles)} veículos filtrados, ele equilibra ano ({best['year']}), "
            f"quilometragem ({distance} km) e preço.{extra}"
        )
    if not vehicles:
        return (
            "Não encontrei no inventário um veículo que atenda a esse pedido. "
            "A frota local cobre hatches, sedãs e SUVs; não invento modelos fora dela."
        )
    lines = "\n".join(f"- {_render_line(vehicle)}." for vehicle in vehicles)
    return f"Encontrei {len(vehicles)} veículos compatíveis com a busca.\n{lines}"


def build_graph(runtime: Runtime):
    def classify_node(state: AgentState) -> dict:
        return {"intent": classify(state["query"])}

    def explore_node(state: AgentState) -> dict:
        return _empty_payload(_search(runtime, state["query"], 3))

    def compare_node(state: AgentState) -> dict:
        selected: list[dict] = []
        seen: set[str] = set()
        for vehicle in _search(runtime, state["query"], 4):
            if vehicle["id"] not in seen:
                selected.append(vehicle)
                seen.add(vehicle["id"])
        if len(selected) < 2:
            previous = runtime.sessions.get_state(state["session_id"]).get("vehicle_ids") or []
            for vehicle in _by_ids(list(previous)):
                if vehicle["id"] not in seen:
                    selected.append(vehicle)
                    seen.add(vehicle["id"])
                if len(selected) >= 2:
                    break
        return _empty_payload(selected[:2])

    def finance_node(state: AgentState) -> dict:
        found = _search(runtime, state["query"], 1)
        if not found:
            previous = runtime.sessions.get_state(state["session_id"]).get("vehicle_ids") or []
            found = _by_ids(list(previous))[:1]
        if not runtime.flags.enabled("finance-sandbox"):
            payload = _empty_payload(found)
            return payload
        if not found:
            return _empty_payload([])
        vehicle = found[0]
        months, down_ratio = parse_finance(state["query"])
        down_payment = round(vehicle["price"] * down_ratio, 2)
        principal = round(vehicle["price"] - down_payment, 2)
        code = f"round(pmt({principal}, {MONTHLY_RATE}, {months}), 2)"
        with start_span("tool.sandbox", months=months):
            installment = run_sandbox(code)
        payload = _empty_payload([vehicle])
        payload["sandbox_used"] = True
        payload["finance"] = {
            "vehicle_id": vehicle["id"],
            "months": months,
            "down_ratio": down_ratio,
            "down_payment": down_payment,
            "principal": principal,
            "monthly_rate": MONTHLY_RATE,
            "installment": installment,
            "code": code,
        }
        return payload

    def decide_node(state: AgentState) -> dict:
        vehicles = _search(runtime, state["query"], 4)
        payload = _empty_payload(vehicles)
        if vehicles:
            best = max(vehicles, key=decision_score)
            payload["recommendation_id"] = best["id"]
        return payload

    def synthesize_node(state: AgentState) -> dict:
        answer = _render_answer(state)
        grounding = json.dumps(
            {
                "answer_anchored": answer,
                "vehicles": state.get("vehicles") or [],
                "finance": state.get("finance"),
            },
            ensure_ascii=False,
        )
        return {"answer": answer, "grounding": grounding}

    graph = StateGraph(AgentState)
    graph.add_node("classify", classify_node)
    graph.add_node("explore", explore_node)
    graph.add_node("compare", compare_node)
    graph.add_node("finance", finance_node)
    graph.add_node("decide", decide_node)
    graph.add_node("synthesize", synthesize_node)
    graph.add_edge(START, "classify")
    graph.add_conditional_edges(
        "classify",
        lambda state: state["intent"],
        {
            "explore": "explore",
            "compare": "compare",
            "finance": "finance",
            "decide": "decide",
        },
    )
    for node_name in ("explore", "compare", "finance", "decide"):
        graph.add_edge(node_name, "synthesize")
    graph.add_edge("synthesize", END)
    return graph.compile()


def _turn_context(runtime: Runtime, query: str, previous: dict) -> dict:
    return {
        "filters": asdict(parse_filters(query)),
        "vector_backend": runtime.vector.backend,
        "session_backend": runtime.sessions.backend,
        "remembered_vehicle_ids": list(previous.get("vehicle_ids") or []),
    }


def run_turn(runtime: Runtime, query: str, session_id: str) -> dict:
    intent = classify(query)
    previous = runtime.sessions.get_state(session_id)
    context = _turn_context(runtime, query, previous)
    fingerprint = tuple(previous.get("vehicle_ids") or [])
    cache_key = (intent, fold(query), fingerprint, runtime.flags.enabled("finance-sandbox"))
    if runtime.flags.enabled("rag-cache"):
        cached = runtime.cache.get(cache_key)
        if cached and time.time() - cached[0] < CACHE_TTL_SECONDS:
            payload = dict(cached[1])
            payload["cache_hit"] = True
            payload["tokens_saved"] = payload["tokens_estimated"]
            payload.update(context)
            return payload

    graph = getattr(runtime, "_graph", None)
    if graph is None:
        graph = build_graph(runtime)
        runtime._graph = graph
    with start_span("agent.run", intent=intent):
        result = graph.invoke(
            {
                "query": query,
                "session_id": session_id,
                "intent": intent,
                "vehicles": [],
                "finance": None,
                "recommendation_id": None,
                "sandbox_used": False,
                "answer": "",
                "grounding": "",
            }
        )

    answer = result.get("answer") or ""
    grounding = result.get("grounding") or ""
    payload = {
        "intent": result.get("intent") or intent,
        "vehicles": result.get("vehicles") or [],
        "finance": result.get("finance"),
        "recommendation_id": result.get("recommendation_id"),
        "answer": answer,
        "grounding": grounding,
        "sandbox_used": bool(result.get("sandbox_used")),
        "cache_hit": False,
        "tokens_estimated": max(1, (len(answer) + len(grounding)) // 4),
        "tokens_saved": 0,
        "model": "offline-template",
        **context,
    }
    if runtime.flags.enabled("rag-cache"):
        runtime.cache[cache_key] = (time.time(), payload)
    return payload
