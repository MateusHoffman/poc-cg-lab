from __future__ import annotations

import re

from app.catalog import VEHICLES
from app.text import fold

CPF_PATTERN = re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b")
EMAIL_PATTERN = re.compile(r"\b[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+\b")
PHONE_PATTERN = re.compile(
    r"(?:\+55\s?)?(?:\(\d{2}\)\s?)(?:9?\d{4})-?\d{4}\b"
)
CARD_PATTERN = re.compile(r"\b(?:\d[ -]*?){13,16}\b")


def redact_pii(text: str) -> tuple[str, int]:
    redacted = text
    total = 0
    for pattern, label in (
        (CPF_PATTERN, "[CPF PROTEGIDO]"),
        (EMAIL_PATTERN, "[EMAIL PROTEGIDO]"),
        (PHONE_PATTERN, "[TELEFONE PROTEGIDO]"),
        (CARD_PATTERN, "[CARTAO PROTEGIDO]"),
    ):
        redacted, count = pattern.subn(label, redacted)
        total += count
    return redacted, total


def mentioned_models(answer: str) -> list[str]:
    folded = fold(answer)
    found: list[str] = []
    for vehicle in VEHICLES:
        model = fold(vehicle["model"])
        if re.search(rf"(?<![a-z0-9]){re.escape(model)}(?![a-z0-9])", folded):
            found.append(vehicle["model"])
    return found


def assess_faithfulness(answer: str, allowed_models: list[str]) -> dict:
    allowed = {fold(model) for model in allowed_models}
    invented = [model for model in mentioned_models(answer) if fold(model) not in allowed]
    return {
        "faithful": not invented,
        "hallucinated": invented,
    }


def judge_answer(query: str, answer: str, allowed_models: list[str]) -> dict:
    """Juiz determinístico. A fonte da verdade é o inventário recuperado na busca."""
    verdict = assess_faithfulness(answer, allowed_models)
    folded = answer.lower()
    refusal = "não encontrei" in folded or "não temos" in folded
    if not verdict["faithful"]:
        passed = False
    elif not allowed_models:
        passed = refusal
    else:
        passed = True
    return {
        "judge": "heuristic",
        "passed": passed,
        "faithfulness": 1.0 if verdict["faithful"] else 0.0,
        "hallucination_rate": 0.0 if verdict["faithful"] else 1.0,
        "hallucinated": verdict["hallucinated"],
        "query": query,
    }
