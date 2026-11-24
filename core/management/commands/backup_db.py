"""One dump of the database now, into a folder: `manage.py backup_db`.

The dump the nightly job takes, taken by hand or by a deploy. Its file is
named for the minute, under a prefix no code ever removes. It prints the
file, its size, the head of the migrations and the row count of every
table, and never a row."""
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from core import backup

# Where the two binaries are, said the same way by every command that needs them.
RUN_IT_THERE = ("Postgres' client tools are in the app image and not here. Run it there: "
                "`docker compose exec scheduler python manage.py {command}` "
                "(`docker compose run --rm scheduler python manage.py {command}` while the scheduler is stopped).")


class Command(BaseCommand):
    help = "Dump the whole database into a folder (pg_dump's custom format) and print its counts."

    def add_arguments(self, parser):
        parser.add_argument("--folder", default=settings.BACKUP_DIR,
                            help="Where the file goes. Default: BACKUP_DIR, which in the stack is the mounted backup folder.")

    def handle(self, *args, **options):
        if not options["folder"]:
            raise CommandError("No folder to write to: give --folder, or set BACKUP_DIR.")
        name = f"{backup.BY_HAND}{timezone.now():%Y-%m-%dT%H%M%SZ}.dump"
        try:
            made = backup.dump(Path(options["folder"]), name)
        except backup.ToolsMissing as missing:
            raise CommandError(f"{missing}: {RUN_IT_THERE.format(command='backup_db')}")
        except backup.DumpFailed as failure:
            raise CommandError(f"No dump was written: {failure}")
        self.stdout.write(f"{made.path}  {made.size} bytes")
        self.stdout.write("migrations: " + ", ".join(f"{app} {last}" for app, last in made.migrations.items()))
        for table, rows in made.counts.items():
            self.stdout.write(f"{table} {rows}")
