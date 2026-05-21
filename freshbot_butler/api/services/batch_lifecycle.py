from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from freshbot_butler.api.freshness import assess_batch_freshness
from freshbot_butler.api.models import Batch, BatchEvent, Household, Member, SessionToken, utc_now
from freshbot_butler.api.schemas import (
    BatchLifecycleActionRequest,
    BatchLifecycleEventListResponse,
    BatchLifecycleEventSummary,
    BatchLifecycleListResponse,
    BatchLifecycleSummary,
    BatchMergeSuggestion,
    FreshnessSummary,
)
from freshbot_butler.api.services.batch_quantities import is_countable_quantity, parse_quantity, render_quantity
from freshbot_butler.api.services.freshness_overrides import FreshnessOverrideService
from freshbot_butler.api.services.shopping_lists import ShoppingListService


ACTION_TO_EVENT = {
    "open": "opened",
    "decrement": "decremented",
    "use_up": "used_up",
    "discard": "discarded",
}


@dataclass(frozen=True)
class HouseholdContext:
    household: Household
    member: Member


class BatchLifecycleService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_for_token(self, token: str) -> BatchLifecycleListResponse:
        context = await self._load_context(token)
        batches = (
            await self._session.scalars(
                select(Batch)
                .where(Batch.household_id == context.household.id)
                .order_by(Batch.created_at.asc(), Batch.id.asc())
            )
        ).all()
        overrides = await FreshnessOverrideService(self._session).load_override_map_for_household(context.household.id)
        summaries = [await self._to_summary(batch, today=utc_now().date(), overrides=overrides) for batch in batches]
        return BatchLifecycleListResponse(
            batches=summaries,
            merge_suggestions=self._build_merge_suggestions(summaries),
        )

    async def load_events_for_token(self, token: str, batch_id: str) -> BatchLifecycleEventListResponse:
        context = await self._load_context(token)
        batch = await self._load_batch(context.household.id, batch_id)
        return BatchLifecycleEventListResponse(events=await self._load_events(batch.id))

    async def act_for_token(self, token: str, batch_id: str, request: BatchLifecycleActionRequest) -> BatchLifecycleSummary:
        context = await self._load_context(token)
        batch = await self._load_batch(context.household.id, batch_id)
        before = batch.quantity
        self._apply_action(batch, request.action)
        after = batch.quantity
        event = BatchEvent(
            household_id=context.household.id,
            batch_id=batch.id,
            member_id=context.member.id,
            action=ACTION_TO_EVENT[request.action],
            quantity_before=before,
            quantity_after=after,
        )
        self._session.add(event)
        await self._session.flush()
        await ShoppingListService(self._session).record_replenishment_suggestion(context.household.id, batch, event)
        await self._session.commit()
        from freshbot_butler.api.services.reminders import ReminderService

        await ReminderService(self._session).enqueue_pending_jobs()
        overrides = await FreshnessOverrideService(self._session).load_override_map_for_household(context.household.id)
        return await self._to_summary(batch, today=utc_now().date(), overrides=overrides)

    async def _load_context(self, token: str) -> HouseholdContext:
        session_token = await self._session.scalar(
            select(SessionToken).where(
                SessionToken.token == token,
                SessionToken.expires_at > utc_now(),
            )
        )
        if session_token is None:
            raise InvalidBatchSessionError()

        member = await self._session.get(Member, session_token.member_id)
        if member is None:
            raise InvalidBatchSessionError()

        household = await self._session.get(Household, member.household_id)
        if household is None:
            raise InvalidBatchSessionError()
        return HouseholdContext(household=household, member=member)

    async def _load_batch(self, household_id: str, batch_id: str) -> Batch:
        batch = await self._session.scalar(
            select(Batch).where(Batch.id == batch_id, Batch.household_id == household_id)
        )
        if batch is None:
            raise UnknownBatchError()
        return batch

    async def _load_events(self, batch_id: str) -> list[BatchLifecycleEventSummary]:
        rows = await self._session.execute(
            select(BatchEvent, Member.display_name)
            .join(Member, Member.id == BatchEvent.member_id)
            .where(BatchEvent.batch_id == batch_id)
            .order_by(BatchEvent.created_at.asc(), BatchEvent.id.asc())
        )
        return [
            BatchLifecycleEventSummary(
                action=row.BatchEvent.action,
                quantity_before=row.BatchEvent.quantity_before,
                quantity_after=row.BatchEvent.quantity_after,
                created_at=row.BatchEvent.created_at,
                member_name=row.display_name,
            )
            for row in rows
        ]

    async def _to_summary(
        self,
        batch: Batch,
        *,
        today: date,
        overrides: dict[str, object],
    ) -> BatchLifecycleSummary:
        freshness = assess_batch_freshness(batch, today=today, overrides=overrides)
        return BatchLifecycleSummary(
            id=batch.id,
            name=batch.name,
            quantity=batch.quantity,
            category=batch.category,
            location=batch.location,
            state=batch.lifecycle_state,
            freshness=FreshnessSummary.model_validate(freshness.__dict__),
            events=await self._load_events(batch.id),
        )

    def _apply_action(self, batch: Batch, action: str) -> None:
        if action == "open":
            if batch.lifecycle_state not in {"sealed", "opened"}:
                raise InvalidBatchActionError()
            batch.lifecycle_state = "opened"
            if batch.opened_at is None:
                batch.opened_at = utc_now()
            return

        amount, unit = self._effective_quantity(batch)
        if action == "decrement":
            if not is_countable_quantity(amount, unit) or amount is None or amount <= 0:
                raise InvalidBatchActionError()
            if batch.lifecycle_state == "sealed":
                batch.lifecycle_state = "opened"
                batch.opened_at = batch.opened_at or utc_now()
            next_amount = amount - 1
            batch.quantity_amount = next_amount
            batch.quantity_unit = unit
            batch.quantity = render_quantity(next_amount, unit, batch.quantity)
            if next_amount == 0:
                batch.lifecycle_state = "depleted"
            return

        if action == "use_up":
            if batch.lifecycle_state in {"depleted", "discarded"}:
                raise InvalidBatchActionError()
            next_amount = 0 if amount is not None else None
            batch.quantity_amount = next_amount
            batch.quantity_unit = unit
            batch.quantity = render_quantity(next_amount, unit, batch.quantity)
            batch.lifecycle_state = "depleted"
            return

        if action == "discard":
            if batch.lifecycle_state in {"depleted", "discarded"}:
                raise InvalidBatchActionError()
            batch.lifecycle_state = "discarded"
            return

        raise InvalidBatchActionError()

    def _effective_quantity(self, batch: Batch) -> tuple[int | None, str | None]:
        if batch.quantity_amount is not None or batch.quantity_unit is not None:
            return batch.quantity_amount, batch.quantity_unit
        amount, unit = parse_quantity(batch.quantity)
        return amount, unit

    def _build_merge_suggestions(self, batches: list[BatchLifecycleSummary]) -> list[BatchMergeSuggestion]:
        grouped: dict[tuple[str, str, str], list[BatchLifecycleSummary]] = defaultdict(list)
        for batch in batches:
            if batch.state in {"depleted", "discarded"}:
                continue
            grouped[(batch.name, batch.category, batch.location)].append(batch)

        suggestions: list[BatchMergeSuggestion] = []
        for (name, category, location), duplicates in grouped.items():
            if len(duplicates) < 2:
                continue
            suggestions.append(
                BatchMergeSuggestion(
                    batch_ids=[batch.id for batch in duplicates],
                    name=name,
                    category=category,
                    location=location,
                    count=len(duplicates),
                )
            )
        return suggestions


class InvalidBatchSessionError(Exception):
    pass


class UnknownBatchError(Exception):
    pass


class InvalidBatchActionError(Exception):
    pass
