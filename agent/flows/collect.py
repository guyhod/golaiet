"""A tracker's collector: a fresh session that researches the tracker's brief
and files observations through record_observation. The count of rows this run
wrote is the summary; the agent's closing paragraph is kept after it."""
from core import kinds
from core.models import Observation, Tracker
from agent.flows import outcome, tracker_of
from agent.prompts import COLLECT_SYSTEM_PROMPT as SYSTEM_PROMPT
from agent.runner import ClaudeRunner

ALLOWED_TOOLS = ["mcp__golaiet__record_observation", "WebSearch", "WebFetch"]
TOOLS = ["WebSearch", "WebFetch"]
RECENT_OBSERVATIONS_IN_PROMPT = 30


def prompt(tracker: Tracker) -> str:
    """The prompt the next run would get; the admin's prompt page shows it."""
    recent = tracker.observations.order_by("-observed_at")[:RECENT_OBSERVATIONS_IN_PROMPT]
    return kinds.get(tracker.kind).collect_prompt(tracker, recent)


def run(job, run) -> dict:
    tracker = tracker_of(job)
    if tracker.status != Tracker.Status.ACTIVE:
        return {"summary": f"skipped: tracker is {tracker.status}"}
    result = ClaudeRunner().run(prompt(tracker), system_prompt=SYSTEM_PROMPT, allowed_tools=ALLOWED_TOOLS,
                                tools=TOOLS, env={"GOLAIET_JOB_RUN_ID": run.pk})
    filed = Observation.objects.filter(job_run=run).count()
    return outcome(result, f"{filed} new observations · ")
