"""The ten functions the agent may call. Registered as MCP
tools by `manage.py mcp_tools`; name, docstring and type hints become the tool
name, description and schema the model sees. Each call is one short unit of
ORM work; provenance (which run, which message) comes from the environment the
runner put in the per-run MCP config."""
from __future__ import annotations

import os
from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

from apscheduler.triggers.cron import CronTrigger
from django.conf import settings
from django.core.validators import URLValidator
from django.utils import timezone

from chat.models import Message
from core import kinds, life
from core.models import Alert, Assessment, Focus, Observation, Tracker
from scheduler.models import Job


def _run_id() -> int | None:
    value = os.environ.get("GOLAIET_JOB_RUN_ID")
    return int(value) if value else None


def _message_id() -> int | None:
    value = os.environ.get("GOLAIET_MESSAGE_ID")
    return int(value) if value else None


def _tracker_dict(tracker: Tracker) -> dict:
    latest = tracker.observations.order_by("-observed_at").first()
    judged = tracker.assessments.order_by("-at").first()
    described = {
        "slug": tracker.slug, "title": tracker.title, "kind": tracker.kind, "status": tracker.status,
        "subject": tracker.subject, "cadence": cadence_of(tracker),
        "observations": tracker.observations.count(),
        "latest_observation_at": latest.observed_at.isoformat() if latest else None,
        "latest_assessment": _assessment_dict(judged) if judged else None,
    }
    if tracker.kind in kinds.LIFE:
        described["on_board"] = life.on_board(tracker.slug)
    return described


def _agent_subject(kind_module, subject: dict, stored: dict) -> None:
    """Refuses a subject from the agent that sets or changes a field the kind keeps for Guy.
    A subject that is not an object is left for the kind to refuse."""
    for field in getattr(kind_module, "OWNER_FIELDS", ()) if isinstance(subject, dict) else ():
        if field in subject and subject[field] != stored.get(field):
            raise ValueError(f"subject.{field} is Guy's to set, in admin: leave it out and tell him")


def _assessment_dict(assessment: Assessment) -> dict:
    return {
        "id": assessment.pk, "tracker": assessment.tracker.slug, "at": assessment.at.isoformat(),
        "state": assessment.state, "reason": assessment.reason,
        "evidence_ids": list(assessment.evidence.values_list("pk", flat=True)),
    }


def _alert_dict(alert: Alert) -> dict:
    return {"id": alert.pk, "tracker": alert.tracker.slug, "level": alert.level, "text": alert.text,
            "created_at": alert.created_at.isoformat()}


def _focus_dict(focus: Focus) -> dict:
    return {"tracker": focus.tracker.slug if focus.tracker else None, "view": focus.view,
            "view_params": focus.view_params, "note": focus.note, "set_at": focus.set_at.isoformat()}


def _observation_dict(observation: Observation) -> dict:
    return {
        "id": observation.pk, "tracker": observation.tracker.slug,
        "observed_at": observation.observed_at.isoformat(), "source_url": observation.source_url,
        "summary": observation.summary, "payload": observation.payload,
    }


def _cadence_jobs(tracker: Tracker):
    """The tracker's jobs that follow the cadence word: a kind's fixed schedules
    (the topic judge an hour after the Monday collect) are not among them."""
    return tracker.jobs.filter(schedule__in=list(kinds.CADENCES.values()))


def cadence_of(tracker: Tracker) -> str | None:
    job = _cadence_jobs(tracker).first() or tracker.jobs.first()
    if job is None:
        return None
    for word, crontab in kinds.CADENCES.items():
        if crontab == job.schedule:
            return word
    return job.schedule


def _parse_when(value: str, label: str) -> datetime:
    """ISO date or datetime. A bare date is midnight in Guy's time zone."""
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        raise ValueError(f"{label} must be an ISO date or datetime, got {value!r}")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo(settings.TIME_ZONE))
    return parsed


def sync_jobs(tracker: Tracker, cadence: str) -> list[dict]:
    """The tracker's jobs as its kind derives them from the subject, at the cadence:
    missing ones are created (at the cadence, or the spec's own schedule), ones the
    subject no longer calls for are deleted (a country whose desk is dropped loses
    the daily session), and the ones that follow the cadence word move to it. The
    agent's create and update tools and the admin's tracker form all go through here."""
    if cadence not in kinds.CADENCES:
        raise ValueError(f"cadence must be one of {', '.join(kinds.CADENCES)}")
    wanted = {f"{spec['kind']}:{tracker.slug}": spec for spec in kinds.get(tracker.kind).jobs(tracker.subject)}
    tracker.jobs.exclude(name__in=wanted).delete()
    for name, spec in wanted.items():
        Job.objects.get_or_create(name=name, defaults=dict(
            kind=spec["kind"], tracker=tracker, trigger=Job.Trigger.CRON,
            schedule=spec.get("schedule") or kinds.CADENCES[cadence], target=spec["target"]))
    _cadence_jobs(tracker).update(schedule=kinds.CADENCES[cadence])
    return [{"name": job.name, "schedule": job.schedule, "first_run_at": _next_fire(job.schedule)}
            for job in tracker.jobs.order_by("name")]


