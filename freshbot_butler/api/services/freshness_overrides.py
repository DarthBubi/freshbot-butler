from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from freshbot_butler.api.freshness import (
    CategoryFreshnessPolicy,
    DEFAULT_CATEGORY_POLICIES,
    build_effective_policies,
)
from freshbot_butler.api.models import FreshnessOverride, Household, Member, SessionToken, utc_now
from freshbot_butler.api.schemas import (
    FreshnessOverrideRequest,
    FreshnessPolicyListResponse,
    FreshnessPolicySummary,
)


class FreshnessOverrideService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_for_token(self, token: str) -> FreshnessPolicyListResponse:
        household = await self._load_household_for_token(token)
        overrides = await self._load_overrides(household.id)
        return FreshnessPolicyListResponse(
            policies=[FreshnessPolicySummary.model_validate(policy.__dict__) for policy in build_effective_policies(overrides)]
        )

    async def save_for_token(
        self,
        token: str,
        category: str,
        request: FreshnessOverrideRequest,
    ) -> FreshnessPolicySummary:
        household = await self._load_household_for_token(token)
        normalized_category = normalize_freshness_category(category)
        override = await self._session.scalar(
            select(FreshnessOverride).where(
                FreshnessOverride.household_id == household.id,
                FreshnessOverride.category == normalized_category,
            )
        )
        if override is None:
            override = FreshnessOverride(
                household_id=household.id,
                category=normalized_category,
                shelf_life_days=request.shelf_life_days,
                soon_window_days=request.soon_window_days,
            )
            self._session.add(override)
        else:
            override.shelf_life_days = request.shelf_life_days
            override.soon_window_days = request.soon_window_days

        await self._session.commit()

        for policy in build_effective_policies(
            {normalized_category: CategoryFreshnessPolicy(request.shelf_life_days, request.soon_window_days)}
        ):
            if policy.category == normalized_category:
                return FreshnessPolicySummary.model_validate(policy.__dict__)
        raise UnknownFreshnessCategoryError()

    async def load_override_map_for_household(self, household_id: str) -> dict[str, CategoryFreshnessPolicy]:
        return await self._load_overrides(household_id)

    async def _load_household_for_token(self, token: str) -> Household:
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
        return household

    async def _load_overrides(self, household_id: str) -> dict[str, CategoryFreshnessPolicy]:
        records = (
            await self._session.scalars(
                select(FreshnessOverride)
                .where(FreshnessOverride.household_id == household_id)
                .order_by(FreshnessOverride.category.asc())
            )
        ).all()
        return {
            record.category: CategoryFreshnessPolicy(
                shelf_life_days=record.shelf_life_days,
                soon_window_days=record.soon_window_days,
            )
            for record in records
        }


def normalize_freshness_category(category: str) -> str:
    normalized = category.strip()
    if normalized not in DEFAULT_CATEGORY_POLICIES:
        raise UnknownFreshnessCategoryError()
    return normalized


class InvalidSessionError(Exception):
    pass


class UnknownFreshnessCategoryError(Exception):
    pass
