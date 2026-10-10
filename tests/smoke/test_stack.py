"""The deployed stack answers: run after `make stack` (and in CI against the
same compose file), pointed at the dashboard's port by SMOKE_URL. Everything
goes through nginx, so a broken proxy rule fails here and nowhere else."""
import os
import re

import httpx
import pytest

pytestmark = pytest.mark.smoke

BASE = os.environ.get("SMOKE_URL", "http://127.0.0.1:8003")
FIRST_EVENT_SEC = 5


@pytest.fixture(scope="module")
def http():
    with httpx.Client(base_url=BASE, timeout=10) as client:
        yield client


def test_health_reports_the_fields_the_dashboard_reads(http):
    body = http.get("/api/health").raise_for_status().json()
    assert body["status"] in ("ok", "stale")
    assert isinstance(body["trackers"], int) and isinstance(body["telegram_configured"], bool)


def test_tracker_and_alert_lists_answer(http):
    assert isinstance(http.get("/api/trackers").raise_for_status().json(), list)
    assert isinstance(http.get("/api/alerts?limit=1").raise_for_status().json(), list)


def test_dashboard_serves_the_built_app(http):
    html = http.get("/").raise_for_status().text
    bundle = re.search(r'<script type="module"[^>]*src="(/assets/[^"]+\.js)"', html)
    assert bundle, "index.html names no bundle: the dashboard image was built without the app"
    script = http.get(bundle.group(1)).raise_for_status()
    assert "javascript" in script.headers["content-type"]


def test_admin_and_its_static_files_are_proxied(http):
    assert "Django administration" in http.get("/admin/login/").raise_for_status().text
    assert "text/css" in http.get("/static/admin/css/base.css").raise_for_status().headers["content-type"]


def test_focus_stream_sends_its_first_event_through_nginx(http):
    with http.stream("GET", "/api/focus/stream", timeout=FIRST_EVENT_SEC) as stream:
        assert stream.headers["content-type"].startswith("text/event-stream")
        first = next(stream.iter_lines())
    assert first == "event: focus"
