"""pull_db with the two binaries and every statement on a whole database
stood in for. These tests run on the Postgres of the running stack, in a
database beside the live one, so nothing here creates, renames or drops a
database or ends a session: restore.Server is replaced whole. The real ones
run inside the end-to-end stack (tests/e2e/stack_check.py)."""
import contextlib
import json
import subprocess
from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.db.migrations.loader import MigrationLoader

from chat.models import Conversation
from core import backup, restore, standing
from core.management.commands import pull_db


class Stage:
    """What the stood-in server answers, and what was asked of it."""

    def __init__(self, calls):
        self.calls = calls                 # the binaries' calls and the server's, in the order they happened
        self.counts = {"core_tracker": 2, "django_migrations": 30}
        self.applied = set(MigrationLoader(None).disk_migrations)
        self.busy = 0                      # how many swaps find a session on the database
        self.sessions = 3                  # sessions ended by each round
        self.named = []
        self.left_half_done = []
        self.taken = []                    # for each time the names are looked for, a function that says which are taken
        self.scheduler_alive = False       # whether a scheduler holds the lock when the swap looks
        self.fail = None                   # the step that raises

    def steps(self) -> list[str]:
        return [" ".join(call["arguments"][:2]) for call in self.calls]

    def server(self):
        stage = self

        class Server:
            def __getattr__(self, step):
                def asked(*arguments):
                    stage.calls.append({"arguments": ["server", step, *arguments]})
                    if stage.fail == step:
                        raise RuntimeError(f"{step} failed")
                    if step == "swap" and stage.busy:
                        stage.busy -= 1
                        raise restore.InUse("the database is being accessed by other users")
                    if step == "named_from":
                        if not arguments[0].endswith(("_incoming_", "_before_")):   # every database named after the live one
                            return stage.named + stage.left_half_done + stage.taken.pop(0)() if stage.taken else stage.named
                        return stage.left_half_done if "_incoming_" in arguments[0] else stage.named
                    return {"counts": stage.counts, "applied_migrations": stage.applied, "end_sessions": stage.sessions,
                            "scheduler_alive": stage.scheduler_alive}.get(step)
                return asked
        self.calls.append({"arguments": ["server", "opened"]})
        return Server()


@pytest.fixture
def stage(tools, monkeypatch):
    calls, _ = tools
    stage = Stage(calls)
    monkeypatch.setattr(restore, "Server", stage.server)
    monkeypatch.setattr(pull_db.time, "sleep", lambda seconds: None)
    return stage


@pytest.fixture
def archive(tmp_path):
    path = tmp_path / "nightly-2031-03-01.dump"
    path.write_text("an archive")
    return path


def pull(*arguments, **options) -> str:
    printed = StringIO()
    call_command("pull_db", *[str(argument) for argument in arguments], stdout=printed, **options)
    return printed.getvalue()


def refusal(*arguments, **options) -> str:
    with pytest.raises(CommandError) as refused:
        pull(*arguments, **options)
    return str(refused.value)


def test_it_refuses_where_the_tools_are_missing(monkeypatch, archive):
    monkeypatch.setattr(backup.shutil, "which", lambda tool: None)
    assert "docker compose run --rm scheduler python manage.py pull_db <source>" in refusal(archive)


@pytest.mark.django_db
def test_it_refuses_a_file_that_is_not_there_and_one_that_is_no_dump(stage, tools, archive, settings):
    said = refusal(archive.with_name("no-such.dump"))
    assert "There is no file at" in said and f"{settings.BACKUP_DIR} is BACKUP_HOST_DIR of the machine" in said
    tools[1].append("pg_restore --list")
    assert "is not a dump that pg_restore reads" in refusal(archive)
    assert "server opened" not in stage.steps(), "nothing was created"


@pytest.mark.django_db
def test_it_refuses_while_a_scheduler_holds_the_lock_and_says_how_to_stop_it(stage, archive):
    holder = standing.SchedulerLock()
    assert holder.take()
    try:
        said = refusal(archive, takeover=True, replace=True)
    finally:
        holder.release()
    assert "A scheduler holds the lock" in said and "docker compose rm --stop --force scheduler" in said
    assert "stop scheduler" not in said, "a stopped container starts again with Docker"
    assert "server opened" not in stage.steps()


@pytest.mark.django_db
def test_it_refuses_to_replace_what_somebody_wrote_unless_told_to(stage, archive, tracker):
    said = refusal(archive)
    assert "holds rows that somebody wrote (core_tracker 1)" in said and "give --replace" in said
    assert "server opened" not in stage.steps()
    assert "COPY" in pull(archive, replace=True)


