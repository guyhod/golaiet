import pytest

from chat import poller
from chat.models import Message
from scheduler.models import Job


def update(update_id, chat_id, text, message_id=1):
    return {"update_id": update_id, "message": {"message_id": message_id, "chat": {"id": chat_id}, "text": text}}


@pytest.mark.django_db
def test_store_inbound_accepts_only_guys_chat(settings):
    settings.TELEGRAM_CHAT_ID = "6307"
    assert poller.store_inbound(update(10, 999, "hi")) is None
    assert poller.store_inbound(update(11, 6307, "   ")) is None
    stored = poller.store_inbound(update(12, 6307, "track VRAM"))
    assert stored.direction == "in" and stored.conversation.chat_id == "6307" and stored.telegram_update_id == 12
    assert poller.stored_offset() == 13


@pytest.mark.django_db
def test_handle_update_runs_reply_job(settings, monkeypatch):
    settings.TELEGRAM_CHAT_ID = "6307"
    reply = Job.objects.create(name="reply", kind="reply", trigger="manual", schedule="", target="x")
    executed = []
    monkeypatch.setattr(poller, "execute_job", lambda job, **params: executed.append((job.pk, params)))
    poller.handle_update(update(20, 6307, "hello"))
    message = Message.objects.get()
    assert executed == [(reply.pk, {"message_id": message.pk})]


@pytest.mark.django_db
def test_stored_offset_empty_is_none():
    assert poller.stored_offset() is None
