from __future__ import annotations

import re

COUNTABLE_UNITS = {
    "packung",
    "packungen",
    "karton",
    "kartons",
    "flasche",
    "flaschen",
    "stück",
    "stücke",
    "dose",
    "dosen",
}


def parse_quantity(quantity: str) -> tuple[int | None, str | None]:
    match = re.fullmatch(r"\s*(\d+)(?:[.,]0+)?\s*(.*?)\s*", quantity)
    if match is None:
        return None, None

    amount = int(match.group(1))
    unit = normalize_unit(match.group(2))
    return amount, unit


def is_countable_quantity(amount: int | None, unit: str | None) -> bool:
    if amount is None:
        return False
    if unit is None:
        return True
    return unit.casefold() in COUNTABLE_UNITS


def render_quantity(amount: int | None, unit: str | None, fallback: str) -> str:
    if amount is None:
        return fallback
    if unit is None:
        return str(amount)
    if amount == 1:
        unit = singularize_unit(unit)
    return f"{amount} {unit}"


def normalize_unit(value: str) -> str | None:
    normalized = re.sub(r"\s+", " ", value.strip())
    return normalized or None


def singularize_unit(value: str) -> str:
    normalized = value.casefold()
    if normalized == "packungen":
        return "Packung"
    if normalized == "kartons":
        return "Karton"
    if normalized == "flaschen":
        return "Flasche"
    if normalized == "stücke":
        return "Stück"
    if normalized == "dosen":
        return "Dose"
    return value
