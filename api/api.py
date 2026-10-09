"""Read-only API for the dashboard (next phase) and for checking the system
is alive. The agent never uses this; it has its tools."""
from datetime import timedelta

from django.utils import timezone
from ninja import NinjaAPI

from chat import telegram
from core.models import Observation, Tracker
from scheduler.models import JobRun

api = NinjaAPI(title="Golaiet", version="0.1")

# Two heartbeat intervals without a run: stale.
STALE_AFTER = timedelta(minutes=65)


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


def _tracker(tracker: Tracker) -> dict:
    latest = tracker.observations.order_by("-observed_at").first()
    return {"slug": tracker.slug, "title": tracker.title, "kind": tracker.kind, "status": tracker.status,
            "view": tracker.view, "subject": tracker.subject, "observations": tracker.observations.count(),
            "latest_observation_at": latest.observed_at if latest else None}


def _observation(observation: Observation) -> dict:
    return {"id": observation.pk, "observed_at": observation.observed_at, "source_url": observation.source_url,
            "summary": observation.summary, "payload": observation.payload}


@api.get("/trackers")
def trackers(request):
    return [_tracker(tracker) for tracker in Tracker.objects.all()]


@api.get("/trackers/{slug}")
def tracker_detail(request, slug: str, limit: int = 50):
    tracker = Tracker.objects.get(slug=slug)
    recent = tracker.observations.order_by("-observed_at")[:max(1, min(limit, 500))]
    return dict(_tracker(tracker), brief=tracker.brief, recent_observations=[_observation(o) for o in recent])
