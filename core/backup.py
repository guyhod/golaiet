"""One dump of the whole database, as a standard pg_dump archive: what the
nightly job keeps, what a deploy takes first, and what the other side of a
copy is handed. A standard archive restores with stock tools on a day this
code does not run.

The counts and the head of the migrations that come back with the file are
read in the dump's own snapshot, in one transaction that pg_dump is handed,
so a row written while the dump runs is in neither and a good restore never
looks short of what was counted. The tables are the ones the database's own
catalog names, not the code's models: a restore is counted before the code
has migrated it, when a model's table may not be there yet.

The file gets its name only when it is whole: pg_dump writes beside it, and
the name is given once pg_dump ended well and pg_restore reads the archive's
list. A dump that failed leaves nothing behind. Beside a whole archive goes
a small file, the archive's name with .json after it, that says when it was
taken, the head of the migrations and the counts, so that a restore months
later has something to prove itself against.

A dump holds every row, so both files are their owner's alone, and so is a
folder this code creates."""
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

import psycopg
from django.conf import settings
from django.db import connection
from django.utils import timezone
from psycopg import sql

log = logging.getLogger(__name__)

PARTIAL = ".partial"
BY_HAND = "backup-"    # backup_db's files: no code ever removes one
NIGHTLY = "nightly-"   # the nightly job's files: the job keeps thirty days of them
# Generous for a database whose dump takes seconds. Without a limit a pg_dump that hangs holds its
# snapshot open and one of the scheduler's threads for good.
TOOL_TIMEOUT_SEC = 600
# The response header in which the other side of a copy says, as JSON, what its dump holds and how
# that side stands: api/dump.py writes it and pull_db reads it.
STATE_HEADER = "X-Golaiet-Dump"


class DumpFailed(Exception):
    pass


class ToolsMissing(DumpFailed):
    """pg_dump or pg_restore is not on this machine. They are in the app image."""


@dataclass(frozen=True)
class Dump:
    path: Path
    size: int
    taken_at: str
    migrations: dict[str, str]   # app -> its last applied migration
    counts: dict[str, int]       # table -> rows


def require_tools() -> None:
    for tool in ("pg_dump", "pg_restore"):
        if shutil.which(tool) is None:
            raise ToolsMissing(f"{tool} is not on this machine")


def session(database: str | None = None) -> psycopg.Connection:
    """A connection of its own to a database of the configured server, the configured one by default.
    It gives up connecting after ten seconds, and TCP keepalives notice a peer that vanished in about
    a minute (30 s idle, then three probes 10 s apart): without them a statement on a dead socket waits
    for the operating system's own limit, which is hours, and whatever thread sent it waits with it."""
    configured = connection.settings_dict
    return psycopg.connect(dbname=database or configured["NAME"], user=configured["USER"], password=configured["PASSWORD"],
                           host=configured["HOST"], port=configured["PORT"], autocommit=True, connect_timeout=10,
                           keepalives=1, keepalives_idle=30, keepalives_interval=10, keepalives_count=3)


def server_arguments() -> list[str]:
    configured = connection.settings_dict
    return ["--no-password", f"--host={configured['HOST']}", f"--port={configured['PORT']}", f"--username={configured['USER']}"]


def table_counts(open_session: psycopg.Connection) -> dict[str, int]:
    """Rows of every ordinary table of the public schema, as the catalog names them."""
    tables = [name for (name,) in open_session.execute(
        "SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = 'public' AND c.relkind = 'r' ORDER BY c.relname").fetchall()]
    return {table: open_session.execute(sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(table))).fetchone()[0]
            for table in tables}


def migration_heads(open_session: psycopg.Connection) -> dict[str, str]:
    return dict(open_session.execute("SELECT app, max(name) FROM django_migrations GROUP BY app ORDER BY app").fetchall())


def beside(archive: Path) -> Path:
    return archive.with_name(archive.name + ".json")


def read_beside(archive: Path) -> dict | None:
    """What was written beside the archive when it was taken, or None: a dump taken by other means
    has none. Raises ValueError when the file is there and is not what dump() writes."""
    if not beside(archive).exists():
        return None
    written = json.loads(beside(archive).read_text())
    if not isinstance(written, dict) or not isinstance(written.get("counts"), dict) or "taken_at" not in written:
        raise ValueError("it does not hold the counts and the time a dump writes")
    return written


