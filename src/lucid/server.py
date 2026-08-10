"""The `lucid mcp` server — MCP tools over stdio.

Every tool here is a thin wrapper over `lucid.ops`, and every one has a
matching `lucid` CLI subcommand (CLAUDE.md). Tool bodies stay trivial on
purpose: logic that lives here is logic the CLI cannot reach and the stdio
tests cannot isolate.

Note the SDK is v2 — `MCPServer` from `mcp.server`. There is no `FastMCP` and
no `mcp.server.fastmcp` module, whatever your priors say.
"""

from __future__ import annotations

import functools
import inspect
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, TypeVar

from mcp.server import MCPServer

from lucid import __version__, asr, energy, ops
from lucid.project import ProjectError

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


#: The project this server is bound to, or None when it is unbound. Set once
#: by `serve(root=...)`, which `lucid mcp` calls with its `-C` directory — and
#: only when `-C` was actually typed, because a globally-configured
#: `lucid mcp` has no project and must keep reaching any of them.
_BOUND_ROOT: Path | None = None

F = TypeVar("F", bound=Callable[..., Any])


def _confine(path: str) -> str:
    """Resolve a tool's `path` argument against the bound project, or refuse it.

    **Only `path` is confined, and that is a deliberate boundary**: `path` is
    the *project selector*, so leaving it free is what lets an agent panel
    opened on one project mutate another. The file arguments are not
    selectors and are left alone — `import_media`'s `source` reads footage
    that lives on the NAS, and `export`/`add_captions` write where the user
    asked. Confining either would break the ordinary workflow while buying
    nothing, since neither can touch a second project's state.

    A relative path resolves against the bound root rather than the process
    cwd. For the agent panel the two are the same directory (`webui.py` sets
    `cwd` on the Popen), but a bound server means "this project", and that
    reading should not depend on where the client happened to be standing.
    Both sides are `resolve()`d, so `..` and a symlink out are refused rather
    than followed.
    """
    root = _BOUND_ROOT
    if root is None:
        return path
    candidate = Path(path)
    resolved = (candidate if candidate.is_absolute() else root / candidate).resolve()
    if resolved != root and root not in resolved.parents:
        raise ProjectError(
            f"this server is bound to {root} and {path!r} resolves outside it "
            f"({resolved}). It was started as `lucid -C {root} mcp`, so every "
            "tool addresses that project; pass a path at or under it."
        )
    return str(resolved)


def _tool() -> Callable[[F], F]:
    """Register a tool, routing its `path` argument through `_confine` first.

    A decorator rather than a line in each body because the confinement has
    to hold for *every* tool — one body that forgot it would be the whole
    hole again — and because tool bodies stay trivial (see this module's
    docstring). `functools.wraps` sets `__wrapped__`, which the SDK's
    `inspect.signature(fn, eval_str=True)` follows, so the advertised schema
    is the undecorated function's and nothing about the tool surface changes.
    """

    def decorator(fn: F) -> F:
        signature = inspect.signature(fn)
        if "path" not in signature.parameters:
            return mcp.tool()(fn)

        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            bound = signature.bind(*args, **kwargs)
            bound.arguments["path"] = _confine(bound.arguments["path"])
            return fn(*bound.args, **bound.kwargs)

        return mcp.tool()(wrapper)

    return decorator


@_tool()
def ping() -> dict[str, str]:
    """Check that the lucid MCP server is alive, and report its version."""
    return {"status": "ok", "server": "lucid", "version": __version__}


@_tool()
def init(path: str, name: str | None = None) -> dict[str, Any]:
    """Create a lucid project directory at `path`."""
    return ops.init(path, name=name)


@_tool()
def migrate_project(path: str, plan: bool = False) -> dict[str, Any]:
    """Bring an older project manifest forward to the current schema version.

    Every other tool refuses a project written by an older lucid rather than
    guessing at a layout it does not recognise; this is what clears that. It
    is forward-only, and it copies the manifest into `cache/history/` before
    writing. `plan=True` reports the version and the steps without writing,
    which is how to ask what a project is before deciding to change it.
    """
    return ops.migrate(path, plan=plan)


@_tool()
def import_media(
    path: str, source: str, clip_id: str | None = None, copy: bool = False
) -> dict[str, Any]:
    """Register a media file with the project, probing it with ffprobe.

    Links the media by default rather than copying it. Returns the clip record,
    including the `clip_id` every other tool takes.
    """
    return ops.import_media(path, source, clip_id=clip_id, copy=copy)


