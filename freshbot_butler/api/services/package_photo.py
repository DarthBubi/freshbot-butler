from __future__ import annotations

import base64
import json
from datetime import datetime, timedelta, timezone
from typing import Protocol

import httpx
from sqlalchemy import select, update
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
from freshbot_butler.api.settings import Settings

AVAILABLE_DATE_TYPES = ["best_before", "use_by"]
RAW_UPLOAD_RETENTION = timedelta(hours=1)


class PackagePhotoExtractor(Protocol):
    async def extract(self, *, filename: str, content_type: str, content: bytes) -> list[dict]:
        ...


class PackagePhotoService:
    def __init__(self, session: AsyncSession, extractor: PackagePhotoExtractor) -> None:
        self._session = session
        self._text_capture = TextCaptureService(session)
        self._extractor = extractor

    async def create_drafts(self, token: str, photo: AudioCapture) -> PackagePhotoDraftResponse:
        if isinstance(self._extractor, UnavailablePackagePhotoExtractor):
            raise PackagePhotoExtractorUnavailableError("Package photo extractor is not configured")
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
        if await self._expire_raw_upload_if_needed(capture):
            await self._session.commit()
        return self._to_response(capture)

    async def confirm_drafts(
        self,
        token: str,
        request: PackagePhotoConfirmRequest,
    ) -> TextCaptureConfirmResponse:
        household = await self._text_capture._load_household_for_token(token)
        capture = await self._load_capture(household.id, request.capture_id)
        if capture.status != "pending_review":
            raise PackagePhotoDraftConfirmationError()

        confirmed_drafts = self._confirmed_drafts_from_capture(capture, request.drafts)
        if any(draft.requires_date_review and not draft.date_reviewed for draft in confirmed_drafts):
            raise LowConfidenceDateRequiresReviewError()
        capture.status = "confirmed"
        capture.extraction_payload = {
            "drafts": [draft.model_dump(mode="json") for draft in confirmed_drafts],
        }
        return await self._text_capture.confirm_drafts(
            token,
            TextCaptureConfirmRequest(drafts=confirmed_drafts),
        )

    async def process_capture(self, capture_id: str) -> None:
        capture = await self._session.get(PackagePhotoCapture, capture_id)
        if capture is None:
            raise PackagePhotoCaptureNotFoundError()
        if capture.status in {"confirmed", "failed"}:
            return
        if (
            capture.raw_upload is not None
            and capture.raw_upload_expires_at is not None
            and _as_utc_naive(capture.raw_upload_expires_at) <= _as_utc_naive(utc_now())
        ):
            result = await self._session.execute(
                update(PackagePhotoCapture)
                .where(
                    PackagePhotoCapture.id == capture_id,
                    PackagePhotoCapture.status == "processing",
                )
                .values(
                    status="failed",
                    raw_upload=None,
                    raw_upload_filename=None,
                    raw_upload_content_type=None,
                    raw_upload_expires_at=None,
                )
            )
            if result.rowcount == 0:
                await self._session.rollback()
                return
            await self._session.commit()
            return

        try:
            extracted_drafts = await self._extractor.extract(
                filename=capture.raw_upload_filename or "package-photo.jpg",
                content_type=capture.raw_upload_content_type or "application/octet-stream",
                content=capture.raw_upload or b"",
            )
        except Exception:
            result = await self._session.execute(
                update(PackagePhotoCapture)
                .where(
                    PackagePhotoCapture.id == capture_id,
                    PackagePhotoCapture.status == "processing",
                )
                .values(status="failed")
            )
            if result.rowcount == 0:
                await self._session.rollback()
                raise
            await self._session.commit()
            raise

        draft_models = [PackagePhotoDraft.model_validate(draft) for draft in extracted_drafts]
        result = await self._session.execute(
            update(PackagePhotoCapture)
            .where(
                PackagePhotoCapture.id == capture_id,
                PackagePhotoCapture.status == "processing",
            )
            .values(
                status="pending_review",
                extraction_payload={"drafts": [draft.model_dump(mode="json") for draft in draft_models]},
                raw_upload=None,
                raw_upload_filename=None,
                raw_upload_content_type=None,
                raw_upload_expires_at=None,
            )
        )
        if result.rowcount == 0:
            await self._session.rollback()
            return
        await self._session.commit()

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

    def _drafts_from_capture(self, capture: PackagePhotoCapture) -> list[PackagePhotoDraft]:
        payload_drafts = capture.extraction_payload.get("drafts", [])
        return [PackagePhotoDraft.model_validate(draft) for draft in payload_drafts]

    async def _expire_raw_upload_if_needed(self, capture: PackagePhotoCapture) -> bool:
        if (
            capture.raw_upload is None
            or capture.raw_upload_expires_at is None
            or _as_utc_naive(capture.raw_upload_expires_at) > _as_utc_naive(utc_now())
        ):
            return False

        capture.raw_upload = None
        capture.raw_upload_filename = None
        capture.raw_upload_content_type = None
        capture.raw_upload_expires_at = None
        if capture.status == "processing":
            capture.status = "failed"
        return True

    def _confirmed_drafts_from_capture(
        self,
        capture: PackagePhotoCapture,
        requested_drafts: list[PackagePhotoDraft],
    ) -> list[PackagePhotoDraft]:
        stored_drafts = self._drafts_from_capture(capture)
        if len(stored_drafts) != len(requested_drafts):
            raise PackagePhotoDraftConfirmationError()

        confirmed_drafts: list[PackagePhotoDraft] = []
        for stored_draft, requested_draft in zip(stored_drafts, requested_drafts):
            if (
                requested_draft.model_dump(mode="json", exclude={"date_reviewed"})
                != stored_draft.model_dump(mode="json", exclude={"date_reviewed"})
            ):
                raise PackagePhotoDraftConfirmationError()
            confirmed_drafts.append(
                stored_draft.model_copy(update={"date_reviewed": requested_draft.date_reviewed})
            )
        return confirmed_drafts

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


