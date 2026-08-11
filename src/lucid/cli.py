"""The `lucid` CLI.

Every MCP tool is also reachable here, so the same operations can be scripted
or debugged without an agent in the loop. Both front ends call `lucid.ops`;
neither holds logic of its own.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from lucid import __version__, asr, captions, describe, energy, ops, webui
from lucid.asr import ASRError
from lucid.autoeditor import AutoEditorError
from lucid.describe import DescribeError
from lucid.energy import EnergyError
from lucid.graphics import GraphicsError
from lucid.media import MediaError
from lucid.mlt import MLTError
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


def _resolution(value: str) -> tuple[int, int]:
    """Parse a `WIDTHxHEIGHT` export resolution, e.g. `1080x1920`."""
    width_str, _, height_str = value.partition("x")
    try:
        width, height = int(width_str), int(height_str)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"{value!r} is not a resolution — use WIDTHxHEIGHT, e.g. 1920x1080"
        ) from None
    return (width, height)


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

    p_info = sub.add_parser("info", help="show a project's manifest")
    p_info.add_argument(
        "--raw",
        action="store_true",
        help="print the manifest verbatim, descriptions and all",
    )

    p_migrate = sub.add_parser(
        "migrate", help="bring an older project manifest forward to the current schema"
    )
    p_migrate.add_argument(
        "--plan", action="store_true", help="report the steps and the version, writing nothing"
    )

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

    p_tx_checks = sub.add_parser(
        "transcript-checks",
        help="re-run the attach-time transcript checks over an attached transcript",
    )
    p_tx_checks.add_argument(
        "clip_id", nargs="?", help="one clip; omitted, every clip with a transcript"
    )

    p_describe = sub.add_parser(
        "describe", help="describe a clip's footage in windows, for b-roll search"
    )
    p_describe.add_argument(
        "clip_id", nargs="?", help="one clip; omitted, every video clip not yet described"
    )
    p_describe.add_argument(
        "--window",
        type=float,
        default=describe.WINDOW,
        help=f"seconds of footage per description ({describe.WINDOW:g})",
    )
    p_describe.add_argument(
        "--force", action="store_true", help="describe again, replacing what is stored"
    )
    p_describe.add_argument(
        "--plan",
        action="store_true",
        help="resolve the work list and the estimate without loading a model",
    )

    p_describe_ls = sub.add_parser(
        "describe-ls", help="read the footage descriptions — this is the b-roll search"
    )
    p_describe_ls.add_argument(
        "clip_id", nargs="?", help="only this clip's descriptions (default: every clip)"
    )
    p_describe_ls.add_argument(
        "--contains",
        help="keep descriptions containing every one of these terms, case-insensitively",
    )

    p_card = sub.add_parser("card", help="generate the card assets a picture cue points at")
    card_sub = p_card.add_subparsers(dest="card_command", required=True)

    card_sub.add_parser("templates", help="the card templates lucid ships, and their slots")

    p_card_new = card_sub.add_parser(
        "new", help="fill a template's slots and land both the SVG and its PNG"
    )
    p_card_new.add_argument("name", help="the <name> in card:<name>, without an extension")
    p_card_new.add_argument("--template", required=True, help="see `lucid card templates`")
    p_card_new.add_argument(
        "--set",
        action="append",
        default=[],
        metavar="SLOT=VALUE",
        dest="slots",
        help="fill one slot; repeat for each. A literal \\n in VALUE is a line break",
    )
    p_card_new.add_argument(
        "--width", type=int, help="canvas width (default: the project's own)"
    )
    p_card_new.add_argument(
        "--height", type=int, help="canvas height (with --width)"
    )
    p_card_new.add_argument(
        "--overwrite", action="store_true", help="replace a card of this name if one exists"
    )

    p_card_render = card_sub.add_parser(
        "render", help="rasterise assets/cards/<name>.svg to the PNG card:<name> resolves to"
    )
    p_card_render.add_argument("name", help="the <name> in card:<name>, without an extension")
    p_card_render.add_argument(
        "--width", type=int, help="render width in pixels (with --height; fits, never distorts)"
    )
    p_card_render.add_argument(
        "--height", type=int, help="render height in pixels (with --width)"
    )

    p_card_reauthor = card_sub.add_parser(
        "reauthor", help="draw recorded cards again at the project's canvas"
    )
    p_card_reauthor.add_argument(
        "name",
        nargs="?",
        help="one card; omit to redraw every recorded card the canvas has left behind",
    )
    p_card_reauthor.add_argument(
        "--plan", action="store_true", help="report what would be redrawn, writing nothing"
    )

    p_cue = sub.add_parser("cue", help="manage the picture cue table (word_index -> asset)")
    cue_sub = p_cue.add_subparsers(dest="cue_command", required=True)

    p_cue_add = cue_sub.add_parser("add", help="add a cue: from this word onward, show asset")
    p_cue_add.add_argument("clip_id")
    p_cue_add.add_argument("word_index", type=int)
    p_cue_add.add_argument(
        "asset", help="card:name, or a registered video clip_id — `lucid shots` resolves it"
    )
    p_cue_add.add_argument(
        "--src-start",
        type=float,
        help="pin the in-point: seconds into the asset's own source time, as "
        "`lucid describe ls` reports it. Omitted, the shot reads from wherever "
        "the per-asset cursor is. In-point only — the out-point stays derived",
    )

    p_cue_rm = cue_sub.add_parser("rm", help="remove a cue")
    p_cue_rm.add_argument("clip_id")
    p_cue_rm.add_argument("word_index", type=int)

    p_cue_ls = cue_sub.add_parser("ls", help="list the cue table")
    p_cue_ls.add_argument("--clip-id", help="only this clip's cues (default: every clip)")

    p_synopsis = sub.add_parser(
        "synopsis", help="read, set or clear what a clip is — the corpus a b-roll picker needs"
    )
    p_synopsis.add_argument(
        "clip_id", nargs="?", help="omit to list every clip's synopsis and which are missing one"
    )
    p_synopsis.add_argument(
        "text",
        nargs="?",
        help="a sentence or three naming the work, the scene and the people. It is "
        "allowed to carry what a camera cannot see — who wrote it, what the twist "
        "means — because that is what decides the placement",
    )
    p_synopsis.add_argument("--clear", action="store_true", help="remove this clip's synopsis")

    p_broll = sub.add_parser(
        "broll-brief",
        help="the whole b-roll question as data: the catalogue, and every position "
        "with the narration over it",
    )
    p_broll.add_argument(
        "--fps", type=float, help="frame grid to answer on (default: the export's rate)"
    )

    p_shots = sub.add_parser(
        "shots", help="project the cue table into contiguous shots over the current edit"
    )
    p_shots.add_argument(
        "--fps",
        type=float,
        help="answer on this frame grid (default: the project timebase, "
        "which for audio-only projects is milliseconds — pass the export's "
        "rate to see the frames the export will actually cut at)",
    )

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
        "--through-pause",
        action="store_true",
        help="extend each cut range's trailing edge through the pause after its last "
        "word, when the gap clears the marker threshold (cut mode only)",
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

    p_restore = sub.add_parser("restore", help="un-cut word ranges that are currently absent")
    p_restore.add_argument("clip_id")
    p_restore.add_argument(
        "ranges",
        nargs="+",
        type=_word_range,
        metavar="FIRST:LAST",
        help="inclusive word ranges to restore",
    )
    p_restore.add_argument(
        "--pad",
        type=float,
        default=0.0,
        help="match the pad used on the original cut, to bring the padding sliver back too",
    )
    p_restore.add_argument(
        "--plan",
        action="store_true",
        help="show what would be restored without touching the timeline",
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

    p_waveform = sub.add_parser(
        "waveform", help="RMS envelope for the timeline's waveform lane (cached)"
    )
    p_waveform.add_argument(
        "--clip-id", help="which clip's media to measure (default: the one the timeline opens with)"
    )

    p_preview = sub.add_parser(
        "preview", help="resolve one preview asset and say whether a browser will play it"
    )
    p_preview.add_argument("asset", help="a cue's asset key: card:<name>, or a clip_id")

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
    # Every one of these defaults to None rather than to a number, and that is
    # load-bearing: the defaults live on the *project* now (`caption-style`),
    # so a flag that defaulted to 7 here would silently overrule a stored 4.
    p_cap.add_argument(
        "--preset", choices=sorted(captions.PRESETS), help="override the project's base preset, for this file only"
    )
    p_cap.add_argument("--max-words", type=int, help="words per caption line (project's, else 7)")
    p_cap.add_argument(
        "--max-gap", type=float, help="silence that starts a new line (project's, else 0.7s)"
    )
    p_cap.add_argument(
        "--max-duration", type=float, help="longest a line stays up (project's, else 6.0s)"
    )
    p_cap.add_argument(
        "--hold", type=float, help="linger after the last word (project's, else 0.3s)"
    )
    p_cap.add_argument(
        "--burn", help="burn the captions into this video — must be a render of this timeline"
    )
    p_cap.add_argument(
        "--burn-output", help="captioned video path (default: renders/<name>-captioned.<ext>)"
    )

    p_capview = sub.add_parser(
        "caption-view", help="the captions this timeline would produce, and the style in force"
    )
    p_capview.add_argument(
        "--clip-id", help="caption only this clip (default: every clip with a transcript)"
    )

    p_capstyle = sub.add_parser(
        "caption-style", help="read or change the caption look this project keeps"
    )
    p_capstyle.add_argument(
        "--preset", choices=sorted(captions.PRESETS), help="the base look everything else overrides"
    )
    p_capstyle.add_argument("--font", help="font family, as libass will look it up")
    p_capstyle.add_argument(
        "--size", type=int, help=f"point size against a {captions.REFERENCE_HEIGHT}-line canvas"
    )
    p_capstyle.add_argument(
        "--text", metavar="COLOUR", help="the words' colour — #rrggbb[aa], a name, or ASS &H…"
    )
    p_capstyle.add_argument(
        "--highlight", metavar="COLOUR", help="what a word turns as it is spoken (karaoke only)"
    )
    p_capstyle.add_argument("--outline-colour", metavar="COLOUR", help="the outline's colour")
    p_capstyle.add_argument("--box-colour", metavar="COLOUR", help="the box/shadow colour")
    p_capstyle.add_argument("--outline-width", type=float, help="outline thickness")
    p_capstyle.add_argument("--shadow", type=float, help="drop-shadow depth")
    p_capstyle.add_argument(
        "--position", choices=sorted(captions.ALIGNMENTS), help="where on the frame the line sits"
    )
    p_capstyle.add_argument("--margin", type=int, help="distance from that edge")
    # Three-state, and it has to be: `store_true` would default to False, and
    # False is a *setting* here — it would turn karaoke off on every unrelated
    # `caption-style --size 72`. BooleanOptionalAction with default=None gives
    # --karaoke / --no-karaoke / say nothing.
    for flag, helptext in (
        ("bold", "draw the text bold"),
        ("box", "draw an opaque box behind the text instead of an outline"),
        ("karaoke", "highlight each word as it is spoken"),
    ):
        p_capstyle.add_argument(
            f"--{flag}", action=argparse.BooleanOptionalAction, default=None, help=helptext
        )
    p_capstyle.add_argument("--max-words", type=int, help="words per caption line")
    p_capstyle.add_argument("--max-gap", type=float, help="silence that starts a new line")
    p_capstyle.add_argument("--max-duration", type=float, help="longest a line stays up")
    p_capstyle.add_argument("--hold", type=float, help="linger after the last word")
    p_capstyle.add_argument(
        "--reset", action="store_true", help="drop every override before applying these"
    )
    p_capstyle.add_argument(
        "--plan", action="store_true", help="resolve and check without writing the manifest"
    )

    p_canvas = sub.add_parser("canvas", help="read or change the shape this project renders at")
    p_canvas.add_argument(
        "size",
        nargs="?",
        metavar="WIDTHxHEIGHT",
        help="e.g. 1080x1920. Omit to read what is in force and what it derives from",
    )
    p_canvas.add_argument(
        "--reset", action="store_true", help="drop the override and go back to the footage's shape"
    )
    p_canvas.add_argument(
        "--plan", action="store_true", help="resolve and check without writing the manifest"
    )

    p_reel = sub.add_parser(
        "reel", help="derive a new project holding one span of this one's timeline"
    )
    p_reel.add_argument("dest", help="where to put the derived project (must not exist yet)")
    # The same surface `cut-at` takes, because it is the same kind of number —
    # seconds an export played at, read off a watch. What differs is the
    # direction: this one names what to *keep*.
    p_reel.add_argument(
        "keep",
        type=_time_span,
        metavar="START-END|START+DURATION",
        help="the span to keep, in the seconds the current export plays at",
    )
    p_reel.add_argument(
        "--canvas",
        metavar="WIDTHxHEIGHT",
        help="reshape the derived project only, e.g. 1080x1920. The film is left alone",
    )
    p_reel.add_argument("--name", help="project name (default: the destination directory's)")
    p_reel.add_argument(
        "--confirm-suspect",
        action="store_true",
        help="allow a kept edge that lands on a word with a suspect duration "
        "(the reel's own two edges — not everything being cut away)",
    )
    p_reel.add_argument(
        "--plan",
        action="store_true",
        help="resolve the spans and the clips it would link, and create nothing",
    )

    p_reframe = sub.add_parser(
        "reframe", help="read or set which part of each clip survives into the frame"
    )
    p_reframe.add_argument(
        "clip_id", nargs="?", help="the clip to crop. Omit to read every clip's crop"
    )
    p_reframe.add_argument(
        "--rect",
        metavar="X,Y,W,H",
        help="the region to keep, in the clip's own source pixels. Grown to the "
        "canvas's shape if it is not already, so everything named stays on screen",
    )
    p_reframe.add_argument(
        "--pane",
        metavar="X,Y,W,H",
        help="draw this window as a stacked split: --rect on top, this below, "
        "each pane getting twice the width one 9:16 crop gets. For the "
        "two-hander one window cannot frame",
    )
    p_reframe.add_argument(
        "--at",
        type=float,
        metavar="SECONDS",
        help="seconds into this clip's own source that the rect applies from, "
        "until the next window. Omit for the window from the head of the file",
    )
    p_reframe.add_argument(
        "--reset",
        action="store_true",
        help="drop this clip's overrides, every one of them with no clip_id, or "
        "just the window named by --at",
    )
    p_reframe.add_argument(
        "--plan", action="store_true", help="resolve and check without writing the manifest"
    )

    p_detect = sub.add_parser(
        "reframe-detect",
        help="propose a framing window per camera shot, from where the faces are",
    )
    p_detect.add_argument(
        "clip_id", nargs="?", help="only this clip's placements. Omit for every one"
    )
    p_detect.add_argument(
        "--threshold",
        type=float,
        default=ops.SCENE_THRESHOLD,
        metavar="SCORE",
        help=f"scene score above which a change of picture is a cut "
        f"(default {ops.SCENE_THRESHOLD}, picked by the framing control)",
    )
    p_detect.add_argument(
        "--frames",
        type=int,
        default=ops.DETECT_FRAMES,
        help=f"frames sampled per window (default {ops.DETECT_FRAMES})",
    )
    p_detect.add_argument(
        "--apply",
        action="store_true",
        help="write the proposals through `reframe`, leaving any window that is "
        "already framed by hand alone. Off by default: look at `reframe-sheet` first",
    )
    p_detect.add_argument(
        "--no-split",
        dest="split",
        action="store_false",
        help="never offer a stacked split, however many subjects a window holds. "
        "On by default, and rare: 3 of the film's 59 windows",
    )

    p_sheet = sub.add_parser(
        "reframe-sheet",
        help="draw every placement's framing window on its own source frames, for review",
    )
    p_sheet.add_argument("--out", help="where to write the montage (default cache/sheets/sheet.png)")
    p_sheet.add_argument(
        "--moments",
        help="comma-separated fractions of each placement to sample (default 0.15,0.5,0.85)",
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

    p_export = sub.add_parser(
        "export",
        help="export or render the timeline (multi-source projects are written as MLT "
        "by lucid and rendered by melt; everything else goes through auto-editor)",
    )
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
        help="render media instead of exporting an NLE project (melt on a "
        "multi-source timeline, auto-editor otherwise)",
    )
    p_export.add_argument(
        "--fps",
        type=float,
        help="frame rate for the NLE timeline, and for a multi-source render "
        "(default: the picture's, else 30)",
    )
    p_export.add_argument(
        "--preset",
        # Read off ops.EXPORT_PRESETS rather than restated here, so a preset
        # added there cannot silently go unreachable from the CLI. 'custom'
        # is not in that dict (ops._resolve_preset handles it specially) so
        # it is added back explicitly.
        choices=[*sorted(ops.EXPORT_PRESETS), "custom"],
        help="a named quality bundle (--render only; an NLE export has no bitrate). "
        "'custom' requires --resolution. 'tiktok-reels' checks that the project's "
        "canvas is 9:16 and refuses otherwise — it never sets the shape, because "
        "that is `lucid canvas`'s job",
    )
    p_export.add_argument(
        "--resolution",
        type=_resolution,
        metavar="WIDTHxHEIGHT",
        help="single-source render only: letterboxes the existing frame to this "
        "size — does not crop or reframe it. Refused on a multi-source (melt) "
        "project. To crop to fill instead, set the shape with `lucid canvas`",
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

    return _emit(_summarise(Project.open(args.project).read_manifest(), raw=args.raw))


def _summarise(manifest: dict[str, Any], *, raw: bool) -> dict[str, Any]:
    """Stand the descriptions down to a count, unless `--raw`.

    `info` prints the manifest, and the manifest is where descriptions live —
    which took a described project's `info` to 103 KB of prose, in a command
    whose whole job is being readable at a glance. `describe-ls` is where the
    text is meant to be read, so this points at it rather than inlining it.
    Substituting a summary is a lie unless the escape hatch exists, hence
    `--raw`: nothing else in lucid can show you the stored bytes.
    """
    if raw or not manifest.get("descriptions"):
        return manifest
    descriptions = manifest["descriptions"]
    per_clip: dict[str, int] = {}
    for entry in descriptions:
        per_clip[entry["clip_id"]] = per_clip.get(entry["clip_id"], 0) + 1
    return {
        **manifest,
        "descriptions": {
            "count": len(descriptions),
            "clips": per_clip,
            "read": "lucid describe-ls (or `lucid info --raw` for the stored entries)",
        },
    }


def _cmd_migrate(args: argparse.Namespace) -> int:
    return _emit(ops.migrate(args.project, plan=args.plan))


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


def _cmd_transcript_checks(args: argparse.Namespace) -> int:
    return _emit(ops.transcript_checks(args.project, args.clip_id))


def _cmd_describe_ls(args: argparse.Namespace) -> int:
    return _emit(ops.describe_ls(args.project, args.clip_id, contains=args.contains))


def _cmd_describe(args: argparse.Namespace) -> int:
    return _emit(
        ops.describe(
            args.project,
            args.clip_id,
            window=args.window,
            force=args.force,
            plan=args.plan,
        )
    )


def _slot_assignments(pairs: list[str]) -> dict[str, str]:
    """`SLOT=VALUE` pairs into a slot dict, `\\n` in VALUE meaning a line break.

    The escape is here rather than in `graphics` because it is a shell
    problem: a real newline inside `--set quote=...` is awkward to type and
    trivial to lose to word splitting, while the op and the MCP tool both
    take the string with its newlines already in it.
    """
    slots: dict[str, str] = {}
    for pair in pairs:
        slot, sep, value = pair.partition("=")
        if not sep or not slot.strip():
            raise ProjectError(f"--set takes SLOT=VALUE, not {pair!r}")
        slots[slot.strip()] = value.replace("\\n", "\n")
    return slots


def _cmd_card(args: argparse.Namespace) -> int:
    if args.card_command == "templates":
        return _emit(ops.card_templates())
    if args.card_command == "new":
        return _emit(
            ops.card_new(
                args.project,
                args.name,
                args.template,
                _slot_assignments(args.slots),
                width=args.width,
                height=args.height,
                overwrite=args.overwrite,
            )
        )
    if args.card_command == "reauthor":
        return _emit(ops.card_reauthor(args.project, args.name, plan=args.plan))
    return _emit(ops.card_render(args.project, args.name, width=args.width, height=args.height))


def _cmd_cue(args: argparse.Namespace) -> int:
    if args.cue_command == "add":
        return _emit(
            ops.cue_add(
                args.project,
                args.clip_id,
                args.word_index,
                args.asset,
                src_start=args.src_start,
            )
        )
    if args.cue_command == "rm":
        return _emit(ops.cue_rm(args.project, args.clip_id, args.word_index))
    return _emit(ops.cue_ls(args.project, clip_id=args.clip_id))


def _cmd_shots(args: argparse.Namespace) -> int:
    return _emit(ops.build_shots(args.project, fps=args.fps))


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
            through_pause=args.through_pause,
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


def _cmd_restore(args: argparse.Namespace) -> int:
    return _emit(
        ops.restore(args.project, args.clip_id, args.ranges, pad=args.pad, plan=args.plan)
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


def _cmd_waveform(args: argparse.Namespace) -> int:
    return _emit(ops.waveform(args.project, clip_id=args.clip_id))


def _cmd_preview(args: argparse.Namespace) -> int:
    return _emit(ops.preview_source(args.project, args.asset))


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


def _cmd_caption_view(args: argparse.Namespace) -> int:
    return _emit(ops.caption_view(args.project, clip_id=args.clip_id))


def _cmd_caption_style(args: argparse.Namespace) -> int:
    return _emit(
        ops.caption_style(
            args.project,
            preset=args.preset,
            font=args.font,
            size=args.size,
            text=args.text,
            highlight=args.highlight,
            outline_colour=args.outline_colour,
            box_colour=args.box_colour,
            bold=args.bold,
            box=args.box,
            outline_width=args.outline_width,
            shadow=args.shadow,
            position=args.position,
            margin=args.margin,
            karaoke=args.karaoke,
            max_words=args.max_words,
            max_gap=args.max_gap,
            max_duration=args.max_duration,
            hold=args.hold,
            reset=args.reset,
            plan=args.plan,
        )
    )


def _cmd_canvas(args: argparse.Namespace) -> int:
    # The raw string goes through: `ops._parse_canvas` owns every refusal, so
    # the CLI and the MCP tool cannot disagree about what a canvas may be.
    return _emit(ops.canvas(args.project, size=args.size, reset=args.reset, plan=args.plan))


def _cmd_reel(args: argparse.Namespace) -> int:
    start, end = args.keep
    return _emit(
        ops.reel(
            args.project,
            args.dest,
            start=start,
            end=end,
            canvas=args.canvas,
            name=args.name,
            confirm_suspect=args.confirm_suspect,
            plan=args.plan,
        )
    )


def _cmd_reframe(args: argparse.Namespace) -> int:
    # Same rule as `canvas` above: the raw `X,Y,W,H` goes through, because
    # `ops._parse_rect` and `ops._fit_rect_to_canvas` own every refusal.
    return _emit(
        ops.reframe(
            args.project,
            args.clip_id,
            rect=args.rect,
            pane=args.pane,
            src_start=args.at,
            reset=args.reset,
            plan=args.plan,
        )
    )


def _cmd_reframe_detect(args: argparse.Namespace) -> int:
    return _emit(
        ops.reframe_detect(
            args.project,
            clip_id=args.clip_id,
            split=args.split,
            threshold=args.threshold,
            frames=args.frames,
            apply=args.apply,
        )
    )


def _cmd_reframe_sheet(args: argparse.Namespace) -> int:
    moments = [float(part) for part in args.moments.split(",")] if args.moments else None
    return _emit(ops.reframe_sheet(args.project, out=args.out, moments=moments))


def _cmd_synopsis(args: argparse.Namespace) -> int:
    return _emit(ops.synopsis(args.project, args.clip_id, args.text, clear=args.clear))


def _cmd_broll_brief(args: argparse.Namespace) -> int:
    return _emit(ops.broll_brief(args.project, fps=args.fps))


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
    return _emit(
        ops.export(
            args.project,
            args.output,
            export_format=fmt,
            fps=args.fps,
            preset=args.preset,
            resolution=args.resolution,
        )
    )


def _cmd_ping(_args: argparse.Namespace) -> int:
    from lucid.server import ping

    return _emit(ping())


def _cmd_mcp(args: argparse.Namespace) -> int:
    from lucid.server import serve

    # `-C` binds the server to one project, and is honoured only when it was
    # actually typed: `main()` defaults it to ".", so binding unconditionally
    # would pin a globally-configured `lucid mcp` to whatever directory its
    # client happened to launch from. Unbound is the general-client default;
    # bound is what the web UI's agent panel spawns (`webui.py`'s generated
    # MCP config), and what confines that agent to the project it was opened
    # on rather than to lucid's ops in general.
    serve(root=args.project if args.project_given else None)
    return 0


_COMMANDS = {
    "init": _cmd_init,
    "info": _cmd_info,
    "migrate": _cmd_migrate,
    "import": _cmd_import,
    "attach-transcript": _cmd_attach_transcript,
    "transcribe": _cmd_transcribe,
    "transcript": _cmd_transcript,
    "transcript-checks": _cmd_transcript_checks,
    "describe": _cmd_describe,
    "describe-ls": _cmd_describe_ls,
    "card": _cmd_card,
    "cue": _cmd_cue,
    "shots": _cmd_shots,
    "seed": _cmd_seed,
    "cut": _cmd_cut,
    "cut-at": _cmd_cut_at,
    "restore": _cmd_restore,
    "locate": _cmd_locate,
    "status": _cmd_status,
    "view": _cmd_view,
    "waveform": _cmd_waveform,
    "preview": _cmd_preview,
    "web": _cmd_web,
    "undo": _cmd_undo,
    "captions": _cmd_captions,
    "caption-view": _cmd_caption_view,
    "caption-style": _cmd_caption_style,
    "canvas": _cmd_canvas,
    "reel": _cmd_reel,
    "reframe": _cmd_reframe,
    "reframe-detect": _cmd_reframe_detect,
    "reframe-sheet": _cmd_reframe_sheet,
    "synopsis": _cmd_synopsis,
    "broll-brief": _cmd_broll_brief,
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
    # The vision model is missing, or failed on a clip — a message naming
    # which interpreter was looked for, not a traceback.
    DescribeError,
    VerifyError,
    PictureError,
    EnergyError,
    GraphicsError,
    # `plan_picture` refuses a shot longer than the asset it points at, and
    # that refusal fired for real on the Scream assembly (HISTORY.md
    # § Rendering through `melt`) — it is a message to read, not a traceback.
    MLTError,
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
