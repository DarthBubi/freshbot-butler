from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from freshbot_butler.api.freshness import assess_batch_freshness
from freshbot_butler.api.models import Batch, Household, Member, SessionToken, utc_now
from freshbot_butler.api.schemas import BatchSummary, FreshnessSummary, TodayResponse, TodaySections
from freshbot_butler.api.services.freshness_overrides import FreshnessOverrideService


class TodayDashboardService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def load_for_token(self, token: str) -> TodayResponse:
        session_token = await self._session.scalar(
            select(SessionToken).where(
                SessionToken.token == token,
                SessionToken.expires_at > utc_now(),
            )
        )
        if session_token is None:
            raise InvalidSessionError()

        member = await self._session.get(Member, session_token.member_id)
        if member is None:
            raise InvalidSessionError()

        household = await self._session.get(Household, member.household_id)
        if household is None:
            raise InvalidSessionError()

        inventory = (
            await self._session.scalars(
                select(Batch)
                .where(Batch.household_id == household.id)
                .order_by(Batch.created_at.asc(), Batch.id.asc())
            )
        ).all()
        override_map = await FreshnessOverrideService(self._session).load_override_map_for_household(household.id)
        inventory_items = [
            self._to_batch_summary(batch, today=utc_now().date(), overrides=override_map) for batch in inventory
        ]

        return TodayResponse(
            household_name=household.name,
            member_name=member.display_name,
            locale=household.locale,
            sections=TodaySections(
                inventory=inventory_items,
                needs_attention=[item for item in inventory_items if item.freshness and item.freshness.state == "urgent"],
                upcoming=[item for item in inventory_items if item.freshness and item.freshness.state == "soon"],
            ),
        )

    def _to_batch_summary(
        self,
        batch: Batch,
        *,
        today: date,
        overrides: dict[str, object],
    ) -> BatchSummary:
        freshness = assess_batch_freshness(batch, today=today, overrides=overrides)
        return BatchSummary(
            name=batch.name,
            quantity=batch.quantity,
            category=batch.category,
            location=batch.location,
            freshness=FreshnessSummary.model_validate(freshness.__dict__),
        )


class InvalidSessionError(Exception):
    pass
