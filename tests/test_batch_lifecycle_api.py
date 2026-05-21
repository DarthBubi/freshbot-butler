from __future__ import annotations

from pathlib import Path

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


def test_member_can_manage_batch_lifecycle_and_review_history() -> None:
    settings, _ = create_test_settings("batch-lifecycle.sqlite3")

    with TestClient(create_app(settings)) as client:
        token = authenticate(client)
        confirm_response = client.post(
            "/api/text-capture/confirm",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "drafts": [
                    {
                        "name": "Haferdrink",
                        "quantity": "2 Packungen",
                        "category": "Getränke",
                        "location": "Vorratsschrank",
                    },
                    {
                        "name": "Haferdrink",
                        "quantity": "2 Packungen",
                        "category": "Getränke",
                        "location": "Vorratsschrank",
                    },
                ]
            },
        )
        assert confirm_response.status_code == 200

        batches_response = client.get("/api/batches", headers={"Authorization": f"Bearer {token}"})
        assert batches_response.status_code == 200
        batches = batches_response.json()["batches"]
        assert batches[0]["quantity"] == "2 Packungen"
        assert batches_response.json()["merge_suggestions"] == [
            {
                "batch_ids": [batches[0]["id"], batches[1]["id"]],
                "name": "Haferdrink",
                "category": "Getränke",
                "location": "Vorratsschrank",
                "count": 2,
            }
        ]

        first_batch_id = batches[0]["id"]
        second_batch_id = batches[1]["id"]

        open_response = client.post(
            f"/api/batches/{first_batch_id}/actions",
            headers={"Authorization": f"Bearer {token}"},
            json={"action": "open"},
        )
        assert open_response.status_code == 200
        assert open_response.json()["state"] == "opened"

        decrement_response = client.post(
            f"/api/batches/{first_batch_id}/actions",
            headers={"Authorization": f"Bearer {token}"},
            json={"action": "decrement"},
        )
        assert decrement_response.status_code == 200
        assert decrement_response.json()["quantity"] == "1 Packung"

        use_up_response = client.post(
            f"/api/batches/{first_batch_id}/actions",
            headers={"Authorization": f"Bearer {token}"},
            json={"action": "use_up"},
        )
        assert use_up_response.status_code == 200
        assert use_up_response.json()["state"] == "depleted"

        discard_response = client.post(
            f"/api/batches/{second_batch_id}/actions",
            headers={"Authorization": f"Bearer {token}"},
            json={"action": "discard"},
        )
        assert discard_response.status_code == 200
        assert discard_response.json()["state"] == "discarded"

        history_response = client.get(
            f"/api/batches/{first_batch_id}/events",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert history_response.status_code == 200
    assert [event["action"] for event in history_response.json()["events"]] == [
        "opened",
        "decremented",
        "used_up",
    ]
