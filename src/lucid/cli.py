"""The `lucid` CLI.

Every MCP tool is also reachable here, so the same operations can be scripted
or debugged without an agent in the loop. Both front ends call `lucid.ops`;
neither holds logic of its own.
"""

from __future__ import annotations

import argparse
import json
import sys

from lucid import __version__, asr, captions, energy, ops, webui
from lucid.asr import ASRError
from lucid.autoeditor import AutoEditorError
from lucid.energy import EnergyError
from lucid.media import MediaError
from lucid.picture import PictureError
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


def _parse_timecode(value: str) -> float:
    """Parse a colon-separated timecode, parts optional from the right.

    `"4.4"` -> 4.4, `"0:40.4"` -> 40.4, `"1:00:40.4"` -> 3640.4 — the same
    surface `vo_trim.parse_tc` uses.
    """
    parts = value.split(":")
    if not 1 <= len(parts) <= 3:
        raise argparse.ArgumentTypeError(
            f"{value!r} is not a timecode — use [[H:]M:]S, e.g. 0:40.4"
        )
    try:
        seconds = 0.0
        for part in (float(p) for p in parts):
            seconds = seconds * 60 + part
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"{value!r} is not a timecode — use [[H:]M:]S, e.g. 0:40.4"
        ) from None
    return seconds


