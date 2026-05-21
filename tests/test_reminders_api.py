import asyncio
import sqlite3
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

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


def authenticate(client: TestClient) -> str:
    response = client.post(
        "/api/auth/household-session",
        json={"household_name": "WG Sonnenseite", "member_name": "Johannes"},
    )
    assert response.status_code == 200
    return response.json()["token"]


def queue_reminder_job(client: TestClient, token: str, expires_on: str) -> None:
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
                    "expires_on": expires_on,
                }
            ]
        },
    )
    assert confirm_response.status_code == 200


def duplicate_pending_reminder_job(database_path: Path) -> None:
    with sqlite3.connect(database_path) as connection:
        row = connection.execute(
            """
            SELECT queue_name, payload, status, created_at
            FROM jobs
            WHERE queue_name = 'reminder-delivery'
              AND status = 'pending'
            ORDER BY created_at ASC, id ASC
            LIMIT 1
            """
        ).fetchone()
        assert row is not None
        queue_name, payload, status, created_at = row
        connection.execute(
            """
            INSERT INTO jobs (id, queue_name, payload, status, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (str(uuid4()), queue_name, payload, status, created_at),
        )
        connection.commit()


def get_batch_id(client: TestClient, token: str, batch_name: str) -> str:
    batches_response = client.get(
        "/api/batches",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert batches_response.status_code == 200
    batches = batches_response.json()["batches"]
    batch = next(batch for batch in batches if batch["name"] == batch_name)
    return batch["id"]


def test_household_can_view_and_dispatch_freshness_reminders() -> None:
    settings, _ = create_test_settings("reminders-api.sqlite3")
    today = utc_now().date()

    with TestClient(create_app(settings)) as client:
        token = authenticate(client)
        settings_response = client.put(
            "/api/reminder-settings",
            headers={"Authorization": f"Bearer {token}"},
            json={"daily_digest_enabled": True, "urgent_push_enabled": True},
        )
        assert asyncio.run(process_pending_jobs_once(settings)) == 1

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
                    },
                    {
                        "name": "Joghurt",
                        "quantity": "2 Becher",
                        "category": "Molkerei",
                        "location": "Kühlschrank",
                        "date_type": "best_before",
                        "expires_on": (today + timedelta(days=1)).isoformat(),
                    },
                ]
            },
        )
        preview_response = client.get(
            "/api/reminders",
            headers={"Authorization": f"Bearer {token}"},
        )
        preview = preview_response.json()
        assert preview["deliveries"] == []
        processed_jobs = asyncio.run(process_pending_jobs_once(settings))
        delivered_response = client.get(
            "/api/reminders",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert confirm_response.status_code == 200
    assert settings_response.status_code == 200
    assert settings_response.json() == {
        "daily_digest_enabled": True,
        "urgent_push_enabled": True,
    }
    assert preview_response.status_code == 200
    assert preview["settings"] == {
        "daily_digest_enabled": True,
        "urgent_push_enabled": True,
    }
    assert preview["digest"]["summary"] == "1 dringende und 1 baldige Frischehinweise"
    assert [item["name"] for item in preview["digest"]["urgent_items"]] == ["Hackfleisch"]
    assert [item["name"] for item in preview["digest"]["soon_items"]] == ["Joghurt"]
    assert preview["delivery"] == {
        "daily_digest_delivery": "in_app",
        "urgent_push_delivery": "web_push",
        "urgent_push_candidates": preview["delivery"]["urgent_push_candidates"],
    }
    assert [item["name"] for item in preview["delivery"]["urgent_push_candidates"]] == ["Hackfleisch"]
    assert processed_jobs == 2
    assert delivered_response.status_code == 200
    assert {delivery["kind"] for delivery in delivered_response.json()["deliveries"]} == {
        "daily_digest",
        "urgent_push",
    }
    assert {delivery["channel"] for delivery in delivered_response.json()["deliveries"]} == {
        "in_app",
        "web_push",
    }


def test_pending_reminder_jobs_do_not_deliver_after_settings_are_disabled() -> None:
    settings, _ = create_test_settings("reminders-disabled.sqlite3")
    today = utc_now().date()

    with TestClient(create_app(settings)) as client:
        token = authenticate(client)
        assert asyncio.run(process_pending_jobs_once(settings)) == 1
        queue_reminder_job(client, token, today.isoformat())

        settings_response = client.put(
            "/api/reminder-settings",
            headers={"Authorization": f"Bearer {token}"},
            json={"daily_digest_enabled": False, "urgent_push_enabled": False},
        )
        processed_jobs = asyncio.run(process_pending_jobs_once(settings))
        reminders_response = client.get(
            "/api/reminders",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert settings_response.status_code == 200
    assert settings_response.json() == {
        "daily_digest_enabled": False,
        "urgent_push_enabled": False,
    }
    assert processed_jobs == 1
    assert reminders_response.status_code == 200
    assert reminders_response.json()["deliveries"] == []


def test_pending_reminder_jobs_do_not_block_newly_enabled_delivery_paths() -> None:
    settings, _ = create_test_settings("reminders-new-channel.sqlite3")
    today = utc_now().date()

    with TestClient(create_app(settings)) as client:
        token = authenticate(client)
        initial_settings_response = client.put(
            "/api/reminder-settings",
            headers={"Authorization": f"Bearer {token}"},
            json={"daily_digest_enabled": False, "urgent_push_enabled": True},
        )
        assert asyncio.run(process_pending_jobs_once(settings)) == 1
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
                    },
                    {
                        "name": "Joghurt",
                        "quantity": "2 Becher",
                        "category": "Molkerei",
                        "location": "Kühlschrank",
                        "date_type": "best_before",
                        "expires_on": (today + timedelta(days=1)).isoformat(),
                    },
                ]
            },
        )
        enable_digest_response = client.put(
            "/api/reminder-settings",
            headers={"Authorization": f"Bearer {token}"},
            json={"daily_digest_enabled": True, "urgent_push_enabled": True},
        )
        processed_jobs = asyncio.run(process_pending_jobs_once(settings))
        reminders_response = client.get(
            "/api/reminders",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert initial_settings_response.status_code == 200
    assert initial_settings_response.json() == {
        "daily_digest_enabled": False,
        "urgent_push_enabled": True,
    }
    assert confirm_response.status_code == 200
    assert enable_digest_response.status_code == 200
    assert enable_digest_response.json() == {
        "daily_digest_enabled": True,
        "urgent_push_enabled": True,
    }
    assert processed_jobs == 2
    assert reminders_response.status_code == 200
    assert {delivery["kind"] for delivery in reminders_response.json()["deliveries"]} == {
        "daily_digest",
        "urgent_push",
    }


def test_pending_reminder_jobs_use_current_freshness_state_when_processed() -> None:
    settings, _ = create_test_settings("reminders-stale-state.sqlite3")
    today = utc_now().date()

    with TestClient(create_app(settings)) as client:
        token = authenticate(client)
        assert asyncio.run(process_pending_jobs_once(settings)) == 1
        queue_reminder_job(client, token, today.isoformat())
        batch_id = get_batch_id(client, token, "Hackfleisch")

        act_response = client.post(
            f"/api/batches/{batch_id}/actions",
            headers={"Authorization": f"Bearer {token}"},
            json={"action": "use_up"},
        )
        processed_jobs = asyncio.run(process_pending_jobs_once(settings))
        reminders_response = client.get(
            "/api/reminders",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert act_response.status_code == 200
    assert act_response.json()["state"] == "depleted"
    assert processed_jobs == 1
    assert reminders_response.status_code == 200
    assert reminders_response.json()["digest"]["summary"] == "Keine Frischehinweise heute"
    assert reminders_response.json()["deliveries"] == []


def test_duplicate_reminder_jobs_only_deliver_once() -> None:
    settings, database_path = create_test_settings("reminders-duplicate-job.sqlite3")
    today = utc_now().date()

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
                        "expires_on": today.isoformat(),
                    }
                ]
            },
        )
        settings_response = client.put(
            "/api/reminder-settings",
            headers={"Authorization": f"Bearer {token}"},
            json={"daily_digest_enabled": True, "urgent_push_enabled": False},
        )
        duplicate_pending_reminder_job(database_path)
        processed_jobs = asyncio.run(process_pending_jobs_once(settings))
        reminders_response = client.get(
            "/api/reminders",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert confirm_response.status_code == 200
    assert settings_response.status_code == 200
    assert processed_jobs == 3
    assert reminders_response.status_code == 200
    assert len(reminders_response.json()["deliveries"]) == 1
    assert reminders_response.json()["deliveries"][0]["kind"] == "daily_digest"
    assert reminders_response.json()["deliveries"][0]["channel"] == "in_app"
