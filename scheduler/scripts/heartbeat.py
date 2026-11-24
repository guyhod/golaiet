"""The liveness job: a JobRun every interval, which the API's /health and the
dashboard's stale banner read. It also resends the alerts that failed to land
in the last day (chat.alerts.retry).

Nothing inside the stack can say that the stack is down, so when
HEARTBEAT_PING_URL is set the job also calls that address: an outside
service that expects the call and tells Guy when it stops coming. A call
that fails does not fail the heartbeat. /health reads the last heartbeat
that ended well, and a failed run here would show the dashboard as stale
because a service outside was down.

The address is a secret of its own kind: whoever holds it can keep the
alarm quiet. It goes into no summary, no log line and no exception text,
and httpx's own exceptions carry the request's address in their words, so
only the kind of a failure is ever said."""
import httpx
from django.conf import settings

from chat import alerts

PING_TIMEOUT_SEC = 10


def ping_outside() -> str:
    """What the summary says of the outside call; empty when none is set."""
    if not settings.HEARTBEAT_PING_URL:
        return ""
    try:
        answer = httpx.get(settings.HEARTBEAT_PING_URL, timeout=PING_TIMEOUT_SEC)
    except Exception as failure:
        # Every kind, not httpx's own alone: an address that is not a URL raises another, and an
        # exception that got out of here would fail the heartbeat and carry the address into the
        # run's log and the failure notice.
        return f" · the outside call failed ({type(failure).__name__})"
    if not 200 <= answer.status_code < 300:   # a redirect is not the service saying it heard
        return f" · the outside call failed (HTTP {answer.status_code})"
    return " · the outside call was answered"


def run(job, run):
    resent = alerts.retry()
    return {"summary": "alive" + (f" · {resent} alerts resent" if resent else "") + ping_outside()}
