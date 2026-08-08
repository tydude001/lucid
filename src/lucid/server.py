"""The `lucid mcp` server — MCP tools over stdio.

Every tool here is a thin wrapper over `lucid.ops`, and every one has a
matching `lucid` CLI subcommand (CLAUDE.md). Tool bodies stay trivial on
purpose: logic that lives here is logic the CLI cannot reach and the stdio
tests cannot isolate.

Note the SDK is v2 — `MCPServer` from `mcp.server`. There is no `FastMCP` and
no `mcp.server.fastmcp` module, whatever your priors say.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from mcp.server import MCPServer

from lucid import __version__, asr, ops

mcp: MCPServer = MCPServer(
    name="lucid",
    version=__version__,
    instructions=(
        "lucid edits video locally. All state lives in a project directory on "
        "disk; nothing is uploaded.\n\n"
        "The usual order is: init -> import_media -> attach_transcript -> "
        "seed_timeline -> cut_by_transcript (repeatedly) -> export.\n\n"
        "Word indices in cut_by_transcript address the ORIGINAL recording and "
        "never renumber, so a range stays valid across accumulated cuts. Use "
        "get_transcript with search= to locate a phrase rather than reading "
        "the whole transcript. Every mutation is snapshotted; undo rolls one "
        "back."
    ),
)


@mcp.tool()
def ping() -> dict[str, str]:
    """Check that the lucid MCP server is alive, and report its version."""
    return {"status": "ok", "server": "lucid", "version": __version__}


@mcp.tool()
def init(path: str, name: str | None = None) -> dict[str, Any]:
    """Create a lucid project directory at `path`."""
    return ops.init(path, name=name)


@mcp.tool()
def import_media(
    path: str, source: str, clip_id: str | None = None, copy: bool = False
) -> dict[str, Any]:
    """Register a media file with the project, probing it with ffprobe.

    Links the media by default rather than copying it. Returns the clip record,
    including the `clip_id` every other tool takes.
    """
    return ops.import_media(path, source, clip_id=clip_id, copy=copy)


@mcp.tool()
def attach_transcript(path: str, clip_id: str, transcript_path: str) -> dict[str, Any]:
    """Ingest an existing word-timed whisper JSON as this clip's transcript."""
    return ops.attach_transcript(path, clip_id, transcript_path)


@mcp.tool()
def transcribe(
    path: str, clip_id: str, model: str = "turbo", language: str | None = None
) -> dict[str, Any]:
    """Transcribe a clip's own media with whisper, and attach the result.

    attach_transcript's ASR-driven sibling: use that when the recording
    already has a transcript, this when it needs one made. Takes minutes on a
    long recording — there is no timeout, so let it run.
    """
    return ops.transcribe(path, clip_id, model=model, language=language)


@mcp.tool()
def get_transcript(
    path: str,
    clip_id: str,
    first: int | None = None,
    last: int | None = None,
    search: str | None = None,
) -> dict[str, Any]:
    """Read a clip's transcript.

    With `search`, returns each match as a word range ready to hand to
    cut_by_transcript — prefer this to reading the whole transcript. With
    `first`/`last`, returns that window of words. Indices are inclusive.
    """
    return ops.get_transcript(path, clip_id, first=first, last=last, search=search)


@mcp.tool()
def seed_timeline(
    path: str,
    clip_id: str,
    remove_silences: bool = True,
    threshold: float = 0.04,
    margin: str | None = None,
    edit_expr: str | None = None,
) -> dict[str, Any]:
    """Lay a clip down as the timeline, silence-cut by auto-editor by default.

    `edit_expr` passes auto-editor's edit language straight through, e.g.
    "(or audio:0.03 motion:0.06)".
    """
    return ops.seed_timeline(
        path,
        clip_id,
        remove_silences=remove_silences,
        threshold=threshold,
        margin=margin,
        edit_expr=edit_expr,
    )


@mcp.tool()
def cut_by_transcript(
    path: str,
    clip_id: str,
    cut: Sequence[Sequence[int]] | None = None,
    keep: Sequence[Sequence[int]] | None = None,
    pad: float = 0.0,
) -> dict[str, Any]:
    """Cut or keep inclusive word ranges, e.g. cut=[[30, 45], [120, 131]].

    Pass exactly one of `cut` or `keep`. `pad` widens each range on both sides
    in seconds, to land the cut in the silence between words. The timeline is
    snapshotted first, so this is undoable.
    """
    return ops.cut_by_transcript(path, clip_id, cut=cut, keep=keep, pad=pad)


