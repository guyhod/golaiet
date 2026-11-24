import subprocess
from pathlib import Path

import pytest


@pytest.fixture
def tracker(db):
    from core.models import Tracker
    return Tracker.objects.create(slug="vram-supply", title="VRAM supply and pricing", kind="topic",
                                  subject={"query": "GDDR7 and HBM supply, pricing"}, brief="Watch vendor pricing and supply news.")


@pytest.fixture
def tools(monkeypatch, settings, tmp_path_factory):
    """pg_dump and pg_restore as stand-ins, as a flow test stands in for the CLI. Each call is kept
    with its arguments, its environment, its time limit and the files that were in its folder when it
    ran; a call whose command line contains one of the strings in `fail` ends badly, and what it
    printed is kept in settings.BACKUP_DIR, which is a folder of the test's own unless the test sets another."""
    from core import backup
    calls, fail = [], []
    settings.BACKUP_DIR = str(tmp_path_factory.mktemp("backups"))

    def run(arguments, env=None, timeout=None, **options):
        target = next((Path(argument.removeprefix("--file=")) for argument in arguments if argument.startswith("--file=")), None)
        if arguments[0] == "pg_dump":
            target.write_text("an archive")
        folder = (target or Path(arguments[-1])).parent
        calls.append({"arguments": arguments, "env": env, "timeout": timeout, "files": sorted(path.name for path in folder.iterdir())})
        failed = any(part in " ".join(arguments) for part in fail)
        # A failure ends as Postgres really ends one: its ERROR: on the tool's line, then DETAIL: and CONTEXT:
        # lines of its own, which quote the value and are the last lines printed.
        return subprocess.CompletedProcess(arguments, 1 if failed else 0, stdout="", stderr=(
            f'{arguments[0]}: from TOC entry 3401; 0 16412 TABLE DATA core_tracker golaiet\n'
            f'{arguments[0]}: error: COPY failed for table "core_tracker": ERROR:  invalid input syntax for type bigint: "a-row-of-the-data"\n'
            'DETAIL:  Key (slug)=(a-row-of-the-data) already exists.\n'
            'CONTEXT:  COPY core_tracker, line 3, column id: "a-row-of-the-data"\n') if failed else "")

    monkeypatch.setattr(backup.shutil, "which", lambda tool: f"/usr/bin/{tool}")
    monkeypatch.setattr(backup.subprocess, "run", run)
    return calls, fail
