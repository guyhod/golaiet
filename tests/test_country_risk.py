import pytest

from agent import tools
from core.kinds import country_risk
from scheduler.models import Job

CONFLICT = {
    "title": "Northern front with Hezbollah", "kind": "war", "scope": "external", "heat": "warm",
    "summary": "Exchanges of fire continue along the border.", "detail": "Detail.", "parties": ["Israel", "Hezbollah"],
    "since": "2023-10-08", "place": {"name": "Galilee", "kind": "area", "latitude": 33.0, "longitude": 35.4},
    "counterpart_iso3": "lbn", "source_urls": ["https://reuters.example/a"],
}
RECORD = {"peace_score": 35, "peace_score_reason": "Several active fronts.", "overview": "Over.", "outlook": "Out.",
          "conflicts": [CONFLICT, {**CONFLICT, "title": "Gaza", "heat": "hot", "place": None, "counterpart_iso3": None}]}


def test_subject_is_filled_from_the_iso_list():
    assert country_risk.validate_subject({"iso3": "irn"}) == {"iso3": "IRN", "name": "Iran", "numeric": "364"}
    with pytest.raises(ValueError, match="not an ISO 3166-1"):
        country_risk.validate_subject({"iso3": "ZZZ"})


def test_state_derives_level_and_trend_and_rejects_unsourced():
    from types import SimpleNamespace
    state = country_risk.validate_state({**RECORD, "conflicts": [dict(c) for c in RECORD["conflicts"]]})
    assert state["level"] == "hot" and "trend" not in state
    assert state["conflicts"][0]["counterpart_iso3"] == "LBN"
    previous = SimpleNamespace(state={"peace_score": 42}, level="warm")
    again = country_risk.validate_state({**RECORD, "conflicts": []}, previous)
    assert again["level"] == "calm" and again["trend"] == "worsening" and again["peace_score_change"] == -7
    with pytest.raises(ValueError, match=r"conflicts\[0\].source_urls needs at least one"):
        country_risk.validate_state({**RECORD, "conflicts": [{**CONFLICT, "source_urls": []}]})
    with pytest.raises(ValueError, match="level is derived"):
        country_risk.validate_state({**RECORD, "level": "calm", "conflicts": [dict(CONFLICT)]})
    with pytest.raises(ValueError, match="peace_score must be 0 to 100"):
        country_risk.validate_state({**RECORD, "peace_score": 101, "conflicts": []})
    with pytest.raises(ValueError, match="heat must be one of"):
        country_risk.validate_state({**RECORD, "conflicts": [{**CONFLICT, "heat": "boiling"}]})


@pytest.mark.django_db
def test_country_tracker_gets_a_research_job_and_alerts_on_heat(monkeypatch):
    monkeypatch.setenv("GOLAIET_MESSAGE_ID", "")
    monkeypatch.setenv("GOLAIET_JOB_RUN_ID", "")
    created = tools.create_tracker("isr", "Israel", "country_risk", {"iso3": "isr"}, "Guy lives here.", "weekly")
    assert created["subject"] == {"iso3": "ISR", "name": "Israel", "numeric": "376"} and created["cadence"] == "weekly"
    job = Job.objects.get(name="assess:isr")
    assert job.target == "agent.flows.research.run" and job.schedule == "0 7 * * mon"
    tools.update_tracker("isr", cadence="daily")
    assert Job.objects.get(name="assess:isr").schedule == "0 7 * * *"
    source = tools.record_observation("isr", "2026-10-09", "https://reuters.example/a", "Border fire.", {"title": "Reuters"})
    first = tools.record_assessment("isr", {**RECORD, "conflicts": [dict(c) for c in RECORD["conflicts"]]}, "Several fronts.", [source["id"]])
    assert first["state"]["level"] == "hot" and first["alert"]["text"].startswith("Israel: calm → hot.")
    second = tools.record_assessment("isr", {**RECORD, "peace_score": 41, "conflicts": [dict(CONFLICT)]}, "Gaza quiet.", [])
    assert second["state"] == {**second["state"], "level": "warm", "trend": "improving", "peace_score_change": 6}
    assert second["alert"]["text"].startswith("Israel: hot → warm.")
    assert tools.get_tracker("isr")["latest_assessment"]["state"]["peace_score_change"] == 6
