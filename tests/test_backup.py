"""The database's dump with the two binaries stood in for, as a flow test
stands in for the CLI: the names a file goes through, what a failure leaves,
what the nightly job removes. The real pg_dump is run inside the end-to-end
stack (tests/e2e/stack_check.py), where the image has it."""
import json
import os
import re
import stat
import subprocess
import time
from io import StringIO
from pathlib import Path

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.utils.module_loading import import_string

from core import backup
from core.models import Tracker
from scheduler.models import Job
from scheduler.scripts import backup as nightly

REPO = Path(__file__).resolve().parent.parent
DAY = 24 * 3600


def test_the_image_has_the_client_tools_of_the_servers_major_version():
    server = re.search(r"image: postgres:(\d+)", (REPO / "docker-compose.yml").read_text())
    client = re.search(r"postgresql-client-(\d+)", (REPO / "Dockerfile").read_text())
    assert server and client and server.group(1) == client.group(1)


@pytest.mark.django_db(transaction=True)
def test_a_dump_is_written_beside_its_name_and_named_when_it_is_whole(tools, tmp_path):
    calls, _ = tools
    Tracker.objects.create(slug="vram-supply", title="VRAM supply", kind="topic", subject={"query": "GDDR7"})
    made = backup.dump(tmp_path / "dumps", "backup-one.dump")

    pg_dump, pg_restore = calls
    assert pg_dump["files"] == ["backup-one.dump.partial"], "pg_dump wrote beside the name"
    assert pg_restore["arguments"][:2] == ["pg_restore", "--list"] and pg_restore["files"] == ["backup-one.dump.partial"]
    assert sorted(path.name for path in (tmp_path / "dumps").iterdir()) == ["backup-one.dump", "backup-one.dump.json"]
    assert made.path == tmp_path / "dumps" / "backup-one.dump" and made.size == len("an archive")
    assert pg_dump["timeout"] == pg_restore["timeout"] == 600

    password = connection.settings_dict["PASSWORD"]
    assert pg_dump["env"]["PGPASSWORD"] == password and password not in pg_dump["arguments"]
    assert not any("password=" in argument.lower() for argument in pg_dump["arguments"])
    assert any(re.fullmatch(r"--snapshot=\S+", argument) for argument in pg_dump["arguments"])
    assert f"--dbname={connection.settings_dict['NAME']}" in pg_dump["arguments"]

    assert made.counts["core_tracker"] == 1 and made.counts["core_observation"] == 0
    assert {"core_assessment_evidence", "chat_conversation", "scheduler_job", "auth_user"} <= set(made.counts)
    assert made.counts["django_migrations"] > 0, "the tables are the catalog's, so the one no model has is counted too"
    assert {"core", "chat", "scheduler"} <= set(made.migrations) and made.migrations["scheduler"].startswith("000")

    written = json.loads((tmp_path / "dumps" / "backup-one.dump.json").read_text())
    assert written == {"taken_at": made.taken_at, "migrations": made.migrations, "counts": made.counts}
    assert backup.read_beside(made.path) == written and backup.read_beside(tmp_path / "another.dump") is None
    for kept in (made.path, backup.beside(made.path)):
        assert stat.S_IMODE(kept.stat().st_mode) == 0o600, "a dump holds every row: its owner's alone"
    assert stat.S_IMODE((tmp_path / "dumps").stat().st_mode) == 0o700


