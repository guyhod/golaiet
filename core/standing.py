"""What this database is: the live one, or a copy of it. Two facts, both kept
by Postgres itself and in no table.

The mark. A copy of the live database carries a comment on the database that
opens with MARK_WORD. A comment belongs to the database and is not inside a
dump, so a dump taken from a copy and restored elsewhere does not bring the
mark with it, and a copy is a copy because the command that made it said so.
On a marked database the scheduler refuses to start and Telegram counts as
not configured: a copy holds the live one's bot token and chat, and a second
poller on one bot takes the live one's messages.

The lock. The scheduler holds one advisory lock for as long as it lives, on
a connection of its own. Postgres drops the lock when that connection ends,
so a scheduler that died holds nothing, and whether one is alive is read
from pg_locks without waiting on a heartbeat (the heartbeat runs every half
hour, so its age says nothing about the last half hour)."""
import json
import logging
from dataclasses import dataclass

import psycopg
from django.db import connection
from psycopg import sql

from core import backup

log = logging.getLogger(__name__)

MARK_WORD = "golaiet-copy"
# pg_try_advisory_lock(int, int): any pair no other code takes. Advisory locks are per database.
LOCK_KEY = (0x676F6C61, 1)

_HELD_BY = """SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND granted AND classid = %s AND objid = %s
              AND objsubid = 2 AND database = (SELECT oid FROM pg_database WHERE datname = current_database())"""


@dataclass(frozen=True)
class CopyMark:
    source: str      # where the copy was pulled from: an address or a file
    pulled_at: str   # when, as it was written


def copy_mark() -> CopyMark | None:
    """The mark on the database this process is connected to, or None. A
    comment of any other text is not a mark."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT shobj_description(oid, 'pg_database') FROM pg_database WHERE datname = current_database()")
        comment = cursor.fetchone()[0] or ""
    if not comment.startswith(MARK_WORD):
        return None
    try:
        written = json.loads(comment[len(MARK_WORD):])
        return CopyMark(source=str(written["source"]), pulled_at=str(written["pulled_at"]))
    except (ValueError, KeyError, TypeError):
        # The word is there and the rest is not what mark_as_copy writes: still a copy.
        return CopyMark(source="an unknown source", pulled_at="an unknown time")


def mark_text(source: str, pulled_at: str) -> str:
    return f"{MARK_WORD} {json.dumps({'source': source, 'pulled_at': pulled_at})}"


def mark_as_copy(source: str, pulled_at: str) -> None:
    _comment(mark_text(source, pulled_at))


def clear_copy_mark() -> None:
    _comment(None)


def _comment(text: str | None) -> None:
    with connection.cursor() as cursor:
        cursor.execute("SELECT current_database()")
        database = cursor.fetchone()[0]
        cursor.execute(sql.SQL("COMMENT ON DATABASE {} IS {}").format(sql.Identifier(database), sql.Literal(text)))


def scheduler_alive() -> bool:
    """Whether any session holds the scheduler's lock on this database."""
    with connection.cursor() as cursor:
        cursor.execute(_HELD_BY, LOCK_KEY)
        return cursor.fetchone()[0] > 0


class SchedulerLock:
    """The lock as its holder has it. The session is not Django's: the
    scheduler's threads close Django's connections around every job, and the
    lock lives exactly as long as the session that took it."""

    def __init__(self):
        self.session: psycopg.Connection | None = None

    def take(self) -> bool:
        """Open a session and take the lock on it. False when another session
        holds it. Raises psycopg.OperationalError when the database does not answer."""
        self.release()
        session = backup.session()
        if not session.execute("SELECT pg_try_advisory_lock(%s, %s)", LOCK_KEY).fetchone()[0]:
            session.close()
            return False
        self.session = session
        return True

    def held(self) -> bool:
        """Whether this holder's own session still has the lock."""
        if self.session is None or self.session.closed:
            return False
        try:
            return self.session.execute(_HELD_BY + " AND pid = pg_backend_pid()", LOCK_KEY).fetchone()[0] > 0
        except psycopg.OperationalError:
            return False

    def keep(self) -> bool:
        """Make sure the lock is still this holder's, taking it again when the
        database restarted under the session. False only when another session
        holds it now. While the database does not answer nobody holds it, and
        the next call tries again."""
        if self.held():
            return True
        try:
            return self.take()
        except psycopg.OperationalError as failure:
            log.warning("the scheduler's lock could not be taken again yet (%s)", str(failure).strip().splitlines()[-1])
            return True

    def release(self) -> None:
        if self.session is not None:
            self.session.close()
            self.session = None
