"""`reframe_sheet` — the window drawn on the source frame, for review.

PLAN.md § Per-shot framing, step 3, and it is a build item *beside* the
framing rather than after it: the hand-framed teaser had 2 of its 15 windows
wrong and **neither was visible in motion**. A badly-placed window reads as
framing, because nothing in the frame says otherwise — what catches one is
the whole source frame with the window drawn on it, where the material being
left out sits beside the material being kept.

Shells ffmpeg and magick for real, because the thing under test is what comes
out of them: a tile per sample and one montage. The video is generated here
rather than fixtured, so the frames the sheet draws on are real decoded ones.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from lucid import ops
from lucid import timeline as tl
from lucid import transcript as tx
from lucid.project import Project, ProjectError

needs_tools = pytest.mark.skipif(
    shutil.which("magick") is None or shutil.which("ffmpeg") is None,
    reason="the sheet is ffmpeg's frames drawn on by magick",
)

VO = {
    "clip_id": "vo",
    "source": "/tmp/vo.wav",
    "duration": 4.0,
    "has_video": False,
    "has_audio": True,
}


def _video(path: Path, seconds: int = 8) -> None:
    command = [
        "ffmpeg", "-v", "error", "-y",
        "-f", "lavfi", "-i", f"testsrc=size=1920x816:rate=30:duration={seconds}",
        "-pix_fmt", "yuv420p", str(path),
    ]  # fmt: skip
    subprocess.run(command, check=True)


@pytest.fixture
def project(tmp_path: Path) -> Project:
    """A VO with two cues onto one real 1920x816 clip, on a vertical canvas —
    so the film has two placements of one asset and something to crop."""
    project = Project.create(tmp_path / "proj")
    footage = tmp_path / "clipa.mp4"
    _video(footage)

    manifest = project.read_manifest()
    manifest["clips"] = [
        VO,
        {
            "clip_id": "clipa",
            "source": str(footage),
            "duration": 8.0,
            "has_video": True,
            "has_audio": False,
            "width": 1920,
            "height": 816,
        },
    ]
    project.write_manifest(manifest)

    edit = tl.Edit([tl.Segment("vo", 0.0, 4.0)])
    tl.write(
        tl.to_otio(edit, {c["clip_id"]: c for c in manifest["clips"]}, rate=1000.0),
        project.timeline_path,
    )
    tx.save(
        tx.Transcript(
            clip_id="vo",
            words=(
                tx.Word(index=0, text="cold", start=0.0, end=0.4),
                tx.Word(index=1, text="open", start=2.0, end=2.4),
            ),
        ),
        project.transcript_path("vo"),
    )
    ops.canvas(project.root, size="1080x1920")
    return project


@needs_tools
def test_the_sheet_draws_a_row_per_placement_and_three_moments_each(
    project: Project,
) -> None:
    ops.cue_add(project.root, "vo", 0, "clipa")
    ops.cue_add(project.root, "vo", 1, "clipa")

    result = ops.reframe_sheet(project.root)

    assert result["count"] == 2, "a row per window shown — one each here, and not per clip"
    assert [row["asset"] for row in result["rows"]] == ["clipa", "clipa"]
    assert all(len(row["samples"]) == 3 for row in result["rows"])
    assert Path(result["sheet"]).exists()
    for row in result["rows"]:
        for sample in row["samples"]:
            assert Path(sample["png"]).exists()


@needs_tools
def test_each_row_is_labelled_with_the_window_in_force_at_that_moment(
    project: Project,
) -> None:
    """The two placements read different stretches of the one file, so a
    window that starts between them frames only the second — which is the
    whole reason the sheet is per placement."""
    ops.cue_add(project.root, "vo", 0, "clipa")
    ops.cue_add(project.root, "vo", 1, "clipa")
    ops.reframe(project.root, "clipa", rect="0,0,459,816")
    ops.reframe(project.root, "clipa", rect="1461,0,459,816", src_start=1.9)

    rows = ops.reframe_sheet(project.root)["rows"]

    assert rows[0]["samples"][0]["crop"] == "0,0,459,816"
    assert rows[1]["samples"][-1]["crop"] == "1461,0,459,816"


@needs_tools
def test_a_placement_crossing_a_window_boundary_says_so(project: Project) -> None:
    """`windows` counts the windows the *placement* crosses — off the geometry,
    not off where the samples happened to land. More than one means this shot
    is not framed alike throughout, which is what a reviewer needs pointing at,
    and it is also the preview/render asymmetry: the preview places the whole
    shot by the window at its `src_start`."""
    ops.cue_add(project.root, "vo", 0, "clipa")
    ops.reframe(project.root, "clipa", rect="0,0,459,816")
    ops.reframe(project.root, "clipa", rect="1461,0,459,816", src_start=1.0)

    rows = ops.reframe_sheet(project.root)["rows"]

    assert rows[0]["windows"] == 2
    assert [row["windows"] for row in rows] == [2, 2], "a property of the shot, not of the row"


# -- the row is a window, which is what the coverage fix is ---------------


@needs_tools
def test_a_window_no_round_fraction_lands_in_is_still_drawn(project: Project) -> None:
    """The finding. Three fixed fractions of a placement missed 14 of the
    vertical cut's 55 windows and eight of those were hand-approved — a window
    covering a small slice of a long placement is one no round fraction lands
    in, and it was reported as reviewed (HISTORY.md § The thirty-nine windows,
    reviewed)."""
    ops.cue_add(project.root, "vo", 0, "clipa")
    ops.reframe(project.root, "clipa", rect="0,0,459,816")
    ops.reframe(project.root, "clipa", rect="1461,0,459,816", src_start=3.9)

    result = ops.reframe_sheet(project.root)

    assert result["placements"] == 1 and result["count"] == 2
    assert [row["window"] for row in result["rows"]] == [0.0, 3.9]
    assert result["rows"][1]["samples"][0]["crop"] == "1461,0,459,816"
    # And the old unit could not have drawn it: every fraction of the whole
    # placement lands before the boundary.
    assert all(s["src_time"] < 3.9 for s in result["rows"][0]["samples"])


@needs_tools
def test_a_boundary_within_a_frame_of_a_placement_edge_is_that_edge(
    project: Project,
) -> None:
    """A frame of tolerance, never an epsilon — `reframe_coverage`'s rule, and
    not optional here either.

    A window boundary and the placement that starts on it are the same instant
    a frame apart: 20.39538 against 20.39541 on the real vertical cut. Compared
    exactly, that splits off a stretch 30µs long, draws three tiles of it, and
    leaves the placement labelled with the window it is about to leave —
    fifteen of that cut's rows were exactly this. A boundary within a frame of
    the *end* goes for the mirror reason: a window with under a frame of a
    placement left is not one that placement shows, and whichever placement
    starts there draws it as its own head.
    """
    ops.cue_add(project.root, "vo", 0, "clipa")
    ops.cue_add(project.root, "vo", 1, "clipa")
    ops.reframe(project.root, "clipa", rect="0,0,459,816")
    ops.reframe(project.root, "clipa", rect="1461,0,459,816", src_start=2.0001)

    rows = ops.reframe_sheet(project.root)["rows"]

    assert len(rows) == 2, "two placements, one window each — not a 30µs sliver"
    assert [row["windows"] for row in rows] == [1, 1]
    # And the second placement is labelled with what the render actually steps
    # to, which is the later of the two addresses.
    assert rows[1]["window"] == 2.0
    assert rows[1]["samples"][0]["crop"] == "1461,0,459,816"


@needs_tools
def test_moments_are_fractions_of_the_window_not_of_the_placement(
    project: Project,
) -> None:
    """Which is what makes the coverage claim true rather than approximate: a
    stretch is sampled inside itself, so a short window gets the same three
    looks a long one does."""
    ops.cue_add(project.root, "vo", 0, "clipa")
    ops.reframe(project.root, "clipa", rect="0,0,459,816")
    ops.reframe(project.root, "clipa", rect="1461,0,459,816", src_start=2.0)

    rows = ops.reframe_sheet(project.root, moments=[0.5])["rows"]

    assert [row["src_start"] for row in rows] == [0.0, 2.0]
    assert [row["duration"] for row in rows] == [2.0, 2.0]
    assert [row["samples"][0]["src_time"] for row in rows] == [1.0, 3.0]
    assert [row["placement_duration"] for row in rows] == [4.0, 4.0]


@needs_tools
def test_a_card_is_skipped_and_named(project: Project) -> None:
    """A still is authored at the canvas and never cropped, so it has no
    window to review — saying which rows are missing is the difference between
    "nothing to check" and "not checked"."""
    project.cards_dir.joinpath("outro.png").write_bytes(b"\x89PNG")
    ops.cue_add(project.root, "vo", 0, "clipa")
    ops.cue_add(project.root, "vo", 1, "card:outro")

    result = ops.reframe_sheet(project.root)

    assert result["count"] == 1
    assert result["skipped"] == [
        {"index": 1, "asset": "card:outro", "why": "a still is never cropped"}
    ]


@needs_tools
def test_the_edits_own_track_is_sheeted_when_there_is_no_picture_lane(
    tmp_path: Path,
) -> None:
    """With no cues the edit *is* the picture, and it is framed by the same
    rects — so it is the same review, not a different one."""
    project = Project.create(tmp_path / "solo")
    footage = tmp_path / "solo.mp4"
    _video(footage, seconds=4)
    manifest = project.read_manifest()
    manifest["clips"] = [
        {
            "clip_id": "clipa",
            "source": str(footage),
            "duration": 4.0,
            "has_video": True,
            "has_audio": False,
            "width": 1920,
            "height": 816,
        }
    ]
    project.write_manifest(manifest)
    edit = tl.Edit([tl.Segment("clipa", 0.0, 2.0), tl.Segment("clipa", 3.0, 4.0)])
    tl.write(
        tl.to_otio(edit, {c["clip_id"]: c for c in manifest["clips"]}, rate=1000.0),
        project.timeline_path,
    )
    ops.canvas(project.root, size="1080x1920")

    result = ops.reframe_sheet(project.root)

    assert result["count"] == 2, "a row per surviving segment"
    assert [row["src_start"] for row in result["rows"]] == [0.0, 3.0]


def test_moments_outside_a_placement_are_refused(project: Project) -> None:
    with pytest.raises(ProjectError, match="fractions of a placement"):
        ops.reframe_sheet(project.root, moments=[0.5, 1.5])
