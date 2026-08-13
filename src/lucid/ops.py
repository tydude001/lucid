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
import statistics
import subprocess
import tempfile
import time
from collections.abc import Iterable, Sequence
from dataclasses import replace
from itertools import pairwise
from math import gcd, hypot
from pathlib import Path
from typing import Any

from lucid import (
    asr,
    autoeditor,
    captions,
    energy,
    faces,
    graphics,
    media,
    mlt,
    picture,
)

# `describe` is also the name of the op below — the same collision `verify`
# has, and the same fix.
from lucid import describe as dsc
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


def migrate(path: Path | str, *, plan: bool = False) -> dict[str, Any]:
    """Bring an older project manifest forward to the current schema version.

    Every other op goes through `Project.open`, which refuses a manifest it
    does not recognise rather than guessing at its shape; this is what clears
    that refusal. Forward-only, and the pre-migration manifest is copied into
    `cache/history/` before anything is written.
    """
    return Project.migrate(path, plan=plan)


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


def _overlaps(parsed: tx.Transcript) -> list[dict[str, Any]]:
    """Flag seams where two words' timings overlap — an invented word's tell.

    The third of the attach-time checks, and it catches what the other two
    structurally cannot. `_near_duplicates` matches *phrases*, so a splice
    that invents a single word repeats nothing for it to match
    (`coincidence incidents`, `guy's guys`, `is genu genuinely`); measured on
    the Scream VO, 39 of 56 overlapping pairs fall outside every
    near-duplicate window. `_suspect_durations` looks at one word's length,
    and a seam's words are ordinary-length — they are merely in two places at
    once. HISTORY.md § The hand-framed teaser, watched.

    The echo is the point here as much as anywhere else (CLAUDE.md): a seam
    reads as correct English on its own and the neighbours are what show it
    is a splice.
    """
    seams = tx.find_overlaps(parsed.words)
    for seam in seams:
        seam.update(_context(parsed, seam["first_word"], seam["last_word"]))
    return seams


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
        "overlaps": _overlaps(parsed),
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
        "overlaps": _overlaps(parsed),
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


def transcript_checks(path: Path | str, clip_id: str | None = None) -> dict[str, Any]:
    """Re-run the attach-time transcript checks over what is already attached.

    The three findings `attach_transcript` returns are computed once, at
    attach, and handed back in that call's result — so a project attached
    before a check existed can never see it. That is not hypothetical: the
    Scream VO was attached long before `overlaps`, and its 40 seams were
    invisible to the project holding it. Re-attaching to surface a finding
    would mean re-running ASR or hunting down the original whisper JSON, so
    the checks are addressable on their own.

    Reads only — nothing here writes to the project, which is what makes it
    safe to run over a finished cut.
    """
    project = Project.open(path)
    if clip_id is not None:
        wanted = [clip_id]
    else:
        wanted = [
            c["clip_id"]
            for c in project.read_manifest().get("clips", [])
            if project.transcript_path(c["clip_id"]).exists()
        ]

    clips = []
    for cid in wanted:
        parsed = _transcript(project, cid)
        clips.append(
            {
                "clip_id": cid,
                "words": len(parsed),
                "near_duplicates": _near_duplicates(parsed),
                "suspect_durations": _suspect_durations(parsed),
                "overlaps": _overlaps(parsed),
            }
        )
    return {"clips": clips}


# -- footage descriptions ---------------------------------------------------
#
# Step 1 of PLAN.md § B-roll by description. **A description indexes the
# source, which is why an edit cannot invalidate it**: the unit is
# `(clip_id, src_start, src_end, text)` in *source* seconds, and the b-roll
# asset is not the thing being cut, so its own times never renumber. That is
# the same property word indices have, and the reason nothing here needs a
# re-describe hook on edit.
#
# They live in the manifest rather than a sidecar directory or `cache/`: they
# are per-clip metadata `info` should report, they have no natural filename,
# and they cost GPU minutes, which is not what `cache/` is for.


def _descriptions(project: Project) -> list[dict[str, Any]]:
    return list(project.read_manifest().get("descriptions", []))


def _describable(project: Project, clip_id: str | None) -> list[dict[str, Any]]:
    """The clips `describe` can look at, refusing an audio-only one by name.

    Naming it matters: the Scream project's VO is a `.wav`, and "describe the
    project" quietly skipping it reads the same as describing it and finding
    nothing worth saying.
    """
    if clip_id is not None:
        clip = media.get_clip(project, clip_id)
        if not clip.get("has_video"):
            raise ProjectError(
                f"clip {clip_id!r} has no video track, so there is nothing to "
                "describe — descriptions index pictures, not dialogue. Its "
                "words are what `transcribe` indexes."
            )
        return [clip]
    clips = project.read_manifest().get("clips", [])
    return [c for c in clips if c.get("has_video")]


def describe(
    path: Path | str,
    clip_id: str | None = None,
    *,
    window: float = dsc.WINDOW,
    force: bool = False,
    plan: bool = False,
) -> dict[str, Any]:
    """Describe a clip's footage — or every video clip's — in fixed windows.

    This is a **job, not a request**: cost is per window at roughly three
    seconds each, so a project's footage is minutes of GPU time. `plan=True`
    resolves the whole work list and the estimate without loading a model,
    which is the only way to ask "what would this cost" without paying it.

    Already-described clips are skipped unless `force`, so re-running after
    importing one new clip describes one clip. `force` re-describes and
    replaces, since a description is derived and there is nothing in it to
    lose.

    The windows are fixed and are never widened to save time — a whole-clip
    pass invents people (`describe`'s module docstring). The two error
    classes the measurement left standing ride along on every result rather
    than being smoothed over: `errors` names windows the model could not
    describe, and `truncated` names ones whose text stops mid-sentence.
    """
    project = Project.open(path)
    clips = _describable(project, clip_id)
    existing = _descriptions(project)
    already = {d["clip_id"] for d in existing}

    todo: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    windows: list[dict[str, Any]] = []
    for clip in clips:
        if clip["clip_id"] in already and not force:
            skipped.append(
                {
                    "clip_id": clip["clip_id"],
                    "why": "already described — pass force to describe it again",
                    "windows": sum(1 for d in existing if d["clip_id"] == clip["clip_id"]),
                }
            )
            continue
        source = media.media_path(project, clip)
        spans = dsc.plan_windows(float(clip["duration"]), window=window)
        for start, end in spans:
            windows.append(
                {
                    "index": len(windows),
                    "clip_id": clip["clip_id"],
                    "media": str(source),
                    "src_start": start,
                    "src_end": end,
                    "timestamps": dsc.frame_times(start, end),
                }
            )
        todo.append({"clip_id": clip["clip_id"], "windows": len(spans)})

    report: dict[str, Any] = {
        "project": str(project.root),
        "window": window,
        "clips": todo,
        "skipped": skipped,
        "windows": len(windows),
        # 3.5s per window, near enough constant regardless of how much footage
        # the window spans, plus the model load the run pays once. Measured on
        # the whole Scream project at 1920x816 rather than taken from the
        # note's per-clip spike, which saw 2.6-3.3s on smaller frames.
        #
        # The load is in here because leaving it out makes the estimate wrong
        # by 3x on exactly the small runs someone checks it against: three
        # windows is 10s of describing and 25s of waiting.
        "estimated_seconds": round(len(windows) * 3.5 + 15) if windows else 0,
    }
    if plan:
        report["plan"] = True
        report["runtime"] = dsc.available()
        return report
    if not windows:
        report["described"] = 0
        report["errors"] = []
        report["truncated"] = []
        return report

    started = time.monotonic()
    # The worker takes the whole list at once and loads the model once for
    # it — ~15s of loading against ~3s per window, so a process per clip
    # would spend most of the run loading the same weights again.
    results = dsc.describe_windows(
        [{"index": w["index"], "media": w["media"], "timestamps": w["timestamps"]} for w in windows]
    )

    stored: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    truncations: list[dict[str, Any]] = []
    for spec, result in zip(windows, results, strict=True):
        where = {
            "clip_id": spec["clip_id"],
            "src_start": round(spec["src_start"], 3),
            "src_end": round(spec["src_end"], 3),
        }
        if "error" in result:
            errors.append({**where, "error": result["error"]})
            continue
        text = result["text"].strip()
        entry = {
            **where,
            "text": text,
            "truncated": dsc.truncated(text),
            "origin": f"qwen2.5-vl:{window:g}s/{dsc.FRAMES_PER_WINDOW}f",
        }
        stored.append(entry)
        if entry["truncated"]:
            truncations.append(where)

    redescribed = {w["clip_id"] for w in windows}
    manifest = project.read_manifest()
    kept = [d for d in manifest.get("descriptions", []) if d["clip_id"] not in redescribed]
    manifest["descriptions"] = sorted(
        kept + stored, key=lambda d: (d["clip_id"], d["src_start"])
    )
    project.write_manifest(manifest)

    report["described"] = len(stored)
    report["errors"] = errors
    report["truncated"] = truncations
    report["seconds"] = round(time.monotonic() - started, 1)
    return report


def describe_ls(
    path: Path | str,
    clip_id: str | None = None,
    *,
    contains: str | None = None,
) -> dict[str, Any]:
    """List the footage descriptions — the read half of b-roll by description.

    Read-only, and this *is* the search: no ranking, no embeddings, no
    similarity threshold. The descriptions are text, and whoever is looking
    reads them and picks. That holds up to a measured ceiling of roughly 600
    windows, past which reading them in one go stops being reasonable and a
    cross-project library would be the trigger to revisit (PLAN.md § B-roll by
    description). `words` reports the size of what came back so that cost is
    visible rather than guessed at.

    `contains` is a convenience on top, not a subsystem: whitespace-separated
    terms matched case-insensitively, and **every** term must appear somewhere
    in a description for it to match — so `"kitchen knife"` finds "a knife on
    the kitchen counter". The terms it split into come back under `filter`,
    the same reason a word-indexed tool echoes what it landed on.

    Ordered by `(clip_id, src_start)`: source order, which is the order the
    footage runs in and which no edit can renumber. `clips` covers **every**
    video clip in the project, described or not, so a zero there reads as "not
    described yet" rather than "no such clip".
    """
    project = Project.open(path)
    stored = _descriptions(project)
    total = len(stored)

    terms = (contains or "").split()
    entries = [
        d
        for d in stored
        if (clip_id is None or d["clip_id"] == clip_id)
        and all(term.lower() in d["text"].lower() for term in terms)
    ]
    entries.sort(key=lambda d: (d["clip_id"], d["src_start"]))

    # Every video clip, not just the described ones: "clipa: 0" is the answer
    # to "is this footage indexed", and leaving it out makes an undescribed
    # clip indistinguishable from a clip_id that does not exist.
    described: dict[str, list[dict[str, Any]]] = {}
    for d in stored:
        described.setdefault(d["clip_id"], []).append(d)
    clips = []
    for clip in _describable(project, None):
        cid = clip["clip_id"]
        mine = described.get(cid, [])
        clips.append(
            {
                "clip_id": cid,
                "windows": len(mine),
                "described_seconds": round(sum(d["src_end"] - d["src_start"] for d in mine), 3),
                # Rounded to match `described_seconds`, because the pair is
                # read as a coverage check and 14.013 against 14.013292 looks
                # like a shortfall that is not there.
                "duration": round(float(clip["duration"]), 3),
                # Truncated entries read exactly like complete ones to whoever
                # searches them, so the count rides along here too.
                "truncated": sum(1 for d in mine if d.get("truncated")),
            }
        )

    return {
        "descriptions": entries,
        "count": len(entries),
        # What a filter matched *out of*: three hits with no total reads the
        # same as a project with three descriptions in it.
        "total": total,
        "words": sum(len(d["text"].split()) for d in entries),
        "clips": clips,
        "filter": {"clip_id": clip_id, "contains": contains, "terms": terms},
    }


#: What a clip *is*, in one sentence of prose — the corpus a picker needs, and
#: a different kind of fact from a `describe` window. A description says what
#: is in front of the camera; a synopsis says what the footage *is*, which for
#: found footage means naming the work, the scene and the people. Absent means
#: nobody has said, which is what every project written before this key existed
#: meant, so it is additive the way `CANVAS_KEY` is and takes no
#: `SCHEMA_VERSION` bump. HISTORY.md § Choosing the b-roll.
SYNOPSIS_KEY = "synopsis"

#: Prose for a reader who already knows the material, not a search field. The
#: cap keeps it from quietly becoming a second transcript: every clip's
#: synopsis has to fit in one prompt *beside* the whole narration, and the
#: measurement that chose this mechanism used lines of about this length.
SYNOPSIS_MAX = 800


def synopsis(
    path: Path | str,
    clip_id: str | None = None,
    text: str | None = None,
    *,
    clear: bool = False,
) -> dict[str, Any]:
    """Read, set or clear a clip's one-line synopsis.

    Read/write/clear on one entry point, the shape `canvas` already uses:
    no `clip_id` lists every clip's synopsis, `clip_id` alone reads one,
    `text` writes, `clear` removes. Listing is the common call — a picker
    wants the whole catalogue, never one line.

    **This is the field that decides which clip goes under a sentence, and
    `descriptions` is not.** Measured on the Scream footage against 25 human
    choices: the vision index agreed 2 times, the clips' own filenames 3, and
    a synopsis catalogue read by a model that knows the films, 13. The reason
    is not that the descriptions were bad — they are accurate — it is that the
    connection is never lexical. "Every one of those is further outside the
    film than the one before it" belongs over the Scream VI reveal because its
    killers are a family avenging someone from the last movie, and no
    description of those pixels contains any word of that sentence. So a
    synopsis is *allowed and expected* to carry what a camera cannot see:
    who wrote it, what the twist means, which entry in the series it is.
    HISTORY.md § Choosing the b-roll.

    Nothing generates these. A VLM cannot — that is the finding — and lucid
    will not guess a title from a filename, because a wrong synopsis is worse
    than an absent one: it produces confident, plausible, wrong placements
    rather than an empty catalogue somebody notices. `broll_brief` reports
    which clips are missing one instead.
    """
    project = Project.open(path)
    manifest = project.read_manifest()
    clips = manifest.get("clips", [])

    if clip_id is None:
        if text is not None or clear:
            raise ProjectError("naming a clip_id is what says which synopsis to write")
        return {
            "clips": [
                {"clip_id": c["clip_id"], "synopsis": c.get(SYNOPSIS_KEY)} for c in clips
            ],
            "missing": [c["clip_id"] for c in clips if not c.get(SYNOPSIS_KEY)],
            "count": len(clips),
        }

    record = media.get_clip(project, clip_id)
    if text is not None and clear:
        raise ProjectError("pass text to write a synopsis or clear to remove it, not both")

    written = False
    if clear:
        record.pop(SYNOPSIS_KEY, None)
        written = True
    elif text is not None:
        text = " ".join(str(text).split())
        if not text:
            raise ProjectError(
                "an empty synopsis is not the same as no synopsis — pass clear to remove one"
            )
        if len(text) > SYNOPSIS_MAX:
            raise ProjectError(
                f"synopsis is {len(text)} characters, over the {SYNOPSIS_MAX} cap — every "
                "clip's has to fit in one prompt beside the narration, so this is a "
                "sentence or three about what the footage is, not a summary of the work"
            )
        record[SYNOPSIS_KEY] = text
        written = True

    if written:
        for index, existing in enumerate(clips):
            if existing["clip_id"] == clip_id:
                clips[index] = record
                break
        project.write_manifest(manifest)
    return {
        "clip_id": clip_id,
        "synopsis": record.get(SYNOPSIS_KEY),
        "written": written,
        "cleared": bool(clear),
    }


# -- cards -----------------------------------------------------------------
#
# Step 1 of PLAN.md § Motion graphics and templates: the asset a `card:` cue
# resolves to, generated rather than drawn elsewhere and copied in. SVG is the
# source and PNG the rasterisation, both kept — the cue table and the preview
# `<img>` want a raster, and a card you cannot re-edit is a card you redraw
# from scratch to change a year.
#
# Step 2 of PLAN.md § Aspect swap added the *record*: the two files on disk
# have the canvas baked into them (the SVG's viewBox, the PNG's pixels), so
# the shape of a card is not derivable from the card. `cards` in the manifest
# is what it was made from, and `card_reauthor` is what turns that back into
# the two files at whatever shape the project is now. This one is a schema
# bump where `assets/cards/` was not, for the reason CLAUDE.md gives: it is a
# list another op would `setdefault`, so the version number is what makes it
# true rather than incidentally survivable.

#: Card records in the manifest, one per card `card_new` has made:
#: `{"card", "template", "slots", "canvas"}` — geometry and content, never a
#: length, so nothing here is in tension with PLAN.md § The property
#: everything below defends.
CARDS_KEY = "cards"


def _card_records(project: Project) -> list[dict[str, Any]]:
    return list(project.read_manifest().get(CARDS_KEY, []))


def _card_record(project: Project, name: str) -> dict[str, Any] | None:
    for record in _card_records(project):
        if record.get("card") == name:
            return record
    return None


def _write_card_record(project: Project, record: dict[str, Any]) -> None:
    """Store what a card was made from, replacing any record of that name.

    Replaces rather than appends because a card name is the key a cue points
    at: two records for one name would make "what is this card" a question
    with two answers, and `card_reauthor` would draw whichever came first.
    """
    manifest = project.read_manifest()
    records = [r for r in manifest.setdefault(CARDS_KEY, []) if r.get("card") != record["card"]]
    records.append(record)
    manifest[CARDS_KEY] = records
    project.write_manifest(manifest)


def _cards_on_disk(project: Project) -> list[str]:
    """Every card name with a file under `assets/cards/`, SVG or PNG.

    Both extensions, because the two are separately sufficient to make a card
    real: an SVG with no PNG is a card no cue can resolve yet, and a PNG with
    no SVG is a card made outside lucid — which is what the Scream project
    holds, and the reason `card_new`'s guard cannot look at the SVG alone.
    """
    if not project.cards_dir.is_dir():
        return []
    return sorted({p.stem for p in project.cards_dir.iterdir() if p.suffix in (".svg", ".png")})


def card_templates() -> dict[str, Any]:
    """Every card template lucid ships, with the slots each one takes.

    Takes no project: a template is package data, the same for every one.
    """
    return {"templates": graphics.templates()}


