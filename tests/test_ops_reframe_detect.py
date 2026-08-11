"""`reframe_detect` — the framing proposal, and the four ways it refuses.

PLAN.md § The auto-framing detector. Whether the *rule* is any good is settled
in `test_framing_control.py`, against the sixteen approved windows and a metric
that existed before the detector did. This file is about the op around it: that
a placement is split at its own camera cuts, that a window with no face comes
back **named rather than quietly centre-cropped**, that applying goes through
`ops.reframe` and never over a window someone framed by hand.

The scene scan shells ffmpeg for real, on a clip generated here with one hard
cut in the middle of it, because the boundary half of this is ffmpeg's answer
and a fixtured one would be lucid's. The *detector* is stubbed: insightface
lives in another interpreter (`faces.py`), and what the boxes mean is measured
in the control rather than asserted here.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from lucid import faces, mlt, ops
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

#: The generated clip's own cut. `testsrc` for four seconds and then
#: `smptebars` is about as unambiguous a change of picture as exists, so the
#: threshold under test is doing no work here — the boundary is.
CUT_AT = 4.0


def _video(path: Path) -> None:
    command = [
        "ffmpeg", "-v", "error", "-y",
        "-f", "lavfi", "-i", "testsrc=size=1920x816:rate=30:duration=4",
        "-f", "lavfi", "-i", "smptebars=size=1920x816:rate=30:duration=4",
        "-filter_complex", "[0:v][1:v]concat=n=2:v=1[v]", "-map", "[v]",
        "-pix_fmt", "yuv420p", str(path),
    ]  # fmt: skip
    subprocess.run(command, check=True)


@pytest.fixture
def project(tmp_path: Path) -> Project:
    """A VO over one real 1920x816 clip with a cut in it, on a 9:16 canvas."""
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
            "fps": 30.0,
            "width": 1920,
            "height": 816,
        },
    ]
    project.write_manifest(manifest)

    edit = tl.Edit([tl.Segment("vo", 0.0, 8.0)])
    tl.write(
        tl.to_otio(edit, {c["clip_id"]: c for c in manifest["clips"]}, rate=1000.0),
        project.timeline_path,
    )
    tx.save(
        tx.Transcript(
            clip_id="vo",
            words=(
                tx.Word(index=0, text="one", start=0.0, end=0.4),
                tx.Word(index=1, text="two", start=4.0, end=4.4),
            ),
        ),
        project.transcript_path("vo"),
    )
    ops.canvas(project.root, size="1080x1920")
    return project


def _face(centre: float) -> dict[str, Any]:
    """One plausible box, centred where the caller wants the window."""
    return {"box": [centre - 60.0, 120.0, centre + 60.0, 400.0], "score": 0.9}


def _stub(monkeypatch: pytest.MonkeyPatch, answer: Any) -> list[dict[str, Any]]:
    """Stand in for the detector, and hand back the jobs it was asked for.

    `answer` is called with each job and returns that window's frames, or an
    error string. The captured jobs are the assertion that the op sampled where
    it said it did.
    """
    seen: list[dict[str, Any]] = []

    def fake_detect(jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        seen.extend(jobs)
        out = []
        for job in jobs:
            got = answer(job)
            if isinstance(got, str):
                out.append({"index": job["index"], "error": got})
            else:
                out.append(
                    {
                        "index": job["index"],
                        "frames": [{"ts": ts, "faces": got} for ts in job["timestamps"]],
                    }
                )
        return out

    monkeypatch.setattr(
        faces, "available", lambda: {"available": True, "python": "/stub", "model": "x", "why": None}
    )
    monkeypatch.setattr(faces, "detect", fake_detect)
    return seen


@needs_ffmpeg
def test_a_placement_is_split_at_its_own_camera_cuts(
    project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two windows out of one placement, and each says where it came from.

    § Per-shot framing's threshold-robust claim, on the smallest possible case:
    the film needs more windows than it has placements, because a placement is
    a stretch of the edit and a window is a camera shot.
    """
    ops.cue_add(project.root, "vo", 0, "clipa")
    seen = _stub(monkeypatch, lambda _job: [_face(700.0)])

    result = ops.reframe_detect(project.root)

    assert result["count"] == 2
    assert result["placements"] == 1
    head, second = result["windows"]
    assert head["boundary"] == "placement" and head["scene_score"] is None
    assert second["boundary"] == "cut"
    assert second["src_start"] == pytest.approx(CUT_AT, abs=0.1)
    assert second["scene_score"] >= ops.SCENE_THRESHOLD
    # Three frames a window, off both edges — a sample landing on the boundary
    # is as likely to catch the shot after it as the one being framed.
    assert [len(job["timestamps"]) for job in seen] == [3, 3]
    assert all(
        w["src_start"] < ts < w["src_end"]
        for w, job in zip(result["windows"], seen, strict=True)
        for ts in job["timestamps"]
    )


