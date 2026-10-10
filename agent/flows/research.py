"""A country's researcher: one session a week that searches the web, files the
sources it used as observations and records one assessment, the full record
(the country_risk kind does collect and judge in one session: the conflict map
proved the single sourced record, and a second session would pay again for the
same judgment). Alerts raised by the level rule are delivered here, after the
CLI has exited."""
from chat import alerts
from core import kinds
from core.models import Assessment, Observation, Tracker
from agent.prompts import RESEARCH_SYSTEM_PROMPT
from agent.runner import ClaudeRunner

ALLOWED_TOOLS = ["mcp__golaiet__record_observation", "mcp__golaiet__record_assessment", "mcp__golaiet__raise_alert",
                 "WebSearch", "WebFetch"]
TOOLS = ["WebSearch", "WebFetch"]


def run(job, run) -> dict:
    tracker: Tracker = job.tracker
    if tracker is None:
        raise ValueError(f"research job {job.name} has no tracker")
    if tracker.status != Tracker.Status.ACTIVE:
        return {"summary": f"skipped: tracker is {tracker.status}"}
    previous = tracker.assessments.order_by("-at").first()
    prompt = kinds.get(tracker.kind).research_prompt(tracker, previous)
    result = ClaudeRunner().run(prompt, system_prompt=RESEARCH_SYSTEM_PROMPT, allowed_tools=ALLOWED_TOOLS,
                                tools=TOOLS, env={"GOLAIET_JOB_RUN_ID": run.pk})
    filed = Observation.objects.filter(job_run=run).count()
    recorded = Assessment.objects.filter(job_run=run).count()
    delivered = alerts.deliver(run)
    # A session that searched and then never recorded the judgment is a failed run, not a quiet one.
    failed = result.is_error or result.is_billing_abort or recorded == 0
    prefix = ("billing: " if result.is_billing_abort else "error: " if failed
              else f"{filed} sources · {recorded} assessment · {delivered} alerts sent · ")
    return {"summary": prefix + result.text[:500], "cost_usd": result.cost_usd,
            "session_id": result.session_id, "failed": failed}
