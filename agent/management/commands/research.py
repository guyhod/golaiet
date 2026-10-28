"""Research one country now, off schedule: the weekly job's run, recorded as a
JobRun like any other. --lens makes it a study of one lens with every search
spent on it, the other lenses carried over from the record on file."""
from django.core.management.base import BaseCommand, CommandError

from core.kinds import country_risk
from scheduler.dispatcher import execute_job
from scheduler.models import Job, JobRun


class Command(BaseCommand):
    help = "Research a country tracker now; --lens studies one lens in depth"

    def add_arguments(self, parser):
        parser.add_argument("slug", help="the tracker's slug, e.g. prt")
        parser.add_argument("--lens", choices=list(country_risk.LENSES))

    def handle(self, slug, lens, **options):
        job = Job.objects.filter(tracker__slug=slug, target="agent.flows.research.run").first()
        if job is None:
            raise CommandError(f"{slug} has no research job: is it a country tracker?")
        run = execute_job(job, lens=lens)
        self.stdout.write(f"{run.status}, ${run.cost_usd or 0:.2f}: {run.summary}")
        if run.status != JobRun.Status.DONE:
            raise CommandError("the run failed; its JobRun holds the log")
        state = job.tracker.assessments.order_by("-at").first().state
        self.stdout.write(f"{job.tracker.title}: {state['level']}, peace score {state['peace_score']}")
        for key, judged in state["lenses"].items():
            if lens in (None, key):
                self.stdout.write(f"  {key}: {judged['heat']} ({judged['latest_event'] or 'undated'}) {judged['summary']}")
