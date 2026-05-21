from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal, Sequence

from freshbot_butler.api.freshness import CategoryFreshnessPolicy, FreshnessAssessment, assess_batch_freshness
from freshbot_butler.api.models import Batch


@dataclass(frozen=True)
class ReminderDigestItem:
    name: str
    quantity: str
    category: str
    location: str
    freshness: FreshnessAssessment


@dataclass(frozen=True)
class ReminderDigest:
    generated_on: date
    urgent_items: list[ReminderDigestItem]
    soon_items: list[ReminderDigestItem]
    summary: str


@dataclass(frozen=True)
class ReminderSettings:
    daily_digest_enabled: bool
    urgent_push_enabled: bool


@dataclass(frozen=True)
class ReminderDeliveryPlan:
    daily_digest_delivery: Literal["in_app", "quiet"]
    urgent_push_delivery: Literal["web_push", "quiet"]
    urgent_push_candidates: list[ReminderDigestItem]


def build_reminder_digest(
    batches: Sequence[Batch],
    *,
    today: date,
    overrides: dict[str, CategoryFreshnessPolicy] | None = None,
) -> ReminderDigest:
    assessments: list[tuple[Batch, FreshnessAssessment]] = [
        (batch, assess_batch_freshness(batch, today=today, overrides=overrides)) for batch in batches
    ]

    urgent_items = [
        _to_digest_item(batch, assessment)
        for batch, assessment in assessments
        if assessment.state == "urgent"
    ]
    soon_items = [
        _to_digest_item(batch, assessment)
        for batch, assessment in assessments
        if assessment.state == "soon"
    ]
    urgent_items.sort(key=_digest_sort_key)
    soon_items.sort(key=_digest_sort_key)

    return ReminderDigest(
        generated_on=today,
        urgent_items=urgent_items,
        soon_items=soon_items,
        summary=_render_summary(len(urgent_items), len(soon_items)),
    )


def select_reminder_delivery(settings: ReminderSettings, digest: ReminderDigest) -> ReminderDeliveryPlan:
    urgent_push_candidates = digest.urgent_items if settings.urgent_push_enabled and digest.urgent_items else []
    return ReminderDeliveryPlan(
        daily_digest_delivery="in_app" if settings.daily_digest_enabled else "quiet",
        urgent_push_delivery="web_push" if urgent_push_candidates else "quiet",
        urgent_push_candidates=urgent_push_candidates,
    )


def _to_digest_item(batch: Batch, assessment: FreshnessAssessment) -> ReminderDigestItem:
    return ReminderDigestItem(
        name=batch.name,
        quantity=batch.quantity,
        category=batch.category,
        location=batch.location,
        freshness=assessment,
    )


def _digest_sort_key(item: ReminderDigestItem) -> tuple[date, str, str, str]:
    return (item.freshness.due_on, item.name, item.category, item.location)


def _render_summary(urgent_count: int, soon_count: int) -> str:
    if urgent_count == 0 and soon_count == 0:
        return "Keine Frischehinweise heute"

    parts: list[str] = []
    if urgent_count:
        parts.append(f"{urgent_count} dringende")
    if soon_count:
        parts.append(f"{soon_count} baldige")
    return f"{' und '.join(parts)} Frischehinweise"
