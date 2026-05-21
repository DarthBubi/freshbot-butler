from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import httpx

from freshbot_butler.api.settings import Settings


@dataclass(frozen=True)
class AudioCapture:
    filename: str
    content_type: str | None
    data: bytes


class TranscriptionProvider(Protocol):
    async def transcribe(self, audio_file: AudioCapture) -> str: ...

    async def aclose(self) -> None: ...


class LocalTranscriptionAdapter(Protocol):
    async def transcribe(self, audio_file: AudioCapture) -> str: ...

    async def aclose(self) -> None: ...


class OpenAITranscriptionProvider:
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

    async def transcribe(self, audio_file: AudioCapture) -> str:
        if self._api_key is None:
            raise TranscriptionProviderUnavailableError("OpenAI API key is not configured")

        try:
            response = await self._http_client.post(
                "/audio/transcriptions",
                headers={"Authorization": f"Bearer {self._api_key}"},
                data={"model": self._model},
                files={
                    "file": (
                        audio_file.filename,
                        audio_file.data,
                        audio_file.content_type or "application/octet-stream",
                    )
                },
            )
            response.raise_for_status()
        except httpx.HTTPError as error:
            raise TranscriptionProviderUnavailableError("OpenAI transcription failed") from error

        transcript = response.json().get("text")
        if not isinstance(transcript, str):
            raise TranscriptionProviderUnavailableError("OpenAI transcription did not return text")
        return transcript

    async def aclose(self) -> None:
        if self._owns_http_client:
            await self._http_client.aclose()


class LocalTranscriptionProvider:
    def __init__(self, adapter: LocalTranscriptionAdapter | None = None) -> None:
        self._adapter = adapter

    async def transcribe(self, audio_file: AudioCapture) -> str:
        if self._adapter is None:
            raise TranscriptionProviderUnavailableError("Local transcription adapter is not configured")
        return await self._adapter.transcribe(audio_file)

    async def aclose(self) -> None:
        if self._adapter is not None:
            await self._adapter.aclose()


class UnavailableTranscriptionProvider:
    async def transcribe(self, audio_file: AudioCapture) -> str:
        raise TranscriptionProviderUnavailableError()

    async def aclose(self) -> None:
        return None


def create_transcription_provider(
    settings: Settings,
    http_client: httpx.AsyncClient | None = None,
    local_adapter: LocalTranscriptionAdapter | None = None,
) -> TranscriptionProvider:
    if settings.transcription_provider == "local":
        return LocalTranscriptionProvider(local_adapter)
    if settings.transcription_provider == "openai":
        return OpenAITranscriptionProvider(
            api_key=settings.transcription_openai_api_key,
            base_url=settings.transcription_openai_base_url,
            model=settings.transcription_openai_model,
            http_client=http_client,
        )
    return UnavailableTranscriptionProvider()


class TranscriptionProviderUnavailableError(Exception):
    pass
