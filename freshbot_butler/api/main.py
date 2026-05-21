from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

import uvicorn
from fastapi import Depends, FastAPI, File, Header, HTTPException, Request, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from freshbot_butler.api.db import Database
from freshbot_butler.api.schemas import (
    FreshnessOverrideRequest,
    FreshnessPolicyListResponse,
    FreshnessPolicySummary,
    HouseholdSessionRequest,
    HouseholdSessionResponse,
    PackagePhotoConfirmRequest,
    PackagePhotoDraftResponse,
    TextCaptureConfirmRequest,
    TextCaptureConfirmResponse,
    TextCaptureDraftRequest,
    TextCaptureDraftResponse,
    TodayResponse,
    VoiceCaptureDraftResponse,
)
from freshbot_butler.api.services.access import HouseholdAccessService
from freshbot_butler.api.services.freshness_overrides import (
    InvalidSessionError as FreshnessOverrideInvalidSessionError,
)
from freshbot_butler.api.services.freshness_overrides import (
    FreshnessOverrideService,
    UnknownFreshnessCategoryError,
)
from freshbot_butler.api.services.text_capture import InvalidSessionError as TextCaptureInvalidSessionError
from freshbot_butler.api.services.text_capture import TextCaptureService
from freshbot_butler.api.services.transcription import (
    AudioCapture,
    TranscriptionProvider,
    TranscriptionProviderUnavailableError,
    create_transcription_provider,
)
from freshbot_butler.api.services.today import InvalidSessionError, TodayDashboardService
from freshbot_butler.api.services.voice_capture import VoiceCaptureService
from freshbot_butler.api.settings import Settings

try:
    from freshbot_butler.api.services.package_photo import (
        DemoPackagePhotoExtractor,
        LowConfidenceDateRequiresReviewError,
        PackagePhotoCaptureNotFoundError,
        PackagePhotoExtractor,
        PackagePhotoService,
    )
except ModuleNotFoundError:
    DemoPackagePhotoExtractor = None
    LowConfidenceDateRequiresReviewError = Exception
    PackagePhotoCaptureNotFoundError = Exception
    PackagePhotoExtractor = Any
    PackagePhotoService = None