def _time_span(value: str) -> list[float]:
    """Parse a render-time span: `START+DURATION` or `START-END`.

    `+DURATION` is primary — it's how a watch-note is phrased ("cut 0:40.4
    for 4.4s"), a start and a length rather than two timestamps someone has
    to compute. `-END` is kept for a note phrased as two timestamps, matching
    `vo_trim`'s own surface.
    """
    if "+" in value:
        start_str, _, duration_str = value.partition("+")
        start = _parse_timecode(start_str)
        try:
            duration = float(duration_str)
        except ValueError:
            raise argparse.ArgumentTypeError(
                f"{value!r} is not START+DURATION — duration must be seconds"
            ) from None
        return [start, start + duration]
    if "-" in value:
        start_str, _, end_str = value.partition("-")
        return [_parse_timecode(start_str), _parse_timecode(end_str)]
    raise argparse.ArgumentTypeError(
        f"{value!r} is not a span — use START-END or START+DURATION, e.g. 0:40.4+4.4"
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="lucid",
        description="Local-first AI video editing: an MCP server over ffmpeg, whisper, and OTIO.",
    )
    parser.add_argument("--version", action="version", version=f"lucid {__version__}")
    # Global and git-style, before the subcommand: `lucid -C myproject cut ...`.
    # Defining it per-subparser instead would make the two positions clobber
    # each other on the shared dest.
    # `default=None`, resolved to "." in `main`, so `init` can tell an
    # explicit `-C .` from no `-C` at all.
    parser.add_argument("-C", "--project", help="project directory (default: .)")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("mcp", help="run the MCP server on stdio")
    sub.add_parser("ping", help="print the same payload the MCP ping tool returns")

    p_init = sub.add_parser("init", help="create a project directory")
    # `default=None`, not `"."`, so the handler can tell "not given" from
    # "given as `.`" and refuse the ambiguous both-were-given call.
    p_init.add_argument(
        "path",
        nargs="?",
        help="where to create it (default: the -C directory, or .)",
    )
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

    p_transcribe = sub.add_parser("transcribe", help="transcribe a clip's media with whisper")
    p_transcribe.add_argument("clip_id")
    p_transcribe.add_argument(
        "--model", default=asr.DEFAULT_MODEL, help=f"whisper model ({asr.DEFAULT_MODEL})"
    )
    p_transcribe.add_argument("--language", help="force a language instead of detecting one")

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
    p_cut.add_argument(
        "--confirm-suspect",
        action="store_true",
        help="allow a boundary word flagged with a suspect duration (see `transcript`)",
    )
    p_cut.add_argument(
        "--plan",
        action="store_true",
        help="show what these ranges resolve to and what the edit would become, "
        "without touching the timeline",
    )

    p_cut_at = sub.add_parser(
        "cut-at", help="cut render/timeline-time spans from watching an export"
    )
    p_cut_at.add_argument(
        "spans", nargs="+", type=_time_span, metavar="START-END|START+DURATION"
    )
    p_cut_at.add_argument(
        "--pad", type=float, default=0.0, help="widen each span's outer edges by N seconds"
    )
    p_cut_at.add_argument(
        "--confirm-suspect",
        action="store_true",
        help="allow an overlapped word flagged with a suspect duration (see `transcript`)",
    )
    p_cut_at.add_argument(
        "--plan",
        action="store_true",
        help="show what these spans resolve to and what the edit would become, "
        "without touching the timeline",
    )

    p_locate = sub.add_parser(
        "locate", help="where a source word or source time plays in the current render"
    )
    p_locate.add_argument("clip_id")
    # Mutually exclusive because they are two ways of naming one thing, and a
    # call giving both cannot say which it meant — `ops.locate` refuses the
    # same combination, this just refuses it earlier and with usage text.
    p_where = p_locate.add_mutually_exclusive_group(required=True)
    p_where.add_argument(
        "--words", type=_word_range, metavar="FIRST[:LAST]", help="inclusive word indices"
    )
    p_where.add_argument(
        "--at", type=_parse_timecode, metavar="TIMECODE", help="a source instant, [[H:]M:]S"
    )
    p_where.add_argument(
        "--span",
        type=_time_span,
        metavar="START-END|START+DURATION",
        help="a source interval, in the seconds of the original recording",
    )

    sub.add_parser("status", help="show the current timeline")

    p_view = sub.add_parser(
        "view", help="the whole edit as one payload: segments, seams, every word's fate"
    )
    p_view.add_argument(
        "--clip-id", help="which clip's words to report (default: the one the timeline opens with)"
    )

    p_web = sub.add_parser("web", help="serve the preview/timeline UI on localhost")
    p_web.add_argument("--host", default=webui.DEFAULT_HOST, help=f"bind address ({webui.DEFAULT_HOST})")
    p_web.add_argument(
        "--port", type=int, default=webui.DEFAULT_PORT, help=f"port ({webui.DEFAULT_PORT}); 0 picks a free one"
    )
    p_web.add_argument("--open", action="store_true", help="open a browser at it")
    p_web.add_argument("--verbose", action="store_true", help="log every request, media ranges included")

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
        "--model",
        help=f"whisper model (default: {asr.DEFAULT_MODEL}, or "
        f"{asr.WINDOWED_MODEL} with --windowed)",
    )
    p_verify.add_argument("--language", help="force a language instead of detecting one")
    p_verify.add_argument(
        "--windowed",
        action="store_true",
        help="transcribe in short overlapping windows — catches a retake a single "
        "pass collapses, at 2x the audio to transcribe",
    )
    p_verify.add_argument(
        "--window", type=float, default=asr.WINDOW, help=f"window length ({asr.WINDOW}s)"
    )
    p_verify.add_argument(
        "--overlap", type=float, default=asr.OVERLAP, help=f"window overlap ({asr.OVERLAP}s)"
    )

    p_frames = sub.add_parser(
        "frames", help="count the timeline's frames, and check an export against it"
    )
    p_frames.add_argument(
        "target",
        nargs="?",
        help="an NLE project to ask melt about, or a render to count with ffprobe "
        "(default: just report the timeline's own total)",
    )
    p_frames.add_argument(
        "--fps",
        type=float,
        help="the rate the export used (default: the picture's, else 30)",
    )

    p_black = sub.add_parser(
        "black", help="scan a render for black stretches and explain the known ones"
    )
    p_black.add_argument("target", help="the render to scan")
    p_black.add_argument(
        "--fps", type=float, help="the rate the export used (default: the picture's, else 30)"
    )
    p_black.add_argument(
        "--pix-th", type=float, default=0.10, help="ffmpeg blackdetect pix_th (0.10)"
    )
    p_black.add_argument(
        "--min-duration",
        type=float,
        help="shortest run to count, in seconds (default: 0 — see check_black's docstring "
        "for why a positive default would hide the known tail-frame case)",
    )

    p_spots = sub.add_parser(
        "spots", help="pull sample frames from a render, with darkest-first luma stats"
    )
    p_spots.add_argument("target", help="the render to sample")
    p_spots.add_argument("--count", type=int, default=6, help="evenly-spaced samples (6)")
    p_spots.add_argument(
        "--at",
        dest="times",
        type=float,
        action="append",
        metavar="SECONDS",
        help="an explicit sample time; repeatable",
    )
    p_spots.add_argument(
        "--fps", type=float, help="the rate the export used (default: the picture's, else 30)"
    )

    p_atten = sub.add_parser(
        "attenuate", help="pull down short loud non-speech events in narrow word-map gaps"
    )
    p_atten.add_argument("clip_id")
    p_atten.add_argument("--db", type=float, default=-12.0, help="gain reduction in dB (-12.0)")
    p_atten.add_argument(
        "--max-event-seconds",
        type=float,
        default=1.5,
        help="longest event duration that still qualifies (1.5s)",
    )
    p_atten.add_argument(
        "--max-gap-seconds",
        type=float,
        default=2.0,
        help="widest gap that still proves the word map is dense (2.0s)",
    )
    p_atten.add_argument(
        "--pad", type=float, default=0.05, help="widen each attenuated span by N seconds (0.05)"
    )
    p_atten.add_argument(
        "--confirm-suspect",
        action="store_true",
        help="also attenuate events whose bounding word has a suspect duration",
    )
    p_atten.add_argument(
        "--plan",
        action="store_true",
        help="show what would be attenuated without writing anything",
    )

    p_speech = sub.add_parser(
        "speech-overlap",
        help="does a proposed clip placement overlap the VO's speech, once both are mapped through the edit?",
    )
    p_speech.add_argument("clip_id")
    p_speech.add_argument(
        "--at", type=_parse_timecode, default=0.0, help="proposed placement start on the timeline (0.0)"
    )
    p_speech.add_argument(
        "--in",
        dest="clip_in",
        type=_parse_timecode,
        help="clip start, source time (default: 0.0)",
    )
    p_speech.add_argument(
        "--out",
        dest="clip_out",
        type=_parse_timecode,
        help="clip end, source time (default: the clip's own duration)",
    )
    p_speech.add_argument(
        "--vo-clip",
        dest="vo_clip_id",
        help="the VO clip_id on the timeline (default: the sole clip on it)",
    )
    p_speech.add_argument(
        "--max-gap",
        type=float,
        default=0.3,
        help="gap tolerance for merging speech into runs (0.3s)",
    )
    p_speech.add_argument(
        "--min-seam",
        type=float,
        default=0.5,
        help="narrowest clean seam worth reporting (0.5s)",
    )
    p_speech.add_argument(
        "--cap",
        type=float,
        default=energy.CAP,
        help=f"energy.believable's median-multiple cap ({energy.CAP})",
    )

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
    """Create a project, from `-C` or the positional path — never both.

    Every other subcommand *finds* a project through `-C`, so `-C` reading as
    "the project directory" is the habit the CLI teaches. `init` used to
    ignore it entirely and read only its positional, which meant
    `lucid -C myproj init` created a project in the current directory and
    reported success — the wrong directory, silently. Both spellings now work
    and giving two different answers is an error rather than a coin flip.
    """
    if args.project_given and args.path is not None:
        raise ProjectError(
            f"init was given two directories: -C {args.project!r} and {args.path!r}. "
            "Pass one — they name where the project goes, and there is no "
            "sensible way to pick between them."
        )
    return _emit(ops.init(args.path if args.path is not None else args.project, name=args.name))


