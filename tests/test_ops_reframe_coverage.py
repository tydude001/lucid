"""`reframe_coverage` — the placed seconds no window was ever chosen for.

HISTORY.md § The thirty-nine windows, reviewed. The review found the detector's
placement rule sound and its *coverage* not: 13.6s of one clip framed by a rect
chosen for a shot that ended long before, with the manifest, `status` and
`reframe_sheet` all clean over it. `reframe_detect` names that as
`falls_back_to` for the windows it refuses in the call being made, and then
throws it away — nothing is written for a refusal, so a project on disk could
not be asked. This is the asking.

The scene scan shells ffmpeg for real, on clips generated here with hard cuts
in them, for `test_ops_reframe_detect.py`'s reason: the boundary half of this is
ffmpeg's answer and a fixtured one would be lucid's. Nothing here stubs the face
detector, because nothing here calls it — that is one of the claims.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from lucid import faces, ops
from lucid import timeline as tl
from lucid import transcript as tx
from lucid.project import Project, ProjectError

needs_ffmpeg = pytest.mark.skipif(
    shutil.which("ffmpeg") is None, reason="the scene scan is ffmpeg's own answer"
)

VO = {
    "clip_id": "vo",
    "source": "/tmp/vo.wav",
    "duration": 8.0,
    "has_video": False,
    "has_audio": True,
}

#: A window the whole 1920x816 source could hold, so `reframe`'s grow-to-fit
#: leaves it alone and the rect stored is the rect asked for.
RECT = "1461,0,459,816"


def _video(path: Path, patterns: list[str], seconds: float) -> None:
    """One clip whose picture changes hard every `seconds`.

    `testsrc` against `smptebars` is about as unambiguous a change of picture as
    exists, so the threshold is doing no work in these tests — the boundary is.
    """
    inputs = []
    for pattern in patterns:
        inputs += ["-f", "lavfi", "-i", f"{pattern}=size=1920x816:rate=30:duration={seconds}"]
    joined = "".join(f"[{i}:v]" for i in range(len(patterns)))
    command = [
        "ffmpeg", "-v", "error", "-y", *inputs,
        "-filter_complex", f"{joined}concat=n={len(patterns)}:v=1[v]", "-map", "[v]",
        "-pix_fmt", "yuv420p", str(path),
    ]  # fmt: skip
    subprocess.run(command, check=True)


def _project(tmp_path: Path, patterns: list[str], seconds: float) -> Project:
    """A VO over one real clip with cuts in it, on a 9:16 canvas."""
    total = seconds * len(patterns)
    project = Project.create(tmp_path / "proj")
    footage = tmp_path / "clipa.mp4"
    _video(footage, patterns, seconds)

    manifest = project.read_manifest()
    manifest["clips"] = [
        {**VO, "duration": total},
        {
            "clip_id": "clipa",
            "source": str(footage),
            "duration": total,
            "has_video": True,
            "has_audio": False,
            "fps": 30.0,
            "width": 1920,
            "height": 816,
        },
    ]
    project.write_manifest(manifest)

    edit = tl.Edit([tl.Segment("vo", 0.0, total)])
    tl.write(
        tl.to_otio(edit, {c["clip_id"]: c for c in manifest["clips"]}, rate=1000.0),
        project.timeline_path,
    )
    tx.save(
        tx.Transcript(
            clip_id="vo",
            words=(tx.Word(index=0, text="one", start=0.0, end=0.4),),
        ),
        project.transcript_path("vo"),
    )
    ops.canvas(project.root, size="1080x1920")
    ops.cue_add(project.root, "vo", 0, "clipa")
    return project


@pytest.fixture
def project(tmp_path: Path) -> Project:
    """8s of clipa, one camera cut at 4s, all of it one placement."""
    return _project(tmp_path, ["testsrc", "smptebars"], 4.0)


@needs_ffmpeg
def test_an_override_held_across_a_camera_cut_is_reported_as_stale(
    project: Project,
) -> None:
    """The finding the whole op exists for.

    One window at the head of the clip, a real camera cut four seconds in with
    nothing at it, and everything downstream of that cut is framed by a rect
    chosen for the shot before it. On the film this shape is 13.6s of
    `cold-open` held across four camera setups, and every other check was clean
    over it.
    """
    ops.reframe(project.root, "clipa", rect=RECT)

    result = ops.reframe_coverage(project.root)

    assert result["cuts"] == 1 and result["cuts_unframed"] == 1
    assert result["stale_stretches"] == 1
    (stretch,) = result["stretches"]
    assert stretch["stale"] is True
    assert stretch["asset"] == "clipa"
    assert stretch["src_start"] == pytest.approx(4.0, abs=0.1)
    # To the placement's end, there being no later window to re-frame it.
    assert stretch["src_end"] == pytest.approx(8.0, abs=0.1)
    assert stretch["seconds"] == pytest.approx(4.0, abs=0.1)
    assert stretch["held_from"] == 0.0
    assert stretch["framed_by"] == "the window from 0.000s — a different shot's framing"
    # And the headline number is seconds of film, not a count of stretches.
    assert result["stale_seconds"] == pytest.approx(4.0, abs=0.1)
    assert result["stale_share"] == pytest.approx(0.5, abs=0.02)
    assert result["placed_seconds"] == pytest.approx(8.0, abs=0.1)


@needs_ffmpeg
def test_the_centre_crop_walking_through_a_cut_is_counted_apart_from_it(
    project: Project,
) -> None:
    """A clip with no override at all is not stale — it is undecided.

    The distinction is the point of the two numbers. An override held across a
    cut is *worse* than the default, because a stale window looks deliberate;
    the centre crop crossing one is only the default doing what it always did,
    and rolling the two together would report a project nobody has framed as a
    project somebody framed wrong.
    """
    result = ops.reframe_coverage(project.root)

    assert result["cuts_unframed"] == 1
    (stretch,) = result["stretches"]
    assert stretch["stale"] is False
    assert stretch["framed_by"] == "the centre crop"
    assert result["stale_seconds"] == 0.0
    assert result["stale_stretches"] == 0
    assert result["default_seconds"] == pytest.approx(4.0, abs=0.1)


@needs_ffmpeg
def test_a_window_at_the_cut_leaves_nothing_stale(project: Project) -> None:
    """The clean case, and it has to be reachable or the op cries wolf forever."""
    at = ops.reframe_coverage(project.root)["stretches"][0]["src_start"]
    ops.reframe(project.root, "clipa", rect=RECT)
    ops.reframe(project.root, "clipa", rect=RECT, src_start=at)

    result = ops.reframe_coverage(project.root)

    assert result["cuts"] == 1 and result["cuts_framed"] == 1
    assert result["cuts_unframed"] == 0
    assert result["stretches"] == []
    assert result["stale_seconds"] == 0.0 and result["default_seconds"] == 0.0


@needs_ffmpeg
def test_a_window_is_matched_to_a_cut_within_a_frame_and_not_exactly(
    project: Project,
) -> None:
    """A frame of tolerance, never an epsilon.

    ffmpeg reports the film's cut at 0.834167 where the manifest holds 0.8342 —
    the same cut, 33µs apart, because a stored window was addressed by hand
    through a timeline offset while the scan reads raw presentation times. An
    exact match reported 20 stale stretches on the film where there are 6. Two
    boundaries inside one source frame are one window, which is the resolution
    the render has.
    """
    at = ops.reframe_coverage(project.root)["stretches"][0]["src_start"]
    ops.reframe(project.root, "clipa", rect=RECT)
    ops.reframe(project.root, "clipa", rect=RECT, src_start=at + 0.01)

    result = ops.reframe_coverage(project.root)

    assert result["same_window_within"] == pytest.approx(1 / 30, abs=1e-4)
    assert result["cuts_framed"] == 1 and result["stretches"] == []

    # Half a second out is a different window, and then the cut is uncovered
    # again — the tolerance is a frame, not a shrug.
    ops.reframe(project.root, "clipa", src_start=at + 0.01, reset=True)
    ops.reframe(project.root, "clipa", rect=RECT, src_start=at + 0.5)
    assert ops.reframe_coverage(project.root)["cuts_unframed"] == 1


@needs_ffmpeg
def test_several_unframed_cuts_under_one_window_are_one_stretch(
    tmp_path: Path,
) -> None:
    """`cold-open` holds one rect across four camera setups, and that is one
    thing wrong rather than three.

    Counting stretches per cut would have reported the film's worst defect as
    several small ones and buried the fact that a single window is covering all
    of them.
    """
    project = _project(tmp_path, ["testsrc", "smptebars", "testsrc"], 3.0)
    ops.reframe(project.root, "clipa", rect=RECT)

    result = ops.reframe_coverage(project.root)

    assert result["cuts"] == 2 and result["cuts_unframed"] == 2
    (stretch,) = result["stretches"]
    assert len(stretch["cuts"]) == 2
    assert stretch["src_start"] == pytest.approx(3.0, abs=0.1)
    assert stretch["src_end"] == pytest.approx(9.0, abs=0.1)
    assert stretch["seconds"] == pytest.approx(6.0, abs=0.1)
    assert all(score >= ops.SCENE_THRESHOLD for score in stretch["scores"])


@needs_ffmpeg
def test_it_answers_without_a_face_detector(
    project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Scene cuts against stored geometry, and nothing else.

    `reframe_detect` raises before it decodes anything when `LUCID_FACE` names
    no usable interpreter — correctly, since it has nothing to propose from.
    The coverage question is not about proposing, so it has to be answerable on
    a box that cannot run the detector at all.
    """
    monkeypatch.setattr(
        faces, "available", lambda: {"available": False, "why": "no interpreter", "python": None}
    )
    monkeypatch.setattr(
        faces, "detect", lambda jobs: pytest.fail("coverage must not call the detector")
    )
    ops.reframe(project.root, "clipa", rect=RECT)

    assert ops.reframe_coverage(project.root)["stale_stretches"] == 1


