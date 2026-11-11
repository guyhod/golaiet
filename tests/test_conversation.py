"""The conversation as the collector of Guy's own life: when a message was
sent, what the model is told, the tools the life rules lean on, the note in
the vault, and the replay. Invented content throughout."""
import datetime
import io
import json
from decimal import Decimal

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from agent import flows, tools
from agent.flows import reply
from agent.runner import AgentResult
from chat import poller, telegram
from chat.models import Conversation, Message
from core.models import Observation, Tracker
from scheduler.models import Job, JobRun

SENT = 1930717320   # 2031-03-08 06:22 UTC, 08:22 in Jerusalem


def update(update_id, text=None, **message):
    body = {"message_id": update_id, "chat": {"id": 6307}, "date": SENT, **message}
    if text is not None:
        body["text"] = text
    return {"update_id": update_id, "message": body}


@pytest.fixture
def chat(db, settings, monkeypatch):
    settings.TELEGRAM_CHAT_ID = "6307"
    sent = []
    monkeypatch.setattr(telegram, "send", lambda text, **kw: sent.append(text) or len(sent))
    return sent


def test_a_message_keeps_the_time_it_was_sent_and_a_forward_the_time_of_the_original(chat):
    plain = poller.store_inbound(update(1, "Stretched this morning"))
    assert plain.sent_at == datetime.datetime.fromtimestamp(SENT, datetime.timezone.utc)
    forwarded = poller.store_inbound(update(2, "Stretched this morning", date=SENT + 90000,
                                            forward_origin={"type": "user", "date": SENT}))
    assert forwarded.sent_at == plain.sent_at
    untimed = poller.store_inbound({"update_id": 3, "message": {"chat": {"id": 6307}, "text": "hello"}})
    assert abs((untimed.sent_at - untimed.created_at).total_seconds()) < 5


def test_a_message_with_no_text_is_answered_once_and_runs_no_session(chat, monkeypatch):
    Job.objects.create(name="reply", kind="reply", trigger="manual", schedule="", target="x")
    monkeypatch.setattr(poller, "execute_job", lambda *a, **k: pytest.fail("a voice note must not start a session"))
    poller.handle_update(update(5, voice={"duration": 3}))
    assert chat == [poller.NO_TEXT_REPLY] and poller.stored_offset() == 6
    assert list(Message.objects.values_list("direction", "text")) == [("in", ""), ("out", poller.NO_TEXT_REPLY)]


@pytest.fixture
def session(chat, monkeypatch, settings):
    """The reply flow with the CLI replaced: records how it was called."""
    calls = []

    class Runner:
        def __init__(self, model=None):
            self.model = model

        def run(self, prompt, **kwargs):
            calls.append({"prompt": prompt, "model": self.model, "locked": flows.conversation_turn.locked(), **kwargs})
            return AgentResult(text="Recorded: stretch, 2031-03-08.", session_id="11111111-1111-1111-1111-111111111111",
                               cost_usd=Decimal("0.01"))

    monkeypatch.setattr(reply, "ClaudeRunner", Runner)
    return calls


def test_the_reply_is_told_when_the_message_was_sent_in_jerusalem(session, settings):
    settings.CLAUDE_REPLY_MODEL = "stronger"
    inbound = poller.store_inbound(update(7, "Stretched last night"))
    run = JobRun.objects.create(job=Job.objects.create(name="reply", kind="reply", trigger="manual", schedule="", target="x"))
    reply.run(run.job, run, message_id=inbound.pk)
    call = session[0]
    assert call["prompt"] == "[Sent Saturday 2031-03-08 08:22, Jerusalem time]\nStretched last night"
    assert call["model"] == "stronger" and call["locked"] and not flows.conversation_turn.locked()
    assert Conversation.objects.get().session_id.startswith("1111")


def test_the_listing_is_one_short_row_per_tracker(tracker):
    tools.create_tracker("stretch", "Stretching", "practice", {"color": "red", "started": "2031-03-01"}, "Ten minutes count.")
    assert tools.list_trackers(kind="practice") == [
        {"slug": "stretch", "title": "Stretching", "kind": "practice", "status": "active", "level": None}]
    assert {row["slug"] for row in tools.list_trackers()} == {"stretch", tracker.slug}
    with pytest.raises(ValueError, match="unknown tracker kind"):
        tools.list_trackers(kind="hobby")
    renamed = tools.update_tracker("stretch", title="Stretching, mornings only", status="paused")
    assert renamed["changed"] == ["title", "status"] and Tracker.objects.get(slug="stretch").title == "Stretching, mornings only"
    with pytest.raises(ValueError, match="title"):
        tools.update_tracker("stretch", title="  ")


