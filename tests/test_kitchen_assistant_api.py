from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from freshbot_butler.api.main import create_app
from freshbot_butler.api.models import utc_now
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


def test_kitchen_assistant_answers_read_only_questions_about_what_should_be_used_soon() -> None:
    settings, _ = create_test_settings("kitchen-assistant-soon.sqlite3")
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
                        "expires_on": (today + timedelta(days=1)).isoformat(),
                    },
                    {
                        "name": "Joghurt",
                        "quantity": "2 Becher",
                        "category": "Molkerei",
                        "location": "Kühlschrank",
                        "date_type": "best_before",
                        "expires_on": (today + timedelta(days=2)).isoformat(),
                    },
                ]
            },
        )
        assert confirm_response.status_code == 200

        before_response = client.get("/api/today", headers={"Authorization": f"Bearer {token}"})
        assistant_response = client.post(
            "/api/kitchen-assistant/query",
            headers={"Authorization": f"Bearer {token}"},
            json={"question": "Was sollten wir bald nutzen?"},
        )
        named_response = client.post(
            "/api/kitchen-assistant/query",
            headers={"Authorization": f"Bearer {token}"},
            json={"question": "Was sollten wir für Joghurt bald nutzen?"},
        )
        after_response = client.get("/api/today", headers={"Authorization": f"Bearer {token}"})

    assert before_response.status_code == 200
    assert assistant_response.status_code == 200
    assert assistant_response.json() == {
        "question": "Was sollten wir bald nutzen?",
        "answer": "Ihr solltet zuerst Hackfleisch nutzen. Bald dran: Joghurt.",
        "topic": "soon_items",
        "needs_clarification": False,
    }
    assert named_response.status_code == 200
    assert named_response.json() == {
        "question": "Was sollten wir für Joghurt bald nutzen?",
        "answer": "Joghurt ist bald dran.",
        "topic": "soon_items",
        "needs_clarification": False,
    }
    assert after_response.json() == before_response.json()


def test_kitchen_assistant_named_soon_questions_stick_to_the_named_item() -> None:
    settings, _ = create_test_settings("kitchen-assistant-named-soon.sqlite3")
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
                        "expires_on": (today + timedelta(days=1)).isoformat(),
                    },
                    {
                        "name": "Joghurt",
                        "quantity": "2 Becher",
                        "category": "Molkerei",
                        "location": "Kühlschrank",
                        "date_type": "best_before",
                        "expires_on": (today + timedelta(days=10)).isoformat(),
                    },
                ]
            },
        )
        assert confirm_response.status_code == 200

        generic_response = client.post(
            "/api/kitchen-assistant/query",
            headers={"Authorization": f"Bearer {token}"},
            json={"question": "Was sollten wir bald nutzen?"},
        )
        named_response = client.post(
            "/api/kitchen-assistant/query",
            headers={"Authorization": f"Bearer {token}"},
            json={"question": "Was sollten wir für Joghurt bald nutzen?"},
        )
        missing_response = client.post(
            "/api/kitchen-assistant/query",
            headers={"Authorization": f"Bearer {token}"},
            json={"question": "Was sollten wir für Milch bald nutzen?"},
        )

    assert generic_response.status_code == 200
    assert generic_response.json() == {
        "question": "Was sollten wir bald nutzen?",
        "answer": "Ihr solltet zuerst Hackfleisch nutzen.",
        "topic": "soon_items",
        "needs_clarification": False,
    }
    assert named_response.status_code == 200
    assert named_response.json() == {
        "question": "Was sollten wir für Joghurt bald nutzen?",
        "answer": "Joghurt ist aktuell kein bald zu nutzender Artikel.",
        "topic": "soon_items",
        "needs_clarification": False,
    }
    assert missing_response.status_code == 200
    assert missing_response.json() == {
        "question": "Was sollten wir für Milch bald nutzen?",
        "answer": "Ich finde Milch nicht im aktuellen Inventar. Meint ihr einen anderen Artikel?",
        "topic": "soon_items",
        "needs_clarification": True,
    }


def test_kitchen_assistant_handles_missing_inventory_items_clearly() -> None:
    settings, _ = create_test_settings("kitchen-assistant-missing.sqlite3")

    with TestClient(create_app(settings)) as client:
        token = authenticate(client)
        confirm_response = client.post(
            "/api/text-capture/confirm",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "drafts": [
                    {
                        "name": "Penne",
                        "quantity": "1 Packung",
                        "category": "Vorrat",
                        "location": "Vorratsschrank",
                    }
                ]
            },
        )
        assert confirm_response.status_code == 200

        assistant_response = client.post(
            "/api/kitchen-assistant/query",
            headers={"Authorization": f"Bearer {token}"},
            json={"question": "Haben wir Milch?"},
        )

    assert assistant_response.status_code == 200
    assert assistant_response.json() == {
        "question": "Haben wir Milch?",
        "answer": "Ich finde Milch nicht im aktuellen Inventar. Auf keiner Einkaufsliste steht Milch.",
        "topic": "inventory_presence",
        "needs_clarification": False,
    }


def test_kitchen_assistant_reports_missing_freshness_items_with_clarification() -> None:
    settings, _ = create_test_settings("kitchen-assistant-missing-freshness.sqlite3")

    with TestClient(create_app(settings)) as client:
        token = authenticate(client)
        confirm_response = client.post(
            "/api/text-capture/confirm",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "drafts": [
                    {
                        "name": "Penne",
                        "quantity": "1 Packung",
                        "category": "Vorrat",
                        "location": "Vorratsschrank",
                    }
                ]
            },
        )
        assert confirm_response.status_code == 200

        assistant_response = client.post(
            "/api/kitchen-assistant/query",
            headers={"Authorization": f"Bearer {token}"},
            json={"question": "Wie frisch ist Milch?"},
        )

    assert assistant_response.status_code == 200
    assert assistant_response.json() == {
        "question": "Wie frisch ist Milch?",
        "answer": "Ich finde Milch nicht im aktuellen Inventar. Meint ihr einen anderen Artikel?",
        "topic": "freshness_status",
        "needs_clarification": True,
    }


def test_kitchen_assistant_asks_for_clarification_when_freshness_match_is_ambiguous() -> None:
    settings, _ = create_test_settings("kitchen-assistant-ambiguous-freshness.sqlite3")
    today = utc_now().date()

    with TestClient(create_app(settings)) as client:
        token = authenticate(client)
        confirm_response = client.post(
            "/api/text-capture/confirm",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "drafts": [
                    {
                        "name": "Milch",
                        "quantity": "1 Liter",
                        "category": "Molkerei",
                        "location": "Kühlschrank",
                        "date_type": "best_before",
                        "expires_on": (today + timedelta(days=1)).isoformat(),
                    },
                    {
                        "name": "Milch",
                        "quantity": "500 ml",
                        "category": "Molkerei",
                        "location": "Kühlschrank",
                        "date_type": "best_before",
                        "expires_on": (today + timedelta(days=3)).isoformat(),
                    },
                ]
            },
        )
        assert confirm_response.status_code == 200

        assistant_response = client.post(
            "/api/kitchen-assistant/query",
            headers={"Authorization": f"Bearer {token}"},
            json={"question": "Wie frisch ist Milch?"},
        )

    assert assistant_response.status_code == 200
    assert assistant_response.json() == {
        "question": "Wie frisch ist Milch?",
        "answer": "Ich finde mehrere mögliche Treffer: Milch, Milch. Könnt ihr einen davon genauer benennen?",
        "topic": "freshness_status",
        "needs_clarification": True,
    }
