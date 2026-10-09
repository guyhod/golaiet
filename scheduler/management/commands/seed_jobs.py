"""The jobs every install has: `reply` (manual; the poller runs it per
message) and `heartbeat` (every 30 min). Idempotent: existing rows are left
alone, so an operator's edits in admin survive a re-seed."""
from django.core.management.base import BaseCommand

from scheduler.models import Job

SEED = (
    dict(name="reply", kind=Job.Kind.REPLY, trigger=Job.Trigger.MANUAL, schedule="",
         target="agent.flows.reply.run"),
    dict(name="heartbeat", kind=Job.Kind.HEARTBEAT, trigger=Job.Trigger.INTERVAL, schedule="1800",
         target="scheduler.scripts.heartbeat.run"),
)


class Command(BaseCommand):
    help = "Create the reply and heartbeat jobs if missing."

    def handle(self, *args, **options):
        for fields in SEED:
            job, created = Job.objects.get_or_create(name=fields["name"], defaults=fields)
            self.stdout.write(f"{job.name}: {'created' if created else 'exists'}")
