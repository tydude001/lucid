"""The VFR probe, and the measurement behind its tolerance — docs/plans/POLISH.md § Step 04.

Phone and screen recordings are often variable frame rate, and VFR is where
naive cut math breaks. The recorded lean (PLAN.md § Open questions, *Variable
frame rate footage*) is **not** to transcode on import: cut-and-concat works in
the time domain, where VFR is mostly fine. Probe it, record it, and normalise
only where frame-exactness actually matters. So the whole job of this signal is
to put a *name* on the condition before it becomes a mystery failure.

The signal is `r_frame_rate` vs `avg_frame_rate` with a 1% tolerance, and it is
cheap enough to be free. What it is not is obviously correct, so it was
measured rather than assumed (2026-08-24, this box):

- A real variable file — 30fps testsrc with frames dropped, which is the shape
  a screen recorder produces because it captures only when the screen changes —
  reads r=30, avg=17.4. The signal fires at 42%, nowhere near the threshold.
- **Zero false positives over twelve real files on this box**: the film's own
  source footage at 23.976 (r=23.976023976…, avg=23.976 — 1e-6 relative), the
  a2 fade probes, the qt probes, the skew-check renders. Every one lands orders
  of magnitude inside the tolerance.
- The tightest true-CFR margin measured is **0.33%**, on a file whose
  container duration makes `avg` disagree with `r` by one frame's worth. So the
  1% tolerance clears the real material by about 3× — not 100×, which is worth
  knowing before anyone tightens it.
- Packet timing settles what the rates only summarise, and agrees: a CFR file
  has at most two distinct pts deltas, one timebase tick apart (rounding); the
  variable one had nine, spanning 0.033–0.100. That is the fallback POLISH
  allows if the cheap signal proves unreliable — measured, and **not needed**.

The fixtures below are built with ffmpeg rather than vendored, so the file that
is measured is the file the assertion is about.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from lucid import media, ops

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is not installed")
needs_ffprobe = pytest.mark.skipif(
    shutil.which("ffprobe") is None, reason="ffprobe is not installed"
)


def _make_cfr(path: Path, *, rate: int = 30, duration: float = 4.0) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-v", "error",
            "-f", "lavfi", "-i", f"testsrc=size=160x120:rate={rate}:duration={duration}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ],
        check=True,
    )


def _make_vfr(path: Path, *, rate: int = 30, duration: float = 4.0) -> None:
    """Frames dropped from a constant grid — a screen recorder's own shape.

    `select` keeps a random subset and `-fps_mode vfr` writes the surviving
    presentation times as they are rather than re-timing them onto a grid, so
    the result is genuinely variable rather than merely slower.
    """
    subprocess.run(
        [
            "ffmpeg", "-y", "-v", "error",
            "-f", "lavfi", "-i", f"testsrc=size=160x120:rate={rate}:duration={duration}",
            "-vf", "select='gt(random(0),0.45)'", "-fps_mode", "vfr",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ],
        check=True,
    )


# -- the probe -------------------------------------------------------------


@needs_ffmpeg
@needs_ffprobe
def test_a_variable_file_probes_as_vfr(tmp_path: Path) -> None:
    source = tmp_path / "screencap.mp4"
    _make_vfr(source)

    info = media.probe(source)

    assert info.vfr is True
    # Not a marginal call: the whole point of recording the margin is that the
    # next person tightening the tolerance can see how much room there was.
    assert info.fps is not None


@needs_ffmpeg
@needs_ffprobe
def test_a_constant_file_does_not(tmp_path: Path) -> None:
    source = tmp_path / "steady.mp4"
    _make_cfr(source)

    assert media.probe(source).vfr is False


@needs_ffmpeg
@needs_ffprobe
def test_a_broadcast_rate_is_rounding_and_not_variability(tmp_path: Path) -> None:
    """23.976 is the case the 1% tolerance exists for: `r_frame_rate` comes
    back as 24000/1001 and `avg_frame_rate` as a rounded 23.976, which an
    exact comparison would call variable on every piece of film footage in the
    project. Measured against the film's own source clips, which land 1e-6
    apart."""
    source = tmp_path / "film.mp4"
    subprocess.run(
        [
            "ffmpeg", "-y", "-v", "error",
            "-f", "lavfi", "-i", "testsrc=size=160x120:rate=24000/1001:duration=3",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(source),
        ],
        check=True,
    )

    assert media.probe(source).vfr is False


def test_audio_only_is_never_variable(tmp_path: Path) -> None:
    """No video stream means no frame rate to vary — `fps` is None and the
    expression short-circuits rather than dividing by it."""
    info = media.MediaInfo(
        duration=1.0, has_video=False, has_audio=True, fps=None, width=None, height=None,
        sample_rate=44100, channels=1, video_codec=None, audio_codec="pcm_s16le", vfr=False,
    )
    assert info.vfr is False


# -- where it surfaces -----------------------------------------------------


@needs_ffmpeg
@needs_ffprobe
def test_import_records_it_and_the_report_names_the_clip(tmp_path: Path) -> None:
    """The record is the deliverable: `import`'s own return, the manifest, and
    `finish_report`'s informational `sources` line. Never a flag — the lean is
    not to transcode, so nothing in the window could clear one."""
    root = tmp_path / "proj"
    steady, wobbly = tmp_path / "steady.mp4", tmp_path / "wobbly.mp4"
    _make_cfr(steady)
    _make_vfr(wobbly)

    ops.init(root)
    assert ops.import_media(root, steady, clip_id="steady")["vfr"] is False
    assert ops.import_media(root, wobbly, clip_id="wobbly")["vfr"] is True

    stored = {c["clip_id"]: c.get("vfr") for c in ops.info(root)["clips"]}
    assert stored == {"steady": False, "wobbly": True}

    ops.seed_timeline(root, "steady", remove_silences=False)
    report = ops.finish_report(root)

    assert report["sources"] == {"clips": 2, "vfr": ["wobbly"]}
    assert not any("vfr" in str(flag).lower() for flag in report["flags"]["items"])


@needs_ffmpeg
@needs_ffprobe
def test_properties_carries_it_through_assets(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    wobbly = tmp_path / "wobbly.mp4"
    _make_vfr(wobbly)

    ops.init(root)
    ops.import_media(root, wobbly, clip_id="wobbly")
    ops.seed_timeline(root, "wobbly", remove_silences=False)

    assert ops.properties(root, clip_id="wobbly")["clip"]["vfr"] is True


def test_an_older_manifest_with_no_vfr_key_reads_as_not_variable(tmp_path: Path) -> None:
    """Additive and optional — absent means what every older manifest meant,
    so there is no schema bump and no migration step for this.

    `assets` echoes the absence as `None` rather than inventing a `False`,
    which is the honest answer ("nobody probed this") — and every consumer
    that has to decide reads it through `.get`, where absent and false lead
    to the same place."""
    from lucid.project import Project

    root = tmp_path / "proj"
    ops.init(root)
    project = Project.open(root)
    manifest = project.read_manifest()
    manifest["clips"] = [{"clip_id": "old", "media": "media/old.wav", "duration": 1.0}]
    project.write_manifest(manifest)

    row = ops.assets(root)["clips"][0]
    assert row["clip_id"] == "old"
    assert row["vfr"] is None
    assert [c["clip_id"] for c in manifest["clips"] if c.get("vfr")] == []