def _next_fire(crontab: str) -> str:
    trigger = CronTrigger.from_crontab(crontab, timezone=ZoneInfo(settings.TIME_ZONE))
    fire = trigger.get_next_fire_time(None, timezone.now())
    return fire.isoformat() if fire else "unknown"


def list_trackers(kind: str | None = None) -> list[dict]:
    """List the trackers, one short row each: slug, title, kind, status and the level of the latest
    judgment. kind: only that kind (topic, country_risk, stock, practice, campaign). Use get_tracker
    for one tracker's brief, state and observations."""
    # One short row: with every tracker's whole latest state the listing outgrew what the CLI
    # accepts as a tool result (25,000 tokens) once the country records were in.
    if kind:
        kinds.get(kind)
    found = Tracker.objects.filter(kind=kind) if kind else Tracker.objects.all()
    rows = []
    for tracker in found:
        judged = tracker.assessments.order_by("-at").first()
        rows.append({"slug": tracker.slug, "title": tracker.title, "kind": tracker.kind, "status": tracker.status,
                     "level": judged.level if judged else None})
    return rows


def get_tracker(slug: str, observations: int = 20) -> dict:
    """One tracker in full: its brief, its last few assessments and its most recent observations (newest first)."""
    tracker = Tracker.objects.get(slug=slug)
    recent = tracker.observations.select_related("tracker").order_by("-observed_at")[:max(0, observations)]
    judged = tracker.assessments.select_related("tracker").order_by("-at")[:5]
    return dict(_tracker_dict(tracker), brief=tracker.brief,
                recent_assessments=[_assessment_dict(assessment) for assessment in judged],
                recent_observations=[_observation_dict(observation) for observation in recent])


def create_tracker(slug: str, title: str, kind: str, subject: dict, brief: str, cadence: str = "weekly") -> dict:
    """Start tracking something new. slug: short, lowercase, hyphens (e.g. vram-supply, isr).
    kind: topic (a web-researched subject), country_risk (one country's war risk and peace score),
    stock (a listed company against a buy price), practice (a habit of Guy's, counted from his reports) or
    campaign (a lane of stations on his life map). subject: the kind's fields (topic: {"query": ..., "regions": [...]};
    country_risk: {"iso3": "ISR"}, with "desk": ["security", "political_stability"] for a daily news desk on those
    lenses; stock: {"ticker": "CEG", "good_below": 170}; practice: {"color": "green" for a streak that an event
    breaks or "red" for a gap that an event closes, "started": "YYYY-MM-DD", "alert_after": days, red only};
    campaign: {"short": a short name for the map}, all optional).
    brief: standing instructions in full sentences (for a stock: the thesis; for a practice: what counts as an
    event and how it is dated).
    cadence: hourly, daily or weekly (stock news: daily; prices tick on their own every 15 minutes). A practice
    and a campaign have no schedule and ignore it.
    Creates the tracker and its jobs; returns when the first run is. For a practice or a campaign the result
    carries on_board: false means it is recorded and not drawn (the pulse row and the map are full, or a lane
    has no stations yet); say so in the reply."""
    if Tracker.objects.filter(slug=slug).exists():
        raise ValueError(f"tracker {slug!r} already exists; use update_tracker")
    kind_module = kinds.get(kind)
    _agent_subject(kind_module, subject, {})
    subject = kind_module.validate_subject(subject)
    if cadence not in kinds.CADENCES:
        raise ValueError(f"cadence must be one of {', '.join(kinds.CADENCES)}")
    if not brief.strip():
        raise ValueError("brief must not be empty")
    tracker = Tracker.objects.create(slug=slug, title=title, kind=kind, subject=subject, brief=brief.strip(),
                                     view=kind_module.VIEW, created_by_message_id=_message_id())
    jobs = sync_jobs(tracker, cadence)
    return dict(_tracker_dict(tracker), jobs=jobs)


