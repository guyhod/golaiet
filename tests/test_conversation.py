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
from agent.flows import brief, reply
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
    assert call["prompt"] == "[Sent Saturday 2031-03-08 08:22, Asia/Jerusalem time]\nStretched last night"
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
    with pytest.raises(ValueError, match="has no schedule"):
        tools.update_tracker("stretch", cadence="daily")


def test_a_tracker_the_board_has_no_room_for_says_so(db):
    for number in range(8):
        made = tools.create_tracker(f"habit-{number}", f"Habit {number}", "practice",
                                    {"color": "green", "started": "2031-03-01", "rank": number}, "Counts daily.")
    assert made["on_board"] is False and tools.get_tracker("habit-0")["on_board"] is True
    assert tools.create_tracker("garden", "Garden", "campaign", {}, "Bed by bed.")["on_board"] is False, "no stations yet"


def test_a_lane_the_map_has_no_room_for_says_so_when_its_stations_arrive(db):
    for number in range(10):
        tools.create_tracker(f"lane-{number}", f"Lane {number}", "campaign", {"rank": number}, "Step by step.")
        said = tools.record_observation(f"lane-{number}", "2031-03-08", "", "First step is the plan")
        drawn = tools.record_assessment(f"lane-{number}", {"stations": [{"id": "s1", "label": "Plan", "track": "Start"}]},
                                        "He named the first step.", [said["id"]])["on_board"]
        assert drawn is (number < 9), f"lane {number}"


def test_a_null_in_a_life_subject_is_a_field_left_out_and_the_board_still_answers(db, client):
    tools.create_tracker("stretch", "Stretching", "practice", {"color": "red", "started": "2031-03-01", "rank": 1}, "Ten minutes.")
    made = tools.create_tracker("walk", "Walking", "practice", {"color": "red", "started": "2031-03-01", "rank": None,
                                                                "note": None}, "Any walk.")
    assert made["subject"] == {"color": "red", "started": "2031-03-01"} and made["on_board"] is True
    assert tools.create_tracker("garden", "Garden", "campaign", {"rank": None, "layout": None}, "Bed by bed.")["subject"] == {}
    # A row stored before nulls were dropped still sorts.
    Tracker.objects.filter(slug="walk").update(subject={"color": "red", "started": "2031-03-01", "rank": None})
    board = client.get("/api/life")
    assert board.status_code == 200 and [tile["id"] for tile in board.json()["pulse"]] == ["stretch", "walk"]
    for subject in (["rank"], "file"):
        with pytest.raises(ValueError, match="subject must be an object"):
            tools.create_tracker("pond", "Pond", "campaign", subject, "Dig it.")
        with pytest.raises(ValueError, match="subject must be an object"):
            tools.update_tracker("garden", subject=subject)


def test_a_lane_changes_only_on_a_fact_filed_in_the_same_turn(db, monkeypatch):
    tools.create_tracker("garden", "Garden", "campaign", {}, "Bed by bed.")
    earlier = tools.record_observation("garden", "2031-03-01", "", "The beds want digging.")
    turn = JobRun.objects.create(job=Job.objects.create(name="reply", kind="reply", trigger="manual", schedule="", target="x"))
    monkeypatch.setenv("GOLAIET_JOB_RUN_ID", str(turn.pk))
    change = {"stations": [{"id": "dig", "label": "Dig the beds", "track": "Beds"}]}
    with pytest.raises(ValueError, match="filed in this conversation turn"):
        tools.record_assessment("garden", change, "He said so.", [earlier["id"]])
    said = tools.record_observation("garden", "2031-03-08", "", "Dig the beds next.")
    assert tools.record_assessment("garden", change, "He said so.", [earlier["id"], said["id"]])["state"]["changed"] == ["dig"]


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
    Tracker.objects.create(slug="garden", title="Garden", kind="campaign", view="campaign_map", brief="Bed by bed.",
                           subject={"file": "Garden.md", "short": "Beds", "rank": 2})
    return tmp_path / "Garden.md"


def test_a_note_is_appended_as_one_dated_line(garden, monkeypatch):
    monkeypatch.setattr(tools.life, "today", lambda: datetime.date(2031, 3, 10))
    noted = tools.add_note("garden", "  the roses\nneed lime ")
    assert noted == {"file": "Garden.md", "line": "- 2031-03-10: the roses need lime"}
    tools.add_note("garden", "and the gate squeaks")
    assert garden.read_text(encoding="utf-8") == ("# Garden\n\nFirst line, no newline at the end\n"
                                                  "- 2031-03-10: the roses need lime\n- 2031-03-10: and the gate squeaks\n")


