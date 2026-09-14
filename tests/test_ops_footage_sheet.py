"""`footage_sheet` — a clip's own footage drawn as one labelled grid.

PLAN.md § The footage sheet; HISTORY.md § The footage sheet. The reachability
half (the MCP tool returning `ImageContent` rather than a path) is tested over
the real server in `tests/test_server_stdio.py`; what is tested here is the
part that is pure ops — which instants each address picks, and the two luma
rules, which are the only new claims this op makes about pixels.

The fixture is deliberately a project with **no timeline, no cues and no
transcript**. That is not a shortcut: it is the audience. Someone with a
recording and nothing to search has no edit yet, and an op that needed one
would be unreachable exactly where it is supposed to help.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from proofcut import ops
from proofcut.project import Project

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is not installed")
needs_magick = pytest.mark.skipif(
    shutil.which("magick") is None, reason="ImageMagick is not installed"
)


def _video(path: Path, seconds: float, *, source: str = "testsrc") -> None:
    command = [
        "ffmpeg", "-v", "error", "-y",
        "-f", "lavfi", "-i", f"{source}=size=320x240:rate=25:duration={seconds}",
        "-pix_fmt", "yuv420p", str(path),
    ]  # fmt: skip
    subprocess.run(command, check=True)


def _register(project: Project, clip_id: str, source: Path, duration: float, **extra: object) -> None:
    manifest = project.read_manifest()
    manifest.setdefault("clips", []).append(
        {
            "clip_id": clip_id,
            "source": str(source),
            "duration": duration,
            "has_video": True,
            "has_audio": False,
            "width": 320,
            "height": 240,
            "fps": 25.0,
            **extra,
        }
    )
    project.write_manifest(manifest)


@pytest.fixture
def project(tmp_path: Path) -> Project:
    project = Project.create(tmp_path / "proj")
    footage = tmp_path / "footage.mp4"
    _video(footage, 12.0)
    _register(project, "footage", footage, 12.0)
    return project


@needs_ffmpeg
@needs_magick
def test_the_interval_address_needs_no_edit_and_leaves_no_remainder(project: Project) -> None:
    """Equal windows, count rounded up — `describe.plan_windows`, shared.

    12s asked for 5s tiles is three windows of 4s, never two of 5s and a 2s
    runt. The runt is not cosmetic: deriving this split by hand put the last
    mark at the clip's exact duration, which is past the final frame, and
    ffmpeg refused it — seven marks and six tiles on a real 60.1s recording,
    at exit 0.
    """
    result = ops.footage_sheet(project.root, "footage", interval=5.0)

    assert result["mode"] == "interval" and result["asked"] == "auto"
    assert result["marks"] == 3 and result["drawn"] == 3
    assert result["interval"] == 4.0
    # The request is reported beside what was drawn, or the reply describes a
    # sheet nobody made.
    assert result["interval_asked"] == 5.0

    # Every mark sits in the middle of the stretch it stands for, and every
    # one is inside the file.
    assert [t["src"] for t in result["tiles"]] == [2.0, 6.0, 10.0]
    assert all(t["src"] < 12.0 for t in result["tiles"])
    assert Path(result["sheet"]).is_file()


@needs_ffmpeg
@needs_magick
def test_auto_prefers_described_windows_and_carries_their_text(project: Project) -> None:
    """A tile and a description sharing one address is the point of the op.

    `auto` upgrades to `describe` the moment a clip has descriptions, rather
    than waiting for someone to remember a flag — the whole argument for this
    sheet is that the thing choosing footage should be able to see the
    candidate it is reading about.
    """
    manifest = project.read_manifest()
    manifest["descriptions"] = [
        {"clip_id": "footage", "src_start": 0.0, "src_end": 6.0, "text": "a colour chart"},
        {"clip_id": "footage", "src_start": 6.0, "src_end": 12.0, "text": "the same chart again"},
    ]
    project.write_manifest(manifest)

    result = ops.footage_sheet(project.root, "footage")

    assert result["mode"] == "describe" and result["asked"] == "auto"
    assert result["described_windows"] == 2
    # `interval` is None under describe: reporting the default there would
    # claim a spacing that had no part in choosing these instants.
    assert result["interval"] is None
    assert [t["text"] for t in result["tiles"]] == ["a colour chart", "the same chart again"]
    assert [t["src"] for t in result["tiles"]] == [3.0, 9.0]
    assert [(t["src_start"], t["src_end"]) for t in result["tiles"]] == [(0.0, 6.0), (6.0, 12.0)]

    # The sentence stays out of the picture: the label band holds one line, and
    # a description truncated to fit is worse than one the caller reads whole.
    assert all("colour chart" not in t["label"] for t in result["tiles"])


@needs_ffmpeg
@needs_magick
def test_auto_never_scans_for_cuts_and_scenes_must_be_asked_for(project: Project) -> None:
    """The measured reason `scenes` is opt-in, in the two directions it fails.

    A scene scan decodes the whole clip, so it can never be a default
    (`reframe_coverage`'s rule). And its yield is uncorrelated with anything
    the caller knows: measured on real unedited footage it returns *nothing*
    on a continuous take — a correct answer per `media.scene_cuts`, and a
    sheet of one tile — while firing 17 times in 60s of gameplay on deaths
    and respawns, which are not shots.

    `testsrc` is that continuous take: one unbroken generated pattern, no
    cuts. Interval draws it; scenes falls back to the head alone.
    """
    auto = ops.footage_sheet(project.root, "footage", interval=5.0)
    scenes = ops.footage_sheet(project.root, "footage", mode="scenes")

    assert auto["mode"] == "interval"
    assert "scan_seconds" not in auto, "auto paid for a scan it must never run"

    assert scenes["mode"] == "scenes"
    assert "scan_seconds" in scenes
    # The head is not a cut, and without it a cut-addressed sheet of a
    # continuous take would have no tiles at all rather than one.
    assert scenes["marks"] == 1
    assert scenes["tiles"][0]["src"] == 0.0
    assert auto["marks"] > scenes["marks"]


@needs_ffmpeg
@needs_magick
def test_a_tile_with_nothing_in_it_says_so_on_the_picture(tmp_path: Path) -> None:
    """`[blank]` rides the tile, because the reply's two halves are read apart.

    A black square in a montage is indistinguishable from a frame that failed
    to extract, and the thing looking at the sheet sees the square rather than
    the JSON. The threshold is on YMAX and not on average brightness: sampling
    70 frames of real material found no gap at all between dark and normal
    footage, and a clean 8x one between a black frame (16) and the darkest
    real frame in the corpus (127).
    """
    project = Project.create(tmp_path / "proj")
    bars = tmp_path / "bars.mp4"
    dark = tmp_path / "dark.mp4"
    clip = tmp_path / "clip.mp4"
    _video(bars, 10.0, source="smptebars")
    # Not through `_video`: its `source=` is a filter *name* it appends
    # `=size=...` to, and `color` needs its own `c=` argument first.
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
         "color=c=black:size=320x240:rate=25:duration=10", "-pix_fmt", "yuv420p", str(dark)],
        check=True,
    )  # fmt: skip
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-i", str(bars), "-i", str(dark),
         "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0", "-pix_fmt", "yuv420p", str(clip)],
        check=True,
    )  # fmt: skip
    _register(project, "clip", clip, 20.0)

    result = ops.footage_sheet(project.root, "clip", interval=5.0)

    assert result["count"] == 4
    assert result["blank"] == 2
    lit, blank = result["tiles"][:2], result["tiles"][2:]
    assert all(t["luma"]["blank"] is False for t in lit)
    assert all(t["luma"]["blank"] is True for t in blank)
    assert all(ops._BLANK_MARK not in t["label"] for t in lit)
    assert all(ops._BLANK_MARK in t["label"] for t in blank)


@needs_ffmpeg
@needs_magick
def test_luma_is_normalised_so_two_clips_can_be_compared(tmp_path: Path) -> None:
    """A 10-bit clip is not seven times brighter than an 8-bit one.

    `signalstats` reports on the source's own scale, so raw YAVG is not
    comparable across clips — the film's `s4-overexposed` measures 429 against
    its neighbours' 26-132 purely because it is 10-bit. Without the divide, a
    fixed floor would call every 10-bit clip bright and every 8-bit one dark.
    """
    project = Project.create(tmp_path / "proj")
    eight = tmp_path / "eight.mp4"
    ten = tmp_path / "ten.mp4"
    _video(eight, 6.0, source="smptebars")
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
         "smptebars=size=320x240:rate=25:duration=6",
         "-c:v", "libx264", "-pix_fmt", "yuv420p10le", str(ten)],
        check=True,
    )  # fmt: skip
    _register(project, "eight", eight, 6.0)
    _register(project, "ten", ten, 6.0)

    low = ops.footage_sheet(project.root, "eight", interval=6.0)["tiles"][0]["luma"]
    high = ops.footage_sheet(project.root, "ten", interval=6.0)["tiles"][0]["luma"]

    assert low["scale"] == 255.0
    assert high["scale"] == 1023.0
    # The raw averages differ by roughly the scale ratio; the normalised ones
    # agree, because it is the same colour chart.
    assert high["avg"] > low["avg"] * 2
    assert abs(high["fraction"] - low["fraction"]) < 0.05
    assert high["blank"] is False


@needs_ffmpeg
@needs_magick
def test_paging_is_absolute_and_a_page_past_the_end_is_empty(project: Project) -> None:
    """`pages` is what stops a first page reading as the whole recording."""
    first = ops.footage_sheet(project.root, "footage", interval=2.0, per_page=2, page=0)
    second = ops.footage_sheet(project.root, "footage", interval=2.0, per_page=2, page=1)
    past = ops.footage_sheet(project.root, "footage", interval=2.0, per_page=2, page=99)

    assert first["marks"] == 6 and first["pages"] == 3
    assert [t["index"] for t in first["tiles"]] == [0, 1]
    assert [t["index"] for t in second["tiles"]] == [2, 3]
    assert past["count"] == 0 and past["sheet"] is None
    assert past["pages"] == 3


def test_the_refusals_land_before_anything_is_drawn(project: Project, tmp_path: Path) -> None:
    """Each refusal names the thing to do instead, and none of them decode."""
    with pytest.raises(ops.ProjectError, match="at least one tile"):
        ops.footage_sheet(project.root, "footage", per_page=0)
    with pytest.raises(ops.ProjectError, match="counted from 0"):
        ops.footage_sheet(project.root, "footage", page=-1)
    with pytest.raises(ops.ProjectError, match="mode is one of"):
        ops.footage_sheet(project.root, "footage", mode="cuts")
    with pytest.raises(ops.ProjectError, match="positive number of seconds"):
        ops.footage_sheet(project.root, "footage", interval=0)

    # Asking for descriptions a clip has not got points at `describe`, and at
    # the address that needs nothing — a refusal that leaves the caller with
    # no next move is the one shape this must not have.
    with pytest.raises(ops.ProjectError, match="no descriptions to sheet"):
        ops.footage_sheet(project.root, "footage", mode="describe")

    audio = tmp_path / "vo.wav"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
         "sine=frequency=300:duration=4", str(audio)],
        check=True,
    )  # fmt: skip
    manifest = project.read_manifest()
    manifest["clips"].append(
        {"clip_id": "vo", "source": str(audio), "duration": 4.0,
         "has_video": False, "has_audio": True}
    )  # fmt: skip
    project.write_manifest(manifest)
    with pytest.raises(ops.ProjectError, match="no video track"):
        ops.footage_sheet(project.root, "vo")

    assert not (project.root / ops.SHEET_FRAMES_DIR).exists()
    assert not (project.root / ops.FOOTAGE_SHEET_DIR).exists()
