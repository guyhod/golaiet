"""The liveness job: a JobRun every interval, which the API's /health and the
dashboard's stale banner read. It also resends the alerts that failed to land
in the last day (chat.alerts.retry)."""
from chat import alerts


def run(job, run):
    resent = alerts.retry()
    return {"summary": "alive" + (f" · {resent} alerts resent" if resent else "")}
