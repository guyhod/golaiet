"""The copy's mark and the scheduler's lock, on the test database: what marks
a database, who holds the lock, and what the scheduler and Telegram make of both."""
import threading
import time
from io import StringIO

import psycopg
import pytest
from apscheduler.schedulers.blocking import BlockingScheduler
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import OperationalError, connection

from chat import alerts, telegram
from core import standing
from core.models import Alert
from scheduler.management.commands import run_scheduler
from scheduler.models import Job


def session():
    """A connection of the test's own to the test database, as another process would have."""
    database = connection.settings_dict
    return psycopg.connect(dbname=database["NAME"], user=database["USER"], password=database["PASSWORD"],
                           host=database["HOST"], port=database["PORT"], autocommit=True)


def take_lock(holder) -> bool:
    return holder.execute("SELECT pg_try_advisory_lock(%s, %s)", standing.LOCK_KEY).fetchone()[0]


def released() -> bool:
    """Postgres frees a closed session's lock a moment after the close returns."""
    deadline = time.monotonic() + 5
    while standing.scheduler_alive() and time.monotonic() < deadline:
        time.sleep(0.02)
    return not standing.scheduler_alive()


@pytest.fixture
def started(monkeypatch, settings):
    """run_scheduler up to the point where it would block: no poller, and a loop that returns at once."""
    settings.TELEGRAM_BOT_TOKEN = ""
    starts = []
    monkeypatch.setattr(BlockingScheduler, "start", lambda scheduler: starts.append(scheduler))
    return starts


@pytest.mark.django_db
def test_the_mark_is_set_read_and_cleared_and_another_comment_is_no_mark():
    assert standing.copy_mark() is None
    standing.mark_as_copy("http://the-other-side:8003", "2031-03-01T22:10+02:00")
    assert standing.copy_mark() == standing.CopyMark(source="http://the-other-side:8003", pulled_at="2031-03-01T22:10+02:00")
    standing.clear_copy_mark()
    assert standing.copy_mark() is None
    standing._comment("a note somebody left about this database")
    assert standing.copy_mark() is None
    standing._comment(f"{standing.MARK_WORD} and then something no code wrote")
    assert standing.copy_mark() is not None, "the word alone makes a copy, whatever follows it"


@pytest.mark.django_db
def test_the_scheduler_refuses_a_copy_and_says_what_to_do(started):
    standing.mark_as_copy("/backups/nightly-2031-03-01.dump", "2031-03-02T09:00+02:00")
    with pytest.raises(CommandError) as refusal:
        call_command("run_scheduler")
    said = str(refusal.value)
    assert "a copy of /backups/nightly-2031-03-01.dump, pulled 2031-03-02T09:00+02:00" in said
    assert "never runs the scheduler" in said and "pull_db <source> --takeover" in said
    assert started == [] and not standing.scheduler_alive(), "it refused before it took the lock"


@pytest.mark.django_db
def test_the_scheduler_refuses_while_another_holds_the_lock_and_starts_once_it_is_gone(started):
    assert not standing.scheduler_alive()
    other = session()
    try:
        assert take_lock(other) and standing.scheduler_alive()
        with pytest.raises(CommandError, match="already alive on this database"):
            call_command("run_scheduler")
        assert started == []
    finally:
        other.close()   # a failed assert must not leave the lock held for the tests after this one
    assert released()
    call_command("run_scheduler")
    assert len(started) == 1
    assert released(), "the lock went with the scheduler"


def drop(lock) -> None:
    """What a restart of the database does to the holder: its session is gone and it has not let go itself.
    Closed from this side, because no test ends a session by a statement: this Postgres is the running stack's."""
    lock.session.close()


@pytest.mark.django_db
def test_the_lock_is_taken_again_after_the_holders_session_was_lost():
    lock = standing.SchedulerLock()
    try:
        assert lock.take() and lock.held()
        drop(lock)
        assert released() and not lock.held()
        assert lock.keep() and lock.held(), "nobody else took it, so it is this holder's again"
    finally:
        lock.release()


@pytest.mark.django_db
def test_the_lock_is_given_up_when_another_took_it_in_between():
    lock, other = standing.SchedulerLock(), session()
    try:
        assert lock.take()
        drop(lock)
        assert released() and take_lock(other)
        assert not lock.keep() and not lock.held()
    finally:
        lock.release()
        other.close()


@pytest.mark.django_db
def test_a_session_that_looks_open_and_fails_its_next_statement_is_not_held_and_is_taken_again():
    """What a restart of the database leaves the holder with: nothing says the session is gone until it is used."""
    class Gone:
        closed = False

        def execute(self, *arguments):
            raise psycopg.OperationalError("server closed the connection unexpectedly")

        def close(self):
            pass
    lock = standing.SchedulerLock()
    try:
        lock.session = Gone()
        assert not lock.held()
        assert lock.keep() and lock.held() and not isinstance(lock.session, Gone)
    finally:
        lock.release()


