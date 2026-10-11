"""The jobs every install has: `reply` (manual; the poller runs it per
message), `heartbeat` (every 30 min) and `prices` (every 15 minutes on
weekday afternoons Jerusalem time, which covers New York's trading day; the
script checks New York's clock itself). Idempotent: existing rows are left
alone, so an operator's edits in admin survive a re-seed."""
from django.core.management.base import BaseCommand

from scheduler.models import Job

SEED = (
    dict(name="reply", kind=Job.Kind.REPLY, trigger=Job.Trigger.MANUAL, schedule="",
         target="agent.flows.reply.run"),
    dict(name="heartbeat", kind=Job.Kind.HEARTBEAT, trigger=Job.Trigger.INTERVAL, schedule="1800",
         target="scheduler.scripts.heartbeat.run"),
    dict(name="prices", kind=Job.Kind.COLLECT, trigger=Job.Trigger.CRON, schedule="*/15 16-23 * * mon-fri",
         target="scheduler.scripts.prices.run"),
)


class Command(BaseCommand):
    help = "Create the reply, heartbeat and prices jobs if missing."

    def handle(self, *args, **options):
        for fields in SEED:
            job, created = Job.objects.get_or_create(name=fields["name"], defaults=fields)
            self.stdout.write(f"{job.name}: {'created' if created else 'exists'}")
