"""The `lucid mcp` server — MCP tools over stdio.

Milestone 1 exposes only `ping`, to prove the wiring end to end. The editing
tools land in later milestones; see PLAN.md for the intended surface.
"""

from __future__ import annotations

from mcp.server import MCPServer

from lucid import __version__

mcp: MCPServer = MCPServer(
    name="lucid",
    version=__version__,
    instructions=(
        "lucid edits video locally: import media, transcribe it, cut by "
        "transcript, and render. All state lives in a project directory on "
        "disk; nothing is uploaded."
    ),
)


@mcp.tool()
def ping() -> dict[str, str]:
    """Check that the lucid MCP server is alive, and report its version."""
    return {"status": "ok", "server": "lucid", "version": __version__}


def serve() -> None:
    """Run the server on stdio. Blocks until the client disconnects."""
    mcp.run(transport="stdio")
