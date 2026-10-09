import pytest
from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.schedulers.background import BackgroundScheduler

from scheduler import dispatcher, jobs
from scheduler.models import Job, JobRun

CALLS = []


def ok_target(job, run, **params):
    CALLS.append((job.name, run.pk, params))
    return {"summary": "fine", "cost_usd": "0.0100", "session_id": "s-1"}


def failed_target(job, run, **params):
    return {"summary": "billing: usage limit reached", "failed": True}


def raising_target(job, run, **params):
    raise RuntimeError("boom")


@pytest.fixture(autouse=True)
def quiet_telegram(monkeypatch):
    sent = []
    monkeypatch.setattr(dispatcher.telegram, "send", lambda text, **kw: sent.append(text) or 1)
    return sent


@pytest.mark.django_db
def test_execute_job_records_result_fields():
    job = Job.objects.create(name="t", kind="heartbeat", trigger="interval", schedule="60", target="tests.test_scheduler.ok_target", params={"a": 1})
    run = dispatcher.execute_job(job, b=2)
    assert run.status == "done" and run.summary == "fine" and str(run.cost_usd) == "0.0100" and run.session_id == "s-1"
    assert CALLS[-1] == ("t", run.pk, {"a": 1, "b": 2})
    job.refresh_from_db()
    assert job.last_status == "done" and job.last_run == run.started_at


@pytest.mark.django_db
def test_failed_result_and_exception_are_loud(quiet_telegram):
    job = Job.objects.create(name="f", kind="collect", schedule="0 7 * * *", target="tests.test_scheduler.failed_target")
    run = dispatcher.execute_job(job)
    assert run.status == "failed" and run.summary.startswith("billing:")
    assert quiet_telegram == ["⚠️ f failed: billing: usage limit reached"]
    # A second failure inside the hour stays in admin only.
    dispatcher.execute_job(job)
    assert len(quiet_telegram) == 1
    job.target = "tests.test_scheduler.raising_target"
    job.save()
    run = dispatcher.execute_job(job)
    assert run.status == "failed" and "RuntimeError: boom" in run.summary and "Traceback" in run.log


@pytest.mark.django_db
def test_sync_jobs_adds_removes_and_skips_manual():
    Job.objects.create(name="reply", kind="reply", trigger="manual", schedule="", target="x")
    cron = Job.objects.create(name="collect:a", kind="collect", schedule="0 7 * * mon", target="x")
    Job.objects.create(name="hb", kind="heartbeat", trigger="interval", schedule="1800", target="x")
    scheduler = BackgroundScheduler(timezone=jobs.timezone())
    scheduler.add_jobstore(MemoryJobStore(), "default")
    scheduler.start(paused=True)
    try:
        assert jobs.sync_jobs(scheduler) == {"added": 2, "removed": 0, "replaced": 0}
        assert {j.id for j in scheduler.get_jobs()} == {"job-collect:a", "job-hb"}
        cron.refresh_from_db()
        assert cron.next_run_time is not None
        cron.schedule = "0 8 * * mon"
        cron.save()
        assert jobs.sync_jobs(scheduler)["replaced"] == 1
        cron.enabled = False
        cron.save()
        assert jobs.sync_jobs(scheduler)["removed"] == 1
    finally:
        scheduler.shutdown(wait=False)
