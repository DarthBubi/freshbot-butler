from datetime import timedelta

from freshbot_butler.api.freshness import assess_batch_freshness
from freshbot_butler.api.models import Batch, utc_now
from freshbot_butler.api.reminders import (
    ReminderSettings,
    build_reminder_digest,
    select_reminder_delivery,
)


def test_builds_daily_digest_and_delivery_plan_from_freshness_state() -> None:
    today = utc_now().date()
    batches = [
        Batch(
            id="batch-urgent",
            household_id="household-1",
            name="Hackfleisch",
            quantity="500 g",
            category="Molkerei",
            location="Kühlschrank",
            date_type="use_by",
            expires_on=today,
            created_at=utc_now(),
        ),
        Batch(
            id="batch-soon",
            household_id="household-1",
            name="Joghurt",
            quantity="2 Becher",
            category="Molkerei",
            location="Kühlschrank",
            date_type="best_before",
            expires_on=today + timedelta(days=1),
            created_at=utc_now(),
        ),
        Batch(
            id="batch-category",
            household_id="household-1",
            name="Bananen",
            quantity="6 Stück",
            category="Obst & Gemüse",
            location="Vorratsschrank",
            created_at=utc_now(),
        ),
    ]

    digest = build_reminder_digest(batches, today=today)

    assert [item.name for item in digest.urgent_items] == ["Hackfleisch"]
    assert [item.name for item in digest.soon_items] == ["Joghurt", "Bananen"]
    assert digest.summary == "1 dringende und 2 baldige Frischehinweise"
    assert digest.urgent_items[0].freshness.state == "urgent"
    assert digest.soon_items[0].freshness.state == "soon"
    assert digest.soon_items[1].freshness == assess_batch_freshness(batches[2], today=today)

    delivery = select_reminder_delivery(
        ReminderSettings(daily_digest_enabled=True, urgent_push_enabled=True),
        digest,
    )

    assert delivery.daily_digest_delivery == "in_app"
    assert delivery.urgent_push_delivery == "web_push"
    assert [item.name for item in delivery.urgent_push_candidates] == ["Hackfleisch"]

    quiet_delivery = select_reminder_delivery(
        ReminderSettings(daily_digest_enabled=False, urgent_push_enabled=False),
        digest,
    )

    assert quiet_delivery.daily_digest_delivery == "quiet"
    assert quiet_delivery.urgent_push_delivery == "quiet"
    assert quiet_delivery.urgent_push_candidates == []