def test_a_proposal_cites_what_was_said_and_changes_nothing_else(db):
    tools.create_tracker("garden", "Garden", "campaign", {"short": "Garden"}, "Bed by bed.")
    said = tools.record_observation("garden", "2031-03-08", "", "Maybe a pond one day.")
    first = tools.record_assessment("garden", {"stations": [{"id": "dig", "label": "Dig the beds", "track": "Beds"}]},
                                    "He listed the work.", [said["id"]])
    proposal = tools.record_assessment("garden", {"stations": [
        {"id": "pond", "label": "Dig a pond", "track": "Water", "state": "proposed"}]}, "It came up.", [said["id"]])
    assert proposal["state"]["changed"] == ["pond"] and proposal["state"]["tracks"][0] == first["state"]["tracks"][0]
    assert proposal["state"]["level"] == "steady"


@pytest.fixture
def garden(db, settings, tmp_path):
    """A lane whose notes go to a file in a vault that is a temporary folder, never the real one."""
    settings.VAULT_DIR = str(tmp_path)
    (tmp_path / "Garden.md").write_text("# Garden\n\nFirst line, no newline at the end", encoding="utf-8")
    tools.create_tracker("garden", "Garden", "campaign", {"file": "Garden.md"}, "Bed by bed.")
    return tmp_path / "Garden.md"


def test_a_note_is_appended_as_one_dated_line(garden, monkeypatch):
    monkeypatch.setattr(tools.life, "today", lambda: datetime.date(2031, 3, 10))
    noted = tools.add_note("garden", "  the roses\nneed lime ")
    assert noted == {"file": "Garden.md", "line": "- 2031-03-10: the roses need lime"}
    tools.add_note("garden", "and the gate squeaks")
    assert garden.read_text(encoding="utf-8") == ("# Garden\n\nFirst line, no newline at the end\n"
                                                  "- 2031-03-10: the roses need lime\n- 2031-03-10: and the gate squeaks\n")


def test_a_note_is_refused_when_it_has_nowhere_safe_to_go(garden, settings, tmp_path):
    before = garden.read_bytes()
    tools.create_tracker("boat", "Boat", "campaign", {}, "The boat.")
    tools.create_tracker("shed", "Shed", "campaign", {"file": "../outside.md"}, "The shed.")
    tools.create_tracker("pond", "Pond", "campaign", {"file": "Pond.md"}, "The pond.")
    (tmp_path.parent / "outside.md").write_text("not in the vault")
    for slug, message in (("boat", "names no vault file"), ("shed", "inside the vault"), ("pond", "existing file"),
                          ("garden", "must not be empty")):
        with pytest.raises(ValueError, match=message):
            tools.add_note(slug, "" if slug == "garden" else "a note")
    settings.VAULT_DIR = ""
    with pytest.raises(ValueError, match="not reachable"):
        tools.add_note("garden", "a note")
    assert garden.read_bytes() == before and (tmp_path.parent / "outside.md").read_text() == "not in the vault"


def test_a_note_that_did_not_reach_the_file_is_reported_not_believed(garden, monkeypatch):
    monkeypatch.setattr(tools.Path, "open", lambda self, mode: io.BytesIO())
    with pytest.raises(ValueError, match="may not have landed"):
        tools.add_note("garden", "lost on the way")


CASES = {"cases": [
    {"id": "c1", "sent": {"date": "2031-03-08", "time": "07:30"}, "text": "Stretched last night",
     "expected": [{"tracker": "stretch", "effect": "event", "date": "2031-03-07"}]},
    {"id": "c2", "sent": {"date": "2031-03-09", "assumed_time": "09:00"}, "text": "What is the weather like?",
     "expected": [{"tracker": "garden", "effect": "answer_only"}]},
]}


def test_the_replay_compares_the_events_filed_with_the_events_expected(db, tmp_path, monkeypatch, capsys, settings):
    settings.TELEGRAM_BOT_TOKEN, settings.TELEGRAM_CHAT_ID = "123:token", "6307"
    tools.create_tracker("stretch", "Stretching", "practice", {"color": "red", "started": "2031-03-01"}, "Ten minutes count.")
    cases = tmp_path / "cases.json"
    cases.write_text(json.dumps(CASES))
    filed_on = {"day": "2031-03-07"}

    def session(self, prompt, *, env, **kwargs):
        if "Stretched" in prompt:
            assert prompt.startswith("[Sent Saturday 2031-03-08 07:30")
            Observation.objects.create(tracker=Tracker.objects.get(slug="stretch"), summary="Stretched last night",
                                       observed_at=tools._parse_when(filed_on["day"], "day"), job_run_id=env["GOLAIET_JOB_RUN_ID"])
        return AgentResult(text="Recorded.", session_id="11111111-1111-1111-1111-111111111111")

    monkeypatch.setattr(reply.ClaudeRunner, "run", session)
    monkeypatch.setattr(telegram, "_post", lambda *a, **k: pytest.fail("the replay sends nothing"))
    call_command("replay", str(cases))
    assert capsys.readouterr().out.count("ok  ") == 2
    with pytest.raises(CommandError, match="scratch database"):
        call_command("replay", str(cases))
    Message.objects.all().delete()
    Conversation.objects.all().delete()
    filed_on["day"] = "2031-03-08"
    with pytest.raises(CommandError, match="1 case"):
        call_command("replay", str(cases))
    assert "MISS c1" in capsys.readouterr().out
