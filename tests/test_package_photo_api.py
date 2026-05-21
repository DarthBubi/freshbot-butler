import asyncio
import inspect
import json
import sqlite3
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.dml import Update

from freshbot_butler.api.main import create_app
from freshbot_butler.api.models import PackagePhotoCapture
from freshbot_butler.api.services.package_photo import create_package_photo_extractor
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


def fetch_job_status(database_path: Path, capture_id: str) -> str:
    with sqlite3.connect(database_path) as connection:
        row = connection.execute(
            """
            SELECT status
            FROM jobs
            WHERE queue_name = 'package-photo-extraction'
              AND json_extract(payload, '$.capture_id') = ?
            """,
            (capture_id,),
        ).fetchone()

    assert row is not None
    return row[0]


def insert_stale_package_photo_job(database_path: Path, capture_id: str) -> None:
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            INSERT INTO jobs (id, queue_name, payload, status, created_at)
            VALUES (?, 'package-photo-extraction', json_object('capture_id', ?), 'pending', '2000-01-01T00:00:00+00:00')
            """,
            (str(uuid4()), capture_id),
        )
        connection.commit()


def process_all_pending_jobs(settings: Settings, extractor=None) -> int:
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
    def __init__(self) -> None:
        self.calls = 0

    async def extract(self, *, filename: str, content_type: str, content: bytes) -> list[dict]:
        self.calls += 1
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


class FailingPackagePhotoExtractor:
    async def extract(self, *, filename: str, content_type: str, content: bytes) -> list[dict]:
        raise RuntimeError("scanner exploded")


class FlakyPackagePhotoExtractor:
    def __init__(self) -> None:
        self.calls = 0

    async def extract(self, *, filename: str, content_type: str, content: bytes) -> list[dict]:
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("scanner exploded")
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


@pytest.mark.asyncio
async def test_package_photo_extractor_factory_uses_openai_chat_completion_endpoint_when_configured() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "drafts": [
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
                                }
                            )
                        }
                    }
                ]
            },
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://package-photo.example",
    ) as http_client:
        extractor = create_package_photo_extractor(
            Settings(
                package_photo_extractor="openai",
                package_photo_openai_api_key="test-key",
                package_photo_openai_base_url="https://package-photo.example",
                package_photo_openai_model="gpt-4o-mini",
            ),
            http_client=http_client,
        )
        drafts = await extractor.extract(
            filename="milch-label.jpg",
            content_type="image/jpeg",
            content=b"fake-image-bytes",
        )

    assert drafts == [
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
    assert len(requests) == 1
    request = requests[0]
    assert request.method == "POST"
    assert request.url == httpx.URL("https://package-photo.example/chat/completions")
    assert request.headers["authorization"] == "Bearer test-key"
    assert json.loads(request.content)["model"] == "gpt-4o-mini"
    assert b"fake-image-bytes" not in request.content


def test_member_can_upload_package_photo_and_receive_reviewable_draft_after_background_extraction() -> None:
    settings, _ = create_test_settings("package-photo-draft.sqlite3")
    extractor = FakePackagePhotoExtractor()

    with TestClient(create_app(settings, package_photo_extractor=extractor)) as client:
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
        assert extractor.calls == 0
        processed_jobs = process_all_pending_jobs(settings, extractor)
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
    assert extractor.calls == 1
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
        confirmed_draft_response = client.get(
            f"/api/package-photo/drafts/{draft_response.json()['capture_id']}",
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
    assert confirmed_draft_response.status_code == 200
    assert confirmed_draft_response.json()["status"] == "confirmed"
    assert confirmed_draft_response.json()["drafts"] == [
        {
            "name": "Hackfleisch",
            "quantity": "500 g",
            "category": "Molkerei",
            "location": "Kühlschrank",
            "date_type": "use_by",
            "expires_on": "2099-03-14",
            "requires_date_review": True,
            "date_reviewed": True,
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


def test_package_photo_confirmation_rejects_processing_capture_and_waits_for_stored_extraction() -> None:
    settings, _ = create_test_settings("package-photo-confirm-processing.sqlite3")

    with TestClient(create_app(settings, package_photo_extractor=FakePackagePhotoExtractor())) as client:
        token = authenticate(client)

        upload_response = client.post(
            "/api/package-photo/drafts",
            headers={"Authorization": f"Bearer {token}"},
            files={"photo": ("milch-label.jpg", b"fake-image-bytes", "image/jpeg")},
        )
        capture_id = upload_response.json()["capture_id"]

        rejected_response = client.post(
            "/api/package-photo/confirm",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "capture_id": capture_id,
                "drafts": [
                    {
                        "name": "Ganz anderes Produkt",
                        "quantity": "9 Packungen",
                        "category": "Vorrat",
                        "location": "Vorratsschrank",
                    }
                ],
            },
        )
        processed_jobs = process_all_pending_jobs(settings, FakePackagePhotoExtractor())
        fetch_response = client.get(
            f"/api/package-photo/drafts/{capture_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        today_response = client.get("/api/today", headers={"Authorization": f"Bearer {token}"})

    assert rejected_response.status_code == 422
    assert processed_jobs == 2
    assert fetch_response.status_code == 200
    assert fetch_response.json()["status"] == "pending_review"
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
    assert today_response.status_code == 200
    assert today_response.json()["sections"]["inventory"] == []


def test_package_photo_confirmation_rejects_payload_that_does_not_match_reviewed_capture() -> None:
    settings, _ = create_test_settings("package-photo-confirm-mismatch.sqlite3")

    with TestClient(create_app(settings, package_photo_extractor=FakePackagePhotoExtractor())) as client:
        token = authenticate(client)

        upload_response = client.post(
            "/api/package-photo/drafts",
            headers={"Authorization": f"Bearer {token}"},
            files={"photo": ("milch-label.jpg", b"fake-image-bytes", "image/jpeg")},
        )
        capture_id = upload_response.json()["capture_id"]
        assert process_all_pending_jobs(settings, FakePackagePhotoExtractor()) == 2

        review_response = client.get(
            f"/api/package-photo/drafts/{capture_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        reviewed_draft = {**review_response.json()["drafts"][0], "name": "Mandarinen"}

        rejected_response = client.post(
            "/api/package-photo/confirm",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "capture_id": capture_id,
                "drafts": [reviewed_draft],
            },
        )
        today_response = client.get("/api/today", headers={"Authorization": f"Bearer {token}"})

    assert rejected_response.status_code == 422
    assert today_response.status_code == 200
    assert today_response.json()["sections"]["inventory"] == []


def test_package_photo_worker_skips_already_confirmed_captures() -> None:
    settings, database_path = create_test_settings("package-photo-worker-skip.sqlite3")

    with TestClient(create_app(settings, package_photo_extractor=FakePackagePhotoExtractor())) as client:
        token = authenticate(client)

        upload_response = client.post(
            "/api/package-photo/drafts",
            headers={"Authorization": f"Bearer {token}"},
            files={"photo": ("milch-label.jpg", b"fake-image-bytes", "image/jpeg")},
        )
        capture_id = upload_response.json()["capture_id"]
        assert process_all_pending_jobs(settings, FakePackagePhotoExtractor()) == 2

        review_response = client.get(
            f"/api/package-photo/drafts/{capture_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        confirm_response = client.post(
            "/api/package-photo/confirm",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "capture_id": capture_id,
                "drafts": review_response.json()["drafts"],
            },
        )

        insert_stale_package_photo_job(database_path, capture_id)
        processed_jobs = process_all_pending_jobs(settings, FakePackagePhotoExtractor())
        confirmed_response = client.get(
            f"/api/package-photo/drafts/{capture_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        today_response = client.get("/api/today", headers={"Authorization": f"Bearer {token}"})

    assert confirm_response.status_code == 200
    assert confirm_response.json()["batches"] == [
        {
            "name": "Bio-Milch",
            "quantity": "1 Flasche",
            "category": "Molkerei",
            "location": "Kühlschrank",
        }
    ]
    assert processed_jobs == 2
    assert confirmed_response.status_code == 200
    assert confirmed_response.json()["status"] == "confirmed"
    assert confirmed_response.json()["drafts"] == [
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
    assert today_response.status_code == 200
    assert today_response.json()["sections"]["inventory"] == [
        {
            "name": "Bio-Milch",
            "quantity": "1 Flasche",
            "category": "Molkerei",
            "location": "Kühlschrank",
            "freshness": {
                "state": "urgent",
                "source": "exact_date",
                "date_type": "best_before",
                "due_on": "2025-03-14",
            },
        }
    ]


@pytest.mark.asyncio
async def test_package_photo_worker_does_not_overwrite_a_capture_confirmed_while_another_worker_is_stale() -> None:
    settings, _ = create_test_settings("package-photo-worker-race.sqlite3")
    extractor = FakePackagePhotoExtractor()
    original_execute = AsyncSession.execute
    original_get = AsyncSession.get
    process_capture_execute_started = asyncio.Event()
    allow_process_capture_execute = asyncio.Event()

    async def get_with_release(self: AsyncSession, entity, ident, *args, **kwargs):
        result = await original_get(self, entity, ident, *args, **kwargs)
        if entity is PackagePhotoCapture and any(frame.function == "process_capture" for frame in inspect.stack()):
            await self.commit()
        return result

    async def execute_with_gate(self: AsyncSession, statement, *args, **kwargs):
        if any(frame.function == "process_capture" for frame in inspect.stack()) and isinstance(statement, Update):
            process_capture_execute_started.set()
            await allow_process_capture_execute.wait()
        return await original_execute(self, statement, *args, **kwargs)

    app = create_app(settings, package_photo_extractor=extractor)
    transport = httpx.ASGITransport(app=app)

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(AsyncSession, "get", get_with_release)
        monkeypatch.setattr(AsyncSession, "execute", execute_with_gate)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                auth_response = await client.post(
                    "/api/auth/household-session",
                    json={"household_name": "WG Sonnenseite", "member_name": "Johannes"},
                )
                assert auth_response.status_code == 200
                token = auth_response.json()["token"]

                upload_response = await client.post(
                    "/api/package-photo/drafts",
                    headers={"Authorization": f"Bearer {token}"},
                    files={"photo": ("milch-label.jpg", b"fake-image-bytes", "image/jpeg")},
                )
                assert upload_response.status_code == 200
                capture_id = upload_response.json()["capture_id"]

                worker = asyncio.create_task(process_pending_jobs_once(settings, extractor))
                await asyncio.wait_for(process_capture_execute_started.wait(), timeout=5)

                with sqlite3.connect(settings.database_url.removeprefix("sqlite+aiosqlite:///")) as connection:
                    connection.execute(
                        """
                        UPDATE package_photo_captures
                        SET
                            status = 'pending_review',
                            extraction_payload = json_object(
                                'drafts',
                                json_array(
                                    json_object(
                                        'name', 'Bio-Milch',
                                        'quantity', '1 Flasche',
                                        'category', 'Molkerei',
                                        'location', 'Kühlschrank',
                                        'date_type', 'best_before',
                                        'expires_on', '2025-03-14',
                                        'requires_date_review', 0
                                    )
                                )
                            ),
                            raw_upload = NULL,
                            raw_upload_filename = NULL,
                            raw_upload_content_type = NULL,
                            raw_upload_expires_at = NULL
                        WHERE id = ?
                        """,
                        (capture_id,),
                    )
                    connection.commit()

                pending_response = await client.get(
                    f"/api/package-photo/drafts/{capture_id}",
                    headers={"Authorization": f"Bearer {token}"},
                )
                assert pending_response.status_code == 200
                assert pending_response.json()["status"] == "pending_review"

                confirm_response = await client.post(
                    "/api/package-photo/confirm",
                    headers={"Authorization": f"Bearer {token}"},
                    json={
                        "capture_id": capture_id,
                        "drafts": pending_response.json()["drafts"],
                    },
                )
                assert confirm_response.status_code == 200

                allow_process_capture_execute.set()
                assert await asyncio.wait_for(worker, timeout=5) == 3

                confirmed_response = await client.get(
                    f"/api/package-photo/drafts/{capture_id}",
                    headers={"Authorization": f"Bearer {token}"},
                )
                today_response = await client.get("/api/today", headers={"Authorization": f"Bearer {token}"})

    assert confirmed_response.status_code == 200
    assert confirmed_response.json()["status"] == "confirmed"
    assert confirmed_response.json()["drafts"] == [
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
    assert today_response.status_code == 200
    assert today_response.json()["sections"]["inventory"] == [
        {
            "name": "Bio-Milch",
            "quantity": "1 Flasche",
            "category": "Molkerei",
            "location": "Kühlschrank",
            "freshness": {
                "state": "urgent",
                "source": "exact_date",
                "date_type": "best_before",
                "due_on": "2025-03-14",
            },
        }
    ]


def test_expired_package_photo_upload_is_purged_even_without_successful_extraction() -> None:
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
        expire_package_photo_upload(database_path, capture_id)

        fetch_response = client.get(
            f"/api/package-photo/drafts/{capture_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        expired_raw_upload, expired_extraction = fetch_package_photo_capture_storage(database_path, capture_id)

    assert stored_raw_upload == b"fake-image-bytes"
    assert stored_extraction == "{}"
    assert fetch_response.status_code == 200
    assert fetch_response.json()["status"] == "failed"
    assert fetch_response.json()["drafts"] == []
    assert expired_raw_upload is None
    assert expired_extraction == "{}"


def test_package_photo_upload_uses_supported_disabled_mode_when_extractor_is_missing() -> None:
    settings, _ = create_test_settings("package-photo-unconfigured.sqlite3")
    settings = settings.model_copy(update={"app_env": "development"})

    with TestClient(create_app(settings)) as client:
        token = authenticate(client)

        response = client.post(
            "/api/package-photo/drafts",
            headers={"Authorization": f"Bearer {token}"},
            files={"photo": ("milch-label.jpg", b"fake-image-bytes", "image/jpeg")},
        )

    assert response.status_code == 503
    assert response.json() == {"detail": "Package photo extractor unavailable"}


def test_package_photo_extraction_failure_marks_the_background_job_failed() -> None:
    settings, database_path = create_test_settings("package-photo-failure.sqlite3")

    with TestClient(create_app(settings, package_photo_extractor=FailingPackagePhotoExtractor())) as client:
        token = authenticate(client)

        upload_response = client.post(
            "/api/package-photo/drafts",
            headers={"Authorization": f"Bearer {token}"},
            files={"photo": ("milch-label.jpg", b"fake-image-bytes", "image/jpeg")},
        )

        assert upload_response.status_code == 200
        capture_id = upload_response.json()["capture_id"]

        asyncio.run(process_pending_jobs_once(settings, FailingPackagePhotoExtractor()))
        fetch_response = client.get(
            f"/api/package-photo/drafts/{capture_id}",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert fetch_job_status(database_path, capture_id) == "failed"
    assert fetch_response.status_code == 200
    assert fetch_response.json()["status"] == "failed"
    assert fetch_response.json()["drafts"] == []


def test_worker_continues_processing_later_jobs_after_a_failure() -> None:
    settings, database_path = create_test_settings("package-photo-worker-continues.sqlite3")
    extractor = FlakyPackagePhotoExtractor()

    with TestClient(create_app(settings, package_photo_extractor=extractor)) as client:
        token = authenticate(client)

        first_upload = client.post(
            "/api/package-photo/drafts",
            headers={"Authorization": f"Bearer {token}"},
            files={"photo": ("first.jpg", b"fake-image-bytes", "image/jpeg")},
        )
        second_upload = client.post(
            "/api/package-photo/drafts",
            headers={"Authorization": f"Bearer {token}"},
            files={"photo": ("second.jpg", b"fake-image-bytes", "image/jpeg")},
        )

        assert first_upload.status_code == 200
        assert second_upload.status_code == 200
        first_capture_id = first_upload.json()["capture_id"]
        second_capture_id = second_upload.json()["capture_id"]

        assert asyncio.run(process_pending_jobs_once(settings, extractor)) >= 2

        first_fetch = client.get(
            f"/api/package-photo/drafts/{first_capture_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        second_fetch = client.get(
            f"/api/package-photo/drafts/{second_capture_id}",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert fetch_job_status(database_path, first_capture_id) == "failed"
    assert fetch_job_status(database_path, second_capture_id) == "completed"
    assert first_fetch.status_code == 200
    assert first_fetch.json()["status"] == "failed"
    assert second_fetch.status_code == 200
    assert second_fetch.json()["status"] == "pending_review"
