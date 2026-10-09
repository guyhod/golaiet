import pytest
from django.test import Client


@pytest.mark.django_db
def test_health_is_stale_without_heartbeat(settings):
    settings.TELEGRAM_BOT_TOKEN = ""
    body = Client().get("/api/health").json()
    assert body["status"] == "stale" and body["telegram_configured"] is False and body["trackers"] == 0


@pytest.mark.django_db
def test_tracker_endpoints(tracker):
    from agent import tools
    tools.record_observation(tracker.slug, "2026-10-08", "https://n.example/1", "HBM supply tight", None)
    assert Client().get("/api/trackers").json()[0]["observations"] == 1
    detail = Client().get(f"/api/trackers/{tracker.slug}").json()
    assert detail["brief"] == tracker.brief and detail["recent_observations"][0]["source_url"] == "https://n.example/1"
