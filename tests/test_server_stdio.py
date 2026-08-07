"""End-to-end check against the real server process.

This spawns `lucid mcp` as a subprocess and speaks MCP over its stdio, rather
than calling the tool function directly — the wiring between the CLI, the
transport, and the tool registry is exactly what a unit test would miss.
"""

from __future__ import annotations

import json
import sys
from typing import Any

import anyio
from mcp import ClientSession, StdioServerParameters, stdio_client

SERVER = StdioServerParameters(command=sys.executable, args=["-m", "lucid.cli", "mcp"])


async def _talk_to_server() -> tuple[Any, Any]:
    async with stdio_client(SERVER) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            result = await session.call_tool("ping", {})
            return tools, result


def test_server_serves_ping_over_stdio() -> None:
    tools, result = anyio.run(_talk_to_server)

    assert [tool.name for tool in tools.tools] == ["ping"]

    payload = json.loads(result.content[0].text)
    assert payload["status"] == "ok"
    assert payload["server"] == "lucid"
