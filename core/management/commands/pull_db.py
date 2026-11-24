"""Replace this machine's database with what a dump holds:

    manage.py pull_db <file or address> [--takeover] [--replace]

The source is a dump file, or the address of another machine that runs this
code (`http://its-name:8003`): its dump is then fetched from /api/dump with
the token both sides hold in DUMP_TOKEN, read from the environment and
never from the arguments.

Run where the database is replaced, as a one-off container of the
scheduler's service, which mounts the backup folder and the agent's session
store. It is the restore of a nightly dump, the way a new host is raised
from nothing, and the way a copy of the live system is made.

The result is a copy unless --takeover is given: marked, so that no
scheduler starts on it and nothing is sent to Telegram from it. A copy holds
the live one's bot token and chat; unmarked, it would be a second live
system on the same bot.

The dump is never restored into the database this process is configured
for. It goes into a new database beside it and is checked there; then the
two names are swapped. A failure before the swap drops the new database and
leaves the rest as it was, and after the swap the database that was there
stays under a dated name, which is the way back. No code drops one of
those.

It prints counts, names and times, and never a row."""
import json
import re
import tempfile
import time
from pathlib import Path

import httpx
from django.apps import apps
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.db.migrations.loader import MigrationLoader
from django.utils import timezone

from core import backup, restore, standing
from core.management.commands.backup_db import RUN_IT_THERE

# What `migrate` itself fills in a database nobody has used yet. Rows anywhere else were written by a
# person, a job or a command, and are not replaced without --replace.
FILLED_BY_MIGRATE = {"django_migrations", "django_content_type", "auth_permission"}
# How long the swap goes on trying when a session comes back onto the database between ending the
# sessions and the rename (the dashboard's stream reconnects every second).
SWAP_PATIENCE_SEC = 5
# Postgres cuts a name at 63 bytes without a word, and a pull needs <name>_incoming_<stamp>.
LONGEST_NAME = 63 - len("_incoming_20310301T000000Z")
FETCHED = "pulled-"   # a dump fetched from an address, removed when the pull ended well


