"""`shot_sheet` — the picture track drawn as one labelled grid.

PLAN.md § The agent contact sheet; HISTORY.md § The shot sheet. The reachability
half of this feature (the MCP tool returning `ImageContent` rather than a path)
is tested over the real server in `tests/test_server_stdio.py`, because a tool
body proves nothing about what comes back over the wire. What is tested here is
the part that is pure ops: the cache's two invalidation rules, and the
`asset`-not-`clip_id` trap.

Fixture setup follows `tests/test_ops_contact_sheet.py`: real ffmpeg-decoded
media registered by hand, no ffprobe needed.
"""

from __future__ import annotations

import json
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


@pytest.fixture
def project(tmp_path: Path) -> Project:
    """A voiceover clip the cues are addressed against, and footage to show.

    Deliberately an audio-only `vo`: that is the film's own shape, and it is
    what makes the `asset`/`clip_id` distinction impossible to get right by
    accident — a tile drawn off `clip_id` would have no picture at all.
    """
    project = Project.create(tmp_path / "proj")
    footage = tmp_path / "footage.mp4"
    _video(footage, 12.0)
    audio = tmp_path / "vo.wav"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
         "sine=frequency=300:duration=8", str(audio)],
        check=True,
    )  # fmt: skip

    manifest = project.read_manifest()
    manifest["clips"] = [
        {
            "clip_id": "vo",
            "source": str(audio),
            "duration": 8.0,
            "has_video": False,
            "has_audio": True,
        },
        {
            "clip_id": "footage",
            "source": str(footage),
            "duration": 12.0,
            "has_video": True,
            "has_audio": False,
            "width": 320,
            "height": 240,
            "fps": 25.0,
        },
    ]
    project.write_manifest(manifest)

    words = [{"word": f"w{i}", "start": float(i), "end": i + 0.5} for i in range(8)]
    source = tmp_path / "vo.json"
    source.write_text(json.dumps({"language": "en", "words": words}), encoding="utf-8")
    ops.attach_transcript(project.root, "vo", source)
    ops.seed_timeline(project.root, "vo", remove_silences=False)
    ops.cue_add(project.root, "vo", 0, asset="footage")
    ops.cue_add(project.root, "vo", 4, asset="footage")
    return project


@needs_ffmpeg
@needs_magick
def test_a_tile_is_drawn_from_the_asset_not_the_addressing_clip(project: Project) -> None:
    """The standing trap in this projection, and the reason both ride a row.

    `clip_id` is the transcript the cue hangs on — here an audio-only VO — and
    `asset` is the footage. A sheet that reached for `clip_id` would resolve to
    a `.wav` and draw nothing, on every shot of a project shaped like the film.
    """
    result = ops.shot_sheet(project.root)

    assert result["shots_error"] is None
    assert result["count"] == 2
    for tile in result["tiles"]:
        assert tile["asset"] == "footage"
        assert tile["clip_id"] == "vo"
        assert tile["label"].startswith("footage ")
        assert Path(tile["frame"]).is_file()
    assert Path(result["sheet"]).is_file()


@needs_ffmpeg
@needs_magick
def test_frames_cache_under_the_asset_and_carry_the_tile_width(project: Project) -> None:
    """Cached by `(asset, source second)` at the tile's own width.

    The width rides the filename so that changing `SHOT_SHEET_TILE` misses the
    cache rather than silently upscaling the frames a previous width wrote —
    a stale smaller frame would still montage, just softer, which is the kind
    of wrong nothing reports.
    """
    ops.shot_sheet(project.root)

    # Under `SHEET_FRAMES_DIR`, not this sheet's own directory: a source frame
    # is `(asset, source second)` and knows nothing about which sheet asked
    # for it, so `footage_sheet` and `shot_sheet` share one copy.
    cached = sorted((project.root / ops.SHEET_FRAMES_DIR / "footage").glob("*.png"))
    assert cached, "no frame was cached under the asset"
    for frame in cached:
        assert frame.name.endswith(f"@{ops.SHOT_SHEET_TILE}.png")

    # Never under `cache/thumbs/`: that cache snaps to a THUMB_INTERVAL bucket
    # and a shot's in-point is exact, so a short shot would be drawn from a
    # second belonging to a different shot.
    assert not (project.root / ops.THUMBS_DIR).exists()


@needs_ffmpeg
@needs_magick
def test_replacing_the_footage_invalidates_every_cached_frame(project: Project) -> None:
    """A sheet is evidence, so a stale one is worse here than anywhere else.

    `thumbnail()`'s scheme rather than a second one: one `_source.json` per
    asset, so replacing a clip's media invalidates all of its frames at once
    and each is re-extracted only when something next asks for it.
    """
    first = ops.shot_sheet(project.root)
    frame = Path(first["tiles"][0]["frame"])
    before = frame.read_bytes()

    # Same clip_id, different footage — smptebars looks nothing like testsrc.
    source = Path(
        next(
            clip["source"]
            for clip in project.read_manifest()["clips"]
            if clip["clip_id"] == "footage"
        )
    )
    _video(source, 12.0, source="smptebars")

    second = ops.shot_sheet(project.root)
    after = Path(second["tiles"][0]["frame"]).read_bytes()

    assert after != before, "the cache served a frame of footage that is no longer there"


@needs_ffmpeg
@needs_magick
def test_a_page_past_the_end_draws_nothing_and_still_reports_the_range(
    project: Project,
) -> None:
    """"There is no page 9" is an answer; `pages` beside it says what was real."""
    past = ops.shot_sheet(project.root, per_page=1, page=9)

    assert past["count"] == 0
    assert past["sheet"] is None
    assert past["pages"] == 2
    assert past["shots"] == 2


def test_a_bad_page_size_refuses_before_anything_is_drawn(project: Project) -> None:
    from proofcut.project import ProjectError

    with pytest.raises(ProjectError):
        ops.shot_sheet(project.root, per_page=0)
    with pytest.raises(ProjectError):
        ops.shot_sheet(project.root, page=-1)


@needs_ffmpeg
@needs_magick
def test_a_card_on_the_picture_track_draws_as_a_tile(project: Project, tmp_path: Path) -> None:
    """A still is held, not played, and `probe` refuses one (no duration). The
    first recorded agent run (docs/plans/LAUNCH.md § Step 1) made a title
    card unprompted, cued it over the opening line, and then could not review
    its own picture: `shot_sheet` read the card's bit depth through `probe`
    and the refusal errored the whole sheet. A card row goes through
    `media.still_bit_depth` and draws; and a source ffprobe *does* refuse is
    one errored tile, never a lost sheet."""
    cards = project.cards_dir
    cards.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=orange:size=320x240",
         "-frames:v", "1", str(cards / "title.png")],
        check=True,
    )  # fmt: skip
    ops.cue_add(project.root, "vo", 2, asset="card:title")

    sheet = ops.shot_sheet(project.root)
    by_asset = {tile["asset"]: tile for tile in sheet["tiles"]}
    card = by_asset["card:title"]
    assert "error" not in card, card
    assert card["is_image"] is True
    assert Path(sheet["sheet"]).is_file()
    assert all("error" not in tile for tile in sheet["tiles"]), sheet["tiles"]