@pytest.mark.django_db
def test_a_copy_is_restored_beside_checked_marked_and_only_then_swapped(stage, archive):
    stage.named = ["test_golaiet_before_20310101T000000Z"]
    stage.left_half_done = ["test_golaiet_incoming_20310102T000000Z"]
    said = pull(archive)   # the test database was only migrated, which counts as empty: no --replace

    live = connection.settings_dict["NAME"]
    assert stage.steps() == ["pg_restore --list", "server opened", "server named_from", "server create", "pg_restore --no-owner", "server counts",
                             "server applied_migrations", "server comment", "server scheduler_alive", "server end_sessions",
                             "server swap", "server named_from", "server named_from", "server close"]
    restored = next(call["arguments"] for call in stage.calls if call["arguments"][:2] == ["pg_restore", "--no-owner"])
    incoming = stage.calls[3]["arguments"][2]
    assert incoming.startswith(f"{live}_incoming_") and f"--dbname={incoming}" in restored
    assert {"--no-acl", "--exit-on-error"} <= set(restored) and "--create" not in restored
    assert connection.settings_dict["PASSWORD"] not in restored
    marked, text = next(call["arguments"][2:] for call in stage.calls if call["arguments"][:2] == ["server", "comment"])
    assert marked == incoming and text.startswith(standing.MARK_WORD) and str(archive) in text
    swapped = next(call["arguments"][2:] for call in stage.calls if call["arguments"][:2] == ["server", "swap"])
    assert swapped[:2] == [live, incoming] and swapped[2].startswith(f"{live}_before_")

    assert f"{live} now holds what {archive} held" in said
    assert "nothing to compare the restore with" in said and "  core_tracker 2" in said
    assert "3 other session(s)" in said and f'DROP DATABASE "{swapped[2]}";' in said
    assert 'An earlier one is still there: DROP DATABASE "test_golaiet_before_20310101T000000Z";' in said
    assert 'A pull that was killed left its new database behind: DROP DATABASE "test_golaiet_incoming_20310102T000000Z";' in said
    assert "This is a COPY" in said and "`make stack-without-scheduler`" in said and "LIVE" not in said


@pytest.mark.django_db
def test_a_takeover_is_not_marked_and_says_whose_word_it_took_and_where_the_session_is(stage, archive, settings, tmp_path):
    settings.CLAUDE_CONFIG_DIR = str(tmp_path / "state")
    Conversation.objects.create(chat_id="6307", session_id="0f0e0d0c-0b0a-4908-8706-050403020100")
    said = pull(archive, takeover=True, replace=True)
    assert "server comment" not in stage.steps() and "server swap" in stage.steps()
    assert "This is now the LIVE database: it is not marked" in said and "taken on your word" in said
    assert "`docker compose up -d`" in said and "COPY" not in said
    assert "does not hold the conversation's session: the next message opens a new session" in said

    sessions = tmp_path / "state" / "projects" / "-app-agent-runs"
    sessions.mkdir(parents=True)
    (sessions / "0f0e0d0c-0b0a-4908-8706-050403020100.jsonl").write_text("")
    assert "holds the conversation's session: the conversation goes on" in pull(archive, takeover=True, replace=True)


@pytest.mark.django_db
def test_the_counts_beside_the_dump_are_compared_and_a_difference_stops_it(stage, archive):
    backup.beside(archive).write_text(json.dumps({"taken_at": "2031-03-01T03:15:02+02:00", "migrations": {}, "counts": stage.counts}))
    assert "the ones the dump wrote down when it was taken (2031-03-01T03:15:02+02:00)" in pull(archive)

    stage.calls.clear()
    stage.counts = {"core_tracker": 1, "django_migrations": 30}
    said = refusal(archive)
    assert "does not hold what the dump counted" in said and "core_tracker 1 (the dump: 2)" in said
    assert stage.steps()[-2:] == ["server drop", "server close"] and "server swap" not in stage.steps()


@pytest.mark.django_db
def test_a_dump_newer_than_the_code_is_refused_before_the_swap(stage, archive):
    stage.applied = stage.applied | {("core", "9999_from_a_later_code")}
    said = refusal(archive)
    assert "the dump is newer than this code" in said and "core 9999_from_a_later_code" in said
    assert "Bring the code forward first" in said
    assert "server drop" in stage.steps() and "server swap" not in stage.steps() and "server migrate" not in stage.steps()


