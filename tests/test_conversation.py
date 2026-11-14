"""The conversation as the collector of Guy's own life: when a message was
sent, what the model is told, the tools the life rules lean on, the note in
the vault, and the replay. Invented content throughout."""
import datetime
import io
import json
import os
from pathlib import Path
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
    Conversation.objects.update(conventions="- Distances are given in kilometres.")
    reply.run(run.job, run, message_id=poller.store_inbound(update(8, "Stretched")).pk)
    assert session[1]["prompt"] == ("[Sent Saturday 2031-03-08 08:22, Asia/Jerusalem time]\n[Guy's standing conventions for every report:\n"
                                    "- Distances are given in kilometres.]\nStretched")


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
    Tracker.objects.filter(slug="stretch").update(subject={"color": "red", "started": "2031-03-01", "rank": "first"})
    assert client.get("/api/life").status_code == 200, "a rank that is not a number is a rank that is missing"
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


def event(tracker, date, **more):
    return {"tracker": tracker, "effect": "event", "date": date, **more}


CASES = {"cases": [
    {"id": "c1", "sent": {"date": "2031-03-08", "time": "07:30"}, "text": "Stretched last night", "expected": [event("stretch", "2031-03-07")]},
    {"id": "c2", "sent": {"date": "2031-03-09", "assumed_time": "09:00"}, "text": "What is the weather like?",
     "expected": [{"tracker": None, "effect": "answer_only"}, {"tracker": "garden", "effect": "note", "file": "garden.md"}]},
    {"id": "c3", "sent": {"date": "2031-03-09", "time": "21:00"}, "text": "Count my swims from now on; I swam today",
     "expected": [{"tracker": "swim", "effect": "new_tracker"}, event("swim", "2031-03-09")]},
    {"id": "c4", "sent": {"date": "2031-03-11", "time": "08:00"}, "text": "Swam yesterday", "expected": [event("swim", "2031-03-10")]},
    {"id": "c5", "sent": {"date": "2031-03-11", "time": "09:00"}, "text": "As I said, I did stretch on the 7th", "expected": [event("stretch", "2031-03-07")]},
    {"id": "c6", "sent": {"date": "2031-03-12", "time": "00:30"}, "text": "Stretched around midnight",
     "expected": [event("stretch", "2031-03-11", **{"or": ["2031-03-12"]})]},
    {"id": "c7", "sent": {"date": "2031-03-12", "time": "10:00"}, "text": "Start counting my naps",
     "expected": [{"tracker": "nap", "effect": "new_tracker"}, {"tracker": "nap", "effect": "start", "date": "2031-03-12"}]},
    {"id": "c8", "sent": {"date": "2031-03-13", "time": "18:00"}, "text": "Napped after lunch", "expected": [event("nap", "2031-03-13")]},
]}
# What the session does on each message: ("create", slug, started) and ("file", slug, day). The slugs
# of the practices it creates are its own, not the ids the cases use.
SCRIPT = {
    "Stretched last night": [("file", "stretch", "2031-03-07")],
    "Count my swims from now on; I swam today": [("create", "swimming-laps", "2031-03-09"), ("file", "swimming-laps", "2031-03-09")],
    "Swam yesterday": [("file", "swimming-laps", "2031-03-10")],
    "As I said, I did stretch on the 7th": [("file", "stretch", "2031-03-07")],
    "Stretched around midnight": [("file", "stretch", "2031-03-12")],
    "Start counting my naps": [("create", "naps", "2031-03-12")],
    "Napped after lunch": [("file", "naps", "2031-03-13")],
}


