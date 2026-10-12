"""The inbound loop: long-poll Telegram, store each message, run the reply
job for it. Runs as a daemon thread inside the scheduler process.

Offset handling: Telegram hands out updates in order and forgets them once a
later offset is acknowledged. The highest update id stored on a Message is
the resume point, so a restart neither re-reads nor skips anything; an
update from a foreign chat is skipped without being stored, which only means
it is re-skipped after a restart (Telegram keeps it 24 h)."""
import logging
import time

import httpx
from django.conf import settings
from django.db import close_old_connections, models
from django.utils import timezone

from scheduler.dispatcher import execute_job
from scheduler.models import Job

from . import telegram
from .models import Conversation, Message

log = logging.getLogger(__name__)

RETRY_DELAY_SEC = 10


def stored_offset() -> int | None:
    highest = Message.objects.aggregate(highest=models.Max("telegram_update_id"))["highest"]
    return highest + 1 if highest is not None else None


def store_inbound(update: dict) -> Message | None:
    """The update's message as a Message row, or None when it is not for us
    (another chat) or carries no text (a sticker, a photo without caption)."""
    message = update.get("message") or {}
    chat_id = str((message.get("chat") or {}).get("id", ""))
    if chat_id != str(settings.TELEGRAM_CHAT_ID):
        log.warning("ignoring update %s from chat %s", update.get("update_id"), chat_id)
        return None
    text = message.get("text") or message.get("caption") or ""
    if not text.strip():
        return None
    conversation, _ = Conversation.objects.get_or_create(chat_id=chat_id, defaults={"channel": "telegram"})
    conversation.last_message_at = timezone.now()
    conversation.save(update_fields=["last_message_at"])
    return Message.objects.create(
        conversation=conversation, direction=Message.Direction.IN, text=text,
        telegram_message_id=message.get("message_id"), telegram_update_id=update.get("update_id"))


def handle_update(update: dict) -> None:
    inbound = store_inbound(update)
    if inbound is None:
        return
    reply_job = Job.objects.filter(name="reply", enabled=True).first()
    if reply_job is None:
        log.error("no enabled 'reply' job; run `manage.py seed_jobs`")
        telegram.send("⚠️ Golaiet has no reply job configured.", chat_id=inbound.conversation.chat_id)
        return
    execute_job(reply_job, message_id=inbound.pk)


def poll_once(offset: int | None) -> int | None:
    """One long poll and its updates; returns the next offset. A transport
    failure (the connection cut mid-handshake, the 40 s read timed out) is
    one warning line and the same offset back: 13 of them in the 48 h to
    2026-10-12, every one recovered on the next poll, and each had been
    logged as two chained tracebacks. Anything else keeps its traceback."""
    try:
        if offset is None:
            offset = stored_offset()
        for update in telegram.get_updates(offset):
            handle_update(update)
            offset = update["update_id"] + 1
    except httpx.TransportError as failure:
        log.warning("telegram poll failed (%s: %s); retrying in %ss", type(failure).__name__, failure, RETRY_DELAY_SEC)
        time.sleep(RETRY_DELAY_SEC)
    except Exception:
        log.exception("telegram poll failed; retrying in %ss", RETRY_DELAY_SEC)
        time.sleep(RETRY_DELAY_SEC)
    return offset


def poll_forever() -> None:
    offset = None
    while True:
        close_old_connections()
        try:
            offset = poll_once(offset)
        finally:
            close_old_connections()