@pytest.mark.django_db
def test_a_dump_older_than_the_code_is_migrated_before_the_mark_and_the_swap(stage, archive):
    last = max(name for app, name in stage.applied if app == "scheduler")
    stage.applied = stage.applied - {("scheduler", last)}
    said = pull(archive)
    steps = stage.steps()
    assert steps.index("server migrate") < steps.index("server comment") < steps.index("server swap")
    assert f"applied before the swap: scheduler {last}." in said


@pytest.mark.django_db
@pytest.mark.parametrize("step", ["pg_restore --no-owner", "counts", "applied_migrations", "migrate", "comment",
                                  "scheduler_alive", "end_sessions", "swap"])
def test_a_failure_at_any_step_before_the_swap_drops_the_new_database_and_changes_no_name(stage, tools, archive, step):
    stage.applied = stage.applied - {("scheduler", max(name for app, name in stage.applied if app == "scheduler"))}
    if step.startswith("pg_restore"):
        tools[1].append(step)
        said = refusal(archive)
        assert "Nothing was replaced: pg_restore failed (exit 1), at table core_tracker" in said and "a-row-of-the-data" not in said
    else:
        stage.fail = step
        with pytest.raises(RuntimeError, match=f"{step} failed"):
            pull(archive)
    steps = stage.steps()
    created = next(call["arguments"][2] for call in stage.calls if call["arguments"][:2] == ["server", "create"])
    dropped = [call["arguments"][2] for call in stage.calls if call["arguments"][:2] == ["server", "drop"]]
    assert dropped == [created] and steps[-1] == "server close"
    assert steps.count("server swap") == (1 if step == "swap" else 0), "no swap went through"


@pytest.mark.django_db
def test_the_swap_tries_again_when_a_session_came_back_and_gives_up_with_nothing_changed(stage, archive, monkeypatch):
    stage.busy = 2
    said = pull(archive)
    assert stage.steps().count("server end_sessions") == 3 and stage.steps().count("server swap") == 3
    assert "9 other session(s)" in said

    stage.calls.clear()
    stage.busy = 1000
    monkeypatch.setattr(pull_db, "SWAP_PATIENCE_SEC", 0)
    assert "a session kept coming back" in refusal(archive)
    assert stage.steps()[-2:] == ["server drop", "server close"]


@pytest.mark.django_db
def test_a_scheduler_that_started_during_the_pull_stops_the_swap_with_nothing_changed(stage, archive):
    stage.scheduler_alive = True
    said = refusal(archive)
    assert "a scheduler started on" in said and "during the pull" in said and "rm --stop --force scheduler" in said
    steps = stage.steps()
    assert "server end_sessions" not in steps and "server swap" not in steps, "it looked before it ended anybody's session"
    assert steps[-2:] == ["server drop", "server close"]


@pytest.mark.django_db
def test_a_damaged_file_of_counts_is_refused_before_anything_is_created(stage, archive):
    backup.beside(archive).write_text("{ not what a dump writes")
    said = refusal(archive)
    assert f"{archive}.json is damaged" in said and "Move that file away" in said and "without the comparison" in said
    backup.beside(archive).write_text(json.dumps({"counts": [1, 2]}))
    assert "is damaged" in refusal(archive)
    assert "server opened" not in stage.steps()


def test_the_new_database_is_migrated_by_a_process_configured_for_it(monkeypatch, settings, tmp_path):
    settings.BACKUP_DIR = str(tmp_path)
    ran = []

    def run(arguments, env=None, cwd=None, **options):
        ran.append((arguments, env["DB_NAME"], cwd))
        return subprocess.CompletedProcess(arguments, 1 if "broken" in env["DB_NAME"] else 0, stdout="  Applying chat.0003_message_sent_at...", stderr=(
            'Traceback (most recent call last):\n  File "/app/manage.py", line 22, in <module>\n'
            'psycopg.errors.UniqueViolation: duplicate key value violates unique constraint "chat_message_pkey"\n'
            'DETAIL:  Key (text)=(a-row-of-the-data) already exists.\n\nThe above exception was the direct cause of the following exception:\n\n'
            'django.db.utils.IntegrityError: duplicate key value violates unique constraint "chat_message_pkey"\n'
            'DETAIL:  Key (text)=(a-row-of-the-data) already exists.\n'))
    monkeypatch.setattr(restore.subprocess, "run", run)
    restore.Server.migrate(None, "golaiet_incoming_20310301T000000Z")
    (arguments, database, folder), = ran
    assert arguments[1:] == ["manage.py", "migrate", "--noinput"] and database == "golaiet_incoming_20310301T000000Z"
    assert folder == settings.BASE_DIR
    with pytest.raises(backup.DumpFailed) as failure:
        restore.Server.migrate(None, "broken")
    said = str(failure.value)
    assert said.startswith("migrate failed (exit 1): django.db.utils.IntegrityError. Its whole output is in ")
    assert "a-row-of-the-data" not in said and "a-row-of-the-data" in next(tmp_path.glob("failed-migrate-*.log")).read_text()

    def hang(arguments, timeout=None, **options):
        assert timeout == backup.TOOL_TIMEOUT_SEC
        raise subprocess.TimeoutExpired(arguments, timeout)
    monkeypatch.setattr(restore.subprocess, "run", hang)
    with pytest.raises(backup.DumpFailed, match="the migrations of the new database ran out of time"):
        restore.Server.migrate(None, "golaiet_incoming_20310301T000000Z")