def test_the_note_is_dated_by_when_the_message_was_sent(garden, chat, monkeypatch):
    sent = poller.store_inbound(update(9, "Note for the garden: lime the roses"))
    monkeypatch.setenv("GOLAIET_MESSAGE_ID", str(sent.pk))
    assert tools.add_note("garden", "lime the roses")["line"] == "- 2031-03-08: lime the roses"


def test_where_a_lanes_notes_go_is_not_the_agents_to_set(garden):
    with pytest.raises(ValueError, match="Guy's to set"):
        tools.create_tracker("boat", "Boat", "campaign", {"file": "TODO.md"}, "The boat.")
    for subject in ({"file": "TODO.md"}, {"file": None}):
        with pytest.raises(ValueError, match="Guy's to set"):
            tools.update_tracker("garden", subject=subject)
    kept = tools.update_tracker("garden", subject={"file": "Garden.md", "layout": "wide", "short": None})
    assert kept["subject"] == {"file": "Garden.md", "rank": 2, "layout": "wide"}, "a partial subject keeps the rest; null removes"


def test_a_note_is_refused_when_it_has_nowhere_safe_to_go(garden, settings, tmp_path):
    before = garden.read_bytes()
    tools.create_tracker("boat", "Boat", "campaign", {}, "The boat.")
    for slug, file in (("shed", "../outside.md"), ("pond", "Pond.md"), ("list", "list.txt")):
        Tracker.objects.create(slug=slug, title=slug, kind="campaign", view="campaign_map", brief="-", subject={"file": file})
    (tmp_path.parent / "outside.md").write_text("not in the vault")
    (tmp_path / "list.txt").write_text("a list, not a note file")
    for slug, message in (("boat", "names no vault file"), ("shed", "inside the vault"), ("pond", "existing .md file"),
                          ("list", "existing .md file"), ("garden", "must not be empty")):
        with pytest.raises(ValueError, match=message):
            tools.add_note(slug, "" if slug == "garden" else "a note")
    settings.VAULT_DIR = ""
    with pytest.raises(ValueError, match="not reachable"):
        tools.add_note("garden", "a note")
    assert garden.read_bytes() == before and (tmp_path.parent / "outside.md").read_text() == "not in the vault"
    assert (tmp_path / "list.txt").read_text() == "a list, not a note file"


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
    assert Conversation.objects.count() == 2, "each case starts a session of its own"
    with pytest.raises(CommandError, match="scratch database"):
        call_command("replay", str(cases))
    Message.objects.all().delete()
    Conversation.objects.all().delete()
    filed_on["day"] = "2031-03-08"
    with pytest.raises(CommandError, match="1 case"):
        call_command("replay", str(cases))
    assert "MISS c1" in capsys.readouterr().out
    Message.objects.all().delete()
    cases.write_text(json.dumps({"cases": [{"id": "c3", "sent": {"date": "2031-03-08"}, "text": "Stretched", "expected": []}]}))
    with pytest.raises(CommandError, match="c3: `sent` needs a time"):
        call_command("replay", str(cases))


# ---------------- the Friday brief ----------------

@pytest.fixture
def week(chat):
    """A conversation, and a board with a week on it: a pass, an event, a check gone by, a proposal."""
    Conversation.objects.create(chat_id="6307", session_id="22222222-2222-2222-2222-222222222222")
    tools.create_tracker("stretch", "Stretching", "practice", {"color": "red", "started": "2031-03-01"}, "Ten minutes count.")
    tools.record_observation("stretch", "2031-03-12", "", "Stretched.")
    tools.create_tracker("garden", "Garden", "campaign", {"short": "Garden"}, "Bed by bed.")
    said = tools.record_observation("garden", "2031-03-11", "", "The beds are dug; the fence by the 12th; maybe a pond.")
    tools.record_assessment("garden", {"stations": [
        {"id": "dig", "label": "Dig the beds", "track": "Beds", "state": "passed", "date": "2031-03-11"},
        {"id": "fence", "label": "Mend the fence", "track": "Beds", "state": "current", "check": "2031-03-12"},
        {"id": "pond", "label": "Dig a pond", "track": "Water", "state": "proposed"}]}, "He listed the work.", [said["id"]])
    return Job.objects.create(name="brief", kind="digest", trigger="cron", schedule="30 7 * * fri", target="agent.flows.brief.run")


