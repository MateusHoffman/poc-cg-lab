from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.catalog import BODY_ALIASES, BRAND_ALIASES, FUEL_ALIASES, VEHICLES
from app.text import cosine, embed, fold, vehicle_document

OUT_OF_DOMAIN = (
    "voa",
    "voar",
    "plutonio",
    "aviao",
    "barco",
    "helicoptero",
    "motocicleta",
    "bicicleta",
)
VALID_MONTHS = {12, 24, 36, 48, 60}
MONTHLY_RATE = 0.0149


@dataclass
class Filters:
    brand: str | None = None
    body: str | None = None
    fuel: str | None = None
    transmission: str | None = None
    max_price: float | None = None
    models: list[str] = field(default_factory=list)


def parse_filters(query: str) -> Filters:
    folded = fold(query)
    filters = Filters()
    for alias, brand in BRAND_ALIASES.items():
        if re.search(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])", folded):
            filters.brand = brand
            break
    for alias, body in BODY_ALIASES.items():
        if re.search(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])", folded):
            filters.body = body
            break
    for alias, fuel in FUEL_ALIASES.items():
        if re.search(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])", folded):
            filters.fuel = fuel
            break
    if "automatico" in folded or "automatica" in folded:
        filters.transmission = "automatico"
    elif re.search(r"(?<![a-z0-9])manual(?![a-z0-9])", folded):
        filters.transmission = "manual"

    price_match = re.search(
        r"(?:ate|abaixo de|menos de|no maximo)\s*r?\$?\s*(\d{1,3}(?:\.\d{3})+|\d+)(?:\s*mil)?",
        folded,
    )
    if price_match:
        raw = price_match.group(1).replace(".", "")
        filters.max_price = float(raw)
        if "mil" in price_match.group(0) and filters.max_price < 1000:
            filters.max_price *= 1000

    for vehicle in VEHICLES:
        model = fold(vehicle["model"])
        if re.search(rf"(?<![a-z0-9]){re.escape(model)}(?![a-z0-9])", folded):
            if vehicle["model"] not in filters.models:
                filters.models.append(vehicle["model"])
    return filters


def parse_finance(query: str) -> tuple[int, float]:
    folded = fold(query)
    months = 48
    match = re.search(r"\b(\d{2})\s*(?:x|meses)\b", folded)
    if match and int(match.group(1)) in VALID_MONTHS:
        months = int(match.group(1))
    down = 0.20
    percent = re.search(r"\b(\d{1,2})\s*%", folded)
    if percent:
        down = int(percent.group(1)) / 100
    return months, down


def is_out_of_domain(query: str) -> bool:
    folded = fold(query)
    return any(term in folded for term in OUT_OF_DOMAIN)


def _matches(vehicle: dict, filters: Filters) -> bool:
    if filters.brand and vehicle["brand"] != filters.brand:
        return False
    if filters.body and vehicle["body"] != filters.body:
        return False
    if filters.fuel and vehicle["fuel"] != filters.fuel:
        return False
    if filters.transmission and vehicle["transmission"] != filters.transmission:
        return False
    if filters.max_price is not None and vehicle["price"] > filters.max_price:
        return False
    if filters.models and vehicle["model"] not in filters.models:
        return False
    return True


def has_explicit_filter(filters: Filters) -> bool:
    return any(
        [
            filters.brand,
            filters.body,
            filters.fuel,
            filters.transmission,
            filters.max_price is not None,
            filters.models,
        ]
    )


def rank_vehicles(query: str, scores: dict[str, float], limit: int = 3) -> list[dict]:
    filters = parse_filters(query)
    if is_out_of_domain(query) and not filters.models and not filters.brand:
        return []

    folded = fold(query)
    ranked: list[tuple[float, dict]] = []
    for vehicle in VEHICLES:
        if not _matches(vehicle, filters):
            continue
        lexical = 0.0
        if fold(vehicle["model"]) in folded:
            lexical += 0.45
        if fold(vehicle["brand"]) in folded:
            lexical += 0.15
        score = scores.get(vehicle["id"], 0.0) + lexical
        ranked.append((score, {**vehicle, "score": round(score, 4)}))

    ranked.sort(key=lambda item: item[0], reverse=True)
    if not ranked or (not has_explicit_filter(filters) and ranked[0][0] < 0.28):
        return _generic_shortlist(query, limit)
    return [vehicle for _, vehicle in ranked[:limit]]


def _generic_shortlist(query: str, limit: int) -> list[dict]:
    folded = fold(query)
    generic_terms = ("carro", "veiculo", "estoque", "melhor", "recomend", "opcao", "comprar")
    if not any(term in folded for term in generic_terms):
        return []
    featured = sorted(VEHICLES, key=decision_score, reverse=True)[:limit]
    return [{**vehicle, "score": 0.0} for vehicle in featured]


def decision_score(vehicle: dict) -> float:
    return (vehicle["year"] - 2020) * 3 - (vehicle["price"] / 20000) - (vehicle["km"] / 15000)
