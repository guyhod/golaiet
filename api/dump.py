"""GET /api/dump: this machine's whole database as one pg_dump archive, for
the machine that pulls a copy of it (manage.py pull_db <address>).

Not part of the read-only API beside it: that one shows the dashboard what
it draws, this one hands over every row. It is off unless DUMP_TOKEN is set,
and the caller has to send that value. With the archive it says how this
side stands, so that the caller can tell a live system from a copy and a
running one from a stopped one before it takes over.

The dump is built whole in a folder of its own and sent with its length, so
that a dump that failed is an error and never a short file that looks
whole; the folder is removed whether or not anything was sent. One is built
at a time, across the web workers: the turn is an advisory lock.

The token is compared in constant time and appears in no response, no log
line and no exception."""
import hmac
import json
import logging
import shutil
import tempfile
from pathlib import Path

from django.conf import settings
from django.db import connection
from django.http import HttpResponse
from django.views.decorators.http import require_GET

from core import backup, standing
from scheduler.models import JobRun

log = logging.getLogger(__name__)

# Shorter than this counts as not set: the token guards every row.
SHORTEST_TOKEN = 32
# pg_try_advisory_lock(int, int): the scheduler's lock is (the same first number, 1).
ONE_AT_A_TIME = (standing.LOCK_KEY[0], 2)


def refused(sentence: str, status: int = 403) -> HttpResponse:
    return HttpResponse(sentence + "\n", status=status, content_type="text/plain; charset=utf-8")


@require_GET
def dump(request) -> HttpResponse:
    token = settings.DUMP_TOKEN
    if not token:
        return refused("The dump endpoint is off on this side: DUMP_TOKEN is not set in its .env.")
    if len(token) < SHORTEST_TOKEN:
        return refused(f"The dump endpoint is off on this side: its DUMP_TOKEN is shorter than {SHORTEST_TOKEN} characters, "
                       "which counts as not set, since it guards every row.")
    scheme, _, sent = request.headers.get("Authorization", "").partition(" ")
    if scheme != "Bearer" or not sent:
        return refused("No token came with the request: it rides in the Authorization header, as `Bearer <DUMP_TOKEN>`.")
    if not hmac.compare_digest(sent.strip().encode(), token.encode()):
        return refused("The token that came is not this side's DUMP_TOKEN: the two sides have to hold the same value.")

    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_try_advisory_lock(%s, %s)", ONE_AT_A_TIME)
        if not cursor.fetchone()[0]:
            return refused("A dump is being built for another request on this side. Ask again when it is done.", status=409)
    folder = Path(tempfile.mkdtemp(prefix="dump-"))
    try:
        made = backup.dump(folder, "served.dump")
        archive = made.path.read_bytes()
        state = {"taken_at": made.taken_at, "migrations": made.migrations, "counts": made.counts,
                 "is_copy": standing.copy_mark() is not None, "scheduler_alive": standing.scheduler_alive(),
                 "runs_running": JobRun.objects.filter(status=JobRun.Status.RUNNING).count()}
    except backup.DumpFailed as failure:
        log.error("no dump was served: %s", failure)
        return refused(f"No dump could be built on this side: {failure}", status=500)
    finally:
        shutil.rmtree(folder, ignore_errors=True)
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_unlock(%s, %s)", ONE_AT_A_TIME)
    response = HttpResponse(archive, content_type="application/octet-stream")
    response[backup.STATE_HEADER] = json.dumps(state)
    return response