FRIDAY = datetime.date(2031, 3, 14)


def test_the_brief_is_built_from_the_weeks_rows(week):
    text = brief.prompt(FRIDAY, None)
    for line in ("- Garden: Dig the beds (Mar 11)", "- Stretching: reported on Wed 12", "- Garden — Mend the fence: check date Mar 12",
                 "- Garden: Dig a pond", "at most three questions", "ANSWERED: first"):
        assert line in text
    quiet = brief.week_of(datetime.date(2031, 4, 20))
    assert "Passed this week:\n- nothing" in quiet and "Practices that moved this week:\n- nothing" in quiet


def brief_run(job, monkeypatch, answer):
    calls = []

    class Runner:
        def __init__(self, model=None):
            pass

        def run(self, prompt, **kwargs):
            calls.append({"prompt": prompt, "locked": flows.conversation_turn.locked(), **kwargs})
            return AgentResult(text=answer, session_id="33333333-3333-3333-3333-333333333333")

    monkeypatch.setattr(brief, "ClaudeRunner", Runner)
    monkeypatch.setattr(brief.life, "today", lambda: FRIDAY)
    run = JobRun.objects.create(job=job)
    report = brief.run(job, run)
    run.summary, run.status = report["summary"], "failed" if report.get("failed") else "done"
    run.save()
    return report, calls


def test_the_brief_goes_out_from_the_conversations_own_session(week, chat, monkeypatch):
    report, calls = brief_run(week, monkeypatch, "The beds are dug.\n1. Move the fence date?\nANSWERED: first")
    call = calls[0]
    assert call["resume"].startswith("2222") and call["locked"] and call["tools"] == []
    assert all(tool.rpartition("__")[2] in ("list_trackers", "get_tracker", "search_observations") for tool in call["allowed_tools"])
    assert chat == ["The beds are dug.\n1. Move the fence date?"] and report["summary"].startswith("judged=none answered=first delivered")
    assert Conversation.objects.get().session_id.startswith("3333")
    assert Message.objects.get(direction="out").job_run.job == week
    _, calls = brief_run(week, monkeypatch, "Nothing new.\nANSWERED: yes")
    assert "Your previous brief, as it was delivered on" in calls[0]["prompt"]


def test_the_verdict_is_read_from_the_rows_by_a_session_that_never_saw_the_brief(week, chat, monkeypatch):
    brief_run(week, monkeypatch, "The beds are dug.\n1. Move the fence date?\nANSWERED: first")
    delivered = Message.objects.get(direction="out").created_at
    conversation = Conversation.objects.get()
    for text, hours in (("Move the fence to the 20th", 5), ("Too late to count", 49)):
        Message.objects.create(conversation=conversation, direction="in", text=text, sent_at=delivered + datetime.timedelta(hours=hours))

    class Stranger:
        """A session with no memory: it answers yes only when the prompt itself shows the question taken up."""
        def __init__(self, model=None):
            pass

        def run(self, prompt, **kwargs):
            shown = "1. Move the fence date?" in prompt and "Move the fence to the 20th" in prompt
            assert "Too late to count" not in prompt
            return AgentResult(text=f"Next brief.\nANSWERED: {'yes' if shown else 'no'}", session_id="4" * 8)

    monkeypatch.setattr(brief, "ClaudeRunner", Stranger)
    monkeypatch.setattr(brief.life, "today", lambda: FRIDAY)
    assert " answered=yes " in brief.run(week, JobRun.objects.create(job=week))["summary"]
    assert " answered=no " in brief.run(week, JobRun.objects.create(job=week))["summary"], "nothing followed the second brief"


def test_only_the_last_line_is_the_verdict(week, chat, monkeypatch):
    report, _ = brief_run(week, monkeypatch, "Answered last week: the fence moved.\n1. Keep the pond?\nANSWERED: first\n")
    assert chat == ["Answered last week: the fence moved.\n1. Keep the pond?"] and " answered=first " in report["summary"]


