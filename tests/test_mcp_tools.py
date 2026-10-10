"""The tool server as the CLI sees it: a real child process on stdio."""
import json
import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest

MANAGE = Path(__file__).resolve().parent.parent / "manage.py"


def call_through_server(method: str, params: dict, timeout: float = 20) -> dict:
    """The child process gets the database pytest-django is using by name, so
    a call sees the same (test) tables the test does. Without this it opened
    the dev database by its configured name, which on a fresh CI runner has
    no tables, and the refusal came back masked (2026-10-10)."""
    from django.db import connection
    env = dict(os.environ, GOLAIET_JOB_RUN_ID="", DB_NAME=connection.settings_dict["NAME"])
    server = subprocess.Popen([sys.executable, str(MANAGE), "mcp_tools"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, text=True, env=env, bufsize=1)

    def send(message):
        server.stdin.write(json.dumps(message) + "\n")
        server.stdin.flush()

    send({"jsonrpc": "2.0", "id": 1, "method": "initialize",
          "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "test", "version": "0"}}})
    send({"jsonrpc": "2.0", "method": "notifications/initialized"})
    send({"jsonrpc": "2.0", "id": 2, "method": method, "params": params})
    answer = {}

    def read():
        for line in server.stdout:
            message = json.loads(line)
            if message.get("id") == 2:
                answer.update(message)
                return

    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    reader.join(timeout)
    server.stdin.close()
    server.kill()
    assert answer, f"no answer from the tool server; stderr: {server.stderr.read()[-800:]}"
    return answer["result"]


def test_tools_list_keeps_names_docs_and_schemas():
    listed = {tool["name"]: tool for tool in call_through_server("tools/list", {})["tools"]}
    assert set(listed) == {"list_trackers", "get_tracker", "create_tracker", "update_tracker", "record_observation",
                           "search_observations", "record_assessment", "raise_alert", "set_focus"}
    assert "required" not in listed["set_focus"]["inputSchema"]
    assert listed["record_observation"]["inputSchema"]["required"] == ["slug", "observed_at", "source_url", "summary"]
    assert "ISO date" in listed["record_observation"]["description"]


@pytest.mark.django_db(transaction=True)
def test_refusals_reach_the_model_as_text():
    """The child process has its own connection, so this needs a committed
    transaction (transaction=True) and a tracker that is not there."""
    result = call_through_server("tools/call", {"name": "record_observation", "arguments": {
        "slug": "no-such-tracker", "observed_at": "2026-10-01", "source_url": "https://x.example/1", "summary": "s"}})
    assert result["isError"] is True
    assert "record_observation: Tracker matching query does not exist" in result["content"][0]["text"]
