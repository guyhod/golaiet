import pytest

from agent import tools
from core.models import Observation, Tracker
from scheduler.models import Job


@pytest.mark.django_db
def test_create_tracker_makes_rows_and_collect_job(monkeypatch):
    monkeypatch.setenv("GOLAIET_MESSAGE_ID", "")
    created = tools.create_tracker("vram-supply", "VRAM supply", "topic", {"query": "GDDR7 pricing"}, "Watch prices.", "weekly")
    tracker = Tracker.objects.get(slug="vram-supply")
    assert tracker.view == "feed" and tracker.brief == "Watch prices."
    job = Job.objects.get(name="collect:vram-supply")
    assert job.tracker == tracker and job.schedule == "0 7 * * mon" and job.target == "agent.flows.collect.run"
    assert created["cadence"] == "weekly" and created["jobs"][0]["first_run_at"]


@pytest.mark.django_db
def test_create_tracker_rejects_bad_input():
    with pytest.raises(ValueError, match="cadence must be one of"):
        tools.create_tracker("a", "A", "topic", {"query": "q"}, "brief", "fortnightly")
    with pytest.raises(ValueError, match="missing required field 'query'"):
        tools.create_tracker("a", "A", "topic", {}, "brief", "daily")
    assert not Tracker.objects.exists() and not Job.objects.exists()


@pytest.mark.django_db
def test_create_tracker_twice_points_at_update(tracker):
    with pytest.raises(ValueError, match="already exists; use update_tracker"):
        tools.create_tracker(tracker.slug, "x", "topic", {"query": "q"}, "b", "daily")


@pytest.mark.django_db
def test_update_tracker_changes_cadence_on_the_job(tracker):
    Job.objects.create(name=f"collect:{tracker.slug}", kind="collect", tracker=tracker, schedule="0 7 * * mon", target="agent.flows.collect.run")
    updated = tools.update_tracker(tracker.slug, cadence="daily", status="paused")
    assert Job.objects.get(name=f"collect:{tracker.slug}").schedule == "0 7 * * *"
    assert updated["status"] == "paused" and set(updated["changed"]) == {"status", "cadence"}


@pytest.mark.django_db
def test_record_observation_validates_and_dedupes(tracker, monkeypatch):
    monkeypatch.setenv("GOLAIET_JOB_RUN_ID", "")
    first = tools.record_observation(tracker.slug, "2026-10-08", "https://news.example/a", "HBM3E prices rose 10%.", {"severity": 3, "figure": 10, "unit": "%"})
    again = tools.record_observation(tracker.slug, "2026-10-08", "https://news.example/a", "same page again", None)
    assert first["duplicate"] is False and again["duplicate"] is True and again["id"] == first["id"]
    assert Observation.objects.count() == 1
    with pytest.raises(ValueError, match="unknown fields"):
        tools.record_observation(tracker.slug, "2026-10-08", "https://news.example/b", "x", {"price": 1})
    with pytest.raises(ValueError, match="ISO date"):
        tools.record_observation(tracker.slug, "yesterday", "https://news.example/c", "x", None)


@pytest.mark.django_db
def test_search_and_get(tracker):
    tools.record_observation(tracker.slug, "2026-10-01", "https://n.example/1", "Micron raises HBM prices", None)
    tools.record_observation(tracker.slug, "2026-10-08", "https://n.example/2", "Samsung HBM supply tight", None)
    found = tools.search_observations("hbm supply")
    assert [o["source_url"] for o in found] == ["https://n.example/2"]
    assert len(tools.search_observations("hbm", since="2026-10-05")) == 1
    detail = tools.get_tracker(tracker.slug, observations=1)
    assert detail["observations"] == 2 and len(detail["recent_observations"]) == 1
    assert detail["recent_observations"][0]["source_url"] == "https://n.example/2"
    assert tools.list_trackers()[0]["slug"] == tracker.slug


@pytest.mark.django_db
def test_record_assessment_links_evidence_and_alerts_on_level_change(tracker, monkeypatch):
    from core.models import Alert, Assessment
    monkeypatch.setenv("GOLAIET_JOB_RUN_ID", "")
    observation = tools.record_observation(tracker.slug, "2026-10-08", "https://n.example/1", "HBM supply tight", None)
    first = tools.record_assessment(tracker.slug, {"level": "watch", "score": 40}, "Supply tightened on 2026-10-08.", [observation["id"]])
    assert first["evidence_ids"] == [observation["id"]]
    assert first["alert"]["level"] == "watch" and first["alert"]["text"].startswith("VRAM supply and pricing: quiet → watch.")
    same = tools.record_assessment(tracker.slug, {"level": "watch"}, "No change.", [])
    assert same["alert"] is None
    assert Assessment.objects.count() == 2 and Alert.objects.count() == 1
    with pytest.raises(ValueError, match="level must be one of"):
        tools.record_assessment(tracker.slug, {"level": "panic"}, "x", [])
    with pytest.raises(ValueError, match="not observations of vram-supply: 999"):
        tools.record_assessment(tracker.slug, {"level": "watch"}, "x", [999])
    assert tools.list_trackers()[0]["latest_assessment"]["state"] == {"level": "watch"}


@pytest.mark.django_db
def test_raise_alert_dedupes_at_same_level(tracker, monkeypatch):
    from core.models import Alert
    monkeypatch.setenv("GOLAIET_JOB_RUN_ID", "")
    first = tools.raise_alert(tracker.slug, "elevated", "Micron halted GDDR7 shipments on 2026-10-09.")
    again = tools.raise_alert(tracker.slug, "elevated", "same thing again")
    assert first["duplicate"] is False and again["duplicate"] is True and again["id"] == first["id"]
    assert tools.raise_alert(tracker.slug, "critical", "now worse")["duplicate"] is False
    assert Alert.objects.count() == 2
    with pytest.raises(ValueError, match="level must be one of"):
        tools.raise_alert(tracker.slug, "red", "x")


@pytest.mark.django_db
def test_set_focus_is_one_row(tracker, monkeypatch):
    from core.models import Focus
    monkeypatch.setenv("GOLAIET_MESSAGE_ID", "")
    shown = tools.set_focus(tracker.slug, note="Guy asked for VRAM")
    assert shown["tracker"] == tracker.slug and shown["view"] == "feed" and shown["note"] == "Guy asked for VRAM"
    cleared = tools.set_focus()
    assert cleared["tracker"] is None and cleared["view"] == "overview"
    assert Focus.objects.count() == 1
    with pytest.raises(Tracker.DoesNotExist):
        tools.set_focus("nope")
