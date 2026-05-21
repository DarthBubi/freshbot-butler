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


def test_household_members_can_create_rename_and_manage_multiple_shopping_lists() -> None:
    settings, _ = create_test_settings("shopping-lists.sqlite3")

    with TestClient(create_app(settings)) as client:
        token = authenticate(client)

        created_response = client.post(
            "/api/shopping-lists",
            headers={"Authorization": f"Bearer {token}"},
            json={"name": "Wochenende"},
        )
        assert created_response.status_code == 200
        created_list = created_response.json()["lists"][0]
        assert created_list["name"] == "Wochenende"
        assert created_list["items"] == []

        renamed_response = client.put(
            f"/api/shopping-lists/{created_list['id']}",
            headers={"Authorization": f"Bearer {token}"},
            json={"name": "Einkauf für Samstag"},
        )
        assert renamed_response.status_code == 200
        assert renamed_response.json()["lists"][0]["name"] == "Einkauf für Samstag"

        item_response = client.post(
            f"/api/shopping-lists/{created_list['id']}/items",
            headers={"Authorization": f"Bearer {token}"},
            json={"name": "Haferdrink", "quantity": "2 Packungen"},
        )
        assert item_response.status_code == 200
        assert item_response.json()["lists"][0]["items"] == [
            {
                "id": item_response.json()["lists"][0]["items"][0]["id"],
                "product_key": "haferdrink",
                "name": "Haferdrink",
                "quantity": "2 Packungen",
            }
        ]

        lists_response = client.get("/api/shopping-lists", headers={"Authorization": f"Bearer {token}"})
        assert lists_response.status_code == 200
        assert lists_response.json()["lists"][0]["name"] == "Einkauf für Samstag"
        assert lists_response.json()["lists"][0]["items"][0]["product_key"] == "haferdrink"


def test_use_up_events_create_optional_replenishment_suggestions_that_can_be_accepted_into_a_list() -> None:
    settings, _ = create_test_settings("shopping-suggestions.sqlite3")

    with TestClient(create_app(settings)) as client:
        token = authenticate(client)

        list_response = client.post(
            "/api/shopping-lists",
            headers={"Authorization": f"Bearer {token}"},
            json={"name": "Samstag"},
        )
        list_id = list_response.json()["lists"][0]["id"]

        draft_response = client.post(
            "/api/text-capture/drafts",
            headers={"Authorization": f"Bearer {token}"},
            json={"input_text": "2 Bio Milch im Kühlschrank"},
        )
        batch_response = client.post(
            "/api/text-capture/confirm",
            headers={"Authorization": f"Bearer {token}"},
            json={"drafts": draft_response.json()["drafts"]},
        )
        batch_id = batch_response.json()["batches"][0]["name"]

        batches_response = client.get("/api/batches", headers={"Authorization": f"Bearer {token}"})
        batch_id = batches_response.json()["batches"][0]["id"]

        action_response = client.post(
            f"/api/batches/{batch_id}/actions",
            headers={"Authorization": f"Bearer {token}"},
            json={"action": "use_up"},
        )
        assert action_response.status_code == 200

        today_response = client.get("/api/today", headers={"Authorization": f"Bearer {token}"})
        suggestions = today_response.json()["sections"]["shopping_suggestions"]
        assert suggestions == [
            {
                "id": suggestions[0]["id"],
                "product_key": "bio-milch",
                "name": "Bio Milch",
                "quantity": "2",
                "source_action": "used_up",
                "source_batch_name": "Bio Milch",
                "accepted_at": None,
                "accepted_list_id": None,
            }
        ]

        accept_response = client.post(
            f"/api/shopping-suggestions/{suggestions[0]['id']}/accept",
            headers={"Authorization": f"Bearer {token}"},
            json={"list_id": list_id},
        )
        assert accept_response.status_code == 200

        repopulated_response = client.post(
            f"/api/shopping-lists/{list_id}/items",
            headers={"Authorization": f"Bearer {token}"},
            json={"name": "Bio-Milch", "quantity": "3"},
        )
        assert repopulated_response.status_code == 200
        items = repopulated_response.json()["lists"][0]["items"]
        assert items == [
            {
                "id": items[0]["id"],
                "product_key": "bio-milch",
                "name": "Bio-Milch",
                "quantity": "3",
            }
        ]


def test_decrement_to_zero_events_create_optional_replenishment_suggestions_that_can_be_accepted_into_a_list() -> None:
    settings, _ = create_test_settings("shopping-suggestions-decrement.sqlite3")

    with TestClient(create_app(settings)) as client:
        token = authenticate(client)

        list_response = client.post(
            "/api/shopping-lists",
            headers={"Authorization": f"Bearer {token}"},
            json={"name": "Samstag"},
        )
        list_id = list_response.json()["lists"][0]["id"]

        draft_response = client.post(
            "/api/text-capture/drafts",
            headers={"Authorization": f"Bearer {token}"},
            json={"input_text": "1 Bio Milch im Kühlschrank"},
        )
        batch_response = client.post(
            "/api/text-capture/confirm",
            headers={"Authorization": f"Bearer {token}"},
            json={"drafts": draft_response.json()["drafts"]},
        )
        batch_id = batch_response.json()["batches"][0]["name"]

        batches_response = client.get("/api/batches", headers={"Authorization": f"Bearer {token}"})
        batch_id = batches_response.json()["batches"][0]["id"]

        action_response = client.post(
            f"/api/batches/{batch_id}/actions",
            headers={"Authorization": f"Bearer {token}"},
            json={"action": "decrement"},
        )
        assert action_response.status_code == 200

        today_response = client.get("/api/today", headers={"Authorization": f"Bearer {token}"})
        suggestions = today_response.json()["sections"]["shopping_suggestions"]
        assert suggestions == [
            {
                "id": suggestions[0]["id"],
                "product_key": "bio-milch",
                "name": "Bio Milch",
                "quantity": "1",
                "source_action": "used_up",
                "source_batch_name": "Bio Milch",
                "accepted_at": None,
                "accepted_list_id": None,
            }
        ]

        accept_response = client.post(
            f"/api/shopping-suggestions/{suggestions[0]['id']}/accept",
            headers={"Authorization": f"Bearer {token}"},
            json={"list_id": list_id},
        )
        assert accept_response.status_code == 200

        repopulated_response = client.post(
            f"/api/shopping-lists/{list_id}/items",
            headers={"Authorization": f"Bearer {token}"},
            json={"name": "Bio-Milch", "quantity": "3"},
        )
        assert repopulated_response.status_code == 200
        items = repopulated_response.json()["lists"][0]["items"]
        assert items == [
            {
                "id": items[0]["id"],
                "product_key": "bio-milch",
                "name": "Bio-Milch",
                "quantity": "3",
            }
        ]
