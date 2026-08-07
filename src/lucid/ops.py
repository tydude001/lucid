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
from pathlib import Path
from typing import Any

from lucid import asr, autoeditor, captions, media
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


def cut_by_transcript(
    path: Path | str,
    clip_id: str,
    *,
    cut: Sequence[Sequence[int]] | None = None,
    keep: Sequence[Sequence[int]] | None = None,
    pad: float = 0.0,
) -> dict[str, Any]:
    """Cut or keep word ranges — the operation lucid exists for.

    Ranges are inclusive word indices into the clip's transcript, resolved to
    source time and applied to the accumulated timeline. `pad` widens each cut
    on both sides, which is how you reach the silence *between* words instead
    of clipping the consonant at the edge.

    Exactly one of `cut` or `keep` is accepted: a call that meant "keep" but
    was read as "cut" would produce the precise inverse of the intended edit,
    so there is no default.
    """
    if bool(cut) == bool(keep):
        raise tx.TranscriptError("pass exactly one of cut= or keep=")

    project = Project.open(path)
    media.get_clip(project, clip_id)
    parsed = _transcript(project, clip_id)
    edit = _load_edit(project)
    before = edit.duration

    applied: list[dict[str, Any]] = []
    if cut:
        for (first, last), (start, end) in zip(cut, _resolve(parsed, cut)):
            lo, hi = max(0.0, start - pad), end + pad
            present = edit.covers(clip_id, lo, hi)
            touched = edit.remove(clip_id, lo, hi)
            applied.append(
                {
                    "first_word": int(first),
                    "last_word": int(last),
                    "source_start": lo,
                    "source_end": hi,
                    "text": " ".join(w.text for w in parsed.window(int(first), int(last))),
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
                    "first_word": int(first),
                    "last_word": int(last),
                    "source_start": start,
                    "source_end": end,
                    "text": " ".join(w.text for w in parsed.window(int(first), int(last))),
                }
            )

    _save_edit(project, edit)
    return {
        "clip_id": clip_id,
        "mode": "cut" if cut else "keep",
        "applied": applied,
        "duration_before": before,
        "duration_after": edit.duration,
        "removed": before - edit.duration,
        "segments": len(edit.segments),
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
    model: str = asr.DEFAULT_MODEL,
    language: str | None = None,
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

    if transcript_path is not None:
        heard_transcript = tx.load(transcript_path, clip_id="render")
    else:
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

    return result
