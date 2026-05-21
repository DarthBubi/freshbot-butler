import asyncio
import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from freshbot_butler.api.main import create_app
from freshbot_butler.api.settings import Settings
from freshbot_butler.worker.main import process_pending_jobs_once


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


def expire_package_photo_upload(database_path: Path, capture_id: str) -> None:
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            UPDATE package_photo_captures
            SET raw_upload_expires_at = '2000-01-01T00:00:00+00:00'
            WHERE id = ?
            """,
            (capture_id,),
        )
        connection.commit()


def fetch_package_photo_capture_storage(database_path: Path, capture_id: str) -> tuple[bytes | None, str]:
    with sqlite3.connect(database_path) as connection:
        row = connection.execute(
            """
            SELECT raw_upload, extraction_payload
            FROM package_photo_captures
            WHERE id = ?
            """,
            (capture_id,),
        ).fetchone()

    assert row is not None
    raw_upload, extraction_payload = row
    assert isinstance(extraction_payload, str)
    return raw_upload, extraction_payload


def process_all_pending_jobs(settings: Settings, extractor) -> int:
    processed_jobs = 0
    while True:
        processed = asyncio.run(
            process_pending_jobs_once(
                settings,
                package_photo_extractor=extractor,
            )
        )
        processed_jobs += processed
        if processed == 0:
            return processed_jobs


class FakePackagePhotoExtractor:
    async def extract(self, *, filename: str, content_type: str, content: bytes) -> list[dict]:
        assert filename == "milch-label.jpg"
        assert content_type == "image/jpeg"
        assert content == b"fake-image-bytes"
        return [
            {
                "name": "Bio-Milch",
                "quantity": "1 Flasche",
                "category": "Molkerei",
                "location": "Kühlschrank",
                "date_type": "best_before",
                "expires_on": "2025-03-14",
                "requires_date_review": False,
            }
        ]


def test_member_can_upload_package_photo_and_receive_reviewable_draft_after_background_extraction() -> None:
    settings, _ = create_test_settings("package-photo-draft.sqlite3")

    with TestClient(create_app(settings, package_photo_extractor=FakePackagePhotoExtractor())) as client:
        token = authenticate(client)

        response = client.post(
            "/api/package-photo/drafts",
            headers={"Authorization": f"Bearer {token}"},
            files={"photo": ("milch-label.jpg", b"fake-image-bytes", "image/jpeg")},
        )
        queued_response = client.get(
            f"/api/package-photo/drafts/{response.json()['capture_id']}",
            headers={"Authorization": f"Bearer {token}"},
        )
        processed_jobs = process_all_pending_jobs(settings, FakePackagePhotoExtractor())
        completed_response = client.get(
            f"/api/package-photo/drafts/{response.json()['capture_id']}",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "processing"
    assert payload["drafts"] == []
    assert queued_response.status_code == 200
    assert queued_response.json()["status"] == "processing"
    assert queued_response.json()["drafts"] == []
    assert processed_jobs == 2
    assert completed_response.status_code == 200
    assert completed_response.json()["status"] == "pending_review"
    assert completed_response.json()["drafts"] == [
        {
            "name": "Bio-Milch",
            "quantity": "1 Flasche",
            "category": "Molkerei",
            "location": "Kühlschrank",
            "date_type": "best_before",
            "expires_on": "2025-03-14",
            "requires_date_review": False,
            "date_reviewed": False,
        }
    ]
    assert completed_response.json()["available_categories"] == [
        "Molkerei",
        "Obst & Gemüse",
        "Vorrat",
        "Getränke",
        "Sonstiges",
    ]
    assert completed_response.json()["available_locations"] == [
        "Kühlschrank",
        "Gefrierschrank",
        "Vorratsschrank",
    ]
    assert completed_response.json()["available_date_types"] == ["best_before", "use_by"]
    assert isinstance(payload["capture_id"], str)


class FakeLowConfidencePackagePhotoExtractor:
    async def extract(self, *, filename: str, content_type: str, content: bytes) -> list[dict]:
        return [
            {
                "name": "Hackfleisch",
                "quantity": "500 g",
                "category": "Molkerei",
                "location": "Kühlschrank",
                "date_type": "use_by",
                "expires_on": "2099-03-14",
                "requires_date_review": True,
            }
        ]


def test_low_confidence_package_photo_dates_require_explicit_review_before_saving() -> None:
    settings, _ = create_test_settings("package-photo-review-required.sqlite3")

    with TestClient(
        create_app(
            settings,
            package_photo_extractor=FakeLowConfidencePackagePhotoExtractor(),
        )
    ) as client:
        token = authenticate(client)

        draft_response = client.post(
            "/api/package-photo/drafts",
            headers={"Authorization": f"Bearer {token}"},
            files={"photo": ("hackfleisch-label.jpg", b"fake-image-bytes", "image/jpeg")},
        )
        assert draft_response.status_code == 200
        assert process_all_pending_jobs(settings, FakeLowConfidencePackagePhotoExtractor()) == 2
        uploaded_draft = client.get(
            f"/api/package-photo/drafts/{draft_response.json()['capture_id']}",
            headers={"Authorization": f"Bearer {token}"},
        ).json()["drafts"][0]

        rejected_response = client.post(
            "/api/package-photo/confirm",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "capture_id": draft_response.json()["capture_id"],
                "drafts": [uploaded_draft],
            },
        )
        today_after_rejection = client.get(
            "/api/today",
            headers={"Authorization": f"Bearer {token}"},
        )

        reviewed_draft = {**uploaded_draft, "date_reviewed": True}
        confirmed_response = client.post(
            "/api/package-photo/confirm",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "capture_id": draft_response.json()["capture_id"],
                "drafts": [reviewed_draft],
            },
        )
        today_after_confirmation = client.get(
            "/api/today",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert rejected_response.status_code == 422
    assert today_after_rejection.status_code == 200
    assert today_after_rejection.json()["sections"]["inventory"] == []
    assert confirmed_response.status_code == 200
    assert confirmed_response.json()["batches"] == [
        {
            "name": "Hackfleisch",
            "quantity": "500 g",
            "category": "Molkerei",
            "location": "Kühlschrank",
        }
    ]
    assert today_after_confirmation.status_code == 200
    assert today_after_confirmation.json()["sections"]["inventory"] == [
        {
            "name": "Hackfleisch",
            "quantity": "500 g",
            "category": "Molkerei",
            "location": "Kühlschrank",
            "freshness": {
                "state": "normal",
                "source": "exact_date",
                "date_type": "use_by",
                "due_on": "2099-03-14",
            },
        }
    ]


def test_package_photo_keeps_reviewable_extraction_after_raw_upload_expires() -> None:
    settings, database_path = create_test_settings("package-photo-retention.sqlite3")

    with TestClient(create_app(settings, package_photo_extractor=FakePackagePhotoExtractor())) as client:
        token = authenticate(client)

        upload_response = client.post(
            "/api/package-photo/drafts",
            headers={"Authorization": f"Bearer {token}"},
            files={"photo": ("milch-label.jpg", b"fake-image-bytes", "image/jpeg")},
        )

        assert upload_response.status_code == 200
        capture_id = upload_response.json()["capture_id"]

        stored_raw_upload, stored_extraction = fetch_package_photo_capture_storage(database_path, capture_id)
        assert process_all_pending_jobs(settings, FakePackagePhotoExtractor()) == 2
        processed_raw_upload, processed_extraction = fetch_package_photo_capture_storage(
            database_path,
            capture_id,
        )
        expire_package_photo_upload(database_path, capture_id)

        fetch_response = client.get(
            f"/api/package-photo/drafts/{capture_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        expired_raw_upload, expired_extraction = fetch_package_photo_capture_storage(database_path, capture_id)

    assert stored_raw_upload == b"fake-image-bytes"
    assert stored_extraction == "{}"
    assert processed_raw_upload == b"fake-image-bytes"
    assert "Bio-Milch" in processed_extraction
    assert fetch_response.status_code == 200
    assert fetch_response.json()["drafts"] == [
        {
            "name": "Bio-Milch",
            "quantity": "1 Flasche",
            "category": "Molkerei",
            "location": "Kühlschrank",
            "date_type": "best_before",
            "expires_on": "2025-03-14",
            "requires_date_review": False,
            "date_reviewed": False,
        }
    ]
    assert expired_raw_upload is None
    assert expired_extraction == processed_extraction
