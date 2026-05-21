from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from freshbot_butler.api.schemas import TextCaptureDraftRequest, VoiceCaptureDraftResponse
from freshbot_butler.api.services.text_capture import TextCaptureService, normalize_whitespace
from freshbot_butler.api.services.transcription import AudioCapture, TranscriptionProvider


class VoiceCaptureService:
    def __init__(self, session: AsyncSession, transcription_provider: TranscriptionProvider) -> None:
        self._text_capture = TextCaptureService(session)
        self._transcription_provider = transcription_provider

    async def create_drafts(self, token: str, audio_file: AudioCapture) -> VoiceCaptureDraftResponse:
        await self._text_capture.validate_session(token)
        transcript = normalize_whitespace(await self._transcription_provider.transcribe(audio_file))
        draft_response = await self._text_capture.create_drafts(
            token,
            TextCaptureDraftRequest(input_text=transcript),
        )
        return VoiceCaptureDraftResponse(
            transcript=transcript,
            drafts=draft_response.drafts,
            available_categories=draft_response.available_categories,
            available_locations=draft_response.available_locations,
        )