def dump(folder: Path, name: str) -> Dump:
    require_tools()
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    whole, partial = folder / name, folder / (name + PARTIAL)
    # A session of its own: the snapshot lives as long as its transaction, and Django's connection
    # is closed around every job.
    snapshot_session = session()
    try:
        snapshot_session.execute("BEGIN ISOLATION LEVEL REPEATABLE READ")
        snapshot = snapshot_session.execute("SELECT pg_export_snapshot()").fetchone()[0]
        taken_at = timezone.now().isoformat(timespec="seconds")
        counts = table_counts(snapshot_session)
        migrations = migration_heads(snapshot_session)
        try:
            write_owners_alone(partial, "")   # made before pg_dump fills it, so it is never readable by others
            run_tool(["pg_dump", "--format=custom", f"--snapshot={snapshot}", f"--file={partial}", *server_arguments(),
                      f"--dbname={connection.settings_dict['NAME']}"])
            run_tool(["pg_restore", "--list", str(partial)])
        except BaseException:
            partial.unlink(missing_ok=True)
            raise
        # Named while the session is still open: the archive is whole by now, and nothing that goes
        # wrong in leaving the session may leave a whole dump under a half file's name.
        partial.replace(whole)
    finally:
        try:
            snapshot_session.close()
        except Exception as failure:
            log.warning("the dump's own session did not close cleanly (%s)", type(failure).__name__)
    write_owners_alone(beside(whole), json.dumps({"taken_at": taken_at, "migrations": migrations, "counts": counts}, indent=1))
    return Dump(path=whole, size=whole.stat().st_size, taken_at=taken_at, migrations=migrations, counts=counts)


def write_owners_alone(path: Path, text: str) -> None:
    """The text into a file only its owner reads, whole or not at all: written beside the name and
    then moved onto it. A symbolic link under either name is refused, since writing through one
    would put a dump's contents wherever the link points."""
    writing = path.with_name(path.name + ".writing")
    for name in (path, writing):
        if name.is_symlink():
            raise DumpFailed(f"{name} is a symbolic link, and nothing is written through one")
    with os.fdopen(os.open(writing, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600), "w") as opened:
        opened.write(text)
    writing.chmod(0o600)   # a file that was already there keeps its old mode through os.open
    writing.replace(path)


def run_tool(arguments: list[str]) -> str:
    """One of the two binaries, to its end or to the time limit; returns what it printed. The password
    goes to the child in its environment: a process's arguments can be read by any other."""
    environment = dict(os.environ, PGPASSWORD=connection.settings_dict["PASSWORD"])
    try:
        done = subprocess.run(arguments, env=environment, stdin=subprocess.DEVNULL, capture_output=True, text=True,
                              timeout=TOOL_TIMEOUT_SEC)
    except subprocess.TimeoutExpired:   # subprocess.run has ended the child by now
        raise DumpFailed(f"{arguments[0]} ran out of time: it was ended after {TOOL_TIMEOUT_SEC // 60} minutes")
    if done.returncode != 0:
        raise failed(Path(arguments[0]).name, done.returncode, done.stdout + done.stderr)
    return done.stdout


def failed(tool: str, exit_code: int, output: str, says: str = "") -> DumpFailed:
    """The sentence for a child that ended badly, which is printed, logged and sent to the other
    side of a copy. Postgres quotes the failing value in its own lines: after ERROR: on the line
    that reports it, and in the DETAIL: and CONTEXT: lines that follow ("Key (slug)=(...) already
    exists", "COPY core_tracker, line 3, column id: ..."), which are the last lines of a failed
    restore. So nothing is left to the shape of the output: the sentence is built only from lines
    that begin with the tool's own name, and from those only the words before ERROR:. It takes the
    table those lines name and the last of them. `says` is what a caller that knows its child's
    output better puts in their place. The whole output goes into a file that only its owner reads,
    and the sentence says where."""
    own_lines = [line.split("ERROR:")[0].rstrip(" :") for line in output.splitlines() if line.startswith(f"{tool}:")]
    named = re.findall(r'TABLE DATA (?:public )?(\w+)|table "(\w+)"', "\n".join(own_lines))
    table = next((name for found in reversed(named) for name in found if name), None)
    folder = Path(settings.BACKUP_DIR or tempfile.gettempdir())
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    kept = folder / f"failed-{tool}-{timezone.now():%Y-%m-%dT%H%M%SZ}.log"
    write_owners_alone(kept, output)
    said = says or (own_lines[-1] if own_lines else "")
    return DumpFailed(f"{tool} failed (exit {exit_code})" + (f", at table {table}" if table else "")
                      + (f": {said}" if said else "") + f". Its whole output is in {kept}, which only its "
                      "owner reads: it can quote rows.")