def _cmd_info(args: argparse.Namespace) -> int:
    from lucid.project import Project

    return _emit(Project.open(args.project).read_manifest())


def _cmd_import(args: argparse.Namespace) -> int:
    return _emit(
        ops.import_media(args.project, args.source, clip_id=args.clip_id, copy=args.copy)
    )


def _cmd_attach_transcript(args: argparse.Namespace) -> int:
    return _emit(ops.attach_transcript(args.project, args.clip_id, args.transcript))


def _cmd_transcribe(args: argparse.Namespace) -> int:
    return _emit(
        ops.transcribe(args.project, args.clip_id, model=args.model, language=args.language)
    )


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
            confirm_suspect=args.confirm_suspect,
            plan=args.plan,
        )
    )


def _cmd_cut_at(args: argparse.Namespace) -> int:
    return _emit(
        ops.cut_by_time(
            args.project,
            spans=args.spans,
            pad=args.pad,
            confirm_suspect=args.confirm_suspect,
            plan=args.plan,
        )
    )


def _cmd_locate(args: argparse.Namespace) -> int:
    first = last = None
    source_start = source_end = None
    if args.words is not None:
        first, last = args.words
    elif args.span is not None:
        source_start, source_end = args.span
    else:
        source_start = args.at
    return _emit(
        ops.locate(
            args.project,
            args.clip_id,
            first=first,
            last=last,
            source_start=source_start,
            source_end=source_end,
        )
    )


