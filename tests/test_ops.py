"""The two scripts that run outside the stack, against a health endpoint and a
`docker` that are stand-ins: what they log, and when the watcher speaks up."""
import datetime
import http.server
import json
import os
import subprocess
import threading
from pathlib import Path

import pytest

OPS = Path(__file__).resolve().parent.parent / "ops"


@pytest.fixture
def health():
    """A health endpoint whose answer the test sets; None closes the connection with an error."""
    answer = {"body": None}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            if answer["body"] is None:
                self.send_error(503)
                return
            body = json.dumps(answer["body"]).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield answer, f"http://127.0.0.1:{server.server_port}/api/health"
    server.shutdown()


def heartbeat(minutes_ago: int) -> dict:
    at = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=minutes_ago)
    return {"status": "ok", "last_heartbeat": at.strftime("%Y-%m-%dT%H:%M:%S.000Z")}


def test_the_watcher_logs_every_run_and_notifies_only_when_something_is_wrong(health, tmp_path):
    answer, url = health
    notifier = tmp_path / "notify.sh"
    notifier.write_text(f'#!/bin/sh\necho "$1" >> "{tmp_path}/notified"\n')
    notifier.chmod(0o755)

    def watch():
        subprocess.run([str(OPS / "watch.sh")], check=True, env={
            **os.environ, "HEALTH_URL": url, "LOG_DIR": str(tmp_path), "test_notify": str(notifier)})
        return (tmp_path / "watch.log").read_text().splitlines()[-1]

    answer["body"] = heartbeat(10)
    assert " ok age_minutes=" in watch()
    assert not (tmp_path / "notified").exists()
    answer["body"] = heartbeat(200)
    assert " stale age_minutes=" in watch()
    answer["body"] = {"status": "stale", "last_heartbeat": None}
    assert watch().endswith(" no-heartbeat")
    answer["body"] = None
    assert watch().endswith(" unreachable")
    spoken = (tmp_path / "notified").read_text().splitlines()
    assert len(spoken) == 3 and "minutes old" in spoken[0] and "does not answer" in spoken[2]


def test_the_backup_keeps_a_whole_dump_logs_it_and_clears_a_half_one(tmp_path):
    bin_dir, dumps = tmp_path / "bin", tmp_path / "dumps"
    bin_dir.mkdir()
    dumps.mkdir()
    (bin_dir / "docker").write_text("#!/bin/sh\nprintf 'a dump'\n")
    (bin_dir / "docker").chmod(0o755)
    (dumps / "golaiet-2031-03-01.dump.partial").write_text("half")
    subprocess.run([str(OPS / "backup.sh")], check=True, env={
        **os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "BACKUP_DIR": str(dumps), "LOG_DIR": str(tmp_path)})
    kept = sorted(path.name for path in dumps.iterdir())
    assert kept == [f"golaiet-{datetime.date.today().isoformat()}.dump"] and (dumps / kept[0]).read_text() == "a dump"
    assert " ok 6 bytes " in (tmp_path / "backup.log").read_text()
