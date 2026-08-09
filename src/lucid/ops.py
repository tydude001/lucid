"""Project operations — the single implementation behind both front ends.

Every MCP tool and every `lucid` CLI subcommand is a thin wrapper over a
function here. That is what keeps the two in parity without duplicating logic,
and it is why the CLI is a debugging surface rather than a second codebase
(CLAUDE.md).

Each function returns a plain dict: MCP wants structured returns, and the CLI
wants something to print as JSON.
"""

from __future__ import annotations

import json
import shutil
import tempfile
from collections.abc import Iterable, Sequence
from itertools import pairwise
from pathlib import Path
from typing import Any

from lucid import asr, autoeditor, captions, energy, media, mlt, picture
from lucid import speech as sp
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
    HISTORY.md § Adjacent near-duplicate phrases at `attach-transcript`.
    """
    return vfy.find_adjacent_repeats(vfy.tokens(w.text for w in parsed.words))


def _suspect_durations(parsed: tx.Transcript) -> list[dict[str, Any]]:
    """Flag words whose claimed duration is a lie about something.

    `energy.believable` already computes this same 3x-median cutoff to mask
    audio for `verify --windowed`'s envelope pass — this just surfaces it as a
    finding at attach time, before it is ever used as a cut boundary
    (`cut_by_transcript` refuses those without confirmation).
    HISTORY.md § Suspect word durations at `attach-transcript`.
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


# -- cue table -------------------------------------------------------------
#
# Step 1 of the layered timeline (PLAN.md § The layered timeline): a picture
# overlay addressed by source word, never by timeline position. A cue says
# "from this word of this clip onward, show this asset"; the shot projection
# (step 2) turns the table into contiguous shots by mapping each cue's word
# through the edit's surviving ranges. Nothing here touches project.otio —
# the cue table lives in the manifest and is metadata until step 2 reads it.


def _cue_echo(parsed: tx.Transcript, word_index: int) -> dict[str, Any]:
    """What a cue's word index resolved to — the same convention cut/locate
    use for any tool that takes a word index (CLAUDE.md)."""
    start, end = parsed.span(word_index, word_index)
    word = parsed.words[word_index]
    return {
        "word_index": word_index,
        "text": word.text,
        "start": start,
        "end": end,
        **_context(parsed, word_index, word_index),
    }


def cue_add(path: Path | str, clip_id: str, word_index: int, asset: str) -> dict[str, Any]:
    """Add a cue: from `word_index` of `clip_id` onward, show `asset`.

    Source-addressed, like every other word-indexed tool here — `asset` is
    not resolved or checked against disk; that is the shot projection's job
    (step 2), which also knows how to turn a `card:name` key into a path.
    Refused if a cue already sits at this exact word; remove it first with
    `cue_rm` to replace it, so a call can never silently pick a winner
    between two assets at the same word.
    """
    project = Project.open(path)
    media.get_clip(project, clip_id)
    parsed = _transcript(project, clip_id)
    word_index = int(word_index)
    echo = _cue_echo(parsed, word_index)

    manifest = project.read_manifest()
    cues = manifest.setdefault("cues", [])
    if any(c["clip_id"] == clip_id and c["word_index"] == word_index for c in cues):
        raise tx.TranscriptError(
            f"{clip_id!r} already has a cue at word {word_index} — remove it "
            "with cue_rm first (CLI: `lucid cue rm`) if you meant to replace it"
        )
    cues.append({"clip_id": clip_id, "word_index": word_index, "asset": asset})
    cues.sort(key=lambda c: (c["clip_id"], c["word_index"]))
    project.write_manifest(manifest)
    return {"clip_id": clip_id, "asset": asset, "cues": len(cues), **echo}


def cue_rm(path: Path | str, clip_id: str, word_index: int) -> dict[str, Any]:
    """Remove the cue at `clip_id` word `word_index`."""
    project = Project.open(path)
    manifest = project.read_manifest()
    cues = manifest.get("cues", [])
    word_index = int(word_index)
    match = next(
        (c for c in cues if c["clip_id"] == clip_id and c["word_index"] == word_index), None
    )
    if match is None:
        known = ", ".join(f"{c['clip_id']}:{c['word_index']}" for c in cues) or "none"
        raise tx.TranscriptError(
            f"no cue at {clip_id!r} word {word_index} (existing cues: {known}) — see cue_ls"
        )
    manifest["cues"] = [c for c in cues if c is not match]
    project.write_manifest(manifest)
    parsed = _transcript(project, clip_id)
    return {
        "clip_id": clip_id,
        "asset": match["asset"],
        "cues": len(manifest["cues"]),
        **_cue_echo(parsed, word_index),
    }


def cue_ls(path: Path | str, clip_id: str | None = None) -> dict[str, Any]:
    """List the cue table, each entry echoed with its resolved word.

    Read-only. `clip_id` narrows to one clip's cues; omit it to see every
    cue in the project. Ordered by `(clip_id, word_index)`, not by resolved
    timeline position — that ordering is `build_shots`'s job, because it
    depends on the edit's surviving ranges.
    """
    project = Project.open(path)
    cues = project.read_manifest().get("cues", [])
    if clip_id is not None:
        cues = [c for c in cues if c["clip_id"] == clip_id]
    cues = sorted(cues, key=lambda c: (c["clip_id"], c["word_index"]))

    transcripts: dict[str, tx.Transcript] = {}
    entries = []
    for cue in cues:
        cid = cue["clip_id"]
        if cid not in transcripts:
            transcripts[cid] = _transcript(project, cid)
        entries.append(
            {
                "clip_id": cid,
                "asset": cue["asset"],
                **_cue_echo(transcripts[cid], cue["word_index"]),
            }
        )
    return {"cues": entries, "count": len(entries)}


def _resolve_asset(project: Project, asset: str) -> dict[str, Any]:
    """Turn a cue's opaque `asset` into a checked path, the way
    `assemble_scream.py`'s `resolve_media()` did by hand: `card:name` is a
    static picture under `assets/cards/`, anything else is a `clip_id`
    already registered with `import_media`. Raises if the asset does not
    resolve to real media — the projection is meant to catch a missing card
    or a typo'd clip_id here, not hand it to the MLT writer to find out.

    `asset_duration` rides along for the same reason: the MLT writer decides
    where inside a clip each shot reads from (`mlt.plan_picture`), and it can
    only tell a re-use from an overrun if it knows how long the clip is. A
    card has no duration — a still is held, not played.
    """
    if asset.startswith("card:"):
        name = asset.removeprefix("card:")
        if not name:
            raise ProjectError(f"asset {asset!r} names no card")
        resolved = project.cards_dir / f"{name}.png"
        is_image = True
        duration = None
    else:
        clip = media.get_clip(project, asset)
        if not clip.get("has_video"):
            raise ProjectError(
                f"asset {asset!r} is clip_id {asset!r}, which has no video — "
                "a picture cue needs a video clip or a card:name"
            )
        resolved = media.media_path(project, clip)
        is_image = False
        duration = float(clip["duration"])
    if not resolved.is_file():
        raise ProjectError(f"asset {asset!r} resolves to {resolved}, which does not exist")
    return {"asset_path": str(resolved), "is_image": is_image, "asset_duration": duration}


def build_shots(path: Path | str, *, fps: float | None = None) -> dict[str, Any]:
    """Project the cue table into contiguous shots over the current edit.

    Step 2 of the layered timeline (PLAN.md § The layered timeline):
    `assemble_scream.py`'s `build_shots` minus the XML. Each cue's word maps
    to a timeline frame via `edit.timeline_span(clip_id, word.start,
    word.end)` — an overlap test across the whole word, never containment of
    its start instant alone (CLAUDE.md: "survival is an overlap test... never
    containment"). A word whose *start* lands in a gap but whose tail spills
    into the next surviving segment is exactly the case that distinction
    exists for, and it is not a corner case: it is what a cue riding a
    swallowed retake looks like, and the real Scream VO has one (word 115,
    the "here's" that survived a false start). `timeline_time` on the start
    alone was tried first and disagreed with `assemble_scream.py`'s own
    arithmetic on that exact word — this is HISTORY.md § The multi-track
    costing spike's validation, redone with the right method. A cue whose
    word has no overlap at all refuses rather than silently snapping
    forward: `timeline_span` returns None for a fully-cut word, and that is
    the safety property PLAN.md calls out as step 3 — it cannot be deferred
    past step 2, because the frame arithmetic has nothing to return
    otherwise.

    Cues are ordered by resolved timeline position, not by `(clip_id,
    word_index)` (`cue_ls`'s order) — the whole reason this is its own step
    rather than a `cue_ls` sort key: two clips' cues only have a shared order
    once mapped through the edit. The first shot is forced to frame 0 — the
    picture track is contiguous by construction, so whichever cue comes first
    covers from the open, not from wherever its own word happens to land.
    Every other shot runs from its cue's frame to the next cue's; the last
    runs to `autoeditor.frame_total`, never to a summed duration (CLAUDE.md).

    What this does *not* do, deliberately: no per-clip playback cursor, no
    source in/out points. Those decide what the MLT writer (step 4) actually
    shows for the duration computed here, and belong with the XML that
    consumes them — this step only says when and for how long.

    `fps` states which frame grid to answer on, and defaults to the project's
    own timebase — which for an audio-only project is **milliseconds**, not
    frames (`autoeditor.AUDIO_TIMEBASE`). An export quantises to a real frame
    rate instead (`_export_fps`), so `export` passes its own rate through
    rather than converting the answer afterwards: two roundings of the same
    number are how a picture ends up a frame off the audio it was cut to.
    """
    project = Project.open(path)
    edit = _load_edit(project)
    rate = float(fps) if fps else _rate(project)
    total_frames = autoeditor.frame_total(edit, rate)

    cues = project.read_manifest().get("cues", [])
    if not cues:
        raise tl.TimelineError(
            "this project has no cues yet — add one with cue_add "
            "(CLI: `lucid cue add`) before projecting shots"
        )

    transcripts: dict[str, tx.Transcript] = {}
    marks: list[dict[str, Any]] = []
    for cue in cues:
        clip_id = cue["clip_id"]
        if clip_id not in transcripts:
            transcripts[clip_id] = _transcript(project, clip_id)
        echo = _cue_echo(transcripts[clip_id], cue["word_index"])
        span = edit.timeline_span(clip_id, echo["start"], echo["end"])
        if span is None:
            raise tl.TimelineError(
                f"cue at {clip_id!r} word {cue['word_index']} ({echo['text']!r}) "
                "was cut from the edit — remove or move the cue (cue_rm/cue_add) "
                "before projecting shots"
            )
        timeline_start, _ = span
        marks.append(
            {
                "clip_id": clip_id,
                "word_index": cue["word_index"],
                "text": echo["text"],
                "asset": cue["asset"],
                **_resolve_asset(project, cue["asset"]),
                "start_frame": round(timeline_start * rate),
            }
        )

    marks.sort(key=lambda m: m["start_frame"])
    marks[0]["start_frame"] = 0

    for previous, current in pairwise(marks):
        if current["start_frame"] <= previous["start_frame"]:
            raise tl.TimelineError(
                f"cue at {current['clip_id']!r} word {current['word_index']} lands "
                f"at or before the previous cue ({previous['clip_id']!r} word "
                f"{previous['word_index']}) — two cues resolved to the same instant"
            )

    shots = []
    for index, mark in enumerate(marks):
        end_frame = marks[index + 1]["start_frame"] if index + 1 < len(marks) else total_frames
        frames = end_frame - mark["start_frame"]
        shots.append(
            {
                **mark,
                "frames": frames,
                "start": mark["start_frame"] / rate,
                "duration": frames / rate,
            }
        )
    return {"shots": shots, "count": len(shots), "rate": rate, "total_frames": total_frames}


