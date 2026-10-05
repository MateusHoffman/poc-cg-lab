from __future__ import annotations

import json
import os
import urllib.request
from collections.abc import Iterator

OFFLINE_MODEL = "offline-template"
OLLAMA_MODEL = "llama3.1:8b"
MODELS = (OFFLINE_MODEL, OLLAMA_MODEL)


def choose_model(requested: str | None) -> str:
    if requested in MODELS:
        return requested
    return OFFLINE_MODEL


def resolve_model() -> str:
    return OFFLINE_MODEL


def uses_llm(model: str) -> bool:
    return model != OFFLINE_MODEL


def iter_completion(system: str, user: str, model: str) -> Iterator[str]:
    host = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
    payload = json.dumps(
        {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": True,
            "options": {"temperature": 0},
        }
    ).encode()
    request = urllib.request.Request(
        f"{host}/api/chat",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=180) as response:
        for line in response:
            if not line.strip():
                continue
            chunk = json.loads(line)
            if chunk.get("error"):
                raise RuntimeError(str(chunk["error"]))
            text = (chunk.get("message") or {}).get("content") or ""
            if text:
                yield text
            if chunk.get("done"):
                break