def card_new(
    path: Path | str,
    name: str,
    template: str,
    slots: dict[str, Any],
    *,
    width: int | None = None,
    height: int | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Fill `template`'s slots and land both files under `assets/cards/`.

    The SVG is written first and then rendered *from disk* by the same
    `card_render` an edit-and-re-render would use — not from the string in
    memory. One path, so a card made here and a card re-rendered later
    cannot diverge.

    **The canvas defaults to the project's own** — `_mlt_resolution`, the
    same number the MLT profile declares — which is step 3 of PLAN.md
    § Motion graphics and templates and what closes its finding 4. That
    finding measured a 1920x1080 card in the Scream cut's 1920x816 frame
    losing 465 px of width, 24%, to black bar. The fix is not to resize on
    the way in: `-size` fits rather than distorts, so a card authored at the
    wrong aspect pillarboxes whatever it is scaled to. It is to *author* at
    the canvas, which a template can do because its geometry is in
    1920-wide units and its viewBox is written to the aspect it is asked for.

    Refused if the card already exists, unless `overwrite`. A card is
    referenced by cues, and silently replacing the asset under one is the
    kind of edit nobody can see happen. **Either file is enough to exist** —
    a card made outside lucid has a PNG and no SVG, and a guard that looked
    only at the source would overwrite the raster a cue resolves to without
    ever tripping.

    What it was made from is recorded in the manifest (`cards`), which is
    what lets `card_reauthor` draw it again at a different canvas. The record
    is written after both files land, so a template error leaves no record of
    a card that does not exist.
    """
    project = Project.open(path)
    _card_name(name)
    if (width is None) != (height is None):
        raise ProjectError(
            "card_new takes both width and height or neither — one alone "
            "would have to guess the other, and the guess would be a card "
            "that pillarboxes in the frame it was made for"
        )
    canvas_from = "project"
    if width is None or height is None:
        width, height = _mlt_resolution(project)
        canvas_from = "project"
    else:
        canvas_from = "requested"
    source = project.cards_dir / f"{name}.svg"
    existing = [p for p in (source, project.cards_dir / f"{name}.png") if p.exists()]
    if existing and not overwrite:
        raise ProjectError(
            f"a card named {name!r} already exists at "
            f"{', '.join(str(p) for p in existing)} — pass overwrite "
            "to replace it, remembering that any cue pointing at card:"
            f"{name} will show the new one"
        )

    # Which *file* the canvas picked, not just the canvas: a variant shipping
    # changes what a shape draws without changing the shape, and then
    # `card_reauthor`'s sweep has nothing to compare and reports the project
    # up to date. Additive and optional — absent means the record predates
    # variants, which is the same as none, so it is not a schema bump.
    variant = graphics.template_layout(template, width, height)["variant"]
    svg = graphics.fill_template(template, dict(slots), width=width, height=height)
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(svg, encoding="utf-8")
    rendered = card_render(path, name)
    _write_card_record(
        project,
        {
            "card": name,
            "template": template,
            "slots": dict(slots),
            "canvas": f"{width}x{height}",
            **({"variant": variant} if variant else {}),
        },
    )
    return {
        "template": template,
        "canvas": f"{width}x{height}",
        "canvas_from": canvas_from,
        "variant": variant,
        "recorded": True,
        **rendered,
    }


def _card_name(name: str) -> str:
    if not name or "/" in name or name.startswith("."):
        raise ProjectError(
            f"card name {name!r} is not a card name — it is the `<name>` in "
            "`card:<name>`, so it names one file in assets/cards/, not a path"
        )
    return name


def card_render(
    path: Path | str,
    name: str,
    *,
    width: int | None = None,
    height: int | None = None,
) -> dict[str, Any]:
    """Rasterise `assets/cards/<name>.svg` to the PNG its cue resolves to.

    The PNG is what `_resolve_asset` looks for, and it is written beside the
    source under exactly the name `card:<name>` resolves to — a card
    rasterised anywhere else is a card the cue table cannot find, and the
    error for that arrives at export.

    The font report rides along on every call because it is the only guard
    there is: a card naming a face this box lacks renders pixel-identically
    to one naming a face it has, at exit 0 (`graphics`' docstring). It
    reports and does not prevent, the same call `captions.font_match` made.
    """
    project = Project.open(path)
    _card_name(name)
    source = project.cards_dir / f"{name}.svg"
    if not source.is_file():
        existing = sorted(p.name for p in project.cards_dir.glob("*.svg"))
        raise ProjectError(
            f"no card source at {source} (cards with an SVG source: "
            f"{', '.join(existing) or 'none'})"
        )
    rendered = graphics.render_svg(
        source, project.cards_dir / f"{name}.png", width=width, height=height
    )
    return {"card": name, "asset": f"card:{name}", **rendered}


def card_reauthor(
    path: Path | str,
    name: str | None = None,
    *,
    plan: bool = False,
) -> dict[str, Any]:
    """Draw recorded cards again, at the shape the project renders at now.

    Step 2 of PLAN.md § Aspect swap, and the thing that gates step 3: a
    vertical render with the old 16:9 cards pillarboxed inside it is the
    failure the item exists to close, not a partial win. **Cards are the only
    project state that is rasterised rather than derived** — captions survive
    a canvas change because they come off `caption_style` every time, while a
    card has its canvas baked into the SVG's viewBox and the PNG's pixels.
    This is what makes one derivable after the fact: the record says what it
    was made from, and the card is authored again from that at
    `_mlt_resolution`, which is `card_new`'s own default and the number the
    MLT profile declares.

    **It re-authors rather than resizes**, for the reason `render_svg` has no
    resize path: `-size` *fits*, so rasterising a 16:9 document into a 9:16
    frame pillarboxes the card inside the frame rather than reflowing it.
    Only `fill_template` can put the geometry at a new aspect, and only the
    record can feed it.

    With no `name` this sweeps: every recorded card whose canvas is not the
    project's, whose *layout* is not the one that canvas now resolves to, plus
    any whose files have gone missing. Named, it redraws that one whatever its
    canvas — an explicit ask is not second-guessed.

    **The layout half is not redundant with the canvas half**, and the day a
    variant ships is when that shows. A portrait file appearing changes what
    1080x1920 draws without changing 1080x1920, so a canvas-only sweep answers
    `redrawn: 0` over twelve cards that are all still the old layout — the
    project reads as up to date and every card is wrong. So the record says
    which file it was drawn from and the sweep compares that too.

    **A card with no record is reported, never skipped quietly.** Nothing on
    disk can recover what a card was made from, so the honest output is its
    name and the fact that `card new --overwrite` is the way back — which is
    also how such a card gains a record. `plan` resolves and writes nothing.

    There is deliberately no size argument. A card authored at anything but
    the project canvas is finding 4 of the note all over again, and the knob
    for "render at a different shape" is `canvas`, one level up.
    """
    project = Project.open(path)
    width, height = _mlt_resolution(project)
    canvas_now = f"{width}x{height}"

    records = _card_records(project)
    known = {r.get("card") for r in records}
    unrecorded = [c for c in _cards_on_disk(project) if c not in known]

    if name is not None:
        _card_name(name)
        record = _card_record(project, name)
        if record is None:
            where = "it has files on disk but no record" if name in unrecorded else "no such card"
            raise ProjectError(
                f"nothing recorded for card {name!r} — {where}. A record says what a "
                "card was made from, and no file on disk carries that; make it again "
                f"with `card new {name} --template ... --overwrite`, which records it "
                "and leaves every later swap a single command"
            )
        records = [record]

    results = []
    for record in records:
        card = record.get("card")
        was = str(record.get("canvas") or "")
        variant_was = record.get("variant")
        variant_now = graphics.template_layout(str(record.get("template")), width, height)["variant"]
        svg = project.cards_dir / f"{card}.svg"
        png = project.cards_dir / f"{card}.png"
        missing = [p.name for p in (svg, png) if not p.is_file()]
        if name is not None:
            why = "asked for"
        elif missing:
            why = "missing " + " and ".join(missing)
        elif was != canvas_now:
            why = f"{was or 'unrecorded canvas'} -> {canvas_now}"
        elif variant_was != variant_now:
            why = f"layout {variant_was or 'base'} -> {variant_now or 'base'}"
        else:
            why = ""
        entry: dict[str, Any] = {
            "card": card,
            "template": record.get("template"),
            "canvas_was": was or None,
            "canvas": canvas_now,
            "variant_was": variant_was,
            "variant": variant_now,
            "redrawn": bool(why) and not plan,
            "why": why or "already at the project canvas",
        }
        if why and not plan:
            drawn = card_new(
                project.root,
                str(card),
                str(record.get("template")),
                dict(record.get("slots") or {}),
                width=width,
                height=height,
                overwrite=True,
            )
            entry["asset"] = drawn["asset"]
            entry["width"] = drawn["width"]
            entry["height"] = drawn["height"]
            entry["font_warnings"] = drawn["font_warnings"]
        results.append(entry)

    return {
        "project": str(project.root),
        "canvas": canvas_now,
        "cards": results,
        "redrawn": sum(1 for e in results if e["redrawn"]),
        "to_redraw": sum(1 for e in results if e["why"] != "already at the project canvas"),
        # Named rather than counted: the name is what a caller needs to make
        # one of these right, and the count is what lets it be ignored.
        "unrecorded": unrecorded,
        "plan": bool(plan),
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


def cue_add(
    path: Path | str,
    clip_id: str,
    word_index: int,
    asset: str,
    *,
    src_start: float | None = None,
) -> dict[str, Any]:
    """Add a cue: from `word_index` of `clip_id` onward, show `asset`.

    Source-addressed, like every other word-indexed tool here — `asset` is
    not resolved or checked against disk; that is the shot projection's job
    (step 2), which also knows how to turn a `card:name` key into a path.
    Refused if a cue already sits at this exact word; remove it first with
    `cue_rm` to replace it, so a call can never silently pick a winner
    between two assets at the same word.

    `src_start` **pins the in-point**: seconds into `asset`, in that asset's
    own source time, which is exactly what a `describe_ls` window reports
    (PLAN.md § B-roll by description). Omit it and the shot reads from
    wherever `mlt.plan_picture`'s per-asset cursor has got to — the right
    default for re-using a clip, and wrong for placing a moment somebody
    searched for.

    **It is an in-point only, never a range.** The out-point stays derived
    from the next cue through the edit, because a cue carrying its own length
    is the failure PLAN.md § The property everything below defends exists to
    prevent — the music bed's lengths were tuned to a runtime and a later
    append invalidated every one of them. What the pin costs instead is a
    refusal: a pinned shot that outruns its asset is `plan_picture`'s error,
    not a rewind, and it surfaces on the picture lane as `shots_error`.

    Nothing here checks the pin against the asset's duration, for the same
    reason nothing here resolves the asset: that needs media on disk, and it
    is the projection's job. What it does check is the pin's own arithmetic —
    a negative in-point, or one on a `card:`, where a held frame has no
    playhead to move.
    """
    project = Project.open(path)
    media.get_clip(project, clip_id)
    parsed = _transcript(project, clip_id)
    word_index = int(word_index)
    echo = _cue_echo(parsed, word_index)

    cue: dict[str, Any] = {"clip_id": clip_id, "word_index": word_index, "asset": asset}
    if src_start is not None:
        src_start = float(src_start)
        if src_start < 0:
            raise tx.TranscriptError(
                f"src_start {src_start} is before the start of {asset!r} — an "
                "in-point is seconds into the asset, in its own source time"
            )
        if asset.startswith("card:"):
            raise tx.TranscriptError(
                f"asset {asset!r} is a card, and a still has no playhead to move — "
                "drop src_start, or point the cue at a video clip_id"
            )
        cue["src_start"] = src_start

    manifest = project.read_manifest()
    cues = manifest.setdefault("cues", [])
    if any(c["clip_id"] == clip_id and c["word_index"] == word_index for c in cues):
        raise tx.TranscriptError(
            f"{clip_id!r} already has a cue at word {word_index} — remove it "
            "with cue_rm first (CLI: `lucid cue rm`) if you meant to replace it"
        )
    cues.append(cue)
    cues.sort(key=lambda c: (c["clip_id"], c["word_index"]))
    project.write_manifest(manifest)
    return {
        "clip_id": clip_id,
        "asset": asset,
        "src_start": src_start,
        "cues": len(cues),
        **echo,
    }


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
        "src_start": match.get("src_start"),
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
                "src_start": cue.get("src_start"),
                **_cue_echo(transcripts[cid], cue["word_index"]),
            }
        )
    return {"cues": entries, "count": len(entries)}


def broll_brief(path: Path | str, *, fps: float | None = None) -> dict[str, Any]:
    """Everything needed to choose b-roll, and nothing that chooses it.

    One read-only call that assembles the whole question: the catalogue of
    footage with each clip's `synopsis`, and every shot position with the
    narration that plays over it and how long it is held. What comes back is
    meant to be handed to something that knows the material — the agent on the
    other end of the MCP server, a `claude -p` panel, or a person — which then
    writes its answers back through `cue_add`, where `plan_picture` checks
    them like any other cue.

    **lucid does not pick, and this is a measurement rather than a
    preference.** Against 25 human choices on the Scream footage: the
    `describe` index agreed 2 times, the clips' own filenames 3, an explicit
    film-name match 4. A synopsis catalogue narrowed nine candidates to a
    correct three 15 times but still only picked right 5. The same catalogue
    read by a model that knows the films picked right 13. Every mechanism that
    scores text against text plateaus in single digits because the connection
    is not lexical — the sentence that earns the Scream VI reveal shares no
    word with any description of it. So the useful thing lucid can build is
    the brief, not the ranker. HISTORY.md § Choosing the b-roll.

    What is in here is what was measured to matter, and one thing that was
    measured *not* to. `narration` per position and the synopsis catalogue are
    the signal. `duration` and the `card` positions are cheap and plausibly
    useful — a long hold wants footage that sustains, and a repeat reads as a
    repeat across a card — but adding them moved 12 correct to 13, which is
    noise, so nothing here should be defended on their behalf. The thing that
    was measured not to work is a **second reviewing pass**: handing these
    positions back with the picks already in them and asking for repeats and
    off-by-one beats to be fixed changed 6 answers and scored 13 → 10. It is
    not implemented for that reason, not because it was never tried.

    `card:` positions are reported and are **not** candidates. A card is
    authored for its moment; the choice this brief exists for is which footage
    goes under which sentence. They are here so the picker can see the rhythm
    it is choosing into, marked with `card: true`.

    Read-only, so it never leaves a project half-briefed, and it reports
    rather than raises: a project whose picture plan already refuses comes
    back with `shots_error` set and `positions` empty, because a brief listing
    a slot `export` will not produce invites a pick for a shot that cannot
    exist.
    """
    project = Project.open(path)
    edit = _load_edit(project)
    clips = _clips_by_id(project)
    rate = float(fps) if fps else _export_fps(clips)

    shots_error: str | None = None
    try:
        shots, _ = _picture_plan(project, rate)
    except _PICTURE_REFUSALS as exc:
        shots, shots_error = [], str(exc)

    # Every word that still plays, with where it now plays. Placements come
    # per clip because a transcript indexes its own source; the timeline is
    # what they get sorted onto (CLAUDE.md: emits for playback map through
    # the edit, never straight off the transcript).
    playing: list[tuple[float, str]] = []
    for clip_id in clips:
        if not project.transcript_path(clip_id).exists():
            continue
        for item in _word_placements(edit, clip_id, _transcript(project, clip_id)):
            if item["present"]:
                playing.append((item["timeline_start"], item["text"]))
    playing.sort(key=lambda pair: pair[0])

    positions = []
    for shot in shots:
        start, end = shot["start"], shot["start"] + shot["duration"]
        positions.append(
            {
                "clip_id": shot["clip_id"],
                "word_index": shot["word_index"],
                "asset": shot["asset"],
                "card": bool(shot["asset"].startswith("card:")),
                "start": start,
                "duration": shot["duration"],
                "narration": " ".join(
                    text for at, text in playing if start <= at < end
                ).strip(),
            }
        )

    candidates = [
        {
            "clip_id": c["clip_id"],
            "synopsis": c.get(SYNOPSIS_KEY),
            "duration": c.get("duration"),
        }
        for c in clips.values()
        if c.get("has_video")
    ]
    result: dict[str, Any] = {
        "project": str(project.root),
        "candidates": candidates,
        "missing_synopsis": [c["clip_id"] for c in candidates if not c["synopsis"]],
        "positions": positions,
        "count": len(positions),
        "choices": sum(1 for p in positions if not p["card"]),
        "rate": rate,
    }
    if shots_error is not None:
        result["shots_error"] = shots_error
    elif not positions:
        # `_picture_plan` returns empty rather than refusing for a project with
        # no cues, which is right for the picture lane and silent here: a brief
        # is asked for precisely when nothing has been placed yet, and an empty
        # answer with no error reads as "nothing to choose". Say which it is.
        result["note"] = (
            "no cues yet, so there are no positions to choose for — a cue is where the "
            "picture changes, and deciding where those go is a separate call (cue_add, "
            "CLI: `lucid cue add`). The catalogue below is what they can point at."
        )
    return result


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

    A cue's optional in-point rides through as `src_pin` and is not one of
    them: it is *carried*, never decided here. The distinction is worth the
    second field name — `src_pin` is what the cue asked for, and the
    `src_start` a shot picks up in `_picture_plan` is where it actually
    reads. For a pinned shot they agree by construction, which is what
    `plan_picture` refusing rather than rewinding buys; for an unpinned one
    `src_pin` is None and `src_start` is wherever the cursor had got to.

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
                "src_pin": cue.get("src_start"),
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
        "canvas": "{}x{}".format(*_mlt_resolution(project)),
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

    `canvas` and `reframe` are the frame, and they are here so a preview can
    draw the shape the render declares instead of the shape its media happens
    to be — step 4 of PLAN.md § Aspect swap. `canvas` is `_mlt_resolution`,
    the profile's own number. `reframe` maps a clip to `dest`, **where its
    whole source frame lands on that canvas**, in canvas pixels: the same
    `Reframe.dest_rect` the MLT writer turns into a `qtblend` rect, so a
    front end places media by reading it rather than by re-deriving a crop.
    A clip whose reframe changes nothing still gets an entry, and it is the
    contain placement — one path draws both, and neither is the front end's
    own arithmetic. A stale stored rect comes back as `reframe_error`, for
    `shots_error`'s reason: the view is how a person finds the rect to fix.

    **Each shot carries its own `dest`, and the picture layer draws that one.**
    `reframe[clip].dest` is the head window, which is the edit track's answer
    and only accidentally the picture lane's: framing is addressed in source
    seconds, so two placements of one clip can sit under two windows (PLAN.md
    § Per-shot framing). A shot's `dest` is the window its `src_start` reads.
    It is null for a still, which is contained rather than cropped, and null
    for every shot while `reframe_error` stands.
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

    resolution = _mlt_resolution(project)
    reframe_error: str | None = None
    entries: dict[str, mlt.Reframe] = {}
    try:
        entries = _reframe_map(project, resolution)
    except ProjectError as exc:
        reframe_error = str(exc)
    placement = {
        clip_id_: {
            "source": list(entry.source),
            "crop": list(entry.crop),
            "dest": list(entry.dest_rect(resolution)),
            # The lower half when the head window is a stacked split. Both
            # halves or the preview draws one person where the film draws two.
            "pane": (
                list(entry.pane_dest_at(0.0, resolution))
                if entry.pane_dest_at(0.0, resolution)
                else None
            ),
            "crops": not entry.is_identity(resolution),
        }
        for clip_id_, entry in entries.items()
    }

    # A shot carries its *own* placement, because framing is per shot: two
    # placements of one clip read different parts of its source and so can sit
    # under different windows. The picture layer draws this rather than the
    # per-clip `reframe` entry, which is the head window and right only for
    # the edit's own track. `null` for a still — a card is re-authored at the
    # canvas, never cropped (`mlt.document`).
    for shot in shots:
        found = entries.get(str(shot.get("asset")))
        drawn = found is not None and not shot.get("is_image")
        at = float(shot.get("src_start") or 0.0)
        shot["dest"] = list(found.dest_rect_at(at, resolution)) if drawn else None
        # A shot the render draws as two half-height panes carries both, and
        # `dest` above is already the upper one. Null is the ordinary case.
        pane = found.pane_dest_at(at, resolution) if drawn else None
        shot["dest_pane"] = list(pane) if pane else None

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
        "canvas": list(resolution),
        "reframe": placement,
        "shots": shots or None,
        "shots_rate": shots_rate,
        "segments": _placed_segments(edit),
        "seams": _seams(edit, clip_id, placements),
    }
    if shots_error is not None:
        result["shots_error"] = shots_error
    if reframe_error is not None:
        result["reframe_error"] = reframe_error
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
        # `preview_path`, not `media_path`: the proxy when a current one
        # exists (PLAN.md § The preview proxy transcode). This is one of the
        # two callers that resolve that way, and `export` is deliberately not
        # among them — see media.py § the preview proxy.
        source = media.preview_path(project, media.get_clip(project, asset))
    if not source.is_file():
        raise ProjectError(f"asset {asset!r} resolves to {source}, which does not exist")

    result: dict[str, Any] = {"asset": asset, "path": str(source)}
    if source.suffix.lower() in _PREVIEW_IMAGE_SUFFIXES:
        return {**result, "kind": "image", "playable": True, "reason": None}

    verdict = media.playability(source)
    kind = "video" if verdict.get("video_codec") else "audio"
    return {**result, "kind": kind, **verdict}


def proxy_transcode(
    path: Path | str, clip_id: str, *, force: bool = False
) -> dict[str, Any]:
    """Build a browser-playable stand-in for footage the preview cannot decode.

    The other half of what `media.playability()` already reports: the viewer
    names the reason a clip shows black (`hev1`, 10-bit, an unopenable
    container, an undecodable audio track), and this is what makes it play.
    One ffmpeg pass, downscaled — a proxy is for a `<video>` in a window, not
    for delivery, and `media.PROXY_HEIGHT` carries the measurement behind that.

    **The result never enters the manifest**, which is the point rather than an
    omission: no key here means `media_path()` cannot reach it, so no render,
    `verify` or `check_frames` can be silently taken at preview quality. Only
    `media.preview_path` resolves it, and only the preview side calls that.

    Skips the work when a current proxy already exists — keyed by the resolved
    source's size and mtime — so this is safe to call on every unplayable
    asset in a project without re-encoding the ones already done. `force`
    rebuilds anyway, which is for a changed `PROXY_HEIGHT`/`PROXY_CRF` rather
    than for a changed source, since a changed source invalidates the key on
    its own.

    Refuses a clip that is already playable rather than transcoding it: a
    proxy of a file the browser opens directly is pure cost and a second,
    lower-quality copy of footage nothing needed a copy of. `force` does not
    override that — it overrides the *cache*, not the judgement.
    """
    project = Project.open(path)
    clip = media.get_clip(project, clip_id)
    source = media.media_path(project, clip)
    if not source.is_file():
        raise ProjectError(f"{clip_id}'s media is missing from disk: {source}")

    verdict = media.playability(source)
    if verdict.get("playable"):
        raise ProjectError(
            f"{clip_id} already plays in a browser ({source.name}) — a proxy would be a "
            "second, lower-quality copy of footage nothing needs one of"
        )
    # The one refusal a transcode cannot close: not a codec problem.
    if not verdict.get("video_codec") and not verdict.get("audio_codec"):
        raise ProjectError(
            f"{clip_id} has no decodable streams ({verdict.get('reason')}) — that is a "
            "broken file, not a codec a transcode can change"
        )

    proxy = project.proxy_path(clip_id)
    if not force and media.proxy_is_current(project, clip):
        return {
            "clip_id": clip_id,
            "proxy": str(proxy),
            "built": False,
            "reason": verdict.get("reason"),
            "bytes": proxy.stat().st_size,
        }

    stat = source.stat()
    media.make_proxy(source, proxy)
    # Written *after* the transcode returns, never before: a key that exists
    # beside a half-written or absent mp4 is a stale hit that reads as current.
    project.proxy_key_path(clip_id).write_text(
        json.dumps({"size": stat.st_size, "mtime_ns": stat.st_mtime_ns}),
        encoding="utf-8",
    )
    return {
        "clip_id": clip_id,
        "proxy": str(proxy),
        "built": True,
        "reason": verdict.get("reason"),
        "bytes": proxy.stat().st_size,
        "source_bytes": stat.st_size,
        # What the preview will now play, read back off the file rather than
        # assumed from the flags handed to ffmpeg — the same discipline every
        # render check here follows.
        "playable": media.playability(proxy),
    }


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
#: `tiktok-reels` arrived with PLAN.md § Aspect swap step 5, and it carries
#: `youtube`'s four values on purpose: both platforms re-encode what they are
#: given, so the upload wants the highest-quality source the measured-safe
#: keys can express, and there is no fifth key to reach for. **What the entry
#: actually adds is the aspect it asserts** (`PRESET_ASPECT`) — because the
#: canvas half of this preset belongs to the project rather than to an export
#: flag. `canvas` is where the shape is decided; a preset that quietly set it
#: would be an export argument reshaping a project, which is the same class of
#: silent wrong output `export`-picks-its-writer-from-the-project exists to
#: prevent. So the preset checks and refuses with the fix in it, and never
#: writes.
EXPORT_PRESETS: dict[str, dict[str, str]] = {
    "youtube": {"vcodec": "libx264", "crf": "18", "preset": "medium", "acodec": "aac"},
    "web": {"vcodec": "libx264", "crf": "23", "preset": "faster", "acodec": "aac"},
    "tiktok-reels": {"vcodec": "libx264", "crf": "18", "preset": "medium", "acodec": "aac"},
}


#: The frame shape a preset's *name* claims, for the presets whose name is a
#: claim about geometry. Checked against the canvas in force at export, never
#: applied — see `EXPORT_PRESETS`. Exact rather than "portrait enough": both
#: platforms specify 9:16, and a preset named after that spec accepting
#: 19.5:9 would be guessing on the caller's behalf about a shape the caller
#: can simply state. A vertical canvas that is not 9:16 is a legitimate
#: export; it just goes out under `youtube` or `web`.
PRESET_ASPECT: dict[str, tuple[int, int]] = {"tiktok-reels": (9, 16)}


def _suggest_canvas(aspect: tuple[int, int]) -> str:
    """A concrete `WIDTHxHEIGHT` to put in a refusal, at the delivery size.

    Scaled so the *shorter* edge lands on 1080 — 9:16 → `1080x1920`, and a
    landscape ratio would come out `1920x1080` rather than upside down. The
    factor is even at every ratio that reaches here, which is what keeps the
    suggestion something `_parse_canvas` will actually accept.
    """
    factor = max(1, 1080 // min(aspect))
    return f"{aspect[0] * factor}x{aspect[1] * factor}"


def _check_preset_canvas(project: Project, preset: str | None) -> None:
    """Refuse a preset whose name claims a shape this project does not render at.

    The failure being closed is a landscape file with a vertical name on it:
    every downstream check passes, because nothing but the preset's name ever
    said the frame should be 9:16. The message names the one command that
    fixes it rather than describing the problem, since `canvas` is also what
    reports what the crop costs.

    **A project with no picture is refused separately, and not by geometry.**
    `_mlt_resolution` falls back to 1080p for an audio-only project, so the
    shared path would refuse a vertical preset by quoting a frame size that
    project does not have — a true refusal for a false reason. Asked of the
    manifest rather than of the rendered payload, deliberately: every other
    canvas derivation in this file walks `clips`, and finding 4 of PLAN.md
    § Aspect swap is about what happens when two of them stop agreeing.
    """
    want = PRESET_ASPECT.get(preset or "")
    if want is None:
        return
    if not any(clip.get("has_video") for clip in project.read_manifest().get("clips", [])):
        raise ProjectError(
            f"preset {preset!r} names a frame shape ({want[0]}:{want[1]}) and this project "
            "has no picture to shape — the render would be audio. Drop the preset, or use "
            "'youtube'/'web', which claim nothing about the frame."
        )
    width, height = _mlt_resolution(project)
    if width * want[1] != height * want[0]:
        # Cross-multiplied rather than compared as floats: the canvas is a pair
        # of integers and 1080/1920 is not exactly representable, so a ratio
        # test would refuse a shape that is exactly right.
        suggest = _suggest_canvas(want)
        raise ProjectError(
            f"preset {preset!r} renders {want[0]}:{want[1]}, and this project's canvas is "
            f"{width}x{height} ({_aspect(width, height)}) — a preset names the encode, and "
            "the shape a project renders at is `canvas`'s job rather than an export flag's, "
            "so honouring this one would mean an export argument reshaping the project. "
            f"Set the shape first (`lucid canvas {suggest}`), which "
            "routes through the MLT writer, crops to fill rather than pillarboxing, and "
            "reports what each clip loses; then export again. A vertical canvas that is not "
            f"{want[0]}:{want[1]} is a legitimate export — use 'youtube' or 'web' with it."
        )


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
            f"{sorted([*EXPORT_PRESETS, 'custom'])}. A preset names the encode only — "
            "the shape a project renders at is `canvas`'s, and 'tiktok-reels' checks "
            "it rather than setting it."
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


#: Where a project keeps the shape it renders at, as `WIDTHxHEIGHT`. Absent
#: means "derive from the footage", which is exactly what every project
#: written before this key existed meant — so it is additive the way
#: `CAPTION_STYLE_KEY` is, and gets no `SCHEMA_VERSION` bump for the same
#: reason: a bump would make `Project.open` refuse every project on disk to
#: gain nothing. PLAN.md § Aspect swap.
CANVAS_KEY = "canvas"


def _parse_canvas(value: Any) -> tuple[int, int]:
    """`WIDTHxHEIGHT` → a pair, refusing what the encoders refuse quietly.

    The odd dimension is the one worth naming: libx264 at `yuv420p`
    subsamples chroma by two, so an odd edge is padded or refused depending
    on which link in the chain notices first — and a canvas that comes back
    one pixel different from the one asked for is the silent-wrong-output
    this whole item exists to avoid.
    """
    text = str(value).strip().lower().replace("×", "x")
    parts = text.split("x")
    if len(parts) != 2 or not all(part.strip().isdigit() for part in parts):
        raise ProjectError(f"canvas must read WIDTHxHEIGHT (e.g. 1080x1920), not {value!r}")
    width, height = (int(part) for part in parts)
    if width <= 0 or height <= 0:
        raise ProjectError(f"canvas must be positive, not {width}x{height}")
    if width % 2 or height % 2:
        raise ProjectError(
            f"canvas must be even on both edges, not {width}x{height} — libx264 at "
            "yuv420p subsamples chroma by two, and an odd edge is padded or refused "
            "depending on which link in the chain notices first"
        )
    return width, height


def _stored_canvas(project: Project) -> tuple[int, int] | None:
    """The project's canvas override, or None to derive from the footage."""
    stored = project.read_manifest().get(CANVAS_KEY)
    return None if stored is None else _parse_canvas(stored)


def _footage_resolution(project: Project) -> tuple[int, int]:
    """The shape the footage itself implies: the first real picture in the
    project, else 1080p. Cards are not consulted — scaling a still to the
    canvas is normal; sizing the canvas to a still is not.
    """
    for clip in project.read_manifest().get("clips", []):
        if clip.get("has_video") and clip.get("width") and clip.get("height"):
            return int(clip["width"]), int(clip["height"])
    return mlt.DEFAULT_RESOLUTION


def _aspect(width: int, height: int) -> str:
    """`1080x1920` → `9:16`. Reported because it is the question actually
    being asked, and because two canvases that differ only in scale are the
    same decision while two that differ in ratio are not.
    """
    divisor = gcd(width, height) or 1
    return f"{width // divisor}:{height // divisor}"


def _canvas_crop_report(project: Project, resolution: tuple[int, int]) -> dict[str, Any]:
    """What a canvas costs in footage: which clips crop, and which cannot.

    Reports rather than raises, and that is the whole reason it exists.
    A stored rect is kept as asked and refit to the canvas in force, so a
    canvas change can leave one that no longer fits — and discovering that by
    having `canvas` raise *after* it has written the manifest would leave the
    project half-swapped. `export` still refuses such a project; this is the
    warning that says which clip to fix and with what.
    """
    asked = _stored_reframes(project)
    cropped, conflicts = [], []
    for clip in project.read_manifest().get("clips", []):
        clip_id = str(clip.get("clip_id"))
        try:
            entry = _clip_reframe(clip, asked.get(clip_id), resolution)
        except ProjectError as error:
            conflicts.append({"clip_id": clip_id, "why": str(error)})
            continue
        if entry is not None and not entry.is_identity(resolution):
            cropped.append(clip_id)
    return {
        "cropped": cropped,
        "reframe_conflicts": conflicts,
    }


def canvas(
    path: Path | str,
    *,
    size: str | None = None,
    reset: bool = False,
    plan: bool = False,
) -> dict[str, Any]:
    """Read or change the shape this project renders at.

    **The canvas is project state and every frame size is derived from it**,
    the same separation `caption_style` has and for the same reason: the MLT
    profile and the captions' reference canvas both read this, so a project
    cannot end up quoting caption sizes against one shape while rendering
    another. Called with no arguments it changes nothing and reports what is
    in force, including the footage-derived shape it would fall back to.

    Setting one has a routing consequence, reported as `routes_through`: an
    overridden project renders through the MLT writer whatever its source
    count, because auto-editor's `-res` letterboxes and has no reframe to
    teach (PLAN.md § Aspect swap). `reset` drops the override and returns the
    project to deriving from its footage. `plan` resolves without writing.

    An override that changes the *aspect* crops to fill rather than
    pillarboxing, so what it costs is footage rather than frame. `cropped`
    names every clip that loses some; which part each one keeps is `reframe`'s
    to report and to override.
    """
    if size is not None and reset:
        raise ProjectError("pass a size or `reset`, not both")

    project = Project.open(path)
    stored = _stored_canvas(project)
    if size is not None:
        after: tuple[int, int] | None = _parse_canvas(size)
    elif reset:
        after = None
    else:
        after = stored

    write = (size is not None or reset) and not plan
    if write:
        manifest = project.read_manifest()
        if after is None:
            manifest.pop(CANVAS_KEY, None)
        else:
            manifest[CANVAS_KEY] = f"{after[0]}x{after[1]}"
        project.write_manifest(manifest)

    footage = _footage_resolution(project)
    width, height = after or footage
    canvas_now = f"{width}x{height}"
    has_clips = any(c.get("has_video") for c in project.read_manifest().get("clips", []))
    records = _card_records(project)
    recorded = {r.get("card") for r in records}
    return {
        "project": str(project.root),
        "canvas": canvas_now,
        "width": width,
        "height": height,
        "aspect": _aspect(width, height),
        "source": "override" if after else ("footage" if has_clips else "default"),
        "footage": f"{footage[0]}x{footage[1]}",
        "footage_aspect": _aspect(*footage),
        # The consequence of setting one, said out loud rather than discovered
        # at export: auto-editor cannot be handed this.
        "routes_through": "mlt" if after else "auto-editor or mlt, by source count",
        # True since the reframe landed — the question worth asking now is not
        # whether the frame is filled but what filling it costs, so the clips
        # paying for it are named beside it.
        "fills_frame": True,
        # Against `(width, height)` rather than through `reframe`, which would
        # read the stored canvas — under `plan` that is the shape being
        # replaced, and the whole point of planning is to see what the new one
        # costs before writing it.
        **_canvas_crop_report(project, (width, height)),
        "captions_reference": "{}x{}".format(*captions.canvas(width, height)),
        # Cards are the only project state a canvas change cannot re-derive on
        # its own (PLAN.md § Aspect swap, finding 5), so the moment the shape
        # moves is the moment to name the ones now drawn at the old one.
        # Reported by both arms: reading the canvas is also how you ask
        # whether the cards agree with it.
        "cards_stale": [str(r.get("card")) for r in records if r.get("canvas") != canvas_now],
        "cards_unrecorded": [c for c in _cards_on_disk(project) if c not in recorded],
        "written": write,
        "reset": bool(reset),
        "plan": bool(plan),
    }


#: `reel` takes a `canvas=` argument, which shadows the function above inside
#: its body — the same collision `describe` and `verify` have with their
#: modules, and the same fix. Aliased here rather than worked around there, so
#: the argument keeps the name the CLI flag and the MCP tool use.
_set_canvas = canvas


#: Per-clip crop rects, `[{"clip_id", "rect": [x, y, w, h]}]` in **source
#: pixels**. Geometry and never a length, so an edit cannot invalidate one
#: (PLAN.md § Aspect swap) — and the rect stored is the one *asked for*, refit
#: to whatever canvas is in force at render time, so a canvas change cannot
#: invalidate one either.
#:
#: Additive and optional, and so no `SCHEMA_VERSION` bump — the
#: `CANVAS_KEY`/`CAPTION_STYLE_KEY` shape rather than the `cards` one. Absent
#: means "centre-crop every clip", which is a complete answer rather than a
#: gap: the migration a bump would carry is `setdefault([])`, and CLAUDE.md's
#: bar is that a bump exists where the number is what makes the key true.
#: Nothing about an older project is untrue without it.
REFRAME_KEY = "reframe"


def _parse_rect(value: Any) -> tuple[int, int, int, int]:
    """`X,Y,W,H` → a rect in source pixels, refusing the degenerate shapes."""
    if isinstance(value, (list, tuple)):
        parts = [str(part).strip() for part in value]
    else:
        parts = [part.strip() for part in str(value).replace(" ", ",").split(",") if part.strip()]
    if len(parts) != 4 or not all(part.lstrip("-").isdigit() for part in parts):
        raise ProjectError(f"a crop rect must read X,Y,W,H in source pixels, not {value!r}")
    x, y, width, height = (int(part) for part in parts)
    if width <= 0 or height <= 0:
        raise ProjectError(f"a crop rect must be positive, not {width}x{height}")
    if x < 0 or y < 0:
        raise ProjectError(f"a crop rect starts inside the source, not at {x},{y}")
    return x, y, width, height


def _fit_rect_to_canvas(
    rect: tuple[int, int, int, int],
    source: tuple[int, int],
    resolution: tuple[int, int],
) -> tuple[int, int, int, int]:
    """Grow a requested rect to the canvas's aspect, keeping it inside the source.

    **Grow rather than shrink, and the asymmetry is the whole argument.** A
    box drawn round a subject cannot be shown as-is in a frame of a different
    shape — something has to give. Growing keeps everything asked for on
    screen and pulls in surroundings; shrinking would keep the surroundings
    out and cut the subject in half. The second is the wrong-video failure
    this item exists to close, so the ask is treated as a floor.

    Recentred on the ask, then shifted whole to stay inside the source — a
    rect that leaves the frame renders MLT's idea of what is past the edge,
    not the footage's. When even the grown rect cannot fit, that is refused
    rather than quietly clipped, and the refusal names the largest rect that
    would have worked.
    """
    x, y, width, height = rect
    src_w, src_h = source
    canvas_w, canvas_h = resolution
    if x + width > src_w or y + height > src_h:
        raise ProjectError(
            f"crop rect {x},{y},{width},{height} runs past the source's {src_w}x{src_h}"
        )
    if width * canvas_h >= height * canvas_w:
        grown_w, grown_h = width, round(width * canvas_h / canvas_w)
    else:
        grown_w, grown_h = round(height * canvas_w / canvas_h), height
    if grown_w > src_w or grown_h > src_h:
        largest = mlt.centre_crop(source, resolution)
        raise ProjectError(
            f"crop rect {x},{y},{width},{height} cannot be shown whole in a "
            f"{canvas_w}x{canvas_h} frame — grown to that shape it is "
            f"{grown_w}x{grown_h}, past the source's {src_w}x{src_h}. The largest "
            f"rect that fits is {largest[0]},{largest[1]},{largest[2]},{largest[3]}"
        )
    grown_x = min(max(round(x + width / 2 - grown_w / 2), 0), src_w - grown_w)
    grown_y = min(max(round(y + height / 2 - grown_h / 2), 0), src_h - grown_h)
    return grown_x, grown_y, grown_w, grown_h


#: One stored window: where in the source it starts, the rect asked for, and
#: the second rect when that window is drawn as a stacked split.
StoredWindow = tuple[float, tuple[int, int, int, int], tuple[int, int, int, int] | None]


def _stored_reframes(project: Project) -> dict[str, list[StoredWindow]]:
    """Every clip's requested crop rects, as asked for rather than as fitted.

    A series per clip, `(src_start seconds, rect, pane)` in source order. A
    record with no `src_start` is the window from the head of the file onward,
    which is what every rect written before per-shot framing existed meant and
    still means — the key is optional and absent-means-what-it-always-meant, so
    this is deliberately not a schema bump (CLAUDE.md).

    `pane` is the same for the stacked split: absent means the window is one
    rect, which is what every window written before the split existed was. It
    rides on the *same record* rather than in a series of its own precisely so
    it cannot drift from the window it is the other half of — a pane with no
    window would render as half a frame over whatever framing happened to be
    in force.
    """
    stored: dict[str, list[StoredWindow]] = {}
    for record in project.read_manifest().get(REFRAME_KEY, []):
        at = float(record.get("src_start") or 0.0)
        pane = record.get("pane")
        stored.setdefault(str(record["clip_id"]), []).append(
            (at, _parse_rect(record["rect"]), _parse_rect(pane) if pane else None)
        )
    for series in stored.values():
        series.sort(key=lambda entry: entry[0])
    return stored


def _clip_source(clip: dict[str, Any]) -> tuple[int, int] | None:
    """A clip's own pixel size, or None if it is not picture with a known one."""
    if not clip.get("has_video") or not clip.get("width") or not clip.get("height"):
        return None
    return int(clip["width"]), int(clip["height"])


def _fit_pane_rect(
    rect: tuple[int, int, int, int],
    source: tuple[int, int],
    pane: tuple[int, int],
) -> tuple[int, int, int, int]:
    """Grow a requested rect to a pane of the canvas — **full source height**.

    The pane's aspect alone is not enough, and that is the whole of this
    function. Nothing masks or crops a pane: `mlt.Reframe._dest` places the
    *entire* source frame so the rect fills the pane, and the profile does the
    clipping. So a rect of the pane's shape but only part of the source's
    height scales the frame up until it overruns the pane and draws into the
    other one — a two-hander with the other person's chin across the middle,
    at exit 0. A caught-by-a-test bug rather than a reasoned one: growing to
    9:8 alone turned a 200px-tall ask into a 4.8x zoom.

    Full height makes the scaled frame exactly one pane tall for any source
    shape, which is the only thing holding the two halves apart. The width
    follows from it, so the ask moves the window sideways and nothing else —
    which is what a framing decision is here.
    """
    src_w, src_h = source
    pane_w, pane_h = pane
    width = round(src_h * pane_w / pane_h)
    if width > src_w:
        raise ProjectError(
            f"a {src_w}x{src_h} source cannot be shown whole in a {pane_w}x{pane_h} "
            f"pane — a pane window is the full source height, so it would be "
            f"{width} wide against the source's {src_w}. This footage is too tall "
            "to stack; frame it with one window instead"
        )
    x, _y, ask_w, _ask_h = rect
    if x + ask_w > src_w:
        raise ProjectError(
            f"crop rect {rect[0]},{rect[1]},{rect[2]},{rect[3]} runs past the "
            f"source's {src_w}x{src_h}"
        )
    left = min(max(round(x + ask_w / 2 - width / 2), 0), src_w - width)
    return (left, 0, width, src_h)


def _clip_reframe(
    clip: dict[str, Any],
    asked: list[StoredWindow] | None,
    resolution: tuple[int, int],
) -> mlt.Reframe | None:
    """What survives into the frame for one clip, overrides or centre default.

    The head window is whichever override sits at 0, else the centre crop —
    so a clip whose first override starts partway in is centre-cropped up to
    that point rather than being framed by a window that has not begun.

    **A split's two rects are fitted to the pane, not to the canvas** — and to
    the full source height, which is `_fit_pane_rect`'s whole argument: the
    geometry is the only thing holding the two halves off each other, there
    being no mask and no crop filter anywhere in this (`mlt.Reframe._dest`).
    A source too tall to carry a pane is refused there, at the keyboard.
    """
    source = _clip_source(clip)
    if source is None:
        return None
    series = list(asked or [])
    starts = [start for start, *_ in series]
    if len(set(starts)) != len(starts):
        # Only reachable by hand-editing the manifest — the op refuses a second
        # entry at one in-point. Refused as a `ProjectError` so the reading
        # paths report it (`reframe`'s table, `timeline_view`'s
        # `reframe_error`) rather than being taken down by it, which is how a
        # person finds the window to drop.
        raise ProjectError(
            f"clip {clip.get('clip_id')!r} has two reframe windows at one in-point "
            f"({sorted(starts)}) — a window is addressed by where it starts, so one of "
            "them is unreachable; drop it with `reframe <clip> --at <seconds> --reset`"
        )
    upper, _lower = mlt.pane_boxes(resolution)
    pane_shape = (upper[2], upper[3])

    def fit(at: float, rect: tuple[int, int, int, int], pane: object) -> tuple[int, int, int, int]:
        if pane:
            return _fit_pane_rect(rect, source, pane_shape)
        return _fit_rect_to_canvas(rect, source, resolution)

    # The head window is addressed as 0.0 whatever it was stored as, so that a
    # pane on it pairs with the window `Reframe` calls `crop`.
    head = (0.0, *series.pop(0)[1:]) if series and series[0][0] <= 0 else None
    crop = mlt.centre_crop(source, resolution) if head is None else fit(*head)
    later = tuple((when, fit(when, rect, pane)) for when, rect, pane in series)
    panes = tuple(
        (when, _fit_pane_rect(pane, source, pane_shape))
        for when, _rect, pane in ([head] if head else []) + series
        if pane is not None
    )
    return mlt.Reframe(source=source, crop=crop, later=later, panes=panes)


def _reframe_map(project: Project, resolution: tuple[int, int]) -> dict[str, mlt.Reframe]:
    """Clip id → the reframe to apply, for every video clip in the project.

    Keyed by clip id here and translated to a resource by the caller, because
    the manifest's unit is `(clip_id, rect)` while the MLT writer's is a node
    per resource per role.
    """
    asked = _stored_reframes(project)
    reframes = {}
    for clip in project.read_manifest().get("clips", []):
        clip_id = str(clip.get("clip_id"))
        reframe = _clip_reframe(clip, asked.get(clip_id), resolution)
        if reframe is not None:
            reframes[clip_id] = reframe
    return reframes


def _rect_text(rect: tuple[int, int, int, int]) -> str:
    return ",".join(str(value) for value in rect)


def reframe(
    path: Path | str,
    clip_id: str | None = None,
    *,
    rect: str | None = None,
    pane: str | None = None,
    src_start: float | None = None,
    reset: bool = False,
    plan: bool = False,
) -> dict[str, Any]:
    """Read or set which part of each clip survives into the frame.

    **What makes a swapped canvas fill the frame instead of pillarboxing it**
    (PLAN.md § Aspect swap, step 3). A rect is `X,Y,W,H` in the clip's own
    source pixels — geometry, never a length, so no cut can invalidate one —
    and it is stored exactly as asked and refit to whatever canvas is in force
    when the project renders. The default is a centre crop, which is *wrong
    whenever the subject is not centred*: that is the reason this reports the
    rect it used for every clip rather than quietly choosing one. Analysis
    that picks a crop lives in `reframe_detect` and **proposes** through here
    rather than framing — this op still never chooses anything by itself.

    **`src_start` frames a shot rather than a clip.** It is seconds into that
    clip's own source, and the rect it carries is in force from there onward,
    until the next window. That address is the source's clock and not the
    timeline's, so a clip used seven times gets seven correct windows without
    anything being said seven times, and no cut can invalidate one — the same
    reason a footage description indexes the source (PLAN.md § Per-shot
    framing). Omitted, it means the window from the head of the file, which is
    exactly what a per-clip reframe always meant.

    Called with no arguments it changes nothing and reports the crops in force
    per clip. `clip_id` with `rect` sets one window; `clip_id` with `reset`
    drops that clip's windows, or with `src_start` just the one at that point;
    `reset` alone drops every one. `plan` resolves — a rect that cannot fit is
    refused here either way — without writing.

    An override is a *floor*, not a frame: a rect whose shape is not the
    canvas's is grown to it, so everything asked for stays on screen, and the
    reply names both `asked` and the `crop` it became.

    **`pane` makes that window a stacked split**: two half-height panes, `rect`
    on top and `pane` below, each getting a window of the source twice the
    width a single 9:16 crop of this footage gets. It is for the shot one
    window cannot frame — a two-hander where every face is a true positive and
    only one of them is the shot (`faces.py`), so choosing between them is
    losing one. Both rects are grown to the *pane's* shape rather than the
    canvas's, and a source too tall to carry it is refused here rather than
    rendering as two halves bleeding into each other. Measured before it was
    built: PLAN.md § The stacked split.
    """
    if rect is not None and reset:
        raise ProjectError("pass a rect or `reset`, not both")
    if pane is not None and rect is None:
        raise ProjectError(
            "a split's lower pane needs an upper one — pass `rect` as well, since "
            "a pane is half of a window rather than a window of its own"
        )
    if rect is not None and clip_id is None:
        raise ProjectError("a rect needs a clip_id — a crop indexes one clip's source")
    if src_start is not None and clip_id is None:
        raise ProjectError(
            "an in-point needs a clip_id — a window indexes one clip's own source"
        )
    if src_start is not None and rect is None and not reset:
        raise ProjectError("an in-point needs a rect to put there, or `reset` to drop one")

    project = Project.open(path)
    resolution = _mlt_resolution(project)
    clips = {str(clip.get("clip_id")): clip for clip in project.read_manifest().get("clips", [])}
    if clip_id is not None:
        if clip_id not in clips:
            raise ProjectError(f"no clip {clip_id!r} in this project")
        if _clip_source(clips[clip_id]) is None:
            raise ProjectError(
                f"clip {clip_id!r} has no picture to crop — a reframe indexes video"
            )

    at = 0.0 if src_start is None else float(src_start)
    if clip_id is not None and src_start is not None:
        duration = clips[clip_id].get("duration")
        if at < 0:
            raise ProjectError(f"src_start {at} is before the start of clip {clip_id!r}")
        # A window past the end never applies, and would sit in the manifest
        # reading as framing that had been dealt with.
        if duration and at >= float(duration):
            raise ProjectError(
                f"src_start {at} is past clip {clip_id!r}'s {float(duration):.3f}s, so "
                "the window would never come into force"
            )

    asked = _stored_reframes(project)
    if rect is not None:
        # Resolved before it is stored, so an impossible rect is refused at the
        # keyboard rather than at the render an hour later.
        source = _clip_source(clips[clip_id])  # type: ignore[arg-type]
        parsed = _parse_rect(rect)
        parsed_pane = _parse_rect(pane) if pane is not None else None
        upper, _lower = mlt.pane_boxes(resolution)
        # A split's rects are fitted against the pane, an ordinary window's
        # against the canvas. Both refuse an impossible rect here rather than
        # at the render an hour later.
        if parsed_pane is not None:
            _fit_pane_rect(parsed, source, (upper[2], upper[3]))  # type: ignore[arg-type]
            _fit_pane_rect(parsed_pane, source, (upper[2], upper[3]))  # type: ignore[arg-type]
        else:
            _fit_rect_to_canvas(parsed, source, resolution)  # type: ignore[arg-type]
        series = [entry for entry in asked.get(str(clip_id), []) if entry[0] != at]
        series.append((at, parsed, parsed_pane))
        asked[str(clip_id)] = sorted(series, key=lambda entry: entry[0])
    elif reset:
        if clip_id is None:
            asked = {}
        elif src_start is None:
            asked.pop(clip_id, None)
        else:
            series = [entry for entry in asked.get(clip_id, []) if entry[0] != at]
            if len(series) == len(asked.get(clip_id, [])):
                raise ProjectError(
                    f"clip {clip_id!r} has no reframe window at {at}s — `reframe {clip_id}` "
                    "lists the ones it has"
                )
            if series:
                asked[clip_id] = series
            else:
                asked.pop(clip_id, None)

    write = (rect is not None or reset) and not plan
    if write:
        manifest = project.read_manifest()
        records = []
        for key, series in sorted(asked.items()):
            for window_at, window_rect, window_pane in series:
                record: dict[str, Any] = {"clip_id": key, "rect": list(window_rect)}
                # The head window writes the record it wrote before per-shot
                # framing existed, so an unwindowed project's manifest is
                # unchanged by any of this. Same for `pane`: absent is what
                # every window written before the split existed meant.
                if window_at:
                    record["src_start"] = window_at
                if window_pane is not None:
                    record["pane"] = list(window_pane)
                records.append(record)
        if records:
            manifest[REFRAME_KEY] = records
        else:
            manifest.pop(REFRAME_KEY, None)
        project.write_manifest(manifest)

    report = []
    for key, clip in clips.items():
        source = _clip_source(clip)
        if source is None:
            continue
        try:
            entry = _clip_reframe(clip, asked.get(key), resolution)
        except ProjectError as error:
            # A stored rect the canvas has outgrown. Reported rather than
            # raised so that reading the table — and so finding out which clip
            # to reset — is possible at all; `export` is where it is refused.
            report.append(
                {
                    "clip_id": key,
                    "source": f"{source[0]}x{source[1]}",
                    "crop": None,
                    "asked": _rect_text(asked[key][0][1]),
                    "origin": "override",
                    "reframes": None,
                    "kept": None,
                    "windows": None,
                    "error": str(error),
                }
            )
            continue
        assert entry is not None
        overrides = {when: rect for when, rect, _pane in asked.get(key, [])}
        report.append(
            {
                "clip_id": key,
                "source": f"{source[0]}x{source[1]}",
                "crop": _rect_text(entry.crop),
                "asked": _rect_text(overrides[0.0]) if 0.0 in overrides else None,
                "origin": "override" if 0.0 in overrides else "centre",
                # False means the filter is not emitted at all: the clip already
                # carries the canvas's aspect uncropped, so MLT's own placement
                # is already the right one.
                "reframes": not entry.is_identity(resolution),
                "kept": round(
                    (entry.crop[2] * entry.crop[3]) / (source[0] * source[1]),
                    4,
                ),
                # Every window in force, head one included, so the shot-level
                # table is readable without re-deriving which override applies
                # where. One entry is the ordinary per-clip case.
                "windows": [
                    {
                        "src_start": window_at,
                        "crop": _rect_text(window_crop),
                        "asked": _rect_text(overrides[window_at])
                        if window_at in overrides
                        else None,
                        "origin": "override" if window_at in overrides else "centre",
                        # The lower half when this window is a stacked split,
                        # and the reason `kept` is the two of them together:
                        # a split keeps *more* of the source than the window it
                        # replaces, which is the whole point of drawing one.
                        "pane": _rect_text(entry.pane_at(window_at))
                        if entry.pane_at(window_at)
                        else None,
                        "kept": round(
                            (
                                window_crop[2] * window_crop[3]
                                + (
                                    entry.pane_at(window_at)[2] * entry.pane_at(window_at)[3]
                                    if entry.pane_at(window_at)
                                    else 0
                                )
                            )
                            / (source[0] * source[1]),
                            4,
                        ),
                    }
                    for window_at, window_crop in entry.windows()
                ],
                "error": None,
            }
        )
    return {
        "project": str(project.root),
        "canvas": f"{resolution[0]}x{resolution[1]}",
        "clips": report,
        "count": len(report),
        "written": write,
        "reset": bool(reset),
        "plan": bool(plan),
    }


#: Where in each placement the sheet samples. Three, and not at the edges: an
#: edge frame is the one a seek is least likely to land on and the one a cut
#: is most likely to have made ambiguous. `~/lucid-final-cut/audit.py`'s own
#: numbers, which is the prototype this is a build of.
SHEET_MOMENTS = (0.15, 0.5, 0.85)
#: Tile width in the montage. The sheet is read on a phone (auto-memory:
#: review by served page), so three across at this width is a legible row.
SHEET_TILE_WIDTH = 420
#: The window, drawn on the source frame. Red because nothing in this footage
#: is, and thick enough to read once the tile is 420px wide.
SHEET_STROKE = "#ff3b3b"
SHEET_LABEL = "#ffcc00"
#: Tiles a row draws when it is sampled for the subject's extremes: leftmost,
#: median, rightmost. Three because the montage is a fixed grid — a row with
#: fewer tiles shifts every row after it, and a sheet whose rows do not line up
#: mislabels the thing being reviewed.
SHEET_PICKS = 3
#: Probes per second of window when sampling for extremes. The detector costs
#: ~0.48s a frame on this box's CPU build, measured at 3/12/36 frames, so a
#: 245-second cut is about four minutes of probing — a price a review
#: instrument pays once, and why this is opt-in rather than the default.
SHEET_PROBE_HZ = 2.0
#: The floor is `DETECT_FRAMES`, so the shortest window is asked the same three
#: questions the detector asks of one. The ceiling keeps a long held shot from
#: costing a minute on its own; a subject's extremes are where it turns, and
#: sixteen looks find a turn that two do not.
SHEET_PROBE_MIN = 3
SHEET_PROBE_MAX = 16


def _spread(values: list[float], count: int) -> list[float]:
    """`count` items spaced evenly through `values`, in the order given.

    For padding a row out to its tile count when the subject was located in
    fewer probes than that: the leftovers still want to be spread across the
    stretch rather than bunched at its head.
    """
    if count <= 0 or not values:
        return []
    if count >= len(values):
        return list(values)
    step = (len(values) - 1) / (count - 1) if count > 1 else 0.0
    return [values[round(index * step)] for index in range(count)]


def _sheet_extremes(
    stretches: list[tuple[dict[str, Any], float, float, int]],
    at: Sequence[float],
) -> dict[int, dict[str, Any]]:
    """Where the subject is extreme in each stretch, in one detector run.

    **The half of the sheet's finding that drawing every window did not
    close.** A tile is evidence about the instant it draws and a window is a
    claim about a span, so three fixed fractions have no reason to find either
    the best moment or the worst one — the teaser's opening window was 184px
    out at its median and the one tile that landed inside it was 122px out,
    which reads as tight and fine (HISTORY.md § The tile that made a wrong
    window look right).

    **The rect is static inside a stretch, so the worst moment is at one of the
    subject's own extremes** — the error is `|subject_x - crop centre|`, which
    is monotonic in `subject_x` either side of that centre. That is what makes
    leftmost/median/rightmost the right three and not merely a denser sampling:
    the worst moment is in them by construction, whatever the subject did in
    between.

    Probing does not decide anything and writes nothing. It picks *which
    frames get drawn*, and the drawn frame is still what a window is judged on
    — the same rule as `reframe_detect`, whose proposal is 114px out on a
    459px window.

    **The probe grid includes the fixed fractions, and that is a correction the
    measurement made.** Probing at a rate finds the extreme of the *probed*
    sample, not of the stretch, so a fraction landing between two probes can
    catch a worse moment than any of them — on the teaser it did on 5 rows of
    16, by up to 29px, which is a sheet that changed its sampling and got
    quietly worse. Sampling the fractions too costs at most three extra frames
    a row and makes the old sheet a subset of this one, so the drawn moment is
    never worse than the moment the default would have drawn.

    Returns the picks per row, plus the numbers behind them. A stretch where no
    probe held a face comes back **named** rather than quietly sampled the old
    way: a fraction presented as an extreme is a tile claiming evidence it
    does not have.
    """
    jobs: list[dict[str, Any]] = []
    probes: dict[int, list[float]] = {}
    for row, (placement, begin, finish, _crossed) in enumerate(stretches):
        entry = placement["reframe"]
        if entry is None or entry.crop_at(begin) is None:
            continue  # No geometry, so no rect to be extreme against.
        count = min(SHEET_PROBE_MAX, max(SHEET_PROBE_MIN, round((finish - begin) * SHEET_PROBE_HZ)))
        times = sorted(
            {
                *dsc.frame_times(begin, finish, count),
                *(begin + (finish - begin) * moment for moment in at),
            }
        )
        probes[row] = times
        jobs.append({"index": row, "media": str(placement["path"]), "timestamps": times})

    detections = {result["index"]: result for result in faces.detect(jobs)}

    found: dict[int, dict[str, Any]] = {}
    for row, times in probes.items():
        placement, begin, _finish, _crossed = stretches[row]
        crop = placement["reframe"].crop_at(begin)
        middle = crop[0] + crop[2] / 2
        answer = detections[row]
        note: str | None = None
        located: list[tuple[float, float, int]] = []  # (subject_x, src_time, faces)
        if "error" in answer:
            # One unreadable stretch is not a reason to lose the other rows'
            # probing, so it is reported against this row and its tiles fall
            # back to the probe times, drawn with no subject number on them.
            note = f"the detector could not read this stretch: {answer['error']}"
        else:
            for frame in answer["frames"]:
                seen_faces = frame.get("faces", [])
                centre = faces.frame_centre(seen_faces)
                if centre is not None:
                    located.append((centre, float(frame["ts"]), len(seen_faces)))
        located.sort()

        picks: list[dict[str, Any]] = []
        seen: set[float] = set()
        if located:
            for name, index in (
                ("leftmost", 0),
                ("median", len(located) // 2),
                ("rightmost", len(located) - 1),
            ):
                subject, when, seen_faces = located[index]
                if when in seen:
                    continue
                seen.add(when)
                picks.append(
                    {
                        "src_time": when,
                        "subject_x": round(subject),
                        "offset": round(subject - middle),
                        # **The count is not decoration.** `frame_centre` is
                        # area-weighted across every face in the frame, so two
                        # faces put the "subject" between them, where neither
                        # is: the teaser's largest offset, 608px, is Stu at
                        # 1079 averaged with a bystander at 1775 against a crop
                        # centred on 830 — and Stu is 250px out, not 608. That
                        # is `faces.py`'s own which-face-is-the-shot finding
                        # arriving in a review number, so the number carries
                        # the count that explains it.
                        "faces": seen_faces,
                        "pick": name,
                    }
                )
        for when in _spread([ts for ts in times if ts not in seen], SHEET_PICKS - len(picks)):
            picks.append(
                {"src_time": when, "subject_x": None, "offset": None, "faces": 0, "pick": "probe"}
            )

        # Worst first. A reviewer reads a row left to right on a phone, and the
        # whole finding behind this is that the reassuring tile was the one
        # that got looked at. Unlocated tiles sort last, in time order.
        picks.sort(key=lambda p: (p["offset"] is None, -abs(p["offset"] or 0), p["src_time"]))
        offsets = [subject - middle for subject, _, _ in located]
        found[row] = {
            "probe": note or ("extremes" if located else f"no face in {len(times)} probes"),
            "probes": len(times),
            "located": len(located),
            # Whether any probe held more than one face, which is the flag on
            # every offset in the row: a two-face frame's weighted centre is a
            # question about which face is the shot, not a measurement of how
            # wrong the window is.
            "multi_face": any(count > 1 for _, _, count in located),
            "subject_min": round(located[0][0]) if located else None,
            "subject_max": round(located[-1][0]) if located else None,
            # Off every probe rather than only the drawn three — they agree by
            # construction, and saying so is what makes that claim checkable.
            "worst_offset": round(max(offsets, key=abs)) if offsets else None,
            "picks": picks[:SHEET_PICKS],
        }
    return found


def _sheet_placements(
    project: Project, resolution: tuple[int, int]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Every stretch of footage the render shows, and what it is framed by.

    The picture lane when there is one — `_picture_plan`'s shots, which is
    what `export` will actually produce — else the edit's own segments, which
    is the whole picture for a project with no cues. Stills come back in the
    second list rather than being dropped silently: a card is authored at the
    canvas and never cropped, so there is no window to review, and saying so
    is the difference between "nothing to check" and "not checked".
    """
    clips = _clips_by_id(project)
    reframes = _reframe_map(project, resolution)
    rate = _export_fps(clips)
    shots, _ = _picture_plan(project, rate)

    placements: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    if shots:
        for index, shot in enumerate(shots):
            if shot.get("is_image"):
                skipped.append({"index": index, "asset": shot["asset"], "why": "a still is never cropped"})
                continue
            placements.append(
                {
                    "index": index,
                    "asset": str(shot["asset"]),
                    "path": Path(str(shot["asset_path"])),
                    "src_start": float(shot["src_start"]),
                    "duration": float(shot["duration"]),
                    "timeline_start": float(shot["start"]),
                    "reframe": reframes.get(str(shot["asset"])),
                }
            )
        return placements, skipped

    for index, seg in enumerate(_placed_segments(_load_edit(project))):
        clip = clips.get(seg["clip_id"])
        if clip is None or _clip_source(clip) is None:
            continue
        placements.append(
            {
                "index": index,
                "asset": seg["clip_id"],
                "path": media.media_path(project, clip),
                "src_start": float(seg["start"]),
                "duration": float(seg["duration"]),
                "timeline_start": float(seg["timeline_start"]),
                "reframe": reframes.get(seg["clip_id"]),
            }
        )
    return placements, skipped


def _draw_window(
    tile: Path,
    crop: tuple[int, int, int, int],
    source: tuple[int, int],
    label: str,
    pane: tuple[int, int, int, int] | None = None,
) -> None:
    """Draw one window on one extracted frame, in place.

    A stacked split draws **both** of its rects, because half a split judged
    on its own is the same failure the whole sheet exists to catch: the upper
    pane alone reads as a badly-centred single window, and whether the pair is
    right is a question about the pair. The lower one is dashed, so which half
    is which is legible in a montage rather than only in the label.
    """
    x, y, width, height = crop
    stroke = max(2, round(source[0] / 240))
    panes = [
        "-draw", f"rectangle {x},{y} {x + width - 1},{y + height - 1}",
    ]  # fmt: skip
    if pane is not None:
        px, py, pw, ph = pane
        # The dash array is an MVG primitive inside `-draw`, not a command-line
        # option: `-strokedasharray` is ImageMagick 6's spelling and `magick`
        # rejects it outright — which at least fails loudly, unlike most of
        # what this file guards against.
        dashed = (
            f"stroke-dasharray {stroke * 4} {stroke * 3} "
            f"rectangle {px},{py} {px + pw - 1},{py + ph - 1}"
        )
        panes += ["-draw", dashed]
    command = [
        *graphics.magick_command(), str(tile),
        "-fill", "none", "-stroke", SHEET_STROKE, "-strokewidth", str(stroke),
        *panes,
        "-stroke", "none", "-fill", SHEET_LABEL,
        "-pointsize", str(max(18, round(source[0] / 36))),
        "-annotate", f"+{stroke * 3}+{round(source[1] / 12)}", label,
        str(tile),
    ]  # fmt: skip
    done = subprocess.run(command, capture_output=True, text=True, timeout=120, check=False)
    if done.returncode != 0:
        raise graphics.GraphicsError(f"magick could not draw the window on {tile}: {done.stderr[-800:]}")


def reframe_sheet(
    path: Path | str,
    *,
    out: str | None = None,
    moments: Sequence[float] | None = None,
    extremes: bool = False,
) -> dict[str, Any]:
    """Draw every placement's framing window on its own source frames.

    **The output of any framing decision is unreviewable without this**, and
    that is why it is built beside the framing rather than after it. The hand-
    framed teaser had 2 of its 15 windows wrong and *neither was visible in
    motion*: a badly-placed window reads as framing, because nothing in the
    frame says otherwise. What catches one is the window drawn on the whole
    source frame, where the part it is leaving out is right there beside it
    (PLAN.md § Per-shot framing, step 3; `~/lucid-final-cut/audit.py` is the
    prototype).

    Every placement the render shows — the picture lane's shots, or the edit's
    own segments where there is no lane — walked window by window, with the
    window in force drawn on the frame in red and labelled with the rect.
    Placements rather than clips, because framing is per shot: one clip used
    seven times gets seven placements, each showing the windows its own stretch
    of source reads.

    **The row is a window, not a placement, and that is a correction.** Three
    fixed fractions of each placement missed 14 of the vertical cut's 55
    windows, eight of them hand-approved — a window covering a small slice of a
    long placement is one no round fraction lands in, and it was reported as
    reviewed. So each placement is split at the boundaries it crosses and each
    stretch is sampled inside itself: every window that reaches the screen gets
    drawn, and `moments` are fractions of the stretch that shows it rather than
    of the whole placement. `windows` on a row still says how many the
    *placement* crosses, which is the preview/render asymmetry's own tell
    (CLAUDE.md). HISTORY.md § The thirty-nine windows, reviewed.

    **A tile is evidence about an instant, not an approval of the span**, and
    `extremes` is the answer to that. A static rect over a moving subject has a
    best moment and a sample can land on it: the teaser's opening window was
    184px out at its median and the one tile inside it landed 122px out, which
    reads as tight and fine. Drawing every window closed the coverage half of
    that finding; this closes the other half. With `extremes` each stretch is
    probed with the face detector and drawn where the subject is **leftmost,
    median and rightmost** rather than where the clock is round — and since the
    rect does not move inside a stretch, the worst moment is one of those two
    ends by construction. Worst tile first, labelled with how far the subject
    sits from the middle of the crop. It costs a detector and minutes of
    decoding, which is why it is opt-in; `_sheet_extremes` has the rule and the
    measurement. HISTORY.md § The tile that made a wrong window look right.

    Writes a tile per sample and one montage under `cache/sheets/`, and
    returns both paths and the table. `out` names the sheet somewhere else;
    `moments` overrides where inside each window's stretch it samples, as
    fractions — and is refused alongside `extremes`, which is what replaces
    them rather than something they tune.
    """
    project = Project.open(path)
    resolution = _mlt_resolution(project)
    if extremes and moments is not None:
        raise ProjectError(
            "moments are fractions of the clock and extremes are where the "
            "subject is — ask for one or the other, not both"
        )
    at = tuple(float(m) for m in (moments or SHEET_MOMENTS))
    if not at or any(m < 0 or m > 1 for m in at):
        raise ProjectError(f"sample moments are fractions of a placement, not {list(at)}")
    if extremes:
        # Asked before any decoding, for `reframe_detect`'s reason: a missing
        # interpreter is a refusal that should arrive now rather than after
        # ffmpeg has walked the film.
        detector = faces.available()
        if not detector["available"]:
            raise faces.FaceError(str(detector["why"]))

    placements, skipped = _sheet_placements(project, resolution)
    if not placements:
        raise ProjectError(
            "this project has no footage placements to sheet — there is nothing "
            "framed here to look at"
        )

    tiles: list[Path] = []
    rows: list[dict[str, Any]] = []
    dest_dir = project.sheet_dir
    shutil.rmtree(dest_dir, ignore_errors=True)
    dest_dir.mkdir(parents=True, exist_ok=True)

    # One entry per window a placement shows, in the order it shows them. The
    # split is the whole coverage fix: sampling the placement asks about the
    # window at whichever fractions happen to land inside it, and the windows
    # that get missed that way are precisely the short ones.
    #
    # **A frame of tolerance, never an epsilon** — `reframe_coverage`'s rule,
    # and it is not optional here either. A window boundary and the placement
    # that starts on it are the same instant a frame apart (20.39538 against
    # 20.39541 on the real cut), so an exact comparison splits off a stretch
    # 30µs long, draws three tiles of it, and labels the placement with the
    # window it is about to leave. Fifteen of the vertical's rows were that.
    frame = 1.0 / _export_fps(_clips_by_id(project))
    stretches: list[tuple[dict[str, Any], float, float, int]] = []
    for placement in placements:
        entry = placement["reframe"]
        begin = placement["src_start"]
        finish = begin + placement["duration"]
        windows = entry.windows() if entry is not None else ()
        # Dropped at the tail for the same reason: a window with under a frame
        # of a placement left is one that placement does not show. Whichever
        # placement starts there draws it as its own head.
        edges: list[float] = []
        for edge in sorted({begin, *(b for b, _ in windows if begin - frame <= b < finish - frame)}):
            if edges and edge - edges[-1] <= frame:
                # One instant. The later address wins, because that is the one
                # the render steps to and the one a rect is stored at.
                edges[-1] = edge
            else:
                edges.append(edge)
        for index, edge in enumerate(edges):
            stop = edges[index + 1] if index + 1 < len(edges) else finish
            stretches.append((placement, edge, stop, len(edges)))

    probed = _sheet_extremes(stretches, at) if extremes else {}

    for row, (placement, begin, finish, crossed) in enumerate(stretches):
        entry = placement["reframe"]
        source = entry.source if entry is not None else None
        # In extremes mode the picks *are* the samples; a stretch with no
        # geometry to be extreme against still gets its fractions, so every
        # window is drawn either way.
        chosen = probed.get(row, {}).get("picks") or [
            {
                "src_time": begin + (finish - begin) * moment,
                "subject_x": None,
                "offset": None,
                "faces": None,
                "pick": f"{moment:.2f}",
            }
            for moment in at
        ]
        samples = []
        for index, pick in enumerate(chosen):
            when = float(pick["src_time"])
            tile = dest_dir / f"{row:03d}-{index}-{pick['pick']}.png"
            picture.extract_frame(placement["path"], when, tile)
            crop = entry.crop_at(when) if entry is not None else None
            pane = entry.pane_at(entry.window_start(when)) if entry is not None else None
            if crop is not None and source is not None:
                label = f"{row} {placement['asset']} @{when:.2f}s  {_rect_text(crop)}"
                if pane is not None:
                    label += f" + {_rect_text(pane)} (split)"
                if pick["subject_x"] is not None:
                    # The number the tile is being read for: where the subject
                    # is against the middle of the crop, signed, so which way
                    # the window is wrong is on the tile rather than inferred.
                    label += f"  subj {pick['subject_x']} {pick['offset']:+} {pick['pick']}"
                    if pick["faces"] > 1:
                        # On the tile, not only in the table: this is the one
                        # number on a sheet that can be large and mean nothing,
                        # and a sheet is read as pictures.
                        label += f" ({pick['faces']} faces)"
                _draw_window(tile, crop, source, label, pane)
            tiles.append(tile)
            samples.append(
                {
                    "src_time": round(when, 3),
                    "crop": _rect_text(crop) if crop else None,
                    # Named rather than folded into `crop`, so a page built on
                    # this table can say which tiles are splits without parsing
                    # a label back apart.
                    "pane": _rect_text(pane) if pane else None,
                    "subject_x": pick["subject_x"],
                    "offset": pick["offset"],
                    "faces": pick["faces"],
                    "pick": pick["pick"],
                    "png": str(tile),
                }
            )
        rows.append(
            {
                "row": row,
                "shot": placement["index"],
                "asset": placement["asset"],
                # The stretch this row is about — one window's worth of one
                # placement, which is what the tiles are frames of.
                "src_start": round(begin, 3),
                "duration": round(finish - begin, 3),
                # And the placement it came out of, so a row can still be
                # traced back to a shot on the timeline.
                "placement_src_start": round(placement["src_start"], 3),
                "placement_duration": round(placement["duration"], 3),
                # The address the rect is stored at, which is what `reframe
                # --src-start` takes to change it.
                "window": round(entry.window_start(begin), 3) if entry is not None else None,
                # How many windows this *placement* crosses — counted off the
                # geometry rather than off where the samples landed, which is
                # the number that was wrong before. More than one is also the
                # preview/render asymmetry: the preview places the whole shot
                # by the window at its `src_start` (CLAUDE.md).
                "windows": crossed,
                # Whether any sampled frame of this placement is drawn as a
                # stacked split, which is what a review page filters on.
                "split": any(sample["pane"] for sample in samples),
                # And how much of the two panes is the same strip of source,
                # which is what the split is *judged* on — the sheet draws the
                # lower pane dashed so a reviewer can see the duplication, and
                # this is the number under it. None where the row is not a
                # split. `mlt.pane_overlap`.
                "pane_overlap": next(
                    (
                        mlt.pane_overlap(_parse_rect(sample["crop"]), _parse_rect(sample["pane"]))
                        for sample in samples
                        if sample["pane"] and sample["crop"]
                    ),
                    None,
                ),
                # How the tiles were chosen, and what the probing found. A row
                # says "no face in N probes" rather than reporting extremes it
                # does not have — an unsupported claim of evidence is the same
                # failure as a refused window read as a centre crop.
                "probe": probed.get(row, {}).get("probe"),
                "probes": probed.get(row, {}).get("probes"),
                "located": probed.get(row, {}).get("located"),
                # Read beside `worst_offset`, never after it: an offset off a
                # multi-face frame is the weighted centre of two subjects and
                # can be large with the shot's own face well inside the crop.
                "multi_face": probed.get(row, {}).get("multi_face"),
                "subject_min": probed.get(row, {}).get("subject_min"),
                "subject_max": probed.get(row, {}).get("subject_max"),
                # The worst the window is off across every probe, not only the
                # drawn ones. This is the number a sheet gets sorted by.
                "worst_offset": probed.get(row, {}).get("worst_offset"),
                "samples": samples,
            }
        )

    sheet = Path(out).expanduser() if out else dest_dir / "sheet.png"
    sheet.parent.mkdir(parents=True, exist_ok=True)
    command = [
        *graphics.magick_command(), "montage", *[str(tile) for tile in tiles],
        "-tile", f"{SHEET_PICKS if extremes else len(at)}x",
        "-geometry", f"{SHEET_TILE_WIDTH}x+3+3",
        "-background", "#222",
        str(sheet),
    ]  # fmt: skip
    done = subprocess.run(command, capture_output=True, text=True, timeout=600, check=False)
    if done.returncode != 0 or not sheet.exists():
        raise graphics.GraphicsError(f"magick could not montage the sheet: {done.stderr[-800:]}")

    return {
        "project": str(project.root),
        "canvas": f"{resolution[0]}x{resolution[1]}",
        "sheet": str(sheet),
        "rows": rows,
        # A row is a window shown, so this is no longer the placement count —
        # the two differ by exactly the windows the old sampling could miss.
        "count": len(rows),
        "placements": len(placements),
        # Where the tiles came from. `moments` is null under `extremes`, so
        # nothing reading this table can report fractions a run never used.
        "extremes": extremes,
        "moments": None if extremes else list(at),
        "probed": sum(1 for row in rows if row["located"]) if extremes else 0,
        "skipped": skipped,
    }


#: The scene score above which a change of picture is a camera cut. **Pinned by
#: judging the detections, not by agreeing with the hand table** — which is the
#: correction that moved it from 0.20. The first pin scored candidates against
#: the sixteen approved framing boundaries and called precision the share that
#: matched one, so a real camera cut in a shot nobody had framed counted
#: against the floor; precision "climbing" to 0.20 was the hand table's own
#: coverage, over three clips of nine. Every candidate inside the film's
#: placements from 0.05 up was then looked at, on the frames either side, over
#: all nine: **21 real cuts sat between 0.15 and 0.20, and not one false
#: positive**. The first non-cut is at 0.137, so 0.15 is the lowest round value
#: that is still all-cut with a margin (0.14 clears too, at 0.003 from the first
#: mistake — which is not a margin). `tests/test_scene_threshold.py` holds the
#: judgements and pins this from both sides. HISTORY.md § The scene threshold,
#: re-pinned; PLAN.md § The auto-framing detector, finding 1.
SCENE_THRESHOLD = 0.15
#: Frames sampled per window, and `describe.FRAMES_PER_WINDOW`'s number for
#: `describe.frame_times`' reason: a window boundary is where a cut is most
#: likely to be, so samples sit off both edges. Three is what finding 5 was
#: measured with.
DETECT_FRAMES = 3


def _detect_windows(
    placements: list[dict[str, Any]], threshold: float
) -> list[dict[str, Any]]:
    """Split every placement at its own camera cuts, and merge the duplicates.

    A window is `(clip_id, src_start)` — the same address a stored rect uses —
    running to the next cut inside the same placement, or to the placement's
    end. Cuts come from the *source*, so the boundaries are the footage's own
    and no edit can move one.

    Two placements reading the same stretch of a clip produce the same window
    twice, and it is one window: they would write to one address, and framing
    it twice from two samplings is how the second silently wins. Merged, it
    keeps every shot it serves and the widest span either placement showed, so
    the sampling covers what both of them put on screen.
    """
    windows: dict[tuple[str, int], dict[str, Any]] = {}
    for placement in placements:
        start = placement["src_start"]
        end = start + placement["duration"]
        inside = [
            cut
            for cut in placement["cuts"]
            if cut["score"] >= threshold and start < cut["src_time"] < end
        ]
        edges = [{"src_time": start, "score": None}, *inside]
        for index, edge in enumerate(edges):
            stop = edges[index + 1]["src_time"] if index + 1 < len(edges) else end
            # Millisecond keys, because two placements of one clip agree on a
            # cut to ffmpeg's own precision and not to a float's.
            key = (placement["asset"], round(edge["src_time"] * 1000))
            found = windows.get(key)
            if found is None:
                windows[key] = {
                    "clip_id": placement["asset"],
                    "path": placement["path"],
                    "source": placement["source"],
                    "src_start": edge["src_time"],
                    "src_end": stop,
                    "boundary": "placement" if edge["score"] is None else "cut",
                    "scene_score": edge["score"],
                    "shots": [placement["index"]],
                }
                continue
            found["src_end"] = max(found["src_end"], stop)
            found["shots"].append(placement["index"])
            # A window that is one placement's head and another's cut is both;
            # "placement" is the truthful label because the edit supplies it
            # for free and no detector had to find it.
            if edge["score"] is None:
                found["boundary"] = "placement"
                found["scene_score"] = None
    return sorted(windows.values(), key=lambda w: (w["clip_id"], w["src_start"]))


def reframe_detect(
    path: Path | str,
    *,
    clip_id: str | None = None,
    threshold: float = SCENE_THRESHOLD,
    frames: int = DETECT_FRAMES,
    apply: bool = False,
    split: bool = True,
) -> dict[str, Any]:
    """Propose a framing window per camera shot, from where the faces are.

    **The first pass at the framing `reframe` deliberately refuses to guess**
    (PLAN.md § The auto-framing detector). Every placement is split at its own
    camera cuts, each window is sampled at three moments, and the window is
    centred on the faces found there — which beats the centre crop it replaces
    on every column of the control: 0.755 mean overlap against 0.568, 111.6px
    displacement against 199.4, and **never the approved subject left entirely
    outside the frame** that the centre crop has on one shot of fifteen.

    **It proposes; it does not frame.** `apply` is off by default, which is the
    opposite of `cut --plan` and deliberately so: the pass is still 111px out on
    a 459px window — 24% of its width — and 2 of the 15 hand-framed windows were
    wrong in a way *no watch showed*. `reframe_sheet` is how either gets caught,
    so the flow is detect, sheet, apply. Applying writes through `ops.reframe`
    one window at a time, the same function the CLI, MCP and web UI call — this
    is a fourth client, never a fourth implementation — and it **never writes
    over a window that is already an override**, because that window is
    someone's decision and this has no way to know it is the worse one.

    **A window with no face is named, never guessed at.** Eight of the film's
    fifty-nine windows have no signal at all, and a silent fallback is
    indistinguishable in the output from a framing decision. They come back with
    `refused` saying so, the way a card with no record is reported rather than
    reconstructed — and with `falls_back_to`, which is the half that is easy to
    get wrong. Nothing is written for a refused window, so **whatever window is
    already in force carries over**: at the head of a clip that is the centre
    crop, and anywhere else it is the *previous shot's* framing. That is worse
    than the default rather than equal to it, because a stale window looks
    deliberate. On the film 4 of the 8 refusals inherit one that way.

    **A window one crop cannot hold is proposed as a stacked split**, which is
    the answer to the case the paragraph below names: two faces, both true
    positives, only one of them the shot. Two half-height panes hold both, at
    twice the width. `split` turns the offer off; the rule behind it is
    `faces.split_centres`, and it is deliberately strict — every sampled frame
    must hold two or three faces that one window cannot, which on the film is
    3 windows of 59 and 5.7% of the picture-seconds against the 14.8% a
    median-frame rule would have claimed. The count that would have been
    inherited from the spike, 24.8%, is neither.

    Nothing here chooses the *subject*: an oracle picking which detected face to
    frame on scores 0.863 to this rule's 0.755, and no property of the boxes says
    which face is the shot. `faces.py` has that finding and the reason it is not
    a fixable one.
    """
    if not 0 < threshold <= 1:
        raise ProjectError(f"a scene threshold is a score between 0 and 1, not {threshold}")
    if frames < 1:
        raise ProjectError(f"a window needs at least one frame sampled, not {frames}")

    project = Project.open(path)
    resolution = _mlt_resolution(project)

    # Asked before the scene scan, because the scan is minutes of decoding and
    # a missing interpreter is a refusal that should arrive now.
    detector = faces.available()
    if not detector["available"]:
        raise faces.FaceError(str(detector["why"]))

    placements, skipped = _sheet_placements(project, resolution)
    if clip_id is not None:
        clips = {str(clip.get("clip_id")) for clip in project.read_manifest().get("clips", [])}
        if clip_id not in clips:
            raise ProjectError(f"no clip {clip_id!r} in this project")
        placements = [p for p in placements if p["asset"] == clip_id]
    for placement in list(placements):
        entry = placement["reframe"]
        if entry is None:
            # No registered geometry, so there is no rect to express and no
            # centre crop being replaced. Named rather than dropped.
            skipped.append(
                {
                    "index": placement["index"],
                    "asset": placement["asset"],
                    "why": "this clip has no registered picture size to crop against",
                }
            )
            placements.remove(placement)
            continue
        placement["source"] = entry.source
    if not placements:
        raise ProjectError(
            "this project has no footage placements to frame — there is nothing "
            "here a window would apply to"
        )

    # One scan per clip, stopped at the last frame any placement of it reads:
    # a 730s cold open the film uses 71.8s of has no reason to be walked to the
    # end, and the decode is the whole cost of this half.
    scans: dict[str, list[dict[str, float]]] = {}
    for asset in {p["asset"] for p in placements}:
        used = [p for p in placements if p["asset"] == asset]
        scans[asset] = media.scene_cuts(
            used[0]["path"], until=max(p["src_start"] + p["duration"] for p in used)
        )
    for placement in placements:
        placement["cuts"] = scans[placement["asset"]]

    windows = _detect_windows(placements, threshold)
    jobs = [
        {
            "index": index,
            "media": str(window["path"]),
            "timestamps": dsc.frame_times(window["src_start"], window["src_end"], frames),
        }
        for index, window in enumerate(windows)
    ]
    detections = {result["index"]: result for result in faces.detect(jobs)}

    stored = _stored_reframes(project)
    # **A frame, not an epsilon.** ffmpeg reports this cut at 0.834167 and the
    # manifest holds 0.8342, because a stored window was addressed by hand
    # through a timeline offset while the scan reads raw presentation times —
    # 33µs apart, the same cut, and an exact-match test called fifteen of the
    # sixteen hand windows unframed and would have written a duplicate beside
    # each one. Two boundaries inside one source frame are one window: that is
    # not a tolerance for slop, it is the resolution the render has, since a
    # reframe is emitted as keyframes numbered in the producer's own source
    # frames (CLAUDE.md § The MLT reframe).
    same_window = 1.0 / _export_fps(_clips_by_id(project))
    _upper, _lower = mlt.pane_boxes(resolution)
    pane_shape = (_upper[2], _upper[3])
    report: list[dict[str, Any]] = []
    for index, window in enumerate(windows):
        source = window["source"]
        held = [at for at, *_ in stored.get(window["clip_id"], [])]
        current = (
            "override"
            if any(abs(at - window["src_start"]) <= same_window for at in held)
            else "centre"
        )
        entry: dict[str, Any] = {
            "clip_id": window["clip_id"],
            "src_start": round(window["src_start"], 4),
            "src_end": round(window["src_end"], 4),
            "boundary": window["boundary"],
            "scene_score": round(window["scene_score"], 3) if window["scene_score"] else None,
            "shots": sorted(set(window["shots"])),
            "sampled": [round(ts, 3) for ts in jobs[index]["timestamps"]],
            "faces": 0,
            "frames_with_faces": 0,
            # **Subjects, not detections.** `faces` above sums the boxes over
            # every sampled frame, so one face reads as 3 and a room watching a
            # television reads as 33. That number is the wrong one to set a
            # split threshold from and was nearly used as it: this is the
            # per-frame count, medianed, which makes the same window 11.
            "subjects": 0,
            "current": current,
            "rect": None,
            "pane": None,
            # How much of the two panes is the same strip of source, when this
            # window is offered as a split. **The number that decides whether a
            # split is worth having**, and it used to be worked out by hand off
            # the two rects every single time: the film's own separate at
            # 23–24% and its duplicating ones at 52–63%. Reported, never
            # enforced — `mlt.pane_overlap`.
            "pane_overlap": None,
            "applied": False,
            "refused": None,
            "falls_back_to": None,
        }
        found = detections[index]
        if "error" in found:
            entry["refused"] = f"the detector could not read this window: {found['error']}"
            report.append(entry)
            continue
        sampled = found["frames"]
        entry["faces"] = sum(len(frame["faces"]) for frame in sampled)
        entry["frames_with_faces"] = sum(1 for frame in sampled if frame["faces"])
        entry["subjects"] = int(
            statistics.median([len(frame["faces"]) for frame in sampled] or [0])
        )
        centre = faces.window_centre(sampled)
        if centre is None:
            entry["refused"] = f"no face in any of the {len(sampled)} frames sampled"
            report.append(entry)
            continue
        # The centre crop's own shape, moved. Taking the rect from
        # `mlt.centre_crop` rather than deriving one means the proposal is
        # already the canvas's aspect, so `reframe`'s grow-to-fit is a no-op on
        # it and the rect stored is the rect proposed.
        _x, y, width, height = mlt.centre_crop(source, resolution)
        entry["rect"] = _rect_text((faces.window_x(centre, source[0], width), y, width, height))

        # A window one crop cannot hold, offered as a stacked split. The pane
        # rects are the *pane's* geometry — full source height, so the scaled
        # frame is exactly one pane tall — which is the same rect
        # `_fit_pane_rect` would produce, so what is proposed is what gets
        # stored.
        seconds = window["src_end"] - window["src_start"]
        centres = (
            faces.split_centres(sampled, width)
            if split and seconds >= faces.MIN_SPLIT_SECONDS
            else None
        )
        if centres is not None:
            pane_width = round(source[1] * pane_shape[0] / pane_shape[1])
            if pane_width <= source[0]:
                near, far = (
                    faces.window_x(value, source[0], pane_width) for value in centres
                )
                # Two panes clamped to the same column are one window drawn
                # twice — the split gains nothing and costs half the height.
                if near != far:
                    upper = (near, 0, pane_width, source[1])
                    lower = (far, 0, pane_width, source[1])
                    entry["rect"] = _rect_text(upper)
                    entry["pane"] = _rect_text(lower)
                    entry["pane_overlap"] = mlt.pane_overlap(upper, lower)
        report.append(entry)

    # **A refused window is not a centre-cropped one, and saying so was wrong.**
    # Nothing is written for it, so whatever window is already in force simply
    # carries over — which at the head of a clip is the centre crop and
    # everywhere else is *the previous shot's framing*. On the film 4 of the 8
    # refusals inherit a different shot's window that way, and that is worse
    # than the default rather than equal to it: a stale window looks deliberate.
    # So each refusal names what will actually cover it — resolved as if these
    # proposals were applied, which is the question being asked even in a plan,
    # since a plan is read to decide whether to apply it.
    for entry in report:
        if entry["rect"] is not None:
            continue
        if entry["current"] == "override":
            entry["falls_back_to"] = "the override already at this in-point"
            continue
        covering = [at for at, *_ in stored.get(entry["clip_id"], [])] + [
            other["src_start"]
            for other in report
            if other["clip_id"] == entry["clip_id"]
            and other["rect"] is not None
            and other["current"] == "centre"
        ]
        earlier = [at for at in covering if at <= entry["src_start"] - same_window]
        entry["falls_back_to"] = (
            f"the window from {max(earlier):.3f}s — a different shot's framing"
            if earlier
            else "the centre crop"
        )

    written = 0
    if apply:
        for entry in report:
            if entry["rect"] is None:
                continue
            if entry["current"] == "override":
                entry["refused"] = (
                    "left alone — this window is already framed by hand, and a proposal "
                    "has no way to know it is the better one"
                )
                continue
            reframe(
                project.root,
                entry["clip_id"],
                rect=entry["rect"],
                pane=entry["pane"],
                src_start=entry["src_start"] or None,
            )
            entry["applied"] = True
            written += 1

    return {
        "project": str(project.root),
        "canvas": f"{resolution[0]}x{resolution[1]}",
        "threshold": threshold,
        "frames_per_window": frames,
        # How close a stored window has to be for this one to be the same
        # window. Reported rather than assumed, because it is the number that
        # decides whether `apply` leaves a hand-framed shot alone.
        "same_window_within": round(same_window, 5),
        "detector": detector,
        "windows": report,
        "count": len(report),
        "proposed": sum(1 for entry in report if entry["rect"] is not None),
        "refused": sum(1 for entry in report if entry["rect"] is None),
        # Of the proposals, how many are stacked splits. On the film this is 3
        # of 51 — a rule this strict is meant to be rare, and a run where it
        # is not is the signal to look at `reframe_sheet` before applying.
        "splits": sum(1 for entry in report if entry["pane"] is not None),
        "placements": len({shot for entry in report for shot in entry["shots"]}),
        "applied": written,
        "written": bool(written),
        "skipped": skipped,
    }


def reframe_coverage(
    path: Path | str,
    *,
    clip_id: str | None = None,
    threshold: float = SCENE_THRESHOLD,
) -> dict[str, Any]:
    """Which placed seconds are framed by a window chosen for an earlier shot.

    **The question `reframe_detect` cannot answer, because it is about the
    project as it stands rather than about a proposal.** A detect run reports
    `falls_back_to` for the windows it is refusing *this call*, and then throws
    it away; nothing is written for a refusal, so a project on disk has no way
    to say that 13.6s of one clip is held by a rect chosen for a shot that
    ended long before. The manifest, `status` and `reframe_sheet` were all
    clean over exactly that (HISTORY.md § The thirty-nine windows, reviewed).

    **One observable, two mechanisms, and this deliberately does not separate
    them** — because the render cannot. A window the detector refused writes
    nothing; a camera cut scoring under `threshold` is never offered a window
    at all. What reaches the film either way is one rect held across a cut, so
    what is measured is the cut with no window at it and the stretch of
    footage downstream of it.

    Every placement is walked against its own source's scene cuts. A cut with
    no window boundary within a frame of it opens a **stale stretch**, running
    to the next boundary or to the placement's end, and the whole stretch is
    framed by whatever was in force before the cut. Which is one of two things,
    and the distinction is the point: an **override** held across a cut is
    worse than the default, since a stale window looks deliberate, while the
    **centre crop** walking through one is only the default doing what it
    always did. `stale_seconds` counts the first; `default_seconds` the second.

    **A frame of tolerance, never an epsilon.** ffmpeg reports a cut at
    0.834167 where the manifest holds 0.8342 — the same cut, 33µs apart — and
    matching exactly reported 20 stale stretches on the film where there are 6.
    Two boundaries inside one source frame are one window, which is the
    resolution the render has (CLAUDE.md § The MLT reframe).

    **And the mirror, which is the one a viewer actually notices.** The walk
    above asks which cuts have no window; `steps` asks which windows have no
    cut — a boundary *inside* one placement, where the frame moves sideways
    and the picture behind it does not change. Coverage answers clean over
    exactly that, because nothing was held across anything: the teaser opened
    on 510px of sideways travel inside one continuous take, from a clip whose
    head was never framed, and every check in this project agreed with it
    (HISTORY.md § The teaser, re-cut). A boundary at a placement's own edge is
    not one of these — the timeline cuts there, so the frame is expected to.

    **The two directions do not use the same cut list, deliberately.** A cut
    has to score `threshold` to *demand* a window, because that floor was
    picked by a control against sixteen approved boundaries. It only has to be
    detected at all to *explain* one — a weak cut is still a picture change,
    and calling a justified boundary a defect sends someone to re-frame a shot
    that is already right. So `steps` is scored against the whole scan and each
    one carries `nearest_cut`, which is what says whether the boundary missed a
    real cut by 40ms or sits in the middle of a take.

    Needs no face detector: this is scene cuts against stored geometry, so it
    answers on a box where `reframe_detect` cannot run at all. It reads and
    never writes. Each stretch carries `timeline_start` — where it plays in the
    film — because the fix is to look at it, and `reframe_detect --clip` is
    what proposes a window for it.
    """
    if not 0 < threshold <= 1:
        raise ProjectError(f"a scene threshold is a score between 0 and 1, not {threshold}")

    project = Project.open(path)
    resolution = _mlt_resolution(project)
    placements, skipped = _sheet_placements(project, resolution)
    if clip_id is not None:
        clips = {str(clip.get("clip_id")) for clip in project.read_manifest().get("clips", [])}
        if clip_id not in clips:
            raise ProjectError(f"no clip {clip_id!r} in this project")
        placements = [p for p in placements if p["asset"] == clip_id]
    for placement in list(placements):
        if placement["reframe"] is None:
            skipped.append(
                {
                    "index": placement["index"],
                    "asset": placement["asset"],
                    "why": "this clip has no registered picture size to crop against",
                }
            )
            placements.remove(placement)
    if not placements:
        raise ProjectError(
            "this project has no footage placements to check — there is nothing "
            "here a window would apply to"
        )

    # One scan per clip, stopped at the last frame any placement of it reads —
    # `reframe_detect`'s own arithmetic, and for its reason: the decode is the
    # whole cost, and a 730s clip the film reads 71.8s of has no reason to be
    # walked to the end.
    scans: dict[str, list[dict[str, float]]] = {}
    for asset in {p["asset"] for p in placements}:
        used = [p for p in placements if p["asset"] == asset]
        scans[asset] = media.scene_cuts(
            used[0]["path"], until=max(p["src_start"] + p["duration"] for p in used)
        )

    same_window = 1.0 / _export_fps(_clips_by_id(project))
    stored = _stored_reframes(project)

    stale: list[dict[str, Any]] = []
    steps: list[dict[str, Any]] = []
    cuts_seen = 0
    cuts_framed = 0
    steps_seen = 0
    steps_cut = 0
    for placement in sorted(placements, key=lambda p: p["timeline_start"]):
        entry = placement["reframe"]
        start = placement["src_start"]
        end = start + placement["duration"]
        boundaries = [at for at, _ in entry.windows()]
        held = [at for at, *_ in stored.get(placement["asset"], [])]
        cuts = [cut for cut in scans[placement["asset"]] if cut["score"] >= threshold]

        def framed(at: float, edges: list[float] = boundaries) -> bool:
            return any(abs(edge - at) <= same_window for edge in edges)

        shown = [cut for cut in cuts if start < cut["src_time"] < end]
        cuts_seen += len(shown)
        cuts_framed += sum(1 for cut in shown if framed(cut["src_time"]))

        # The mirror. Only boundaries *inside* the placement: one at either
        # edge is a frame change the timeline's own cut already explains.
        #
        # **And "inside" takes the same frame of tolerance everything else
        # here does.** A window placed at a shot boundary is the normal case —
        # it is what `reframe_detect` writes — and the placement's own
        # `src_start` is computed while the window's is a rounded manifest
        # value, so they sit ~1e-7 apart and a strict comparison calls every
        # one of them an interior boundary. Measured before this line existed:
        # 13 of 15 findings on the vertical cut were that, and the two real
        # ones were the two a watch had already found.
        for at in [edge for edge in boundaries if start + same_window < edge < end - same_window]:
            before = entry.crop_at(at - same_window)
            after = entry.crop_at(at)
            was_split = entry.pane_at(entry.window_start(at - same_window))
            is_split = entry.pane_at(at)
            if before == after and was_split == is_split:
                # Two addresses, one framing — nothing moves, so there is
                # nothing for a cut to justify.
                continue
            steps_seen += 1
            # The whole scan, not the thresholded list: a cut too weak to
            # demand a window is still enough to explain one.
            near = min(scans[placement["asset"]], key=lambda c: abs(c["src_time"] - at), default=None)
            if near is not None and abs(near["src_time"] - at) <= same_window:
                steps_cut += 1
                continue
            steps.append(
                {
                    "index": placement["index"],
                    "asset": placement["asset"],
                    "timeline_at": round(placement["timeline_start"] + (at - start), 3),
                    "src_time": round(at, 4),
                    "from_rect": list(before),
                    "to_rect": list(after),
                    # In the source's own pixels, like the rects — how far the
                    # frame travels, which is what makes one of these visible
                    # rather than merely present.
                    "shift": round(
                        hypot(
                            (after[0] + after[2] / 2) - (before[0] + before[2] / 2),
                            (after[1] + after[3] / 2) - (before[1] + before[3] / 2),
                        )
                    ),
                    "nearest_cut": round(near["src_time"], 4) if near else None,
                    "nearest_cut_score": round(near["score"], 3) if near else None,
                    "nearest_cut_gap": round(abs(near["src_time"] - at), 3) if near else None,
                }
            )

        # **The question is asked of the footage, not of the cut** — because a
        # placement can begin *downstream* of the cut that stranded it and
        # never contain one. The film has three of those and an earlier walk
        # over the cuts inside each placement could not see any of them: the
        # cut is in source nothing shows, and the placement is stale from its
        # own first frame. So the stretch is split wherever the framing could
        # change — a window boundary, or a cut the framing does not follow —
        # and each piece is asked what is covering it.
        edges = {start}
        edges.update(at for at in boundaries if start < at < end)
        edges.update(
            cut["src_time"] for cut in shown if not framed(cut["src_time"])
        )
        points = sorted(edges)

        run: dict[str, Any] | None = None
        for index, at in enumerate(points):
            stop = points[index + 1] if index + 1 < len(points) else end
            governing = entry.window_start(at)
            # A cut between where this window began and where this footage
            # starts is the whole finding: the picture changed and the framing
            # did not follow it.
            crossed = [
                cut
                for cut in cuts
                if governing + same_window < cut["src_time"] <= at + same_window
            ]
            if not crossed:
                run = None
                continue
            # Two unframed cuts under one window are one stale stretch, not
            # two: `cold-open` holds a single rect across four camera setups
            # and that is one thing wrong. A change of governing window ends
            # the run even when the new one is stale too, because they are
            # different windows to go and fix.
            if run is not None and abs(run["held_from"] - governing) <= same_window:
                run["src_end"] = round(stop, 4)
                run["seconds"] = round(stop - run["src_start"], 3)
                run["cuts"] = sorted({*run["cuts"], *(round(c["src_time"], 4) for c in crossed)})
                continue
            override = framed(governing, held)
            run = {
                "index": placement["index"],
                "asset": placement["asset"],
                "timeline_start": round(placement["timeline_start"] + (at - start), 3),
                "src_start": round(at, 4),
                "src_end": round(stop, 4),
                "seconds": round(stop - at, 3),
                "held_from": round(governing, 4),
                # `reframe_detect`'s own two answers, in its own words: this is
                # the same question asked of a project rather than of a
                # proposal, and two vocabularies for one fact is how they drift.
                "framed_by": (
                    f"the window from {governing:.3f}s — a different shot's framing"
                    if override
                    else "the centre crop"
                ),
                "stale": override,
                "cuts": sorted({round(cut["src_time"], 4) for cut in crossed}),
                "scores": sorted({round(cut["score"], 3) for cut in crossed}),
            }
            stale.append(run)

    placed = sum(p["duration"] for p in placements)
    held_over = [row for row in stale if row["stale"]]
    stale_seconds = sum(row["seconds"] for row in held_over)
    default_seconds = sum(row["seconds"] for row in stale if not row["stale"])
    return {
        "project": str(project.root),
        "canvas": f"{resolution[0]}x{resolution[1]}",
        "threshold": threshold,
        "same_window_within": round(same_window, 5),
        "placements": len(placements),
        "placed_seconds": round(placed, 3),
        "cuts": cuts_seen,
        "cuts_framed": cuts_framed,
        "cuts_unframed": cuts_seen - cuts_framed,
        "stretches": stale,
        # The other direction, counted the same way round: boundaries that
        # move the frame inside one placement, and how many of them the
        # picture accounts for.
        "steps_seen": steps_seen,
        "steps_cut": steps_cut,
        "steps": steps,
        # The headline, and the only number that is a defect: an override held
        # across a camera cut. The centre crop walking through one is the
        # default doing what it always did, counted beside it and not with it.
        "stale_seconds": round(stale_seconds, 3),
        "stale_share": round(stale_seconds / placed, 4) if placed else 0.0,
        "stale_stretches": len(held_over),
        "default_seconds": round(default_seconds, 3),
        "skipped": skipped,
    }


def _is_layered(project: Project, edit: tl.Edit) -> bool:
    """Does this timeline need the MLT writer?

    Three ways to get there and they hit the same wall: a cue table lays
    picture over the edit, an edit naming two clips already holds two `src`
    files, and a canvas override names a shape auto-editor can only
    letterbox into. auto-editor 31.x refuses to *export* the first two
    (exit 2) and *renders* them at 720x576 with exit 0 (CLAUDE.md); it would
    take the third and quietly ignore it, which is the same failure wearing
    a different hat. All three route through the MLT writer.
    """
    if len({segment.clip_id for segment in edit.segments}) > 1:
        return True
    manifest = project.read_manifest()
    return bool(manifest.get("cues") or manifest.get(CANVAS_KEY))


def _mlt_resolution(project: Project) -> tuple[int, int]:
    """The canvas to declare in the MLT profile."""
    return _stored_canvas(project) or _footage_resolution(project)


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
    # Which clip each file on the timeline is, so a reframe stored against a
    # clip_id reaches the resource the writer keys its nodes on. Built from the
    # entries rather than from the manifest so an unused (or missing) clip
    # cannot be resolved on the way past.
    clip_of: dict[str, str] = {}
    for segment, (offset, frames) in zip(edit.segments, autoeditor.frame_layout(edit, rate)):
        clip = media.get_clip(project, segment.clip_id)
        resource = str(media.media_path(project, clip))
        clip_of[resource] = segment.clip_id
        audio.append(
            mlt.Entry(
                resource=resource,
                src_in=offset,
                frames=frames,
                has_video=bool(clip.get("has_video")),
            )
        )

    shots, lane = _picture_plan(project, rate)
    for shot in shots:
        if not shot["is_image"]:
            clip_of[shot["asset_path"]] = shot["asset"]

    resolution = _mlt_resolution(project)
    by_clip = _reframe_map(project, resolution)
    reframes = {
        resource: by_clip[clip] for resource, clip in clip_of.items() if clip in by_clip
    }
    document = mlt.document(
        audio=audio,
        picture=lane,
        rate=rate,
        resolution=resolution,
        reframe=reframes,
        name=project.read_manifest().get("name") or project.root.name,
    )
    return {
        "document": document,
        "rate": rate,
        "resolution": resolution,
        "shots": shots,
        "frames": sum(entry.frames for entry in audio),
        "sources": len({entry.resource for entry in [*audio, *lane]}),
        # What the render will actually crop, named where the render is built
        # rather than left for a pixel probe to discover.
        "reframed": sorted(
            clip
            for resource, clip in clip_of.items()
            if resource in reframes and not reframes[resource].is_identity(resolution)
        ),
    }


def _mlt_reply(built: dict[str, Any], edit: tl.Edit, **extra: Any) -> dict[str, Any]:
    """The fields both multi-source roads report, so they cannot drift apart."""
    return {
        "writer": extra.pop("writer"),
        # The shape the document was actually built at, said out loud because
        # a preset can now claim one (`PRESET_ASPECT`) and a reply that only
        # echoes the preset name proves nothing about what got written.
        "canvas": "{}x{}".format(*built["resolution"]),
        "timebase": built["rate"],
        "segments": len(edit.segments),
        "shots": len(built["shots"]),
        "sources": built["sources"],
        "frames": built["frames"],
        # Named on both roads because a crop is a decision about what is on
        # screen, and the render that made it looks entirely plausible.
        "reframed": built["reframed"],
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
    silently ruins it. A `canvas` override joins them for the same reason:
    auto-editor would take the export and ignore the canvas, which is the same
    silent wrong output wearing a different hat. The reply says which road was
    taken: `"writer"` is `"auto-editor"`, `"mlt"`, or `"melt"`.

    `preset` names one of `EXPORT_PRESETS` (`"youtube"`, `"web"`,
    `"tiktok-reels"`) or `"custom"` (which requires `resolution`) — a bundle
    of the same four consumer keys `picture.RENDER_ARGS` already hardcodes on
    the melt path, and of auto-editor's own quality flags on the single-source
    path. `resolution` sets a `WIDTH,HEIGHT` output size on the single-source
    path only — **it letterboxes the existing 16:9 frame, it does not crop or
    reframe it**, so it is not a substitute for a vertical/9:16 export.

    **`"tiktok-reels"` checks the project's shape and never sets it**
    (`PRESET_ASPECT`, PLAN.md § Aspect swap step 5). A preset whose name is a
    claim about geometry refuses a canvas that contradicts it, naming the
    `canvas` command that fixes it — because the alternative, an export flag
    reshaping the project on the way past, is the same silent wrong output as
    picking the writer from an argument. Its four encode values are
    `"youtube"`'s: both platforms re-encode the upload, so the source wants
    the best quality the measured-safe keys can say. The reply's `"canvas"` is
    the shape the render was actually built at, on either road.
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
    _check_preset_canvas(project, preset)
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
        # The project's own shape, which is what this road renders — `-res`
        # letterboxes on top of it and is reported separately as
        # `"resolution"`, measured off the finished file rather than asked for.
        "canvas": "{}x{}".format(*_mlt_resolution(project)),
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
    """The reference canvas for captions: the picture's shape, not its size.

    Reads the project's canvas override before the footage, because the two
    derivations of this fact have to move together — sizes and margins quoted
    against a 16:9 reference and burned into a 9:16 render stretch the
    glyphs, which is what `captions.canvas` exists to prevent.
    """
    override = _stored_canvas(project)
    if override is not None:
        return captions.canvas(*override)
    for clip in project.read_manifest().get("clips", []):
        if clip.get("has_video"):
            return captions.canvas(clip.get("width"), clip.get("height"))
    return captions.DEFAULT_RESOLUTION


#: Where a project keeps its caption look. A manifest key rather than a new
#: file, and read with `.get()` rather than behind a schema bump: a project
#: written before this existed is not wrong, it is unstyled, and bumping
#: `SCHEMA_VERSION` for an additive key would make `Project.open` refuse every
#: existing project to gain nothing.
CAPTION_STYLE_KEY = "caption_style"


def _stored_caption_style(project: Project) -> dict[str, Any]:
    stored = project.read_manifest().get(CAPTION_STYLE_KEY)
    if stored is None:
        return {}
    if not isinstance(stored, dict):
        raise captions.CaptionError(
            f"{project.manifest_path}'s {CAPTION_STYLE_KEY!r} must be a JSON object"
        )
    return stored


#: Words the transcript holds that the recording never said — whisper reading
#: across a retake splice and emitting both takes interleaved (HISTORY.md § The
#: hand-framed teaser, watched). Additive and optional the way `CANVAS_KEY` and
#: `CAPTION_STYLE_KEY` are: absent means what every older manifest meant, that
#: every transcribed word was spoken, so it takes no `SCHEMA_VERSION` bump.
#:
#: **Word-indexed, for the reason cues are** — the transcript indexes the
#: source, so no cut can invalidate a mark, and `Word.index` survives the
#: filtering below because a transcript never renumbers.
UNSPOKEN_KEY = "unspoken"


def _stored_unspoken(project: Project) -> dict[str, dict[int, str]]:
    """Per clip, the word indices marked never-spoken and the text each was.

    The text is on the record so the mark can be *checked* rather than
    trusted: an index is only meaningful against the transcript it was taken
    from, and re-transcribing a clip renumbers nothing but does change what
    sits at each index. `_spoken_transcripts` compares before it drops.
    """
    stored = project.read_manifest().get(UNSPOKEN_KEY, [])
    if not isinstance(stored, list):
        raise tx.TranscriptError(
            f"{project.manifest_path}'s {UNSPOKEN_KEY!r} must be a JSON array"
        )
    marked: dict[str, dict[int, str]] = {}
    for record in stored:
        marked.setdefault(str(record["clip_id"]), {})[int(record["word_index"])] = str(
            record.get("text", "")
        )
    return marked


def _spoken_transcripts(
    project: Project, transcripts: dict[str, tx.Transcript]
) -> tuple[dict[str, tx.Transcript], dict[str, Any]]:
    """The transcripts with the never-spoken words taken out.

    The one derivation, shared by `_caption_cues` and `verify` for the reason
    `_caption_cues` is itself shared: what the window draws, what the subtitle
    file contains and what the render is checked against cannot be three
    different word sequences. A word removed here is removed from all three,
    and `verify` reports the count so a render is never silently checked
    against a shortened expectation.

    **A stale mark is kept, never applied.** If the text on the record and the
    text at that index disagree, the transcript has been replaced under the
    mark, and the two failures are not symmetric: a word wrongly left on
    screen is visible to anyone watching, while a real word silently dropped
    is invisible in every check lucid has. So a mismatch is reported as
    `unspoken_stale` and the word stays.
    """
    marked = _stored_unspoken(project)
    if not marked:
        return transcripts, {"unspoken": 0, "unspoken_stale": []}

    spoken: dict[str, tx.Transcript] = {}
    dropped = 0
    stale: list[dict[str, Any]] = []
    for clip_id, transcript in transcripts.items():
        indices = marked.get(clip_id)
        if not indices:
            spoken[clip_id] = transcript
            continue
        keep: list[tx.Word] = []
        for word in transcript.words:
            recorded = indices.get(word.index)
            if recorded is None:
                keep.append(word)
                continue
            if recorded and recorded != word.text:
                stale.append(
                    {
                        "clip_id": clip_id,
                        "word_index": word.index,
                        "recorded": recorded,
                        "found": word.text,
                    }
                )
                keep.append(word)
                continue
            dropped += 1
        spoken[clip_id] = replace(transcript, words=tuple(keep))
    return spoken, {"unspoken": dropped, "unspoken_stale": stale}


def caption_style(
    path: Path | str,
    *,
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

    **The style is project state; the captions are derived.** That separation
    is the whole point of this op rather than a pile of arguments on
    `add_captions`: regenerating captions after a cut re-runs the derivation
    and picks the style back up, so "restyle, then keep editing" cannot lose
    the styling — there is nothing to preserve, because nothing was ever
    coupled to a particular generation.

    Called with no arguments it changes nothing and reports the current look,
    which is also how to find out what the fields are called. Any argument
    sets that field and leaves the rest alone; `reset` drops every override
    first, so `reset` plus `preset` is how to start clean from a preset.

    What is stored is the base preset name plus only the fields overridden on
    top of it — never a flattened copy — so the manifest stays readable and a
    later improvement to a preset still reaches a project that only changed
    its size. `plan` resolves and validates without writing.

    Colours take `#rrggbb`, `#rrggbbaa`, a name (`yellow`, `white`, …) or an
    ASS `&H…` value; positions are named (`bottom`, `top-right`, …). Both are
    echoed back resolved, in both vocabularies, because ASS quotes colours
    alpha-first-and-backwards and a value that looks right is routinely a
    different colour than the one meant.
    """
    project = Project.open(path)
    changes = {
        "preset": preset,
        "font": font,
        "size": size,
        "text": text,
        "highlight": highlight,
        "outline_colour": outline_colour,
        "box_colour": box_colour,
        "bold": bold,
        "box": box,
        "outline_width": outline_width,
        "shadow": shadow,
        "position": position,
        "margin": margin,
        "karaoke": karaoke,
        "max_words": max_words,
        "max_gap": max_gap,
        "max_duration": max_duration,
        "hold": hold,
    }
    changes = {field: value for field, value in changes.items() if value is not None}

    base = {} if reset else _stored_caption_style(project)
    style = captions.resolve({**base, **changes})

    write = bool(changes or reset) and not plan
    if write:
        manifest = project.read_manifest()
        if style.stored:
            manifest[CAPTION_STYLE_KEY] = style.stored
        else:
            manifest.pop(CAPTION_STYLE_KEY, None)
        project.write_manifest(manifest)

    return {
        "project": str(project.root),
        "changed": sorted(changes),
        "reset": bool(reset),
        "written": write,
        "plan": bool(plan),
        # Reported on every call, not only when the font changes: a project can
        # be opened on a machine that has a different set of fonts from the one
        # it was styled on, and the substitution is silent at every other layer.
        "font": captions.font_match(style.ass.font),
        **style.describe(),
    }


def _caption_cues(
    project: Project,
    edit: tl.Edit,
    style: captions.Style,
    clip_id: str | None,
) -> tuple[list[captions.Cue], list[captions.CueWord], int, dict[str, Any]]:
    """Place and group every transcribed word — the one derivation.

    Shared by `caption_view` and `add_captions` so that what the window draws
    and what the subtitle file contains cannot be two different groupings of
    the same words. The grouping numbers come off the style for the same
    reason the font does: line breaks are part of the look.
    """
    transcripts = _transcripts_for(project, clip_id)
    transcripts, unspoken = _spoken_transcripts(project, transcripts)
    placed, cut = captions.place(edit, transcripts)
    cues = captions.group(
        placed,
        max_words=style.max_words,
        max_gap=style.max_gap,
        max_duration=style.max_duration,
        hold=style.hold,
    )
    return cues, placed, cut, {"clips": sorted(transcripts), **unspoken}


def unspoken_add(path: Path | str, clip_id: str, word_index: int) -> dict[str, Any]:
    """Mark a word the transcript holds and the recording never said.

    The subject is one failure and not a general edit: whisper transcribes
    straight *across* a retake splice and emits words from both takes
    interleaved, so a word appears in the index that was never spoken
    (HISTORY.md § The hand-framed teaser, watched). It is in the transcript
    and in nothing else — not the audio, not the render — so every consumer of
    the transcript carries it and nothing downstream can tell it from a word
    somebody said quietly.

    This does not touch the transcript file, and it must not: the transcript
    is an immutable index over source media, word indices never renumber, and
    a cue at word 366 has to keep meaning word 366. What it writes is a mark
    beside the transcript, addressed the same way a cue is, so a cut can no
    more invalidate it than it can invalidate a cue.

    **It removes a word from captions, from `caption_view` and from what
    `verify` expects — the three that read the transcript rather than the
    audio.** It changes no audio, no timing and no shot: a marked word's
    seconds still belong to the words either side of it, because the sound in
    them is the take that was kept.

    Echoes the word it resolved to plus the three either side, for the reason
    every word-indexed tool here does: an index one past the intended word
    reads correctly on its own.
    """
    project = Project.open(path)
    media.get_clip(project, clip_id)
    parsed = _transcript(project, clip_id)
    word_index = int(word_index)
    echo = _cue_echo(parsed, word_index)

    manifest = project.read_manifest()
    marks = manifest.setdefault(UNSPOKEN_KEY, [])
    if any(m["clip_id"] == clip_id and int(m["word_index"]) == word_index for m in marks):
        raise tx.TranscriptError(
            f"word {word_index} of {clip_id!r} is already marked unspoken — "
            "remove it with unspoken_rm first (CLI: `lucid unspoken rm`)"
        )
    marks.append(
        {"clip_id": clip_id, "word_index": word_index, "text": parsed.words[word_index].text}
    )
    marks.sort(key=lambda m: (m["clip_id"], int(m["word_index"])))
    project.write_manifest(manifest)
    return {"clip_id": clip_id, "marked": len(marks), **echo}


def unspoken_rm(path: Path | str, clip_id: str, word_index: int) -> dict[str, Any]:
    """Unmark a word, putting it back into captions and into `verify`."""
    project = Project.open(path)
    word_index = int(word_index)
    manifest = project.read_manifest()
    marks = manifest.get(UNSPOKEN_KEY, [])
    kept = [
        m
        for m in marks
        if not (m["clip_id"] == clip_id and int(m["word_index"]) == word_index)
    ]
    if len(kept) == len(marks):
        raise tx.TranscriptError(
            f"word {word_index} of {clip_id!r} is not marked unspoken"
        )
    if kept:
        manifest[UNSPOKEN_KEY] = kept
    else:
        manifest.pop(UNSPOKEN_KEY, None)
    project.write_manifest(manifest)
    return {"clip_id": clip_id, "word_index": word_index, "marked": len(kept)}


def unspoken_ls(path: Path | str) -> dict[str, Any]:
    """Every word marked never-spoken, with what the transcript says now.

    `stale` is the mark whose recorded text and current text disagree — the
    transcript was replaced under it — and those are reported here rather than
    applied anywhere, so a re-transcribe surfaces as a list to re-check rather
    than as words vanishing from a caption file.
    """
    project = Project.open(path)
    marked = _stored_unspoken(project)
    rows: list[dict[str, Any]] = []
    for clip_id in sorted(marked):
        try:
            parsed = _transcript(project, clip_id)
        except tx.TranscriptError:
            parsed = None
        for index in sorted(marked[clip_id]):
            recorded = marked[clip_id][index]
            found = (
                parsed.words[index].text
                if parsed is not None and 0 <= index < len(parsed.words)
                else None
            )
            row: dict[str, Any] = {
                "clip_id": clip_id,
                "word_index": index,
                "text": recorded,
                "found": found,
                "stale": bool(recorded and found is not None and recorded != found),
            }
            if parsed is not None and 0 <= index < len(parsed.words):
                row.update(_context(parsed, index, index))
            rows.append(row)
    return {
        "project": str(project.root),
        "count": len(rows),
        "stale": sum(1 for row in rows if row["stale"]),
        "unspoken": rows,
    }


#: How far either side of a candidate word to read the render's own words when
#: asking whether it was said. Wide enough to survive whisper placing a word a
#: few hundred milliseconds off, narrow enough that a common token borrowed
#: from the next sentence cannot vouch for one in this one.
UNSPOKEN_PAD = 1.5

#: A word this much of whose own duration survived the edit is *asked about*,
#: never removed — the removing is the render's answer, below. Set where it
#: asks about little and misses nothing: over the whole Scream film, 947 of
#: 958 surviving words survive **whole**, and the 11 under this floor hold
#: every clipped fragment in the cut, the shortest being 33ms of a `The`.
#: A floor that decided anything here would be wrong for the reason the
#: overlap scan has none (HISTORY.md § The overlap scan) — partial survival is
#: normal, and 0.48 of a word is a word.
UNSPOKEN_KEPT_SHARE = 0.5


def unspoken_detect(
    path: Path | str,
    render: Path | str,
    *,
    clip_id: str | None = None,
    transcript_path: Path | str | None = None,
    model: str | None = None,
    language: str | None = None,
    pad: float = UNSPOKEN_PAD,
    apply: bool = False,
) -> dict[str, Any]:
    """Propose the words the render's own ears say were never spoken.

    Two independent signals, and the intersection is the proposal — neither
    alone is safe. `transcript.find_overlaps` says *where a seam is*: a word
    starting before the one ahead of it ends is whisper reading across a
    splice, which is the only mechanism known to invent a word here. The
    render's transcription says *what was actually said*, and it is the only
    witness that answers to the audio rather than to the index. A seam word
    the render does not say is an invention; a seam word it does say is a word
    somebody said at a splice, and there are plenty.

    **Counted rather than looked up, because the inventions are function
    words.** Whisper's seams produce "The That's the ceiling" and "what was
    the this all about" as readily as "Billions" — asking "does the render say
    'the' near here" answers yes off the *real* `the` standing next to the
    invented one. So the candidate's token is counted in the timeline's words
    over the window and in the render's words over the same seconds, and it is
    proposed only where the timeline has more of them than the render heard.

    The two clocks agree by construction: a verified render is a render *of
    this timeline*, so a word's timeline seconds and the heard word's seconds
    are the same seconds. That is what makes a local window possible at all,
    and it is why this reads the render rather than diffing two whole word
    sequences — a global diff cannot say which of six `the`s it lost.

    `apply=False` is the default, the same way round as `reframe_detect` and
    for the same reason: this proposes a change to what a caption *says*, the
    evidence is a whisper run, and a wrongly applied mark deletes a real word
    from every check lucid has. Read the echoes, then apply.

    `transcript_path` takes an existing transcription of the render — the
    cached one `verify` leaves behind is the obvious candidate, and it is
    passed explicitly rather than found, for `verify`'s own reason: a
    re-render under the same filename would otherwise be judged against the
    previous render's audio.
    """
    project = Project.open(path)
    edit = _load_edit(project)
    transcripts = _transcripts_for(project, clip_id)
    already = _stored_unspoken(project)

    render_path = Path(render).expanduser()
    if transcript_path is not None:
        heard_transcript = tx.load(transcript_path, clip_id="render")
        origin = str(transcript_path)
    else:
        model = model or asr.DEFAULT_MODEL
        payload = asr.transcribe(
            render_path, model=model, language=language or _shared_language(transcripts)
        )
        if not payload.get("words") and not payload.get("segments"):
            raise vfy.VerifyError(
                f"whisper heard no speech at all in {render_path.name} — there is "
                "nothing here to judge a transcript against"
            )
        heard_transcript = tx.parse_whisper(
            payload, clip_id="render", origin=f"whisper:{model}"
        )
        cached = project.verify_dir / f"{render_path.stem}.json"
        tx.save(heard_transcript, cached)
        origin = str(cached)

    heard = [
        (word.start, word.end, token)
        for word in heard_transcript.words
        for token in vfy.tokens([word.text])
    ]

    proposals: list[dict[str, Any]] = []
    seams_seen = 0
    fragments_seen = 0
    for name, transcript in sorted(transcripts.items()):
        marked = already.get(name, {})
        # Every word placed on the timeline, with the source index kept: the
        # question is asked of what plays, and answered against what was heard.
        placed: list[tuple[int, float, float, str]] = []
        for word in transcript.words:
            span = edit.timeline_span(
                name, word.start, max(word.end, word.start + captions.MIN_WORD)
            )
            if span is not None:
                placed.append((word.index, span[0], span[1], word.text))
        at_index = {index: (start, end) for index, start, end, _ in placed}

        # Two candidate sources, one confirmation. A seam is where whisper
        # *invented* a word; a fragment is where a cut left a sliver of a real
        # one — 33ms of a `The` from an abandoned take reads on screen as a
        # whole word and is inaudible. Different mechanisms, same symptom, and
        # widening the candidates costs nothing because it is the render that
        # decides. `seam` is None for the second kind: there is no splice to
        # quote, and claiming one would put a false reason on the record.
        candidates: dict[int, dict[str, Any] | None] = {}
        for seam in tx.find_overlaps(transcript.words):
            seams_seen += 1
            for index in range(seam["first_word"], seam["last_word"] + 1):
                candidates.setdefault(index, seam)
        for index, start, end, _ in placed:
            word = transcript.words[index]
            spoken_for = word.end - word.start
            if spoken_for <= 0:
                continue
            if (end - start) / spoken_for < UNSPOKEN_KEPT_SHARE:
                fragments_seen += 1
                candidates.setdefault(index, None)

        for index in sorted(candidates):
            if index in marked or index not in at_index:
                continue
            seam = candidates[index]
            word = transcript.words[index]
            token = vfy.tokens([word.text])
            if not token:
                # Normalises to nothing — "-" and its friends. The render can
                # never be asked about it, so the candidacy is the only
                # evidence there is, and it is enough: a token with no letters
                # in it was never a word anyone said.
                proposals.append(
                    _unspoken_proposal(transcript, seam, index, heard_says=None)
                )
                continue
            start, end = at_index[index]
            window = (start - pad, end + pad)
            mine = sum(
                1
                for _, other_start, other_end, text in placed
                if window[0] <= other_start and other_end <= window[1]
                for other in vfy.tokens([text])
                if other == token[0]
            )
            theirs = sum(
                1
                for heard_start, heard_end, other in heard
                if other == token[0]
                and heard_end >= window[0]
                and heard_start <= window[1]
            )
            if mine > theirs:
                proposals.append(
                    _unspoken_proposal(transcript, seam, index, heard_says=(mine, theirs))
                )

    applied = 0
    if apply:
        manifest = project.read_manifest()
        marks = manifest.setdefault(UNSPOKEN_KEY, [])
        for proposal in proposals:
            marks.append(
                {
                    "clip_id": proposal["clip_id"],
                    "word_index": proposal["word_index"],
                    "text": proposal["text"],
                }
            )
            applied += 1
        marks.sort(key=lambda m: (m["clip_id"], int(m["word_index"])))
        project.write_manifest(manifest)

    return {
        "project": str(project.root),
        "render": str(render_path),
        "heard_transcript": origin,
        "pad": pad,
        "seams": seams_seen,
        "fragments": fragments_seen,
        "already_marked": sum(len(v) for v in already.values()),
        "count": len(proposals),
        "applied": applied,
        "apply": apply,
        "proposals": proposals,
    }


def _unspoken_proposal(
    transcript: tx.Transcript,
    seam: dict[str, Any] | None,
    index: int,
    *,
    heard_says: tuple[int, int] | None,
) -> dict[str, Any]:
    """One proposal, echoed the way every word-indexed tool here echoes."""
    word = transcript.words[index]
    why = (
        "no token — a candidate with no letters in it"
        if heard_says is None
        else f"the timeline says it {heard_says[0]}x here, the render says it {heard_says[1]}x"
    )
    return {
        "clip_id": transcript.clip_id,
        "word_index": index,
        "text": word.text,
        "start": word.start,
        "end": word.end,
        # Which mechanism put it up for the question, in its own words: a
        # splice whisper read across, or a cut that left a sliver. Naming the
        # wrong one is worse than naming none, so the second says `null`.
        "found_by": "seam" if seam is not None else "fragment",
        "seam": seam["text"] if seam is not None else None,
        "seam_words": [seam["first_word"], seam["last_word"]] if seam is not None else None,
        "overlap": seam["worst"] if seam is not None else None,
        "why": why,
        **_context(transcript, index, index),
    }


def caption_view(path: Path | str, clip_id: str | None = None) -> dict[str, Any]:
    """The captions this timeline would produce, with the style in force.

    `add_captions` without the writing — the read model behind the preview
    overlay and the window's CC lane, and the way to see a restyle before
    committing a file to it. Cues are in *timeline* seconds, already grouped
    by the stored style's own break rules, so a front end draws them and
    decides nothing.

    Read-only, and it reports rather than raises where `add_captions` refuses:
    a project with no transcript, or one whose every word has been cut, comes
    back with `cues: []` and the reason, because this is the view a person has
    open while making exactly that mistake. `resolution` is the reference
    canvas the style's sizes and margins are quoted against — 1080 tall
    whatever the footage is (`captions.REFERENCE_HEIGHT`), which is what a
    preview must scale by to show the size that will burn in.
    """
    project = Project.open(path)
    edit = _load_edit(project)
    style = captions.resolve(_stored_caption_style(project))
    width, height = _caption_canvas(project)

    result: dict[str, Any] = {
        "project": str(project.root),
        "clip_id": clip_id,
        "resolution": [width, height],
        "timeline_duration": edit.duration,
        "style": style.describe(),
        "font": captions.font_match(style.ass.font),
    }
    try:
        cues, placed, cut, meta = _caption_cues(project, edit, style, clip_id)
    except tx.TranscriptError as exc:
        return {**result, "cues": [], "words": 0, "words_cut": 0, "cues_error": str(exc)}

    result.update(meta)
    result["cues"] = [cue.as_dict() for cue in cues]
    result["words"] = len(placed)
    result["words_cut"] = cut
    if not cues:
        result["cues_error"] = "no transcribed word survives on the timeline"
    return result


def add_captions(
    path: Path | str,
    output: Path | str,
    *,
    clip_id: str | None = None,
    preset: str | None = None,
    max_words: int | None = None,
    max_gap: float | None = None,
    max_duration: float | None = None,
    hold: float | None = None,
    burn: Path | str | None = None,
    burn_output: Path | str | None = None,
) -> dict[str, Any]:
    """Write word-timed ASS captions for the current timeline.

    Timings are the timeline's, not the recording's: every word is mapped
    through the accumulated edit, and words that have been cut do not appear.
    The count that did is reported as `words_cut`, so a missing sentence can be
    told apart from a bug.

    The look comes from the project (`caption_style`), not from this call.
    `preset` and the four grouping numbers still override it for a one-off
    file, but they override *for this file only* — they are not written back,
    so the next regeneration is styled the way the project says again. That
    asymmetry is deliberate: one writer for the style, and it is not this.

    `caption_view` is this op's `plan`: same cues, same style, nothing written.

    `burn` renders the captions into a video with ffmpeg. It has to be a render
    of *this* timeline — burning onto the untrimmed source lines the captions up
    against audio that has since moved. The default exit is the sidecar `.ass`,
    which Kdenlive loads and can restyle.
    """
    project = Project.open(path)
    edit = _load_edit(project)

    stored = _stored_caption_style(project)
    overrides = {
        "preset": preset,
        "max_words": max_words,
        "max_gap": max_gap,
        "max_duration": max_duration,
        "hold": hold,
    }
    overrides = {field: value for field, value in overrides.items() if value is not None}
    style = captions.resolve({**stored, **overrides})

    cues, placed, cut, meta = _caption_cues(project, edit, style, clip_id)
    if not placed:
        raise captions.CaptionError(
            "no transcribed word survives on the timeline — nothing to caption"
        )

    destination = Path(output).expanduser()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        captions.to_ass(
            cues,
            style=style.ass,
            resolution=_caption_canvas(project),
            title=project.read_manifest().get("name", "lucid"),
        ),
        encoding="utf-8",
    )

    result: dict[str, Any] = {
        "output": str(destination),
        "preset": style.base,
        "style": style.describe(),
        "overrides": sorted(overrides),
        **meta,
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
    transcripts, unspoken = _spoken_transcripts(project, transcripts)

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
            # Reported beside the diff and never folded into it: this check's
            # expectation was *shortened* by hand, and a render checked against
            # a shortened expectation has to say so or the mark becomes a way
            # to make a real miss disappear.
            **unspoken,
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


# -- deriving a project ---------------------------------------------------
#
# A reel is a *derived project*: a film, cut down to the span someone watched,
# at whatever shape the feed wants. PLAN.md § Three uncosted parity items found
# that the choosing needs nothing built — `cut_by_time` already takes the
# seconds an export plays at — and that what is missing sits one level up. The
# canvas is project state and the cuts are destructive, so the copy is
# mandatory, and it was a `cp -a` done by hand.
#
# Almost nothing here is transformation. Descriptions index the source and a
# reframe is a rect in source pixels refit at render time, so neither a cut
# nor a canvas change can invalidate one — the roadmap's core property paying
# out rather than work this op does.
#
# Two things do need handling, and both were found by deriving a reel of the
# real film rather than by reasoning about one. Cards are rasterised rather
# than derived, so `card_reauthor` runs at the end. And a cue, though it is
# word-indexed and so cannot be *invalidated* by a cut, can be orphaned by
# one: a reel removes most of the film, which takes most of the cues' words
# with it, and `build_shots` refuses a whole projection on a single orphan.
# `_reel_orphan_cues`. Pruning them is then what strands the survivors, since
# the cursor deciding what each shot shows is per-asset and cumulative —
# `_reel_cue_pins`, the quieter half of the same problem.

#: How long a platform will let a vertical post run. Reported beside the
#: reel's own duration and never enforced: it is why a reel exists at all
#: (a 5:36 film reaches no feed), and it is exactly the kind of fact that
#: goes stale in a codebase, so it is a note to whoever is reading rather
#: than a refusal to be worked around.
PLATFORM_CAP = 180.0


def _reel_media(source: Project, reel: Project, manifest: dict[str, Any]) -> list[dict[str, Any]]:
    """Point a derived project's clips at the film's own media bytes.

    Never a copy: a reel of a five-minute film would duplicate every gigabyte
    that went into making one. Each `media/` and `cache/attenuated/` entry
    becomes a symlink to the file the *film* resolves, so `media_path()` on the
    reel and on the film return the same bytes.

    **Both keys, and `attenuated` is the one that matters.** `media_path()`
    prefers it over `media/` — that is what makes attenuation transparent to
    every downstream op — so carrying `media/` alone would give the reel a
    render at full noise with nothing in the manifest saying so, which is the
    shape of bug `test_export_renders_the_attenuated_copy_not_the_original`
    exists for pointing the other way.

    Falls back to writing the film's absolute path into the derived manifest
    where the filesystem will not take a symlink — the NAS case that already
    makes `media/` optional (wiki `files.md`). `media_path()` reads that
    correctly without a branch, since a `/`-joined absolute path is itself,
    and `mutates the manifest it was handed` is the point rather than a side
    effect. It does not fall back to *dropping* the key: that would resolve
    through `clip["source"]`, which is the original import path and so the
    un-attenuated file.
    """
    linked: list[dict[str, Any]] = []
    for clip in manifest.get("clips", []):
        for key in ("media", "attenuated"):
            entry = clip.get(key)
            if not entry:
                continue
            target = (source.root / entry).resolve()
            link = reel.root / entry
            link.parent.mkdir(parents=True, exist_ok=True)
            try:
                link.symlink_to(target)
                how = "symlink"
            except OSError:
                clip[key] = str(target)
                how = "absolute"
            linked.append(
                {
                    "clip_id": clip.get("clip_id"),
                    "key": key,
                    "how": how,
                    "target": str(target),
                    # Reported rather than refused, the way `media_path()`
                    # itself does not check: a film with one missing file
                    # should still derive, and a dangling link that says so
                    # beats one that does not.
                    "missing": not target.is_file(),
                }
            )
    return linked


def _reel_suspect_edges(
    project: Project, edit: tl.Edit, start: float, end: float
) -> list[dict[str, Any]]:
    """Suspect-duration words at the two edges a reel *keeps*.

    `cut_by_time` flags every suspect word a removed span overlaps. That is
    right for an ordinary cut, where the span and its boundary are nearly the
    same thing, and it is useless here: a reel removes most of the film, so
    one suspect word anywhere in it flags the operation whatever the reel
    keeps. Measured on the film this was written against — a 44s reel of a
    5:36 cut flagged fifteen, none of them within a hundred seconds of the
    reel. A guard that has to be suppressed every time guards nothing.

    The edges that can hide a retake are the two the reel keeps. An inflated
    duration there is a word that does not end where it claims, so the reel
    opens or closes on material from the wrong take (HISTORY.md § Suspect word
    durations). The other two edges are the film's own head and tail, and
    those hide nothing.
    """
    edges: list[tuple[str, float, str, float]] = []
    if start >= tl.MIN_SEGMENT:
        clip_id, _, src_end = edit.source_spans(0.0, start)[-1]
        edges.append((clip_id, src_end, "start", start))
    if edit.duration - end >= tl.MIN_SEGMENT:
        clip_id, src_start, _ = edit.source_spans(end, edit.duration)[0]
        edges.append((clip_id, src_start, "end", end))

    parsed_by_clip: dict[str, tx.Transcript | None] = {}
    found: list[dict[str, Any]] = []
    for clip_id, at, which, timeline_at in edges:
        if clip_id not in parsed_by_clip:
            try:
                parsed_by_clip[clip_id] = _transcript(project, clip_id)
            except tx.TranscriptError:
                parsed_by_clip[clip_id] = None
        parsed = parsed_by_clip[clip_id]
        if parsed is None:
            continue
        for item in _suspect_durations(parsed):
            word = parsed.words[item["index"]]
            # An *instant* test, so both ends count: an edge landing exactly on
            # a word's own boundary is the case this is looking for, and the
            # half-open rule the spans use would call it a miss (CLAUDE.md).
            if word.start <= at <= word.end:
                found.append(
                    {
                        **item,
                        "clip_id": clip_id,
                        "edge": which,
                        "timeline_at": timeline_at,
                        "source_at": at,
                    }
                )
    return found


def _reel_orphan_cues(
    project: Project, edit: tl.Edit, start: float, end: float
) -> list[dict[str, Any]]:
    """Cues whose word the derivation leaves off the timeline.

    A cue says "from this word onward, show this asset", so a cue whose word
    is gone points at nothing, and `build_shots` refuses the *whole*
    projection on one — rightly, since in a film that is someone having cut
    the line a picture was hung on. A reel cuts most of the film on purpose,
    so it orphans nearly every cue: on the real one, keeping 44s of 5:36 left
    30-odd of them and the derived project could not project shots at all.
    It passed every check and was unrenderable.

    So the derived cue table is the surviving cues, and this names the rest —
    quietly dropping them would be dropping a picture the reel was going to
    have. Resolved against the *film's* timeline, before any cut, which is the
    same question one asked afterwards: what survives the two cuts is exactly
    what mapped into `[start, end)` to begin with.
    """
    parsed_by_clip: dict[str, tx.Transcript | None] = {}
    orphans: list[dict[str, Any]] = []
    for cue in project.read_manifest().get("cues", []):
        clip_id = cue["clip_id"]
        if clip_id not in parsed_by_clip:
            try:
                parsed_by_clip[clip_id] = _transcript(project, clip_id)
            except tx.TranscriptError:
                parsed_by_clip[clip_id] = None
        parsed = parsed_by_clip[clip_id]
        if parsed is None:
            # Nothing to resolve the word index against. Left in place rather
            # than guessed at: `build_shots` owns that refusal and names it
            # better than a guess here would.
            continue
        word = parsed.words[cue["word_index"]]
        span = edit.timeline_span(clip_id, word.start, word.end)
        if span is None or not (span[0] < end and span[1] > start):
            orphans.append({**cue, "text": word.text})
    return orphans


def _reel_cue_pins(project: Project) -> tuple[dict[tuple[str, int], float], str | None]:
    """Where in its asset each of the *film's* shots actually reads.

    The counterpart to `_reel_orphan_cues`, and the same class of failure one
    level further in: pruning is what stops the derived project refusing, and
    pinning is what stops it rendering a different film.

    `plan_picture`'s per-asset cursor carries on from where the previous shot
    left it, so what a shot shows depends on every shot *before* it. A
    derivation drops the ones it cut, which empties that cursor — every
    survivor then replays its asset from the head, and the reel's picture is
    not the film's picture over the same seconds. It is the silent kind: the
    frames are real, the projection is valid, `status` and `verify` and
    `check_frames` all agree, and only a watch against the film says otherwise
    (CLAUDE.md; HISTORY.md § The teaser, re-cut).

    So the in-points are read off the film's own plan and written onto the
    survivors, which is exactly what `src_start` means — somebody asked for
    *that* moment — and what makes `plan_picture` refuse rather than rewind
    them. Stills are left alone: a card is a held frame with no playhead, and
    `plan_picture` refuses a pin on one.

    A refusal from the film's own projection comes back as a string rather
    than raising. A film that cannot project shots cannot be exported either,
    so the reel is not made newly wrong by deriving from one — but it is the
    reason its cues arrive unpinned, and that has to be said rather than
    inferred from an empty list.
    """
    rate = _export_fps(_clips_by_id(project))
    try:
        shots, _ = _picture_plan(project, rate)
    except _PICTURE_REFUSALS as exc:
        return {}, str(exc)
    return {
        (shot["clip_id"], shot["word_index"]): round(float(shot["src_start"]), 3)
        for shot in shots
        if not shot.get("is_image")
    }, None


def _reel_cue_table(
    cues: list[dict[str, Any]],
    orphans: list[dict[str, Any]],
    pins: dict[tuple[str, int], float],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """The derived cue table, and the in-points this derivation had to add.

    An existing `src_start` is never overwritten: the film's plan agrees with
    it by construction — a pinned shot has no cursor — so there is nothing to
    add, and a cue somebody pinned by hand is the last thing a derivation
    should be rewriting.
    """
    orphaned = {(cue["clip_id"], cue["word_index"]) for cue in orphans}
    kept: list[dict[str, Any]] = []
    pinned: list[dict[str, Any]] = []
    for cue in cues:
        key = (cue["clip_id"], cue["word_index"])
        if key in orphaned:
            continue
        if cue.get("src_start") is None and key in pins:
            cue = {**cue, "src_start": pins[key]}
            pinned.append(
                {
                    "clip_id": cue["clip_id"],
                    "word_index": cue["word_index"],
                    "asset": cue["asset"],
                    "src_start": cue["src_start"],
                }
            )
        kept.append(cue)
    return kept, pinned


def reel(
    path: Path | str,
    dest: Path | str,
    *,
    start: float,
    end: float,
    canvas: str | None = None,
    name: str | None = None,
    confirm_suspect: bool = False,
    plan: bool = False,
) -> dict[str, Any]:
    """Derive a new project holding `[start, end)` of this one's timeline.

    The times are the seconds *an export plays at* — what a human reports
    after a watch — and they are the span to **keep**, which is the only place
    in lucid that reads that way round. Everything else here cuts; a reel is
    named by what survives, so the head and the tail are what get removed,
    through `cut_by_time` and therefore through the same `Edit.remove` path
    every other cut takes. Nothing new decides anything about the timeline.

    `canvas` reshapes the derived project only, which is why deriving is what
    makes a reel safe: `canvas` is project state, so setting it on the film to
    take one vertical render would leave the film swapped after a render
    nobody kept — the same failure `tiktok-reels` refuses at one level down
    (HISTORY.md § `tiktok-reels`). The copy is the fix, not a convenience.

    The media is linked rather than copied (`_reel_media`), so a reel costs
    its manifest and its transcripts rather than its footage. What comes with
    it is what indexes the *source* — the transcripts, and the cards as they
    stand. What stays behind is everything that described the film's own
    renders or its undo stack: `cache/verify/`, `cache/frames/`,
    `cache/history/`, `renders/`. `cache/waveform/` stays behind too, being the
    one derived thing that rebuilds itself from media that has not changed.

    The derived cue table is the cues whose word the reel still has.
    `cues_dropped` names the rest, and each one is a picture the reel will not
    have; without the pruning the derived project cannot project shots at all,
    since `build_shots` refuses the whole projection on one orphan.

    **And every survivor is pinned to the in-point the film gave it**
    (`_reel_cue_pins`), because the pruning empties `plan_picture`'s per-asset
    cursor: unpinned, each survivor replays its asset from the head, which is
    a different film at exit 0 with every check agreeing. `cues_pinned` names
    them, and `pins_error` says why there are none where the film's own
    projection refuses.

    Cards are re-authored at the end because they are the only project state a
    canvas change cannot re-derive (PLAN.md § Aspect swap, finding 5). A card
    with no record cannot be re-authored by anything, so `cards_unrecorded`
    rides in the result: on the film this was written against, that list is
    twelve long, and a reel of it is correct in every other respect while its
    cards are still 16:9.

    The suspect-duration guard is applied at the two edges the reel keeps
    rather than over everything it removes (`_reel_suspect_edges`), and
    `confirm_suspect` answers *that* question. This is the one place a reel
    does not simply defer to `cut_by_time`, and the reason is measured rather
    than argued.

    `plan=True` resolves the whole thing — the spans, the clips that would be
    linked, what the cut would remove — and creates nothing.
    """
    source = Project.open(path)
    edit = _load_edit(source)
    duration = edit.duration
    start, end = float(start), float(end)

    if start < 0:
        raise tl.TimelineError(f"a reel starts inside the timeline, not at {start}")
    if end <= start:
        raise tl.TimelineError(f"a reel keeps [start, end) and {start} is not before {end}")
    if end > duration + tl.MIN_SEGMENT:
        raise tl.TimelineError(
            f"this timeline is {duration:.3f}s long, so it has nothing at {end}s to keep. "
            "The times are the seconds an export plays at — check them against "
            "`info`'s timeline_duration, or against the render you watched"
        )
    end = min(end, duration)

    # The head and the tail, resolved together against the timeline as it
    # stands: `cut_by_time` applies a list of spans against the pre-cut state,
    # which is exactly what makes two ends of one watch stay valid together.
    # A sliver shorter than a segment is dropped rather than asked for, since
    # `Edit.remove` would decline it and the arithmetic would then disagree.
    cuts: list[list[float]] = []
    if start >= tl.MIN_SEGMENT:
        cuts.append([0.0, start])
    if duration - end >= tl.MIN_SEGMENT:
        cuts.append([end, duration])

    # Both resolved against the film, before anything is created, so a refusal
    # leaves nothing behind.
    orphans = _reel_orphan_cues(source, edit, start, end)
    # Read off the film, because that is the only place the answer exists: the
    # cursor `plan_picture` walks is emptied by the pruning above, so a
    # survivor arriving unpinned replays its asset from the head
    # (`_reel_cue_pins`).
    pins, pins_error = _reel_cue_pins(source)
    kept_cues, pinned = _reel_cue_table(source.read_manifest().get("cues", []), orphans, pins)
    # Checked here rather than left to `cut_by_time`, at the granularity a reel
    # actually has a boundary at — see `_reel_suspect_edges`. Under `plan` it
    # is reported and never refused, which is `cut_by_time`'s own convention
    # for the same finding.
    suspect_edges = _reel_suspect_edges(source, edit, start, end)
    if suspect_edges and not (plan or confirm_suspect):
        hit = suspect_edges[0]
        raise tl.TimelineError(
            f"the reel's {hit['edge']} lands on word {hit['index']} ({hit['text']!r}) "
            f"in clip {hit['clip_id']!r}, which claims {hit['duration']}s — more than "
            f"{hit['limit']}s, so it likely hides a retake rather than ending where it "
            "claims (PLAN.md § Suspect word durations). A reel that opens or closes on "
            "the wrong take reads as an editing choice, so check it and retry with "
            "confirm_suspect=True (CLI: --confirm-suspect), or move the edge"
        )

    dest_root = Path(dest).expanduser().resolve()
    existed = dest_root.exists()
    # Before the emptiness check rather than after it: a film is never empty,
    # so this one would otherwise only ever be reached as "that directory has
    # something in it", which is true and unhelpful.
    if dest_root == source.root:
        raise ProjectError(
            "a reel is derived *from* a project, so it cannot be that project — "
            "name a different directory"
        )
    if existed and any(dest_root.iterdir()):
        raise ProjectError(
            f"{dest_root} already has something in it, and a reel is a new project — "
            "name a path that does not exist yet"
        )

    report: dict[str, Any] = {
        "project": str(source.root),
        "reel": str(dest_root),
        "keep": [start, end],
        "cut": cuts,
        "source_duration": duration,
        # What the reel should come out at. The cut's own `duration_after` is
        # the measured answer and replaces this below; under `plan` there is
        # no cut to measure, so the arithmetic is the honest one to report.
        "duration": round(end - start, 3),
        "canvas": canvas,
        # The one to read. `cut_plan`'s own `suspect_boundaries` is every
        # suspect word in everything being removed, which for a reel is most
        # of the film and almost never about the reel.
        "suspect_edges": suspect_edges,
        # Each one is a picture the reel will not have, so they are named
        # rather than counted.
        "cues_dropped": orphans,
        # And each of these is a picture the reel would have had from the
        # wrong second. Named for the same reason.
        "cues_pinned": pinned,
        "pins_error": pins_error,
        "plan": bool(plan),
    }
    report["over_platform_cap"] = report["duration"] > PLATFORM_CAP
    report["platform_cap"] = PLATFORM_CAP

    if plan:
        report["would_link"] = [
            {"clip_id": clip.get("clip_id"), "key": key}
            for clip in source.read_manifest().get("clips", [])
            for key in ("media", "attenuated")
            if clip.get(key)
        ]
        # The one call the real path makes, so what is planned is what would
        # run: `cut_by_time` resolves a whole list against the pre-cut
        # timeline, and planning them one at a time would resolve the tail
        # against a timeline the head had not been taken out of.
        report["cut_plan"] = cut_by_time(source.root, spans=cuts, plan=True) if cuts else None
        return report

    reel_project = Project.create(dest_root, name=name or dest_root.name)
    try:
        manifest = source.read_manifest()
        manifest["name"] = name or reel_project.root.name
        manifest["cues"] = kept_cues
        # Provenance, and the answer to the question a hand-made scratch copy
        # could not answer once already: which film is this, and which seconds
        # of it (HISTORY.md § The VO the project was holding). Additive and
        # optional, so no schema bump — the `canvas`/`caption_style` shape.
        manifest["derived_from"] = {
            "project": str(source.root),
            "keep": [start, end],
            "source_duration": duration,
        }
        report["linked"] = _reel_media(source, reel_project, manifest)
        reel_project.write_manifest(manifest)

        shutil.copy2(source.timeline_path, reel_project.timeline_path)
        # A transcript indexes the source, so it is as true of the reel as of
        # the film and costs ASR minutes to rebuild. The cards come as they
        # stand, to be re-authored below.
        for src_dir, dst_dir in (
            (source.transcript_dir, reel_project.transcript_dir),
            (source.cards_dir, reel_project.cards_dir),
        ):
            if src_dir.is_dir():
                shutil.copytree(src_dir, dst_dir, dirs_exist_ok=True)

        if cuts:
            # Always confirmed, because the decision was already made above at
            # the granularity a reel has boundaries at. Passing the caller's
            # flag through instead would re-ask the wrong question and refuse
            # on a suspect word two hundred seconds from either edge.
            cut = cut_by_time(reel_project.root, spans=cuts, confirm_suspect=True)
            report["removed"] = cut["removed"]
            report["duration"] = cut["duration_after"]
            report["segments"] = cut["segments"]
            report["over_platform_cap"] = report["duration"] > PLATFORM_CAP

        if canvas is not None:
            report["canvas_set"] = _set_canvas(reel_project.root, size=canvas)

        cards = card_reauthor(reel_project.root)
        report["cards_redrawn"] = cards["redrawn"]
        report["cards_unrecorded"] = cards["unrecorded"]
        report["cards"] = cards["cards"]
    except Exception:
        # Only what this call created, and only when there was nothing there
        # before it: `Project.create` will happily adopt an existing empty
        # directory, and removing one the caller had made is not this op's to
        # do. A half-derived project left behind is worse than no reel — it
        # opens, it reads as a film, and its timeline is the uncut one.
        if not existed:
            shutil.rmtree(reel_project.root, ignore_errors=True)
        raise

    return report
