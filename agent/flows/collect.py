"""A tracker's collector: a fresh session that researches the tracker's brief
and files observations through record_observation. The count of rows this run
wrote is the summary; the agent's closing paragraph is kept after it."""
from core import kinds
from core.models import Observation, Tracker
from agent.prompts import COLLECT_SYSTEM_PROMPT
from agent.runner import ClaudeRunner

ALLOWED_TOOLS = ["mcp__golaiet__record_observation", "WebSearch", "WebFetch"]
TOOLS = ["WebSearch", "WebFetch"]
RECENT_OBSERVATIONS_IN_PROMPT = 30


def run(job, run) -> dict:
    tracker: Tracker = job.tracker
    if tracker is None:
        raise ValueError(f"collect job {job.name} has no tracker")
    if tracker.status != Tracker.Status.ACTIVE:
        return {"summary": f"skipped: tracker is {tracker.status}"}
    kind_module = kinds.get(tracker.kind)
    recent = tracker.observations.order_by("-observed_at")[:RECENT_OBSERVATIONS_IN_PROMPT]
    prompt = kind_module.collect_prompt(tracker, recent)

    result = ClaudeRunner().run(prompt, system_prompt=COLLECT_SYSTEM_PROMPT, allowed_tools=ALLOWED_TOOLS,
                                tools=TOOLS, env={"GOLAIET_JOB_RUN_ID": run.pk})
    filed = Observation.objects.filter(job_run=run).count()
    failed = result.is_error or result.is_billing_abort
    prefix = "billing: " if result.is_billing_abort else "error: " if failed else f"{filed} new observations · "
    return {"summary": prefix + result.text[:500], "cost_usd": result.cost_usd,
            "session_id": result.session_id, "failed": failed}
