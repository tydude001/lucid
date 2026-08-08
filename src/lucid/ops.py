"""Project operations — the single implementation behind both front ends.

Every MCP tool and every `lucid` CLI subcommand is a thin wrapper over a
function here. That is what keeps the two in parity without duplicating logic,
and it is why the CLI is a debugging surface rather than a second codebase
(CLAUDE.md).

Each function returns a plain dict: MCP wants structured returns, and the CLI
wants something to print as JSON.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from itertools import pairwise
from pathlib import Path
from typing import Any

from lucid import asr, autoeditor, captions, energy, media, picture
from lucid import timeline as tl
from lucid import transcript as tx

# `verify` is also the name of the op below, so the module needs an alias here
# or the function would shadow it at call time.
from lucid import verify as vfy
from lucid.project import Project, ProjectError

WordRange = tuple[int, int]


def _clips_by_id(project: Project) -> dict[str, dict[str, Any]]:
    return {c["clip_id"]: c for c in project.read_manifest().get("clips", [])}


def _rate(project: Project) -> float:
    manifest = project.read_manifest()
    if "timebase" in manifest:
        return float(manifest["timebase"])
    clips = manifest.get("clips", [])
    fps = next((c["fps"] for c in clips if c.get("has_video") and c.get("fps")), None)
    return float(fps) if fps else float(autoeditor.AUDIO_TIMEBASE)


def _load_edit(project: Project) -> tl.Edit:
    if not project.timeline_path.exists():
        raise ProjectError(
            "this project has no timeline yet — run `lucid seed <clip_id>` "
            "(or the seed_timeline tool) to lay the source down first"
        )
    return tl.read(project.timeline_path)


def _save_edit(project: Project, edit: tl.Edit) -> None:
    """Snapshot, then write. Order matters: the snapshot is of the *old* state."""
    project.snapshot()
    otio = tl.to_otio(edit, _clips_by_id(project), rate=_rate(project), name=project.root.name)
    tl.write(otio, project.timeline_path)


# -- setup ---------------------------------------------------------------


def init(path: Path | str, *, name: str | None = None) -> dict[str, Any]:
    project = Project.create(path, name=name)
    return {"project": str(project.root), "manifest": project.read_manifest()}


def import_media(
    path: Path | str, source: Path | str, *, clip_id: str | None = None, copy: bool = False
) -> dict[str, Any]:
    project = Project.open(path)
    return media.import_media(project, source, clip_id=clip_id, copy=copy)


def _near_duplicates(parsed: tx.Transcript) -> list[dict[str, Any]]:
    """Flag adjacent near-duplicate phrases in a just-attached transcript.

    Called from both attach paths. The retake `verify` structurally cannot
    catch is one the timeline keeps both takes of, so there is nothing to diff
    against. Catching it means looking at attach time, before an edit exists.
    PLAN.md § Adjacent near-duplicate phrases at `attach-transcript`.
    """
    return vfy.find_adjacent_repeats(vfy.tokens(w.text for w in parsed.words))


def _suspect_durations(parsed: tx.Transcript) -> list[dict[str, Any]]:
    """Flag words whose claimed duration is a lie about something.

    `energy.believable` already computes this same 3x-median cutoff to mask
    audio for `verify --windowed`'s envelope pass — this just surfaces it as a
    finding at attach time, before it is ever used as a cut boundary
    (`cut_by_transcript` refuses those without confirmation).
    PLAN.md § Suspect word durations at `attach-transcript`.
    """
    spans = [(w.start, w.end) for w in parsed.words]
    flagged = energy.suspect_durations(spans)
    for item in flagged:
        item["text"] = parsed.words[item["index"]].text
    return flagged


def attach_transcript(
    path: Path | str, clip_id: str, transcript_path: Path | str
) -> dict[str, Any]:
    """Ingest an existing word-timed transcript instead of re-running ASR.

    Recordings often already have one — the Scream VO was transcribed before
    lucid existed. Re-transcribing to get an index lucid could have read is
    wasted GPU time and a second set of timings to disagree with.
    """
    project = Project.open(path)
    clip = media.get_clip(project, clip_id)
    parsed = tx.load(transcript_path, clip_id=clip["clip_id"])
    tx.save(parsed, project.transcript_path(clip_id))
    return {
        "clip_id": clip_id,
        "words": len(parsed),
        "language": parsed.language,
        "cached": str(project.transcript_path(clip_id)),
        "duration": parsed.words[-1].end,
        "near_duplicates": _near_duplicates(parsed),
        "suspect_durations": _suspect_durations(parsed),
    }


def transcribe(
    path: Path | str,
    clip_id: str,
    *,
    model: str = asr.DEFAULT_MODEL,
    language: str | None = None,
) -> dict[str, Any]:
    """Transcribe a clip's own media with whisper and attach the result.

    `attach_transcript`'s ASR-driven sibling: use that when the recording
    already has a transcript (common — the Scream VO was transcribed before
    lucid existed), use this when it doesn't and whisper has to make one.
    """
    project = Project.open(path)
    clip = media.get_clip(project, clip_id)
    source = media.media_path(project, clip)
    payload = asr.transcribe(source, model=model, language=language)
    # Whisper returns an empty `segments` list rather than failing when it
    # hears no speech, and parse_whisper would then blame the missing word
    # timestamps — which were requested. Say what actually happened (verify
    # hits the same case transcribing a render).
    if not payload.get("words") and not payload.get("segments"):
        raise asr.ASRError(
            f"whisper heard no speech at all in {source.name}. Either this "
            "clip has no dialogue on it, or the wrong clip was transcribed."
        )
    parsed = tx.parse_whisper(payload, clip_id=clip_id, origin=f"whisper:{model}")
    tx.save(parsed, project.transcript_path(clip_id))
    return {
        "clip_id": clip_id,
        "words": len(parsed),
        "language": parsed.language,
        "cached": str(project.transcript_path(clip_id)),
        "duration": parsed.words[-1].end,
        "near_duplicates": _near_duplicates(parsed),
        "suspect_durations": _suspect_durations(parsed),
    }


def _transcript(project: Project, clip_id: str) -> tx.Transcript:
    cached = project.transcript_path(clip_id)
    if not cached.exists():
        raise tx.TranscriptError(
            f"no transcript for {clip_id!r} — attach one with "
            f"`lucid transcript attach {clip_id} <whisper.json>`"
        )
    return tx.load(cached, clip_id=clip_id)


def get_transcript(
    path: Path | str,
    clip_id: str,
    *,
    first: int | None = None,
    last: int | None = None,
    search: str | None = None,
) -> dict[str, Any]:
    """Read the transcript: a window of it, or the hits for a phrase."""
    project = Project.open(path)
    parsed = _transcript(project, clip_id)

    if search is not None:
        return {"clip_id": clip_id, "search": search, "matches": parsed.find(search)}

    lo = 0 if first is None else first
    hi = (len(parsed) - 1) if last is None else last
    words = parsed.window(lo, hi)
    return {
        "clip_id": clip_id,
        "total_words": len(parsed),
        "first_word": lo,
        "last_word": min(hi, len(parsed) - 1),
        "text": " ".join(w.text for w in words),
        "words": [w.as_dict() for w in words],
    }


# -- timeline ------------------------------------------------------------


def seed_timeline(
    path: Path | str,
    clip_id: str,
    *,
    remove_silences: bool = True,
    threshold: float = 0.04,
    margin: str | None = None,
    edit_expr: str | None = None,
) -> dict[str, Any]:
    """Lay a clip down as the timeline, optionally silence-cut on the way in.

    Silence detection is auto-editor's, not lucid's — shell out rather than
    reimplement (PLAN.md scope rule).
    """
    project = Project.open(path)
    clip = media.get_clip(project, clip_id)
    source = media.media_path(project, clip)

    if remove_silences:
        edit = autoeditor.silence_edit(
            source, clip_id, threshold=threshold, margin=margin, edit_expr=edit_expr
        )
    else:
        edit = tl.Edit([tl.Segment(clip_id=clip_id, start=0.0, end=float(clip["duration"]))])

    manifest = project.read_manifest()
    manifest.setdefault(
        "timebase",
        float(clip["fps"]) if clip.get("has_video") and clip.get("fps") else autoeditor.AUDIO_TIMEBASE,
    )
    project.write_manifest(manifest)

    _save_edit(project, edit)
    return {
        "clip_id": clip_id,
        "segments": len(edit.segments),
        "source_duration": float(clip["duration"]),
        "timeline_duration": edit.duration,
        "silences_removed": remove_silences,
    }


def status(path: Path | str) -> dict[str, Any]:
    project = Project.open(path)
    edit = _load_edit(project)
    return {
        "project": str(project.root),
        "timeline_duration": edit.duration,
        "segments": len(edit.segments),
        "undo_depth": len(project.snapshots()),
        "clips": [c["clip_id"] for c in project.read_manifest().get("clips", [])],
    }


def _resolve(parsed: tx.Transcript, ranges: Iterable[Sequence[int]]) -> list[tuple[float, float]]:
    resolved = []
    for item in ranges:
        if len(item) != 2:
            raise tx.TranscriptError(f"word range {item!r} must be [first, last]")
        resolved.append(parsed.span(int(item[0]), int(item[1])))
    return resolved


#: Words shown either side of a resolved range. The defect this echo exists to
#: catch is an index one word past the intended phrase (DOGFOOD.md § 3), and
#: resolved text alone cannot show that — "the words I meant, plus one" reads
#: perfectly well on its own. It only looks wrong next to where the phrase
#: should have ended, so the neighbours travel with every echo.
CONTEXT_WORDS = 3


def _context(parsed: tx.Transcript, first: int, last: int) -> dict[str, Any]:
    """The words just outside a range, kept separate from the ones inside it."""
    before = parsed.window(max(0, first - CONTEXT_WORDS), max(0, first - 1))
    after = parsed.window(min(len(parsed) - 1, last + 1), last + CONTEXT_WORDS)
    return {
        "context_before": [{"index": w.index, "text": w.text} for w in before if w.index < first],
        "context_after": [{"index": w.index, "text": w.text} for w in after if w.index > last],
    }


def _pad_reach(
    parsed: tx.Transcript, first: int, last: int, lo: float, hi: float
) -> list[dict[str, Any]]:
    """Words outside `first`..`last` that the padded span nonetheless touches.

    `pad` widens a cut in *seconds*, so the echoed text — which is the words
    themselves — understates what the cut removes whenever the padding reaches
    into a neighbour. That disagreement between the number and the words is
    the same class of error the echo exists to prevent, so name the words the
    padding actually eats.

    Overlap, never containment (CLAUDE.md): a neighbour half-swallowed by the
    padding is exactly the case worth reporting, and containment would miss it.
    """
    reached = []
    for word in parsed.words:
        if first <= word.index <= last:
            continue
        if word.start < hi and word.end > lo:
            reached.append(
                {
                    "index": word.index,
                    "text": word.text,
                    "side": "before" if word.index < first else "after",
                }
            )
    return reached


def _echo(
    parsed: tx.Transcript, first: int, last: int, lo: float, hi: float
) -> dict[str, Any]:
    """What a word range resolved to, in words rather than indices."""
    start, end = parsed.span(first, last)
    echo: dict[str, Any] = {
        "first_word": first,
        "last_word": last,
        "text": " ".join(w.text for w in parsed.window(first, last)),
        # The range's own edges, before padding — so the pair below can be
        # compared against `source_start`/`source_end` to see what pad did.
        "word_start": start,
        "word_end": end,
        **_context(parsed, first, last),
    }
    reach = _pad_reach(parsed, first, last, lo, hi)
    if reach:
        echo["pad_reach"] = reach
    return echo


def cut_by_transcript(
    path: Path | str,
    clip_id: str,
    *,
    cut: Sequence[Sequence[int]] | None = None,
    keep: Sequence[Sequence[int]] | None = None,
    pad: float = 0.0,
    confirm_suspect: bool = False,
    plan: bool = False,
) -> dict[str, Any]:
    """Cut or keep word ranges — the operation lucid exists for.

    Ranges are inclusive word indices into the clip's transcript, resolved to
    source time and applied to the accumulated timeline. `pad` widens each cut
    on both sides, which is how you reach the silence *between* words instead
    of clipping the consonant at the edge.

    Exactly one of `cut` or `keep` is accepted: a call that meant "keep" but
    was read as "cut" would produce the precise inverse of the intended edit,
    so there is no default.

    A range whose first or last word claims a suspect duration
    (PLAN.md § Suspect word durations) is refused unless `confirm_suspect=True`: that word's `start`/`end`
    is what the cut boundary resolves to, and a boundary that long is usually
    hiding a retake rather than ending where it claims.

    `plan=True` resolves everything and returns the same payload without
    writing: no snapshot, no timeline mutation. It runs the identical code path
    — the edit is mutated in memory and simply never saved — so the numbers it
    reports are the real ones, not a second implementation's guess at them.
    Six cues in the Scream shot plan pointed one word past the intended phrase
    and were caught exactly this way (DOGFOOD.md § 3). Planning also *reports*
    suspect boundaries rather than refusing them: looking is the thing you do
    before deciding, so refusing to look would be backwards.
    """
    if bool(cut) == bool(keep):
        raise tx.TranscriptError("pass exactly one of cut= or keep=")

    project = Project.open(path)
    media.get_clip(project, clip_id)
    parsed = _transcript(project, clip_id)
    edit = _load_edit(project)
    before = edit.duration

    suspect = {item["index"]: item for item in _suspect_durations(parsed)}
    flagged: list[dict[str, Any]] = []
    for first, last in cut or keep or []:
        hit = suspect.get(int(first)) or suspect.get(int(last))
        if not hit:
            continue
        flagged.append({**hit, "range": [int(first), int(last)]})
        if plan or confirm_suspect:
            continue
        raise tx.TranscriptError(
            f"word {hit['index']} ({hit['text']!r}) claims {hit['duration']}s, "
            f"more than {hit['limit']}s (the transcript's median x "
            f"energy.CAP) — it likely hides a retake rather than ending "
            "where it claims, so it is refused as a cut boundary "
            "(PLAN.md \u00a7 Suspect word durations). Check it, then retry "
            "with confirm_suspect=True (CLI: --confirm-suspect) if the "
            "boundary is actually fine, or pick a different word."
        )

    applied: list[dict[str, Any]] = []
    if cut:
        for (first, last), (start, end) in zip(cut, _resolve(parsed, cut)):
            lo, hi = max(0.0, start - pad), end + pad
            present = edit.covers(clip_id, lo, hi)
            touched = edit.remove(clip_id, lo, hi)
            applied.append(
                {
                    **_echo(parsed, int(first), int(last), lo, hi),
                    "source_start": lo,
                    "source_end": hi,
                    "segments_touched": touched,
                    "already_cut": present <= 0.0,
                }
            )
    else:
        intervals = [
            (max(0.0, s - pad), e + pad) for s, e in _resolve(parsed, keep or [])
        ]
        edit.keep_only(clip_id, intervals)
        for (first, last), (start, end) in zip(keep or [], intervals):
            applied.append(
                {
                    **_echo(parsed, int(first), int(last), start, end),
                    "source_start": start,
                    "source_end": end,
                }
            )

    if not plan:
        _save_edit(project, edit)
    result = {
        "clip_id": clip_id,
        "mode": "cut" if cut else "keep",
        "applied": applied,
        "duration_before": before,
        "duration_after": edit.duration,
        "removed": before - edit.duration,
        "segments": len(edit.segments),
    }
    if plan:
        result["plan"] = True
        result["suspect_boundaries"] = flagged
    return result


def _reject_overlapping_spans(requests: Sequence[tuple[float, float]]) -> None:
    """Refuse a same-call span overlap rather than resolve and apply it twice.

    Every span resolves against the pre-cut timeline before any is applied
    (so a list of notes from one watch stays valid together), which is
    exactly what makes an overlap between two spans in one call unsafe to
    just apply in order: it is almost certainly one flub logged twice, not a
    thing to merge (`vo_trim.py`'s own choice).
    """
    ordered = sorted(requests)
    for (a_start, a_end), (b_start, b_end) in pairwise(ordered):
        if b_start < a_end:
            raise tl.TimelineError(
                f"spans {a_start:.3f}-{a_end:.3f} and {b_start:.3f}-{b_end:.3f} "
                "overlap in this call — resolve the overlap before cutting, "
                "since applying one would shift the timeline the other addresses"
            )


def _overlap_words(parsed: tx.Transcript, lo: float, hi: float) -> list[dict[str, Any]]:
    """Words a `[lo, hi)` render-time-derived span overlaps.

    Unlike `_pad_reach`, there is no known first/last word to stay relative
    to here, so this walks the whole transcript. Overlap, never containment
    (CLAUDE.md): a word half inside the span still counts.
    """
    return [
        {"index": w.index, "text": w.text, "start": w.start, "end": w.end}
        for w in parsed.words
        if w.start < hi and w.end > lo
    ]


def _nearest_context(parsed: tx.Transcript, lo: float, hi: float) -> dict[str, Any]:
    """Flanking words for a span that landed entirely in silence.

    Treats the silence gap as though it were the (empty) resolved range
    between the nearest word ending at/before `lo` and the nearest one
    starting at/after `hi`, so `_context` can be reused unmodified rather
    than reporting no context at all for a legitimate "cut some dead air" span.
    """
    before_idx = -1
    for word in parsed.words:
        if word.end <= lo:
            before_idx = word.index
        else:
            break
    after_idx = len(parsed)
    for word in parsed.words:
        if word.start >= hi:
            after_idx = word.index
            break
    return _context(parsed, before_idx + 1, after_idx - 1)


def cut_by_time(
    path: Path | str,
    *,
    spans: Sequence[Sequence[float]],
    pad: float = 0.0,
    confirm_suspect: bool = False,
    plan: bool = False,
) -> dict[str, Any]:
    """Cut spans of render/timeline time — what a human reports watching an export.

    Each span is `[start, end)` in the seconds the current export plays at,
    not source time and not word indices. Every span is converted to the
    source interval(s) it plays — `Edit.source_spans`, the aggregate inverse
    of the mapping captions and playback use — and cut through the exact same
    `Edit.remove` path `cut_by_transcript` uses. The render timestamp itself
    is never stored: the conversion happens once, here, at call time, so the
    roadmap's core property (every persisted coordinate is source time) holds.

    All spans resolve against the timeline as it stood before any of them was
    applied, so a list of notes taken against one watch stays valid together
    even though a real cut would shift every later timestamp. Overlapping
    spans in one call are refused rather than silently double-applied.

    Every piece a span produced (more than one when it crossed an earlier cut
    or a clip boundary) echoes the words it overlaps there — an overlap test,
    never containment — plus the words either side, reusing `cut_by_transcript`'s
    own echo convention. A span landing entirely in silence still gets its
    nearest flanking words, so there is always something to check the
    timestamp against. A clip with no transcript attached still gets cut;
    `words_overlapped` is null and `transcript_missing` is set instead of
    refusing a valid render-time cut just because a picture-only clip was
    never transcribed.

    `pad` widens only the two true OUTER edges of each requested span, never
    an inner seam the span happened to cross — padding an inner seam would
    reach toward whatever now sits on the far side of a prior cut, which is
    material the caller never named.

    Refused the same way `cut_by_transcript` is if a span overlaps a word with
    a suspect duration (PLAN.md § Suspect word durations), unless
    `confirm_suspect=True` or `plan=True` — under `plan` they are reported as
    `suspect_boundaries` instead.

    `plan=True` runs the identical code path and simply skips the write, same
    as `cut_by_transcript` (PLAN.md § `cut --plan`).
    """
    if not spans:
        raise tl.TimelineError("cut_by_time needs at least one span")
    requests: list[tuple[float, float]] = []
    for item in spans:
        if len(item) != 2:
            raise tl.TimelineError(f"span {item!r} must be [start, end]")
        requests.append((float(item[0]), float(item[1])))
    _reject_overlapping_spans(requests)

    project = Project.open(path)
    edit = _load_edit(project)
    before = edit.duration

    # Resolved against the pre-cut timeline, all at once, before any span is
    # applied — this is what makes a list of notes taken against one watch
    # stay valid together.
    pieces_by_span = [edit.source_spans(start, end) for start, end in requests]

    transcripts: dict[str, tx.Transcript | None] = {}
    suspects: dict[str, dict[int, dict[str, Any]]] = {}
    flagged: list[dict[str, Any]] = []
    span_pieces: list[list[dict[str, Any]]] = []

    for (req_start, req_end), pieces in zip(requests, pieces_by_span):
        built: list[dict[str, Any]] = []
        last_i = len(pieces) - 1
        for i, (clip_id, start, end) in enumerate(pieces):
            lo = max(0.0, start - pad) if i == 0 else start
            hi = end + pad if i == last_i else end

            if clip_id not in transcripts:
                try:
                    transcripts[clip_id] = _transcript(project, clip_id)
                except tx.TranscriptError:
                    transcripts[clip_id] = None
                suspects[clip_id] = (
                    {item["index"]: item for item in _suspect_durations(transcripts[clip_id])}
                    if transcripts[clip_id] is not None
                    else {}
                )
            parsed = transcripts[clip_id]

            if parsed is None:
                built.append(
                    {
                        "clip_id": clip_id,
                        "lo": lo,
                        "hi": hi,
                        "words_overlapped": None,
                        "transcript_missing": True,
                        "context_before": [],
                        "context_after": [],
                    }
                )
                continue

            words = _overlap_words(parsed, lo, hi)
            for word in words:
                hit = suspects[clip_id].get(word["index"])
                if hit:
                    flagged.append({**hit, "clip_id": clip_id, "span": [req_start, req_end]})
            ctx = (
                _context(parsed, words[0]["index"], words[-1]["index"])
                if words
                else _nearest_context(parsed, lo, hi)
            )
            built.append(
                {"clip_id": clip_id, "lo": lo, "hi": hi, "words_overlapped": words, **ctx}
            )
        span_pieces.append(built)

    if flagged and not (plan or confirm_suspect):
        hit = flagged[0]
        raise tl.TimelineError(
            f"word {hit['index']} ({hit['text']!r}) in clip {hit['clip_id']!r} claims "
            f"{hit['duration']}s, more than {hit['limit']}s (the transcript's median x "
            "energy.CAP) — it likely hides a retake rather than ending where it "
            "claims, so it is refused as a cut boundary (PLAN.md § Suspect "
            "word durations). Check it, then retry with confirm_suspect=True "
            "(CLI: --confirm-suspect) if the boundary is actually fine, or pick "
            "a different span."
        )

    applied: list[dict[str, Any]] = []
    for (req_start, req_end), built in zip(requests, span_pieces):
        piece_results: list[dict[str, Any]] = []
        for piece in built:
            clip_id, lo, hi = piece["clip_id"], piece["lo"], piece["hi"]
            present = edit.covers(clip_id, lo, hi)
            touched = edit.remove(clip_id, lo, hi)
            entry = {
                "clip_id": clip_id,
                "source_start": lo,
                "source_end": hi,
                "words_overlapped": piece["words_overlapped"],
                "context_before": piece["context_before"],
                "context_after": piece["context_after"],
                "segments_touched": touched,
                "already_cut": present <= 0.0,
            }
            if piece.get("transcript_missing"):
                entry["transcript_missing"] = True
            piece_results.append(entry)
        applied.append(
            {"requested_start": req_start, "requested_end": req_end, "pieces": piece_results}
        )

    removed = before - edit.duration
    requested_removed = sum(end - start for start, end in requests)
    if pad == 0.0 and abs(removed - requested_removed) > tl.MIN_SEGMENT:
        raise tl.TimelineError(
            f"internal invariant failed: requested {requested_removed:.3f}s "
            f"removed but the timeline shrank by {removed:.3f}s — "
            "source_spans and remove disagree with each other; this should "
            "be unreachable"
        )

    if not plan:
        _save_edit(project, edit)

    result: dict[str, Any] = {
        "mode": "cut",
        "applied": applied,
        "duration_before": before,
        "duration_after": edit.duration,
        "removed": removed,
        "requested_removed": requested_removed,
        "segments": len(edit.segments),
    }
    if plan:
        result["plan"] = True
        result["suspect_boundaries"] = flagged
    return result


def undo(path: Path | str) -> dict[str, Any]:
    project = Project.open(path)
    restored = project.restore()
    edit = _load_edit(project)
    return {
        "restored_from": str(restored),
        "timeline_duration": edit.duration,
        "segments": len(edit.segments),
        "undo_depth": len(project.snapshots()),
    }


# -- getting the edit out ------------------------------------------------


#: Frame rate for NLE exports from an audio-only project. Arbitrary but sane;
#: override with `fps` to match the picture the VO will be cut against.
DEFAULT_EXPORT_FPS = 30.0


def export(
    path: Path | str,
    output: Path | str,
    *,
    export_format: str | None = "kdenlive",
    fps: float | None = None,
) -> dict[str, Any]:
    """Map the timeline to auto-editor v3 and render or export it.

    `export_format="kdenlive"` writes an MLT project — the only handoff that
    actually opens on this box. `export_format=None` renders media instead.

    The two paths deliberately use different timebases. Rendering keeps the
    project's own rate, which for audio is milliseconds. An **NLE export must
    not**: the v3 timebase becomes the MLT `<profile frame_rate_num>`, so a
    millisecond timeline hands Kdenlive a 1000fps project. NLE timelines are
    frame-based, quantising to frames on the way out is what PLAN.md already
    wanted, and cut points land in inter-word silence where a 33ms grid is
    irrelevant.
    """
    project = Project.open(path)
    edit = _load_edit(project)
    if not edit.segments:
        raise ProjectError("the timeline is empty — nothing to export")

    clips = _clips_by_id(project)
    primary = clips[edit.segments[0].clip_id]
    header = autoeditor.template(media.media_path(project, primary))

    if export_format is None:
        timebase = _rate(project)
    else:
        timebase = float(fps) if fps else _export_fps(clips)
    payload = autoeditor.to_v3(edit, clips, header=header, timebase=timebase)

    written = autoeditor.run_timeline(payload, output, export=export_format)
    return {
        "output": str(written),
        "format": export_format or "media",
        "timebase": timebase,
        "segments": len(edit.segments),
        "timeline_duration": edit.duration,
    }


def _transcripts_for(project: Project, clip_id: str | None) -> dict[str, tx.Transcript]:
    """The transcripts to caption from: one named clip, or every cached one."""
    if clip_id is not None:
        media.get_clip(project, clip_id)
        return {clip_id: _transcript(project, clip_id)}

    found: dict[str, tx.Transcript] = {}
    for clip in project.read_manifest().get("clips", []):
        cached = project.transcript_path(clip["clip_id"])
        if cached.exists():
            found[clip["clip_id"]] = tx.load(cached, clip_id=clip["clip_id"])
    if not found:
        raise tx.TranscriptError(
            "no clip in this project has a transcript — attach one with "
            "`lucid attach-transcript <clip_id> <whisper.json>` first"
        )
    return found


def _caption_canvas(project: Project) -> tuple[int, int]:
    """The reference canvas for captions: the picture's shape, not its size."""
    for clip in project.read_manifest().get("clips", []):
        if clip.get("has_video"):
            return captions.canvas(clip.get("width"), clip.get("height"))
    return captions.DEFAULT_RESOLUTION


def add_captions(
    path: Path | str,
    output: Path | str,
    *,
    clip_id: str | None = None,
    preset: str = "clean",
    max_words: int = 7,
    max_gap: float = 0.7,
    max_duration: float = 6.0,
    hold: float = 0.3,
    burn: Path | str | None = None,
    burn_output: Path | str | None = None,
) -> dict[str, Any]:
    """Write word-timed ASS captions for the current timeline.

    Timings are the timeline's, not the recording's: every word is mapped
    through the accumulated edit, and words that have been cut do not appear.
    The count that did is reported as `words_cut`, so a missing sentence can be
    told apart from a bug.

    `burn` renders the captions into a video with ffmpeg. It has to be a render
    of *this* timeline — burning onto the untrimmed source lines the captions up
    against audio that has since moved. The default exit is the sidecar `.ass`,
    which Kdenlive loads and can restyle.
    """
    project = Project.open(path)
    edit = _load_edit(project)
    style = captions.preset(preset)
    transcripts = _transcripts_for(project, clip_id)

    placed, cut = captions.place(edit, transcripts)
    if not placed:
        raise captions.CaptionError(
            "no transcribed word survives on the timeline — nothing to caption"
        )
    cues = captions.group(
        placed, max_words=max_words, max_gap=max_gap, max_duration=max_duration, hold=hold
    )

    destination = Path(output).expanduser()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        captions.to_ass(
            cues,
            style=style,
            resolution=_caption_canvas(project),
            title=project.read_manifest().get("name", "lucid"),
        ),
        encoding="utf-8",
    )

    result: dict[str, Any] = {
        "output": str(destination),
        "preset": preset,
        "clips": sorted(transcripts),
        "cues": len(cues),
        "words": len(placed),
        "words_cut": cut,
        "captioned_duration": cues[-1].end - cues[0].start,
        "timeline_duration": edit.duration,
    }

    if burn is not None:
        source = Path(burn).expanduser()
        target = (
            Path(burn_output).expanduser()
            if burn_output
            else project.render_dir / f"{source.stem}-captioned{source.suffix}"
        )
        result["burned"] = str(captions.burn(source, destination, target))

    return result


