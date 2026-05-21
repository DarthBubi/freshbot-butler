import httpx
import pytest

from freshbot_butler.api.services.transcription import AudioCapture, create_transcription_provider
from freshbot_butler.api.settings import Settings


@pytest.mark.asyncio
async def test_default_transcription_provider_uses_openai_audio_transcriptions_endpoint_with_valid_default_model() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"text": "2 Milch im Kühlschrank"})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://transcribe.example",
    ) as http_client:
        provider = create_transcription_provider(
            Settings(
                transcription_openai_api_key="test-key",
                transcription_openai_base_url="https://transcribe.example",
            ),
            http_client=http_client,
        )
        transcript = await provider.transcribe(
            AudioCapture(
                filename="capture.wav",
                content_type="audio/wav",
                data=b"pretend-audio",
            )
        )

    assert transcript == "2 Milch im Kühlschrank"
    assert len(requests) == 1
    request = requests[0]
    assert request.method == "POST"
    assert request.url == httpx.URL("https://transcribe.example/audio/transcriptions")
    assert request.headers["authorization"] == "Bearer test-key"
    assert b'name="model"' in request.content
    assert b'whisper-1' in request.content
    assert b'name="file"; filename="capture.wav"' in request.content
