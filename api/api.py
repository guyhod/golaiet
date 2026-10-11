"""Read-only API for the dashboard and for checking the system is alive. The
agent never uses this; it has its tools. Focus has a stream as well as a GET:
the dashboard holds the stream open and re-renders on each event."""
import json
import time
from datetime import timedelta

from django.db import close_old_connections
from django.http import StreamingHttpResponse
from django.utils import timezone
from ninja import NinjaAPI

from chat import telegram
from core import kinds
from core.models import Alert, Assessment, Focus, Observation, Tracker
from scheduler.models import JobRun

api = NinjaAPI(title="Golaiet", version="0.1")

# Two heartbeat intervals without a run: stale.
STALE_AFTER = timedelta(minutes=65)
# The stream re-reads the focus row this often; an unchanged row is a
# keep-alive comment instead of an event, so a proxy never closes an idle stream.
FOCUS_POLL_SEC = 1
FOCUS_KEEPALIVE_SEC = 15


@api.get("/health")
def health(request):
    latest_heartbeat = JobRun.objects.filter(job__name="heartbeat", status=JobRun.Status.DONE).order_by("-started_at").first()
    heartbeat_at = latest_heartbeat.started_at if latest_heartbeat else None
    return {
        "status": "ok" if heartbeat_at and heartbeat_at > timezone.now() - STALE_AFTER else "stale",
        "last_heartbeat": heartbeat_at,
        "telegram_configured": telegram.configured(),
        "trackers": Tracker.objects.filter(status=Tracker.Status.ACTIVE).count(),
    }


def _assessment(assessment: Assessment) -> dict:
    return {"id": assessment.pk, "at": assessment.at, "state": assessment.state, "reason": assessment.reason,
            "evidence_ids": list(assessment.evidence.values_list("pk", flat=True))}


def _tracker(tracker: Tracker) -> dict:
    latest = tracker.observations.order_by("-observed_at").first()
    judged = tracker.assessments.order_by("-at").first()
    levels = kinds.get(tracker.kind).LEVELS
    level = judged.level if judged else None
    return {"slug": tracker.slug, "title": tracker.title, "kind": tracker.kind, "status": tracker.status,
            "view": tracker.view, "subject": tracker.subject, "observations": tracker.observations.count(),
            "latest_observation_at": latest.observed_at if latest else None,
            "level": level, "level_rank": levels.index(level) if level in levels else -1,
            "latest_assessment": _assessment(judged) if judged else None}


def _observation(observation: Observation) -> dict:
    return {"id": observation.pk, "observed_at": observation.observed_at, "source_url": observation.source_url,
            "summary": observation.summary, "payload": observation.payload}


def _alert(alert: Alert) -> dict:
    return {"id": alert.pk, "tracker": alert.tracker.slug, "level": alert.level, "text": alert.text,
            "created_at": alert.created_at, "delivered_at": alert.delivered_at}


def _focus() -> dict:
    focus = Focus.current()
    return {"tracker": focus.tracker.slug if focus.tracker else None, "view": focus.view,
            "view_params": focus.view_params, "note": focus.note, "set_at": focus.set_at.isoformat()}


@api.get("/trackers")
def trackers(request):
    return [_tracker(tracker) for tracker in Tracker.objects.all()]


@api.get("/trackers/{slug}")
def tracker_detail(request, slug: str, limit: int = 50, sourced: bool = False):
    """sourced=true keeps only observations with a URL: a stock's news without
    its ticks, which the price view takes from /prices instead."""
    tracker = Tracker.objects.get(slug=slug)
    recent = tracker.observations.order_by("-observed_at")
    if sourced:
        recent = recent.exclude(source_url="")
    recent = recent[:max(1, min(limit, 500))]
    judged = tracker.assessments.order_by("-at")[:10]
    return dict(_tracker(tracker), brief=tracker.brief,
                recent_assessments=[_assessment(assessment) for assessment in judged],
                recent_observations=[_observation(observation) for observation in recent])


@api.get("/trackers/{slug}/prices")
def prices(request, slug: str, days: int = 30):
    """The tracker's price ticks, oldest first, for the chart."""
    since = timezone.now() - timedelta(days=max(1, min(days, 366)))
    ticks = Tracker.objects.get(slug=slug).observations.filter(observed_at__gte=since, payload__has_key="price").order_by("observed_at")
    return [{"at": tick.observed_at, "price": tick.payload["price"]} for tick in ticks]


@api.get("/alerts")
def alerts(request, limit: int = 20):
    return [_alert(alert) for alert in Alert.objects.select_related("tracker")[:max(1, min(limit, 200))]]


@api.get("/focus")
def focus(request):
    return _focus()


@api.get("/focus/stream")
def focus_stream(request):
    """Server-sent events: the current focus on connect, then one event per
    change. A sync generator under a threaded server; each tick is one query."""
    def events():
        shown = None
        quiet_for = 0
        while True:
            current = _focus()
            close_old_connections()
            if current != shown:
                shown = current
                quiet_for = 0
                yield f"event: focus\ndata: {json.dumps(current)}\n\n"
            else:
                quiet_for += FOCUS_POLL_SEC
                if quiet_for >= FOCUS_KEEPALIVE_SEC:
                    quiet_for = 0
                    yield ": keep-alive\n\n"
            time.sleep(FOCUS_POLL_SEC)

    response = StreamingHttpResponse(events(), content_type="text/event-stream")
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"
    return response