def _export_fps(clips: dict[str, dict[str, Any]]) -> float:
    """The picture's frame rate if there is picture, else a sane default."""
    for clip in clips.values():
        if clip.get("has_video") and clip.get("fps"):
            return float(clip["fps"])
    return DEFAULT_EXPORT_FPS


def check_frames(
    path: Path | str, target: Path | str | None = None, *, fps: float | None = None
) -> dict[str, Any]:
    """Count the frames the timeline should run to, and check a target against it.

    The picture-side counterpart to `verify`, which deliberately covers only
    audio. `expected_frames` is what `export` lays down — the same
    `autoeditor.frame_layout` the export itself uses, so the two cannot drift —
    and every segment edge is quantised on its own, which is why this is not
    `round(duration * fps)`.

    With no `target` it reports that number and stops, which is the cheap thing
    to do before an export. With one:

    * an NLE project (`.kdenlive`, `.mlt`, `.xml`) is put to `melt -consumer
      xml`, which resolves the document and says what it *would* render without
      encoding anything. This is the load-bearing check, and it is load-bearing
      because it runs **before** the render: exact agreement here is what made
      68 cut positions on the Scream essay trustworthy (DOGFOOD.md § 3).
    * anything else is treated as a render and counted with ffprobe.

    `fps` must be the rate the export used, or the two sides are counting
    against different grids; it defaults to the same rate `export` would pick.

    An audio-only render has no frames, and that is the ordinary case for a VO
    project rather than a failure: `agrees` comes back null with a note, and the
    NLE project is the thing to point this at instead.
    """
    project = Project.open(path)
    edit = _load_edit(project)
    if not edit.segments:
        raise ProjectError("the timeline is empty — there are no frames to count")

    rate = float(fps) if fps else _export_fps(_clips_by_id(project))
    expected = autoeditor.frame_total(edit, rate)
    result: dict[str, Any] = {
        "fps": rate,
        "segments": len(edit.segments),
        "timeline_duration": edit.duration,
        "expected_frames": expected,
        "expected_duration": expected / rate,
    }
    if target is None:
        return result

    target_path = Path(target).expanduser()
    if not target_path.exists():
        raise picture.PictureError(f"no such file to check: {target_path}")
    result["target"] = str(target_path)
    notes: list[str] = []

    if target_path.suffix.lower() in picture.NLE_SUFFIXES:
        result["target_kind"] = "nle-project"
        counted: int | None = picture.project_frames(target_path)
        result["target_duration"] = counted / rate if counted is not None else None
    else:
        result["target_kind"] = "render"
        counts = media.count_frames(target_path)
        counted = counts["frames"]
        result["target_duration"] = counts["duration"]
        if not counts["has_video"]:
            result.update({"target_frames": None, "delta": None, "agrees": None})
            result["notes"] = [
                (
                    "this render has no video stream, so there are no frames to "
                    "count and the picture-side check does not apply to it. Compare "
                    "`target_duration` against `expected_duration`, and point this "
                    "at the NLE project if you want a frame count for a VO."
                )
            ]
            return result
        # Two ffprobe readings of one file disagreeing is itself the finding.
        container = counts["container_frames"]
        result["container_frames"] = container
        if container is not None and counted is not None and container != counted:
            notes.append(
                f"ffprobe's two counts disagree: {counted} packets against a "
                f"container header claiming {container}. The packet count is "
                "the one compared here; the header is metadata a muxer can get "
                "wrong. Worth knowing before trusting either."
            )

    if counted is None:
        raise picture.PictureError(
            f"could not get a frame count out of {target_path} — it has a video "
            "stream but ffprobe counted no packets in it."
        )

    delta = counted - expected
    result.update({"target_frames": counted, "delta": delta, "agrees": delta == 0})
    if delta == picture.KNOWN_TAIL_FRAME and result["target_kind"] == "nle-project":
        notes.append(picture.TAIL_FRAME_NOTE)
    if notes:
        result["notes"] = notes
    return result