#: Every way the picture plan refuses. All of them are deliberate — a cue that
#: was cut, two cues resolving to one instant, a shot longer than the asset it
#: points at, an asset that does not resolve — so a caller that wants to
#: *report* a refusal rather than raise it catches exactly these.
_PICTURE_REFUSALS = (
    tl.TimelineError,
    mlt.MLTError,
    ProjectError,
    tx.TranscriptError,
    media.MediaError,
)


def _picture_plan(project: Project, rate: float) -> tuple[list[dict[str, Any]], list[mlt.Entry]]:
    """The picture track, projected and planned, on one frame grid.

    Two steps that have to travel together: `build_shots` (step 2) says when
    each shot starts and how long it runs, and `mlt.plan_picture` (step 4)
    decides what it actually shows and from where inside its asset. Either can
    refuse, and **a refusal from either is a shot `export` will not produce** —
    which is why the web UI's picture lane comes through here rather than off
    `build_shots` alone. A lane drawn from the projection only would draw the
    shot whose 34.6s runs past its 30.1s clip and the writer rejects (HISTORY.md
    § Rendering through `melt`), and that is the same class of lie as drawing a
    track the renderer silently degrades (CLAUDE.md).

    Shots come back annotated with where inside the asset each one reads —
    `plan_picture`'s per-asset cursor, which nothing downstream of it can see —
    so a clip used three times can be told from a clip replayed from its head
    three times.

    `([], [])` for a project with no cues, which is not a refusal: the edit's
    own track is the whole picture then.
    """
    if not project.read_manifest().get("cues"):
        return [], []
    shots = build_shots(project.root, fps=rate)["shots"]
    entries = mlt.plan_picture(shots, rate)
    annotated = [
        {**shot, "src_in": entry.src_in, "src_out": entry.src_out, "src_start": entry.src_in / rate}
        for shot, entry in zip(shots, entries)
    ]
    return annotated, entries


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


def _placed_segments(edit: tl.Edit) -> list[dict[str, Any]]:
    """Every segment with its timeline coordinates alongside its source ones.

    `Edit.segments` carries source time only — where a segment *plays* is the
    running sum of everything before it, which is the arithmetic every cut
    invalidates and every caller otherwise redoes.
    """
    placed = []
    offset = 0.0
    for seg in edit.segments:
        placed.append({**seg.as_dict(), "timeline_start": offset, "timeline_end": offset + seg.duration})
        offset += seg.duration
    return placed


#: `paragraph` break tuning (PLAN.md § Read-model additions). The word-count
#: arm is the guarantee, independent of timing; the gap arm is opportunistic
#: and may break earlier but is never required to.
PARAGRAPH_MIN_WORDS = 40
PARAGRAPH_GAP_MIN_WORDS = 15
PARAGRAPH_GAP_SILENCE = 0.75

#: Daydream's own threshold (DAYDREAM.md § Transcript document — "theirs
#: show down to 0.4s"). Below it a gap renders as nothing, which is the
#: correct reading of an ordinary breath, not a state to hide.
PAUSE_MARKER_MIN = 0.4


def _gap_after(words: Sequence[tx.Word], i: int) -> float | None:
    """Seconds between `words[i]`'s end and the next word's start; None at the
    transcript's last word. The one place both `_paragraphs`' opportunistic
    break and `_word_placements`' pause marker read a gap from — which is
    what makes the duration-inflation asymmetry true for both without
    re-arguing it twice: whisper inflates the *duration* of the word after a
    swallowed retake, which only ever pushes that word's end later, which can
    only shrink this gap, never widen it. A bad transcript can suppress a
    paragraph break or a pause marker (cosmetic); it can never invent one.
    """
    if i + 1 >= len(words):
        return None
    return words[i + 1].start - words[i].end


def _paragraphs(words: Sequence[tx.Word]) -> dict[int, int]:
    """Which paragraph each word belongs to, word-order-driven (CLAUDE.md).

    Breaks after a sentence-ending word (`.`, `?`, `!`) once the current
    paragraph holds `PARAGRAPH_MIN_WORDS` — that is the guarantee, and it
    fires regardless of timing. A silence of `PARAGRAPH_GAP_SILENCE` after a
    sentence end may break earlier, once the paragraph already holds
    `PARAGRAPH_GAP_MIN_WORDS` — but that arm is opportunistic, not a promise.

    The asymmetry that makes the gap arm safe: whisper inflates the *duration*
    of the word following a swallowed retake, which only ever pushes that
    word's `end` later — and a later `end` can only *shrink* the measured gap
    to the next word's `start`, never widen it. A bad transcript can therefore
    only suppress an early break (an ugly paragraph); it cannot invent one
    (a lie about where a sentence ended).
    """
    assigned: dict[int, int] = {}
    current = 0
    count = 0
    for i, word in enumerate(words):
        assigned[word.index] = current
        count += 1
        if i + 1 >= len(words) or not word.text.rstrip().endswith((".", "?", "!")):
            continue
        if count >= PARAGRAPH_MIN_WORDS:
            current += 1
            count = 0
        elif count >= PARAGRAPH_GAP_MIN_WORDS:
            gap = _gap_after(words, i)
            if gap is not None and gap >= PARAGRAPH_GAP_SILENCE:
                current += 1
                count = 0
    return assigned


def _word_placements(edit: tl.Edit, clip_id: str, parsed: tx.Transcript) -> list[dict[str, Any]]:
    """Each word, with whether it survived the edit and where it now plays.

    Survival is an **overlap** test, never containment (CLAUDE.md): whisper
    inflates the duration of the word following a swallowed retake, so a word
    routinely straddles a cut edge and survives in part. `covered` is how much
    of it is left and `partial` says so out loud, because a word drawn as
    simply "kept" when half of it is gone is the same lie the containment test
    told.

    The timeline coordinates come from `Edit.timeline_span` — the singular,
    first-survivor form, which is right here for the same reason it is right
    for captions: one word wants one place to be highlighted, not a list.

    `paragraph` (see `_paragraphs`) is computed over every word in transcript
    order, cut or not — it is a property of the document, not of the edit.

    `pause_after` (see `_gap_after`, `PAUSE_MARKER_MIN`) is present as a key
    only when the gap to the next word clears the marker threshold — never a
    bare boolean, never an always-present number, so the threshold lives in
    exactly one place (here) and the front end never carries a second copy of
    it. Its `present` flag answers "does the pause itself still play", via
    the identical `timeline_span` overlap test used for the word two lines
    above — so a caller never has to infer a pause's survival from its
    flanking words' own `present` flags, which can disagree with it (e.g. a
    `cut_by_time` call that removed only the silence).
    """
    suspect = {item["index"]: item for item in _suspect_durations(parsed)}
    paragraphs = _paragraphs(parsed.words)
    placements = []
    for i, word in enumerate(parsed.words):
        # A zero-width word is not a range, so `timeline_span`'s `b > a` test
        # would report it cut wherever it actually sits. Locate the instant —
        # with the segment's end boundary counted as inside it, because the
        # last word of a transcript routinely sits exactly on the end of the
        # last segment and the half-open test calls that "cut". It is the one
        # place `closed_end` is correct; `timeline.timeline_time` says why.
        if word.end > word.start:
            span = edit.timeline_span(clip_id, word.start, word.end)
            covered = edit.covers(clip_id, word.start, word.end)
        else:
            at = edit.timeline_time(clip_id, word.start, closed_end=True)
            span = None if at is None else (at, at)
            covered = 0.0
        item: dict[str, Any] = {
            **word.as_dict(),
            "present": span is not None,
            "covered": covered,
            "partial": span is not None and (word.end - word.start) - covered > tl.MIN_SEGMENT,
            "timeline_start": span[0] if span else None,
            "timeline_end": span[1] if span else None,
            "paragraph": paragraphs[word.index],
        }
        if word.index in suspect:
            item["suspect"] = suspect[word.index]
        gap = _gap_after(parsed.words, i)
        if gap is not None and gap >= PAUSE_MARKER_MIN:
            nxt = parsed.words[i + 1]
            pause_span = edit.timeline_span(clip_id, word.end, nxt.start)
            item["pause_after"] = {"duration": gap, "present": pause_span is not None}
        placements.append(item)
    return placements


