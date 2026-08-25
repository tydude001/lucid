"""`contact_sheet` — a handful of cached frames from a clip's own head.

goodsometimes' own incident (`ideas/lambs-longlegs.md`, "v3"): two shots used
`sl-0428-elevator.mp4` from its own head — 4.5s of opening-credits text over
black — because nobody had looked at the clip's own first seconds before
cueing it. This is that first look: the frames are built entirely on
`thumbnail()`'s own cache (`cache/thumbs/<clip_id>/`) — no new cache
location, no new manifest key, no new web route — and one montage of them
lands beside every other sheet, because the caller that most needs to look
(the agent panel, `--tools ''`) cannot open a path.

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
        # Named rather than absent: `sheet: None` is "asked for and there was
        # nothing to draw", which is what a caller reading this branch needs
        # to tell apart from `montage=False`, where the key is not there.
        "sheet": None,
        "interval": ops.FIRST_LOOK_INTERVAL,
        "reason": "no video track",
    }


needs_magick = pytest.mark.skipif(
    shutil.which("magick") is None, reason="the montage is drawn by ImageMagick"
)


@needs_ffmpeg
@needs_magick
def test_the_frames_are_montaged_into_one_labelled_sheet(project: Project) -> None:
    """The frames are the first look; the montage is how a caller that cannot
    open a path gets to see them. It is drawn from the thumbnails already
    made, so nothing is decoded twice, and it lands under `cache/sheets/`
    beside every other sheet rather than in the filmstrip's own cache."""
    result = ops.contact_sheet(project.root, "clipa")

    sheet = Path(result["sheet"])
    assert sheet.is_file() and sheet.suffix == ".jpg"
    assert sheet.parent == project.root / ops.FIRST_LOOK_DIR / "clipa"
    assert "sheet_error" not in result
    # One tile per frame — a sheet short of a frame is a first look that
    # quietly skipped a second of the head it exists to show.
    assert len(list(sheet.parent.glob("*.png"))) == len(result["frames"])


@needs_ffmpeg
def test_no_montage_leaves_the_key_out_rather_than_setting_it_null(project: Project) -> None:
    """`finish_report`'s `framing` rule: unasked is not a measured nothing.
    `import_media` asks for no montage, so its record must not be readable as
    "a sheet was drawn and there was nothing in it"."""
    result = ops.contact_sheet(project.root, "clipa", montage=False)

    assert "sheet" not in result
    assert result["frames"]


@needs_ffmpeg
def test_import_asks_for_the_frames_and_not_the_montage(project: Project, tmp_path: Path) -> None:
    """An import reply cannot carry an image, and the pane that reads one
    draws the thumbs themselves — so the montage would be a picture nobody is
    in a position to see."""
    footage = tmp_path / "another.mp4"
    _video(footage, 3.0)

    record = ops.import_media(project.root, str(footage), clip_id="another")

    assert "sheet" not in record["contact_sheet"]
    assert record["contact_sheet"]["frames"]


@needs_ffmpeg
@needs_magick
def test_a_tile_is_labelled_at_the_width_it_is_montaged_at(project: Project) -> None:
    """The defect a reading found and no assertion had: the band is drawn at
    `SHOT_SHEET_POINTSIZE` against whatever scale the picture is at, so
    labelling a full-resolution thumbnail and letting `montage` shrink it
    afterwards puts the label in at a fifth of its size. Every tile came back
    with a legible picture and an illegible smear under it."""
    ops.contact_sheet(project.root, "clipa")

    tiles = sorted((project.root / ops.FIRST_LOOK_DIR / "clipa").glob("*.png"))
    assert tiles
    widths = {
        subprocess.run(
            ["magick", "identify", "-format", "%w", str(tile)],
            capture_output=True, text=True, check=True,
        ).stdout
        for tile in tiles
    }  # fmt: skip
    assert widths == {str(ops.SHEET_PAGE_WIDTH // ops.SHOT_SHEET_COLUMNS)}