def check_black(
    path: Path | str,
    target: Path | str,
    *,
    fps: float | None = None,
    pix_th: float = 0.10,
    min_duration: float | None = None,
) -> dict[str, Any]:
    """Scan a render for black stretches, and say whether each is explained.

    ffmpeg's `blackdetect` finds every black run in `target`. Each is checked
    against the timeline's own `expected_frames`/`expected_duration`
    (`autoeditor.frame_total`, the same arithmetic `check_frames` already
    trusts) using `media.count_frames`'s packet count rather than a fresh
    probe, so the two checks' delta math cannot drift apart.

    A run is `explained` only when it sits at the tail of the render *and*
    the frame delta between `target` and the timeline is exactly
    `picture.KNOWN_TAIL_FRAME` (picture.py) — the documented auto-editor
    kdenlive-export defect. `check_frames` only ever compares that constant
    against an NLE-project target, because a `-consumer xml` read is the only
    place the tail frame shows up before anything is rendered. **This
    deliberately broadens the same reasoning to a bare render** — the
    trailing frame that defect produces is really encoded, not just
    declared, so it can equally turn up in a finished file, and the point of
    naming the defect is to keep it from being mistaken for a genuine one
    wherever it shows up, not only in the one place it was first caught. A
    run inside the declared picture is never explained regardless of delta —
    position has to match the known defect, not just the count.

    `min_duration` defaults to 0, not the export's half-a-frame grid the rest
    of this module measures against — verified against the installed ffmpeg
    (8.1.2), not assumed: `blackdetect` derives a run's reported duration
    from the *next* frame's timestamp, so every run it ever reports is
    already quantised to whole frames except one specific case — a black run
    that reaches end of stream with no following frame reports
    `black_duration:0` regardless of how many black frames it actually
    contains. That exact case is precisely the trailing kdenlive-export
    frame this function exists to explain, so a positive threshold (which
    would read as "half a frame of slack") would silently make `blackdetect`
    itself drop the one event this check is for. Nothing spurious gets in at
    0 that wouldn't already pass at half a frame: every other run's duration
    is a real multiple of the frame interval, never a fraction of one.
    """
    project = Project.open(path)
    edit = _load_edit(project)
    if not edit.segments:
        raise ProjectError("the timeline is empty — there is no picture to check")

    rate = float(fps) if fps else _export_fps(_clips_by_id(project))
    expected_frames = autoeditor.frame_total(edit, rate)
    expected_duration = expected_frames / rate
    threshold = min_duration if min_duration is not None else 0.0

    target_path = Path(target).expanduser()
    if not target_path.exists():
        raise picture.PictureError(f"no such file to check: {target_path}")

    result: dict[str, Any] = {
        "target": str(target_path),
        "fps": rate,
        "pix_th": pix_th,
        "min_duration": threshold,
        "expected_duration": expected_duration,
        "expected_frames": expected_frames,
    }

    counts = media.count_frames(target_path)
    result["target_duration"] = counts["duration"]
    if not counts["has_video"]:
        result.update({"clean": None, "runs": [], "target_frames": None})
        result["notes"] = [
            (
                "this render has no video stream, so there is no picture to scan "
                "for black. Point this at a real render instead."
            )
        ]
        return result

    if counts["frames"] is None:
        raise picture.PictureError(
            f"could not get a frame count out of {target_path} — it has a video "
            "stream but ffprobe counted no packets in it."
        )

    delta = counts["frames"] - expected_frames
    result["target_frames"] = counts["frames"]
    tail_boundary = expected_duration - 0.5 / rate

    runs = picture.blackdetect(target_path, pix_th=pix_th, min_duration=threshold)
    reported: list[dict[str, Any]] = []
    for run in runs:
        inside = run["start"] < tail_boundary
        explained = not inside and delta == picture.KNOWN_TAIL_FRAME
        entry = {
            "start": run["start"],
            "end": run["end"],
            "duration": run["duration"],
            "inside_expected_picture": inside,
            "explained": explained,
        }
        if explained:
            entry["note"] = picture.TAIL_FRAME_NOTE
        reported.append(entry)

    result["runs"] = reported
    result["clean"] = all(r["explained"] for r in reported)

    notes: list[str] = []
    container = counts["container_frames"]
    if container is not None and container != counts["frames"]:
        notes.append(
            f"ffprobe's two counts disagree: {counts['frames']} packets against "
            f"a container header claiming {container}. The packet count is the "
            "one compared here."
        )
    if notes:
        result["notes"] = notes
    return result


