#!/usr/bin/env python3
"""The Claude CLI as the end-to-end stack sees it: same command line, same
JSON envelope on stdout, and the same tool server started from the per-run
MCP config and spoken to over stdio. What differs is the brain: the reply is
scripted from the prompt's first words, so a run costs nothing and does the
same thing every time.

    Track <TICKER>, good below <price>    create_tracker (stock kind)
    Track <title> [hourly|daily|weekly]   create_tracker (topic kind)
    Show me <title>                       set_focus on that tracker
    Show everything                       set_focus with no tracker
    Mark <title> <level>                  record_assessment at that level
    Practice <title>                      create_tracker (practice kind, a gap)
    Did <title>                           record_observation on the day the message was sent
    Lane <title>: <station>               create_tracker (campaign kind), the fact, then the lane's first state

Any other prompt (a collect or assess session) does nothing and says so. A
script is a list of tool calls; a later call may use the id the one before
it returned."""
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


PREVIOUS_ID = "<the id the previous call returned>"


def decide(prompt: str) -> tuple[str | None, dict, str] | tuple[list, str]:
    """(tool, arguments, reply) for the prompt; tool None means answer only.
    A script of several calls is ([(tool, arguments), ...], reply)."""
    sent_day = ""
    if prompt.startswith("[Sent "):
        # The reply flow's first line says when the message was sent; the script is the rest.
        sent_day = prompt.split()[2]
        prompt = prompt.partition("\n")[2]
    words = prompt.strip().split()
    head = " ".join(words[:2]).lower()
    if words and words[0].lower() == "practice":
        title = " ".join(words[1:])
        return "create_tracker", {"slug": slug_of(title), "title": title, "kind": "practice",
                                  "subject": {"color": "red", "started": sent_day},
                                  "brief": "Any time it happens counts."}, f"{title} is a practice."
    if words and words[0].lower() == "did":
        title = " ".join(words[1:])
        return "record_observation", {"slug": slug_of(title), "observed_at": sent_day, "source_url": "",
                                      "summary": prompt.strip()}, f"Recorded {title}."
    if words and words[0].lower() == "lane":
        title, _, station = " ".join(words[1:]).partition(": ")
        slug = slug_of(title)
        return [("create_tracker", {"slug": slug, "title": title, "kind": "campaign", "subject": {}, "brief": f"The {title} lane."}),
                ("record_observation", {"slug": slug, "observed_at": sent_day, "source_url": "", "summary": prompt.strip()}),
                ("record_assessment", {"slug": slug, "reason": "Guy named the first station.", "evidence_ids": [PREVIOUS_ID],
                                       "state": {"stations": [{"id": slug_of(station), "label": station, "track": "", "state": "current"}]}})], \
            f"{title} is a lane."
    if words and words[0].lower() == "track" and "good below" in prompt.lower():
        ticker, line = words[1].strip(",").upper(), float(words[-1])
        return "create_tracker", {"slug": ticker.lower(), "title": ticker, "kind": "stock",
                                  "subject": {"ticker": ticker, "good_below": line},
                                  "brief": "Buy only at a discount to the line.", "cadence": "daily"}, \
            f"Tracking {ticker}, good below {line:g}."
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


def call_tool(mcp_config_path: str, name: str, arguments: dict) -> tuple[str, str]:
    """(refusal, result): the refusal is empty when the tool answered."""
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
    outcome, answered = "the tool server closed the pipe without answering", ""
    for line in server.stdout:
        message = json.loads(line)
        if message.get("id") == 2:
            result = message.get("result") or {"isError": True, "content": [{"type": "text", "text": str(message.get("error"))}]}
            text = "".join(part.get("text", "") for part in result.get("content", []))
            outcome, answered = (f"The tool refused: {text}", "") if result.get("isError") else ("", text)
            break
    server.stdin.close()
    server.wait(timeout=10)
    return outcome, answered


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

    decided = decide(args.prompt)
    calls, reply = decided if len(decided) == 2 else ([decided[:2]] if decided[0] else [], decided[2])
    previous_id = None
    for tool, arguments in calls if args.mcp_config else []:
        arguments = json.loads(json.dumps(arguments).replace(json.dumps(PREVIOUS_ID), json.dumps(previous_id)))
        refusal, answered = call_tool(args.mcp_config, tool, arguments)
        if refusal:
            reply = refusal
            break
        try:
            previous_id = json.loads(answered).get("id")
        except (ValueError, AttributeError):
            previous_id = None
    print(json.dumps({"result": reply, "session_id": args.resume or str(uuid.uuid4()),
                      "total_cost_usd": 0, "is_error": False}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
