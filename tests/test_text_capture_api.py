import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from freshbot_butler.api.main import create_app
from freshbot_butler.api.settings import Settings


def create_test_settings(database_name: str) -> tuple[Settings, Path]:
    runtime_dir = Path("tests/.runtime")
    runtime_dir.mkdir(exist_ok=True)
    database_path = runtime_dir / database_name
    if database_path.exists():
        database_path.unlink()

    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{database_path}",
        app_env="test",
        session_token_ttl_hours=24,
    )
    return settings, database_path


def authenticate(client: TestClient) -> str:
    response = client.post(
        "/api/auth/household-session",
        json={"household_name": "WG Sonnenseite", "member_name": "Johannes"},
    )

    assert response.status_code == 200
    return response.json()["token"]


def fetch_batches(database_path: Path) -> list[tuple[str, str, str, str]]:
    with sqlite3.connect(database_path) as connection:
        return connection.execute(
            "SELECT name, quantity, category, location FROM batches ORDER BY created_at, name"
        ).fetchall()


class StubTranscriptionProvider:
    def __init__(self, transcript: str) -> None:
        self._transcript = transcript
        self.calls = 0

    async def transcribe(self, _audio_file) -> str:
        self.calls += 1
        return self._transcript

    async def aclose(self) -> None:
        return None


def test_member_can_upload_voice_capture_and_review_batch_drafts() -> None:
    settings, _ = create_test_settings("voice-capture-drafts.sqlite3")

    with TestClient(
        create_app(
            settings,
            transcription_provider=StubTranscriptionProvider(
                "2 Milch im Kühlschrank und 1 Packung Pasta im Vorratsschrank"
            ),
        )
    ) as client:
        token = authenticate(client)

        response = client.post(
            "/api/voice-capture/drafts",
            headers={"Authorization": f"Bearer {token}"},
            files={"audio_file": ("capture.wav", b"pretend-audio", "audio/wav")},
        )

    assert response.status_code == 200
    assert response.json() == {
        "transcript": "2 Milch im Kühlschrank und 1 Packung Pasta im Vorratsschrank",
        "drafts": [
            {
                "name": "Milch",
                "quantity": "2",
                "category": "Molkerei",
                "location": "Kühlschrank",
                "date_type": None,
                "expires_on": None,
            },
            {
                "name": "Pasta",
                "quantity": "1 Packung",
                "category": "Vorrat",
                "location": "Vorratsschrank",
                "date_type": None,
                "expires_on": None,
            },
        ],
        "available_categories": [
            "Molkerei",
            "Obst & Gemüse",
            "Vorrat",
            "Getränke",
            "Sonstiges",
        ],
        "available_locations": [
            "Kühlschrank",
            "Gefrierschrank",
            "Vorratsschrank",
        ],
    }


def test_voice_capture_rejects_invalid_session_before_transcribing() -> None:
    settings, _ = create_test_settings("voice-capture-invalid-session.sqlite3")
    provider = StubTranscriptionProvider("2 Milch im Kühlschrank")

    with TestClient(create_app(settings, transcription_provider=provider)) as client:
        response = client.post(
            "/api/voice-capture/drafts",
            headers={"Authorization": "Bearer invalid-session-token"},
            files={"audio_file": ("capture.wav", b"pretend-audio", "audio/wav")},
        )

    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid session"}
    assert provider.calls == 0