def create_app(
    settings: Settings | None = None,
    transcription_provider: TranscriptionProvider | None = None,
    package_photo_extractor: PackagePhotoExtractor | None = None,
) -> FastAPI:
    app_settings = settings or Settings()
    database = Database(app_settings)
    configured_transcription_provider = transcription_provider or create_transcription_provider(app_settings)
    configured_package_photo_extractor = (
        package_photo_extractor
        if package_photo_extractor is not None
        else DemoPackagePhotoExtractor() if DemoPackagePhotoExtractor is not None else None
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await database.create_schema()
        app.state.database = database
        app.state.settings = app_settings
        app.state.transcription_provider = configured_transcription_provider
        app.state.package_photo_extractor = configured_package_photo_extractor
        yield
        await configured_transcription_provider.aclose()
        await database.dispose()

    app = FastAPI(title="Freshbot Butler API", version="0.1.0", lifespan=lifespan)

    async def get_session(request: Request) -> AsyncSession:
        async with request.app.state.database.session() as session:
            yield session

    @app.get("/api/health", operation_id="getHealth")
    async def healthcheck() -> dict[str, str]:
        return {"status": "ok"}

    @app.post(
        "/api/auth/household-session",
        response_model=HouseholdSessionResponse,
        operation_id="createHouseholdSession",
    )
    async def create_household_session(
        request: Request,
        payload: HouseholdSessionRequest,
        session: AsyncSession = Depends(get_session),
    ) -> HouseholdSessionResponse:
        service = HouseholdAccessService(
            session=session,
            session_token_ttl_hours=request.app.state.settings.session_token_ttl_hours,
        )
        return await service.authenticate(payload)

    @app.get("/api/today", response_model=TodayResponse, operation_id="getTodayDashboard")
    async def get_today(
        request: Request,
        authorization: str | None = Header(default=None),
        session: AsyncSession = Depends(get_session),
    ) -> TodayResponse:
        if authorization is None or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Missing bearer token")
        service = TodayDashboardService(session)
        try:
            return await service.load_for_token(authorization.removeprefix("Bearer ").strip())
        except InvalidSessionError as error:
            raise HTTPException(status_code=401, detail="Invalid session") from error

    @app.get(
        "/api/freshness-overrides",
        response_model=FreshnessPolicyListResponse,
        operation_id="listFreshnessOverrides",
    )
    async def list_freshness_overrides(
        authorization: str | None = Header(default=None),
        session: AsyncSession = Depends(get_session),
    ) -> FreshnessPolicyListResponse:
        if authorization is None or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Missing bearer token")
        service = FreshnessOverrideService(session)
        try:
            return await service.list_for_token(authorization.removeprefix("Bearer ").strip())
        except FreshnessOverrideInvalidSessionError as error:
            raise HTTPException(status_code=401, detail="Invalid session") from error

    @app.put(
        "/api/freshness-overrides/{category}",
        response_model=FreshnessPolicySummary,
        operation_id="saveFreshnessOverride",
    )
    async def save_freshness_override(
        category: str,
        payload: FreshnessOverrideRequest,
        authorization: str | None = Header(default=None),
        session: AsyncSession = Depends(get_session),
    ) -> FreshnessPolicySummary:
        if authorization is None or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Missing bearer token")
        service = FreshnessOverrideService(session)
        try:
            return await service.save_for_token(
                authorization.removeprefix("Bearer ").strip(),
                category,
                payload,
            )
        except FreshnessOverrideInvalidSessionError as error:
            raise HTTPException(status_code=401, detail="Invalid session") from error
        except UnknownFreshnessCategoryError as error:
            raise HTTPException(status_code=404, detail="Unknown freshness category") from error

    @app.post(
        "/api/text-capture/drafts",
        response_model=TextCaptureDraftResponse,
        operation_id="createTextCaptureDrafts",
    )
    async def create_text_capture_drafts(
        payload: TextCaptureDraftRequest,
        authorization: str | None = Header(default=None),
        session: AsyncSession = Depends(get_session),
    ) -> TextCaptureDraftResponse:
        if authorization is None or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Missing bearer token")
        service = TextCaptureService(session)
        try:
            return await service.create_drafts(authorization.removeprefix("Bearer ").strip(), payload)
        except TextCaptureInvalidSessionError as error:
            raise HTTPException(status_code=401, detail="Invalid session") from error

    @app.post(
        "/api/voice-capture/drafts",
        response_model=VoiceCaptureDraftResponse,
        operation_id="createVoiceCaptureDrafts",
    )
    async def create_voice_capture_drafts(
        request: Request,
        audio_file: UploadFile = File(...),
        authorization: str | None = Header(default=None),
        session: AsyncSession = Depends(get_session),
    ) -> VoiceCaptureDraftResponse:
        if authorization is None or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Missing bearer token")
        service = VoiceCaptureService(session, request.app.state.transcription_provider)
        try:
            return await service.create_drafts(
                authorization.removeprefix("Bearer ").strip(),
                AudioCapture(
                    filename=audio_file.filename or "voice-capture.webm",
                    content_type=audio_file.content_type,
                    data=await audio_file.read(),
                ),
            )
        except TextCaptureInvalidSessionError as error:
            raise HTTPException(status_code=401, detail="Invalid session") from error
        except TranscriptionProviderUnavailableError as error:
            raise HTTPException(status_code=503, detail="Transcription provider unavailable") from error

    if PackagePhotoService is not None:

        @app.post(
            "/api/package-photo/drafts",
            response_model=PackagePhotoDraftResponse,
            operation_id="createPackagePhotoDrafts",
        )
        async def create_package_photo_drafts(
            request: Request,
            photo: UploadFile = File(...),
            authorization: str | None = Header(default=None),
            session: AsyncSession = Depends(get_session),
        ) -> PackagePhotoDraftResponse:
            if authorization is None or not authorization.startswith("Bearer "):
                raise HTTPException(status_code=401, detail="Missing bearer token")
            service = PackagePhotoService(session, request.app.state.package_photo_extractor)
            try:
                return await service.create_drafts(
                    authorization.removeprefix("Bearer ").strip(),
                    AudioCapture(
                        filename=photo.filename or "package-photo.jpg",
                        content_type=photo.content_type,
                        data=await photo.read(),
                    ),
                )
            except TextCaptureInvalidSessionError as error:
                raise HTTPException(status_code=401, detail="Invalid session") from error

        @app.get(
            "/api/package-photo/drafts/{capture_id}",
            response_model=PackagePhotoDraftResponse,
            operation_id="getPackagePhotoDrafts",
        )
        async def get_package_photo_drafts(
            request: Request,
            capture_id: str,
            authorization: str | None = Header(default=None),
            session: AsyncSession = Depends(get_session),
        ) -> PackagePhotoDraftResponse:
            if authorization is None or not authorization.startswith("Bearer "):
                raise HTTPException(status_code=401, detail="Missing bearer token")
            service = PackagePhotoService(session, request.app.state.package_photo_extractor)
            try:
                return await service.load_drafts(authorization.removeprefix("Bearer ").strip(), capture_id)
            except TextCaptureInvalidSessionError as error:
                raise HTTPException(status_code=401, detail="Invalid session") from error
            except PackagePhotoCaptureNotFoundError as error:
                raise HTTPException(status_code=404, detail="Package photo draft not found") from error

    @app.post(
        "/api/text-capture/confirm",
        response_model=TextCaptureConfirmResponse,
        response_model_exclude_none=True,
        operation_id="confirmTextCaptureDrafts",
    )
    async def confirm_text_capture_drafts(
        payload: TextCaptureConfirmRequest,
        authorization: str | None = Header(default=None),
        session: AsyncSession = Depends(get_session),
    ) -> TextCaptureConfirmResponse:
        if authorization is None or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Missing bearer token")
        service = TextCaptureService(session)
        try:
            return await service.confirm_drafts(authorization.removeprefix("Bearer ").strip(), payload)
        except TextCaptureInvalidSessionError as error:
            raise HTTPException(status_code=401, detail="Invalid session") from error

    if PackagePhotoService is not None:

        @app.post(
            "/api/package-photo/confirm",
            response_model=TextCaptureConfirmResponse,
            response_model_exclude_none=True,
            operation_id="confirmPackagePhotoDrafts",
        )
        async def confirm_package_photo_drafts(
            request: Request,
            payload: PackagePhotoConfirmRequest,
            authorization: str | None = Header(default=None),
            session: AsyncSession = Depends(get_session),
        ) -> TextCaptureConfirmResponse:
            if authorization is None or not authorization.startswith("Bearer "):
                raise HTTPException(status_code=401, detail="Missing bearer token")
            service = PackagePhotoService(session, request.app.state.package_photo_extractor)
            try:
                return await service.confirm_drafts(authorization.removeprefix("Bearer ").strip(), payload)
            except TextCaptureInvalidSessionError as error:
                raise HTTPException(status_code=401, detail="Invalid session") from error
            except PackagePhotoCaptureNotFoundError as error:
                raise HTTPException(status_code=404, detail="Package photo draft not found") from error
            except LowConfidenceDateRequiresReviewError as error:
                raise HTTPException(status_code=422, detail="Review low-confidence dates before saving") from error

    return app


app = create_app()


def main() -> None:
    settings = Settings()
    uvicorn.run("freshbot_butler.api.main:app", host=settings.host, port=settings.port, reload=False)
