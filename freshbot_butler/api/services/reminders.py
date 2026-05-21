from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from freshbot_butler.api.freshness import build_effective_policies
from freshbot_butler.api.models import Batch, Household, Job, Member, ReminderDelivery, SessionToken, utc_now
from freshbot_butler.api.reminders import (
    ReminderDeliveryPlan,
    ReminderDigest,
    ReminderSettings,
    build_reminder_digest,
    select_reminder_delivery,
)
from freshbot_butler.api.schemas import (
    FreshnessPolicySummary,
    FreshnessSummary,
    ReminderDeliveryPlanSummary,
    ReminderDeliverySummary,
    ReminderDigestItemSummary,
    ReminderDigestSummary,
    ReminderPreviewResponse,
    ReminderSettingsRequest,
    ReminderSettingsSummary,
)
from freshbot_butler.api.services.freshness_overrides import FreshnessOverrideService


class ReminderService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def load_for_token(self, token: str) -> ReminderPreviewResponse:
        context = await self._load_context(token)
        return await self._build_preview(context.household.id, context.household.name, context.member.display_name, context.household.locale)

    async def update_settings_for_token(
        self,
        token: str,
        request: ReminderSettingsRequest,
    ) -> ReminderSettingsSummary:
        context = await self._load_context(token)
        context.household.daily_digest_enabled = request.daily_digest_enabled
        context.household.urgent_push_enabled = request.urgent_push_enabled
        await self._session.commit()
        await self.enqueue_pending_jobs()
        return ReminderSettingsSummary(
            daily_digest_enabled=context.household.daily_digest_enabled,
            urgent_push_enabled=context.household.urgent_push_enabled,
        )

    async def dispatch_for_token(self, token: str) -> ReminderPreviewResponse:
        context = await self._load_context(token)
        preview = await self._build_preview(
            context.household.id,
            context.household.name,
            context.member.display_name,
            context.household.locale,
        )
        if self._enqueue_delivery_jobs(
            context.household.id,
            preview.digest,
            preview.delivery,
            pending_reminder_jobs=set(),
        ):
            await self._session.commit()
        return preview

    async def enqueue_pending_jobs(self) -> int:
        households = (
            await self._session.scalars(
                select(Household).order_by(Household.created_at.asc(), Household.id.asc())
            )
        ).all()
        pending_reminder_jobs = {
            (job.payload.get("household_id"), job.payload.get("kind"), job.payload.get("channel"))
            for job in (
                await self._session.scalars(
                    select(Job).where(Job.status == "pending", Job.queue_name == "reminder-delivery")
                )
            ).all()
            if isinstance(job.payload, dict)
            and isinstance(job.payload.get("household_id"), str)
            and isinstance(job.payload.get("kind"), str)
            and isinstance(job.payload.get("channel"), str)
        }
        enqueued_jobs = 0
        for household in households:
            digest, delivery = await self._build_delivery_plan(household)
            household_jobs = self._enqueue_delivery_jobs(
                household.id,
                digest,
                delivery,
                pending_reminder_jobs=pending_reminder_jobs,
            )
            enqueued_jobs += household_jobs
        if enqueued_jobs:
            await self._session.commit()
        return enqueued_jobs

    async def process_job(self, payload: dict) -> None:
        household_id = payload["household_id"]
        household = await self._session.get(Household, household_id)
        if household is None:
            return

        digest, delivery = await self._build_delivery_plan(household)
        if not digest.urgent_items and not digest.soon_items:
            return

        kind = payload["kind"]
        channel = payload["channel"]
        delivery_payload: dict | list | None = None

        if kind == "daily_digest" and channel == "in_app" and delivery.daily_digest_delivery == "in_app":
            delivery_payload = self._digest_payload(digest)
        elif kind == "urgent_push" and channel == "web_push" and delivery.urgent_push_delivery == "web_push":
            delivery_payload = [self._digest_item_payload(item) for item in delivery.urgent_push_candidates]

        if delivery_payload is None:
            return

        existing_delivery = await self._session.scalars(
            select(ReminderDelivery)
            .where(
                ReminderDelivery.household_id == household_id,
                ReminderDelivery.kind == kind,
                ReminderDelivery.channel == channel,
            )
            .order_by(ReminderDelivery.created_at.desc(), ReminderDelivery.id.desc())
        )
        for delivery_row in existing_delivery:
            if delivery_row.payload == delivery_payload:
                return

        self._session.add(
            ReminderDelivery(
                household_id=household_id,
                kind=kind,
                channel=channel,
                payload=delivery_payload,
            )
        )
        await self._session.flush()

    async def _build_preview(
        self,
        household_id: str,
        household_name: str,
        member_name: str,
        locale: str,
    ) -> ReminderPreviewResponse:
        household = await self._session.get(Household, household_id)
        if household is None:
            raise InvalidSessionError()

        digest, delivery = await self._build_delivery_plan(household)
        settings = ReminderSettings(
            daily_digest_enabled=household.daily_digest_enabled,
            urgent_push_enabled=household.urgent_push_enabled,
        )
        override_map = await FreshnessOverrideService(self._session).load_override_map_for_household(household.id)
        deliveries = await self._load_deliveries(household.id)
        return ReminderPreviewResponse(
            household_name=household_name,
            member_name=member_name,
            locale=locale,
            settings=ReminderSettingsSummary.model_validate(settings.__dict__),
            digest=self._to_digest_summary(digest),
            delivery=self._to_delivery_summary(delivery),
            freshness_policies=[
                FreshnessPolicySummary.model_validate(policy.__dict__)
                for policy in build_effective_policies(override_map)
            ],
            deliveries=[self._to_delivery_record_summary(row) for row in deliveries],
        )

    async def _build_delivery_plan(self, household: Household) -> tuple[ReminderDigest, ReminderDeliveryPlan]:
        override_map = await FreshnessOverrideService(self._session).load_override_map_for_household(household.id)
        batches = (
            await self._session.scalars(
                select(Batch)
                .where(Batch.household_id == household.id)
                .order_by(Batch.created_at.asc(), Batch.id.asc())
            )
        ).all()
        active_batches = [batch for batch in batches if batch.lifecycle_state not in {"depleted", "discarded"}]
        digest = build_reminder_digest(active_batches, today=utc_now().date(), overrides=override_map)
        settings = ReminderSettings(
            daily_digest_enabled=household.daily_digest_enabled,
            urgent_push_enabled=household.urgent_push_enabled,
        )
        delivery = select_reminder_delivery(settings, digest)
        return digest, delivery

    async def _load_context(self, token: str) -> HouseholdContext:
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
        return HouseholdContext(household=household, member=member)

    async def _load_deliveries(self, household_id: str) -> list[ReminderDelivery]:
        rows = await self._session.scalars(
            select(ReminderDelivery)
            .where(ReminderDelivery.household_id == household_id)
            .order_by(ReminderDelivery.created_at.desc(), ReminderDelivery.id.desc())
        )
        return rows.all()[:5]

    def _to_digest_summary(self, digest: ReminderDigest) -> ReminderDigestSummary:
        return ReminderDigestSummary(
            generated_on=digest.generated_on,
            summary=digest.summary,
            urgent_items=[self._to_digest_item_summary(item) for item in digest.urgent_items],
            soon_items=[self._to_digest_item_summary(item) for item in digest.soon_items],
        )

    def _to_delivery_summary(self, delivery: ReminderDeliveryPlan) -> ReminderDeliveryPlanSummary:
        return ReminderDeliveryPlanSummary(
            daily_digest_delivery=delivery.daily_digest_delivery,
            urgent_push_delivery=delivery.urgent_push_delivery,
            urgent_push_candidates=[self._to_digest_item_summary(item) for item in delivery.urgent_push_candidates],
        )

    def _enqueue_delivery_jobs(
        self,
        household_id: str,
        digest: ReminderDigest,
        delivery: ReminderDeliveryPlan,
        *,
        pending_reminder_jobs: set[tuple[str, str, str]],
    ) -> int:
        if not digest.urgent_items and not digest.soon_items:
            return 0

        enqueued_jobs = 0
        if delivery.daily_digest_delivery == "in_app" and (
            household_id,
            "daily_digest",
            "in_app",
        ) not in pending_reminder_jobs:
            self._session.add(
                Job(
                    queue_name="reminder-delivery",
                    payload={
                        "household_id": household_id,
                        "kind": "daily_digest",
                        "channel": "in_app",
                        "payload": self._digest_payload(digest),
                    },
                )
            )
            enqueued_jobs += 1
        if delivery.urgent_push_delivery == "web_push" and (
            household_id,
            "urgent_push",
            "web_push",
        ) not in pending_reminder_jobs:
            self._session.add(
                Job(
                    queue_name="reminder-delivery",
                    payload={
                        "household_id": household_id,
                        "kind": "urgent_push",
                        "channel": "web_push",
                        "payload": [self._digest_item_payload(item) for item in delivery.urgent_push_candidates],
                    },
                )
            )
            enqueued_jobs += 1
        return enqueued_jobs

    def _to_digest_item_summary(self, item) -> ReminderDigestItemSummary:
        return ReminderDigestItemSummary(
            name=item.name,
            quantity=item.quantity,
            category=item.category,
            location=item.location,
            freshness=FreshnessSummary.model_validate(item.freshness.__dict__),
        )

    def _digest_item_payload(self, item) -> dict:
        return {
            "name": item.name,
            "quantity": item.quantity,
            "category": item.category,
            "location": item.location,
            "freshness": {
                "state": item.freshness.state,
                "source": item.freshness.source,
                "due_on": item.freshness.due_on.isoformat(),
                "date_type": item.freshness.date_type,
            },
        }

    def _digest_payload(self, digest: ReminderDigest) -> dict:
        return {
            "generated_on": digest.generated_on.isoformat(),
            "summary": digest.summary,
            "urgent_items": [self._digest_item_payload(item) for item in digest.urgent_items],
            "soon_items": [self._digest_item_payload(item) for item in digest.soon_items],
        }

    def _to_delivery_record_summary(self, delivery: ReminderDelivery) -> ReminderDeliverySummary:
        return ReminderDeliverySummary(
            kind=delivery.kind,
            channel=delivery.channel,
            payload=delivery.payload,
            created_at=delivery.created_at,
            delivered_at=delivery.delivered_at,
        )


@dataclass(frozen=True)
class HouseholdContext:
    household: Household
    member: Member


class InvalidSessionError(Exception):
    pass
