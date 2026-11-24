"""The statements that act on whole databases, for pull_db: create one, drop
one, end the sessions on one, swap two names. They are in one class so that
they are sent from one place, on a session to the maintenance database, and
so that the unit tests stand in for the whole of it: those tests run on the
Postgres of the running stack, in a database beside the live one, and none
of these statements may ever be sent there. They run for real inside the
end-to-end stack, on its own Postgres."""
import os
import re
import subprocess
import sys

import psycopg
from django.conf import settings
from django.db import connections
from psycopg import sql

from core import backup, standing

MAINTENANCE_DATABASE = "postgres"


class InUse(Exception):
    """A session is connected to a database that was to be renamed."""


class Server:
    def __init__(self):
        # The command's own connection would otherwise be one of the sessions on the database it replaces.
        connections.close_all()
        self.maintenance = backup.session(MAINTENANCE_DATABASE)

    def close(self) -> None:
        self.maintenance.close()

    def create(self, name: str) -> None:
        self.maintenance.execute(sql.SQL("CREATE DATABASE {} TEMPLATE template0").format(sql.Identifier(name)))

    def drop(self, name: str) -> None:
        # With force: after a pg_restore that the time limit ended, its session on the server can still
        # be there, and a plain drop would wait on it and fail. The database is the pull's own.
        self.maintenance.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name)))

    def counts(self, name: str) -> dict[str, int]:
        with backup.session(name) as inside:
            return backup.table_counts(inside)

    def applied_migrations(self, name: str) -> set[tuple[str, str]]:
        with backup.session(name) as inside:
            return set(inside.execute("SELECT app, name FROM django_migrations").fetchall())

    def migrate(self, name: str) -> None:
        """In a process of its own whose configured database is the new one. Not through a second
        alias in this process: a data migration writes through the default manager, as most do, and
        under an alias it would write to the database that is being replaced, which is the way back,
        and leave the new one's rows as they were."""
        try:
            done = subprocess.run([sys.executable, "manage.py", "migrate", "--noinput"], cwd=settings.BASE_DIR,
                                  env={**os.environ, "DB_NAME": name}, stdin=subprocess.DEVNULL, capture_output=True, text=True,
                                  timeout=backup.TOOL_TIMEOUT_SEC)
        except subprocess.TimeoutExpired:
            raise backup.DumpFailed("the migrations of the new database ran out of time: they were ended after "
                                    f"{backup.TOOL_TIMEOUT_SEC // 60} minutes")
        if done.returncode != 0:
            # A failed migration ends as a failed restore does, with Postgres' own lines last, and they
            # quote the row. Of a traceback only the class of the exception is safe to say.
            output = done.stdout + done.stderr
            classes = re.findall(r"^((?:\w+\.)*\w*(?:Error|Exception))\b", output, flags=re.MULTILINE)
            raise backup.failed("migrate", done.returncode, output, says=classes[-1] if classes else "no exception was named")

    def scheduler_alive(self, name: str) -> bool:
        """Whether a session holds the scheduler's lock on the named database, read from this session."""
        return self.maintenance.execute(
            "SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND granted AND classid = %s AND objid = %s "
            "AND objsubid = 2 AND database = (SELECT oid FROM pg_database WHERE datname = %s)",
            [*standing.LOCK_KEY, name]).fetchone()[0] > 0

    def comment(self, name: str, text: str) -> None:
        self.maintenance.execute(sql.SQL("COMMENT ON DATABASE {} IS {}").format(sql.Identifier(name), sql.Literal(text)))

    def end_sessions(self, name: str) -> int:
        return self.maintenance.execute(
            "SELECT count(pg_terminate_backend(pid)) FROM pg_stat_activity WHERE datname = %s AND pid <> pg_backend_pid()",
            [name]).fetchone()[0]

    def swap(self, live: str, incoming: str, kept: str) -> None:
        """`live` becomes `kept` and `incoming` becomes `live`, both or neither."""
        try:
            with self.maintenance.transaction():
                self.maintenance.execute(sql.SQL("ALTER DATABASE {} RENAME TO {}").format(sql.Identifier(live), sql.Identifier(kept)))
                self.maintenance.execute(sql.SQL("ALTER DATABASE {} RENAME TO {}").format(sql.Identifier(incoming), sql.Identifier(live)))
        except psycopg.errors.ObjectInUse as busy:
            raise InUse(str(busy).strip().splitlines()[0])

    def named_from(self, prefix: str) -> list[str]:
        return [name for (name,) in self.maintenance.execute(
            "SELECT datname FROM pg_database WHERE starts_with(datname, %s) ORDER BY datname", [prefix]).fetchall()]
