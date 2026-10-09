"""The agent's tool server. The Claude CLI starts this as a child process (from
the per-run MCP config the runner writes) and talks JSON-RPC over the pipe:
tools/list once, tools/call per tool use. It lives exactly as long as the
session and never sends anything unasked.

stdout is the protocol channel: nothing here may print. Django's logging goes
to stderr, which the CLI collects."""
import functools
import os

from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.core.management.base import BaseCommand

from agent import tools


def as_tool(function):
    """The function with its refusals made readable. The MCP package reports
    any plain exception as "Error executing tool X" and keeps the message to
    itself; only its ToolError passes the text through. A collect session
    on 2026-10-09 tried record_observation twice, got that blank error
    twice, and filed nothing, so every refusal a tool makes on purpose (bad
    field, unknown slug, missing value) is re-raised as a ToolError here."""
    from mcp.server.mcpserver.exceptions import ToolError

    @functools.wraps(function)
    def guarded(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except (ValueError, ObjectDoesNotExist, ValidationError) as exc:
            raise ToolError(f"{function.__name__}: {exc}") from exc

    return guarded


class Command(BaseCommand):
    help = "Serve the agent tools over MCP stdio (started by the Claude CLI, not by hand)."

    def handle(self, *args, **options):
        # The MCP server runs the tool functions from its asyncio loop. They are
        # plain sync ORM calls, one at a time, in a process that serves one
        # session: the async-unsafe guard protects nothing here.
        os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
        from mcp.server.mcpserver import MCPServer

        server = MCPServer("golaiet", instructions="Golaiet's trackers and observations.")
        for function in tools.ALL:
            server.add_tool(as_tool(function))
        server.run(transport="stdio")