# --- from an address: the HTTP is stood in for as the binaries and the server are

TOKEN = "a-token-of-the-tests-that-is-long-enough"
STATE = {"taken_at": "2031-03-01T22:10:00+02:00", "migrations": {"core": "0006_tracker_kind_life"},
         "counts": {"core_tracker": 2, "django_migrations": 30}, "is_copy": False, "scheduler_alive": False, "runs_running": 0}


@pytest.fixture
def other_side(monkeypatch, settings, tmp_path):
    """The machine at the address. `answer` is what it says; `asked` is what it was sent."""
    settings.DUMP_TOKEN, settings.BACKUP_DIR = TOKEN, str(tmp_path / "backups")
    answer = {"status": 200, "body": b"an archive", "state": dict(STATE), "length": None, "text": "", "type": "application/octet-stream"}
    asked = []

    @contextlib.contextmanager
    def stream(method, url, headers=None, timeout=None):
        asked.append({"method": method, "url": url, "headers": headers})

        class Answer:
            status_code = answer["status"]
            text = answer["text"]
            headers = {backup.STATE_HEADER: json.dumps(answer["state"]), "Content-Type": answer["type"],
                       "Content-Length": str(len(answer["body"]) if answer["length"] is None else answer["length"])}

            def read(self):
                return answer["text"].encode()

            def iter_bytes(self):
                yield answer["body"][:4]
                yield answer["body"][4:]
        yield Answer()
    monkeypatch.setattr(pull_db.httpx, "stream", stream)
    return answer, asked


@pytest.mark.django_db
def test_a_pull_from_an_address_fetches_the_dump_and_goes_on_as_from_a_file(stage, other_side, tmp_path):
    answer, asked = other_side
    said = pull("http://the-other-side:8003/")

    assert asked == [{"method": "GET", "url": "http://the-other-side:8003/api/dump", "headers": {"Authorization": f"Bearer {TOKEN}"}}]
    assert stage.steps() == ["pg_restore --list", "server opened", "server named_from", "server create", "pg_restore --no-owner", "server counts",
                             "server applied_migrations", "server comment", "server scheduler_alive", "server end_sessions",
                             "server swap", "server named_from", "server named_from", "server close"]
    listed = stage.calls[0]["arguments"][-1]
    assert listed.startswith(str(tmp_path / "backups" / "pulled-")) and listed.endswith(".dump"), "it had its name when it was whole"
    assert "http://the-other-side:8003 held" in said and "(2031-03-01T22:10:00+02:00)" in said, "the headers were the counts to compare with"
    mark = next(call["arguments"][3] for call in stage.calls if call["arguments"][:2] == ["server", "comment"])
    assert "http://the-other-side:8003" in mark and TOKEN not in mark and TOKEN not in said
    assert list((tmp_path / "backups").iterdir()) == [], "nothing fetched is left when the pull ended well"


@pytest.mark.django_db
def test_a_fetched_dump_is_kept_and_named_in_the_output_when_the_pull_fails(stage, other_side, tmp_path):
    stage.fail = "counts"
    errors = StringIO()
    with pytest.raises(RuntimeError):
        call_command("pull_db", "http://the-other-side:8003", stdout=StringIO(), stderr=errors)
    (kept,) = (tmp_path / "backups").glob("pulled-*.dump")
    assert f"The dump that was fetched is kept at {kept}" in errors.getvalue()
    assert kept.stat().st_mode & 0o777 == 0o600 and backup.read_beside(kept)["counts"] == STATE["counts"]


