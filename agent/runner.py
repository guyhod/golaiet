"""The headless Claude CLI as a subprocess: one prompt in, one result envelope out.

Invocation:
    claude --print --output-format json --model M [--system-prompt S] [--resume UUID]
           --mcp-config <per-run json> --strict-mcp-config
           "<prompt>" [--allowedTools a,b] [--tools c,d]

What was learned running the CLI headless in the sibling projects, kept here:
- `--bare` strips WebSearch/WebFetch (investment engine, 2026-07-04). Never used.
- `--safe-mode` disables every MCP server, including the one named on the
  command line (probed 2026-10-09: init reported mcp_servers=[]). Never used.
  Host customisations are kept out by CLAUDE_CONFIG_DIR instead (settings).
- `--strict-mcp-config` makes the per-run file the only MCP source.
- The positional prompt must precede --allowedTools and --tools: both are
  variadic and would swallow it.
- stdin is closed, or the CLI waits 3 s for piped input before starting.
- A session that ends in an error (quota wall, dropped connection, no
  credentials) exits non-zero but still prints an envelope with is_error and
  the message in `result`. It is returned, not raised, so a flow can tell a
  quota wall from a bad answer by reading the text.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import uuid
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from django.conf import settings

MCP_SERVER_NAME = "golaiet"

_UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")

# A quota failure hits every later call too, so a flow stops instead of
# retrying. Wordings seen live in the investment engine; an unknown wording
# once turned retries into a queue burner (2026-08-06), so keep this current.
BILLING_MARKERS = (
    "credit balance is too low",   # API-key billing
    "usage limit reached",         # plan auth, rolling window
    "monthly spend limit",         # plan auth, monthly cap
    "session limit",               # plan auth, session cap
)


def is_billing_abort(text: str) -> bool:
    lowered = (text or "").lower()
    return any(marker in lowered for marker in BILLING_MARKERS)


@dataclass(frozen=True)
class AgentResult:
    text: str
    session_id: str | None = None
    cost_usd: Decimal | None = None   # None means the envelope reported no cost, which is not the same as free
    exit_code: int = 0
    is_error: bool = False
    raw: str = ""

    @property
    def is_billing_abort(self) -> bool:
        return is_billing_abort(self.text)


def build_cmd(prompt: str, *, claude_bin: str, model: str, system_prompt: str | None = None,
              resume: str | None = None, mcp_config_path: str | None = None,
              allowed_tools: list[str] | None = None, tools: list[str] | None = None) -> list[str]:
    cmd = [claude_bin, "--print", "--output-format", "json", "--model", model]
    if system_prompt:
        cmd += ["--system-prompt", system_prompt]
    if resume and _UUID_RE.match(resume):
        cmd += ["--resume", resume]
    if mcp_config_path:
        cmd += ["--mcp-config", mcp_config_path, "--strict-mcp-config"]
    cmd.append(prompt)
    if allowed_tools:
        cmd += ["--allowedTools", ",".join(allowed_tools)]
    if tools is not None:
        cmd += ["--tools", ",".join(tools)]
    return cmd


def parse_envelope(stdout: str, exit_code: int = 0) -> AgentResult:
    """Parse `--output-format json`. Tolerates a non-JSON wrapper by taking the
    outermost object; with no object at all, the raw text is the result."""
    text = (stdout or "").strip()
    envelope = None
    try:
        envelope = json.loads(text)
    except ValueError:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            try:
                envelope = json.loads(text[start:end + 1])
            except ValueError:
                envelope = None
    if not isinstance(envelope, dict):
        return AgentResult(text=text, exit_code=exit_code, is_error=exit_code != 0, raw=text)
    cost = envelope.get("total_cost_usd")
    return AgentResult(
        text=str(envelope.get("result", "") or ""),
        session_id=envelope.get("session_id"),
        cost_usd=Decimal(str(cost)) if cost is not None else None,
        exit_code=exit_code,
        is_error=bool(envelope.get("is_error", False)) or exit_code != 0,
        raw=text,
    )


def write_mcp_config(env: dict[str, str]) -> Path:
    """One file per run: `env` is how the tool server learns which job run and
    message it serves (provenance on the rows it writes)."""
    settings.AGENT_RUNS_DIR.mkdir(parents=True, exist_ok=True)
    path = settings.AGENT_RUNS_DIR / f"mcp-{uuid.uuid4()}.json"
    manage_py = Path(settings.BASE_DIR) / "manage.py"
    path.write_text(json.dumps({"mcpServers": {MCP_SERVER_NAME: {
        "command": os.environ.get("GOLAIET_PYTHON") or _current_python(),
        "args": [str(manage_py), "mcp_tools"],
        "cwd": str(settings.BASE_DIR),
        "env": {key: str(value) for key, value in env.items()},
    }}}))
    return path


def _current_python() -> str:
    import sys
    return sys.executable


class ClaudeRunner:
    def __init__(self, claude_bin: str | None = None, model: str | None = None, timeout_sec: int | None = None):
        self.claude_bin = claude_bin or settings.CLAUDE_BIN
        self.model = model or settings.CLAUDE_MODEL
        self.timeout_sec = timeout_sec or settings.AGENT_TIMEOUT_SEC

    def run(self, prompt: str, *, system_prompt: str | None = None, allowed_tools: list[str] | None = None,
            tools: list[str] | None = None, resume: str | None = None, env: dict[str, str] | None = None) -> AgentResult:
        mcp_config_path = write_mcp_config(env or {})
        try:
            result = self._invoke(prompt, system_prompt, allowed_tools, tools, resume, mcp_config_path)
            # A stale session id (store rotated, volume wiped) degrades to a fresh session.
            if result.exit_code != 0 and resume and "No conversation found" in result.raw:
                result = self._invoke(prompt, system_prompt, allowed_tools, tools, None, mcp_config_path)
            return result
        finally:
            mcp_config_path.unlink(missing_ok=True)

    def _invoke(self, prompt, system_prompt, allowed_tools, tools, resume, mcp_config_path) -> AgentResult:
        cmd = build_cmd(prompt, claude_bin=self.claude_bin, model=self.model, system_prompt=system_prompt,
                        resume=resume, mcp_config_path=str(mcp_config_path), allowed_tools=allowed_tools, tools=tools)
        session_env = dict(os.environ, CLAUDE_CONFIG_DIR=settings.CLAUDE_CONFIG_DIR)
        if session_env.get("CLAUDE_CODE_OAUTH_TOKEN"):
            # Which credential the CLI prefers when both are set is version-dependent;
            # drop the API key so the plan token deterministically wins.
            session_env.pop("ANTHROPIC_API_KEY", None)
        Path(settings.CLAUDE_CONFIG_DIR).mkdir(parents=True, exist_ok=True)
        try:
            proc = subprocess.run(cmd, cwd=settings.AGENT_RUNS_DIR, env=session_env, stdin=subprocess.DEVNULL,
                                  capture_output=True, text=True, timeout=self.timeout_sec)
        except subprocess.TimeoutExpired as exc:
            tail = (exc.stdout or b"")[-500:] if isinstance(exc.stdout, bytes) else (exc.stdout or "")[-500:]
            return AgentResult(text=f"timeout after {self.timeout_sec}s", exit_code=-1, is_error=True, raw=str(tail))
        result = parse_envelope(proc.stdout, proc.returncode)
        if not result.text and proc.returncode != 0:
            return AgentResult(text=(proc.stderr or "").strip()[-500:] or f"exit {proc.returncode}",
                               exit_code=proc.returncode, is_error=True, raw=proc.stdout + proc.stderr)
        return result
