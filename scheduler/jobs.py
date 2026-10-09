"""Job rows -> APScheduler jobs.

sync_jobs() diffs enabled Job rows against the scheduler's jobs so that editing
a job in admin takes effect live (run_scheduler re-syncs every SYNC_INTERVAL_SEC).
A fingerprint of the trigger definition rides along in the job args: unchanged
jobs are left untouched (replacing resets next_run_time).

next_run_time is written back to the Job row after every sync so it is visible
in admin and survives restarts without a separate APScheduler job table."""
import logging
from typing import Any
from zoneinfo import ZoneInfo

from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from django.conf import settings
from django.db import close_old_connections

from .dispatcher import run_job
from .models import Job

log = logging.getLogger(__name__)

JOB_PREFIX = "job-"
SYNC_INTERVAL_SEC = 30


def timezone():
    return ZoneInfo(settings.TIME_ZONE)


def job_id(job: Job) -> str:
    return f"{JOB_PREFIX}{job.name}"


def fingerprint(job: Job) -> str:
    return f"{job.trigger}:{job.schedule}:{job.misfire_grace_sec}"


def build_trigger(job: Job) -> IntervalTrigger | CronTrigger:
    if job.trigger == Job.Trigger.INTERVAL:
        return IntervalTrigger(seconds=int(job.schedule), timezone=timezone())
    return CronTrigger.from_crontab(job.schedule, timezone=timezone())


def run_job_entry(job_pk: int, fingerprint: str = "") -> None:
    """APScheduler entry point: fresh DB connections around the dispatch.
    Long-lived scheduler threads must not reuse stale connections (a
    connection opened before the Mac slept is dead when the thread wakes)."""
    close_old_connections()
    try:
        run_job(job_pk, fingerprint)
    finally:
        close_old_connections()


def sync_jobs(scheduler) -> dict[str, int]:
    """Diff Job rows vs scheduled jobs; returns counts for logging and tests.
    Manual-trigger jobs are never scheduled: they run when code calls them."""
    scheduled_rows = Job.objects.filter(enabled=True).exclude(trigger=Job.Trigger.MANUAL)
    wanted_by_job_id = {job_id(job): job for job in scheduled_rows}
    remaining_by_job_id = dict(wanted_by_job_id)
    added = removed = replaced = 0

    for scheduled in list(scheduler.get_jobs()):
        if not scheduled.id.startswith(JOB_PREFIX):
            continue
        job = remaining_by_job_id.pop(scheduled.id, None)
        if job is None:
            scheduler.remove_job(scheduled.id)
            removed += 1
            continue
        current_fingerprint = scheduled.args[1] if len(scheduled.args) >= 2 else None
        if current_fingerprint != fingerprint(job):
            _add(scheduler, job, should_replace=True)
            replaced += 1

    for job in remaining_by_job_id.values():
        _add(scheduler, job)
        added += 1

    if added or removed or replaced:
        log.info("job sync: +%d -%d ~%d", added, removed, replaced)

    _writeback_next_run(scheduler, wanted_by_job_id)
    return {"added": added, "removed": removed, "replaced": replaced}


def _writeback_next_run(scheduler, jobs_by_job_id: dict[str, Job]) -> None:
    updates = []
    for scheduled_id, job in jobs_by_job_id.items():
        scheduled = scheduler.get_job(scheduled_id)
        if scheduled is not None:
            job.next_run_time = scheduled.next_run_time
            updates.append(job)
    if updates:
        Job.objects.bulk_update(updates, ["next_run_time"])


def _add(scheduler, job: Job, should_replace: bool = False) -> None:
    add_job_kwargs: dict[str, Any] = {}
    # Restore the persisted next_run_time so a run missed while the process was
    # down still fires on restart. Only pass it when non-None: APScheduler
    # treats next_run_time=None as "paused".
    if not should_replace and job.next_run_time is not None:
        add_job_kwargs["next_run_time"] = job.next_run_time
    scheduler.add_job(
        run_job_entry,
        trigger=build_trigger(job),
        id=job_id(job),
        args=[job.pk, fingerprint(job)],
        replace_existing=should_replace,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=job.misfire_grace_sec,
        **add_job_kwargs,
    )
