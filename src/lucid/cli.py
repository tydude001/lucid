"""The `lucid` CLI.

Every MCP tool should also be reachable here, so the same operations can be
scripted or debugged without an agent in the loop.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from lucid import __version__
from lucid.project import Project, ProjectError


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="lucid",
        description="Local-first AI video editing: an MCP server over ffmpeg, whisper, and OTIO.",
    )
    parser.add_argument("--version", action="version", version=f"lucid {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("mcp", help="run the MCP server on stdio")

    p_init = sub.add_parser("init", help="create a project directory")
    p_init.add_argument(
        "path", nargs="?", default=".", help="where to create it (default: current directory)"
    )
    p_init.add_argument("--name", help="project name (default: the directory name)")

    p_info = sub.add_parser("info", help="show a project's manifest")
    p_info.add_argument("path", nargs="?", default=".", help="project directory (default: .)")

    sub.add_parser("ping", help="print the same payload the MCP ping tool returns")

    return parser


def _cmd_init(args: argparse.Namespace) -> int:
    project = Project.create(Path(args.path), name=args.name)
    print(f"created lucid project at {project.root}")
    return 0


def _cmd_info(args: argparse.Namespace) -> int:
    project = Project.open(Path(args.path))
    print(json.dumps(project.read_manifest(), indent=2, sort_keys=True))
    return 0


def _cmd_ping(_args: argparse.Namespace) -> int:
    from lucid.server import ping

    print(json.dumps(ping(), indent=2, sort_keys=True))
    return 0


def _cmd_mcp(_args: argparse.Namespace) -> int:
    from lucid.server import serve

    serve()
    return 0


_COMMANDS = {
    "init": _cmd_init,
    "info": _cmd_info,
    "ping": _cmd_ping,
    "mcp": _cmd_mcp,
}


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        return _COMMANDS[args.command](args)
    except ProjectError as exc:
        print(f"lucid: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
