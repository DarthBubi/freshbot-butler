from __future__ import annotations

from datetime import timedelta, timezone
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from freshbot_butler.api.models import Job, PackagePhotoCapture, utc_now
from freshbot_butler.api.schemas import (
    PackagePhotoConfirmRequest,
    PackagePhotoDraft,
    PackagePhotoDraftResponse,
    TextCaptureConfirmRequest,
    TextCaptureConfirmResponse,
)
from freshbot_butler.api.services.text_capture import (
    AVAILABLE_CATEGORIES,
    AVAILABLE_LOCATIONS,
    TextCaptureService,
)
from freshbot_butler.api.services.transcription import AudioCapture

AVAILABLE_DATE_TYPES = ["best_before", "use_by"]
RAW_UPLOAD_RETENTION = timedelta(hours=1)


class PackagePhotoExtractor(Protocol):
    async def extract(self, *, filename: str, content_type: str, content: bytes) -> list[dict]:
        ...


class DemoPackagePhotoExtractor:
    async def extract(self, *, filename: str, content_type: str, content: bytes) -> list[dict]:
        return [
            {
                "name": "Unbekanntes Produkt",
                "quantity": "1 Packung",
                "category": "Sonstiges",
                "location": "Vorratsschrank",
                "requires_date_review": False,
            }
        ]


class PackagePhotoService:
    def __init__(self, session: AsyncSession, extractor: PackagePhotoExtractor) -> None:
        self._session = session
        self._text_capture = TextCaptureService(session)
        self._extractor = extractor

    async def create_drafts(self, token: str, photo: AudioCapture) -> PackagePhotoDraftResponse:
        household = await self._text_capture._load_household_for_token(token)
        capture = PackagePhotoCapture(
            household_id=household.id,
            status="processing",
            extraction_payload={},
            raw_upload=photo.data,
            raw_upload_filename=photo.filename,
            raw_upload_content_type=photo.content_type,
            raw_upload_expires_at=utc_now() + RAW_UPLOAD_RETENTION,
        )
        self._session.add(capture)
        await self._session.flush()
        self._session.add(
            Job(
                queue_name="package-photo-extraction",
                payload={"capture_id": capture.id},
            )
        )
        await self._session.commit()
        return self._to_response(capture)

    async def load_drafts(self, token: str, capture_id: str) -> PackagePhotoDraftResponse:
        household = await self._text_capture._load_household_for_token(token)
        capture = await self._load_capture(household.id, capture_id)
        await self._discard_expired_raw_uploads(capture)
        return self._to_response(capture)

    async def confirm_drafts(
        self,
        token: str,
        request: PackagePhotoConfirmRequest,
    ) -> TextCaptureConfirmResponse:
        household = await self._text_capture._load_household_for_token(token)
        capture = await self._load_capture(household.id, request.capture_id)
        await self._discard_expired_raw_uploads(capture)
        if any(draft.requires_date_review and not draft.date_reviewed for draft in request.drafts):
            raise LowConfidenceDateRequiresReviewError()
        capture.status = "confirmed"
        capture.raw_upload = None
        capture.raw_upload_filename = None
        capture.raw_upload_content_type = None
        capture.raw_upload_expires_at = None
        capture.extraction_payload = {
            "drafts": [draft.model_dump(mode="json") for draft in request.drafts],
        }
        return await self._text_capture.confirm_drafts(
            token,
            TextCaptureConfirmRequest(drafts=request.drafts),
        )

    async def process_capture(self, capture_id: str) -> None:
        capture = await self._session.get(PackagePhotoCapture, capture_id)
        if capture is None:
            raise PackagePhotoCaptureNotFoundError()
        draft_models = [
            PackagePhotoDraft.model_validate(draft)
            for draft in await self._extractor.extract(
                filename=capture.raw_upload_filename or "package-photo.jpg",
                content_type=capture.raw_upload_content_type or "application/octet-stream",
                content=capture.raw_upload or b"",
            )
        ]
        capture.status = "pending_review"
        capture.extraction_payload = {"drafts": [draft.model_dump(mode="json") for draft in draft_models]}

    async def _load_capture(self, household_id: str, capture_id: str) -> PackagePhotoCapture:
        capture = await self._session.scalar(
            select(PackagePhotoCapture).where(
                PackagePhotoCapture.id == capture_id,
                PackagePhotoCapture.household_id == household_id,
            )
        )
        if capture is None:
            raise PackagePhotoCaptureNotFoundError()
        return capture

    async def _discard_expired_raw_uploads(self, capture: PackagePhotoCapture) -> None:
        if capture.raw_upload_expires_at is None or capture.raw_upload is None:
            return
        raw_upload_expires_at = capture.raw_upload_expires_at
        if raw_upload_expires_at.tzinfo is None:
            raw_upload_expires_at = raw_upload_expires_at.replace(tzinfo=timezone.utc)
        if raw_upload_expires_at > utc_now():
            return
        capture.raw_upload = None
        capture.raw_upload_filename = None
        capture.raw_upload_content_type = None
        capture.raw_upload_expires_at = None
        await self._session.commit()

    def _drafts_from_capture(self, capture: PackagePhotoCapture) -> list[PackagePhotoDraft]:
        payload_drafts = capture.extraction_payload.get("drafts", [])
        return [PackagePhotoDraft.model_validate(draft) for draft in payload_drafts]

    def _to_response(self, capture: PackagePhotoCapture) -> PackagePhotoDraftResponse:
        return PackagePhotoDraftResponse(
            capture_id=capture.id,
            status=capture.status,
            drafts=self._drafts_from_capture(capture),
            available_categories=AVAILABLE_CATEGORIES,
            available_locations=AVAILABLE_LOCATIONS,
            available_date_types=AVAILABLE_DATE_TYPES,
        )


class LowConfidenceDateRequiresReviewError(Exception):
    pass


class PackagePhotoCaptureNotFoundError(Exception):
    pass