@pytest.mark.django_db
def test_a_dump_that_came_short_and_a_refusal_of_the_other_side_are_said_in_words(stage, other_side, tmp_path, settings):
    answer, asked = other_side
    answer["length"] = 4096
    assert "came short: 10 bytes of 4096" in refusal("http://the-other-side:8003")
    assert list((tmp_path / "backups").iterdir()) == [] and "server opened" not in stage.steps()

    answer.update(status=403, type="text/plain; charset=utf-8",
                  text="The token that came is not this side's DUMP_TOKEN: the two sides have to hold the same value.\n")
    said = refusal("http://the-other-side:8003")
    assert "did not hand over a dump: The token that came is not this side's DUMP_TOKEN" in said and "403" not in said

    answer.update(status=400, type="text/html", text="<!doctype html>\n<html><h1>Bad Request (400)</h1></html>")
    said = refusal("http://the-other-side:8003")
    assert "answered HTTP 400 with a page that is not the dump endpoint's" in said and "<" not in said
    assert "DJANGO_ALLOWED_HOSTS does not carry the name" in said and "not on this code (404)" in said and "(502)" in said

    settings.DUMP_TOKEN = ""
    assert "DUMP_TOKEN has to be set in this side's .env" in refusal("http://the-other-side:8003")
    assert len(asked) == 3, "without a token nothing is asked"


@pytest.mark.django_db
@pytest.mark.parametrize("stands,sentence", [
    ({"is_copy": True}, "is itself a copy"),
    ({"scheduler_alive": True}, "a scheduler holds the lock at http://the-other-side:8003"),
    ({"runs_running": 2}, "2 run(s) are recorded as running"),
])
def test_a_takeover_from_an_address_asks_the_source_and_a_copy_does_not(stage, other_side, stands, sentence):
    answer, _ = other_side
    answer["state"].update(stands)
    said = refusal("http://the-other-side:8003", takeover=True)
    assert sentence in said and "Nothing was replaced" in said and "server opened" not in stage.steps()
    assert "This is a COPY" in pull("http://the-other-side:8003"), "none of the three stops a copy"


@pytest.mark.django_db
def test_a_takeover_from_a_source_that_is_ready_says_what_the_source_said(stage, other_side):
    said = pull("http://the-other-side:8003", takeover=True)
    assert "The source said that it is not a copy" in said and "on your word" not in said
    assert "server comment" not in stage.steps()


@pytest.mark.django_db
@pytest.mark.parametrize("name", ['golaiet"; DROP DATABASE golaiet; --', "golaiet-live", "a" * 38])
def test_a_configured_name_that_is_not_plain_or_is_too_long_is_refused_before_anything_else(stage, archive, monkeypatch, name):
    monkeypatch.setitem(connection.settings_dict, "NAME", name)
    said = refusal(archive, takeover=True, replace=True)
    assert "cannot be pulled into" in said and "letters, digits and underscores only, and at most 37 characters" in said
    assert stage.steps() == [], "not even the file was read"


@pytest.mark.django_db
def test_a_drop_that_fails_adds_its_sentence_and_does_not_hide_the_first_error(stage, archive):
    stage.applied = stage.applied | {("core", "9999_from_a_later_code")}
    stage.fail = "drop"
    errors = StringIO()
    with pytest.raises(CommandError, match="the dump is newer than this code"):
        call_command("pull_db", str(archive), stdout=StringIO(), stderr=errors)
    created = next(call["arguments"][2] for call in stage.calls if call["arguments"][:2] == ["server", "create"])
    assert f'could not be dropped afterwards (RuntimeError). Drop it by hand: DROP DATABASE "{created}" WITH (FORCE);' in errors.getvalue()


@pytest.mark.django_db
def test_applied_rows_of_an_app_the_code_lacks_are_passed_over_and_said(stage, archive):
    stage.applied = stage.applied | {("django_apscheduler", "0001_initial")}
    said = pull(archive)
    assert "passed over because the app is not this code's or a squashed migration stands in for it: django_apscheduler 0001_initial." in said
    assert "server swap" in stage.steps() and "server migrate" not in stage.steps()


@pytest.mark.django_db
def test_two_pulls_in_one_second_do_not_meet_on_one_name(stage, archive):
    live = connection.settings_dict["NAME"]

    def this_second():
        # What a pull a moment ago left: the kept database of this very second (and of the one before, should the clock turn).
        now = pull_db.timezone.now()
        return [f"{live}_before_{moment:%Y%m%dT%H%M%SZ}" for moment in (now, now - pull_db.timezone.timedelta(seconds=1))]
    stage.taken = [this_second, lambda: []]
    assert "COPY" in pull(archive)
    assert stage.steps().count("server named_from") == 4 and stage.steps().count("server create") == 1
