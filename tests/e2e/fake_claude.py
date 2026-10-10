#!/usr/bin/env python3
"""The Claude CLI as the end-to-end stack sees it: same command line, same
JSON envelope on stdout, and the same tool server started from the per-run
MCP config and spoken to over stdio. What differs is the brain: the reply is
scripted from the prompt's first words, so a run costs nothing and does the
same thing every time.

    Track <title> [hourly|daily|weekly]   create_tracker (topic kind)
    Show me <title>                       set_focus on that tracker
    Show everything                       set_focus with no tracker
    Mark <title> <level>                  record_assessment at that level

Any other prompt (a collect or assess session) does nothing and says so."""
import argparse
import json
import os
import re
import subprocess
import sys
import uuid

CADENCES = ("hourly", "daily", "weekly")


def slug_of(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")


def decide(prompt: str) -> tuple[str | None, dict, str]:
    """(tool, arguments, reply) for the prompt; tool None means answer only."""
    words = prompt.strip().split()
    head = " ".join(words[:2]).lower()
    if words and words[0].lower() == "track":
        cadence = words[-1].lower() if words[-1].lower() in CADENCES else "weekly"
        title = " ".join(words[1:-1] if cadence == words[-1].lower() else words[1:])
        return "create_tracker", {"slug": slug_of(title), "title": title, "kind": "topic",
                                  "subject": {"query": title}, "brief": f"Watch news about {title}.",
                                  "cadence": cadence}, f"Tracking {title} {cadence}."
    if head == "show everything":
        return "set_focus", {}, "Showing everything."
    if head == "show me":
        title = " ".join(words[2:])
        return "set_focus", {"slug": slug_of(title)}, f"{title} is on screen."
    if words and words[0].lower() == "mark":
        title, level = " ".join(words[1:-1]), words[-1].lower()
        return "record_assessment", {"slug": slug_of(title), "state": {"level": level},
                                     "reason": "Marked by the end-to-end test."}, f"{title} is now {level}."
    return None, {}, "Nothing to do."


def call_tool(mcp_config_path: str, name: str, arguments: dict) -> str:
    server_spec = json.load(open(mcp_config_path))["mcpServers"]["golaiet"]
    env = dict(os.environ, **server_spec.get("env", {}))
    server = subprocess.Popen([server_spec["command"], *server_spec["args"]], cwd=server_spec.get("cwd"), env=env,
                              stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=sys.stderr, text=True, bufsize=1)

    def send(message: dict):
        server.stdin.write(json.dumps(message) + "\n")
        server.stdin.flush()

    send({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
        "protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "fake-claude", "version": "0"}}})
    send({"jsonrpc": "2.0", "method": "notifications/initialized"})
    send({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": name, "arguments": arguments}})
    outcome = "the tool server closed the pipe without answering"
    for line in server.stdout:
        message = json.loads(line)
        if message.get("id") == 2:
            result = message.get("result") or {"isError": True, "content": [{"type": "text", "text": str(message.get("error"))}]}
            text = "".join(part.get("text", "") for part in result.get("content", []))
            outcome = f"The tool refused: {text}" if result.get("isError") else ""
            break
    server.stdin.close()
    server.wait(timeout=10)
    return outcome


def main() -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--print", action="store_true")
    parser.add_argument("--output-format")
    parser.add_argument("--model")
    parser.add_argument("--system-prompt")
    parser.add_argument("--resume")
    parser.add_argument("--mcp-config")
    parser.add_argument("--strict-mcp-config", action="store_true")
    parser.add_argument("--allowedTools")
    parser.add_argument("--tools")
    parser.add_argument("prompt")
    args = parser.parse_args()

    tool, arguments, reply = decide(args.prompt)
    if tool and args.mcp_config:
        refusal = call_tool(args.mcp_config, tool, arguments)
        if refusal:
            reply = refusal
    print(json.dumps({"result": reply, "session_id": args.resume or str(uuid.uuid4()),
                      "total_cost_usd": 0, "is_error": False}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