def _nearest_word(parsed: tx.Transcript, t: float) -> dict[str, Any]:
    """The word playing at source time `t`, or the nearest one across a gap.

    Overlap test first (`word.start <= t < word.end`); a sample that lands in
    silence between words falls back to the nearest by edge distance rather
    than reporting nothing. Reuses `_context` either way — this is the
    CLAUDE.md echo convention run in reverse, time-to-word instead of
    word-to-time.
    """
    words = parsed.words
    for w in words:
        if w.start <= t < w.end:
            idx = w.index
            break
    else:
        idx = min(range(len(words)), key=lambda i: min(abs(words[i].start - t), abs(words[i].end - t)))
    return {"word": {"index": words[idx].index, "text": words[idx].text}, **_context(parsed, idx, idx)}


def spot_frames(
    path: Path | str,
    target: Path | str,
    *,
    count: int = 6,
    times: Sequence[float] | None = None,
    fps: float | None = None,
) -> dict[str, Any]:
    """Pull sample frames from a render as PNGs, with luma stats attached.

    `count` evenly-spaced frames (midpoint-sampled, so a sample never lands
    exactly on frame 0 or the last frame) plus any explicit `times`, each
    extracted with `picture.extract_frame` into
    `cache/frames/<render-stem>/` and ranked darkest-first by `YAVG`.

    Word/clip mapping via `Edit.source_at` is attempted only when `target`'s
    own probed duration agrees with the *current* timeline within a frame
    (`mapping_trusted`) — a stale render silently mapping to the wrong words
    would be worse than no mapping at all. When it is not trusted, every
    frame still gets its PNG and stats; only the clip_id/source_time/word
    fields are withheld, and a top-level note points at `check_frames` for
    the stronger check.

    A single bad extraction (a `PictureError` from a seek near a boundary) is
    caught and reported per-frame rather than aborting the whole batch — this
    is an exploratory tool over potentially many samples, and one bad seek
    should not cost the other N-1.
    """
    if count <= 0 and not times:
        raise picture.PictureError(
            "spot_frames needs count > 0 or explicit times — nothing to sample"
        )

    project = Project.open(path)
    edit = _load_edit(project)
    if not edit.segments:
        raise ProjectError("the timeline is empty — there is nothing to sample")

    target_path = Path(target).expanduser()
    if not target_path.exists():
        raise picture.PictureError(f"no such file to sample: {target_path}")

    counts = media.count_frames(target_path)
    target_duration = counts["duration"]
    result: dict[str, Any] = {
        "target": str(target_path),
        "target_duration": target_duration,
        "has_video": counts["has_video"],
    }
    if not counts["has_video"]:
        result.update({"frames": [], "darkest_first": []})
        result["notes"] = ["this render has no video stream, so there are no frames to sample."]
        return result

    if target_duration is None or target_duration <= 0:
        raise picture.PictureError(f"could not read a duration for {target_path}")

    rate = float(fps) if fps else _export_fps(_clips_by_id(project))
    expected_frames = autoeditor.frame_total(edit, rate)
    expected_duration = expected_frames / rate
    half_frame = 0.5 / rate
    mapping_trusted = abs(target_duration - edit.duration) <= half_frame

    notes: list[str] = []
    if not mapping_trusted:
        notes.append(
            f"target_duration ({target_duration:.3f}s) disagrees with the current "
            f"timeline ({edit.duration:.3f}s) by more than a frame at {rate}fps — "
            "this render may be stale, so clip/word mapping is refused. Run "
            "check_frames against it for the stronger check."
        )

    sampled: list[tuple[float, str]] = []
    if count > 0:
        step = target_duration / count
        sampled.extend((step * (i + 0.5), "sampled") for i in range(count))
    for t in times or []:
        sampled.append((float(t), "explicit"))
    sampled.sort(key=lambda item: item[0])

    max_time = max(0.0, target_duration - half_frame)
    transcripts: dict[str, tx.Transcript | None] = {}
    frames_out: list[dict[str, Any]] = []

    for index, (requested, origin) in enumerate(sampled):
        clamped = min(max(requested, 0.0), max_time)
        entry: dict[str, Any] = {"index": index, "time": clamped, "origin": origin}
        if clamped != requested:
            entry["clamped_from"] = requested

        dest = project.frames_dir / target_path.stem / f"{index:02d}_{clamped:.3f}s.png"
        try:
            stats = picture.extract_frame(target_path, clamped, dest)
        except picture.PictureError as exc:
            entry["error"] = str(exc)
            frames_out.append(entry)
            continue

        entry["png"] = str(dest)
        entry.update(stats)

        if mapping_trusted:
            located = edit.source_at(clamped)
            if located is not None:
                clip_id, source_time = located
                entry["clip_id"] = clip_id
                entry["source_time"] = source_time
                if clip_id not in transcripts:
                    try:
                        transcripts[clip_id] = _transcript(project, clip_id)
                    except tx.TranscriptError:
                        transcripts[clip_id] = None
                parsed = transcripts[clip_id]
                if parsed is not None and parsed.words:
                    entry.update(_nearest_word(parsed, source_time))

        frames_out.append(entry)

    darkest_first = sorted(
        (f["index"] for f in frames_out if "YAVG" in f), key=lambda i: frames_out[i]["YAVG"]
    )

    result.update(
        {
            "fps": rate,
            "expected_duration": expected_duration,
            "mapping_trusted": mapping_trusted,
            "frames": frames_out,
            "darkest_first": darkest_first,
        }
    )
    if notes:
        result["notes"] = notes
    return result


