from __future__ import annotations

import hashlib
import math
import re
import unicodedata

EMBEDDING_DIM = 64


def fold(value: str) -> str:
    decomposed = unicodedata.normalize("NFD", value.lower())
    without_accents = "".join(
        char for char in decomposed if unicodedata.category(char) != "Mn"
    )
    return re.sub(r"\s+", " ", without_accents).strip()


def brl(value: float) -> str:
    formatted = f"{value:,.2f}"
    swapped = formatted.replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {swapped}"


def embed(text: str) -> list[float]:
    """Embedding local determinístico.

    Troque esta função por embeddings Gemini/Vertex em produção.
    A dimensão e o contrato (lista normalizada) permanecem os mesmos,
    então o pgvector não muda.
    """
    vector = [0.0] * EMBEDDING_DIM
    tokens = re.findall(r"[a-z0-9]+", fold(text))
    if not tokens:
        return vector
    for token in tokens:
        digest = int(hashlib.sha256(token.encode()).hexdigest(), 16)
        index = digest % EMBEDDING_DIM
        sign = 1.0 if ((digest // EMBEDDING_DIM) % 2 == 0) else -1.0
        vector[index] += sign
    norm = math.sqrt(sum(component * component for component in vector)) or 1.0
    return [component / norm for component in vector]


def cosine(left: list[float], right: list[float]) -> float:
    return sum(a * b for a, b in zip(left, right, strict=True))


def vehicle_document(vehicle: dict) -> str:
    return " ".join(
        [
            vehicle["brand"],
            vehicle["model"],
            str(vehicle["year"]),
            vehicle["body"],
            vehicle["fuel"],
            vehicle["transmission"],
            vehicle["city"],
            vehicle["features"],
        ]
    )
