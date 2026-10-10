"""Alert delivery. A flow calls deliver(run) once its session has exited and
sends every alert that run raised; the tool server itself never talks to
Telegram, so a crashed session leaves rows in admin, not half-sent messages.
An alert that did not land keeps delivered_at empty and says why."""
import logging

from django.utils import timezone

from core.models import Alert

from . import telegram

log = logging.getLogger(__name__)


def deliver(run) -> int:
    """Send this run's undelivered alerts, oldest first. Returns how many landed."""
    sent = 0
    pending = Alert.objects.filter(job_run=run, delivered_at__isnull=True).select_related("tracker").order_by("created_at")
    for alert in pending:
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
