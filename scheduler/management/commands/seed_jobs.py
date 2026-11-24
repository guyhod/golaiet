"""The jobs every install has: `reply` (manual; the poller runs it per
message), `heartbeat` (every 30 min) and `prices` (every 15 minutes on
weekday afternoons Jerusalem time, which covers New York's trading day; the
script checks New York's clock itself) and `brief` (Friday 07:30: the week of
Guy's own life, posted into the conversation; it skips itself while there
are no life trackers) and `backup` (every night at 03:15, the hour the dump
ran at while a script outside the stack took it: the database's dump into
the backup folder). Idempotent: existing rows are left
alone, so an operator's edits in admin survive a re-seed."""
from django.core.management.base import BaseCommand

from scheduler.models import TICK_GRACE_SEC, Job

SEED = (
    dict(name="reply", kind=Job.Kind.REPLY, trigger=Job.Trigger.MANUAL, schedule="",
         target="agent.flows.reply.run"),
    dict(name="heartbeat", kind=Job.Kind.HEARTBEAT, trigger=Job.Trigger.INTERVAL, schedule="1800",
         target="scheduler.scripts.heartbeat.run", misfire_grace_sec=TICK_GRACE_SEC),
    dict(name="prices", kind=Job.Kind.COLLECT, trigger=Job.Trigger.CRON, schedule="*/15 15-23 * * mon-fri",
         target="scheduler.scripts.prices.run", misfire_grace_sec=TICK_GRACE_SEC),
    dict(name="brief", kind=Job.Kind.DIGEST, trigger=Job.Trigger.CRON, schedule="30 7 * * fri",
         target="agent.flows.brief.run"),
    dict(name="backup", kind=Job.Kind.BACKUP, trigger=Job.Trigger.CRON, schedule="15 3 * * *",
         target="scheduler.scripts.backup.run"),
)


class Command(BaseCommand):
    help = "Create the reply, heartbeat, prices, brief and backup jobs if missing."

    def handle(self, *args, **options):
        for fields in SEED:
            job, created = Job.objects.get_or_create(name=fields["name"], defaults=fields)
            self.stdout.write(f"{job.name}: {'created' if created else 'exists'}")
