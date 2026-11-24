"""What only the built image and a running stack can show, run inside the
end-to-end stack's scheduler container (`python -m tests.e2e.stack_check`):
the real pg_dump and pg_restore are there and of a version the server takes,
a dump of this stack's database is whole and counts what the database holds,
the scheduler beside this process holds the lock, so a second one refuses,
and pull_db, on scratch databases of its own on this stack's Postgres and
never on the stack's database, restores, checks, marks and swaps for real,
from a file and from the stack's own address through its nginx.

This is the one place where a database is created, renamed or dropped and a
session ended by statement: the unit tests run on the Postgres of the
running stack and stand in for all of that."""
import os
import re
import subprocess
import sys
import tempfile
import time
from io import StringIO
from pathlib import Path

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from django.apps import apps  # noqa: E402
from django.conf import settings  # noqa: E402
from django.db import connection  # noqa: E402
from django.core.management import call_command  # noqa: E402
from django.core.management.base import CommandError  # noqa: E402

from core import backup, standing  # noqa: E402

SOURCE, TARGET = "golaiet_scratch_source", "golaiet_scratch"
MARK = "SELECT shobj_description(oid, 'pg_database') FROM pg_database WHERE datname = current_database()"
TRACKERS = "SELECT id, slug, title, kind, subject::text, created_at FROM core_tracker ORDER BY id"
MAKE_ROWS = """
from chat.models import Conversation
from core.models import Tracker
Tracker.objects.create(slug="vram-supply", title="VRAM supply and pricing", kind="topic", subject={"query": "GDDR7"})
Tracker.objects.create(slug="widget-prices", title="Widget prices", kind="topic", subject={"query": "widgets"})
Conversation.objects.create(chat_id="1", session_id="0f0e0d0c-0b0a-4908-8706-050403020100")
"""
OWN_MESSAGE = """
import datetime
from chat.models import Conversation, Message
Message.objects.create(conversation=Conversation.objects.first(), direction="in", text="written on the target",
                       sent_at=datetime.datetime(2031, 1, 1, 8, 0, tzinfo=datetime.timezone.utc))
"""
MESSAGES = "SELECT text, sent_at = created_at FROM chat_message ORDER BY id"
ADDRESS = "http://dashboard"   # the stack's own nginx, by its name on the compose network
ONE_MORE = 'from core.models import Tracker; print(Tracker.objects.create(slug="one-more", title="One more", kind="topic", subject={"query": "x"}).pk)'


def check_the_dump() -> None:
    folder = Path(tempfile.mkdtemp())
    printed = StringIO()
    call_command("backup_db", folder=str(folder), stdout=printed)
    (written,) = folder.glob("*.dump")
    listing = subprocess.run(["pg_restore", "--list", str(written)], capture_output=True, text=True, check=True).stdout
    lines = printed.getvalue().splitlines()
    counted = dict(line.rsplit(" ", 1) for line in lines[2:])
    models = {model._meta.db_table: model for model in apps.get_models(include_auto_created=True)}
    assert set(counted) == set(models) | {"django_migrations"}, "every table the database holds is counted"
    for table, model in models.items():
        assert f"TABLE DATA public {table} " in listing, f"the archive names no data for {table}"
        assert int(counted[table]) == model._base_manager.count(), f"{table}: the dump counted {counted[table]}"
    assert int(counted["django_content_type"]) > 0, "a migrated database has content types: the counts are not all zero"
    print(f"dump: {written.name}, {written.stat().st_size} bytes, {len(counted)} tables counted and listed")


def check_the_lock() -> None:
    assert standing.copy_mark() is None
    # `up --wait` waits for the container, not for the scheduler inside it to have taken the lock.
    give_up_at = time.monotonic() + 20
    while not standing.scheduler_alive() and time.monotonic() < give_up_at:
        time.sleep(0.5)
    assert standing.scheduler_alive(), "the stack's scheduler holds the lock"
    try:
        call_command("run_scheduler")
    except CommandError as refusal:
        assert "already alive on this database" in str(refusal)
    else:
        raise AssertionError("a second scheduler started beside the stack's own")
    print("lock: held by the stack's scheduler, and a second one is refused")


def manage(database: str, *arguments: str, refused: bool = False) -> str:
    """manage.py as a process of its own, configured for one of the scratch databases."""
    done = subprocess.run([sys.executable, "manage.py", *arguments], env={**os.environ, "DB_NAME": database},
                          capture_output=True, text=True)
    said = done.stdout + done.stderr
    assert (done.returncode != 0) == refused, f"manage.py {' '.join(arguments)} on {database} ended {done.returncode}: {said}"
    return said