@pytest.mark.django_db
def test_the_poller_starts_on_the_credentials_alone_whatever_a_later_read_of_the_mark_does(started, settings, monkeypatch):
    settings.TELEGRAM_BOT_TOKEN, settings.TELEGRAM_CHAT_ID = "123:token", "6307"
    polling = threading.Event()
    monkeypatch.setattr(run_scheduler, "poll_forever", polling.set)
    read = standing.copy_mark
    reads = []

    def fails_after_the_first():
        reads.append(1)
        if len(reads) > 1:
            raise OperationalError("the database does not answer")
        return read()
    monkeypatch.setattr(standing, "copy_mark", fails_after_the_first)
    call_command("run_scheduler")
    assert polling.wait(5), "the poller's thread was started"
    assert len(started) == 1 and len(reads) == 1, "the start read the mark once, and the poller did not wait on a second read"


@pytest.fixture
def ticking(monkeypatch, settings):
    """run_scheduler with a loop that runs one sync tick and returns, and the hard exit stood in for.
    `before_the_tick` holds what happens to the database between the start and the tick."""
    settings.TELEGRAM_BOT_TOKEN = ""
    happened = {"exits": [], "shutdowns": [], "before_the_tick": lambda: None}

    def start(scheduler):
        happened["before_the_tick"]()
        scheduler.get_job("_job_sync").func()
    monkeypatch.setattr(BlockingScheduler, "start", start)
    monkeypatch.setattr(BlockingScheduler, "shutdown", lambda scheduler, wait=True: happened["shutdowns"].append(wait))
    monkeypatch.setattr(run_scheduler.os, "_exit", lambda code: happened["exits"].append(code))
    # The tick closes Django's connections around itself, and the test's transaction lives on one of them.
    monkeypatch.setattr(run_scheduler, "close_old_connections", lambda: None)
    return happened


@pytest.mark.django_db
def test_a_tick_on_a_database_that_became_a_copy_stops_the_scheduler(ticking):
    ticking["before_the_tick"] = lambda: standing.mark_as_copy("http://the-other-side:8003", "2031-03-01T22:10+02:00")
    errors = StringIO()
    call_command("run_scheduler", stderr=errors)
    assert ticking["exits"] == [1] and ticking["shutdowns"] == [False]
    assert "is now a copy of http://the-other-side:8003" in errors.getvalue() and "swapped in under the running scheduler" in errors.getvalue()
    assert Job.objects.filter(next_run_time__isnull=False).count() == 0, "it stopped before it synced a job"


@pytest.mark.django_db
def test_a_tick_that_finds_the_lock_with_another_stops_the_scheduler(ticking, monkeypatch):
    monkeypatch.setattr(standing.SchedulerLock, "keep", lambda lock: False)
    errors = StringIO()
    call_command("run_scheduler", stderr=errors)
    assert ticking["exits"] == [1] and "another scheduler now holds its lock" in errors.getvalue()


@pytest.mark.django_db
def test_a_tick_that_cannot_read_the_mark_stops_nothing(ticking, monkeypatch):
    def unreadable():
        raise OperationalError("the database does not answer")
    ticking["before_the_tick"] = lambda: monkeypatch.setattr(standing, "copy_mark", unreadable)
    call_command("run_scheduler", stderr=StringIO())
    assert ticking["exits"] == [] and ticking["shutdowns"] == []


@pytest.mark.django_db
def test_telegram_is_off_on_a_copy_and_when_the_mark_cannot_be_read(settings, monkeypatch):
    settings.TELEGRAM_BOT_TOKEN, settings.TELEGRAM_CHAT_ID = "123:token", "6307"
    assert telegram.configured()
    standing.mark_as_copy("http://the-other-side:8003", "2031-03-01T22:10+02:00")
    assert telegram.has_credentials() and not telegram.configured()
    assert telegram.send("to nobody") is None
    standing.clear_copy_mark()

    def unreadable():
        raise OperationalError("the database does not answer")
    monkeypatch.setattr(standing, "copy_mark", unreadable)
    assert not telegram.configured()


@pytest.mark.django_db
def test_an_alert_on_a_copy_is_not_sent_and_says_why(tracker, settings):
    settings.TELEGRAM_BOT_TOKEN, settings.TELEGRAM_CHAT_ID = "123:token", "6307"
    standing.mark_as_copy("http://the-other-side:8003", "2031-03-01T22:10+02:00")
    alert = Alert.objects.create(tracker=tracker, level="watch", text="supply tightened")
    assert alerts.retry() == 0
    assert alerts._send(Alert.objects.all()) == 0
    alert.refresh_from_db()
    assert alert.delivered_at is None and "is a copy" in alert.delivery_error