@needs_ffmpeg
def test_raising_the_threshold_hides_the_cut_and_says_which_one_it_used(
    project: Project,
) -> None:
    """A cut with no window is one the framing walks through, so the floor's own
    miss rate *is* a framing number — the film's stale share is 10% at 0.20 and
    32% at 0.15. Which floor produced an answer is reported with it."""
    ops.reframe(project.root, "clipa", rect=RECT)

    strict = ops.reframe_coverage(project.root, threshold=0.99)

    assert strict["threshold"] == 0.99
    assert strict["cuts"] == 0 and strict["stale_seconds"] == 0.0


def test_it_reads_and_never_writes(project: Project) -> None:
    """It backs a review, so it must be safe to point at a project someone only
    looked at — the rule `Project.open` already holds for `info` and `status`."""
    ops.reframe(project.root, "clipa", rect=RECT)
    before = project.manifest_path.read_bytes()

    ops.reframe_coverage(project.root)

    assert project.manifest_path.read_bytes() == before


def test_an_unknown_clip_is_refused(project: Project) -> None:
    with pytest.raises(ProjectError, match="no clip 'nope'"):
        ops.reframe_coverage(project.root, clip_id="nope")


def test_a_threshold_outside_the_score_range_is_refused(project: Project) -> None:
    with pytest.raises(ProjectError, match="between 0 and 1"):
        ops.reframe_coverage(project.root, threshold=1.5)