def inside(database: str, query: str) -> list[tuple]:
    with backup.session(database) as session:
        return session.execute(query).fetchall()


def counts(database: str) -> dict[str, int]:
    with backup.session(database) as session:
        return backup.table_counts(session)


def databases(prefix: str) -> list[str]:
    return [name for (name,) in inside("postgres", f"SELECT datname FROM pg_database WHERE starts_with(datname, '{prefix}') ORDER BY datname")]


def dump_of(database: str, folder: str) -> Path:
    return Path(manage(database, "backup_db", "--folder", folder).split("  ")[0])


def check_the_pull() -> None:
    with backup.session("postgres") as server:
        for name in (SOURCE, TARGET):
            server.execute(f'CREATE DATABASE "{name}" TEMPLATE template0')
    manage(SOURCE, "migrate")
    manage(SOURCE, "shell", "-c", MAKE_ROWS)
    folder = tempfile.mkdtemp()

    # The round trip, into a database that was never migrated: no --replace is needed for that.
    first = dump_of(SOURCE, folder)
    said = manage(TARGET, "pull_db", str(first))
    assert "This is a COPY" in said and "make stack-without-scheduler" in said
    assert counts(TARGET) == backup.read_beside(first)["counts"] == counts(SOURCE)
    assert inside(TARGET, TRACKERS) == inside(SOURCE, TRACKERS) and len(inside(TARGET, TRACKERS)) == 2
    assert int(manage(TARGET, "shell", "-c", ONE_MORE).split()[-1]) == 3, "the next row gets the next id"
    assert (inside(TARGET, MARK)[0][0] or "").startswith(standing.MARK_WORD)
    assert "is a copy of" in manage(TARGET, "run_scheduler", refused=True)
    (emptied,) = databases(f"{TARGET}_before_")
    assert counts(emptied) == {}, "the database that was there, which held nothing, is kept under its dated name"
    print("pull: the round trip brings the same counts and rows, the next id continues, and the copy is marked and runs no scheduler")

    # A marked database's dump, pulled with --takeover: the mark does not travel, and what was replaced is kept with its rows.
    second = dump_of(TARGET, folder)
    assert "holds rows that somebody wrote" in manage(TARGET, "pull_db", str(second), "--takeover", refused=True)
    said = manage(TARGET, "pull_db", str(second), "--takeover", "--replace")
    assert "This is now the LIVE database" in said and "does not hold the conversation's session" in said
    assert inside(TARGET, MARK)[0][0] is None, "a marked database's dump came out unmarked"
    assert len(inside(TARGET, TRACKERS)) == 3
    replaced = databases(f"{TARGET}_before_")[-1]
    assert len(inside(replaced, TRACKERS)) == 3 and replaced != emptied
    assert f'DROP DATABASE "{emptied}";' in said, "an earlier one is listed with the statement that drops it"
    print("pull: the mark does not travel, a takeover is unmarked, and the replaced database is kept with its rows")

    # A dump whose migrations the code does not know is refused before the swap.
    before = counts(TARGET)
    inside_write(SOURCE, "INSERT INTO django_migrations (app, name, applied) VALUES ('core', '9999_from_a_later_code', now())")
    newer = dump_of(SOURCE, folder)
    inside_write(SOURCE, "DELETE FROM django_migrations WHERE name = '9999_from_a_later_code'")
    said = manage(TARGET, "pull_db", str(newer), "--replace", refused=True)
    assert "the dump is newer than this code" in said and "Bring the code forward first" in said
    assert counts(TARGET) == before and databases(f"{TARGET}_incoming_") == [] and databases(f"{TARGET}_before_")[-1] == replaced
    print("pull: a dump newer than the code is refused, the live name holds what it held and no new database is left")

    # A dump from before a migration that writes rows (chat 0003 gives every message its stored time as
    # its sent time), over a target whose own message has a sent time of its own. The migration has to
    # run on the new database and leave the one being replaced, which is the way back, as it was.
    manage(SOURCE, "migrate", "chat", "0002")
    inside_write(SOURCE, "INSERT INTO chat_message (direction, text, created_at, conversation_id) "
                         "VALUES ('in', 'from before the field', '2031-01-05 10:00+00', (SELECT min(id) FROM chat_conversation))")
    older = dump_of(SOURCE, folder)
    manage(SOURCE, "migrate")
    manage(TARGET, "shell", "-c", OWN_MESSAGE)
    assert inside(TARGET, MESSAGES) == [("written on the target", False)]
    said = manage(TARGET, "pull_db", str(older), "--replace")
    assert "applied before the swap: chat 0003_message_sent_at, chat 0004_conversation_conventions." in said and "This is a COPY" in said
    assert inside(TARGET, MESSAGES) == [("from before the field", True)], "the migration wrote in the new database"
    assert inside(databases(f"{TARGET}_before_")[-1], MESSAGES) == [("written on the target", False)], "and not in the one replaced"
    print("pull: a dump older than the code is migrated before the swap, rows included, and the replaced database is untouched")

    # What a dump taken with the stock tool alone looks like: nothing beside it. And a session that is
    # open on the target when the swap comes is ended and counted.
    plain = Path(folder, "golaiet-2031-03-01.dump")
    subprocess.run(["pg_dump", "--format=custom", f"--file={plain}", *backup.server_arguments(), f"--dbname={SOURCE}"],
                   env={**os.environ, "PGPASSWORD": connection.settings_dict["PASSWORD"]}, check=True)
    open_on_the_target = backup.session(TARGET)
    try:
        said = manage(TARGET, "pull_db", str(plain), "--replace")
    finally:
        open_on_the_target.close()
    assert "nothing to compare the restore with" in said and "1 other session(s)" in said
    assert counts(TARGET) == counts(SOURCE)
    print("pull: a plain pg_dump file with nothing beside it is pulled, and a session open on the target is ended")