def update_tracker(slug: str, brief: str | None = None, cadence: str | None = None, status: str | None = None,
                   subject: dict | None = None, title: str | None = None) -> dict:
    """Change an existing tracker: a new brief (replaces the old one in full), a new cadence
    (hourly, daily, weekly; a practice and a campaign have none), its status (active; paused: off the board,
    still recorded; archived), a new subject (the kind's fields in full, e.g. a stock's new good_below, a
    country's desk lenses; for a practice or a campaign only the fields that change, null to remove one), or a
    new title (a practice is renamed when its definition changes). Omitted fields are untouched."""
    tracker = Tracker.objects.get(slug=slug)
    kind_module = kinds.get(tracker.kind)
    changed = []
    if title is not None:
        if not title.strip():
            raise ValueError("title must not be empty")
        tracker.title = title.strip()
        changed.append("title")
    if subject is not None:
        _agent_subject(kind_module, subject, tracker.subject)
        if tracker.kind in kinds.LIFE and isinstance(subject, dict):
            # A life subject holds presentation the agent did not write (the lane's place on the map,
            # its short name), so a partial subject changes the fields it names and keeps the rest.
            subject = {field: value for field, value in {**tracker.subject, **subject}.items() if value is not None}
        tracker.subject = kind_module.validate_subject(subject)
        changed.append("subject")
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
        if not kind_module.jobs(kind_module.validate_subject(tracker.subject)):
            raise ValueError(f"a {tracker.kind} has no schedule: nothing runs for it, so it has no cadence to change")
        changed.append("cadence")
    tracker.save()
    if subject is not None or cadence is not None:
        sync_jobs(tracker, cadence or cadence_of(tracker) or "weekly")
    return dict(_tracker_dict(tracker), changed=changed)