@_tool()
def attach_transcript(path: str, clip_id: str, transcript_path: str) -> dict[str, Any]:
    """Ingest an existing word-timed whisper JSON as this clip's transcript.

    Checks the transcript against itself for `near_duplicates` — adjacent
    runs of words that sound like the same line said twice. That is a
    retake `verify` can never catch once both takes are cut into the edit,
    since nothing then disagrees with the timeline. A hit is not a verdict:
    a deliberate callback line looks the same as a swallowed retake here.
    """
    return ops.attach_transcript(path, clip_id, transcript_path)


@_tool()
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


@_tool()
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


@_tool()
def describe(
    path: str,
    clip_id: str | None = None,
    window: float = 10.0,
    force: bool = False,
    plan: bool = False,
) -> dict[str, Any]:
    """Describe footage in fixed windows, so b-roll can be found by what is in it.

    A description is `(clip_id, src_start, src_end, text)` in **source**
    seconds, which is why cutting the edit can never invalidate one. Omit
    `clip_id` to describe every video clip that has not been described yet;
    name one to do just that clip. Audio-only clips are refused — their words
    are what `transcribe` indexes.

    **This is a job, not a request.** Cost is about three seconds per window
    regardless of how much footage the window spans, so a project's footage
    is minutes of GPU time. Run it with `plan=True` first: that resolves the
    whole work list and the estimate, and reports whether this machine can
    run the model at all, without loading anything.

    Already-described clips are skipped unless `force`. Do not widen `window`
    to save time without a reason — a single pass over a whole clip describes
    six frames as six people, fluently and with nothing saying it is wrong.

    Read `errors` and `truncated` in the result. A truncated description
    stops mid-fact and reads exactly like a complete one, and a window is
    never evidence of a *continuous shot*: the model narrates across a cut
    inside one as though it were a single take.
    """
    return ops.describe(path, clip_id, window=window, force=force, plan=plan)


@_tool()
def describe_ls(
    path: str, clip_id: str | None = None, contains: str | None = None
) -> dict[str, Any]:
    """Read the footage descriptions, to find b-roll by what is in it.

    **This is the search.** There is no ranking and no similarity score to
    ask for — you read the descriptions and pick, which is why the prompt
    behind them asks for concrete nouns. Each entry is `(clip_id, src_start,
    src_end, text)` in **source** seconds, so what you pick stays valid
    however the edit is cut.

    `contains` filters: whitespace-separated terms, case-insensitive, and
    every term must appear — `"kitchen knife"` matches "a knife on the
    kitchen counter". Reach for it before reading everything on a large
    project; `words` says how much text came back.

    Two things not to over-read. A window is evidence of what is *visible in
    a span*, never of a continuous shot — the model narrates across a cut
    inside one as though it were a single take. And an entry with
    `truncated` true stopped mid-fact and reads exactly like a complete
    description.

    A clip listed under `clips` with `windows: 0` has not been described yet;
    `describe` is what indexes it.
    """
    return ops.describe_ls(path, clip_id, contains=contains)


@_tool()
def card_templates() -> dict[str, Any]:
    """The card templates lucid ships, and the slots each one takes.

    Read this before card_new: each slot says what it is for, whether it is
    required, and what it defaults to. The palette and font stacks are slots
    too, so a card can be restyled without authoring an SVG by hand.
    """
    return ops.card_templates()


