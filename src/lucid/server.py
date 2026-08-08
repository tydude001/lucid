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
    """Ingest an existing word-timed whisper JSON as this clip's transcript.

    Checks the transcript against itself for `near_duplicates` — adjacent
    runs of words that sound like the same line said twice. That is a
    retake `verify` can never catch once both takes are cut into the edit,
    since nothing then disagrees with the timeline. A hit is not a verdict:
    a deliberate callback line looks the same as a swallowed retake here.
    """
    return ops.attach_transcript(path, clip_id, transcript_path)


@mcp.tool()
def transcribe(
    path: str, clip_id: str, model: str = "turbo", language: str | None = None
) -> dict[str, Any]:
    """Transcribe a clip's own media with whisper, and attach the result.

    attach_transcript's ASR-driven sibling: use that when the recording
    already has a transcript, this when it needs one made. Takes minutes on a
    long recording — there is no timeout, so let it run. Reports
    `near_duplicates` the same way attach_transcript does.
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
    confirm_suspect: bool = False,
    plan: bool = False,
) -> dict[str, Any]:
    """Cut or keep inclusive word ranges, e.g. cut=[[30, 45], [120, 131]].

    Pass exactly one of `cut` or `keep`. `pad` widens each range on both sides
    in seconds, to land the cut in the silence between words. The timeline is
    snapshotted first, so this is undoable.

    Every range echoes back the words it resolved to, plus the few words either
    side of it — an index one past the intended phrase reads fine on its own
    and is only visibly wrong next to its neighbours. `pad_reach` names any
    neighbour the padding eats, since padding is in seconds and the echoed text
    is not.

    `plan=True` returns that whole payload — including what the timeline would
    become — without writing anything. Prefer it over cutting and undoing.

    Refused if a range's first or last word claims a suspect duration (see
    `attach_transcript`/`transcribe`'s `suspect_durations`) — that word's
    `end`/`start` is what the cut boundary resolves to, and it is usually
    hiding a retake rather than ending where it claims. Check the word, then
    retry with `confirm_suspect=True` if the boundary is actually fine. Under
    `plan=True` these are reported as `suspect_boundaries` instead of refused.
    """
    return ops.cut_by_transcript(
        path,
        clip_id,
        cut=cut,
        keep=keep,
        pad=pad,
        confirm_suspect=confirm_suspect,
        plan=plan,
    )


@mcp.tool()
def cut_by_time(
    path: str,
    spans: Sequence[Sequence[float]],
    pad: float = 0.0,
    confirm_suspect: bool = False,
    plan: bool = False,
) -> dict[str, Any]:
    """Cut spans of RENDER/TIMELINE time — what a human reports watching an export.

    Each span is [start, end) in the seconds the current export plays at
    (what timeline_status/verify describe), not source time and not word
    indices. lucid converts each span to the source interval(s) it plays —
    the inverse of the mapping captions and playback use — and cuts those
    through the same Edit.remove path cut_by_transcript uses. The render
    timestamp is never stored: the conversion happens once, here, at call
    time.

    All spans resolve against the CURRENT timeline before any is applied, so a
    list of notes from one watch stays valid together even though a real cut
    would shift every later timestamp. Overlapping spans are refused rather
    than silently double-applied.

    Every piece echoes the source interval it produced (more than one when the
    span crosses an earlier cut or a clip boundary) and the words it overlaps
    there, plus three neighbours either side — the human check that the
    timestamp actually hit the intended flub. `pad` widens only the OUTER
    edges of each requested span. `plan=True` resolves and reports without
    writing, identically to cut_by_transcript.

    Refused the same way cut_by_transcript is if a span overlaps a word with a
    suspect duration; `confirm_suspect=True` or `plan=True` behave the same.
    """
    return ops.cut_by_time(path, spans=spans, pad=pad, confirm_suspect=confirm_suspect, plan=plan)


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


@mcp.tool()
def check_frames(path: str, target: str | None = None, fps: float | None = None) -> dict[str, Any]:
    """Check an export's frame count against what the timeline says it should be.

    The picture-side counterpart to `verify`, which covers only the audio. Run
    this on the exported NLE project **before** rendering — that is where it is
    worth the most, because the count settles whether the cut positions are
    right for the price of reading a document rather than encoding one.

    `target` is an NLE project (.kdenlive/.mlt/.xml, put to `melt -consumer
    xml`) or a finished render (counted with ffprobe). Omit it to just report
    `expected_frames`, the total the timeline lays down.

    Read `agrees` first, then `delta` — how many frames the target has that the
    timeline does not. A non-zero delta on an NLE project means the render will
    not be the length the edit is, and `notes` says so when the cause is one
    lucid already knows about. `agrees` is null, not false, for an audio-only
    render: it has no frames, so nothing was checked.

    `fps` must match the rate the export ran at or the two sides are counting on
    different grids; it defaults to the rate `export` would have picked.
    """
    return ops.check_frames(path, target, fps=fps)


@mcp.tool()
def check_black(
    path: str,
    target: str,
    fps: float | None = None,
    pix_th: float = 0.10,
    min_duration: float | None = None,
) -> dict[str, Any]:
    """Scan a render for black stretches, and say whether each is the known
    kdenlive-export tail frame (picture.KNOWN_TAIL_FRAME) or a genuine defect.

    `target` is required — unlike check_frames, there is no cheap no-target
    mode; there is nothing to detect black in without a render. A run is
    only ever explained when it sits at the tail *and* the frame delta
    against the timeline matches the known defect exactly; a black run
    inside the declared picture is always reported as a real defect.
    """
    return ops.check_black(path, target, fps=fps, pix_th=pix_th, min_duration=min_duration)


@mcp.tool()
def spot_frames(
    path: str,
    target: str,
    count: int = 6,
    times: Sequence[float] | None = None,
    fps: float | None = None,
) -> dict[str, Any]:
    """Pull `count` evenly-spaced frames (plus any explicit `times`) from a
    render as PNGs with signalstats luma, ranked darkest-first.

    When `target`'s own probed duration still matches the current timeline
    within a frame (`mapping_trusted`), each frame also reports which
    clip/word it lands near via `Edit.source_at` — refused, not guessed,
    when the render looks stale.
    """
    return ops.spot_frames(path, target, count=count, times=times, fps=fps)


def serve() -> None:
    """Run the server on stdio. Blocks until the client disconnects."""
    mcp.run(transport="stdio")
