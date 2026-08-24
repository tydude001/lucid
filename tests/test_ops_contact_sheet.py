"""`contact_sheet` — a handful of cached frames from a clip's own head.

goodsometimes' own incident (`ideas/lambs-longlegs.md`, "v3"): two shots used
`sl-0428-elevator.mp4` from its own head — 4.5s of opening-credits text over
black — because nobody had looked at the clip's own first seconds before
cueing it. This is that first look, built entirely on `thumbnail()`'s own
cache (`cache/thumbs/<clip_id>/`) — no new cache location, no new manifest
key, no new web route.

Fixture setup follows `tests/test_ops_reframe_sheet.py`: real ffmpeg-decoded
media on disk, registered by hand (no ffprobe needed to give a project a
clip with a shape).
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from lucid import ops
from lucid.project import Project

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is not installed")


def _video(path: Path, seconds: float) -> None:
    command = [
        "ffmpeg", "-v", "error", "-y",
        "-f", "lavfi", "-i", f"testsrc=size=160x120:rate=25:duration={seconds}",
        "-pix_fmt", "yuv420p", str(path),
    ]  # fmt: skip
    subprocess.run(command, check=True)


def _audio(path: Path, seconds: float) -> None:
    command = [
        "ffmpeg", "-v", "error", "-y",
        "-f", "lavfi", "-i", f"sine=frequency=300:duration={seconds}", str(path),
    ]  # fmt: skip
    subprocess.run(command, check=True)


@pytest.fixture
def project(tmp_path: Path) -> Project:
    """One 12s video clip, one 3s video clip (shorter than the default
    look-ahead), and one audio-only clip — the three shapes `contact_sheet`
    has to answer differently for."""
    project = Project.create(tmp_path / "proj")
    long_footage = tmp_path / "clipa.mp4"
    _video(long_footage, 12.0)
    short_footage = tmp_path / "shorty.mp4"
    _video(short_footage, 3.0)
    audio = tmp_path / "vo.wav"
    _audio(audio, 3.0)

    manifest = project.read_manifest()
    manifest["clips"] = [
        {
            "clip_id": "clipa",
            "source": str(long_footage),
            "duration": 12.0,
            "has_video": True,
            "has_audio": False,
            "width": 160,
            "height": 120,
            "fps": 25.0,
        },
        {
            "clip_id": "shorty",
            "source": str(short_footage),
            "duration": 3.0,
            "has_video": True,
            "has_audio": False,
            "width": 160,
            "height": 120,
            "fps": 25.0,
        },
        {
            "clip_id": "vo",
            "source": str(audio),
            "duration": 3.0,
            "has_video": False,
            "has_audio": True,
        },
    ]
    project.write_manifest(manifest)
    return project


@needs_ffmpeg
def test_the_default_window_covers_ten_seconds_at_1point5s_spacing(project: Project) -> None:
    result = ops.contact_sheet(project.root, "clipa")

    assert result["clip_id"] == "clipa"
    assert result["interval"] == ops.FIRST_LOOK_INTERVAL
    expected = [round(i * ops.FIRST_LOOK_INTERVAL, 6) for i in range(7)]  # 0, 1.5, ..., 9.0
    assert [f["src_time"] for f in result["frames"]] == pytest.approx(expected)
    for frame in result["frames"]:
        assert Path(frame["path"]).is_file()


@needs_ffmpeg
def test_frames_land_in_the_existing_thumbnail_cache_layout(project: Project) -> None:
    """No new cache location invented — every frame path sits under the same
    `cache/thumbs/<clip_id>/` `thumbnail()` already writes and
    `webui._send_thumb` already serves."""
    result = ops.contact_sheet(project.root, "clipa")

    thumbs_dir = str(project.root / "cache" / "thumbs" / "clipa")
    for frame in result["frames"]:
        assert frame["path"].startswith(thumbs_dir)


@needs_ffmpeg
def test_a_second_call_hits_the_cache(project: Project) -> None:
    first = ops.contact_sheet(project.root, "clipa")
    assert not any(f["cached"] for f in first["frames"])

    second = ops.contact_sheet(project.root, "clipa")
    assert all(f["cached"] for f in second["frames"])


@needs_ffmpeg
def test_a_clip_shorter_than_the_window_is_not_walked_past_its_own_end(project: Project) -> None:
    result = ops.contact_sheet(project.root, "shorty")

    # span = min(FIRST_LOOK_SECONDS, 3.0) = 3.0, at 1.5s spacing: 0, 1.5, 3.0
    assert len(result["frames"]) == 3
    for frame in result["frames"]:
        assert Path(frame["path"]).is_file()
        assert frame["src_time"] <= 3.0


@needs_ffmpeg
def test_seconds_and_interval_are_overridable(project: Project) -> None:
    result = ops.contact_sheet(project.root, "clipa", seconds=2.0, interval=1.0)

    assert result["interval"] == 1.0
    assert [f["src_time"] for f in result["frames"]] == pytest.approx([0.0, 1.0, 2.0])


@needs_ffmpeg
def test_an_audio_only_clip_returns_no_frames_rather_than_raising(project: Project) -> None:
    result = ops.contact_sheet(project.root, "vo")

    assert result == {
        "clip_id": "vo",
        "frames": [],
        "interval": ops.FIRST_LOOK_INTERVAL,
        "reason": "no video track",
    }
