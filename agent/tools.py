"""The nine (six in this phase) functions the agent may call. Registered as MCP
tools by `manage.py mcp_tools`; name, docstring and type hints become the tool
name, description and schema the model sees. Each call is one short unit of
ORM work; provenance (which run, which message) comes from the environment the
runner put in the per-run MCP config."""
from __future__ import annotations

import os
from datetime import datetime, time
from zoneinfo import ZoneInfo

from apscheduler.triggers.cron import CronTrigger
from django.conf import settings
from django.core.validators import URLValidator
from django.utils import timezone

from core import kinds
from core.models import Observation, Tracker
from scheduler.models import Job


def _run_id() -> int | None:
    value = os.environ.get("GOLAIET_JOB_RUN_ID")
    return int(value) if value else None


def _message_id() -> int | None:
    value = os.environ.get("GOLAIET_MESSAGE_ID")
    return int(value) if value else None


def _tracker_dict(tracker: Tracker) -> dict:
    latest = tracker.observations.order_by("-observed_at").first()
    return {
        "slug": tracker.slug, "title": tracker.title, "kind": tracker.kind, "status": tracker.status,
        "subject": tracker.subject, "cadence": _cadence_of(tracker),
        "observations": tracker.observations.count(),
        "latest_observation_at": latest.observed_at.isoformat() if latest else None,
    }


def _observation_dict(observation: Observation) -> dict:
    return {
        "id": observation.pk, "tracker": observation.tracker.slug,
        "observed_at": observation.observed_at.isoformat(), "source_url": observation.source_url,
        "summary": observation.summary, "payload": observation.payload,
    }


def _cadence_of(tracker: Tracker) -> str | None:
    collect = tracker.jobs.filter(kind=Job.Kind.COLLECT).first()
    if collect is None:
        return None
    for word, crontab in kinds.CADENCES.items():
        if crontab == collect.schedule:
            return word
    return collect.schedule


def _parse_when(value: str, label: str) -> datetime:
    """ISO date or datetime. A bare date is midnight in Guy's time zone."""
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        raise ValueError(f"{label} must be an ISO date or datetime, got {value!r}")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo(settings.TIME_ZONE))
    return parsed


def _next_fire(crontab: str) -> str:
    trigger = CronTrigger.from_crontab(crontab, timezone=ZoneInfo(settings.TIME_ZONE))
    fire = trigger.get_next_fire_time(None, timezone.now())
    return fire.isoformat() if fire else "unknown"


def list_trackers() -> list[dict]:
    """List every tracker: slug, title, kind, status, cadence and when it last saw something."""
    return [_tracker_dict(tracker) for tracker in Tracker.objects.all()]


def get_tracker(slug: str, observations: int = 20) -> dict:
    """One tracker in full: its brief and its most recent observations (newest first)."""
    tracker = Tracker.objects.get(slug=slug)
    recent = tracker.observations.select_related("tracker").order_by("-observed_at")[:max(0, observations)]
    return dict(_tracker_dict(tracker), brief=tracker.brief,
                recent_observations=[_observation_dict(observation) for observation in recent])


def create_tracker(slug: str, title: str, kind: str, subject: dict, brief: str, cadence: str) -> dict:
    """Start tracking something new. slug: short, lowercase, hyphens (e.g. vram-supply).
    kind: one of the tracker kinds (topic). subject: the kind's fields (topic: {"query": ..., "regions": [...]}).
    brief: standing instructions for collecting, in full sentences. cadence: hourly, daily or weekly.
    Creates the tracker and its collect job; returns when the first run is."""
    if Tracker.objects.filter(slug=slug).exists():
        raise ValueError(f"tracker {slug!r} already exists; use update_tracker")
    kind_module = kinds.get(kind)
    kind_module.validate_subject(subject)
    if cadence not in kinds.CADENCES:
        raise ValueError(f"cadence must be one of {', '.join(kinds.CADENCES)}")
    if not brief.strip():
        raise ValueError("brief must not be empty")
    tracker = Tracker.objects.create(slug=slug, title=title, kind=kind, subject=subject, brief=brief.strip(),
                                     view=kind_module.VIEW, created_by_message_id=_message_id())
    jobs = []
    for spec in kind_module.DEFAULT_JOBS:
        job = Job.objects.create(name=f"{spec['kind']}:{slug}", kind=spec["kind"], tracker=tracker,
                                 trigger=Job.Trigger.CRON, schedule=kinds.CADENCES[cadence], target=spec["target"])
        jobs.append({"name": job.name, "schedule": job.schedule, "first_run_at": _next_fire(job.schedule)})
    return dict(_tracker_dict(tracker), jobs=jobs)


def update_tracker(slug: str, brief: str | None = None, cadence: str | None = None, status: str | None = None) -> dict:
    """Change an existing tracker: a new brief (replaces the old one in full), a new cadence
    (hourly, daily, weekly), or its status (active, paused, archived). Omitted fields are untouched."""
    tracker = Tracker.objects.get(slug=slug)
    changed = []
    if brief is not None:
        if not brief.strip():
            raise ValueError("brief must not be empty")
        tracker.brief = brief.strip()
        changed.append("brief")
    if status is not None:
        if status not in Tracker.Status.values:
            raise ValueError(f"status must be one of {', '.join(Tracker.Status.values)}")
        tracker.status = status
        changed.append("status")
    if cadence is not None:
        if cadence not in kinds.CADENCES:
            raise ValueError(f"cadence must be one of {', '.join(kinds.CADENCES)}")
        tracker.jobs.filter(kind=Job.Kind.COLLECT).update(schedule=kinds.CADENCES[cadence])
        changed.append("cadence")
    tracker.save()
    return dict(_tracker_dict(tracker), changed=changed)


def record_observation(slug: str, observed_at: str, source_url: str, summary: str, payload: dict | None = None) -> dict:
    """File one fact for a tracker. observed_at: ISO date or datetime the fact was published or happened.
    source_url: where it comes from (required for web findings). summary: one or two sentences in your words
    with the figure if there is one. payload: only the fields the tracker kind allows.
    A source_url already filed for this tracker is not filed again."""
    tracker = Tracker.objects.get(slug=slug)
    kind_module = kinds.get(tracker.kind)
    payload = kind_module.validate_payload(payload or {})
    if not summary.strip():
        raise ValueError("summary must not be empty")
    if source_url:
        URLValidator()(source_url)
        existing = tracker.observations.filter(source_url=source_url).first()
        if existing is not None:
            return dict(_observation_dict(existing), duplicate=True)
    observation = Observation.objects.create(
        tracker=tracker, observed_at=_parse_when(observed_at, "observed_at"), source_url=source_url,
        summary=summary.strip(), payload=payload, job_run_id=_run_id())
    return dict(_observation_dict(observation), duplicate=False)


def search_observations(query: str, slug: str | None = None, since: str | None = None, limit: int = 20) -> list[dict]:
    """Find observations whose summary contains the words in query (case-insensitive), across all
    trackers or one slug, optionally only since an ISO date. Newest first."""
    found = Observation.objects.select_related("tracker")
    for word in query.split():
        found = found.filter(summary__icontains=word)
    if slug:
        found = found.filter(tracker__slug=slug)
    if since:
        found = found.filter(observed_at__gte=_parse_when(since, "since"))
    return [_observation_dict(observation) for observation in found.order_by("-observed_at")[:max(1, min(limit, 100))]]


ALL = (list_trackers, get_tracker, create_tracker, update_tracker, record_observation, search_observations)
