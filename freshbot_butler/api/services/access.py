from __future__ import annotations

import re
import secrets
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from freshbot_butler.api.models import Household, Job, Member, SessionToken, utc_now
from freshbot_butler.api.schemas import HouseholdSessionRequest, HouseholdSessionResponse


class HouseholdAccessService:
    def __init__(self, session: AsyncSession, session_token_ttl_hours: int) -> None:
        self._session = session
        self._session_token_ttl_hours = session_token_ttl_hours

    async def authenticate(self, request: HouseholdSessionRequest) -> HouseholdSessionResponse:
        household = await self._find_or_create_household(request.household_name)
        member = await self._find_or_create_member(household.id, request.member_name)
        token = secrets.token_urlsafe(24)
        self._session.add(
            SessionToken(
                member_id=member.id,
                token=token,
                expires_at=utc_now() + timedelta(hours=self._session_token_ttl_hours),
            )
        )
        self._session.add(
            Job(
                queue_name="member-joined",
                payload={"household_id": household.id, "member_id": member.id},
            )
        )
        await self._session.commit()
        return HouseholdSessionResponse(
            token=token,
            locale=household.locale,
            household={"name": household.name, "slug": household.slug},
            member={"display_name": member.display_name},
        )

    async def _find_or_create_household(self, household_name: str) -> Household:
        slug = slugify(household_name)
        household = await self._session.scalar(select(Household).where(Household.slug == slug))
        if household is not None:
            return household
        household = Household(slug=slug, name=household_name.strip())
        self._session.add(household)
        await self._session.flush()
        return household

    async def _find_or_create_member(self, household_id: str, member_name: str) -> Member:
        normalized_name = normalize_name(member_name)
        member = await self._session.scalar(
            select(Member).where(
                Member.household_id == household_id,
                Member.normalized_name == normalized_name,
            )
        )
        if member is not None:
            return member
        member = Member(
            household_id=household_id,
            display_name=member_name.strip(),
            normalized_name=normalized_name,
        )
        self._session.add(member)
        await self._session.flush()
        return member


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().lower())
    return slug.strip("-") or "haushalt"


def normalize_name(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().casefold())