@pytest.fixture
def replayed(db, tmp_path, monkeypatch, settings):
    """The replay with the CLI replaced by a script of what the session files for each message."""
    settings.TELEGRAM_BOT_TOKEN, settings.TELEGRAM_CHAT_ID, settings.CLAUDE_CONFIG_DIR = "123:token", "6307", str(tmp_path / "state")
    settings.VAULT_DIR = str(tmp_path)
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "a-token")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:token")
    monkeypatch.setenv("VAULT_DIR", str(tmp_path))
    tools.create_tracker("stretch", "Stretching", "practice", {"color": "red", "started": "2031-03-01"}, "Ten minutes count.")
    Conversation.objects.create(chat_id="6307", conventions="- Distances are given in kilometres.")
    script, states = dict(SCRIPT), []

    def session(self, prompt, *, env, **kwargs):
        states.append(settings.CLAUDE_CONFIG_DIR)
        assert os.environ["TELEGRAM_BOT_TOKEN"] == "", "what the CLI and its tool server inherit sends nothing either"
        assert os.environ["VAULT_DIR"] == settings.VAULT_DIR == "", "and no note can be written: the vault's folder is switched off"
        if Conversation.objects.filter(chat_id="6307").exclude(conventions="").exists():
            assert "conventions for every report:\n- Distances are given in kilometres" in prompt, "each case reads Guy's conventions"
        monkeypatch.setenv("GOLAIET_MESSAGE_ID", str(env["GOLAIET_MESSAGE_ID"]))
        for action, slug, day in script.get(prompt.rpartition("\n")[2], []):
            if action == "limit":
                return AgentResult(text="Claude usage limit reached. It resets at 9pm.", is_error=True, exit_code=1)
            if action == "note":
                with pytest.raises(ValueError, match="VAULT_DIR is not set"):
                    tools.add_note(slug, day)
            elif action == "retract":
                wrong = Observation.objects.get(tracker__slug=slug, observed_at=tools._parse_when(day, "day"))
                Observation.objects.create(tracker=wrong.tracker, summary="Not so", observed_at=wrong.observed_at,
                                           payload={"retracts": wrong.pk}, job_run_id=env["GOLAIET_JOB_RUN_ID"])
            elif action == "create":
                tools.create_tracker(slug, slug.title(), "practice", {"color": "red", "started": day}, "Any one counts.")
            elif Tracker.objects.filter(slug=slug).exists():
                Observation.objects.create(tracker=Tracker.objects.get(slug=slug), summary="As he said",
                                           observed_at=tools._parse_when(day, "day"), job_run_id=env["GOLAIET_JOB_RUN_ID"])
        return AgentResult(text="Recorded.", session_id="11111111-1111-1111-1111-111111111111")

    monkeypatch.setattr(reply.ClaudeRunner, "run", session)
    monkeypatch.setattr(telegram, "_post", lambda *a, **k: pytest.fail("the replay sends nothing"))
    cases = tmp_path / "cases.json"
    cases.write_text(json.dumps(CASES))
    return cases, script, states


def replay(cases, capsys, *more, misses=0, stopped=""):
    """The replay's lines by case id; fails unless exactly `misses` cases missed, or it stopped in the words given."""
    if misses or stopped:
        with pytest.raises(CommandError, match=stopped or f"^{misses} case"):
            call_command("replay", str(cases), *more)
    else:
        call_command("replay", str(cases), *more)
    printed = capsys.readouterr().out
    verdicts = {line.split()[1]: line.split()[0] for line in printed.splitlines() if line[:4] in ("ok  ", "MISS", "n/c ")}
    return verdicts, printed


def test_the_replay_compares_each_practices_days_before_and_after_the_run(replayed, capsys, tmp_path):
    cases, _, states = replayed
    verdicts, printed = replay(cases, capsys)
    assert verdicts == {case: "ok" for case in ("c1", "c3", "c4", "c5", "c6", "c7", "c8")}, printed
    assert "not run, to be read by hand: c2" in printed and printed.rstrip().endswith("every event landed")
    assert Conversation.objects.filter(chat_id__startswith="replay-").count() == 7, "a session of its own per case that is run"
    assert len(set(states)) == 1 and states[0] != str(tmp_path / "state")
    assert not Path(states[0]).exists(), "the transcripts' folder is gone when the replay ends"
    with pytest.raises(CommandError, match="scratch database"):
        call_command("replay", str(cases))


def test_a_day_that_is_missing_and_a_day_nobody_expected_are_both_misses(replayed, capsys):
    cases, script, _ = replayed
    script["Stretched last night"] = [("file", "stretch", "2031-03-08")]
    script["As I said, I did stretch on the 7th"] = []
    script["Stretched around midnight"] = [("file", "stretch", "2031-03-11"), ("file", "stretch", "2031-03-10")]
    verdicts, printed = replay(cases, capsys, misses=3)
    assert [verdicts[case] for case in ("c1", "c5", "c6")] == ["MISS", "MISS", "MISS"]
    assert "wanted stretch on 2031-03-07; its days are now ['2031-03-08']" in printed
    assert "added stretch on 2031-03-08, which was not expected" in printed
    assert "added stretch on 2031-03-10, which was not expected" in printed and "added stretch on 2031-03-11" not in printed


