"""The scheduler process: the ONLY place APScheduler jobs are registered
(never in AppConfig.ready(): runserver's autoreloader forks two processes and
would double-schedule everything). Also hosts the Telegram long-poll thread.

All jobs live in a single MemoryJobStore; next_run_time is written back to Job
rows by sync_jobs() after every cycle, so a restart restores misfire state
from the rows without a separate APScheduler table."""
import threading

from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.schedulers.blocking import BlockingScheduler
from django.core.management.base import BaseCommand
from django.db import close_old_connections
from django.utils import timezone

from chat import telegram
from chat.poller import poll_forever
from scheduler.jobs import SYNC_INTERVAL_SEC, sync_jobs
from scheduler.jobs import timezone as scheduler_timezone


class Command(BaseCommand):
    help = "Run the APScheduler loop that executes Job rows, plus the Telegram poller (blocking)."

    def handle(self, *args, **options):
        scheduler = BlockingScheduler(timezone=scheduler_timezone())
        scheduler.add_jobstore(MemoryJobStore(), "default")

        def sync_entry():
            close_old_connections()
            try:
                sync_jobs(scheduler)
            finally:
                close_old_connections()

        scheduler.add_job(sync_entry, "interval", seconds=SYNC_INTERVAL_SEC,
                          next_run_time=timezone.now(), id="_job_sync", coalesce=True, max_instances=1)

        if telegram.configured():
            threading.Thread(target=poll_forever, name="telegram-poller", daemon=True).start()
            self.stdout.write("telegram poller started")
        else:
            self.stdout.write(self.style.WARNING("telegram not configured (TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID); no chat"))

        self.stdout.write(self.style.SUCCESS(f"scheduler starting · re-sync every {SYNC_INTERVAL_SEC}s"))
        try:
            scheduler.start()
        except KeyboardInterrupt:
            scheduler.shutdown()
