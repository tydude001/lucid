"""The `lucid` CLI.

Every MCP tool is also reachable here, so the same operations can be scripted
or debugged without an agent in the loop. Both front ends call `lucid.ops`;
neither holds logic of its own.
"""

from __future__ import annotations

import argparse
import json
import sys

from lucid import __version__, asr, captions, ops
from lucid.asr import ASRError
from lucid.autoeditor import AutoEditorError
from lucid.media import MediaError
from lucid.project import ProjectError
from lucid.timeline import TimelineError
from lucid.transcript import TranscriptError
from lucid.verify import VerifyError


def _word_range(value: str) -> list[int]:
    """Parse a `FIRST:LAST` or `FIRST` word range from the command line."""
    first, _, last = value.partition(":")
    try:
        lo = int(first)
        hi = int(last) if last else lo
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"{value!r} is not a word range — use FIRST:LAST, e.g. 30:45"
        ) from None
    return [lo, hi]


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="lucid",
        description="Local-first AI video editing: an MCP server over ffmpeg, whisper, and OTIO.",
    )
    parser.add_argument("--version", action="version", version=f"lucid {__version__}")
    # Global and git-style, before the subcommand: `lucid -C myproject cut ...`.
    # Defining it per-subparser instead would make the two positions clobber
    # each other on the shared dest.
    parser.add_argument(
        "-C", "--project", default=".", help="project directory (default: .)"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("mcp", help="run the MCP server on stdio")
    sub.add_parser("ping", help="print the same payload the MCP ping tool returns")

    p_init = sub.add_parser("init", help="create a project directory")
    p_init.add_argument("path", nargs="?", default=".", help="where to create it (default: .)")
    p_init.add_argument("--name", help="project name (default: the directory name)")

    sub.add_parser("info", help="show a project's manifest")

    p_import = sub.add_parser("import", help="register a media file with the project")
    p_import.add_argument("source", help="path to the media file")
    p_import.add_argument("--clip-id", help="override the generated clip id")
    p_import.add_argument(
        "--copy", action="store_true", help="copy the media in rather than linking it"
    )

    p_attach = sub.add_parser("attach-transcript", help="ingest a word-timed whisper JSON")
    p_attach.add_argument("clip_id")
    p_attach.add_argument("transcript", help="path to the whisper JSON")

    p_tx = sub.add_parser("transcript", help="read a clip's transcript")
    p_tx.add_argument("clip_id")
    p_tx.add_argument("--first", type=int, help="first word index (inclusive)")
    p_tx.add_argument("--last", type=int, help="last word index (inclusive)")
    p_tx.add_argument("--search", help="locate a phrase; returns word ranges")

    p_seed = sub.add_parser("seed", help="lay a clip down as the timeline")
    p_seed.add_argument("clip_id")
    p_seed.add_argument(
        "--keep-silences", action="store_true", help="do not run auto-editor's silence pass"
    )
    p_seed.add_argument("--threshold", type=float, default=0.04, help="audio threshold (0.04)")
    p_seed.add_argument("--margin", help="auto-editor --margin, e.g. 0.2s")
    p_seed.add_argument("--edit", dest="edit_expr", help="auto-editor --edit expression")

    p_cut = sub.add_parser("cut", help="cut or keep word ranges")
    p_cut.add_argument("clip_id")
    p_cut.add_argument(
        "ranges", nargs="+", type=_word_range, metavar="FIRST:LAST", help="inclusive word ranges"
    )
    p_cut.add_argument(
        "--keep",
        action="store_true",
        help="keep these ranges and drop the rest of the clip (default is to cut them)",
    )
    p_cut.add_argument(
        "--pad", type=float, default=0.0, help="widen each range by N seconds on both sides"
    )

    sub.add_parser("status", help="show the current timeline")

    sub.add_parser("undo", help="roll back the last timeline mutation")

    p_cap = sub.add_parser("captions", help="write word-timed ASS captions for the timeline")
    p_cap.add_argument("output", help="where to write the .ass subtitle file")
    p_cap.add_argument(
        "--clip-id", help="caption only this clip (default: every clip with a transcript)"
    )
    p_cap.add_argument(
        "--preset", default="clean", choices=sorted(captions.PRESETS), help="caption style (clean)"
    )
    p_cap.add_argument("--max-words", type=int, default=7, help="words per caption line (7)")
    p_cap.add_argument(
        "--max-gap", type=float, default=0.7, help="silence that starts a new line (0.7s)"
    )
    p_cap.add_argument(
        "--max-duration", type=float, default=6.0, help="longest a line stays up (6.0s)"
    )
    p_cap.add_argument(
        "--hold", type=float, default=0.3, help="linger after the last word (0.3s)"
    )
    p_cap.add_argument(
        "--burn", help="burn the captions into this video — must be a render of this timeline"
    )
    p_cap.add_argument(
        "--burn-output", help="captioned video path (default: renders/<name>-captioned.<ext>)"
    )

    p_verify = sub.add_parser(
        "verify", help="transcribe a render and diff it against the timeline"
    )
    p_verify.add_argument("render", help="the finished render to check")
    p_verify.add_argument(
        "--clip-id",
        "--clip",
        dest="clip_id",
        help="verify against only this clip (default: every clip with a transcript)",
    )
    p_verify.add_argument(
        "--transcript",
        dest="transcript_path",
        help="use this transcript of the render instead of running whisper",
    )
    p_verify.add_argument(
        "--model", default=asr.DEFAULT_MODEL, help=f"whisper model ({asr.DEFAULT_MODEL})"
    )
    p_verify.add_argument("--language", help="force a language instead of detecting one")

    p_export = sub.add_parser("export", help="export or render the timeline via auto-editor")
    p_export.add_argument("output", help="output path")
    p_export.add_argument(
        "--format",
        dest="export_format",
        default="kdenlive",
        help="auto-editor export target (default: kdenlive)",
    )
    p_export.add_argument(
        "--render",
        action="store_true",
        help="render media instead of exporting an NLE project",
    )
    p_export.add_argument(
        "--fps",
        type=float,
        help="frame rate for the NLE timeline (default: the picture's, else 30)",
    )

    return parser


def _emit(payload: object) -> int:
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return 0


def _cmd_init(args: argparse.Namespace) -> int:
    return _emit(ops.init(args.path, name=args.name))


def _cmd_info(args: argparse.Namespace) -> int:
    from lucid.project import Project

    return _emit(Project.open(args.project).read_manifest())


def _cmd_import(args: argparse.Namespace) -> int:
    return _emit(
        ops.import_media(args.project, args.source, clip_id=args.clip_id, copy=args.copy)
    )


def _cmd_attach_transcript(args: argparse.Namespace) -> int:
    return _emit(ops.attach_transcript(args.project, args.clip_id, args.transcript))


def _cmd_transcript(args: argparse.Namespace) -> int:
    return _emit(
        ops.get_transcript(
            args.project, args.clip_id, first=args.first, last=args.last, search=args.search
        )
    )


def _cmd_seed(args: argparse.Namespace) -> int:
    return _emit(
        ops.seed_timeline(
            args.project,
            args.clip_id,
            remove_silences=not args.keep_silences,
            threshold=args.threshold,
            margin=args.margin,
            edit_expr=args.edit_expr,
        )
    )


def _cmd_cut(args: argparse.Namespace) -> int:
    ranges = args.ranges
    return _emit(
        ops.cut_by_transcript(
            args.project,
            args.clip_id,
            cut=None if args.keep else ranges,
            keep=ranges if args.keep else None,
            pad=args.pad,
        )
    )


def _cmd_status(args: argparse.Namespace) -> int:
    return _emit(ops.status(args.project))


def _cmd_undo(args: argparse.Namespace) -> int:
    return _emit(ops.undo(args.project))


def _cmd_captions(args: argparse.Namespace) -> int:
    return _emit(
        ops.add_captions(
            args.project,
            args.output,
            clip_id=args.clip_id,
            preset=args.preset,
            max_words=args.max_words,
            max_gap=args.max_gap,
            max_duration=args.max_duration,
            hold=args.hold,
            burn=args.burn,
            burn_output=args.burn_output,
        )
    )


def _cmd_verify(args: argparse.Namespace) -> int:
    return _emit(
        ops.verify(
            args.project,
            args.render,
            clip_id=args.clip_id,
            transcript_path=args.transcript_path,
            model=args.model,
            language=args.language,
        )
    )


def _cmd_export(args: argparse.Namespace) -> int:
    fmt = None if args.render else args.export_format
    return _emit(ops.export(args.project, args.output, export_format=fmt, fps=args.fps))


def _cmd_ping(_args: argparse.Namespace) -> int:
    from lucid.server import ping

    return _emit(ping())


def _cmd_mcp(_args: argparse.Namespace) -> int:
    from lucid.server import serve

    serve()
    return 0


_COMMANDS = {
    "init": _cmd_init,
    "info": _cmd_info,
    "import": _cmd_import,
    "attach-transcript": _cmd_attach_transcript,
    "transcript": _cmd_transcript,
    "seed": _cmd_seed,
    "cut": _cmd_cut,
    "status": _cmd_status,
    "undo": _cmd_undo,
    "captions": _cmd_captions,
    "verify": _cmd_verify,
    "export": _cmd_export,
    "ping": _cmd_ping,
    "mcp": _cmd_mcp,
}

#: Every failure lucid raises deliberately. Anything else is a bug and should
#: keep its traceback rather than be flattened into a one-line message.
_EXPECTED = (
    ProjectError,
    MediaError,
    TranscriptError,
    TimelineError,
    AutoEditorError,
    captions.CaptionError,
    ASRError,
    VerifyError,
)


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        return _COMMANDS[args.command](args)
    except _EXPECTED as exc:
        print(f"lucid: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
