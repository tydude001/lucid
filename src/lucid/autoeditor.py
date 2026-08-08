"""The auto-editor bridge: v3 timelines in, v3 timelines out.

auto-editor is a subprocess, not a library — it is Nim, and PyPI's `auto-editor`
is a stale 29.3.1 fork of the old Python one (CLAUDE.md). This module is the
only place that knows that.

The v3 timeline JSON is the whole reason lucid does not need its own renderer.
It is a flattened OTIO track under different field names, and auto-editor will
both *render* it and *export it to an NLE project*:

    auto-editor cut.v3 -o out.mp4                 # pixels
    auto-editor cut.v3 --export kdenlive -o p.kdenlive   # a real MLT timeline

Verified 2026-08-07 on this box, including for audio-only sources. That second
line is what gets a lucid edit into Kdenlive, which is the only NLE on this
machine — so one mapping layer buys both exits.

Header fields (`layout`, `samplerate`, `langs`, …) are **templated from
auto-editor itself** rather than reconstructed from ffprobe. `--edit none`
emits a valid header and one full-length segment without analysing audio, so
templating is cheap and cannot drift from whatever the installed version
expects.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from lucid.timeline import Edit, Segment

#: Milliseconds. Audio-only timelines are not bound to a frame grid, and 30fps
#: quantisation (33ms) is coarse enough to clip a consonant off a word. Verified
#: that auto-editor honours a 1000/1 timebase on v3 input.
AUDIO_TIMEBASE = 1000


class AutoEditorError(Exception):
    """Raised when auto-editor is missing, or fails on a timeline."""


def binary() -> str:
    """Locate the auto-editor binary, preferring an explicit override."""
    override = os.environ.get("LUCID_AUTO_EDITOR")
    if override:
        return override
    found = shutil.which("auto-editor")
    if found:
        return found
    local = Path.home() / ".local" / "bin" / "auto-editor"
    if local.exists():
        return str(local)
    raise AutoEditorError(
        "auto-editor not found. Install the auto-editor-linux-x86_64 binary "
        "from the GitHub release (not PyPI — that build is stale and diverged), "
        "or set LUCID_AUTO_EDITOR to its path."
    )


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    cmd = [binary(), *args]
    try:
        return subprocess.run(cmd, capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()
        raise AutoEditorError(f"auto-editor failed: {' '.join(cmd)}\n{detail}") from exc


def version() -> str:
    return _run(["--version"]).stdout.strip()


def _export_v3(media: Path, out_stem: Path, edit_expr: str, extra: list[str]) -> dict[str, Any]:
    """Run auto-editor with `--export v3` and read back the timeline it wrote.

    auto-editor forces the `.v3` extension regardless of what `-o` asks for,
    so the written path is derived rather than assumed.
    """
    _run([str(media), "--edit", edit_expr, *extra, "--export", "v3", "-o", str(out_stem)])
    written = out_stem.with_suffix(".v3")
    if not written.exists():
        raise AutoEditorError(f"auto-editor reported success but wrote no timeline at {written}")
    return json.loads(written.read_text(encoding="utf-8"))


def template(media: Path | str) -> dict[str, Any]:
    """A valid v3 header for `media`, with its tracks left in place.

    `--edit none` keeps everything, so this costs a probe rather than a full
    audio analysis.
    """
    media = Path(media)
    with tempfile.TemporaryDirectory(prefix="lucid-v3-") as tmp:
        return _export_v3(media, Path(tmp) / "template", "none", [])


def silence_edit(
    media: Path | str,
    clip_id: str,
    *,
    threshold: float = 0.04,
    margin: str | None = None,
    edit_expr: str | None = None,
) -> Edit:
    """Ask auto-editor which parts of `media` are worth keeping.

    This is the seed for a project's timeline: lucid does not reimplement
    silence detection, per the scope rule in PLAN.md. `edit_expr` passes
    auto-editor's own edit language straight through — it is richer than a
    threshold, e.g. `"(or audio:0.03 motion:0.06)"`.
    """
    media = Path(media)
    expr = edit_expr or f"audio:threshold={threshold}"
    extra = ["--margin", margin] if margin else []
    with tempfile.TemporaryDirectory(prefix="lucid-v3-") as tmp:
        payload = _export_v3(media, Path(tmp) / "silence", expr, extra)
    return from_v3(payload, clip_id)


def _timebase(payload: dict[str, Any]) -> float:
    raw = str(payload.get("timebase", "30/1"))
    num, _, den = raw.partition("/")
    try:
        return float(num) / (float(den) if den else 1.0)
    except ValueError as exc:
        raise AutoEditorError(f"unparseable v3 timebase {raw!r}") from exc


def from_v3(payload: dict[str, Any], clip_id: str) -> Edit:
    """Read a v3 timeline into an `Edit`, in source seconds.

    Only one track is read — the video track when there is one, else the audio
    track. lucid's model treats A/V as linked (see timeline.py), and for a
    cut-and-concat timeline the two tracks carry identical intervals.
    """
    rate = _timebase(payload)
    tracks = payload.get("v") or payload.get("a") or []
    if not tracks:
        raise AutoEditorError("v3 timeline has no tracks")

    segments: list[Segment] = []
    for entry in tracks[0]:
        offset, dur = int(entry["offset"]), int(entry["dur"])
        segments.append(
            Segment(clip_id=clip_id, start=offset / rate, end=(offset + dur) / rate)
        )
    return Edit(segments=segments)


def frame_layout(edit: Edit, rate: float) -> list[tuple[int, int]]:
    """Each segment as `(offset, dur)` in frames at `rate` — the export's own grid.

    Factored out of `to_v3` rather than restated beside it, so that the frame
    total a check reports and the frame total an export writes cannot become
    two different numbers.

    Each edge is quantised on its own, which is not the same as quantising the
    total: `sum(dur)` can differ by a frame or two from
    `round(edit.duration * rate)` once several segments round the same way.
    That difference is the real length of the exported timeline, not an
    artifact to average away — which is the whole reason a caller wanting a
    frame count has to come through here.
    """
    layout: list[tuple[int, int]] = []
    for seg in edit.segments:
        offset = round(seg.start * rate)
        layout.append((offset, max(1, round(seg.end * rate) - offset)))
    return layout


def frame_total(edit: Edit, rate: float) -> int:
    """How many frames the exported timeline runs to at `rate`."""
    return sum(dur for _, dur in frame_layout(edit, rate))


def to_v3(
    edit: Edit,
    clips: dict[str, dict[str, Any]],
    *,
    header: dict[str, Any],
    timebase: float | None = None,
) -> dict[str, Any]:
    """Render an `Edit` as a v3 timeline, reusing a templated header.

    Segments are laid end to end: each clip's `start` is the running total of
    the durations before it, so the timeline is gapless by construction.
    """
    payload = dict(header)
    rate = float(timebase) if timebase else _timebase(header)
    payload["timebase"] = f"{int(rate)}/1" if float(rate).is_integer() else str(rate)

    entries: list[dict[str, Any]] = []
    cursor = 0
    for seg, (offset, dur) in zip(edit.segments, frame_layout(edit, rate)):
        record = clips.get(seg.clip_id)
        if record is None:
            raise AutoEditorError(f"segment references unregistered clip {seg.clip_id!r}")
        entries.append(
            {
                "src": record["source"],
                "start": cursor,
                "dur": dur,
                "offset": offset,
                "stream": 0,
            }
        )
        cursor += dur

    any_video = any(clips[s.clip_id].get("has_video") for s in edit.segments)
    any_audio = any(clips[s.clip_id].get("has_audio") for s in edit.segments)
    payload["v"] = [list(entries)] if any_video else []
    payload["a"] = [[dict(e) for e in entries]] if any_audio else []
    return payload


def run_timeline(payload: dict[str, Any], output: Path | str, *, export: str | None = None) -> Path:
    """Write a v3 timeline and hand it to auto-editor to render or export.

    `export=None` renders media; `export="kdenlive"` writes an MLT project.
    Returns the path auto-editor actually wrote.
    """
    output = Path(output).expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="lucid-v3-") as tmp:
        timeline_path = Path(tmp) / "lucid.v3"
        timeline_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        args = [str(timeline_path)]
        if export:
            args += ["--export", export]
        args += ["-o", str(output)]
        _run(args)

    if output.exists():
        return output
    # kdenlive/v3 exports coerce the extension; find what was written instead.
    candidates = sorted(output.parent.glob(f"{output.stem}.*"))
    if candidates:
        return candidates[0]
    raise AutoEditorError(f"auto-editor wrote no file for {output}")