class Command(BaseCommand):
    help = "Replace this machine's database with a dump's contents: a marked copy by default, the live one with --takeover."

    def add_arguments(self, parser):
        parser.add_argument("source", help="A dump file (pg_dump's custom format), as backup_db and the nightly job write, "
                                           "or the address of another machine that runs this code, as http://name:port.")
        parser.add_argument("--takeover", action="store_true",
                            help="The result is the live database, not a copy: no mark, and a scheduler may start on it.")
        parser.add_argument("--replace", action="store_true",
                            help="Go on although this machine's database holds rows that somebody wrote.")

    def handle(self, *args, **options):
        try:
            backup.require_tools()
        except backup.ToolsMissing as missing:
            raise CommandError(f"{missing}: {RUN_IT_THERE.format(command='pull_db <source>')}")
        live = connection.settings_dict["NAME"]
        if not re.fullmatch(r"[A-Za-z0-9_]+", live) or len(live) > LONGEST_NAME:
            raise CommandError(
                f"The configured database name, {live!r}, cannot be pulled into: a pull makes databases named after it "
                f"and prints statements with those names, so it has to be letters, digits and underscores only, and at most "
                f"{LONGEST_NAME} characters. Nothing was replaced.")
        self.brake(live, options["replace"])

        source, pulled_at = options["source"], timezone.now()
        stamp = f"{pulled_at:%Y%m%dT%H%M%SZ}"
        from_address = source.startswith(("http://", "https://"))
        if from_address:
            source = source.rstrip("/")
            archive, state = self.fetch(source, stamp)
        else:
            archive, state = Path(source), None
        try:
            self.pull(options, source, archive, state, pulled_at, stamp, live)
        except BaseException:
            if from_address:
                self.stderr.write(f"The dump that was fetched is kept at {archive}.")
            raise
        if from_address:
            archive.unlink()
            backup.beside(archive).unlink(missing_ok=True)

    def pull(self, options, source: str, archive: Path, state: dict | None, pulled_at, stamp: str, live: str) -> None:
        self.refuse_an_unreadable_file(archive)
        try:
            beside = backup.read_beside(archive)
        except ValueError as damage:
            raise CommandError(
                f"{backup.beside(archive)} is damaged ({damage}), so the restore cannot be compared with what the dump "
                "counted. Nothing was replaced. Move that file away and the dump can be pulled without the comparison.")
        if options["takeover"] and state is not None:
            self.refuse_a_source_that_is_not_ready(source, state)

        server = restore.Server()
        try:
            incoming, kept = self.free_names(server, live)
            server.create(incoming)
            try:
                counts, migrated, passed_over = self.fill_and_check(server, incoming, archive, beside)
                if not options["takeover"]:
                    # Before the swap: there is never a moment when an unmarked copy answers to the live name.
                    server.comment(incoming, standing.mark_text(source, pulled_at.isoformat(timespec="minutes")))
                ended = self.swap(server, live, incoming, kept)
            except BaseException:
                try:
                    server.drop(incoming)
                except Exception as second:
                    # Said beside the first error, which is the one that is raised: this one must not hide it.
                    self.stderr.write(f"And the new database could not be dropped afterwards ({type(second).__name__}). "
                                      f"Drop it by hand: DROP DATABASE \"{incoming}\" WITH (FORCE);")
                raise
            earlier = [name for name in server.named_from(f"{live}_before_") if name != kept]
            left_half_done = server.named_from(f"{live}_incoming_")
        except backup.DumpFailed as failure:
            raise CommandError(f"Nothing was replaced: {failure}")
        finally:
            server.close()
        self.report(options["takeover"], state is not None, source, pulled_at, live, kept, earlier, left_half_done,
                    counts, beside, migrated, passed_over, ended)

    def free_names(self, server, live: str) -> tuple[str, str]:
        """The names of the new database and of the kept one, stamped to the second. Two pulls inside
        one second met on the same pair on 2026-11-24, in the end-to-end stack's check, and the second
        one's rename failed on a name that was there; so a pair that is taken waits for the next second."""
        while True:
            stamp = f"{timezone.now():%Y%m%dT%H%M%SZ}"
            incoming, kept = f"{live}_incoming_{stamp}", f"{live}_before_{stamp}"
            if not {incoming, kept} & set(server.named_from(f"{live}_")):
                return incoming, kept
            time.sleep(1)

    def fetch(self, address: str, stamp: str) -> tuple[Path, dict]:
        """The other side's dump into a file here, with what it said about itself. The file is owner-only
        and has its name only when it came whole; what the other side counted goes beside it."""
        if not settings.DUMP_TOKEN:
            raise CommandError("To pull from an address, DUMP_TOKEN has to be set in this side's .env, "
                               "to the value the other side has in its own.")
        folder = Path(settings.BACKUP_DIR or tempfile.gettempdir())
        folder.mkdir(mode=0o700, parents=True, exist_ok=True)
        whole = folder / f"{FETCHED}{stamp}.dump"
        partial = whole.with_name(whole.name + backup.PARTIAL)
        give_up_at = time.monotonic() + backup.TOOL_TIMEOUT_SEC
        try:
            with httpx.stream("GET", f"{address}/api/dump", headers={"Authorization": f"Bearer {settings.DUMP_TOKEN}"},
                              timeout=httpx.Timeout(30, connect=10)) as answer:
                if answer.status_code != 200:
                    answer.read()
                    if answer.headers.get("Content-Type", "").startswith("text/plain") and answer.text.strip():
                        raise CommandError(f"{address} did not hand over a dump: {answer.text.strip().splitlines()[0][:500]}")
                    raise CommandError(
                        f"{address} answered HTTP {answer.status_code} with a page that is not the dump endpoint's. Nothing "
                        "was replaced. Usually one of three: the source's DJANGO_ALLOWED_HOSTS does not carry the name that "
                        "was used here (400), the source is not on this code (404), or what stands in front of it is not "
                        "handing the request on (502).")
                state, expected = json.loads(answer.headers[backup.STATE_HEADER]), int(answer.headers["Content-Length"])
                backup.write_owners_alone(partial, "")
                with partial.open("wb") as file:
                    for piece in answer.iter_bytes():
                        if time.monotonic() > give_up_at:
                            raise CommandError(f"{address} took more than {backup.TOOL_TIMEOUT_SEC // 60} minutes to send "
                                               "its dump. Nothing was replaced.")
                        file.write(piece)
        except (httpx.HTTPError, KeyError, ValueError) as failure:
            partial.unlink(missing_ok=True)
            raise CommandError(f"No dump could be fetched from {address} ({type(failure).__name__}). Nothing was replaced. "
                               "Is its stack up, on this code, and is the address the one this container can reach?")
        except BaseException:
            partial.unlink(missing_ok=True)
            raise
        if partial.stat().st_size != expected:
            received = partial.stat().st_size
            partial.unlink()
            raise CommandError(f"The dump from {address} came short: {received} bytes of {expected}. Nothing was replaced.")
        partial.replace(whole)
        backup.write_owners_alone(backup.beside(whole), json.dumps(
            {"taken_at": state["taken_at"], "migrations": state["migrations"], "counts": state["counts"]}, indent=1))
        return whole, state

    def refuse_a_source_that_is_not_ready(self, address: str, state: dict) -> None:
        """A takeover from an address asks the source how it stands. Nothing here stops a copy."""
        if state["is_copy"]:
            raise CommandError(
                f"Nothing was replaced: the database at {address} is itself a copy, and a takeover is from the live one. "
                "Pull from the machine that is live, or, if that one is gone for good, pull this dump as a file with --takeover.")
        if state["scheduler_alive"]:
            raise CommandError(
                f"Nothing was replaced: a scheduler holds the lock at {address}, so it is still the live one. Remove it "
                "there first (`docker compose rm --stop --force scheduler`: a stopped one starts again with Docker), then pull again.")
        if state["runs_running"]:
            raise CommandError(
                f"Nothing was replaced: {state['runs_running']} run(s) are recorded as running at {address}. Wait for them "
                "to end. One that a killed scheduler left behind never will: set its status to failed in the admin there, then pull again.")

    def refuse_an_unreadable_file(self, archive: Path) -> None:
        mounted = settings.BACKUP_DIR or "the backup folder"
        if not archive.is_file():
            raise CommandError(
                f"There is no file at {archive}. Inside the scheduler's container a dump is seen only where a folder "
                f"is mounted: {mounted} is BACKUP_HOST_DIR of the machine (~/Backups/golaiet when unset). Put the dump there.")
        try:
            backup.run_tool(["pg_restore", "--list", str(archive)])
        except backup.DumpFailed as failure:
            raise CommandError(f"{archive} is not a dump that pg_restore reads ({failure}). Nothing was replaced.")

    def brake(self, live: str, replace: bool) -> None:
        if standing.scheduler_alive():
            raise CommandError(
                f"A scheduler holds the lock on {live}: it is alive on the database this would replace. Remove it first "
                "(`docker compose rm --stop --force scheduler`: one that is only stopped starts again with Docker), "
                "then run this as a one-off container: "
                "`docker compose run --rm scheduler python manage.py pull_db <file>`.")
        connection.ensure_connection()
        written = {table: rows for table, rows in backup.table_counts(connection.connection).items()
                   if rows and table not in FILLED_BY_MIGRATE}
        if written and not replace:
            found = ", ".join(f"{table} {rows}" for table, rows in written.items())
            raise CommandError(
                f"{live} holds rows that somebody wrote ({found}). To replace it all the same, give --replace: "
                "the database stays beside the new one under a dated name.")

    def fill_and_check(self, server, incoming: str, archive: Path, beside: dict | None) -> tuple[dict[str, int], list[str], list[str]]:
        """Restore into the new database and bring it to where it may take the live name. Returns its
        counts as restored, the migrations the code had to add, and the applied ones it passed over."""
        backup.run_tool(["pg_restore", "--no-owner", "--no-acl", "--exit-on-error", *backup.server_arguments(),
                         f"--dbname={incoming}", str(archive)])
        counts = server.counts(incoming)
        if beside is not None and counts != beside["counts"]:
            differing = sorted(table for table in counts.keys() | beside["counts"].keys()
                               if counts.get(table) != beside["counts"].get(table))
            raise CommandError(
                "Nothing was replaced: the restored database does not hold what the dump counted when it was taken. "
                + ", ".join(f"{table} {counts.get(table, 'missing')} (the dump: {beside['counts'].get(table, 'missing')})"
                            for table in differing))
        applied = server.applied_migrations(incoming)
        in_the_code = MigrationLoader(None).disk_migrations
        without_a_file = applied - set(in_the_code)
        # Two kinds of applied row have no file and are still not from a later code: one of an app this
        # code does not have at all, and one that a squashed migration in this code stands in for.
        replaced_by_a_squash = {key for migration in in_the_code.values() for key in migration.replaces}
        our_apps = {config.label for config in apps.get_app_configs()}
        passed_over = sorted(key for key in without_a_file if key in replaced_by_a_squash or key[0] not in our_apps)
        unknown = sorted(without_a_file - set(passed_over))
        if unknown:
            raise CommandError(
                "Nothing was replaced: the dump is newer than this code. It has applied "
                + ", ".join(f"{app} {name}" for app, name in unknown)
                + ", which this code does not have. Bring the code forward first, then pull again.")
        missing = sorted(set(in_the_code) - applied)
        if missing:
            # Here and not after the swap: a migration that fails leaves the live name as it was.
            server.migrate(incoming)
        return counts, [f"{app} {name}" for app, name in missing], [f"{app} {name}" for app, name in passed_over]

    def swap(self, server, live: str, incoming: str, kept: str) -> int:
        ended, give_up_at = 0, time.monotonic() + SWAP_PATIENCE_SEC
        while True:
            # Asked again here, in every round and just before the sessions are ended: a scheduler that
            # Docker started during the pull would have its sessions ended with the rest, connect again
            # by name, and find itself the scheduler of the new database.
            if server.scheduler_alive(live):
                raise CommandError(
                    f"Nothing was replaced: a scheduler started on {live} during the pull and holds its lock. "
                    "Remove it (`docker compose rm --stop --force scheduler`) and pull again.")
            ended += server.end_sessions(live)
            try:
                server.swap(live, incoming, kept)
                return ended
            except restore.InUse:
                if time.monotonic() >= give_up_at:
                    raise CommandError(
                        f"Nothing was replaced: for {SWAP_PATIENCE_SEC} seconds a session kept coming back onto {live}. "
                        "Stop what connects to it (`docker compose stop web`, and `docker compose rm --stop --force scheduler`) "
                        "and pull again.")
                time.sleep(0.2)

    def report(self, takeover, from_address, source, pulled_at, live, kept, earlier, left_half_done,
               counts, beside, migrated, passed_over, ended) -> None:
        say = self.stdout.write
        say(f"{live} now holds what {source} held. Pulled {pulled_at.isoformat(timespec='minutes')}.")
        if beside is None:
            say("There was no file of counts beside the dump, so there was nothing to compare the restore with.")
        else:
            say(f"The counts are the ones the dump wrote down when it was taken ({beside['taken_at']}).")
        for table, rows in counts.items():
            say(f"  {table} {rows}")
        if migrated:
            say("The dump was older than the code; applied before the swap: " + ", ".join(migrated) + ".")
        if passed_over:
            say("Applied in the dump and without a file in this code, passed over because the app is not this code's "
                "or a squashed migration stands in for it: " + ", ".join(passed_over) + ".")
        say(f"{ended} other session(s) on {live} were ended for the swap.")
        say(f"The database that was there is kept as {kept}. It is the way back; drop it when it is not: DROP DATABASE \"{kept}\";")
        for name in earlier:
            say(f"An earlier one is still there: DROP DATABASE \"{name}\";")
        for name in left_half_done:
            say(f"A pull that was killed left its new database behind: DROP DATABASE \"{name}\";")
        if not takeover:
            say("This is a COPY: it is marked, no scheduler starts on it and nothing is sent to Telegram from it.")
            say("Next: `make stack-without-scheduler` brings its stack up.")
            return
        if from_address:
            say("This is now the LIVE database: it is not marked. The source said that it is not a copy, that no "
                "scheduler holds its lock and that no run is running.")
        else:
            say("This is now the LIVE database: it is not marked. A file cannot say whether its source's scheduler "
                "is stopped, so that was taken on your word.")
        say("Next: `docker compose up -d` starts the stack, then `docker compose exec scheduler python manage.py seed_jobs`.")
        for line in self.session_store():
            say(line)

    def session_store(self) -> list[str]:
        """Whether the agent's session store that this process sees holds each conversation's session."""
        from chat.models import Conversation
        lines = []
        for conversation in Conversation.objects.exclude(session_id=""):
            found = any(Path(settings.CLAUDE_CONFIG_DIR, "projects").glob(f"*/{conversation.session_id}.jsonl"))
            lines.append(
                "The agent's session store here holds the conversation's session: the conversation goes on where it was."
                if found else
                "The agent's session store here does not hold the conversation's session: the next message opens a new "
                "session, which has the conventions and the tools and none of what was said. Carry the session's file "
                "over before the stack starts if that matters.")
        return lines