def test_member_can_turn_text_input_into_reviewable_batch_drafts() -> None:
    settings, _ = create_test_settings("text-capture-drafts.sqlite3")

    with TestClient(create_app(settings)) as client:
        token = authenticate(client)

        response = client.post(
            "/api/text-capture/drafts",
            headers={"Authorization": f"Bearer {token}"},
            json={"input_text": "2 Milch im Kühlschrank und 1 Packung Pasta im Vorratsschrank"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert [
        {key: draft[key] for key in ("name", "quantity", "category", "location")}
        for draft in payload["drafts"]
    ] == [
        {
            "name": "Milch",
            "quantity": "2",
            "category": "Molkerei",
            "location": "Kühlschrank",
        },
        {
            "name": "Pasta",
            "quantity": "1 Packung",
            "category": "Vorrat",
            "location": "Vorratsschrank",
        },
    ]
    assert payload["available_categories"] == [
        "Molkerei",
        "Obst & Gemüse",
        "Vorrat",
        "Getränke",
        "Sonstiges",
    ]
    assert payload["available_locations"] == [
        "Kühlschrank",
        "Gefrierschrank",
        "Vorratsschrank",
    ]


def test_member_can_edit_drafts_confirm_them_and_see_saved_batches_on_today_dashboard() -> None:
    settings, database_path = create_test_settings("text-capture-confirm.sqlite3")

    with TestClient(create_app(settings)) as client:
        token = authenticate(client)
        drafts_response = client.post(
            "/api/text-capture/drafts",
            headers={"Authorization": f"Bearer {token}"},
            json={"input_text": "2 Milch im Kühlschrank und 1 Packung Pasta im Vorratsschrank"},
        )
        assert drafts_response.status_code == 200

        response = client.post(
            "/api/text-capture/confirm",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "drafts": [
                    {
                        "name": "Haferdrink",
                        "quantity": "2 Kartons",
                        "category": "Getränke",
                        "location": "Kühlschrank",
                    },
                    {
                        "name": "Penne",
                        "quantity": "1 Packung",
                        "category": "Vorrat",
                        "location": "Vorratsschrank",
                    },
                ]
            },
        )

        today_response = client.get(
            "/api/today",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 200
    assert response.json() == {
        "batches": [
            {
                "name": "Haferdrink",
                "quantity": "2 Kartons",
                "category": "Getränke",
                "location": "Kühlschrank",
            },
            {
                "name": "Penne",
                "quantity": "1 Packung",
                "category": "Vorrat",
                "location": "Vorratsschrank",
            },
        ]
    }
    assert fetch_batches(database_path) == [
        ("Haferdrink", "2 Kartons", "Getränke", "Kühlschrank"),
        ("Penne", "1 Packung", "Vorrat", "Vorratsschrank"),
    ]
    assert today_response.status_code == 200
    assert [
        {key: batch[key] for key in ("name", "quantity", "category", "location")}
        for batch in today_response.json()["sections"]["inventory"]
    ] == [
        {
            "name": "Haferdrink",
            "quantity": "2 Kartons",
            "category": "Getränke",
            "location": "Kühlschrank",
        },
        {
            "name": "Penne",
            "quantity": "1 Packung",
            "category": "Vorrat",
            "location": "Vorratsschrank",
        },
    ]


@pytest.mark.parametrize("field_name", ["name", "quantity", "category", "location"])
def test_confirm_rejects_whitespace_only_draft_fields_without_saving_batches(field_name: str) -> None:
    settings, _ = create_test_settings(f"text-capture-invalid-{field_name}.sqlite3")

    with TestClient(create_app(settings)) as client:
        token = authenticate(client)

        invalid_draft = {
            "name": "Haferdrink",
            "quantity": "2 Kartons",
            "category": "Getränke",
            "location": "Kühlschrank",
        }
        invalid_draft[field_name] = "   "

        response = client.post(
            "/api/text-capture/confirm",
            headers={"Authorization": f"Bearer {token}"},
            json={"drafts": [invalid_draft]},
        )
        today_response = client.get(
            "/api/today",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", "drafts", 0, field_name]
    assert today_response.status_code == 200
    assert today_response.json()["sections"]["inventory"] == []


def test_confirm_keeps_normalizing_non_blank_category_and_location_values() -> None:
    settings, database_path = create_test_settings("text-capture-normalized-category-location.sqlite3")

    with TestClient(create_app(settings)) as client:
        token = authenticate(client)

        response = client.post(
            "/api/text-capture/confirm",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "drafts": [
                    {
                        "name": "Haferdrink",
                        "quantity": "2 Kartons",
                        "category": "  Haushaltswaren  ",
                        "location": "  Keller  ",
                    }
                ]
            },
        )

    assert response.status_code == 200
    assert response.json() == {
        "batches": [
            {
                "name": "Haferdrink",
                "quantity": "2 Kartons",
                "category": "Sonstiges",
                "location": "Vorratsschrank",
            }
        ]
    }
    assert fetch_batches(database_path) == [("Haferdrink", "2 Kartons", "Sonstiges", "Vorratsschrank")]
