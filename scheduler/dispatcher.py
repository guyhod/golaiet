"""run_job(job_pk) is what every APScheduler job calls; execute_job(job) is the
reusable core underneath it: run one job's target now and record a JobRun,
whether or not a schedule asked for it. The Telegram poller calls execute_job
directly for each message, so an off-schedule run is not a different kind of
run and needs no different kind of record.

Targets are dotted paths to callables `run(job, run, **params)`: `run` is the
JobRun row being recorded (flows pass its id to the agent for provenance).
The callable returns an optional dict: "summary" becomes the JobRun summary,
"cost_usd" lands on JobRun.cost_usd, "session_id" on JobRun.session_id, and a
truthy "failed" records the run as FAILED even though the callable returned
normally (a billing wall evaluates nothing, and it must not read as green)."""
import logging
import traceback
from datetime import timedelta

from django.utils import timezone
from django.utils.module_loading import import_string

from chat import telegram

from .models import Job, JobRun

log = logging.getLogger(__name__)

# A failing job that fires every 15 minutes must not page every 15 minutes.
FAILURE_NOTICE_WINDOW = timedelta(hours=1)


def run_job(job_pk: int, fingerprint: str = "") -> None:
    """`fingerprint` is carried in the job args by scheduler.jobs for change
    detection; it plays no role at run time."""
    try:
        job = Job.objects.get(pk=job_pk)
    except Job.DoesNotExist:
        log.warning("run_job(%s): job row gone; removed on next sync", job_pk)
        return
    if not job.enabled:
        return
    execute_job(job)


def execute_job(job: Job, **extra_params) -> JobRun:
    """Run one job's target to completion and record its JobRun. `extra_params`
    are merged over job.params for this call only (the reply job gets the
    message id this way); the stored params stay the schedule's."""
    run = JobRun.objects.create(job=job, status=JobRun.Status.RUNNING)
    try:
        target = import_string(job.target)
        result = target(job=job, run=run, **dict(job.params, **extra_params)) or {}
        if isinstance(result, dict):
            run.summary = str(result.get("summary", result))[:2000]
            if result.get("cost_usd") is not None:
                run.cost_usd = result["cost_usd"]
            if result.get("session_id"):
                run.session_id = result["session_id"]
            run.status = JobRun.Status.FAILED if result.get("failed") else JobRun.Status.DONE
        else:
            run.summary = str(result)[:2000]
            run.status = JobRun.Status.DONE
    except Exception:
        run.status = JobRun.Status.FAILED
        run.summary = f"exception: {traceback.format_exc().strip().splitlines()[-1]}"[:2000]
        run.log = traceback.format_exc()[-4000:]
        log.exception("job %s failed", job.name)
    finally:
        run.finished_at = timezone.now()
        run.save()
        job.last_run = run.started_at
        job.last_status = run.status
        job.save(update_fields=["last_run", "last_status"])
    if run.status == JobRun.Status.FAILED:
        _notify_failure(job, run)
    return run


def _notify_failure(job: Job, run: JobRun) -> None:
    """Failures are loud: an outage must never look like a quiet day. One
    Telegram notice per job per hour; the rest are in admin."""
    recent_failures = JobRun.objects.filter(
        job=job, status=JobRun.Status.FAILED, started_at__gte=timezone.now() - FAILURE_NOTICE_WINDOW,
    ).exclude(pk=run.pk)
    if recent_failures.exists():
        return
    telegram.send(f"⚠️ {job.name} failed: {run.summary[:500]}")