def _seams(edit: tl.Edit, clip_id: str, placements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The cut boundaries, named by the words either side of each one.

    A seam is where two segments meet: material was removed between them and
    the hole closed, so it is a single instant on the timeline and a *gap* in
    the source. Naming it by word index rather than by timeline second is the
    whole property this project defends — a later cut moves the second and
    leaves the words alone.

    The words are looked up in **timeline** coordinates, among the survivors
    only. Asking the transcript what sits at the seam's source time answers
    with the word that was *removed* — the cut starts exactly where the
    outgoing segment ends — which is the one word a person reading across the
    join will not hear.
    """
    survivors = [w for w in placements if w["present"]]
    seams = []
    offset = 0.0
    for before, after in pairwise(edit.segments):
        offset += before.duration
        if before.clip_id != after.clip_id:
            # Not a cut in one recording; it is a join between two of them,
            # and "the words either side" would be from different transcripts.
            continue
        seam: dict[str, Any] = {
            "timeline_time": offset,
            "clip_id": before.clip_id,
            "source_end": before.end,
            "source_start": after.start,
            "removed": after.start - before.end,
        }
        if before.clip_id == clip_id:
            heard_before = [
                w for w in survivors if w["timeline_end"] <= offset + tl.MIN_SEGMENT
            ]
            heard_after = [
                w for w in survivors if w["timeline_start"] >= offset - tl.MIN_SEGMENT
            ]
            if heard_before:
                seam["before"] = {"index": heard_before[-1]["index"], "text": heard_before[-1]["text"]}
            if heard_after:
                seam["after"] = {"index": heard_after[0]["index"], "text": heard_after[0]["text"]}
        seams.append(seam)
    return seams


def timeline_view(path: Path | str, clip_id: str | None = None) -> dict[str, Any]:
    """The whole edit in one payload: segments, seams, and every word's fate.

    The read model behind `lucid web` (HISTORY.md § The preview/timeline web UI). It exists as an op
    rather than inside the server because a view that computed word survival
    itself would be a second implementation of the overlap test, and the front
    ends are meant to hold no logic of their own — the same rule that keeps
    the CLI and the MCP server in parity.

    `clip_id` defaults to whichever clip the timeline actually opens with,
    which is the one clip a single-track edit almost always has. A clip with
    no transcript still returns segments and seams; `words` is null and
    `transcript_missing` is set, matching `locate`'s policy rather than
    refusing a valid question about a picture-only clip.

    `layered` says whether this timeline names more than one source — a cue
    table or a second clip — which is what decides whether `export` writes and
    renders it through MLT/melt or hands it to auto-editor. It is reported here
    rather than recomputed by a front end for the usual reason: the answer is
    what routes around a silent failure, and a second implementation of it
    would be a second chance to get it wrong.

    `shots` is the picture lane — step 6 of the layered timeline, and the field
    the web UI's V2 lane is drawn from. It is `_picture_plan`'s answer, not
    `build_shots`'s: the lane may not draw a shot `export` would refuse, so the
    projection goes through the MLT writer's planner before it is reported. Two
    consequences a reader should expect:

    * `shots` is null for a project with no cues — there is no picture lane
      then, only the edit's own track — and null with a `shots_error` when the
      plan refused. **A refusal is reported, not raised**: a stale cue must not
      take the whole view down with it, because the view is how a person finds
      the cue to fix. It is the one thing here that answers with a message
      instead of an answer, and the front end is expected to draw the message.
    * `shots_rate` is the frame grid the shots were quantised on, which is
      `export`'s rate (`_export_fps`) and **not** `timebase` — an audio-only
      project's timebase is milliseconds, and the picture is not.
    """
    project = Project.open(path)
    edit = _load_edit(project)
    clips = _clips_by_id(project)

    if clip_id is None:
        clip_id = next((s.clip_id for s in edit.segments), None) or next(iter(clips), None)
    if clip_id is None:
        raise ProjectError("this project has no clips to view")
    clip = media.get_clip(project, clip_id)

    try:
        parsed: tx.Transcript | None = _transcript(project, clip_id)
    except tx.TranscriptError:
        parsed = None

    placements = [] if parsed is None else _word_placements(edit, clip_id, parsed)

    shots_rate = _export_fps(clips)
    shots_error: str | None = None
    try:
        shots, _ = _picture_plan(project, shots_rate)
    except _PICTURE_REFUSALS as exc:
        shots, shots_error = [], str(exc)

    result: dict[str, Any] = {
        "project": str(project.root),
        "name": project.read_manifest().get("name", project.root.name),
        "clip_id": clip_id,
        "clips": [
            {
                "clip_id": c["clip_id"],
                "duration": c.get("duration"),
                "has_video": bool(c.get("has_video")),
                "has_transcript": project.transcript_path(c["clip_id"]).exists(),
            }
            for c in clips.values()
        ],
        "source_duration": clip.get("duration"),
        "timeline_duration": edit.duration,
        "timebase": _rate(project),
        "undo_depth": len(project.snapshots()),
        "layered": _is_layered(project, edit),
        "shots": shots or None,
        "shots_rate": shots_rate,
        "segments": _placed_segments(edit),
        "seams": _seams(edit, clip_id, placements),
    }
    if shots_error is not None:
        result["shots_error"] = shots_error
    if parsed is None:
        result["words"] = None
        result["transcript_missing"] = True
    else:
        result["words"] = placements
    return result


def _default_clip_id(project: Project, clips: dict[str, dict[str, Any]]) -> str | None:
    """The clip a project-level view opens with when none is named.

    Same preference as `timeline_view` — the timeline's own clip, else the
    first registered one — but does not require a timeline to exist, unlike
    `_load_edit`: a clip that has been imported but not yet seeded is still a
    valid thing to ask a waveform about.
    """
    if project.timeline_path.exists():
        found = next((s.clip_id for s in tl.read(project.timeline_path).segments), None)
        if found is not None:
            return found
    return next(iter(clips), None)


#: `ops.waveform`'s return contract, verbatim (PLAN.md § Read-model
#: additions) — the server and web UI stages code against this shape.
_WAVEFORM_FIELDS = ("clip_id", "frame_ms", "rms", "duration_s")


def _cached_waveform(cache_path: Path, stat: Any) -> dict[str, Any] | None:
    """The cached envelope, if `cache_path` still describes the file at `stat`.

    Keyed by size and mtime rather than a hash: cheap to check (no re-read of
    the media) and exactly what `attenuate_noises` or a re-import changes when
    they replace a clip's audio.
    """
    if not cache_path.exists():
        return None
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if payload.get("size") != stat.st_size or payload.get("mtime_ns") != stat.st_mtime_ns:
        return None
    try:
        return {field: payload[field] for field in _WAVEFORM_FIELDS}
    except KeyError:
        return None


# Deliberately no MCP tool (PLAN.md § Read-model additions): the convention
# binds MCP tools to have a CLI subcommand, not the reverse, and 19,000 floats
# is a picture, not something an agent should reason over — `loud_gaps` and
# `unaccounted_sound` already answer the numeric questions about this same
# envelope. CLI only: `lucid waveform`.
def waveform(path: Path | str, clip_id: str | None = None) -> dict[str, Any]:
    """RMS per 20ms frame for the timeline's waveform lane, normalised to bytes.

    `energy.envelope` is a Python loop — roughly a second of work per 385s of
    8kHz audio, and linear — so the result is cached under `cache/waveform/`,
    keyed by the resolved media file's size and mtime rather than recomputed
    per request. A cache hit never calls `energy.decode`.

    Resolves media through `media.media_path()`, never `root / clip["media"]`
    (CLAUDE.md): the waveform drawn is of the audio that will actually be
    exported, attenuated copy included.

    Each frame's RMS is normalised against the loudest frame in the file, to
    0-255 — the same scale a canvas waveform draws from directly, and a full
    file so the picture does not silently renormalise every time a cut
    changes what is visible.

    Return contract, fixed:
    `{"clip_id": str, "frame_ms": 20, "rms": [0-255 ints], "duration_s": float}`
    """
    project = Project.open(path)
    clips = _clips_by_id(project)
    if clip_id is None:
        clip_id = _default_clip_id(project, clips)
    if clip_id is None:
        raise ProjectError("this project has no clips to measure")
    clip = media.get_clip(project, clip_id)
    source = media.media_path(project, clip)
    if not source.is_file():
        raise ProjectError(f"{clip_id}'s media is missing from disk: {source}")

    stat = source.stat()
    cache_path = project.waveform_path(clip_id)
    cached = _cached_waveform(cache_path, stat)
    if cached is not None:
        return cached

    env = energy.envelope(energy.decode(source))
    peak = max(env) if env else 0.0
    scale = 255.0 / peak if peak > 0 else 0.0
    result: dict[str, Any] = {
        "clip_id": clip_id,
        "frame_ms": round(energy.FRAME * 1000),
        "rms": [min(255, round(v * scale)) for v in env],
        "duration_s": round(len(env) * energy.FRAME, 3),
    }

    project.waveform_dir.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(
        json.dumps({"size": stat.st_size, "mtime_ns": stat.st_mtime_ns, **result}),
        encoding="utf-8",
    )
    return result


#: Cards are written as PNG by every path that makes one, but a person can
#: drop any still into `assets/cards/`, and the preview shows it as an <img>.
_PREVIEW_IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp", ".gif", ".avif"})


def preview_source(path: Path | str, asset: str) -> dict[str, Any]:
    """Resolve one preview asset to a file, and say whether it will play.

    The picture lane draws shots; this is what lets the *viewer* show the shot
    under the playhead, which is what makes V2 a picture rather than a plan of
    one (PLAN.md § Next). One asset key in — a `card:name` or a clip_id, the
    same opaque string a cue carries — a resolved path and a verdict out.

    **Deliberately wider than `_resolve_asset`**, which refuses a clip with no
    video because a picture *cue* pointing at a VO is a mistake. The viewer has
    a second caller with the opposite need: the transport plays the timeline's
    own clip, and on a VO project that clip is exactly the audio-only one. The
    two resolvers agree on where a card lives and on what `media_path` means;
    they disagree only about what a valid answer is, and each is right for its
    own question.

    `kind` is what the front end draws with — an `<img>` holds a still, a
    `<video>` seeks — and it comes from the resolved file rather than from the
    cue, because `is_image` in a shot is a statement about the *cue key* and
    this is a statement about the bytes.

    `playable` is `media.playability`'s verdict, and it is reported rather than
    enforced: an unplayable file is still streamed if asked for, because the
    browser is the only real authority and this list is a prediction. What the
    verdict buys is the *reason*, which a `<video>`'s error event does not carry
    — without it, a codec refusal and a black frame in the edit look identical.
    """
    project = Project.open(path)
    if asset.startswith("card:"):
        name = asset.removeprefix("card:")
        # The one place an asset key arrives from outside the project (the web
        # route), so the traversal check is here rather than in the resolver
        # shared with the cue table.
        if not name or "/" in name or "\\" in name or name.startswith("."):
            raise ProjectError(f"asset {asset!r} does not name a card")
        source = project.cards_dir / f"{name}.png"
    else:
        source = media.media_path(project, media.get_clip(project, asset))
    if not source.is_file():
        raise ProjectError(f"asset {asset!r} resolves to {source}, which does not exist")

    result: dict[str, Any] = {"asset": asset, "path": str(source)}
    if source.suffix.lower() in _PREVIEW_IMAGE_SUFFIXES:
        return {**result, "kind": "image", "playable": True, "reason": None}

    verdict = media.playability(source)
    kind = "video" if verdict.get("video_codec") else "audio"
    return {**result, "kind": kind, **verdict}


def _resolve(parsed: tx.Transcript, ranges: Iterable[Sequence[int]]) -> list[tuple[float, float]]:
    resolved = []
    for item in ranges:
        if len(item) != 2:
            raise tx.TranscriptError(f"word range {item!r} must be [first, last]")
        resolved.append(parsed.span(int(item[0]), int(item[1])))
    return resolved


#: Words shown either side of a resolved range. The defect this echo exists to
#: catch is an index one word past the intended phrase (HISTORY.md § 3), and
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
    through_pause: bool = False,
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

    `through_pause=True` extends each cut range's trailing edge through the
    pause after its last word, when that gap clears `PAUSE_MARKER_MIN` — the
    same predicate `_word_placements` uses to decide whether the transcript
    pane draws a `[N.Ns]` marker there at all, so a range can only ever be
    extended onto a gap the pane actually showed; a stale flag sent for a gap
    that no longer qualifies is a safe no-op. `Transcript.span` stops at the
    last word's own `end`, so without this the trailing pause survives as
    audible dead air even after the words either side of it are cut — this is
    what makes "cutting a phrase cuts its trailing pause" (DAYDREAM.md §
    Transcript document) true rather than merely cosmetic. Only the `cut`
    branch reads it: `keep` already discards everything outside its ranges,
    including any trailing pause, so there is nothing separate to swallow.
    Applies uniformly to every range in one call, matching `pad`'s existing
    per-call (not per-range) precedent.

    A range whose first or last word claims a suspect duration
    (HISTORY.md § Suspect word durations) is refused unless `confirm_suspect=True`: that word's `start`/`end`
    is what the cut boundary resolves to, and a boundary that long is usually
    hiding a retake rather than ending where it claims.

    `plan=True` resolves everything and returns the same payload without
    writing: no snapshot, no timeline mutation. It runs the identical code path
    — the edit is mutated in memory and simply never saved — so the numbers it
    reports are the real ones, not a second implementation's guess at them.
    Six cues in the Scream shot plan pointed one word past the intended phrase
    and were caught exactly this way (HISTORY.md § 3). Planning also *reports*
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
            "(HISTORY.md § Suspect word durations). Check it, then retry "
            "with confirm_suspect=True (CLI: --confirm-suspect) if the "
            "boundary is actually fine, or pick a different word."
        )

    applied: list[dict[str, Any]] = []
    if cut:
        for (first, last), (start, end) in zip(cut, _resolve(parsed, cut)):
            if through_pause:
                gap = _gap_after(parsed.words, int(last))
                if gap is not None and gap >= PAUSE_MARKER_MIN:
                    end = parsed.words[int(last) + 1].start
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
    a suspect duration (HISTORY.md § Suspect word durations), unless
    `confirm_suspect=True` or `plan=True` — under `plan` they are reported as
    `suspect_boundaries` instead.

    `plan=True` runs the identical code path and simply skips the write, same
    as `cut_by_transcript` (HISTORY.md § `cut --plan`).
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


def restore(
    path: Path | str,
    clip_id: str,
    ranges: Sequence[Sequence[int]],
    *,
    pad: float = 0.0,
    plan: bool = False,
) -> dict[str, Any]:
    """Un-cut whichever part of these inclusive word ranges is not currently present.

    `Edit` stores only surviving segments (`timeline.py`'s module docstring)
    — there is no removed-ranges log to read back — so what is absent is
    derived: `Edit.gaps` is the complement of this clip's segments against
    its own registered duration, and `Edit.restore` splices back whatever
    part of the requested range falls in a gap. Ranges are word indices,
    resolved exactly like `cut_by_transcript`'s `cut=`/`keep=`, because the
    only thing pointing at un-cut material naturally is the transcript a
    person is reading, the same way a cut is made; there is no time-based
    form mirroring `cut_by_time`, because that exists to convert a render
    timestamp a human just watched, and material that is off the timeline
    has no render timestamp to convert from. `pad` mirrors
    `cut_by_transcript`'s own `pad`: pass the value used on the original cut
    to bring its padding sliver back too, not just the words.

    Only the part `Edit.gaps` says is actually absent comes back — material
    still on the timeline is left alone. A request spanning two separate
    cuts restores both, as separate pieces; a request only touching part of
    one cut restores only that part; a request over material that was never
    cut is reported `already_present: True`, not an error, mirroring
    `cut_by_transcript`'s `already_cut`.

    Restoring only ever brings back material the source recording already
    has (bounded by the clip's own registered duration), so the timeline
    stays a subset of the source throughout — this is not `vo_extend`
    (PLAN.md parks that separately), which would splice in material the
    source never had.

    There is no suspect-duration refusal here, unlike a cut: a boundary that
    looks like it swallowed a retake is exactly the kind of thing restore
    exists to bring back, not a mistake to guard against.

    Refused (`TimelineError`) if `clip_id` has no surviving segment anywhere
    in the edit — nothing left of it to splice the range next to — or if its
    segments are not contiguous in the edit (an interleaved multi-source
    timeline, which this does not support yet).

    `plan=True` resolves and reports without writing, identically to
    `cut_by_transcript`.
    """
    if not ranges:
        raise tx.TranscriptError("restore needs at least one word range")

    project = Project.open(path)
    clip = media.get_clip(project, clip_id)
    parsed = _transcript(project, clip_id)
    edit = _load_edit(project)
    before = edit.duration
    duration = float(clip["duration"])

    applied: list[dict[str, Any]] = []
    for first, last in ranges:
        first, last = int(first), int(last)
        word_start, word_end = parsed.span(first, last)
        lo, hi = max(0.0, word_start - pad), word_end + pad
        pieces = edit.restore(clip_id, lo, hi, duration=duration)
        applied.append(
            {
                **_echo(parsed, first, last, lo, hi),
                "source_start": lo,
                "source_end": hi,
                "restored": [
                    {"source_start": p_lo, "source_end": p_hi, "duration": p_hi - p_lo}
                    for p_lo, p_hi in pieces
                ],
                "restored_seconds": round(sum(p_hi - p_lo for p_lo, p_hi in pieces), 6),
                "already_present": not pieces,
            }
        )

    if not plan:
        _save_edit(project, edit)

    result: dict[str, Any] = {
        "clip_id": clip_id,
        "applied": applied,
        "duration_before": before,
        "duration_after": edit.duration,
        "restored": edit.duration - before,
        "segments": len(edit.segments),
    }
    if plan:
        result["plan"] = True
    return result


def locate(
    path: Path | str,
    clip_id: str,
    *,
    first: int | None = None,
    last: int | None = None,
    source_start: float | None = None,
    source_end: float | None = None,
) -> dict[str, Any]:
    """Where does this source word or source time play in the current render?

    `cut_by_time`'s read-only mirror: that takes render time and resolves it
    back to source, this takes source and resolves it forward to render time.
    Answering it by hand meant reading `project.otio` and adding up segment
    durations, which is exactly the arithmetic every cut invalidates.

    Address it either way, but only one way per call: `first`/`last` are
    inclusive word indices into the clip's transcript (`last` defaults to
    `first`, so one index locates one word), and `source_start`/`source_end`
    are seconds in the original recording (`source_end` omitted locates an
    instant rather than an interval).

    The distinction the payload exists to keep straight is **cut** versus
    **never there**. An interval that has been edited out returns
    `present: false` with no placements; one that runs past the end of the
    recording returns `beyond_source` as well, because "you cut it" and "it
    was never recorded" are different problems and the empty list looks the
    same in both. A partially-cut interval is the normal case, not an error —
    `placements` reports each surviving piece with the source coordinates that
    say which part of the phrase it is, `covered` how much of it is left, and
    `contiguous` whether the survivors still play back-to-back.

    Word mode echoes the words it resolved to plus the three either side, the
    same convention `cut --plan` uses (CLAUDE.md); time mode echoes the words
    the interval overlaps — an overlap test, never containment — or its
    nearest flanking words when it landed in silence. A clip with no
    transcript still locates by time; `words` is null and `transcript_missing`
    is set, rather than refusing a valid question about a picture-only clip.
    Read-only: nothing is written, and there is no `plan=`.
    """
    by_words = first is not None or last is not None
    by_time = source_start is not None or source_end is not None
    if by_words and by_time:
        raise tl.TimelineError(
            "pass either first/last or source_start/source_end, not both — "
            "they are two ways of naming the same thing, and a call giving "
            "both cannot say which one it meant"
        )
    if not by_words and not by_time:
        raise tl.TimelineError(
            "locate needs something to locate: first= (a word index) or "
            "source_start= (seconds into the recording)"
        )
    if by_words and first is None:
        raise tl.TimelineError("last= needs first= — a range has to start somewhere")
    if by_time and source_start is None:
        raise tl.TimelineError("source_end= needs source_start=")

    project = Project.open(path)
    clip = media.get_clip(project, clip_id)
    edit = _load_edit(project)

    parsed: tx.Transcript | None
    if by_words:
        parsed = _transcript(project, clip_id)
    else:
        try:
            parsed = _transcript(project, clip_id)
        except tx.TranscriptError:
            parsed = None

    # An instant is a zero-width interval everywhere below; only the reported
    # mode and the echo differ, so resolve both shapes to one pair here.
    instant = False
    if by_words:
        assert first is not None
        last = first if last is None else last
        lo, hi = parsed.span(first, last)  # type: ignore[union-attr]
    else:
        assert source_start is not None
        lo = float(source_start)
        if source_end is None:
            hi = lo
            instant = True
        else:
            hi = float(source_end)
        if hi < lo:
            raise tl.TimelineError(f"interval {lo:.3f}-{hi:.3f} runs backwards")
        if lo < 0:
            raise tl.TimelineError(f"source time {lo:.3f} is negative")

    if instant:
        at = edit.timeline_time(clip_id, lo)
        placements = (
            [tl.Placement(timeline_start=at, timeline_end=at, source_start=lo, source_end=lo)]
            if at is not None
            else []
        )
    else:
        placements = edit.timeline_spans(clip_id, lo, hi)

    covered = sum(p.duration for p in placements)
    requested = hi - lo
    contiguous = all(a.contiguous_with(b) for a, b in pairwise(placements))

    result: dict[str, Any] = {
        "clip_id": clip_id,
        "mode": "words" if by_words else ("instant" if instant else "time"),
        "source_start": lo,
        "source_end": hi,
        "present": bool(placements),
        "placements": [p.as_dict() for p in placements],
        "timeline_start": placements[0].timeline_start if placements else None,
        "timeline_end": placements[-1].timeline_end if placements else None,
        "requested": requested,
        "covered": covered,
        "fully_present": bool(placements) and (requested - covered) <= tl.MIN_SEGMENT,
        "contiguous": contiguous,
        "timeline_duration": edit.duration,
    }

    # "Cut" and "never recorded" look identical from the placements alone —
    # missing either way — and only the clip's own duration tells them apart.
    # Say so, rather than let a short `covered` be read as an edit decision.
    duration = clip.get("duration")
    if duration is not None and hi > float(duration):
        end = float(duration)
        result["beyond_source"] = True
        result["source_duration"] = end
        # Zero for an instant past the end — hence the bool above rather than
        # letting a caller test this number's truthiness.
        result["beyond_source_seconds"] = hi - max(lo, end)

    if parsed is None:
        result["words"] = None
        result["transcript_missing"] = True
        return result

    if by_words:
        assert first is not None and last is not None
        result["words"] = [w.as_dict() for w in parsed.window(first, last)]
        result.update(_echo(parsed, first, last, lo, hi))
    else:
        words = _overlap_words(parsed, lo, hi)
        result["words"] = words
        result.update(
            _context(parsed, words[0]["index"], words[-1]["index"])
            if words
            else _nearest_context(parsed, lo, hi)
        )
    return result


def _run_words(words: Sequence[dict[str, Any]], run: tuple[float, float]) -> list[dict[str, Any]]:
    """Which (already timeline-mapped) words overlap a speech `run`.

    Overlap, never containment (CLAUDE.md): a word only partly inside the run
    still names it — the same test `_pad_reach`/`_overlap_words` use.
    """
    lo, hi = run
    return [
        {"index": w["index"], "text": w["text"]}
        for w in words
        if w["timeline_start"] < hi and w["timeline_end"] > lo
    ]


def speech_overlap(
    path: Path | str,
    clip_id: str,
    *,
    at: float = 0.0,
    clip_in: float | None = None,
    clip_out: float | None = None,
    vo_clip_id: str | None = None,
    max_gap: float = 0.3,
    min_seam: float = 0.5,
    cap: float = energy.CAP,
) -> dict[str, Any]:
    """Does a *proposed* placement of `clip_id` overlap the VO's speech?

    The prerequisite check behind "can this clip speak here?" — answer it
    before designing any ducking. `at`/`clip_in`/`clip_out` describe where
    `clip_id` *would* sit on the timeline (defaults: unplaced at 0, its whole
    duration) — the clip need not be on the timeline yet, and usually isn't,
    since the current model is single-track (`timeline.py`'s module
    docstring). The VO side maps through the existing edit
    (`Edit.timeline_span`, exactly as captions map words); `clip_id`'s own
    words are not in the edit, so they map by direct offset against the
    proposed window instead — a third use of one clip's own transcript,
    alongside `attach_transcript`/`transcribe` and `cut_by_transcript`.

    Both sides are trimmed with `energy.believable` first — an inflated word
    duration hides a real seam behind it (CLAUDE.md; HISTORY.md § 2) — then
    merged into speech *runs* with `max_gap` tolerance, since a 0.05s gap
    between two words is not a usable seam to duck into.

    Read `overlaps` first: any entry means this placement would step on VO
    speech, not empty air — this is exactly the shape a word-level pass
    caught on Billy/Stu, where the clip's speech nearly fully covered a VO
    thesis line with no clean seam to duck into. `clean_seams` (>= `min_seam`
    wide) are the windows where `clip_id` could speak without touching the
    VO. Read-only: nothing is written, and there is no `plan=`.
    """
    project = Project.open(path)
    clip = media.get_clip(project, clip_id)
    clip_parsed = _transcript(project, clip_id)

    clip_in = 0.0 if clip_in is None else float(clip_in)
    if clip_out is None:
        duration = clip.get("duration")
        if duration is None:
            raise media.MediaError(
                f"{clip_id!r} has no known duration — probe failed; pass clip_out explicitly"
            )
        clip_out = float(duration)
    else:
        clip_out = float(clip_out)
    if clip_out <= clip_in:
        raise tl.TimelineError(f"interval {clip_in:.3f}-{clip_out:.3f} is empty or backwards")
    if at < 0:
        raise tl.TimelineError(f"at={at:.3f} is negative — a placement cannot start before 0")

    edit = _load_edit(project)
    if not edit.segments:
        raise ProjectError("the VO timeline has no segments to overlap against")

    present = {seg.clip_id for seg in edit.segments}
    if vo_clip_id is None:
        if len(present) > 1:
            raise ProjectError(
                "the timeline has more than one clip "
                f"({', '.join(sorted(present))}) — pass vo_clip_id to say which one is the VO"
            )
        vo_clip_id = next(iter(present))
    elif vo_clip_id not in present:
        raise ProjectError(
            f"{vo_clip_id!r} is not on the timeline (present: {', '.join(sorted(present))})"
        )
    vo_parsed = _transcript(project, vo_clip_id)

    # Clip B side: not in the edit, so words map by direct offset against the
    # proposed [clip_in, clip_out) -> [at, at + (clip_out - clip_in)) window.
    clip_full_trimmed = energy.believable([(w.start, w.end) for w in clip_parsed.words], cap=cap)
    clip_hits = [w for w in clip_parsed.words if w.start < clip_out and w.end > clip_in]
    clip_trimmed = [
        trimmed
        for word, trimmed in zip(clip_parsed.words, clip_full_trimmed)
        if word.start < clip_out and word.end > clip_in
    ]
    clip_words: list[dict[str, Any]] = []
    clip_spans: list[tuple[float, float]] = []
    for word, (bs, be) in zip(clip_hits, clip_trimmed):
        a, b = max(clip_in, bs), min(clip_out, be)
        if b <= a:
            continue
        t0, t1 = at + (a - clip_in), at + (b - clip_in)
        clip_words.append(
            {
                "index": word.index,
                "text": word.text,
                "source_start": word.start,
                "source_end": word.end,
                "believable_start": bs,
                "believable_end": be,
                "timeline_start": t0,
                "timeline_end": t1,
            }
        )
        clip_spans.append((t0, t1))

    # VO side: already in the edit, so words map through the same
    # Edit.timeline_span captions use. A fully-cut word is never heard.
    vo_trimmed = energy.believable([(w.start, w.end) for w in vo_parsed.words], cap=cap)
    vo_words: list[dict[str, Any]] = []
    vo_spans: list[tuple[float, float]] = []
    for word, (bs, be) in zip(vo_parsed.words, vo_trimmed):
        mapped = edit.timeline_span(vo_clip_id, bs, be)
        if mapped is None:
            continue
        t0, t1 = mapped
        vo_words.append(
            {
                "index": word.index,
                "text": word.text,
                "source_start": word.start,
                "source_end": word.end,
                "believable_start": bs,
                "believable_end": be,
                "timeline_start": t0,
                "timeline_end": t1,
            }
        )
        vo_spans.append((t0, t1))

    clip_run_spans = sp.merge_runs(clip_spans, max_gap=max_gap)
    vo_run_spans = sp.merge_runs(vo_spans, max_gap=max_gap)
    clip_runs = [
        {
            "timeline_start": lo,
            "timeline_end": hi,
            "duration": hi - lo,
            "words": _run_words(clip_words, (lo, hi)),
        }
        for lo, hi in clip_run_spans
    ]
    vo_runs = [
        {
            "timeline_start": lo,
            "timeline_end": hi,
            "duration": hi - lo,
            "words": _run_words(vo_words, (lo, hi)),
        }
        for lo, hi in vo_run_spans
    ]

    overlaps = [
        {
            "timeline_start": lo,
            "timeline_end": hi,
            "duration": hi - lo,
            "clip_words": _run_words(clip_words, (lo, hi)),
            "vo_words": _run_words(vo_words, (lo, hi)),
        }
        for lo, hi in sp.intersect_runs(clip_run_spans, vo_run_spans)
    ]

    clean_seams: list[dict[str, Any]] = []
    for run in clip_run_spans:
        for lo, hi in sp.subtract_runs(run, vo_run_spans):
            if hi - lo >= min_seam:
                clean_seams.append(
                    {
                        "timeline_start": lo,
                        "timeline_end": hi,
                        "duration": hi - lo,
                        "clip_words": _run_words(clip_words, (lo, hi)),
                    }
                )

    return {
        "clip_id": clip_id,
        "vo_clip_id": vo_clip_id,
        "at": at,
        "clip_in": clip_in,
        "clip_out": clip_out,
        "max_gap": max_gap,
        "min_seam": min_seam,
        "cap": cap,
        "clip_words": clip_words,
        "vo_words": vo_words,
        "clip_runs": clip_runs,
        "vo_runs": vo_runs,
        "overlaps": overlaps,
        "clean_seams": clean_seams,
        "summary": {
            "clip_words": len(clip_words),
            "vo_words": len(vo_words),
            "clip_runs": len(clip_runs),
            "vo_runs": len(vo_runs),
            "overlap_count": len(overlaps),
            "overlap_seconds": round(sum(o["duration"] for o in overlaps), 3),
            "clean_seam_count": len(clean_seams),
            "clean_seam_seconds": round(sum(c["duration"] for c in clean_seams), 3),
            "clip_speech_seconds": round(sum(r["duration"] for r in clip_runs), 3),
            "vo_speech_seconds": round(sum(r["duration"] for r in vo_runs), 3),
        },
    }


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


# -- attenuating noise, rather than cutting it ----------------------------


def _neighbours(
    parsed: tx.Transcript, trimmed_ends: Sequence[float], gap: dict[str, Any]
) -> tuple[int, int] | None:
    """The two consecutive word indices a `loud_gaps` gap sits between.

    `energy.believable` only ever trims a span's *end*, so a gap's `start` is
    a trimmed end and its `end` is an untrimmed next-word start. Both sides
    already went through the same `round(x, 3)` lucid applies everywhere, so
    this is an exact match, not a fuzzy one.
    """
    for i in range(len(parsed) - 1):
        if (
            round(trimmed_ends[i], 3) == gap["start"]
            and round(parsed.words[i + 1].start, 3) == gap["end"]
        ):
            return i, i + 1
    return None


def _classify_noise_events(
    parsed: tx.Transcript,
    trimmed_ends: Sequence[float],
    gaps: Sequence[dict[str, Any]],
    *,
    max_event_seconds: float,
    max_gap_seconds: float,
    pad: float,
    suspect: dict[int, dict[str, Any]],
) -> list[dict[str, Any]]:
    """The safety filter, isolated from I/O so it can be tested without ffmpeg.

    Every loud run in every gap becomes one event, tagged `"attenuated"`,
    `"suspect_neighbour"`, or `"disqualified"` — never both length and
    width reasons collapsed into one, so a caller can tell which side of the
    filter actually caught a given event.
    """
    events: list[dict[str, Any]] = []
    for gap in gaps:
        neighbours = _neighbours(parsed, trimmed_ends, gap)
        before_idx, after_idx = neighbours if neighbours else (None, None)
        neighbour_before = (
            {"index": before_idx, "text": parsed.words[before_idx].text}
            if before_idx is not None
            else None
        )
        neighbour_after = (
            {"index": after_idx, "text": parsed.words[after_idx].text}
            if after_idx is not None
            else None
        )

        for run in gap["runs"]:
            reasons: list[str] = []
            if run["duration"] > max_event_seconds:
                reasons.append(
                    f"event is {run['duration']}s, longer than "
                    f"max_event_seconds={max_event_seconds}"
                )
            if gap["duration"] > max_gap_seconds:
                reasons.append(
                    f"gap is {gap['duration']}s, wider than max_gap_seconds="
                    f"{max_gap_seconds} — too wide to prove the word map is "
                    "dense around this event"
                )
            if neighbours is None:
                reasons.append("could not resolve the words bounding this gap")

            if reasons:
                status = "disqualified"
            elif (before_idx is not None and before_idx in suspect) or (
                after_idx is not None and after_idx in suspect
            ):
                status = "suspect_neighbour"
                reasons = [
                    (
                        "a word bounding this gap claims a suspect duration, so "
                        "the narrow gap that qualified this event might itself be "
                        "hiding a swallowed retake"
                    )
                ]
            else:
                status = "attenuated"

            events.append(
                {
                    "start": run["start"],
                    "end": run["end"],
                    "duration": run["duration"],
                    "padded_start": max(gap["start"], round(run["start"] - pad, 3)),
                    "padded_end": min(gap["end"], round(run["end"] + pad, 3)),
                    "peak_db": run["peak_db"],
                    "gap": {
                        "start": gap["start"],
                        "end": gap["end"],
                        "duration": gap["duration"],
                    },
                    "neighbour_before": neighbour_before,
                    "neighbour_after": neighbour_after,
                    "status": status,
                    "reasons": reasons,
                }
            )
    return events


def attenuate_noises(
    path: Path | str,
    clip_id: str,
    *,
    db: float = -12.0,
    max_event_seconds: float = 1.5,
    max_gap_seconds: float = 2.0,
    pad: float = 0.05,
    confirm_suspect: bool = False,
    plan: bool = False,
) -> dict[str, Any]:
    """Pull down short loud non-speech events sitting in narrow word-map gaps.

    A word map has holes, and not everything loud in one is noise — the
    Scream v1 false positive was 0.4-0.9s events that turned out to be speech
    sitting in a 4.12s hole the transcript never wrote down (HISTORY.md § 2,
    `ideas/scream.md`). So an event only qualifies automatically when it is
    both short (`max_event_seconds`) *and* sitting in a gap narrow enough to
    prove the map is dense around it (`max_gap_seconds`) — a wide gap
    disqualifies even a very short, very loud event, because a narrow event
    duration is not evidence the *map* is trustworthy there. Qualifying
    events are pulled down `db` (not cut) via `energy.attenuate`'s
    `volume=...:enable='between(t,a,b)'` pass, padded `pad` seconds so the
    gain step lands in near-silence rather than clicking on the noise's edge.

    Unlike `cut_by_transcript`/`cut_by_time`, nothing here ever raises on
    what the scan finds. Those ops act on a handful of explicit,
    deliberately-chosen ranges, so refusing the call to force a look is
    right. This is an automatic scan that can turn up many independent
    candidates across a long clip; refusing the whole pass over one distant
    ambiguous candidate would defeat the point. So `suspect_neighbours` and
    `disqualified` are withheld *per event* and always reported in full —
    not gated behind `plan` the way `cut_by_transcript`'s
    `suspect_boundaries` is — which is a deliberate divergence from that
    convention, not an oversight of it.

    Three tiers: an event that qualifies on duration+gap-width *and* whose
    bounding words carry no suspect duration is attenuated automatically. An
    event whose bounding word does carry one (`suspect_neighbour`) is
    withheld from writing unless `confirm_suspect=True` — the neighbour
    might itself be hiding a swallowed retake, which would make the "gap is
    narrow" evidence unsound. `suspect_neighbours` is reported in full
    regardless of `confirm_suspect`/`plan`, so a caller can review before
    confirming; only whether it gets *written* depends on `confirm_suspect`.
    An event too long, or in too wide a gap (`disqualified`), is never
    written — no confirmation overrides it.

    Always reads the clip's *original* media (`media.original_media_path`),
    never a previous `"attenuated"` copy, so re-running with different
    parameters fully overwrites the derived file rather than compounding
    gain. `media_path()` picks the attenuated copy up automatically
    everywhere downstream once this has run.

    `plan=True` runs the identical classification — `to_write` is gated by
    `confirm_suspect` alone, exactly as a real run gates it — and reports the
    same payload, including `output_media`, the path a real run with the same
    `confirm_suspect` would write to, without calling ffmpeg or touching the
    manifest.
    """
    project = Project.open(path)
    clip = media.get_clip(project, clip_id)
    if not clip.get("has_audio"):
        raise media.MediaError(f"clip {clip_id!r} has no audio track to attenuate")
    parsed = _transcript(project, clip_id)
    source = media.original_media_path(project, clip)

    env = energy.envelope(energy.decode(source))
    claimed = [(w.start, w.end) for w in parsed.words]
    trimmed_ends = [end for _, end in energy.believable(claimed)]
    scan = energy.loud_gaps(claimed, env)

    suspect = {item["index"]: item for item in _suspect_durations(parsed)}
    events = _classify_noise_events(
        parsed,
        trimmed_ends,
        scan["gaps"],
        max_event_seconds=max_event_seconds,
        max_gap_seconds=max_gap_seconds,
        pad=pad,
        suspect=suspect,
    )

    to_write = [
        event
        for event in events
        if event["status"] == "attenuated"
        or (event["status"] == "suspect_neighbour" and confirm_suspect)
    ]

    output_media: Path | None = None
    written = False
    if to_write:
        output_media = project.attenuated_dir / f"{clip_id}{source.suffix}"
        if not plan:
            project.attenuated_dir.mkdir(parents=True, exist_ok=True)
            # Padded spans from adjacent runs in one gap can overlap; merge
            # them before building the filtergraph so ffmpeg's comma-chained
            # `volume` filters never double-attenuate the same window. This
            # is write-side only — `to_write`/`events` still report one entry
            # per detected event.
            raw_spans = [(event["padded_start"], event["padded_end"]) for event in to_write]
            spans = sp.merge_runs(raw_spans, max_gap=0.0)
            energy.attenuate(
                source, spans, db=db, has_video=bool(clip.get("has_video")), output=output_media
            )
            manifest = project.read_manifest()
            for record in manifest.get("clips", []):
                if record["clip_id"] == clip_id:
                    record["attenuated"] = str(output_media.relative_to(project.root))
                    record["attenuation"] = {
                        "db": db,
                        "max_event_seconds": max_event_seconds,
                        "max_gap_seconds": max_gap_seconds,
                        "pad": pad,
                        "events": len(to_write),
                    }
                    break
            project.write_manifest(manifest)
            written = True

    result: dict[str, Any] = {
        "clip_id": clip_id,
        "db": db,
        "gain": round(10 ** (db / 20), 4),
        "max_event_seconds": max_event_seconds,
        "max_gap_seconds": max_gap_seconds,
        "pad": pad,
        "threshold_db": scan["threshold_db"],
        "quiet_db": scan["quiet_db"],
        "speech_db": scan["speech_db"],
        "doubted_durations": scan["doubted_durations"],
        "events": events,
        "attenuated": to_write,
        "suspect_neighbours": [e for e in events if e["status"] == "suspect_neighbour"],
        "disqualified": [e for e in events if e["status"] == "disqualified"],
        "source_media": str(source),
        "output_media": str(output_media) if output_media else None,
        "written": written,
    }
    if plan:
        result["plan"] = True
    return result


# -- getting the edit out ------------------------------------------------


#: Frame rate for NLE exports from an audio-only project. Arbitrary but sane;
#: override with `fps` to match the picture the VO will be cut against.
DEFAULT_EXPORT_FPS = 30.0


#: What `export` will write itself, rather than asking auto-editor to. Both
#: names produce the same document — `.kdenlive` *is* MLT, and the extension
#: is the only thing Kdenlive cares about.
MLT_EXPORT_FORMATS = {"kdenlive", "mlt"}


#: Named export bundles (DAYDREAM.md § Export presets). Each maps to values
#: for the same four consumer keys `picture.RENDER_ARGS` already hardcodes —
#: `vcodec`/`crf`/`preset`/`acodec` — because those four, together, are the
#: combination HISTORY.md § 4 measured as memory-safe on the melt path;
#: adding a fifth key (`ab`/`width`/`height`/`progressive`) is what correlated
#: with the growth to 14.6 GB that froze the machine, and no one has since
#: isolated which addition caused it. `youtube`'s values are
#: `picture.RENDER_ARGS` verbatim — naming it changes nothing about what melt
#: already does. `web` only varies values within the same four keys.
#:
#: There is no `tiktok-reels` entry. 9:16 is mechanically producible on the
#: single-source path (`-res`), but only as a pillarbox of the 16:9 frame,
#: never a filled/reframed vertical video — that is DAYDREAM.md § Aspect
#: swap, a separately deferred item that touches the project model, both
#: render paths, and the preview letterbox. Shipping a preset named after a
#: platform that quietly pillarboxes would be exactly the kind of
#: correct-pixels-wrong-video this repo writes rules against, and on the
#: melt path a resolution override is refused outright below — so a 9:16
#: preset could not even be offered consistently across both writers.
EXPORT_PRESETS: dict[str, dict[str, str]] = {
    "youtube": {"vcodec": "libx264", "crf": "18", "preset": "medium", "acodec": "aac"},
    "web": {"vcodec": "libx264", "crf": "23", "preset": "faster", "acodec": "aac"},
}


def _resolve_preset(
    preset: str | None, resolution: tuple[int, int] | None
) -> dict[str, str] | None:
    """The consumer/quality bundle a preset name means, or `None` for the
    behavior-preserving default (`picture.RENDER_ARGS`, no `-res`).

    `"custom"` is not a fixed bundle — it means "apply `resolution` and leave
    quality at the `youtube`-equivalent default" (DAYDREAM.md's literal
    "resolution + quality" would mean accepting raw vcodec/crf/preset/acodec
    values from a caller, which widens the melt consumer to combinations
    HISTORY.md § 4 never measured; narrowed here on purpose). It requires
    `resolution` — nothing to customize is a likely caller mistake, not a
    legitimate no-op.
    """
    if preset is None:
        return None
    if preset == "custom":
        if resolution is None:
            raise ProjectError(
                "preset='custom' with no resolution customizes nothing — pass "
                "`resolution=(width, height)`, or drop the preset and use the "
                "default, 'youtube', or 'web'"
            )
        return dict(EXPORT_PRESETS["youtube"])
    if preset not in EXPORT_PRESETS:
        raise ProjectError(
            f"no export preset named {preset!r}. Available: "
            f"{sorted([*EXPORT_PRESETS, 'custom'])}. There is no 'tiktok-reels' "
            "preset: 9:16 is only producible here as a pillarbox of the 16:9 "
            "frame, never a filled/reframed vertical video — the latter is "
            "DAYDREAM.md § Aspect swap, a separately deferred item."
        )
    return dict(EXPORT_PRESETS[preset])


#: `bundle`'s keys, in the order auto-editor's own flags read them.
_AUTOEDITOR_QUALITY_FLAGS = {
    "vcodec": "-c:v",
    "crf": "-crf",
    "preset": "-preset",
    "acodec": "-c:a",
}


def _autoeditor_render_args(
    bundle: dict[str, str] | None, resolution: tuple[int, int] | None
) -> list[str]:
    """auto-editor argv for a resolved preset bundle plus an explicit resolution.

    Only ever built for the render path (`export_format=None`) — a v3 export
    writes a project file, which has no bitrate to set (`export()` refuses
    the combination before this is called).
    """
    args: list[str] = []
    if bundle is not None:
        for key, flag in _AUTOEDITOR_QUALITY_FLAGS.items():
            args += [flag, bundle[key]]
    if resolution is not None:
        args += ["-res", f"{resolution[0]},{resolution[1]}"]
    return args


def _melt_consumer_args(bundle: dict[str, str] | None) -> tuple[str, ...]:
    """The melt consumer argv for a resolved preset bundle: `picture.RENDER_ARGS`
    unchanged for the default, or `key=value` pairs for a named bundle —
    never a new key, only new values for the four already there.
    """
    if bundle is None:
        return picture.RENDER_ARGS
    return tuple(f"{key}={value}" for key, value in bundle.items())


def _is_layered(project: Project, edit: tl.Edit) -> bool:
    """Does this timeline name more than one source file?

    Two ways to get there and they hit the same wall: a cue table lays picture
    over the edit, and an edit naming two clips already holds two `src` files.
    auto-editor 31.x refuses to *export* either one (exit 2) and *renders*
    them at 720x576 with exit 0 (CLAUDE.md), so either one routes through the
    MLT writer.
    """
    if len({segment.clip_id for segment in edit.segments}) > 1:
        return True
    return bool(project.read_manifest().get("cues"))


def _mlt_resolution(project: Project) -> tuple[int, int]:
    """The canvas to declare in the MLT profile: the first real picture in the
    project, else 1080p. Cards are not consulted — scaling a still to the
    canvas is normal; sizing the canvas to a still is not.
    """
    for clip in project.read_manifest().get("clips", []):
        if clip.get("has_video") and clip.get("width") and clip.get("height"):
            return int(clip["width"]), int(clip["height"])
    return mlt.DEFAULT_RESOLUTION


def _build_mlt(project: Project, edit: tl.Edit, *, fps: float | None) -> dict[str, Any]:
    """The MLT document for this timeline, plus the facts it was built from.

    The frame grid is settled once, here, and everything downstream is handed
    it: the edit's entries come from `autoeditor.frame_layout` and the picture
    lane from `build_shots(fps=rate)`, so the two are quantised on the same
    grid by construction rather than by agreeing afterwards. `mlt.document`
    then refuses the pair if they still do not sum to the same total.

    Shared by the two things that can be done with a multi-source timeline —
    handing it to an NLE (`_export_mlt`) and rendering it (`_render_mlt`) — so
    that what gets rendered is the same document that would have been exported,
    rather than a second construction of it.
    """
    rate = float(fps) if fps else _export_fps(_clips_by_id(project))
    audio = []
    for segment, (offset, frames) in zip(edit.segments, autoeditor.frame_layout(edit, rate)):
        clip = media.get_clip(project, segment.clip_id)
        audio.append(
            mlt.Entry(
                resource=str(media.media_path(project, clip)),
                src_in=offset,
                frames=frames,
                has_video=bool(clip.get("has_video")),
            )
        )

    shots, lane = _picture_plan(project, rate)

    resolution = _mlt_resolution(project)
    document = mlt.document(
        audio=audio,
        picture=lane,
        rate=rate,
        resolution=resolution,
        name=project.read_manifest().get("name") or project.root.name,
    )
    return {
        "document": document,
        "rate": rate,
        "resolution": resolution,
        "shots": shots,
        "frames": sum(entry.frames for entry in audio),
        "sources": len({entry.resource for entry in [*audio, *lane]}),
    }


def _mlt_reply(built: dict[str, Any], edit: tl.Edit, **extra: Any) -> dict[str, Any]:
    """The fields both multi-source roads report, so they cannot drift apart."""
    return {
        "writer": extra.pop("writer"),
        "timebase": built["rate"],
        "segments": len(edit.segments),
        "shots": len(built["shots"]),
        "sources": built["sources"],
        "frames": built["frames"],
        "timeline_duration": edit.duration,
        **extra,
    }


def _export_mlt(
    project: Project,
    edit: tl.Edit,
    output: Path | str,
    *,
    export_format: str | None,
    fps: float | None,
    preset: str | None = None,
    consumer_args: tuple[str, ...] = picture.RENDER_ARGS,
) -> dict[str, Any]:
    """Write the multi-source timeline as MLT — step 4 of the layered timeline."""
    if export_format is None:
        return _render_mlt(project, edit, output, fps=fps, preset=preset, consumer_args=consumer_args)
    if export_format not in MLT_EXPORT_FORMATS:
        raise ProjectError(
            f"this timeline has more than one source, so lucid writes it itself, "
            f"and what it writes is MLT — {export_format!r} would have to go "
            "through auto-editor, whose exporter refuses a second source (exit 2). "
            f"Ask for one of {sorted(MLT_EXPORT_FORMATS)}."
        )

    built = _build_mlt(project, edit, fps=fps)
    written = mlt.write(built["document"], output)
    return _mlt_reply(
        built, edit, writer="mlt", output=str(written), format=export_format, preset=preset
    )


def _render_mlt(
    project: Project,
    edit: tl.Edit,
    output: Path | str,
    *,
    fps: float | None,
    preset: str | None = None,
    consumer_args: tuple[str, ...] = picture.RENDER_ARGS,
) -> dict[str, Any]:
    """Render the multi-source timeline through `melt` — step 5.

    auto-editor never sees this timeline: it degrades a two-source render to
    720x576 and exits 0 (CLAUDE.md), which is a file that looks like a success.
    `melt` has no source-count gate — it rendered the real 23-source Scream
    assembly at 1920x1080 (PLAN.md § The layered timeline).

    Three things this owes a reader, in the order they happen:

    * **The document goes under `$HOME`**, via `picture.scratch()`. melt runs
      from a flatpak that cannot see the host's `/tmp` and exits 0 having read
      nothing, so a project written to a temp dir would render silence.
    * **melt is asked what it would render before anything is encoded.**
      `project_frames` resolves the document without encoding a frame, and
      exact agreement there is what made 68 cut positions trustworthy before a
      render existed (HISTORY.md § 3). Disagreement refuses here rather than
      spending the encode to discover it.
    * **The finished file is measured, not believed** — `picture.render` does
      that, and only copies a render that agrees into place.

    The scratch directory survives a failure on purpose: the document melt was
    given is the evidence for what it did with it.
    """
    built = _build_mlt(project, edit, fps=fps)
    expected = built["frames"]
    work = picture.scratch("timeline-")
    project_file = mlt.write(built["document"], work / "timeline.mlt")

    declared = picture.project_frames(project_file)
    if declared != expected:
        raise ProjectError(
            f"melt reads {project_file} as {declared} frames where the timeline is "
            f"{expected} — refusing to spend an encode on a document that already "
            "disagrees with the edit. melt renders to the longest declared length "
            "it finds, so the render would have been that long too, and exited 0."
        )

    rendered = picture.render(
        project_file,
        output,
        expect_frames=expected,
        expect_resolution=built["resolution"],
        expect_duration=expected / built["rate"],
        consumer_args=consumer_args,
    )
    shutil.rmtree(work, ignore_errors=True)
    return _mlt_reply(
        built,
        edit,
        writer="melt",
        output=rendered["output"],
        format="media",
        melt_frames=declared,
        rendered=rendered,
        preset=preset,
    )


def _render_single(
    payload: dict[str, Any],
    output: Path | str,
    *,
    export_format: str | None,
    render_args: list[str],
    resolution: tuple[int, int] | None,
) -> tuple[Path, dict[str, Any]]:
    """Render (or export) a single-source v3 timeline through auto-editor.

    When `resolution` was explicitly requested, this owes the same discipline
    `picture.render` already applies on the melt path: auto-editor's exit
    code proves nothing (CLAUDE.md — the 31.x multi-source degrade exits 0 at
    720x576), so the render is staged, the staged file is probed, and it is
    copied to `output` only if it agrees — reusing `picture.render_problems`
    to decide agreement, the same predicate the melt path already trusts.
    A disagreement raises and leaves the staged file where it landed, for the
    same reason `picture.render` does: the evidence is the file, not the exit
    status.

    `resolution=None` (the common case — no preset, or a preset with no
    resolution) skips staging entirely and writes straight to `output`,
    unchanged from before this function existed. `render_args` is only
    forwarded when it is non-empty, for the same reason — a call this makes
    with nothing new to ask for is byte-identical to the call `export()` made
    before `render_args` existed.
    """
    extra_args: dict[str, Any] = {"render_args": render_args} if render_args else {}
    if resolution is None:
        written = autoeditor.run_timeline(payload, output, export=export_format, **extra_args)
        return written, {}

    work = Path(tempfile.mkdtemp(prefix="lucid-render-"))
    staged = work / (Path(output).name or "render.mp4")
    written = autoeditor.run_timeline(payload, staged, export=export_format, **extra_args)

    measured = media.probe(written).as_dict()
    problems = picture.render_problems(measured, expect_resolution=resolution)
    if problems:
        raise ProjectError(
            f"the render disagrees with the resolution it was asked for, so it "
            f"has not been copied to {output}. It is at {written}, kept so the "
            "numbers can be checked against it:\n- " + "\n- ".join(problems)
        )

    destination = Path(output).expanduser()
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(written, destination)
    shutil.rmtree(work, ignore_errors=True)

    notes: list[str] = []
    extra: dict[str, Any] = {}
    if measured.get("has_video"):
        extra["resolution"] = [measured["width"], measured["height"]]
    else:
        extra["resolution"] = None
        notes.append("this render has no video stream — the requested resolution did not apply")
    extra["notes"] = notes
    return destination, extra


def export(
    path: Path | str,
    output: Path | str,
    *,
    export_format: str | None = "kdenlive",
    fps: float | None = None,
    preset: str | None = None,
    resolution: tuple[int, int] | None = None,
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

    **A multi-source project takes a different road entirely** (steps 4 and 5
    of the layered timeline): lucid generates the MLT itself, through `mlt`,
    and renders it with `melt`, because auto-editor refuses to export more than
    one `src` (exit 2) and degrades the render to 720x576 with exit 0. The
    choice is made from the project, not from a flag — a cue table or a second
    clip on the timeline *is* a multi-source timeline, and there is no
    combination of arguments that should route one through the path that
    silently ruins it. The reply says which road was taken: `"writer"` is
    `"auto-editor"`, `"mlt"`, or `"melt"`.

    `preset` names one of `EXPORT_PRESETS` (`"youtube"`, `"web"`) or
    `"custom"` (which requires `resolution`) — a bundle of the same four
    consumer keys `picture.RENDER_ARGS` already hardcodes on the melt path,
    and of auto-editor's own quality flags on the single-source path.
    `resolution` sets a `WIDTH,HEIGHT` output size on the single-source path
    only — **it letterboxes the existing 16:9 frame, it does not crop or
    reframe it**, so it is not a substitute for a vertical/9:16 export. There
    is deliberately no `"tiktok-reels"` preset: 9:16 needs a real reframe,
    which is DAYDREAM.md § Aspect swap, a separately deferred item that
    touches the project model, both render paths, and the preview letterbox.
    Neither `preset` nor `resolution` may be combined with a non-`None`
    `export_format` — an NLE project file has no bitrate to set. `resolution`
    on a layered (multi-source) project is refused outright: widening the
    melt consumer to accept it was not re-isolated as memory-safe after
    HISTORY.md § 4's growth to 14.6 GB, so a single-source project is the
    workaround for now. When `resolution` was honoured, the reply's
    `"resolution"` is the *measured* size the finished file actually has —
    checked against the exit code proving nothing, same discipline as the
    melt path — and is `None` with a `"notes"` entry on an audio-only render,
    where a requested resolution has nothing to apply to.
    """
    if (preset is not None or resolution is not None) and export_format is not None:
        raise ProjectError(
            "preset/resolution set the encode of rendered media — an NLE "
            f"handoff ({export_format!r}) writes a project file, which has no "
            "bitrate or pixel size of its own. Pass export_format=None to "
            "render, or drop preset/resolution to export the project as-is."
        )
    bundle = _resolve_preset(preset, resolution)

    project = Project.open(path)
    edit = _load_edit(project)
    if not edit.segments:
        raise ProjectError("the timeline is empty — nothing to export")

    clips = _clips_by_id(project)
    if _is_layered(project, edit):
        if resolution is not None:
            raise ProjectError(
                "this timeline has more than one source, so it renders through "
                "melt, and melt's consumer is deliberately hardcoded to the "
                "codec and nothing else — adding width/height to it is what "
                "correlated with unbounded memory growth to 14.6 GB and froze "
                "the machine (HISTORY.md § 4), and no one has since isolated "
                "resolution as safe on its own. Render a single-source project "
                "if you need a specific resolution, or drop `resolution` and "
                "export at the project's own picture size."
            )
        return _export_mlt(
            project,
            edit,
            output,
            export_format=export_format,
            fps=fps,
            preset=preset,
            consumer_args=_melt_consumer_args(bundle),
        )

    primary = clips[edit.segments[0].clip_id]
    header = autoeditor.template(media.media_path(project, primary))

    if export_format is None:
        timebase = _rate(project)
    else:
        timebase = float(fps) if fps else _export_fps(clips)
    # `to_v3` reads each entry's "src" straight off the record it is given —
    # resolve every clip through media_path() here so an attenuated copy
    # (or a NAS symlink fallback) is what actually gets rendered/exported,
    # not the raw, immutable `source` field.
    resolved_clips = {
        clip_id: {**record, "source": str(media.media_path(project, record))}
        for clip_id, record in clips.items()
    }
    payload = autoeditor.to_v3(edit, resolved_clips, header=header, timebase=timebase)

    # A preset's flags are all video-encoding flags (`-c:v`/`-crf`/`-preset`)
    # plus `-c:a` — meaningless, and on some containers (a .wav destination
    # forcing `-c:a aac`, verified live) outright fatal, on a project with no
    # picture. Skip them there rather than let auto-editor fail on a
    # combination nobody asked for; `_render_single` still reports the
    # documented no-op note when `resolution` was requested.
    has_picture = bool(payload.get("v"))
    render_args = (
        _autoeditor_render_args(bundle, resolution)
        if export_format is None and has_picture
        else []
    )
    written, extra = _render_single(
        payload,
        output,
        export_format=export_format,
        render_args=render_args,
        resolution=resolution if export_format is None else None,
    )
    return {
        "output": str(written),
        "format": export_format or "media",
        "writer": "auto-editor",
        "timebase": timebase,
        "segments": len(edit.segments),
        "timeline_duration": edit.duration,
        "preset": preset,
        **extra,
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
      68 cut positions on the Scream essay trustworthy (HISTORY.md § 3).
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
    mapping_trusted = abs(target_duration - expected_duration) <= half_frame

    notes: list[str] = []
    if not mapping_trusted:
        notes.append(
            f"target_duration ({target_duration:.3f}s) disagrees with the current "
            f"timeline's export grid ({expected_duration:.3f}s) by more than a frame "
            f"at {rate}fps — this render may be stale, so clip/word mapping is "
            "refused. Run check_frames against it for the stronger check."
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
    the render with nothing in lucid's index pointing at it (HISTORY.md § 2). The
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