@pytest.mark.django_db
@pytest.mark.parametrize("failing", ["pg_dump", "pg_restore"])
def test_a_dump_that_failed_leaves_no_file_and_its_sentence_quotes_no_row(tools, tmp_path, failing, settings):
    _, fail = tools
    fail.append(failing)
    with pytest.raises(backup.DumpFailed) as failure:
        backup.dump(tmp_path, "backup-one.dump")
    assert list(tmp_path.iterdir()) == []
    said = str(failure.value)
    assert said.startswith(f'{failing} failed (exit 1), at table core_tracker: {failing}: error: COPY failed for table "core_tracker". Its whole output is in ')
    assert "a-row-of-the-data" not in said and "it can quote rows" in said
    (kept,) = Path(settings.BACKUP_DIR).iterdir()
    assert str(kept) in said and kept.name.startswith(f"failed-{failing}-") and stat.S_IMODE(kept.stat().st_mode) == 0o600
    assert "Key (slug)=(a-row-of-the-data) already exists" in kept.read_text(), "the whole output is there for its owner"


def test_no_line_that_is_not_the_tools_own_reaches_the_sentence(settings, tmp_path):
    settings.BACKUP_DIR = str(tmp_path)
    said = str(backup.failed("pg_restore", 1, 'a line of some other kind: table "a-row-of-the-data"\nCONTEXT:  COPY a-row-of-the-data, line 1\n'))
    assert said.startswith("pg_restore failed (exit 1). Its whole output is in ") and "a-row-of-the-data" not in said


def test_a_file_is_written_whole_or_not_at_all_and_never_through_a_symbolic_link(tmp_path):
    target = tmp_path / "counts.json"
    backup.write_owners_alone(target, "first")
    backup.write_owners_alone(target, "second")
    assert target.read_text() == "second" and [path.name for path in tmp_path.iterdir()] == ["counts.json"]

    elsewhere = tmp_path / "elsewhere"
    elsewhere.write_text("somebody else's")
    for name in ("linked.json", "linked.json.writing"):
        (tmp_path / name).symlink_to(elsewhere)
        with pytest.raises(backup.DumpFailed, match="is a symbolic link, and nothing is written through one"):
            backup.write_owners_alone(tmp_path / "linked.json", "a dump's counts")
        (tmp_path / name).unlink()
    assert elsewhere.read_text() == "somebody else's"


@pytest.mark.django_db
def test_a_tool_that_hangs_is_a_failed_dump_that_says_it_ran_out_of_time(monkeypatch, tmp_path):
    def hang(arguments, timeout=None, **options):
        raise subprocess.TimeoutExpired(arguments, timeout)
    monkeypatch.setattr(backup.shutil, "which", lambda tool: f"/usr/bin/{tool}")
    monkeypatch.setattr(backup.subprocess, "run", hang)
    with pytest.raises(backup.DumpFailed, match="pg_dump ran out of time: it was ended after 10 minutes"):
        backup.dump(tmp_path, "backup-one.dump")
    assert list(tmp_path.iterdir()) == []


@pytest.mark.django_db
def test_a_dump_is_whole_and_named_even_when_its_session_does_not_close_cleanly(tools, tmp_path, monkeypatch, caplog):
    real = backup.session

    class ClosesBadly:
        def __init__(self):
            self.inner = real()

        def execute(self, *arguments):
            return self.inner.execute(*arguments)

        def close(self):
            self.inner.close()
            raise RuntimeError("the connection was already lost")
    monkeypatch.setattr(backup, "session", ClosesBadly)
    made = backup.dump(tmp_path, "backup-one.dump")
    assert made.path.exists() and sorted(path.name for path in tmp_path.iterdir()) == ["backup-one.dump", "backup-one.dump.json"]
    assert "did not close cleanly" in caplog.text


def test_a_session_of_the_codes_own_gives_up_connecting_and_notices_a_peer_that_vanished(monkeypatch):
    asked = {}
    monkeypatch.setattr(backup.psycopg, "connect", lambda **options: asked.update(options))
    backup.session("another")
    assert asked["dbname"] == "another" and asked["connect_timeout"] == 10
    assert (asked["keepalives"], asked["keepalives_idle"], asked["keepalives_interval"], asked["keepalives_count"]) == (1, 30, 10, 3)


def aged(path: Path, days: int) -> Path:
    path.write_text("an earlier archive")
    then = time.time() - days * DAY
    os.utime(path, (then, then))
    return path


