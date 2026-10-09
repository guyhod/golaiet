"""The liveness job: a JobRun every interval with nothing in it. The API's
/health reads the latest one, and a dashboard stale banner (next phase) hangs
off the same row."""


def run(job, run):
    return {"summary": "alive"}