def test_three_unanswered_briefs_in_a_row_switch_it_off_once(week, chat, monkeypatch):
    for answer in ("first", "no", "no"):
        brief_run(week, monkeypatch, f"A brief.\nANSWERED: {answer}")
    week.refresh_from_db()
    assert week.enabled and len(chat) == 3
    report, _ = brief_run(week, monkeypatch, "A fourth brief.\nANSWERED: no")
    week.refresh_from_db()
    assert not week.enabled and chat[-1] == brief.SWITCHED_OFF and "switched off" in report["summary"]


def test_an_answer_or_a_missing_verdict_breaks_the_run_of_unanswered(week, chat, monkeypatch):
    for answer in ("A brief.\nANSWERED: no", "A brief.\nANSWERED: no", "A brief with no verdict line.", "A brief.\nANSWERED: no"):
        brief_run(week, monkeypatch, answer)
    week.refresh_from_db()
    assert week.enabled and brief.SWITCHED_OFF not in chat


def test_a_friday_that_did_not_go_out_is_not_a_second_no_for_the_same_brief(week, monkeypatch):
    lands = {"now": True}
    sent = []
    monkeypatch.setattr(telegram, "send", lambda text, **kw: (sent.append(text) or len(sent)) if lands["now"] else None)
    brief_run(week, monkeypatch, "Brief one.\nANSWERED: first")
    brief_run(week, monkeypatch, "Brief two.\nANSWERED: no")
    lands["now"] = False
    brief_run(week, monkeypatch, "Lost on the way.\nANSWERED: no")
    lands["now"] = True
    brief_run(week, monkeypatch, "Brief three.\nANSWERED: no")
    week.refresh_from_db()
    assert week.enabled, "two delivered briefs were judged, not three"
    lands["now"] = False
    report, _ = brief_run(week, monkeypatch, "Brief four.\nANSWERED: no")
    week.refresh_from_db()
    assert report["failed"] and week.enabled, "a switch-off nobody was told of does not happen"
    lands["now"] = True
    brief_run(week, monkeypatch, "Brief four.\nANSWERED: no")
    week.refresh_from_db()
    assert not week.enabled and sent[-1] == brief.SWITCHED_OFF and "in the admin" in brief.SWITCHED_OFF

    week.enabled = True
    week.save()
    _, calls = brief_run(week, monkeypatch, "Back again.\nANSWERED: first")
    assert "No brief was delivered before this one" in calls[0]["prompt"], "the switch-off notice is not a brief to judge"
    for _ in range(2):
        brief_run(week, monkeypatch, "Another.\nANSWERED: no")
    week.refresh_from_db()
    assert week.enabled, "the count starts again after a switch-off"
    brief_run(week, monkeypatch, "Another.\nANSWERED: no")
    week.refresh_from_db()
    assert not week.enabled


@pytest.mark.parametrize("line, verdict", [("**Answered:** No.", "no"), ("answered - YES", "yes"), ("`ANSWERED: first`", "first"),
                                           ("ANSWERED: perhaps", "unknown"), ("ANSWERED: not sure", "unknown")])
def test_the_verdict_line_is_read_leniently_and_never_sent(week, chat, monkeypatch, line, verdict):
    report, _ = brief_run(week, monkeypatch, f"The beds are dug.\n1. Move the fence date?\n\n{line}")
    assert chat == ["The beds are dug.\n1. Move the fence date?"] and f"answered={verdict} " in report["summary"]


def test_the_brief_skips_an_empty_board_and_a_failed_session_sends_nothing(chat, monkeypatch, db):
    job = Job.objects.create(name="brief", kind="digest", trigger="cron", schedule="30 7 * * fri", target="agent.flows.brief.run")
    assert brief.run(job, JobRun.objects.create(job=job))["summary"].startswith("skipped")
    Conversation.objects.create(chat_id="6307")
    tools.create_tracker("stretch", "Stretching", "practice", {"color": "red", "started": "2031-03-01"}, "Ten minutes count.")
    monkeypatch.setattr(brief.ClaudeRunner, "run", lambda self, prompt, **kw: AgentResult(text="usage limit reached", is_error=True))
    assert brief.run(job, JobRun.objects.create(job=job))["failed"] and chat == []


def test_the_brief_job_is_seeded_for_friday_morning(db):
    call_command("seed_jobs", verbosity=0)
    job = Job.objects.get(name="brief")
    assert (job.kind, job.schedule, job.target) == ("digest", "30 7 * * fri", "agent.flows.brief.run")
