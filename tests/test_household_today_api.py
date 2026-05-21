import asyncio
import sqlite3
from datetime import timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from freshbot_butler.api.main import create_app
from freshbot_butler.api.models import utc_now
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


def delete_member_for_token(database_path: Path, token: str) -> None:
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            DELETE FROM members
            WHERE id = (
                SELECT member_id
                FROM session_tokens
                WHERE token = ?
            )
            """,
            (token,),
        )
        connection.commit()


def delete_household_for_token(database_path: Path, token: str) -> None:
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            DELETE FROM households
            WHERE id = (
                SELECT members.household_id
                FROM members
                JOIN session_tokens ON session_tokens.member_id = members.id
                WHERE session_tokens.token = ?
            )
            """,
            (token,),
        )
        connection.commit()


def authenticate(client: TestClient) -> str:
    auth_response = client.post(
        "/api/auth/household-session",
        json={"household_name": "WG Sonnenseite", "member_name": "Johannes"},
    )

    assert auth_response.status_code == 200
    return auth_response.json()["token"]


def update_batch_created_at(database_path: Path, batch_id: str, created_at: str) -> None:
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            UPDATE batches
            SET created_at = ?
            WHERE id = ?
            """,
            (created_at, batch_id),
        )
        connection.commit()


def create_legacy_schema(database_path: Path) -> None:
    with sqlite3.connect(database_path) as connection:
        connection.executescript(
            """
            CREATE TABLE households (
                id VARCHAR(36) PRIMARY KEY NOT NULL,
                slug VARCHAR(128) NOT NULL,
                name VARCHAR(255) NOT NULL,
                locale VARCHAR(16) NOT NULL,
                created_at DATETIME NOT NULL
            );
            CREATE TABLE members (
                id VARCHAR(36) PRIMARY KEY NOT NULL,
                household_id VARCHAR(36) NOT NULL,
                display_name VARCHAR(255) NOT NULL,
                normalized_name VARCHAR(255) NOT NULL,
                created_at DATETIME NOT NULL
            );
            CREATE TABLE session_tokens (
                id VARCHAR(36) PRIMARY KEY NOT NULL,
                member_id VARCHAR(36) NOT NULL,
                token VARCHAR(255) NOT NULL,
                expires_at DATETIME NOT NULL,
                created_at DATETIME NOT NULL
            );
            CREATE TABLE batches (
                id VARCHAR(36) PRIMARY KEY NOT NULL,
                household_id VARCHAR(36) NOT NULL,
                name VARCHAR(255) NOT NULL,
                quantity VARCHAR(255) NOT NULL,
                category VARCHAR(255) NOT NULL,
                location VARCHAR(255) NOT NULL,
                created_at DATETIME NOT NULL
            );
            """
        )
        connection.commit()


def test_member_can_join_household_and_load_empty_today_dashboard() -> None:
    settings, _ = create_test_settings("household-today.sqlite3")
    with TestClient(create_app(settings)) as client:
        auth_response = client.post(
            "/api/auth/household-session",
            json={"household_name": "WG Sonnenseite", "member_name": "Johannes"},
        )

        assert auth_response.status_code == 200
        session = auth_response.json()
        assert session["household"]["name"] == "WG Sonnenseite"
        assert session["household"]["slug"] == "wg-sonnenseite"
        assert session["member"]["display_name"] == "Johannes"
        assert session["locale"] == "de-DE"
        assert session["token"]

        today_response = client.get(
            "/api/today",
            headers={"Authorization": f"Bearer {session['token']}"},
        )

        assert today_response.status_code == 200
        today = today_response.json()
        assert today == {
            "household_name": "WG Sonnenseite",
            "member_name": "Johannes",
            "locale": "de-DE",
            "sections": {
                "inventory": [],
                "needs_attention": [],
                "upcoming": [],
                "shopping_suggestions": [],
            },
        }


def test_today_dashboard_rejects_session_when_member_was_deleted_after_login() -> None:
    settings, database_path = create_test_settings("missing-member.sqlite3")

    with TestClient(create_app(settings)) as client:
        auth_response = client.post(
            "/api/auth/household-session",
            json={"household_name": "WG Sonnenseite", "member_name": "Johannes"},
        )

        assert auth_response.status_code == 200
        session = auth_response.json()

        delete_member_for_token(database_path, session["token"])

        today_response = client.get(
            "/api/today",
            headers={"Authorization": f"Bearer {session['token']}"},
        )

    assert today_response.status_code == 401
    assert today_response.json() == {"detail": "Invalid session"}


def test_today_dashboard_rejects_session_when_household_was_deleted_after_login() -> None:
    settings, database_path = create_test_settings("missing-household.sqlite3")

    with TestClient(create_app(settings)) as client:
        auth_response = client.post(
            "/api/auth/household-session",
            json={"household_name": "WG Sonnenseite", "member_name": "Johannes"},
        )

        assert auth_response.status_code == 200
        session = auth_response.json()

        delete_household_for_token(database_path, session["token"])

        today_response = client.get(
            "/api/today",
            headers={"Authorization": f"Bearer {session['token']}"},
        )

    assert today_response.status_code == 401
    assert today_response.json() == {"detail": "Invalid session"}


def test_today_dashboard_computes_freshness_states_from_dates_date_types_and_category_defaults() -> None:
    settings, _ = create_test_settings("today-freshness.sqlite3")
    today_date = utc_now().date()

    with TestClient(create_app(settings)) as client:
        token = authenticate(client)

        confirm_response = client.post(
            "/api/text-capture/confirm",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "drafts": [
                    {
                        "name": "Hackfleisch",
                        "quantity": "500 g",
                        "category": "Molkerei",
                        "location": "Kühlschrank",
                        "date_type": "use_by",
                        "expires_on": today_date.isoformat(),
                    },
                    {
                        "name": "Joghurt",
                        "quantity": "2 Becher",
                        "category": "Molkerei",
                        "location": "Kühlschrank",
                        "date_type": "best_before",
                        "expires_on": today_date.isoformat(),
                    },
                    {
                        "name": "Bananen",
                        "quantity": "6 Stück",
                        "category": "Obst & Gemüse",
                        "location": "Vorratsschrank",
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

    assert confirm_response.status_code == 200
    assert today_response.status_code == 200
    assert today_response.json()["sections"] == {
        "inventory": [
            {
                "name": "Hackfleisch",
                "quantity": "500 g",
                "category": "Molkerei",
                "location": "Kühlschrank",
                "freshness": {
                    "state": "urgent",
                    "source": "exact_date",
                    "date_type": "use_by",
                    "due_on": today_date.isoformat(),
                },
            },
            {
                "name": "Joghurt",
                "quantity": "2 Becher",
                "category": "Molkerei",
                "location": "Kühlschrank",
                "freshness": {
                    "state": "soon",
                    "source": "exact_date",
                    "date_type": "best_before",
                    "due_on": today_date.isoformat(),
                },
            },
            {
                "name": "Bananen",
                "quantity": "6 Stück",
                "category": "Obst & Gemüse",
                "location": "Vorratsschrank",
                "freshness": {
                    "state": "soon",
                    "source": "category_default",
                    "date_type": None,
                    "due_on": (today_date + timedelta(days=2)).isoformat(),
                },
            },
            {
                "name": "Penne",
                "quantity": "1 Packung",
                "category": "Vorrat",
                "location": "Vorratsschrank",
                "freshness": {
                    "state": "normal",
                    "source": "category_default",
                    "date_type": None,
                    "due_on": (today_date + timedelta(days=30)).isoformat(),
                },
            },
        ],
        "needs_attention": [
            {
                "name": "Hackfleisch",
                "quantity": "500 g",
                "category": "Molkerei",
                "location": "Kühlschrank",
                "freshness": {
                    "state": "urgent",
                    "source": "exact_date",
                    "date_type": "use_by",
                    "due_on": today_date.isoformat(),
                },
            }
        ],
        "upcoming": [
            {
                "name": "Joghurt",
                "quantity": "2 Becher",
                "category": "Molkerei",
                "location": "Kühlschrank",
                "freshness": {
                    "state": "soon",
                    "source": "exact_date",
                    "date_type": "best_before",
                    "due_on": today_date.isoformat(),
                },
            },
            {
                "name": "Bananen",
                "quantity": "6 Stück",
                "category": "Obst & Gemüse",
                "location": "Vorratsschrank",
                "freshness": {
                    "state": "soon",
                    "source": "category_default",
                    "date_type": None,
                    "due_on": (today_date + timedelta(days=2)).isoformat(),
                },
            },
        ],
        "shopping_suggestions": [],
    }


def test_today_dashboard_omits_depleted_and_discarded_batches_from_inventory_and_attention() -> None:
    settings, _ = create_test_settings("today-active-only.sqlite3")
    today_date = utc_now().date()

    with TestClient(create_app(settings)) as client:
        token = authenticate(client)
        confirm_response = client.post(
            "/api/text-capture/confirm",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "drafts": [
                    {
                        "name": "Pasta",
                        "quantity": "1 Packung",
                        "category": "Vorrat",
                        "location": "Vorratsschrank",
                    },
                    {
                        "name": "Hackfleisch",
                        "quantity": "500 g",
                        "category": "Molkerei",
                        "location": "Kühlschrank",
                        "date_type": "use_by",
                        "expires_on": today_date.isoformat(),
                    },
                    {
                        "name": "Joghurt",
                        "quantity": "2 Becher",
                        "category": "Molkerei",
                        "location": "Kühlschrank",
                        "date_type": "best_before",
                        "expires_on": today_date.isoformat(),
                    },
                ]
            },
        )
        assert confirm_response.status_code == 200

        batches_response = client.get(
            "/api/batches",
            headers={"Authorization": f"Bearer {token}"},
        )
        batches = batches_response.json()["batches"]
        depleted_batch_id = next(batch["id"] for batch in batches if batch["name"] == "Hackfleisch")
        discarded_batch_id = next(batch["id"] for batch in batches if batch["name"] == "Joghurt")

        depleted_response = client.post(
            f"/api/batches/{depleted_batch_id}/actions",
            headers={"Authorization": f"Bearer {token}"},
            json={"action": "use_up"},
        )
        repeated_depleted_response = client.post(
            f"/api/batches/{depleted_batch_id}/actions",
            headers={"Authorization": f"Bearer {token}"},
            json={"action": "use_up"},
        )
        discarded_response = client.post(
            f"/api/batches/{discarded_batch_id}/actions",
            headers={"Authorization": f"Bearer {token}"},
            json={"action": "discard"},
        )
        repeated_discarded_response = client.post(
            f"/api/batches/{discarded_batch_id}/actions",
            headers={"Authorization": f"Bearer {token}"},
            json={"action": "discard"},
        )
        today_response = client.get(
            "/api/today",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert depleted_response.status_code == 200
    assert depleted_response.json()["state"] == "depleted"
    assert repeated_depleted_response.status_code == 422
    assert repeated_depleted_response.json() == {"detail": "Batch action not allowed"}
    assert discarded_response.status_code == 200
    assert discarded_response.json()["state"] == "discarded"
    assert repeated_discarded_response.status_code == 422
    assert repeated_discarded_response.json() == {"detail": "Batch action not allowed"}
    assert today_response.status_code == 200
    assert today_response.json()["sections"] == {
        "inventory": [
            {
                "name": "Pasta",
                "quantity": "1 Packung",
                "category": "Vorrat",
                "location": "Vorratsschrank",
                "freshness": {
                    "state": "normal",
                    "source": "category_default",
                    "date_type": None,
                    "due_on": (today_date + timedelta(days=30)).isoformat(),
                },
            }
        ],
        "needs_attention": [],
        "upcoming": [],
        "shopping_suggestions": [
            {
                "id": today_response.json()["sections"]["shopping_suggestions"][0]["id"],
                "product_key": "hackfleisch",
                "name": "Hackfleisch",
                "quantity": "500 g",
                "source_action": "used_up",
                "source_batch_name": "Hackfleisch",
                "accepted_at": None,
                "accepted_list_id": None,
            },
            {
                "id": today_response.json()["sections"]["shopping_suggestions"][1]["id"],
                "product_key": "joghurt",
                "name": "Joghurt",
                "quantity": "2 Becher",
                "source_action": "discarded",
                "source_batch_name": "Joghurt",
                "accepted_at": None,
                "accepted_list_id": None,
            },
        ],
    }


def test_opened_batches_use_opened_at_for_category_freshness() -> None:
    settings, database_path = create_test_settings("today-opened-freshness.sqlite3")
    today_date = utc_now().date()
    stale_created_at = (utc_now() - timedelta(days=31)).isoformat()

    with TestClient(create_app(settings)) as client:
        token = authenticate(client)
        confirm_response = client.post(
            "/api/text-capture/confirm",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "drafts": [
                    {
                        "name": "Pasta",
                        "quantity": "1 Packung",
                        "category": "Vorrat",
                        "location": "Vorratsschrank",
                    }
                ]
            },
        )
        assert confirm_response.status_code == 200

        batches_response = client.get(
            "/api/batches",
            headers={"Authorization": f"Bearer {token}"},
        )
        batch_id = batches_response.json()["batches"][0]["id"]
        update_batch_created_at(database_path, batch_id, stale_created_at)

        open_response = client.post(
            f"/api/batches/{batch_id}/actions",
            headers={"Authorization": f"Bearer {token}"},
            json={"action": "open"},
        )
        today_response = client.get(
            "/api/today",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert open_response.status_code == 200
    assert open_response.json()["state"] == "opened"
    assert today_response.status_code == 200
    assert today_response.json()["sections"]["inventory"] == [
        {
            "name": "Pasta",
            "quantity": "1 Packung",
            "category": "Vorrat",
            "location": "Vorratsschrank",
            "freshness": {
                "state": "normal",
                "source": "category_default",
                "date_type": None,
                "due_on": (today_date + timedelta(days=30)).isoformat(),
            },
        }
    ]
    assert today_response.json()["sections"]["needs_attention"] == []
    assert today_response.json()["sections"]["upcoming"] == []


def test_household_can_manage_category_freshness_overrides_for_today_dashboard() -> None:
    settings, _ = create_test_settings("today-freshness-overrides.sqlite3")
    today_date = utc_now().date()

    with TestClient(create_app(settings)) as client:
        token = authenticate(client)

        list_response = client.get(
            "/api/freshness-overrides",
            headers={"Authorization": f"Bearer {token}"},
        )
        save_response = client.put(
            "/api/freshness-overrides/Obst%20%26%20Gem%C3%BCse",
            headers={"Authorization": f"Bearer {token}"},
            json={"shelf_life_days": 0, "soon_window_days": 0},
        )
        confirm_response = client.post(
            "/api/text-capture/confirm",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "drafts": [
                    {
                        "name": "Bananen",
                        "quantity": "6 Stück",
                        "category": "Obst & Gemüse",
                        "location": "Vorratsschrank",
                    }
                ]
            },
        )
        today_response = client.get(
            "/api/today",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert list_response.status_code == 200
    assert list_response.json()["policies"] == [
        {
            "category": "Getränke",
            "default_shelf_life_days": 14,
            "default_soon_window_days": 4,
            "shelf_life_days": 14,
            "soon_window_days": 4,
            "is_override": False,
        },
        {
            "category": "Molkerei",
            "default_shelf_life_days": 7,
            "default_soon_window_days": 3,
            "shelf_life_days": 7,
            "soon_window_days": 3,
            "is_override": False,
        },
        {
            "category": "Obst & Gemüse",
            "default_shelf_life_days": 2,
            "default_soon_window_days": 2,
            "shelf_life_days": 2,
            "soon_window_days": 2,
            "is_override": False,
        },
        {
            "category": "Sonstiges",
            "default_shelf_life_days": 7,
            "default_soon_window_days": 3,
            "shelf_life_days": 7,
            "soon_window_days": 3,
            "is_override": False,
        },
        {
            "category": "Vorrat",
            "default_shelf_life_days": 30,
            "default_soon_window_days": 5,
            "shelf_life_days": 30,
            "soon_window_days": 5,
            "is_override": False,
        },
    ]
    assert save_response.status_code == 200
    assert save_response.json() == {
        "category": "Obst & Gemüse",
        "default_shelf_life_days": 2,
        "default_soon_window_days": 2,
        "shelf_life_days": 0,
        "soon_window_days": 0,
        "is_override": True,
    }
    assert confirm_response.status_code == 200
    assert today_response.status_code == 200
    assert today_response.json()["sections"]["needs_attention"] == [
        {
            "name": "Bananen",
            "quantity": "6 Stück",
            "category": "Obst & Gemüse",
            "location": "Vorratsschrank",
            "freshness": {
                "state": "urgent",
                "source": "household_override",
                "date_type": None,
                "due_on": today_date.isoformat(),
            },
        }
    ]


def test_app_migrates_legacy_sqlite_schema_for_freshness_dates_and_overrides() -> None:
    settings, database_path = create_test_settings("legacy-freshness-schema.sqlite3")
    create_legacy_schema(database_path)
    today_date = utc_now().date()

    with TestClient(create_app(settings)) as client:
        token = authenticate(client)
        save_override_response = client.put(
            "/api/freshness-overrides/Obst%20%26%20Gem%C3%BCse",
            headers={"Authorization": f"Bearer {token}"},
            json={"shelf_life_days": 0, "soon_window_days": 0},
        )
        confirm_response = client.post(
            "/api/text-capture/confirm",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "drafts": [
                    {
                        "name": "Hackfleisch",
                        "quantity": "500 g",
                        "category": "Molkerei",
                        "location": "Kühlschrank",
                        "date_type": "use_by",
                        "expires_on": today_date.isoformat(),
                    },
                    {
                        "name": "Bananen",
                        "quantity": "6 Stück",
                        "category": "Obst & Gemüse",
                        "location": "Vorratsschrank",
                    },
                ]
            },
        )
        today_response = client.get(
            "/api/today",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert save_override_response.status_code == 200
    assert confirm_response.status_code == 200
    assert today_response.status_code == 200
    assert today_response.json()["sections"]["needs_attention"] == [
        {
            "name": "Hackfleisch",
            "quantity": "500 g",
            "category": "Molkerei",
            "location": "Kühlschrank",
            "freshness": {
                "state": "urgent",
                "source": "exact_date",
                "date_type": "use_by",
                "due_on": today_date.isoformat(),
            },
        },
        {
            "name": "Bananen",
            "quantity": "6 Stück",
            "category": "Obst & Gemüse",
            "location": "Vorratsschrank",
            "freshness": {
                "state": "urgent",
                "source": "household_override",
                "date_type": None,
                "due_on": today_date.isoformat(),
            },
        },
    ]


def test_worker_processes_join_jobs_once() -> None:
    settings, _ = create_test_settings("worker-jobs.sqlite3")

    with TestClient(create_app(settings)) as client:
        response = client.post(
            "/api/auth/household-session",
            json={"household_name": "WG Abendbrot", "member_name": "Lea"},
        )

    assert response.status_code == 200
    assert asyncio.run(process_pending_jobs_once(settings)) == 1
    assert asyncio.run(process_pending_jobs_once(settings)) == 0


class FakePackagePhotoExtractor:
    def __init__(self) -> None:
        self.calls = 0

    async def extract(self, *, filename: str, content_type: str, content: bytes) -> list[dict]:
        self.calls += 1
        return [
            {
                "name": "Bio-Milch",
                "quantity": "1 Flasche",
                "category": "Molkerei",
                "location": "Kühlschrank",
                "date_type": "best_before",
                "expires_on": utc_now().date().isoformat(),
                "requires_date_review": False,
            }
        ]


def test_worker_processes_pending_jobs_across_queues_once() -> None:
    settings, _ = create_test_settings("worker-mixed-queues.sqlite3")
    extractor = FakePackagePhotoExtractor()
    today = utc_now().date()

    with TestClient(create_app(settings, package_photo_extractor=extractor)) as client:
        token = authenticate(client)
        photo_response = client.post(
            "/api/package-photo/drafts",
            headers={"Authorization": f"Bearer {token}"},
            files={"photo": ("milch-label.jpg", b"fake-image-bytes", "image/jpeg")},
        )
        confirm_response = client.post(
            "/api/text-capture/confirm",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "drafts": [
                    {
                        "name": "Hackfleisch",
                        "quantity": "500 g",
                        "category": "Molkerei",
                        "location": "Kühlschrank",
                        "date_type": "use_by",
                        "expires_on": today.isoformat(),
                    }
                ]
            },
        )
        settings_response = client.put(
            "/api/reminder-settings",
            headers={"Authorization": f"Bearer {token}"},
            json={"daily_digest_enabled": True, "urgent_push_enabled": True},
        )
        processed_jobs = asyncio.run(process_pending_jobs_once(settings, extractor))
        reminders_response = client.get(
            "/api/reminders",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert photo_response.status_code == 200
    assert confirm_response.status_code == 200
    assert settings_response.status_code == 200
    assert extractor.calls == 1
    assert processed_jobs == 4
    assert reminders_response.status_code == 200
    assert {delivery["kind"] for delivery in reminders_response.json()["deliveries"]} == {
        "daily_digest",
        "urgent_push",
    }
