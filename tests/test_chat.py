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


def test_get_updates_failure_names_status_not_token(monkeypatch, settings):
    import httpx
    from chat import telegram
    settings.TELEGRAM_BOT_TOKEN = "123:SECRET"
    settings.TELEGRAM_CHAT_ID = "1"
    monkeypatch.setattr(httpx, "post", lambda *a, **k: httpx.Response(409, json={"ok": False, "description": "Conflict: webhook is active"}))
    with pytest.raises(RuntimeError) as failure:
        telegram.get_updates(None)
    assert "http 409 Conflict: webhook is active" in str(failure.value) and "SECRET" not in str(failure.value)


@pytest.mark.django_db
def test_poll_once_logs_a_transport_failure_as_one_line(monkeypatch, caplog):
    import httpx
    from chat import telegram

    def cut(offset):
        raise httpx.ConnectError("[SSL: UNEXPECTED_EOF_WHILE_READING] EOF occurred in violation of protocol")

    monkeypatch.setattr(telegram, "get_updates", cut)
    monkeypatch.setattr(poller.time, "sleep", lambda seconds: None)
    with caplog.at_level("WARNING", logger="chat.poller"):
        assert poller.poll_once(7) == 7
    [record] = caplog.records
    assert record.levelname == "WARNING" and "ConnectError" in record.getMessage() and record.exc_info is None