class PackagePhotoDraftConfirmationError(Exception):
    pass


class PackagePhotoExtractorUnavailableError(Exception):
    pass


class UnavailablePackagePhotoExtractor:
    async def extract(self, *, filename: str, content_type: str, content: bytes) -> list[dict]:
        raise PackagePhotoExtractorUnavailableError("Package photo extractor is not configured")


class OpenAIPackagePhotoExtractor:
    def __init__(
        self,
        api_key: str | None,
        base_url: str,
        model: str,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._owns_http_client = http_client is None
        self._http_client = http_client or httpx.AsyncClient(base_url=base_url, timeout=30.0)

    async def extract(self, *, filename: str, content_type: str, content: bytes) -> list[dict]:
        if self._api_key is None:
            raise PackagePhotoExtractorUnavailableError("OpenAI API key is not configured")

        response = await self._http_client.post(
            "/chat/completions",
            headers={"Authorization": f"Bearer {self._api_key}"},
            json={
                "model": self._model,
                "response_format": {"type": "json_object"},
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "Extract grocery and household inventory details from package photos. "
                            "Return JSON with a 'drafts' array of package photo drafts."
                        ),
                    },
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": "Identify all visible package items and return structured drafts.",
                            },
                            {
                                "type": "image_url",
                                "image_url": {"url": _data_url(content_type, content)},
                            },
                        ],
                    },
                ],
            },
        )
        response.raise_for_status()
        message_content = response.json()["choices"][0]["message"]["content"]
        if not isinstance(message_content, str):
            raise PackagePhotoExtractorUnavailableError("OpenAI package photo extraction did not return text")
        payload = json.loads(message_content)
        drafts = payload.get("drafts")
        if not isinstance(drafts, list):
            raise PackagePhotoExtractorUnavailableError("OpenAI package photo extraction did not return drafts")
        return drafts

    async def aclose(self) -> None:
        if self._owns_http_client:
            await self._http_client.aclose()


def create_package_photo_extractor(
    settings: Settings,
    http_client: httpx.AsyncClient | None = None,
) -> UnavailablePackagePhotoExtractor | OpenAIPackagePhotoExtractor:
    if settings.package_photo_extractor == "openai":
        if settings.package_photo_openai_api_key is None:
            return UnavailablePackagePhotoExtractor()
        return OpenAIPackagePhotoExtractor(
            api_key=settings.package_photo_openai_api_key,
            base_url=settings.package_photo_openai_base_url,
            model=settings.package_photo_openai_model,
            http_client=http_client,
        )
    return UnavailablePackagePhotoExtractor()


def _data_url(content_type: str | None, content: bytes) -> str:
    mime_type = content_type or "application/octet-stream"
    encoded = base64.b64encode(content).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def _as_utc_naive(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)