def check_the_pull_from_an_address() -> None:
    stack = connection.settings_dict["NAME"]
    said = manage(TARGET, "pull_db", ADDRESS, "--replace")
    assert f"{ADDRESS} held" in said and "This is a COPY" in said and "the ones the dump wrote down" in said
    assert counts(TARGET) == counts(stack) and (inside(TARGET, MARK)[0][0] or "").startswith(standing.MARK_WORD)
    assert ADDRESS in inside(TARGET, MARK)[0][0]
    said = manage(TARGET, "pull_db", ADDRESS, "--takeover", "--replace", refused=True)
    assert f"a scheduler holds the lock at {ADDRESS}" in said and "The dump that was fetched is kept at" in said
    assert counts(TARGET) == counts(stack) and databases(f"{TARGET}_incoming_") == []
    for fetched in Path(settings.BACKUP_DIR).glob("pulled-*"):
        fetched.unlink()
    print("pull: through nginx, from the stack's own address, the copy holds the stack's counts, and a takeover is refused while its scheduler lives")


def check_a_failed_restore() -> None:
    """A restore that really fails on a row: a word into a column of numbers. Postgres quotes the word
    in its own lines; the sentence must not hold it, and the file its owner reads must."""
    word = "a-word-where-a-number-goes"
    words, numbers = "golaiet_scratch_words", "golaiet_scratch_numbers"
    with backup.session("postgres") as server:
        for name in (words, numbers):
            server.execute(f'CREATE DATABASE "{name}" TEMPLATE template0')
    inside_write(words, "CREATE TABLE trial (amount text)")
    inside_write(words, f"INSERT INTO trial VALUES ('{word}')")
    inside_write(numbers, "CREATE TABLE trial (amount integer)")
    archive = Path(tempfile.mkdtemp(), "words.dump")
    subprocess.run(["pg_dump", "--format=custom", "--data-only", f"--file={archive}", *backup.server_arguments(), f"--dbname={words}"],
                   env={**os.environ, "PGPASSWORD": connection.settings_dict["PASSWORD"]}, check=True)
    try:
        backup.run_tool(["pg_restore", "--data-only", "--exit-on-error", *backup.server_arguments(), f"--dbname={numbers}", str(archive)])
    except backup.DumpFailed as failure:
        said = str(failure)
    else:
        raise AssertionError("a word went into a column of numbers")
    kept = Path(re.search(r"Its whole output is in (\S+), which", said).group(1))
    assert word not in said and "at table trial" in said, said
    assert word in kept.read_text() and kept.stat().st_mode & 0o777 == 0o600
    kept.unlink()
    print(f"failed restore: the sentence holds no word of the row, and the file does. It said: {said}")


def inside_write(database: str, statement: str) -> None:
    with backup.session(database) as session:
        session.execute(statement)


if __name__ == "__main__":
    print(subprocess.run(["pg_dump", "--version"], capture_output=True, text=True, check=True).stdout.strip())
    check_the_dump()
    check_the_lock()
    check_the_pull()
    check_the_pull_from_an_address()
    check_a_failed_restore()
