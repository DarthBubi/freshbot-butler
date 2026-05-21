from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

import uvicorn
from fastapi import Depends, FastAPI, File, Header, HTTPException, Request, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from freshbot_butler.api.db import Database
from freshbot_butler.api.schemas import (
    BatchLifecycleActionRequest,
    BatchLifecycleEventListResponse,
    BatchLifecycleListResponse,
    BatchLifecycleSummary,
    FreshnessOverrideRequest,
    FreshnessPolicyListResponse,
    FreshnessPolicySummary,
    HouseholdSessionRequest,
    HouseholdSessionResponse,
    PackagePhotoConfirmRequest,
    PackagePhotoDraftResponse,
    ShoppingListItemRequest,
    ShoppingListRequest,
    ShoppingListsResponse,
    ShoppingSuggestionAcceptRequest,
    KitchenAssistantQueryRequest,
    KitchenAssistantQueryResponse,
    ReminderPreviewResponse,
    ReminderSettingsRequest,
    ReminderSettingsSummary,
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
from freshbot_butler.api.services.kitchen_assistant import KitchenAssistantService
from freshbot_butler.api.services.batch_lifecycle import (
    BatchLifecycleService,
    InvalidBatchActionError,
    InvalidBatchSessionError,
    UnknownBatchError,
)
from freshbot_butler.api.services.transcription import (
    AudioCapture,
    TranscriptionProvider,
    TranscriptionProviderUnavailableError,
    create_transcription_provider,
)
from freshbot_butler.api.services.today import InvalidSessionError, TodayDashboardService
from freshbot_butler.api.services.reminders import InvalidSessionError as ReminderInvalidSessionError
from freshbot_butler.api.services.reminders import ReminderService
from freshbot_butler.api.services.voice_capture import VoiceCaptureService
from freshbot_butler.api.settings import Settings
from freshbot_butler.api.services.shopping_lists import (
    InvalidShoppingListSessionError,
    ShoppingListService,
    UnknownShoppingListError,
    UnknownShoppingSuggestionError,
)
from freshbot_butler.api.services.package_photo import (
    LowConfidenceDateRequiresReviewError,
    PackagePhotoCaptureNotFoundError,
    PackagePhotoDraftConfirmationError,
    PackagePhotoExtractorUnavailableError,
    PackagePhotoService,
    create_package_photo_extractor,
)


def create_app(
    settings: Settings | None = None,
    transcription_provider: TranscriptionProvider | None = None,
    package_photo_extractor: Any | None = None,
) -> FastAPI:
    app_settings = settings or Settings()
    database = Database(app_settings)
    configured_transcription_provider = transcription_provider or create_transcription_provider(app_settings)
    configured_package_photo_extractor = (
        package_photo_extractor
        if package_photo_extractor is not None
        else create_package_photo_extractor(app_settings)
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await database.create_schema()
        try:
            app.state.database = database
            app.state.settings = app_settings
            app.state.transcription_provider = configured_transcription_provider
            app.state.package_photo_extractor = configured_package_photo_extractor
            yield
        finally:
            await configured_transcription_provider.aclose()
            if hasattr(configured_package_photo_extractor, "aclose"):
                await configured_package_photo_extractor.aclose()
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
        "/api/shopping-lists",
        response_model=ShoppingListsResponse,
        operation_id="listShoppingLists",
    )
    async def list_shopping_lists(
        authorization: str | None = Header(default=None),
        session: AsyncSession = Depends(get_session),
    ) -> ShoppingListsResponse:
        if authorization is None or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Missing bearer token")
        service = ShoppingListService(session)
        try:
            return await service.list_for_token(authorization.removeprefix("Bearer ").strip())
        except InvalidShoppingListSessionError as error:
            raise HTTPException(status_code=401, detail="Invalid session") from error

    @app.post(
        "/api/shopping-lists",
        response_model=ShoppingListsResponse,
        operation_id="createShoppingList",
    )
    async def create_shopping_list(
        payload: ShoppingListRequest,
        authorization: str | None = Header(default=None),
        session: AsyncSession = Depends(get_session),
    ) -> ShoppingListsResponse:
        if authorization is None or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Missing bearer token")
        service = ShoppingListService(session)
        try:
            return await service.create_list(authorization.removeprefix("Bearer ").strip(), payload)
        except InvalidShoppingListSessionError as error:
            raise HTTPException(status_code=401, detail="Invalid session") from error

    @app.put(
        "/api/shopping-lists/{list_id}",
        response_model=ShoppingListsResponse,
        operation_id="renameShoppingList",
    )
    async def rename_shopping_list(
        list_id: str,
        payload: ShoppingListRequest,
        authorization: str | None = Header(default=None),
        session: AsyncSession = Depends(get_session),
    ) -> ShoppingListsResponse:
        if authorization is None or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Missing bearer token")
        service = ShoppingListService(session)
        try:
            return await service.rename_list(authorization.removeprefix("Bearer ").strip(), list_id, payload)
        except InvalidShoppingListSessionError as error:
            raise HTTPException(status_code=401, detail="Invalid session") from error
        except UnknownShoppingListError as error:
            raise HTTPException(status_code=404, detail="Shopping list not found") from error

    @app.post(
        "/api/shopping-lists/{list_id}/items",
        response_model=ShoppingListsResponse,
        operation_id="upsertShoppingListItem",
    )
    async def upsert_shopping_list_item(
        list_id: str,
        payload: ShoppingListItemRequest,
        authorization: str | None = Header(default=None),
        session: AsyncSession = Depends(get_session),
    ) -> ShoppingListsResponse:
        if authorization is None or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Missing bearer token")
        service = ShoppingListService(session)
        try:
            return await service.upsert_item(authorization.removeprefix("Bearer ").strip(), list_id, payload)
        except InvalidShoppingListSessionError as error:
            raise HTTPException(status_code=401, detail="Invalid session") from error
        except UnknownShoppingListError as error:
            raise HTTPException(status_code=404, detail="Shopping list not found") from error

    @app.delete(
        "/api/shopping-lists/{list_id}/items/{item_id}",
        response_model=ShoppingListsResponse,
        operation_id="removeShoppingListItem",
    )
    async def remove_shopping_list_item(
        list_id: str,
        item_id: str,
        authorization: str | None = Header(default=None),
        session: AsyncSession = Depends(get_session),
    ) -> ShoppingListsResponse:
        if authorization is None or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Missing bearer token")
        service = ShoppingListService(session)
        try:
            return await service.remove_item(authorization.removeprefix("Bearer ").strip(), list_id, item_id)
        except InvalidShoppingListSessionError as error:
            raise HTTPException(status_code=401, detail="Invalid session") from error
        except UnknownShoppingListError as error:
            raise HTTPException(status_code=404, detail="Shopping list not found") from error

    @app.post(
        "/api/shopping-suggestions/{suggestion_id}/accept",
        response_model=ShoppingListsResponse,
        operation_id="acceptShoppingSuggestion",
    )
    async def accept_shopping_suggestion(
        suggestion_id: str,
        payload: ShoppingSuggestionAcceptRequest,
        authorization: str | None = Header(default=None),
        session: AsyncSession = Depends(get_session),
    ) -> ShoppingListsResponse:
        if authorization is None or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Missing bearer token")
        service = ShoppingListService(session)
        try:
            return await service.accept_suggestion(authorization.removeprefix("Bearer ").strip(), suggestion_id, payload)
        except InvalidShoppingListSessionError as error:
            raise HTTPException(status_code=401, detail="Invalid session") from error
        except UnknownShoppingListError as error:
            raise HTTPException(status_code=404, detail="Shopping list not found") from error
        except UnknownShoppingSuggestionError as error:
            raise HTTPException(status_code=404, detail="Shopping suggestion not found") from error

    @app.post(
        "/api/kitchen-assistant/query",
        response_model=KitchenAssistantQueryResponse,
        operation_id="queryKitchenAssistant",
    )
    async def query_kitchen_assistant(
        payload: KitchenAssistantQueryRequest,
        authorization: str | None = Header(default=None),
        session: AsyncSession = Depends(get_session),
    ) -> KitchenAssistantQueryResponse:
        if authorization is None or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Missing bearer token")
        service = KitchenAssistantService(session)
        try:
            return await service.query_for_token(authorization.removeprefix("Bearer ").strip(), payload)
        except InvalidSessionError as error:
            raise HTTPException(status_code=401, detail="Invalid session") from error

    @app.get(
        "/api/batches",
        response_model=BatchLifecycleListResponse,
        operation_id="listBatches",
    )
    async def list_batches(
        authorization: str | None = Header(default=None),
        session: AsyncSession = Depends(get_session),
    ) -> BatchLifecycleListResponse:
        if authorization is None or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Missing bearer token")
        service = BatchLifecycleService(session)
        try:
            return await service.list_for_token(authorization.removeprefix("Bearer ").strip())
        except InvalidBatchSessionError as error:
            raise HTTPException(status_code=401, detail="Invalid session") from error

    @app.post(
        "/api/batches/{batch_id}/actions",
        response_model=BatchLifecycleSummary,
        operation_id="actOnBatch",
    )
    async def act_on_batch(
        batch_id: str,
        payload: BatchLifecycleActionRequest,
        authorization: str | None = Header(default=None),
        session: AsyncSession = Depends(get_session),
    ) -> BatchLifecycleSummary:
        if authorization is None or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Missing bearer token")
        service = BatchLifecycleService(session)
        try:
            return await service.act_for_token(authorization.removeprefix("Bearer ").strip(), batch_id, payload)
        except InvalidBatchSessionError as error:
            raise HTTPException(status_code=401, detail="Invalid session") from error
        except UnknownBatchError as error:
            raise HTTPException(status_code=404, detail="Batch not found") from error
        except InvalidBatchActionError as error:
            raise HTTPException(status_code=422, detail="Batch action not allowed") from error

    @app.get(
        "/api/batches/{batch_id}/events",
        response_model=BatchLifecycleEventListResponse,
        operation_id="listBatchEvents",
    )
    async def list_batch_events(
        batch_id: str,
        authorization: str | None = Header(default=None),
        session: AsyncSession = Depends(get_session),
    ) -> BatchLifecycleEventListResponse:
        if authorization is None or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Missing bearer token")
        service = BatchLifecycleService(session)
        try:
            return await service.load_events_for_token(authorization.removeprefix("Bearer ").strip(), batch_id)
        except InvalidBatchSessionError as error:
            raise HTTPException(status_code=401, detail="Invalid session") from error
        except UnknownBatchError as error:
            raise HTTPException(status_code=404, detail="Batch not found") from error

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

    @app.get("/api/reminders", response_model=ReminderPreviewResponse, operation_id="getReminders")
    async def get_reminders(
        authorization: str | None = Header(default=None),
        session: AsyncSession = Depends(get_session),
    ) -> ReminderPreviewResponse:
        if authorization is None or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Missing bearer token")
        service = ReminderService(session)
        try:
            return await service.load_for_token(authorization.removeprefix("Bearer ").strip())
        except ReminderInvalidSessionError as error:
            raise HTTPException(status_code=401, detail="Invalid session") from error

    @app.put(
        "/api/reminder-settings",
        response_model=ReminderSettingsSummary,
        operation_id="updateReminderSettings",
    )
    async def update_reminder_settings(
        payload: ReminderSettingsRequest,
        authorization: str | None = Header(default=None),
        session: AsyncSession = Depends(get_session),
    ) -> ReminderSettingsSummary:
        if authorization is None or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Missing bearer token")
        service = ReminderService(session)
        try:
            return await service.update_settings_for_token(authorization.removeprefix("Bearer ").strip(), payload)
        except ReminderInvalidSessionError as error:
            raise HTTPException(status_code=401, detail="Invalid session") from error

    @app.post(
        "/api/reminders/dispatch",
        response_model=ReminderPreviewResponse,
        operation_id="dispatchReminders",
    )
    async def dispatch_reminders(
        authorization: str | None = Header(default=None),
        session: AsyncSession = Depends(get_session),
    ) -> ReminderPreviewResponse:
        if authorization is None or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Missing bearer token")
        service = ReminderService(session)
        try:
            return await service.dispatch_for_token(authorization.removeprefix("Bearer ").strip())
        except ReminderInvalidSessionError as error:
            raise HTTPException(status_code=401, detail="Invalid session") from error

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
            except PackagePhotoExtractorUnavailableError as error:
                raise HTTPException(status_code=503, detail="Package photo extractor unavailable") from error

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
        token = authorization.removeprefix("Bearer ").strip()
        service = TextCaptureService(session)
        try:
            return await service.confirm_drafts(token, payload)
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
            except PackagePhotoDraftConfirmationError as error:
                raise HTTPException(
                    status_code=422,
                    detail="Package photo draft is not ready for confirmation",
                ) from error
            except LowConfidenceDateRequiresReviewError as error:
                raise HTTPException(status_code=422, detail="Review low-confidence dates before saving") from error

    return app


app = create_app()


def main() -> None:
    settings = Settings()
    uvicorn.run("freshbot_butler.api.main:app", host=settings.host, port=settings.port, reload=False)
