"""Alert delivery. A flow calls deliver(run) once its session has exited and
sends every alert that run raised; the tool server itself never talks to
Telegram, so a crashed session leaves rows in admin, not half-sent messages.
An alert that did not land keeps delivered_at empty and says why, and the
heartbeat retries it for a day: on 2026-10-24 France's first judgment hit one
transient TLS failure at sendMessage and would otherwise never have reached
Guy, since nothing looked at the row again."""
import logging
from datetime import timedelta

from django.utils import timezone

from core.models import Alert

from . import telegram

log = logging.getLogger(__name__)


RETRY_FOR = timedelta(hours=24)


def deliver(run) -> int:
    """Send this run's undelivered alerts, oldest first. Returns how many landed."""
    return _send(Alert.objects.filter(job_run=run))


def retry() -> int:
    """Send every alert that failed to land in the last day. Returns how many landed."""
    if not telegram.configured():
        return 0
    return _send(Alert.objects.filter(created_at__gte=timezone.now() - RETRY_FOR))


def _send(alerts) -> int:
    sent = 0
    for alert in alerts.filter(delivered_at__isnull=True).select_related("tracker").order_by("created_at"):
        message_id = telegram.send(f"🔔 {alert.text}")
        if message_id is not None:
            alert.delivered_at = timezone.now()
            alert.delivery_error = ""
            sent += 1
        else:
            alert.delivery_error = "telegram not configured" if not telegram.configured() else "sendMessage failed; see the scheduler log"
            log.warning("alert %s for %s not delivered: %s", alert.pk, alert.tracker.slug, alert.delivery_error)
        alert.save(update_fields=["delivered_at", "delivery_error"])
    return sent
