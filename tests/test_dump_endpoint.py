"""GET /api/dump with the two binaries stood in for: when it is off, whom it
refuses, what comes with the archive, and that the token is nowhere but in
the request."""
import json
import logging

import pytest

from api import dump as endpoint
from core import backup, standing
from scheduler.models import Job, JobRun

TOKEN = "a-token-of-the-tests-that-is-long-enough"


def ask(client, token=TOKEN):
    return client.get("/api/dump", **({"HTTP_AUTHORIZATION": f"Bearer {token}"} if token is not None else {}))


@pytest.mark.django_db
def test_it_is_off_without_a_token_and_with_a_short_one(client, settings, tools):
    settings.DUMP_TOKEN = ""
    off = ask(client)
    assert off.status_code == 403 and "is off on this side: DUMP_TOKEN is not set" in off.content.decode()
    settings.DUMP_TOKEN = "short-but-right"
    short = ask(client, "short-but-right")
    assert short.status_code == 403 and "shorter than 32 characters, which counts as not set" in short.content.decode()
    assert tools[0] == [], "nothing was dumped"


@pytest.mark.django_db
def test_it_refuses_a_missing_and_a_wrong_token_and_the_token_is_in_nothing_it_says(client, settings, tools, caplog):
    settings.DUMP_TOKEN = TOKEN
    caplog.set_level(logging.DEBUG)
    missing, wrong = ask(client, None), ask(client, "not-the-token-of-this-side-at-all-0000")
    assert missing.status_code == 403 and "No token came with the request" in missing.content.decode()
    assert wrong.status_code == 403 and "is not this side's DUMP_TOKEN" in wrong.content.decode()
    assert client.post("/api/dump").status_code == 405
    said = missing.content.decode() + wrong.content.decode() + caplog.text + str(dict(wrong.headers))
    assert TOKEN not in said and "not-the-token-of-this-side" not in said and tools[0] == []


@pytest.mark.django_db
def test_the_right_token_gets_the_archive_with_its_length_and_how_this_side_stands(client, settings, tools, caplog, tmp_path, monkeypatch):
    settings.DUMP_TOKEN = TOKEN
    caplog.set_level(logging.DEBUG)
    monkeypatch.setattr(endpoint.tempfile, "mkdtemp", lambda prefix: str(tmp_path))
    heartbeat = Job.objects.create(name="heartbeat", kind="heartbeat", trigger="interval", schedule="1800", target="x")
    JobRun.objects.create(job=heartbeat, status=JobRun.Status.RUNNING)
    JobRun.objects.create(job=heartbeat, status=JobRun.Status.DONE)

    answer = ask(client)
    assert answer.status_code == 200 and answer.content == b"an archive"
    assert answer["Content-Length"] == str(len(b"an archive")) and answer["Content-Type"] == "application/octet-stream"
    state = json.loads(answer[backup.STATE_HEADER])
    assert set(state) == {"taken_at", "migrations", "counts", "is_copy", "scheduler_alive", "runs_running"}
    assert "core_tracker" in state["counts"] and state["migrations"]["core"].startswith("000")
    assert (state["is_copy"], state["scheduler_alive"], state["runs_running"]) == (False, False, 1)
    assert not tmp_path.exists(), "nothing of the dump is left behind"
    assert TOKEN not in caplog.text + str(dict(answer.headers))

    standing.mark_as_copy("http://the-other-side:8003", "2031-03-01T22:10+02:00")
    holder = standing.SchedulerLock()
    assert holder.take()
    try:
        state = json.loads(ask(client)[backup.STATE_HEADER])
    finally:
        holder.release()
    assert (state["is_copy"], state["scheduler_alive"]) == (True, True)


@pytest.mark.django_db
def test_a_second_request_while_one_is_built_is_refused_and_not_queued(client, settings, tools):
    settings.DUMP_TOKEN = TOKEN
    building = backup.session()
    try:
        assert building.execute("SELECT pg_try_advisory_lock(%s, %s)", endpoint.ONE_AT_A_TIME).fetchone()[0]
        busy = ask(client)
    finally:
        building.close()
    assert busy.status_code == 409 and "is being built for another request" in busy.content.decode() and tools[0] == []


@pytest.mark.django_db
def test_a_dump_that_fails_is_an_error_in_words_and_leaves_nothing(client, settings, tools, tmp_path, monkeypatch):
    settings.DUMP_TOKEN = TOKEN
    monkeypatch.setattr(endpoint.tempfile, "mkdtemp", lambda prefix: str(tmp_path))
    tools[1].append("pg_dump")
    failed = ask(client)
    assert failed.status_code == 500 and "No dump could be built on this side: pg_dump failed" in failed.content.decode()
    assert not tmp_path.exists() and TOKEN not in failed.content.decode()
    tools[1].clear()
    assert ask(client).status_code == 200, "the turn was given back"
