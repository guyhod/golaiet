import pytest

from agent import tools
from agent.flows import assess
from agent.runner import AgentResult
from chat import alerts
from scheduler.models import Job


@pytest.fixture
def judging_runner(monkeypatch):
    """Stands in for the CLI: the 'model' records a watch-level assessment, the way the tool server would."""
    def run(self, prompt, **kwargs):
        env = kwargs["env"]
        monkeypatch.setenv("GOLAIET_JOB_RUN_ID", str(env["GOLAIET_JOB_RUN_ID"]))
        tools.record_assessment("vram-supply", {"level": "watch"}, "Supply tightened on 2026-10-08.", [])
        return AgentResult(text="watch: supply tightened", session_id="s-1", cost_usd=None)
    monkeypatch.setattr(assess.ClaudeRunner, "run", run)


@pytest.mark.django_db
def test_assess_flow_records_and_delivers_one_alert(tracker, judging_runner, monkeypatch):
    sent = []
    monkeypatch.setattr(alerts.telegram, "send", lambda text, **kw: sent.append(text) or 1)
    monkeypatch.setattr(alerts.telegram, "configured", lambda: True)
    tools.record_observation(tracker.slug, "2026-10-08", "https://n.example/1", "HBM supply tight", None)
    job = Job.objects.create(name=f"assess:{tracker.slug}", kind="assess", tracker=tracker, schedule="0 8 * * mon",
                             target="agent.flows.assess.run")
    from scheduler.dispatcher import execute_job
    run = execute_job(job)
    assert run.status == "done" and run.summary.startswith("1 assessment · 1 alerts sent · ")
    assert sent == ["🔔 VRAM supply and pricing: quiet → watch. Supply tightened on 2026-10-08."]
    alert = tracker.alerts.get()
    assert alert.delivered_at is not None and alert.job_run == run
    # Nothing filed since: the judge is not paid to repeat itself.
    again = execute_job(job)
    assert again.status == "done" and again.summary.startswith("skipped: nothing filed since")
    assert len(sent) == 1
