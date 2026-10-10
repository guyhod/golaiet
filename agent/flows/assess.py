"""A tracker's judge: a fresh session that reads what the collector filed since
the last judgment and records one assessment. No built-in tools at all: the
judge works from the observations in the prompt, nothing else. Alerts the
session raised (by the kind's level rule or raise_alert) are delivered here,
after the CLI has exited."""
from chat import alerts
from core import kinds
from core.models import Assessment, Tracker
from agent.prompts import ASSESS_SYSTEM_PROMPT
from agent.runner import ClaudeRunner

ALLOWED_TOOLS = ["mcp__golaiet__record_assessment", "mcp__golaiet__raise_alert"]
TOOLS: list[str] = []
MAX_OBSERVATIONS_IN_PROMPT = 60


def run(job, run) -> dict:
    tracker: Tracker = job.tracker
    if tracker is None:
        raise ValueError(f"assess job {job.name} has no tracker")
    if tracker.status != Tracker.Status.ACTIVE:
        return {"summary": f"skipped: tracker is {tracker.status}"}
    previous = tracker.assessments.order_by("-at").first()
    observations = tracker.observations.order_by("-observed_at")
    if previous is not None:
        observations = observations.filter(created_at__gt=previous.at)
    observations = list(observations[:MAX_OBSERVATIONS_IN_PROMPT])
    if previous is not None and not observations:
        return {"summary": f"skipped: nothing filed since the {previous.at:%Y-%m-%d} judgment ({previous.level})"}

    prompt = kinds.get(tracker.kind).assess_prompt(tracker, observations, previous)
    result = ClaudeRunner().run(prompt, system_prompt=ASSESS_SYSTEM_PROMPT, allowed_tools=ALLOWED_TOOLS,
                                tools=TOOLS, env={"GOLAIET_JOB_RUN_ID": run.pk})
    recorded = Assessment.objects.filter(job_run=run).count()
    delivered = alerts.deliver(run)
    failed = result.is_error or result.is_billing_abort
    prefix = ("billing: " if result.is_billing_abort else "error: " if failed
              else f"{recorded} assessment · {delivered} alerts sent · ")
    return {"summary": prefix + result.text[:500], "cost_usd": result.cost_usd,
            "session_id": result.session_id, "failed": failed}
