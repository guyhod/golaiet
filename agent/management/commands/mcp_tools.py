"""The agent's tool server. The Claude CLI starts this as a child process (from
the per-run MCP config the runner writes) and talks JSON-RPC over the pipe:
tools/list once, tools/call per tool use. It lives exactly as long as the
session and never sends anything unasked.

stdout is the protocol channel: nothing here may print. Django's logging goes
to stderr, which the CLI collects."""
import os

from django.core.management.base import BaseCommand

from agent import tools


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
            server.add_tool(function)
        server.run(transport="stdio")
