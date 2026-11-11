"""The flows: what a job's target does with one agent session. Each flow
builds a prompt from its kind, runs the CLI once, and returns the outcome
below to the dispatcher."""
import threading

from agent.runner import AgentResult
from core.models import Tracker

# The conversation has one Claude session, and the reply flow and the Friday
# brief both resume it. Two CLI runs resuming one session at once would fork
# it, and the later id would silently replace the earlier, so each takes this
# lock around its run. In-process is enough: both run in the scheduler.
conversation_turn = threading.Lock()


def tracker_of(job) -> Tracker:
    if job.tracker is None:
        raise ValueError(f"job {job.name} has no tracker")
    return job.tracker


def outcome(result: AgentResult, done: str, failed: bool = False) -> dict:
    """The run as the dispatcher records it: the summary (what was filed, then the
    agent's closing words), the cost, the session, and whether the run failed.
    A billing wall or a CLI error fails the run whatever the text says; `failed`
    is a flow's own verdict on top (a research session that judged nothing)."""
    failed = failed or result.is_error or result.is_billing_abort
    prefix = "billing: " if result.is_billing_abort else "error: " if failed else done
    return {"summary": prefix + result.text[:500], "cost_usd": result.cost_usd,
            "session_id": result.session_id, "failed": failed}