@pytest.mark.parametrize("expected_day, does, verdict", [
    ("2031-03-08", [("create", "swimming-laps", "2031-03-08")], "ok"),     # a start in the past is the report itself
    ("2031-03-09", [("create", "swimming-laps", "2031-03-09")], "MISS"),   # a start on the sending day is only the default
])
def test_a_start_counts_as_the_report_only_when_it_is_before_the_day_of_the_message(replayed, capsys, expected_day, does, verdict):
    cases, script, _ = replayed
    told = json.loads(json.dumps(CASES))
    told["cases"][2]["expected"][1]["date"] = expected_day
    cases.write_text(json.dumps(told))
    script["Count my swims from now on; I swam today"] = does
    verdicts, _ = replay(cases, capsys, misses=int(verdict == "MISS"))
    assert (verdicts["c3"], verdicts["c4"]) == (verdict, "ok"), "the practice was born either way, so the later case is compared"


@pytest.mark.parametrize("does, created", [([], 0), ([("create", "swimming-laps", "2031-03-09"), ("create", "pool", "2031-03-09")], 2)])
def test_a_report_on_a_practice_that_was_never_born_is_not_comparable_and_not_a_miss(replayed, capsys, does, created):
    cases, script, _ = replayed
    script["Count my swims from now on; I swam today"] = does
    verdicts, printed = replay(cases, capsys, misses=1)
    assert (verdicts["c3"], verdicts["c4"]) == ("MISS", "n/c")
    assert f"it should create one practice (swim) and created {created}" in printed
    assert "c4 not comparable: swim was never created" in printed
    assert not Conversation.objects.filter(chat_id="replay-c4").exists(), "no session is spent on it"


def test_a_case_that_only_bears_a_practice_passes_when_it_creates_one_and_adds_no_day(replayed, capsys):
    cases, script, _ = replayed
    script["Start counting my naps"] = [("create", "naps", "2031-03-12"), ("file", "naps", "2031-03-12")]
    verdicts, printed = replay(cases, capsys, misses=1)
    assert (verdicts["c7"], verdicts["c8"]) == ("MISS", "ok") and "added nap on 2031-03-12, which was not expected" in printed


def test_only_runs_one_case_and_names_the_case_that_must_come_first(replayed, capsys):
    cases, _, _ = replayed
    with pytest.raises(CommandError, match="--only c4: it reports on a practice that c3 creates; run without --only"):
        call_command("replay", str(cases), "--only", "c4")
    with pytest.raises(CommandError, match="--only c2: no case of that id"):
        call_command("replay", str(cases), "--only", "c2")
    assert not Message.objects.exists()
    verdicts, _ = replay(cases, capsys, "--only", "c3")
    assert verdicts == {"c3": "ok"}


def test_the_replay_checks_every_case_before_it_spends_a_session(replayed, monkeypatch):
    cases, _, _ = replayed
    monkeypatch.setattr(reply.ClaudeRunner, "run", lambda *a, **k: pytest.fail("no session before the cases are checked"))
    broken = json.loads(json.dumps(CASES))
    broken["cases"][2]["sent"] = {"date": "2031-03-09", "time": "21:3x"}
    broken["cases"][3]["id"] = "c1"
    del broken["cases"][4]["sent"]["date"]
    cases.write_text(json.dumps(broken))
    with pytest.raises(CommandError, match="no session was run: c1: the id repeats"):
        call_command("replay", str(cases))
    broken["cases"][3]["id"] = "c4"
    cases.write_text(json.dumps(broken))
    with pytest.raises(CommandError, match="no session was run: c3: `sent` needs .*'21:3x'; c5: `sent` needs a date"):
        call_command("replay", str(cases))
    shapeless = {"cases": [{"id": "d1", "sent": {"date": "2031-03-08", "time": "07:30"}, "text": "Stretched", "expected": [
        {"tracker": "stretch", "effect": "event"}, {"effect": "event", "date": "2031-03-08"}, {"tracker": "stretch"}]},
        {"sent": {"date": "2031-03-08"}, "text": "No id", "expected": []}, {"id": "d3", "text": "No time at all", "expected": []},
        {"id": "d4", "sent": {"date": "2031-03-08", "time": "07:30"}, "text": "Stretched", "expected": [event("stretch", "2031-03-07", **{"or": "2031-03-08"})]},
        {"id": "d5", "sent": {"date": "2031-03-08", "time": "07:30"}, "text": "Count it", "expected": [{"effect": "new_tracker"}]}]}
    cases.write_text(json.dumps(shapeless))
    with pytest.raises(CommandError) as refused:
        call_command("replay", str(cases))
    for words in ("d1: an expected effect has no date", "d1: an expected effect has no tracker", "d1: an expected effect has no effect",
                  "d3: a case needs `sent`", "case 2: it has no id", "d4: `or` must be a list of days, got '2031-03-08'",
                  "d5: an expected effect has no tracker"):
        assert words in str(refused.value)
    assert not Message.objects.exists()
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN")
    with pytest.raises(CommandError, match="CLAUDE_CODE_OAUTH_TOKEN"):
        call_command("replay", str(cases))