@pytest.mark.django_db
def test_the_nightly_job_removes_its_own_old_files_and_only_after_tonights_is_in_place(tools, tmp_path, settings):
    _, fail = tools
    settings.BACKUP_DIR = str(tmp_path)
    old = aged(tmp_path / "nightly-2031-01-01.dump", 31)
    old_counts = aged(tmp_path / "nightly-2031-01-01.dump.json", 31)
    recent = aged(tmp_path / "nightly-2031-01-20.dump", 29)
    recent_counts = aged(tmp_path / "nightly-2031-01-20.dump.json", 29)
    half_files = [aged(tmp_path / "nightly-2031-02-01.dump.partial", 2), aged(tmp_path / "backup-2031-02-01T101500Z.dump.partial", 2)]
    fresh_half = aged(tmp_path / "backup-2031-02-03T101500Z.dump.partial", 0)
    by_hand = aged(tmp_path / "backup-2031-01-01T101500Z.dump", 400)
    not_ours = aged(tmp_path / "golaiet-2031-01-01.dump", 400)

    fail.append("pg_dump")
    with pytest.raises(backup.DumpFailed):
        nightly.run(None, None)
    assert old.exists() and all(half.exists() for half in half_files), "a night without a dump removes nothing"

    fail.clear()
    summary = nightly.run(None, None)["summary"]
    tonight = next(path for path in tmp_path.glob("nightly-*.dump") if path not in (old, recent))
    assert not old.exists() and not old_counts.exists(), "an old dump goes with its file of counts"
    assert recent.exists() and recent_counts.exists() and by_hand.exists() and not_ours.exists()
    assert not any(half.exists() for half in half_files) and fresh_half.exists(), "a half file goes the night after, of either prefix"
    assert summary == f"{tonight.name} · {len('an archive')} bytes · 1 older than 30 days removed"


@pytest.mark.django_db
def test_the_nightly_job_fails_in_words_when_it_has_no_folder(settings):
    settings.BACKUP_DIR = ""
    with pytest.raises(RuntimeError, match="BACKUP_DIR is not set"):
        nightly.run(None, None)


@pytest.mark.django_db
def test_backup_db_prints_the_file_and_the_counts(tools, tmp_path):
    printed = StringIO()
    call_command("backup_db", folder=str(tmp_path), stdout=printed)
    (written,) = tmp_path.glob("*.dump")
    lines = printed.getvalue().splitlines()
    assert re.fullmatch(r"backup-\d{4}-\d\d-\d\dT\d{6}Z\.dump", written.name)
    assert lines[0] == f"{written}  {len('an archive')} bytes" and lines[1].startswith("migrations: ")
    assert "core_tracker 0" in lines and "chat_message 0" in lines


def test_backup_db_refuses_where_the_tools_are_missing_and_says_where_to_run_it(monkeypatch, tmp_path):
    monkeypatch.setattr(backup.shutil, "which", lambda tool: None)
    with pytest.raises(CommandError) as refusal:
        call_command("backup_db", folder=str(tmp_path))
    assert "pg_dump is not on this machine" in str(refusal.value)
    assert "docker compose exec scheduler python manage.py backup_db" in str(refusal.value)
    assert list(tmp_path.iterdir()) == []


def test_backup_db_refuses_without_a_folder(settings):
    settings.BACKUP_DIR = ""
    with pytest.raises(CommandError, match="give --folder, or set BACKUP_DIR"):
        call_command("backup_db", folder="")


@pytest.mark.django_db
def test_seed_jobs_makes_the_nightly_backup_switched_on():
    call_command("seed_jobs", stdout=StringIO())
    job = Job.objects.get(name="backup")
    assert (job.kind, job.trigger, job.schedule, job.enabled) == ("backup", "cron", "15 3 * * *", True)
    assert import_string(job.target) is nightly.run
