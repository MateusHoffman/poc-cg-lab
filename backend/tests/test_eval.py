import asyncio

import pytest

from app.agent import run_turn
from app.guardrails import judge_answer
from app.runtime import Runtime


@pytest.mark.asyncio
async def test_hallucination_guardrail_on_impossible_request():
    runtime = Runtime.local()
    result = await asyncio.to_thread(
        run_turn, runtime, "Quero comprar um carro que voa movido a plutônio.", "eval-1"
    )
    verdict = judge_answer(result["answer"], result["answer"], [item["model"] for item in result["vehicles"]])
    assert result["vehicles"] == []
    assert verdict["passed"] is True
    assert verdict["hallucination_rate"] == 0
    assert "não encontrei" in result["answer"].lower()


def test_finance_answer_is_grounded_in_sandbox():
    runtime = Runtime.local()
    result = run_turn(runtime, "Simule o financiamento do Polo em 48x com 20% de entrada", "eval-2")
    assert result["sandbox_used"] is True
    assert result["finance"]["months"] == 48
    assert result["finance"]["installment"] > 1000
    assert "Polo" in result["answer"]
    verdict = judge_answer("polo", result["answer"], ["Polo"])
    assert verdict["passed"] is True


def test_compare_uses_session_memory():
    runtime = Runtime.local()
    first = run_turn(runtime, "Quero um Polo", "eval-3")
    runtime.sessions.save_state("eval-3", [item["id"] for item in first["vehicles"]], first["intent"])
    second = run_turn(runtime, "Compare com o Onix", "eval-3")
    models = {item["model"] for item in second["vehicles"]}
    assert models == {"Polo", "Onix"}
