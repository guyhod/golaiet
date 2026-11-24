"""The heartbeat's call to the outside: made when an address is set, never a
reason for the heartbeat to fail, and the address in nothing that is kept."""
import logging

import httpx
import pytest

from scheduler import dispatcher
from scheduler.models import Job, JobRun
from scheduler.scripts import heartbeat

ADDRESS = "https://alarm.example/ping/a-secret-of-the-tests"


@pytest.fixture
def beat(db, monkeypatch):
    """One heartbeat run through the dispatcher, with the call stood in for by `outside`."""
    job = Job.objects.create(name="heartbeat", kind="heartbeat", trigger="interval", schedule="1800",
                             target="scheduler.scripts.heartbeat.run")
    called, outside = [], {"answer": lambda: httpx.Response(200)}

    def get(url, timeout=None):
        called.append((url, timeout))
        return outside["answer"]()
    monkeypatch.setattr(heartbeat.httpx, "get", get)
    monkeypatch.setattr(dispatcher.telegram, "send", lambda text, **options: pytest.fail(f"a notice was sent: {text}"))
    return lambda: dispatcher.execute_job(job), called, outside


def test_unset_nothing_is_called_and_nothing_is_said(beat, settings):
    run, called, _ = beat
    settings.HEARTBEAT_PING_URL = ""
    done = run()
    assert called == [] and done.status == JobRun.Status.DONE and done.summary == "alive"


def test_set_and_answered_the_call_is_made_under_a_short_limit(beat, settings):
    run, called, _ = beat
    settings.HEARTBEAT_PING_URL = ADDRESS
    done = run()
    assert called == [(ADDRESS, 10)] and done.status == JobRun.Status.DONE
    assert done.summary == "alive · the outside call was answered"


def raising(failure):
    def answer():
        raise failure
    return answer


@pytest.mark.parametrize("answer,said", [
    (raising(httpx.ConnectTimeout(f"timed out connecting to {ADDRESS}")), "ConnectTimeout"),
    (raising(httpx.ReadTimeout(f"no answer from {ADDRESS}")), "ReadTimeout"),
    (raising(httpx.ConnectError(f"could not resolve {ADDRESS}")), "ConnectError"),
    (raising(httpx.RemoteProtocolError(f"{ADDRESS} closed the connection")), "RemoteProtocolError"),
    (lambda: httpx.Response(503, text=f"no such check: {ADDRESS}"), "HTTP 503"),
    (lambda: httpx.Response(404), "HTTP 404"),
    (lambda: httpx.Response(302, headers={"Location": f"{ADDRESS}/elsewhere"}), "HTTP 302"),
    (raising(httpx.UnsupportedProtocol(f"Request URL is missing an 'http://' or 'https://' protocol: {ADDRESS}")), "UnsupportedProtocol"),
    (raising(ValueError(f"not an address at all: {ADDRESS}")), "ValueError"),
])
def test_a_call_that_fails_does_not_fail_the_heartbeat_and_the_address_is_nowhere(beat, settings, caplog, answer, said):
    run, called, outside = beat
    settings.HEARTBEAT_PING_URL = ADDRESS
    outside["answer"] = answer
    caplog.set_level(logging.DEBUG)
    done = run()
    assert len(called) == 1 and done.status == JobRun.Status.DONE
    assert done.summary == f"alive · the outside call failed ({said})"
    kept = done.summary + done.log + caplog.text + Job.objects.get().last_status
    assert "alarm.example" not in kept and "a-secret-of-the-tests" not in kept