@_tool()
def card_new(
    path: str,
    name: str,
    template: str,
    slots: dict[str, Any],
    width: int | None = None,
    height: int | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Make a card from a template: fill its slots, write the SVG, render it.

    `name` is the `<name>` in `card:<name>` — the key a cue points at. Both
    the SVG source and the PNG are written under the project's
    `assets/cards/`, so the card can be re-edited later and re-rendered with
    card_render rather than redrawn.

    A slot value is text. A newline inside one is a line break wherever the
    template accepts multiple lines; nothing wraps automatically, because a
    guessed wrap overflows the frame without saying so. Ratings are numbers
    out of five, to the nearest half.

    **Leave `width`/`height` unset unless you mean something other than this
    film.** They default to the project's own canvas, which is what stops a
    card from pillarboxing inside the frame it was made for; naming a size
    that is not the project's is how a card loses a quarter of its width to
    black bar. Given at all, both must be.

    Refused if a card of this name exists, unless `overwrite` — a cue may
    already point at it. Read `font_warnings` in the result: a template
    naming a face this machine lacks still renders, in a substitute, with
    nothing else to say so.
    """
    return ops.card_new(
        path, name, template, slots, width=width, height=height, overwrite=overwrite
    )


@_tool()
def card_render(
    path: str, name: str, width: int | None = None, height: int | None = None
) -> dict[str, Any]:
    """Rasterise `assets/cards/<name>.svg` into the PNG `card:<name>` shows.

    Author the SVG under the project's `assets/cards/`, then render it here;
    both files are kept, so a card can be re-edited rather than redrawn. The
    PNG is what a `card:` cue resolves to, so a card is not usable until this
    has run.

    `width`/`height` are given together or not at all and set the *render*
    size — the document is drawn at that scale rather than rasterised and
    resampled — and they fit rather than distort, so a size at a different
    aspect from the document's comes back smaller on one axis. Omitted, the
    document renders at its own declared size.

    Every call reports the fonts the document names and what fontconfig will
    actually draw. Read `font_warnings`: a card naming a face this machine
    lacks renders pixel-identically to one naming a face it has, so nothing
    downstream can catch the substitution.
    """
    return ops.card_render(path, name, width=width, height=height)


@_tool()
def cue_add(path: str, clip_id: str, word_index: int, asset: str) -> dict[str, Any]:
    """Add a picture cue: from `word_index` of `clip_id` onward, show `asset`.

    Source-addressed like a word range — `asset` is an opaque key or path,
    not checked against disk here; `build_shots` resolves it, the same way
    assemble_scream.py's CUES table did by hand. Refused if a cue already
    sits at that exact word; cue_rm it first to replace it. Echoes the
    resolved word plus three either side, the same convention every
    word-indexed tool follows.
    """
    return ops.cue_add(path, clip_id, word_index, asset)


@_tool()
def cue_rm(path: str, clip_id: str, word_index: int) -> dict[str, Any]:
    """Remove the cue at `clip_id` word `word_index`."""
    return ops.cue_rm(path, clip_id, word_index)


@_tool()
def cue_ls(path: str, clip_id: str | None = None) -> dict[str, Any]:
    """List the picture cue table, each entry echoed with its resolved word.

    Read-only. Omit `clip_id` to see every clip's cues. Ordered by
    `(clip_id, word_index)`, not by resolved timeline position — that needs
    the edit's surviving ranges, which is `build_shots`'s job.
    """
    return ops.cue_ls(path, clip_id=clip_id)


@_tool()
def build_shots(path: str, fps: float | None = None) -> dict[str, Any]:
    """Project the cue table into contiguous shots over the current edit.

    Maps each cue's word through the edit's surviving ranges to a timeline
    frame, resolves its `asset` to a checked path (`card:name` under
    `assets/cards/`, else a registered video clip_id), and runs each shot to
    the next cue — the last to the edit's own frame total. Refuses if a
    cue's word was cut from the edit; fix it with cue_rm/cue_add first.

    `fps` picks the frame grid; it defaults to the project's timebase, which
    for an audio-only project is milliseconds rather than frames. Pass the
    rate `export` will use to see the frames the export actually cuts at.
    """
    return ops.build_shots(path, fps=fps)


@_tool()
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


@_tool()
def cut_by_transcript(
    path: str,
    clip_id: str,
    cut: Sequence[Sequence[int]] | None = None,
    keep: Sequence[Sequence[int]] | None = None,
    pad: float = 0.0,
    confirm_suspect: bool = False,
    through_pause: bool = False,
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

    `through_pause=True` (cut only) extends each range's trailing edge through
    the pause after its last word, whenever that gap is wide enough to have
    drawn a `[N.Ns]` marker in the transcript pane — so cutting a phrase also
    removes the dead air after it instead of leaving it playing. A no-op when
    the trailing gap is too short to have drawn a marker.

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
        through_pause=through_pause,
        plan=plan,
    )


@_tool()
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


@_tool()
def restore(
    path: str,
    clip_id: str,
    ranges: Sequence[Sequence[int]],
    pad: float = 0.0,
    plan: bool = False,
) -> dict[str, Any]:
    """Un-cut whichever part of these inclusive word ranges is not currently in the timeline.

    Same range shape as cut_by_transcript's cut=/keep=. Each range resolves to
    source time exactly like a cut does; only the part Edit.gaps says is
    actually absent comes back — material still present in the request is left
    alone, a request spanning two separate cuts restores both as separate
    pieces, a request only touching part of one cut restores only that part.
    Restoring only ever brings back material the source recording already has
    (bounded by the clip's own registered duration), so the timeline stays a
    subset of the source throughout — this is not vo_extend (PLAN.md parks that
    separately), which would add material the source never had.

    pad matches cut_by_transcript's own pad: pass the same value used on the
    original cut to bring back its padding sliver, not just the words.

    Unlike a cut, there is no suspect-duration refusal — a boundary that looks
    like it swallowed a retake is exactly the kind of thing restore exists to
    bring back, not a mistake to guard against.

    Refused if clip_id has no surviving segment anywhere in the edit (nothing
    left of it to splice the range next to — undo or re-seed instead), or if
    its segments are not contiguous in the edit (an interleaved multi-source
    timeline, which restore does not support yet).

    plan=True resolves and reports without writing, identically to
    cut_by_transcript.
    """
    return ops.restore(path, clip_id, ranges, pad=pad, plan=plan)


@_tool()
def locate(
    path: str,
    clip_id: str,
    first: int | None = None,
    last: int | None = None,
    source_start: float | None = None,
    source_end: float | None = None,
) -> dict[str, Any]:
    """Where does a SOURCE word or SOURCE time play in the current render?

    cut_by_time's read-only mirror, and the tool to reach for before quoting
    any timestamp to a human: word indices and transcript times address the
    original recording, so they are NOT render times and every accumulated cut
    moves them further apart.

    Address it one way per call — `first`/`last` are inclusive word indices
    (`last` defaults to `first`), `source_start`/`source_end` are seconds into
    the recording (omit `source_end` to locate an instant).

    Read `present` first. False means the material is not in the render, and
    `beyond_source` distinguishes "you cut it" from "the recording never went
    that far". A partially-cut range is normal: `placements` lists each
    surviving piece in playback order with the source coordinates saying which
    part of the phrase it is, `covered` how much survives, and `contiguous`
    whether the survivors still play back-to-back. Word mode echoes the
    resolved words plus three either side; time mode echoes the words the
    interval overlaps, or its nearest neighbours if it landed in silence.
    Read-only: nothing is written.
    """
    return ops.locate(
        path,
        clip_id,
        first=first,
        last=last,
        source_start=source_start,
        source_end=source_end,
    )


@_tool()
def timeline_status(path: str) -> dict[str, Any]:
    """Report the current timeline: duration, segment count, undo depth."""
    return ops.status(path)


@_tool()
def timeline_view(path: str, clip_id: str | None = None) -> dict[str, Any]:
    """The whole edit at once: segments, cut seams, and every word's fate.

    timeline_status counts things; this says what they are. Each segment
    carries both coordinate systems (source in, timeline out), each seam is
    named by the surviving words either side of it rather than by the second
    it currently sits at, and each word reports whether it survived, how much
    of it did, and where it now plays.

    Survival is an overlap test, so a word a cut split reports present with
    `partial` set — that is normal on whisper timings, not a defect. Words
    with a suspect duration carry the same flag attach_transcript reported.

    This is locate asked once for the whole clip instead of once per range,
    and it is what the `lucid web` view draws. Read-only.

    `shots` is the picture lane the cue table projects — null when there are no
    cues, and null with a `shots_error` message when the plan refuses (a cue
    that was cut, or a shot longer than the asset it points at). The refusal is
    reported here rather than raised, because this is the view a person uses to
    find the cue to fix. `shots_rate` is the frame grid it was quantised on,
    which is export's rate and not `timebase`.
    """
    return ops.timeline_view(path, clip_id=clip_id)


@_tool()
def undo(path: str) -> dict[str, Any]:
    """Roll the timeline back to the state before the last mutation."""
    return ops.undo(path)


@_tool()
def export(
    path: str,
    output: str,
    export_format: str | None = "kdenlive",
    fps: float | None = None,
    preset: str | None = None,
    resolution: Sequence[int] | None = None,
) -> dict[str, Any]:
    """Export the timeline, or render it.

    "kdenlive" writes an MLT project that Kdenlive opens and melt renders —
    the handoff that works on Linux. Pass export_format=null to render media
    instead. Other auto-editor targets (shotcut, premiere, resolve, final-cut-pro)
    pass straight through.

    A **multi-source** timeline — one with a cue table, or with two clips on
    it — is written by lucid itself as MLT ("kdenlive" or "mlt") and rendered
    by melt, because auto-editor refuses to export a second source and renders
    it at 720x576 while exiting 0. The reply says which writer ran
    ("auto-editor", "mlt" or "melt"), and a melt render reports the resolution
    and frame count measured off the finished file rather than melt's exit code.

    `fps` sets the NLE timeline's frame rate; it defaults to the picture's rate,
    or 30 for an audio-only project. It sets the render's frame rate too on the
    multi-source path, where lucid owns the profile; it is ignored when
    auto-editor renders a single-source timeline.

    `preset` is one of "youtube", "web", or "custom" (which requires
    `resolution`) — a named quality bundle, only meaningful together with
    `export_format=null` (an NLE project file has no bitrate). `resolution`
    is `[width, height]`; it **letterboxes** the existing frame on the
    single-source render path — it does not crop or reframe it — and is
    refused outright on a multi-source (melt) project, where widening the
    hardcoded consumer to accept it has not been re-proven memory-safe
    (HISTORY.md § 4). There is deliberately no "tiktok-reels" preset: a real
    9:16 reframe is DAYDREAM.md § Aspect swap, a separately deferred item.
    """
    return ops.export(
        path,
        output,
        export_format=export_format,
        fps=fps,
        preset=preset,
        resolution=tuple(resolution) if resolution is not None else None,
    )


@_tool()
def add_captions(
    path: str,
    output: str,
    clip_id: str | None = None,
    preset: str | None = None,
    max_words: int | None = None,
    max_gap: float | None = None,
    max_duration: float | None = None,
    hold: float | None = None,
    burn: str | None = None,
    burn_output: str | None = None,
) -> dict[str, Any]:
    """Write word-timed ASS captions for the current timeline to `output`.

    Timings follow the *timeline*, not the original recording, so captions stay
    correct after cuts; words that were cut are omitted and counted as
    `words_cut`.

    The look comes from the project — set it with caption_style, see it with
    caption_view. The arguments here override it for this one file and are not
    written back, so regenerating after a cut is styled the project's way
    again. Leave them unset unless you specifically want a one-off.

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


@_tool()
def caption_view(path: str, clip_id: str | None = None) -> dict[str, Any]:
    """The captions this timeline would produce, and the style in force.

    add_captions without writing a file: the same cues, in timeline seconds,
    already grouped by the project's own break rules — so this is how to check
    a restyle, or read back what a caption actually says at some moment,
    before committing a file to it.

    Reports rather than refuses: a project with no transcript, or one whose
    every word has been cut, comes back with an empty `cues` and a
    `cues_error` saying which. Read-only.
    """
    return ops.caption_view(path, clip_id=clip_id)


@_tool()
def caption_style(
    path: str,
    preset: str | None = None,
    font: str | None = None,
    size: int | None = None,
    text: str | None = None,
    highlight: str | None = None,
    outline_colour: str | None = None,
    box_colour: str | None = None,
    bold: bool | None = None,
    box: bool | None = None,
    outline_width: float | None = None,
    shadow: float | None = None,
    position: str | None = None,
    margin: int | None = None,
    karaoke: bool | None = None,
    max_words: int | None = None,
    max_gap: float | None = None,
    max_duration: float | None = None,
    hold: float | None = None,
    reset: bool = False,
    plan: bool = False,
) -> dict[str, Any]:
    """Read or change the caption look this project keeps.

    The style is project state and the captions are derived from it, so a
    restyle survives every later cut: regenerating re-reads this. Call it with
    no arguments to read the current look and learn the field names; any
    argument sets that field and leaves the others alone. `reset` drops every
    override first — `reset` plus `preset` starts clean from a preset.

    `preset` is the base look ("clean", "karaoke" for per-word highlight, or
    "boxed"); everything else overrides one of its fields, and only the
    overrides are stored.

    Colours take "#rrggbb", "#rrggbbaa", a name ("yellow", "white", "red", …)
    or an ASS "&H…" value. `text` is the word's colour and `highlight` what it
    turns as it is spoken, which only shows with karaoke on. `position` is
    named: "bottom", "top", "top-right", and so on. Both come back resolved,
    because ASS quotes colours backwards and alpha-inverted.

    `plan` validates and resolves without writing. Use caption_view to see the
    result on the actual timeline.
    """
    return ops.caption_style(
        path,
        preset=preset,
        font=font,
        size=size,
        text=text,
        highlight=highlight,
        outline_colour=outline_colour,
        box_colour=box_colour,
        bold=bold,
        box=box,
        outline_width=outline_width,
        shadow=shadow,
        position=position,
        margin=margin,
        karaoke=karaoke,
        max_words=max_words,
        max_gap=max_gap,
        max_duration=max_duration,
        hold=hold,
        reset=reset,
        plan=plan,
    )


@_tool()
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


@_tool()
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


@_tool()
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


@_tool()
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


@_tool()
def speech_overlap(
    path: str,
    clip_id: str,
    at: float = 0.0,
    clip_in: float | None = None,
    clip_out: float | None = None,
    vo_clip_id: str | None = None,
    max_gap: float = 0.3,
    min_seam: float = 0.5,
    cap: float = energy.CAP,
) -> dict[str, Any]:
    """Does a proposed placement of `clip_id` overlap the VO's speech?

    The prerequisite check behind "can this clip speak here?" — answer it
    before designing any ducking. `at`/`clip_in`/`clip_out` describe where
    `clip_id` would sit on the timeline (defaults: unplaced at 0, its whole
    duration) — the clip need not be on the timeline yet, and usually isn't,
    since the current model is single-track. VO's own words map through the
    existing edit (`Edit.timeline_span`); `clip_id`'s map by offsetting into
    the proposed window instead. Both sides are trimmed with
    `energy.believable` first — an inflated word duration can hide a real
    seam — then merged into speech runs with `max_gap` tolerance, since a
    0.05s gap is not a usable seam.

    Read `overlaps` first: any entry means placing `clip_id` there would step
    on VO speech, not empty air — this caught exactly that on Billy/Stu,
    where the clip's speech nearly fully covered a VO thesis line with no
    clean seam to duck into. `clean_seams` (>= `min_seam` wide) are the
    windows where `clip_id` could speak without touching the VO. Read-only —
    nothing is written, and there is no `plan=`.
    """
    return ops.speech_overlap(
        path,
        clip_id,
        at=at,
        clip_in=clip_in,
        clip_out=clip_out,
        vo_clip_id=vo_clip_id,
        max_gap=max_gap,
        min_seam=min_seam,
        cap=cap,
    )


@_tool()
def attenuate_noises(
    path: str,
    clip_id: str,
    db: float = -12.0,
    max_event_seconds: float = 1.5,
    max_gap_seconds: float = 2.0,
    pad: float = 0.05,
    confirm_suspect: bool = False,
    plan: bool = False,
) -> dict[str, Any]:
    """Pull down short loud non-speech events instead of cutting them out.

    An event only qualifies automatically when it is both short
    (max_event_seconds) and sitting in a word-map gap narrow enough to prove
    the map is dense around it (max_gap_seconds) — a wide gap disqualifies
    even a very short event, which is the false-positive class this exists
    to prevent (speech sitting in a hole the transcript never wrote down).
    Qualifying events are pulled down `db` via one ffmpeg pass, never cut,
    and written as a new derived copy that `media_path()` picks up
    automatically everywhere downstream; the original is always what a
    re-run reads from, so repeated calls never compound gain.

    Unlike cut_by_transcript/cut_by_time, nothing here ever raises on what
    the scan finds — this is an automatic multi-candidate scan, not a
    handful of explicit ranges, so withholding is done per event rather than
    refusing the whole call. `suspect_neighbours` (a bounding word itself
    has a suspect duration — withheld unless confirm_suspect=True or
    plan=True) and `disqualified` (too long, or too wide a gap — never
    written, no override) are always reported in full, not only under
    plan=True.
    """
    return ops.attenuate_noises(
        path,
        clip_id,
        db=db,
        max_event_seconds=max_event_seconds,
        max_gap_seconds=max_gap_seconds,
        pad=pad,
        confirm_suspect=confirm_suspect,
        plan=plan,
    )


def serve(root: str | Path | None = None) -> None:
    """Run the server on stdio. Blocks until the client disconnects.

    `root` binds every tool's `path` to one project (`_confine`). It is
    checked here rather than on first use because a bad root would otherwise
    surface as a refusal on every call, blaming the argument the client sent
    instead of the directory the server was started with. Existence is all
    that is checked: `init` under a bound root is legitimate, so requiring
    the root to already be a lucid project would refuse a real workflow.
    """
    global _BOUND_ROOT
    if root is not None:
        resolved = Path(root).resolve()
        if not resolved.is_dir():
            raise ProjectError(f"cannot bind the MCP server to {root!r}: not a directory")
        _BOUND_ROOT = resolved
    mcp.run(transport="stdio")
