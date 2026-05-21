from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal

from freshbot_butler.api.models import Batch

DateType = Literal["best_before", "use_by"]
FreshnessSource = Literal["exact_date", "category_default", "household_override"]
FreshnessState = Literal["urgent", "soon", "normal"]


@dataclass(frozen=True)
class CategoryFreshnessPolicy:
    shelf_life_days: int
    soon_window_days: int


@dataclass(frozen=True)
class FreshnessAssessment:
    state: FreshnessState
    source: FreshnessSource
    due_on: date
    date_type: DateType | None


@dataclass(frozen=True)
class EffectiveCategoryFreshnessPolicy:
    category: str
    default_shelf_life_days: int
    default_soon_window_days: int
    shelf_life_days: int
    soon_window_days: int
    is_override: bool


DEFAULT_CATEGORY_POLICIES: dict[str, CategoryFreshnessPolicy] = {
    "Molkerei": CategoryFreshnessPolicy(shelf_life_days=7, soon_window_days=3),
    "Obst & Gemüse": CategoryFreshnessPolicy(shelf_life_days=2, soon_window_days=2),
    "Vorrat": CategoryFreshnessPolicy(shelf_life_days=30, soon_window_days=5),
    "Getränke": CategoryFreshnessPolicy(shelf_life_days=14, soon_window_days=4),
    "Sonstiges": CategoryFreshnessPolicy(shelf_life_days=7, soon_window_days=3),
}


def assess_batch_freshness(
    batch: Batch,
    *,
    today: date,
    overrides: dict[str, CategoryFreshnessPolicy] | None = None,
) -> FreshnessAssessment:
    if batch.expires_on is not None:
        return FreshnessAssessment(
            state=_state_for_exact_date(batch.date_type, batch.expires_on, today),
            source="exact_date",
            due_on=batch.expires_on,
            date_type=batch.date_type,
        )

    active_overrides = overrides or {}
    policy = active_overrides.get(batch.category) or DEFAULT_CATEGORY_POLICIES.get(
        batch.category,
        DEFAULT_CATEGORY_POLICIES["Sonstiges"],
    )
    freshness_start = batch.opened_at.date() if batch.opened_at is not None else batch.created_at.date()
    due_on = freshness_start + timedelta(days=policy.shelf_life_days)
    remaining_days = (due_on - today).days
    state: FreshnessState
    if remaining_days <= 0:
        state = "urgent"
    elif remaining_days <= policy.soon_window_days:
        state = "soon"
    else:
        state = "normal"
    return FreshnessAssessment(
        state=state,
        source="household_override" if batch.category in active_overrides else "category_default",
        due_on=due_on,
        date_type=None,
    )


def _state_for_exact_date(date_type: DateType | None, due_on: date, today: date) -> FreshnessState:
    remaining_days = (due_on - today).days
    if date_type == "use_by":
        if remaining_days <= 0:
            return "urgent"
        if remaining_days <= 2:
            return "soon"
        return "normal"

    if remaining_days < 0:
        return "urgent"
    if remaining_days <= 2:
        return "soon"
    return "normal"


def build_effective_policies(
    overrides: dict[str, CategoryFreshnessPolicy] | None = None,
) -> list[EffectiveCategoryFreshnessPolicy]:
    active_overrides = overrides or {}
    return [
        EffectiveCategoryFreshnessPolicy(
            category=category,
            default_shelf_life_days=default_policy.shelf_life_days,
            default_soon_window_days=default_policy.soon_window_days,
            shelf_life_days=active_overrides.get(category, default_policy).shelf_life_days,
            soon_window_days=active_overrides.get(category, default_policy).soon_window_days,
            is_override=category in active_overrides,
        )
        for category, default_policy in sorted(DEFAULT_CATEGORY_POLICIES.items())
    ]