# -- checking the render -------------------------------------------------


def _shared_language(transcripts: dict[str, tx.Transcript]) -> str | None:
    """The language every source transcript agrees on, if they agree at all.

    Passing it to whisper stops it language-detecting the render from scratch,
    which it occasionally gets wrong on a short or music-heavy one. Ambiguity
    means letting whisper decide is the safer default.
    """
    languages = {t.language for t in transcripts.values() if t.language}
    return languages.pop() if len(languages) == 1 else None


def verify(
    path: Path | str,
    render: Path | str,
    *,
    clip_id: str | None = None,
    transcript_path: Path | str | None = None,
    model: str | None = None,
    language: str | None = None,
    windowed: bool = False,
    window: float = asr.WINDOW,
    overlap: float = asr.OVERLAP,
) -> dict[str, Any]:
    """Transcribe a finished render and diff it against what the timeline says.

    lucid already knows the words the timeline should play — every clip's
    transcript mapped through the accumulated edit, exactly as captions are
    placed. This transcribes the render itself and compares the two word
    sequences.

    It is the only check that catches a retake the transcript never contained:
    whisper collapses an immediate repeat, so a phrase said twice can appear
    once in the source transcript and be cut once, leaving the second take in
    the render with nothing in lucid's index pointing at it (DOGFOOD § 2). The
    render's own transcript has it twice; the timeline expects it once; the diff
    says so.

    **`windowed=True` closes this check's own blind spot.** A single pass over
    the render is still one whisper transcription, and it collapses a repeat in
    the render for exactly the reason it collapsed one in the source: three
    retakes survived a correctly run single-pass verify of the Scream v1 export.
    Windowed mode transcribes in short overlapping windows instead, where a
    segment ends before it can swallow a second take, and it defaults to a
    *smaller* model on purpose — see `asr.transcribe_windowed`. It costs one
    whisper run over ~1.4x the audio, so it is opt-in rather than the default.

    `loud_gaps` is reported either way and answers to neither transcript: it is
    the render's own energy envelope, masked by the words that were heard, and
    a hole in the word map that holds sound anyway is a noise or a take nothing
    wrote down.

    `transcript_path` skips ASR and uses an existing transcript of the render —
    the re-run, debugging and test path, and how a transcript produced on a
    machine with a spare GPU gets used here.
    """
    project = Project.open(path)
    edit = _load_edit(project)
    transcripts = _transcripts_for(project, clip_id)

    placed, cut = captions.place(edit, transcripts)
    if not placed:
        raise vfy.VerifyError(
            "no transcribed word survives on the timeline — there is nothing "
            "for the render to be checked against"
        )
    expected = vfy.tokens(word.text for word in placed)

    render_path = Path(render).expanduser()
    result: dict[str, Any] = {}
    # Resolved here rather than in the signature because the right default
    # differs by mode: a single pass wants the most accurate model available,
    # a windowed pass wants the one least inclined to tidy a stutter away.
    model = model or (asr.WINDOWED_MODEL if windowed else asr.DEFAULT_MODEL)

    if transcript_path is not None:
        # Named for what produced the words, not for what was asked for: a
        # supplied transcript is whatever pass made it, and reporting it as
        # "windowed" because the flag was set would be a lie a reader acts on.
        result["mode"] = "supplied"
        heard_transcript = tx.load(transcript_path, clip_id="render")
    elif windowed:
        result["mode"] = "windowed"
        payload = asr.transcribe_windowed(
            render_path,
            window=window,
            overlap=overlap,
            model=model,
            language=language or _shared_language(transcripts),
        )
        heard_transcript = tx.parse_whisper(
            payload, clip_id="render", origin=f"whisper:{model} windowed"
        )
        result.update(
            {
                "windows": payload["windows"],
                "silent_windows": payload["silent_windows"],
                "hallucinated_words": payload["hallucinated_words"],
                "window": window,
                "overlap": overlap,
            }
        )
        # A distinct name from the single-pass cache: the two are different
        # readings of the same file and overwriting one with the other would
        # make `--transcript` reuse silently ambiguous.
        cached = project.verify_dir / f"{render_path.stem}.windowed.json"
        tx.save(heard_transcript, cached)
        result["heard_transcript"] = str(cached)
    else:
        result["mode"] = "single-pass"
        payload = asr.transcribe(
            render_path, model=model, language=language or _shared_language(transcripts)
        )
        # Whisper returns an empty `segments` list rather than failing when it
        # hears no speech, and `parse_whisper` would then blame the missing
        # word timestamps — which were requested. Say what actually happened.
        if not payload.get("words") and not payload.get("segments"):
            raise vfy.VerifyError(
                f"whisper heard no speech at all in {render_path.name}. Either the "
                "render has no dialogue on it — check that the export kept the "
                "audio track — or the wrong file was passed."
            )
        heard_transcript = tx.parse_whisper(
            payload, clip_id="render", origin=f"whisper:{model}"
        )
        # Keep the expensive artifact, but never read it back automatically: a
        # re-render under the same filename would then verify against the
        # previous render's audio and pass. Reuse is explicit, via
        # `transcript_path`.
        cached = project.verify_dir / f"{render_path.stem}.json"
        tx.save(heard_transcript, cached)
        result["heard_transcript"] = str(cached)

    heard = vfy.tokens(word.text for word in heard_transcript.words)

    result.update(
        {
            "render": str(render_path),
            "clips": sorted(transcripts),
            "expected_words": len(expected),
            "heard_words": len(heard),
            "words_cut_from_transcript": cut,
            "timeline_duration": edit.duration,
            **vfy.compare(expected, heard),
        }
    )

    # Informational only, and never a failure: a render with a card hold or a
    # music tail legitimately runs past the last spoken word.
    try:
        result["render_duration"] = media.probe(render_path).duration
    except media.MediaError:
        pass

    # Likewise never fatal. The envelope is a second opinion on a diff that
    # already stands on its own, and a render lucid cannot decode should not
    # cost the caller the transcription it just paid minutes for.
    try:
        result["loud_gaps"] = energy.unaccounted_sound(
            render_path, [(w.start, w.end) for w in heard_transcript.words]
        )
    except energy.EnergyError as exc:
        result["loud_gaps"] = {"error": str(exc)}

    return result