def record_observation(slug: str, observed_at: str, source_url: str, summary: str, payload: dict | None = None) -> dict:
    """File one fact for a tracker. observed_at: ISO date or datetime the fact was published or happened.
    source_url: where it comes from (required for web findings; empty for what Guy reports himself).
    summary: one or two sentences in your words with the figure if there is one; on a practice or a campaign,
    Guy's own words. payload: only the fields the tracker kind allows (campaign: {"station": id} when the fact
    is about one station; practice: {"retracts": id} to take back a wrong observation).
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


def record_assessment(slug: str, state: dict, reason: str, evidence_ids: list[int] | None = None) -> dict:
    """Record your judgment of a tracker; judgments are kept, never edited. state: the kind's fields
    (topic: {"level": quiet|watch|elevated|critical, "score": 0-100 optional}; country_risk: the record the
    research request describes; campaign: only what changes, e.g. {"stations": [{"id": "s2", "state": "passed",
    "date": "YYYY-MM-DD"}]}. A station's state is passed (with the date it happened), current, ahead, proposed,
    decision or ref. A new station is {"id", "label", "track": the caption of its track, "after": the id it
    follows, optional}. Lane fields: check, target_by, note, burning with burning_why, focus with focus_why,
    next {"text", "hot"}; a station takes burning and focus with their reasons too; null removes a field;
    "dropped": [ids] removes stations; "tracks": [{"caption", "stations": [...]}] replaces the whole lane, to
    regroup it. level and changed are derived: leave them out. The lane is stored whole, and a change must cite
    an observation of what Guy said, filed in this same turn). reason: two to four sentences
    citing dates and figures. evidence_ids: ids of this tracker's observations you relied on.
    A change of level raises an alert to Guy by the kind's rule; you need not raise one yourself. For a
    campaign the result carries on_board: false means the lane is recorded and not drawn (the map is full,
    or the lane is paused); say so in the reply."""
    tracker = Tracker.objects.get(slug=slug)
    kind_module = kinds.get(tracker.kind)
    previous = tracker.assessments.order_by("-at").first()
    state = kind_module.validate_state(state, previous)
    if not reason.strip():
        raise ValueError("reason must not be empty")
    wanted = set(evidence_ids or [])
    evidence = list(tracker.observations.filter(pk__in=wanted))
    missing = wanted - {observation.pk for observation in evidence}
    if missing:
        raise ValueError(f"evidence_ids are not observations of {slug}: {', '.join(map(str, sorted(missing)))}")
    if hasattr(kind_module, "check_evidence"):
        kind_module.check_evidence(evidence, _run_id())
    assessment, alert = judge(tracker, state, reason, evidence, job_run_id=_run_id())
    recorded = dict(_assessment_dict(assessment), alert=_alert_dict(alert) if alert else None)
    if tracker.kind in kinds.LIFE:
        recorded["on_board"] = life.on_board(slug)
    return recorded


def judge(tracker: Tracker, state: dict, reason: str, evidence: list[Observation], *,
          job_run_id: int | None) -> tuple[Assessment, Alert | None]:
    """The judgment itself, for the tool above and for scripts that judge
    without a session (scheduler.scripts.prices): the assessment row, and the
    alert row when the kind's rule says the change is news. The caller has
    validated state against the kind."""
    previous = tracker.assessments.order_by("-at").first()
    assessment = Assessment.objects.create(tracker=tracker, state=state, reason=reason.strip(), job_run_id=job_run_id)
    assessment.evidence.set(evidence)
    alert_text = kinds.get(tracker.kind).alert_for(tracker, previous, assessment)
    alert = None
    if alert_text:
        alert = Alert.objects.create(tracker=tracker, assessment=assessment, level=assessment.level, text=alert_text,
                                     job_run_id=job_run_id)
    return assessment, alert


def raise_alert(slug: str, level: str, text: str) -> dict:
    """Tell Guy something about a tracker now, outside the level rule: one or two sentences with the date
    and source. level: one of the kind's levels. Not raised again while the tracker's latest alert is at the
    same level; the existing one is returned instead."""
    tracker = Tracker.objects.get(slug=slug)
    kind_module = kinds.get(tracker.kind)
    if level not in kind_module.LEVELS:
        raise ValueError(f"level must be one of {', '.join(kind_module.LEVELS)}")
    if not text.strip():
        raise ValueError("text must not be empty")
    latest = tracker.alerts.order_by("-created_at").first()
    if latest is not None and latest.level == level:
        return dict(_alert_dict(latest), duplicate=True)
    alert = Alert.objects.create(tracker=tracker, level=level, text=text.strip(), job_run_id=_run_id())
    return dict(_alert_dict(alert), duplicate=False)


def set_focus(slug: str | None = None, view_params: dict | None = None, note: str = "") -> dict:
    """Move the dashboard. slug: show this tracker in its own view; omit it to return to the overview of
    every tracker. view_params: parameters of that view, if it takes any (a campaign: {"station": id} opens
    that station). note: one short line shown on screen with it, e.g. what Guy asked."""
    focus = Focus.current()
    tracker = Tracker.objects.get(slug=slug) if slug else None
    focus.tracker = tracker
    focus.view = tracker.view if tracker else Focus.OVERVIEW
    focus.view_params = view_params or {}
    focus.note = note.strip()
    focus.set_by_message_id = _message_id()
    focus.save()
    return _focus_dict(focus)


def add_note(slug: str, text: str) -> dict:
    """Append one line, dated the day his message was sent, to the lane's own file in Guy's vault. Only when he
    asks for a note: what a tracker records is not copied there. slug: a campaign whose subject names its file
    (Guy sets it; you cannot). text: the note, his words."""
    tracker = Tracker.objects.get(slug=slug)
    if not text.strip():
        raise ValueError("text must not be empty")
    if not settings.VAULT_DIR:
        raise ValueError("the vault is not reachable from here (VAULT_DIR is not set)")
    if not tracker.subject.get("file"):
        raise ValueError(f"{slug} names no vault file (subject.file); ask Guy which file its notes go to")
    vault = Path(settings.VAULT_DIR).resolve()
    target = (vault / tracker.subject["file"]).resolve()
    if not target.is_relative_to(vault) or not target.is_file() or target.suffix != ".md":
        raise ValueError(f"{tracker.subject['file']} is not an existing .md file inside the vault")
    before = target.read_bytes()
    # Dated like everything else Guy reports: by when he sent the message, not by when it was handled.
    message = Message.objects.filter(pk=_message_id()).first()
    day = message.sent_at.astimezone(ZoneInfo(settings.TIME_ZONE)).date() if message else life.today()
    line = f"- {day.isoformat()}: {' '.join(text.split())}\n"
    written = (("" if not before or before.endswith(b"\n") else "\n") + line).encode("utf-8")
    with target.open("ab") as handle:
        handle.write(written)
    # A file layer between a container and the Mac once handed back an empty file for a full one,
    # so the write is believed only when the file grew by exactly what was written.
    grown = target.stat().st_size - len(before)
    if grown != len(written):
        raise ValueError(f"the note may not have landed: {tracker.subject['file']} grew by {grown} bytes, "
                         f"{len(written)} were written; tell Guy")
    return {"file": tracker.subject["file"], "line": line.strip()}


ALL = (list_trackers, get_tracker, create_tracker, update_tracker, record_observation, search_observations,
       record_assessment, raise_alert, set_focus, add_note)
