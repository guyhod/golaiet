"""The Telegram Bot API, both directions, over plain sync HTTP.

Outbound keeps what the investment engine learned: a 4000-char cap and a
Markdown→plain retry, because Telegram 400s on malformed Markdown rather
than degrading and one stray * in agent text is enough to trip it. Inbound
is long polling (getUpdates with a 30 s wait): no public URL, no webhook.

The credentials are the switch: both set means on, either missing means off.
No separate flag, because a flag can be on while the token is absent and
that state reads as a working channel silently dropping everything."""
import logging

import httpx
from django.conf import settings

log = logging.getLogger(__name__)

API = "https://api.telegram.org/bot{token}/{method}"
MAX_MESSAGE_LEN = 4000
POLL_WAIT_SEC = 30


def configured() -> bool:
    return bool(settings.TELEGRAM_BOT_TOKEN and settings.TELEGRAM_CHAT_ID)


def _url(method: str) -> str:
    return API.format(token=settings.TELEGRAM_BOT_TOKEN, method=method)


def send(text: str, *, chat_id: str | None = None) -> int | None:
    """POST one message; returns Telegram's message id, or None when it did not
    land. Never raises: a notifier that can fail its caller would let a Telegram
    outage roll back the work it was announcing."""
    if not configured():
        return None
    payload = {"chat_id": chat_id or settings.TELEGRAM_CHAT_ID, "text": text[:MAX_MESSAGE_LEN]}
    status, body = _post("sendMessage", dict(payload, parse_mode="Markdown"))
    if status == 400 and "parse" in str((body or {}).get("description", "")).lower():
        log.info("telegram rejected Markdown; resending as plain text")
        status, body = _post("sendMessage", payload)
    if status == 200 and isinstance(body, dict):
        return (body.get("result") or {}).get("message_id")
    log.warning("telegram send failed: http %s %s", status, body)
    return None


def get_updates(offset: int | None) -> list[dict]:
    """One long poll. Raises on transport errors; the poller loop handles them."""
    params = {"timeout": POLL_WAIT_SEC, "allowed_updates": ["message"]}
    if offset is not None:
        params["offset"] = offset
    response = httpx.post(_url("getUpdates"), json=params, timeout=POLL_WAIT_SEC + 10)
    try:
        body = response.json()
    except ValueError:
        body = {}
    if response.status_code != 200 or not body.get("ok"):
        # Not raise_for_status(): httpx puts the request URL, token included,
        # in that exception's message, and the poller logs it. 409 here means
        # a webhook is still registered on the bot (the Organism set one;
        # removed 2026-10-09) or a second poller is running.
        raise RuntimeError(f"getUpdates failed: http {response.status_code} {body.get('description', '')}")
    return body.get("result", [])


def _post(method: str, payload: dict) -> tuple[int | None, dict | None]:
    try:
        response = httpx.post(_url(method), json=payload, timeout=20)
    except Exception as exc:
        return None, {"description": f"{type(exc).__name__}: {exc}"}
    try:
        return response.status_code, response.json()
    except ValueError:
        return response.status_code, None