def test_a_day_the_run_removed_and_a_practice_nobody_asked_for_are_misses(replayed, capsys):
    cases, script, _ = replayed
    script["As I said, I did stretch on the 7th"] = [("retract", "stretch", "2031-03-07")]
    script["Stretched around midnight"] = [("file", "stretch", "2031-03-12"), ("create", "midnights", "2031-03-12")]
    verdicts, printed = replay(cases, capsys, misses=2)
    assert (verdicts["c5"], verdicts["c6"]) == ("MISS", "MISS")
    assert "removed stretch on 2031-03-07, which was there before the run" in printed
    assert "it created a practice (midnights), which was not expected" in printed


def test_the_replay_stops_at_the_plans_limit_and_counts_neither_that_case_nor_the_rest(replayed, capsys):
    cases, script, _ = replayed
    script["Stretched last night"] = []
    script["Swam yesterday"] = [("limit", "", "")]
    verdicts, printed = replay(cases, capsys, stopped="stopped at the plan's usage limit on c4, which is not counted; the last case judged was c3; "
                                                      "not run: c5, c6, c7, c8. Before it: 1 case\\(s\\) did not file what was expected")
    assert verdicts == {"c1": "MISS", "c3": "ok"}, printed
    assert not Conversation.objects.filter(chat_id="replay-c5").exists()


def test_a_replay_without_conventions_says_so_before_the_first_case(replayed, capsys):
    cases, script, _ = replayed
    Conversation.objects.update(conventions="")
    verdicts, printed = replay(cases, capsys, "--only", "c1")
    assert printed.index("the conversation's row has no conventions") < printed.index("ok   c1")


def test_a_replayed_message_that_asks_for_a_note_cannot_write_one(replayed, capsys, tmp_path):
    cases, script, _ = replayed
    (tmp_path / "garden.md").write_text("as it was")
    Tracker.objects.create(slug="garden", title="Garden", kind="campaign", view="campaign_map", brief="Bed by bed.",
                           subject={"file": "garden.md", "short": "Beds"})
    script["Stretched last night"] = [("note", "garden", "a line for the vault"), ("file", "stretch", "2031-03-07")]
    verdicts, _ = replay(cases, capsys, "--only", "c1")
    assert verdicts == {"c1": "ok"} and (tmp_path / "garden.md").read_text() == "as it was"


def test_list_prints_what_would_be_run_with_no_session_and_no_database(tmp_path, capsys, monkeypatch):
    """No `db` fixture: a query would fail the test."""
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    cases = tmp_path / "cases.json"
    cases.write_text(json.dumps(CASES))
    call_command("replay", str(cases), "--list")
    assert capsys.readouterr().out.splitlines() == [
        "run and compared (6): c1, c3, c4, c5, c6, c8", "run only to bear a practice (1): c7", "set aside, to be read by hand (1): c2"]


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


def test_a_line_that_is_only_the_verdict_is_removed_wherever_it_stands(week, chat, monkeypatch):
    report, calls = brief_run(week, monkeypatch, "Answered last week: the fence moved.\n1. Keep the pond?\nANSWERED: first\nGood luck with the fence.")
    assert chat == ["Answered last week: the fence moved.\n1. Keep the pond?\nGood luck with the fence."]
    assert " answered=first " in report["summary"]
    assert "Write that line in English, exactly as given" in calls[0]["prompt"]
    report, _ = brief_run(week, monkeypatch, "ANSWERED: no\nA brief.\n**ANSWERED:** yes")
    assert chat[-1] == "A brief." and " answered=yes " in report["summary"], "the last such line is the verdict"


def test_a_reply_that_is_only_the_verdict_sends_nothing_and_fails(week, chat, monkeypatch):
    report, _ = brief_run(week, monkeypatch, "ANSWERED: first\n")
    assert report["failed"] and "no brief" in report["summary"] and chat == []
    assert not Message.objects.filter(direction="out").exists()


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