def _cmd_status(args: argparse.Namespace) -> int:
    return _emit(ops.status(args.project))


def _cmd_view(args: argparse.Namespace) -> int:
    return _emit(ops.timeline_view(args.project, clip_id=args.clip_id))


def _cmd_web(args: argparse.Namespace) -> int:
    # Blocks until Ctrl-C. Unlike every other subcommand this one prints no
    # JSON — its output is the page.
    webui.serve(
        args.project,
        host=args.host,
        port=args.port,
        verbose=args.verbose,
        open_browser=args.open,
    )
    return 0


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
            windowed=args.windowed,
            window=args.window,
            overlap=args.overlap,
        )
    )


def _cmd_frames(args: argparse.Namespace) -> int:
    return _emit(ops.check_frames(args.project, args.target, fps=args.fps))


def _cmd_black(args: argparse.Namespace) -> int:
    return _emit(
        ops.check_black(
            args.project,
            args.target,
            fps=args.fps,
            pix_th=args.pix_th,
            min_duration=args.min_duration,
        )
    )


def _cmd_spots(args: argparse.Namespace) -> int:
    return _emit(
        ops.spot_frames(args.project, args.target, count=args.count, times=args.times, fps=args.fps)
    )


def _cmd_attenuate(args: argparse.Namespace) -> int:
    return _emit(
        ops.attenuate_noises(
            args.project,
            args.clip_id,
            db=args.db,
            max_event_seconds=args.max_event_seconds,
            max_gap_seconds=args.max_gap_seconds,
            pad=args.pad,
            confirm_suspect=args.confirm_suspect,
            plan=args.plan,
        )
    )


def _cmd_speech_overlap(args: argparse.Namespace) -> int:
    return _emit(
        ops.speech_overlap(
            args.project,
            args.clip_id,
            at=args.at,
            clip_in=args.clip_in,
            clip_out=args.clip_out,
            vo_clip_id=args.vo_clip_id,
            max_gap=args.max_gap,
            min_seam=args.min_seam,
            cap=args.cap,
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
    "transcribe": _cmd_transcribe,
    "transcript": _cmd_transcript,
    "seed": _cmd_seed,
    "cut": _cmd_cut,
    "cut-at": _cmd_cut_at,
    "locate": _cmd_locate,
    "status": _cmd_status,
    "view": _cmd_view,
    "web": _cmd_web,
    "undo": _cmd_undo,
    "captions": _cmd_captions,
    "verify": _cmd_verify,
    "frames": _cmd_frames,
    "black": _cmd_black,
    "spots": _cmd_spots,
    "attenuate": _cmd_attenuate,
    "speech-overlap": _cmd_speech_overlap,
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
    PictureError,
    EnergyError,
)


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    # `-C` defaults here rather than in argparse because `init` is the one
    # subcommand whose directory is an *argument* rather than a lookup, so it
    # alone needs to know whether `-C` was actually typed.
    args.project_given = args.project is not None
    if args.project is None:
        args.project = "."
    try:
        return _COMMANDS[args.command](args)
    except _EXPECTED as exc:
        print(f"lucid: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