@needs_ffmpeg
def test_a_proposal_is_the_canvas_shape_moved_onto_the_faces(
    project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The rect is the centre crop's own shape at a different x.

    Which means `reframe`'s grow-to-fit is a no-op on it and the rect stored is
    the rect proposed — a proposal that had to be fitted would be reported as
    one thing and written as another.
    """
    ops.cue_add(project.root, "vo", 0, "clipa")
    _stub(monkeypatch, lambda _job: [_face(700.0)])

    result = ops.reframe_detect(project.root)
    _x, y, width, height = mlt.centre_crop((1920, 816), (1080, 1920))

    for window in result["windows"]:
        got = [int(v) for v in window["rect"].split(",")]
        assert got[1:] == [y, width, height]
        assert got[0] == round(700.0 - width / 2)
        assert window["refused"] is None
        assert window["faces"] == 3 and window["frames_with_faces"] == 3


@needs_ffmpeg
def test_a_window_with_no_face_is_refused_and_nothing_is_written_for_it(
    project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The load-bearing refusal.

    A silent fallback is indistinguishable in the output from a framing
    decision. Eight of the film's fifty-nine windows arrive this way.
    """
    ops.cue_add(project.root, "vo", 0, "clipa")
    _stub(monkeypatch, lambda job: [] if job["index"] == 0 else [_face(700.0)])

    result = ops.reframe_detect(project.root, apply=True)

    unframed, framed = result["windows"]
    assert unframed["rect"] is None
    assert "no face" in unframed["refused"]
    assert unframed["faces"] == 0 and unframed["applied"] is False
    assert framed["rect"] is not None and framed["applied"] is True
    assert result["proposed"] == 1 and result["refused"] == 1

    # And nothing was written for it — not the centre crop, not anything.
    stored = [r.get("src_start", 0.0) for r in project.read_manifest()["reframe"]]
    assert stored == [pytest.approx(framed["src_start"])]


@needs_ffmpeg
def test_a_refusal_names_what_will_actually_cover_it(
    project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    """"Refused" is not "centre-cropped", and saying it was is a bug the sheet
    caught rather than the tests.

    Nothing is written for a refused window, so whatever is already in force
    carries over. At the head of a clip that is the centre crop. Anywhere else
    it is the **previous shot's** framing — worse than the default rather than
    equal to it, because a stale window looks deliberate. On the film 4 of the
    8 refusals inherit one that way.
    """
    ops.cue_add(project.root, "vo", 0, "clipa")

    # The head window frames, the one after the cut does not.
    _stub(monkeypatch, lambda job: [_face(700.0)] if job["index"] == 0 else [])
    inherits = ops.reframe_detect(project.root, apply=True)["windows"][1]
    assert inherits["rect"] is None
    assert "a different shot's framing" in inherits["falls_back_to"]
    assert inherits["falls_back_to"].startswith("the window from 0.000s")

    # And the other way round: refused at the head, with nothing before it.
    ops.reframe(project.root, reset=True)
    _stub(monkeypatch, lambda job: [] if job["index"] == 0 else [_face(700.0)])
    head = ops.reframe_detect(project.root)["windows"][0]
    assert head["falls_back_to"] == "the centre crop"


@needs_ffmpeg
def test_applying_leaves_a_window_that_is_already_framed_by_hand_alone(
    project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A stored override is someone's decision, and this has no way to know it
    is the worse one — 2 of the 15 hand windows were wrong and neither was
    visible in motion, which cuts both ways."""
    ops.cue_add(project.root, "vo", 0, "clipa")
    ops.reframe(project.root, "clipa", rect="1461,0,459,816")
    _stub(monkeypatch, lambda _job: [_face(700.0)])

    result = ops.reframe_detect(project.root, apply=True)

    head, second = result["windows"]
    assert head["current"] == "override" and head["applied"] is False
    assert "already framed by hand" in head["refused"]
    # It still says what it *would* have proposed, so the sheet can be read
    # against the hand window rather than in place of it.
    assert head["rect"] is not None
    assert second["current"] == "centre" and second["applied"] is True
    assert result["applied"] == 1

    records = project.read_manifest()["reframe"]
    assert [r["rect"] for r in records if not r.get("src_start")] == [[1461, 0, 459, 816]]


@needs_ffmpeg
def test_two_placements_reading_one_stretch_share_one_window(
    project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    """They would write to one address, so framing them twice from two
    samplings is how the second silently wins.

    Both cues are **pinned** to the head of the clip, because that is the only
    way two placements read one stretch: an unpinned cursor advances rather
    than rewinds, so an ordinary re-use reads somewhere else and gets its own
    windows (CLAUDE.md § the pinned cue).
    """
    ops.cue_add(project.root, "vo", 0, "clipa", src_start=0.0)
    ops.cue_add(project.root, "vo", 1, "clipa", src_start=0.0)
    _stub(monkeypatch, lambda _job: [_face(700.0)])

    result = ops.reframe_detect(project.root)

    assert result["placements"] == 2
    starts = [w["src_start"] for w in result["windows"]]
    assert len(starts) == len(set(starts)), "one window per (clip, src_start)"
    shared = [w for w in result["windows"] if len(w["shots"]) > 1]
    assert shared, "the two placements read the same head window"


@needs_ffmpeg
def test_nothing_is_scanned_when_no_detector_is_installed(
    project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The scan is minutes of decoding, so a missing interpreter refuses now.

    And it refuses with the resolver's own message, which names both places it
    looked — an unavailable detector should not read as a project with nothing
    in it to frame.
    """
    ops.cue_add(project.root, "vo", 0, "clipa")
    monkeypatch.setattr(
        faces,
        "available",
        lambda: {"available": False, "python": None, "model": "x", "why": "no interpreter, looked at $LUCID_FACE"},
    )
    monkeypatch.setattr(
        faces, "detect", lambda jobs: pytest.fail("the detector should not have been reached")
    )

    with pytest.raises(faces.FaceError, match="LUCID_FACE"):
        ops.reframe_detect(project.root)


@needs_ffmpeg
def test_one_unreadable_window_does_not_throw_the_others_away(
    project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A window failing is reported against that window. One unseekable moment
    in a thirty-five window run is not a reason to lose the other thirty-four."""
    ops.cue_add(project.root, "vo", 0, "clipa")
    _stub(monkeypatch, lambda job: "RuntimeError: no frame there" if job["index"] == 1 else [_face(700.0)])

    result = ops.reframe_detect(project.root)

    assert result["windows"][0]["rect"] is not None
    assert result["windows"][1]["rect"] is None
    assert "no frame there" in result["windows"][1]["refused"]


@needs_ffmpeg
def test_a_still_has_no_window_to_review_and_says_so(
    project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A card is authored at the canvas and never cropped, so it is named under
    `skipped` rather than dropped — "nothing to check" and "not checked" are
    different answers."""
    project.cards_dir.joinpath("outro.png").write_bytes(b"\x89PNG")
    ops.cue_add(project.root, "vo", 0, "clipa")
    ops.cue_add(project.root, "vo", 1, "card:outro")
    _stub(monkeypatch, lambda _job: [_face(700.0)])

    result = ops.reframe_detect(project.root)

    assert any("still is never cropped" in entry["why"] for entry in result["skipped"])
    assert all(window["clip_id"] == "clipa" for window in result["windows"])


def test_a_threshold_outside_a_score_is_refused(project: Project) -> None:
    for bad in (0.0, -0.5, 1.5):
        with pytest.raises(ProjectError, match="score between 0 and 1"):
            ops.reframe_detect(project.root, threshold=bad)
    with pytest.raises(ProjectError, match="at least one frame"):
        ops.reframe_detect(project.root, frames=0)


@needs_ffmpeg
def test_a_stored_window_a_fraction_of_a_frame_away_is_the_same_window(
    project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The bug the film found and the tests could not.

    ffmpeg reports a cut at its raw presentation time and a hand-framed window
    was addressed through a timeline offset — on the real project those differ
    by **33 microseconds** at the same cut, and an exact-match test called
    fifteen of the sixteen approved windows unframed. `--apply` would then have
    written a duplicate a hair from each one. Two boundaries inside one source
    frame are one window, because that is the resolution the render has.
    """
    ops.cue_add(project.root, "vo", 0, "clipa")
    _stub(monkeypatch, lambda _job: [_face(700.0)])

    found = ops.reframe_detect(project.root)["windows"][1]["src_start"]
    assert found == pytest.approx(CUT_AT, abs=0.1)
    assert ops.reframe_detect(project.root)["same_window_within"] == pytest.approx(
        1 / 30, abs=1e-5
    ), "one frame of this clip's own rate"

    # Half a millisecond off the detected boundary — the same cut, addressed
    # by someone who measured it somewhere else.
    ops.reframe(project.root, "clipa", rect="1461,0,459,816", src_start=found + 0.0005)
    result = ops.reframe_detect(project.root, apply=True)

    assert result["windows"][1]["current"] == "override"
    assert result["windows"][1]["applied"] is False
    assert "already framed by hand" in result["windows"][1]["refused"]
    stored = [r.get("src_start", 0.0) for r in project.read_manifest()["reframe"]]
    assert stored == [0.0, pytest.approx(found + 0.0005)], "no duplicate beside the hand window"


@needs_ffmpeg
def test_a_stored_window_a_whole_shot_away_is_a_different_window(
    project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The other side of it: the tolerance is a frame, not a neighbourhood.

    On the film the human began one window twelve frames into a placement that
    has no visual event at all, and the half-second before it is genuinely
    unframed — a detector proposing something there is not re-framing anyone's
    shot.
    """
    ops.cue_add(project.root, "vo", 0, "clipa")
    _stub(monkeypatch, lambda _job: [_face(700.0)])

    ops.reframe(project.root, "clipa", rect="1461,0,459,816", src_start=CUT_AT + 0.5)
    result = ops.reframe_detect(project.root, apply=True)

    assert [w["current"] for w in result["windows"]] == ["centre", "centre"]
    assert result["applied"] == 2
