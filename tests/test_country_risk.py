from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from django.core.management import call_command

from agent import tools
from agent.flows import research
from agent.runner import AgentResult
from core.kinds import country_risk
from scheduler.models import Job, JobRun

CALM = {"heat": "calm", "summary": "Nothing of the kind.", "detail": "Detail.", "latest_event": None,
        "source_urls": ["https://reuters.example/calm"]}
HOT = {"heat": "hot", "summary": "Riots in several cities.", "detail": "Detail.", "latest_event": "2026-10-17",
       "source_urls": ["https://reuters.example/riots"]}
LENSES = {key: dict(CALM) for key in country_risk.LENSES}
RECORD = {"peace_score": 35, "peace_score_reason": "Riots.", "overview": "Over.", "outlook": "Out.", "lenses": LENSES}


def record(**lenses):
    return {**RECORD, "lenses": {**{key: dict(CALM) for key in country_risk.LENSES}, **lenses}}


def test_subject_is_filled_from_the_iso_list():
    assert country_risk.validate_subject({"iso3": "irn"}) == {"iso3": "IRN", "name": "Iran", "numeric": "364"}
    with pytest.raises(ValueError, match="not an ISO 3166-1"):
        country_risk.validate_subject({"iso3": "ZZZ"})


def test_state_derives_level_and_trend_from_the_lenses():
    state = country_risk.validate_state(record(internal_stability=dict(HOT)))
    assert state["level"] == "hot" and "trend" not in state
    previous = SimpleNamespace(state={"peace_score": 42}, level="warm")
    again = country_risk.validate_state(record(), previous)
    assert again["level"] == "calm" and again["trend"] == "worsening" and again["peace_score_change"] == -7


def test_every_lens_is_judged_and_sourced():
    with pytest.raises(ValueError, match="missing antisemitism, islam"):
        country_risk.validate_state({**RECORD, "lenses": {k: dict(CALM) for k in country_risk.LENSES if k not in ("antisemitism", "islam")}})
    with pytest.raises(ValueError, match="unknown crime"):
        country_risk.validate_state(record(crime=dict(CALM)))
    with pytest.raises(ValueError, match=r"lenses.migration.source_urls needs at least one"):
        country_risk.validate_state(record(migration={**CALM, "source_urls": []}))
    with pytest.raises(ValueError, match="latest_event is required when the heat is hot"):
        country_risk.validate_state(record(security={**HOT, "latest_event": None}))
    with pytest.raises(ValueError, match="latest_event must be a YYYY-MM-DD"):
        country_risk.validate_state(record(security={**HOT, "latest_event": "October 17"}))
    with pytest.raises(ValueError, match="held_until is derived"):
        country_risk.validate_state(record(security={**HOT, "held_until": "2026-11-16"}))
    with pytest.raises(ValueError, match="level is derived"):
        country_risk.validate_state({**record(), "level": "hot"})
    with pytest.raises(ValueError, match="heat must be one of"):
        country_risk.validate_state(record(security={**HOT, "heat": "boiling"}))


def test_a_heat_holds_for_thirty_days_after_its_latest_event():
    previous = SimpleNamespace(state={"peace_score": 35, "lenses": record(internal_stability=dict(HOT))["lenses"]}, level="hot")
    cooled = {**CALM, "heat": "cold", "summary": "No riots found this week."}
    held = country_risk.validate_state(record(internal_stability=dict(cooled)), previous, test_today=date(2026, 10, 26))
    lens = held["lenses"]["internal_stability"]
    assert lens["heat"] == "hot" and lens["latest_event"] == "2026-10-17" and lens["held_until"] == "2026-11-16"
    assert lens["summary"] == "No riots found this week." and held["level"] == "hot"
    released = country_risk.validate_state(record(internal_stability=dict(cooled)), previous, test_today=date(2026, 11, 16))
    assert released["lenses"]["internal_stability"]["heat"] == "cold" and "held_until" not in released["lenses"]["internal_stability"]
    hotter = country_risk.validate_state(record(internal_stability={**HOT, "latest_event": "2026-10-24"}), previous, test_today=date(2026, 10, 26))
    assert hotter["lenses"]["internal_stability"]["latest_event"] == "2026-10-24"


def test_the_prompt_names_the_lenses_and_the_heats_on_file():
    tracker = SimpleNamespace(subject={"name": "France", "iso3": "FRA"}, title="France", slug="fra", brief="Riots.")
    previous = SimpleNamespace(at=date(2026, 10, 26), level="hot",
                               state={"peace_score": 70, "peace_score_reason": "Riots.", "lenses": record(internal_stability=dict(HOT))["lenses"]})
    prompt = country_risk.research_prompt(tracker, previous)
    assert "- islam:" in prompt and "- antisemitism:" in prompt
    assert "internal_stability: hot since 2026-10-17" in prompt and "stale index" in prompt
    study = country_risk.research_prompt(tracker, previous, lens="antisemitism")
    assert "studies one lens in depth, antisemitism:" in study and "Six lenses" not in study
    assert '"internal_stability": {' in study and "Riots in several cities." in study and "the antisemitism heat" in study
    with pytest.raises(ValueError, match="research the whole country first"):
        country_risk.research_prompt(tracker, None, lens="antisemitism")


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
    # Hot on an event older than the hold window, so the second judgment may cool it.
    old_fire = {**HOT, "latest_event": (date.today() - timedelta(days=country_risk.HOLD_DAYS + 1)).isoformat()}
    first = tools.record_assessment("isr", record(security=old_fire), "Several fronts.", [source["id"]])
    assert first["state"]["level"] == "hot" and first["alert"]["text"].startswith("Israel: calm → hot.")
    warm = {**HOT, "heat": "warm", "latest_event": "2026-01-10"}
    second = tools.record_assessment("isr", {**record(security=warm), "peace_score": 41}, "Front quiet.", [])
    assert second["state"] == {**second["state"], "level": "warm", "trend": "improving", "peace_score_change": 6}
    assert second["alert"]["text"].startswith("Israel: hot → warm.")
    assert tools.get_tracker("isr")["latest_assessment"]["state"]["peace_score_change"] == 6


@pytest.mark.django_db
def test_the_research_command_runs_one_lens_study_now(monkeypatch, capsys):
    monkeypatch.setenv("GOLAIET_MESSAGE_ID", "")
    monkeypatch.setenv("GOLAIET_JOB_RUN_ID", "")
    tools.create_tracker("prt", "Portugal", "country_risk", {"iso3": "prt"}, "Guy may move here.", "weekly")
    tools.record_assessment("prt", {**record(), "peace_score": 90}, "Quiet.", [])
    prompts = []

    def run(self, prompt, **kwargs):
        prompts.append(prompt)
        monkeypatch.setenv("GOLAIET_JOB_RUN_ID", str(kwargs["env"]["GOLAIET_JOB_RUN_ID"]))
        warm = {**HOT, "heat": "warm", "summary": "Threats at Coimbra.", "latest_event": date.today().isoformat()}
        tools.record_assessment("prt", {**record(antisemitism=warm), "peace_score": 84}, "Threats.", [])
        return AgentResult(text="antisemitism warm", session_id="s-1", cost_usd=None)
    monkeypatch.setattr(research.ClaudeRunner, "run", run)
    call_command("research", "prt", "--lens", "antisemitism")
    assert "studies one lens in depth, antisemitism" in prompts[0]
    assert JobRun.objects.get().status == JobRun.Status.DONE
    out = capsys.readouterr().out
    assert "Portugal: warm, peace score 84" in out and "antisemitism: warm" in out and "security:" not in out
