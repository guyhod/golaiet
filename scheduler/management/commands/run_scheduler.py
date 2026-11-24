"""The scheduler process: the ONLY place APScheduler jobs are registered
(never in AppConfig.ready(): runserver's autoreloader forks two processes and
would double-schedule everything). Also hosts the Telegram long-poll thread.

All jobs live in a single MemoryJobStore; next_run_time is written back to Job
rows by sync_jobs() after every cycle, so a restart restores misfire state
from the rows without a separate APScheduler table.

One scheduler per database, and none on a copy: it starts only on a database
that carries no copy mark, and only once it holds the scheduler's lock
(core/standing.py). Both are settled before the poller's thread starts and
before a job is registered, because a copy holds the live one's bot token and
a second poller on one bot takes the live one's messages."""
import logging
import os
import sys
import threading

from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.schedulers.blocking import BlockingScheduler
from django.core.management.base import BaseCommand, CommandError
from django.db import Error as DatabaseError
from django.db import close_old_connections
from django.utils import timezone

from chat import telegram
from chat.poller import poll_forever
from core import standing
from scheduler.jobs import SYNC_INTERVAL_SEC, sync_jobs
from scheduler.jobs import timezone as scheduler_timezone

log = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Run the APScheduler loop that executes Job rows, plus the Telegram poller (blocking)."

    def handle(self, *args, **options):
        mark = standing.copy_mark()
        if mark is not None:
            raise CommandError(
                f"This database is a copy of {mark.source}, pulled {mark.pulled_at}. A copy never runs the scheduler: "
                "it would take the live one's Telegram messages and run every job a second time. "
                "To make this machine the live one, run `manage.py pull_db <source> --takeover`.")
        lock = standing.SchedulerLock()
        if not lock.take():
            raise CommandError("A scheduler is already alive on this database: it holds the scheduler's lock. "
                               "Two would run every job twice. Stop that one first.")
        try:
            self.run(lock)
        finally:
            lock.release()

    def run(self, lock: standing.SchedulerLock) -> None:
        scheduler = BlockingScheduler(timezone=scheduler_timezone())
        scheduler.add_jobstore(MemoryJobStore(), "default")
        stopped_because: list[str] = []

        def sync_entry():
            close_old_connections()
            try:
                reason = self.reason_to_stop(lock)
                if reason:
                    stopped_because.append(reason)
                    scheduler.shutdown(wait=False)   # wait=True would join the pool from one of its own threads
                    return
                sync_jobs(scheduler)
            finally:
                close_old_connections()

        scheduler.add_job(sync_entry, "interval", seconds=SYNC_INTERVAL_SEC,
                          next_run_time=timezone.now(), id="_job_sync", coalesce=True, max_instances=1)

        # On the credentials alone, not on configured(): that also reads the mark, which this start read a
        # moment ago and the tick reads from now on, and one failed read here would leave a live scheduler
        # without its poller for the life of the process, with one log line as the only sign.
        if telegram.has_credentials():
            threading.Thread(target=poll_forever, name="telegram-poller", daemon=True).start()
            self.stdout.write("telegram poller started")
        else:
            self.stdout.write(self.style.WARNING("telegram not configured (TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID); no chat"))

        self.stdout.write(self.style.SUCCESS(f"scheduler starting · re-sync every {SYNC_INTERVAL_SEC}s"))
        try:
            scheduler.start()
        except KeyboardInterrupt:
            scheduler.shutdown()
        if stopped_because:
            self.stderr.write(stopped_because[0])
            sys.stderr.flush()
            # Not a plain exit: the pool's threads are not daemons, so the process would stay up until the
            # sessions in flight end, and the poller's thread would go on taking messages all that time.
            os._exit(1)

    def reason_to_stop(self, lock: standing.SchedulerLock) -> str | None:
        """Asked on every sync tick. A pull can swap another database in under this process's name
        while it runs: its sessions are ended, it connects again by name, and it would go on as the
        scheduler of whatever answers there. So the mark is read every time, not only at the start."""
        try:
            mark = standing.copy_mark()
        except DatabaseError as failure:
            # Not a reason to stop: a database that is restarting cannot be read either. The next tick asks again.
            log.warning("whether this database is a copy could not be read on this tick (%s)", type(failure).__name__)
            mark = None
        if mark is not None:
            return (f"This database is now a copy of {mark.source}, pulled {mark.pulled_at}: it was swapped in under "
                    "the running scheduler. This one stops, since a copy never runs the scheduler.")
        if not lock.keep():
            return ("The database restarted and another scheduler now holds its lock: this one stops, "
                    "so that two never run on one database.")
        return None
