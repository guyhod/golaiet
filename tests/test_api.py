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


@pytest.mark.django_db
def test_focus_alerts_and_stream(tracker):
    from agent import tools
    client = Client()
    assert client.get("/api/focus").json()["tracker"] is None
    tools.set_focus(tracker.slug)
    tools.raise_alert(tracker.slug, "elevated", "Shipments halted.")
    assert client.get("/api/focus").json() == {**client.get("/api/focus").json(), "tracker": tracker.slug, "view": "feed"}
    alerts = client.get("/api/alerts").json()
    assert alerts[0]["tracker"] == tracker.slug and alerts[0]["delivered_at"] is None
    listed = client.get("/api/trackers").json()[0]
    assert listed["level"] is None and listed["level_rank"] == -1
    stream = client.get("/api/focus/stream")
    assert stream["Content-Type"] == "text/event-stream"
    first = next(iter(stream.streaming_content)).decode()
    stream.close()
    assert first.startswith("event: focus\ndata: ") and f'"tracker": "{tracker.slug}"' in first