@mcp.tool()
def timeline_status(path: str) -> dict[str, Any]:
    """Report the current timeline: duration, segment count, undo depth."""
    return ops.status(path)


@mcp.tool()
def undo(path: str) -> dict[str, Any]:
    """Roll the timeline back to the state before the last mutation."""
    return ops.undo(path)


@mcp.tool()
def export(
    path: str, output: str, export_format: str | None = "kdenlive", fps: float | None = None
) -> dict[str, Any]:
    """Export the timeline via auto-editor.

    "kdenlive" writes an MLT project that Kdenlive opens and melt renders —
    the handoff that works on Linux. Pass export_format=null to render media
    instead. Other auto-editor targets (shotcut, premiere, resolve, final-cut-pro)
    pass straight through.

    `fps` sets the NLE timeline's frame rate; it defaults to the picture's rate,
    or 30 for an audio-only project. It is ignored when rendering media.
    """
    return ops.export(path, output, export_format=export_format, fps=fps)


@mcp.tool()
def add_captions(
    path: str,
    output: str,
    clip_id: str | None = None,
    preset: str = "clean",
    max_words: int = 7,
    max_gap: float = 0.7,
    max_duration: float = 6.0,
    hold: float = 0.3,
    burn: str | None = None,
    burn_output: str | None = None,
) -> dict[str, Any]:
    """Write word-timed ASS captions for the current timeline to `output`.

    Timings follow the *timeline*, not the original recording, so captions stay
    correct after cuts; words that were cut are omitted and counted as
    `words_cut`. Presets are "clean", "karaoke" (per-word highlight) and
    "boxed".

    The sidecar .ass is the default exit — Kdenlive loads it and it stays
    restylable. Pass `burn` (a render of THIS timeline) to burn the captions in
    with ffmpeg instead; against any other video the timings will not line up.
    """
    return ops.add_captions(
        path,
        output,
        clip_id=clip_id,
        preset=preset,
        max_words=max_words,
        max_gap=max_gap,
        max_duration=max_duration,
        hold=hold,
        burn=burn,
        burn_output=burn_output,
    )


@mcp.tool()
def verify(
    path: str,
    render: str,
    clip_id: str | None = None,
    transcript_path: str | None = None,
    model: str | None = None,
    language: str | None = None,
    windowed: bool = False,
    # Bound to the module constants rather than restated: a stale literal here
    # is a tool whose schema advertises a default the CLI no longer uses.
    window: float = asr.WINDOW,
    overlap: float = asr.OVERLAP,
) -> dict[str, Any]:
    """Transcribe a finished render and diff it against what the timeline says.

    Run this after rendering, before calling an edit done. It transcribes the
    render with whisper and compares that word sequence to the one the timeline
    should play, which is the only check that catches a retake still in the
    picture: whisper collapses an immediate repeat into a single utterance, so a
    doubled phrase can be invisible in the source transcript and still be in the
    render.

    Read `repeated` first — an entry there is a phrase the render plays more
    times than the timeline expects, i.e. a surviving retake, with the heard word
    index to look at. `dropped` is the opposite: words the timeline expects that
    the render never says, usually a cut that reached too far.

    **A clean single-pass result is not proof.** This check has a known blind
    spot: the render's transcript is itself one whisper pass, which collapses a
    repeat the same way the source transcript did — three retakes survived a
    correct run of it on a real video. Set `windowed=True` to transcribe in
    short overlapping windows instead, which is what found them. It costs one
    whisper run over 2x the audio and uses a deliberately smaller model, so
    run the default first and escalate to it before calling an edit finished.

    `loud_gaps` comes back either way and trusts no transcript: it measures the
    render's own energy and reports holes in the heard word map that hold sound
    anyway. An entry is a place to *listen*, not a verdict — a music bed or an
    attenuated noise can produce one. Read `speech_db`/`threshold_db` beside it.

    `similarity` around 0.97 is normal on a *clean* render — whisper spells its
    own output differently on a second pass ("whodunit" / "who done it", "4" /
    "four"). Treat it as triage; `diff` is the artifact. Transcription takes
    minutes on a long render, and the result is cached under
    cache/verify/ and reported as `heard_transcript` — pass it back as
    `transcript_path` to re-diff without re-transcribing.
    """
    return ops.verify(
        path,
        render,
        clip_id=clip_id,
        transcript_path=transcript_path,
        model=model,
        language=language,
        windowed=windowed,
        window=window,
        overlap=overlap,
    )


def serve() -> None:
    """Run the server on stdio. Blocks until the client disconnects."""
    mcp.run(transport="stdio")
