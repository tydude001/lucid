"""`continuity_check` — rewinds, replays, short shots, and film-internal-cut
stubs, ported from goodsometimes' `shot_check.py` and its v5 scan.

The gap the standalone script had: it read `build_shots`' raw `src_pin`,
`None` for every *unpinned* cue, so `if pin is None: continue` silently
skipped every unpinned re-use — `shot_check.py:82-84`'s own comment is wrong
for any unpinned video cue. This reads `_picture_plan`'s resolved
`src_start` instead, so the fixtures below deliberately build the rewind and
replay cases *unpinned*, the exact shape the gap missed.

Rewind/replay/short-shot fixtures use fake (non-decodable) media bytes and
`stubs=False`, following `tests/test_ops_finish_report.py`'s precedent: that
arithmetic never touches the file, only `shot["asset_duration"]` off the
manifest and `shot["asset_path"].is_file()`. The stub fixture shells ffmpeg
for a real hard cut, `tests/test_ops_reframe_coverage.py`'s own `_video`
helper, because the boundary half of a stub finding is ffmpeg's own answer.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from proofcut import ops
from proofcut import timeline as tl
from proofcut import transcript as tx
from proofcut.project import Project, ProjectError

needs_ffmpeg = pytest.mark.skipif(
    shutil.which("ffmpeg") is None, reason="the stub scan is ffmpeg's own answer"
)

VO = {
    "clip_id": "vo",
    "source": "/tmp/vo.wav",
    "has_video": False,
    "has_audio": True,
}


def _words(*starts: float) -> tx.Transcript:
    return tx.Transcript(
        clip_id="vo",
        words=tuple(
            tx.Word(index=i, text=f"w{i}", start=start, end=start + 0.4)
            for i, start in enumerate(starts)
        ),
    )


def _fake_clip(clip_id: str, path: Path, *, duration: float) -> dict[str, Any]:
    path.write_bytes(b"not really a video, just needs to exist")
    return {
        "clip_id": clip_id,
        "source": str(path),
        "duration": duration,
        "has_video": True,
        "has_audio": False,
        "width": 1920,
        "height": 816,
        "fps": 25.0,
    }


@pytest.fixture
def project(tmp_path: Path) -> Project:
    """One VO track and two footage clips, cued to manufacture a rewind
    (unpinned, the goodsometimes gap), a replay (pinned, the elevator
    rhyme), and a short shot, all without touching a decoder.

    Word timings (seconds), and what each cue does:
      0    -> clipa, unpinned            shot0  [0, 4)    src [0, 4)
      4    -> clipa, unpinned            shot1  [4, 9)    src [0, 5) — clipa is
                                          6s long, so the cursor (would-be 4..9)
                                          overruns and rewinds to 0: an
                                          *unpinned* rewind, `src_pin` is None.
      9    -> clipb, unpinned            shot2  [9, 11)   2s — under the 3s
                                          short-shot floor.
      11   -> card:filler                shot3  [11, 30)  a still — never
                                          walked for rewind/replay.
      30   -> clipa, pinned src_start=1  shot4  [30, 35)  src [1, 6) — overlaps
                                          shot1's [0, 5) by 4s, 21s of timeline
                                          since shot1 ended (>= the 20s gap
                                          default): the deliberate rhyme.
    """
    project = Project.create(tmp_path / "proj")
    clipa = _fake_clip("clipa", tmp_path / "clipa.mp4", duration=6.0)
    clipb = _fake_clip("clipb", tmp_path / "clipb.mp4", duration=5.0)

    card = project.cards_dir / "filler.png"
    card.write_bytes(b"not really a png")

    manifest = project.read_manifest()
    manifest["clips"] = [{**VO, "duration": 35.0}, clipa, clipb]
    project.write_manifest(manifest)

    edit = tl.Edit([tl.Segment("vo", 0.0, 35.0)])
    tl.write(
        tl.to_otio(edit, {c["clip_id"]: c for c in manifest["clips"]}, rate=1000.0),
        project.timeline_path,
    )
    tx.save(_words(0.0, 4.0, 9.0, 11.0, 30.0), project.transcript_path("vo"))

    ops.cue_add(project.root, "vo", 0, "clipa")
    ops.cue_add(project.root, "vo", 1, "clipa")
    ops.cue_add(project.root, "vo", 2, "clipb")
    ops.cue_add(project.root, "vo", 3, "card:filler")
    ops.cue_add(project.root, "vo", 4, "clipa", src_start=1.0)
    return project


def test_an_unpinned_reuse_rewinds_the_gap_goodsometimes_own_script_missed(
    project: Project,
) -> None:
    """Both shots on `clipa` here are unpinned — `src_pin` is `None` on both
    — which is exactly the case `shot_check.py`'s own `if pin is None:
    continue` silently skipped. `_picture_plan`'s resolved `src_start`
    catches it anyway.
    """
    result = ops.continuity_check(project.root, stubs=False)

    rewinds = [f for f in result["findings"] if f["kind"] == "rewind"]
    assert len(rewinds) == 1
    (finding,) = rewinds
    assert finding["clip_id"] == "vo"
    assert finding["word_index"] == 1
    assert finding["asset"] == "clipa"
    assert finding["start"] == pytest.approx(4.0)


def test_a_deliberate_rhyme_is_reported_never_refused(project: Project) -> None:
    """The elevator's own two kept replays: reporting rather than refusing
    them, because a deliberate rhyme and a mistake look identical from the
    cue table (goodsometimes `ideas/lambs-longlegs.md`).

    shot4 (word 4, `clipa` pinned to src 1.0) overlaps *both* earlier
    `clipa` shots — shot0's [0, 4) and shot1's [0, 5) — so `replay` is
    reported once per earlier overlap, always keyed to the later shot
    (word 4): "any earlier shot on the same asset", not only the nearest.
    """
    result = ops.continuity_check(project.root, stubs=False)

    replays = [f for f in result["findings"] if f["kind"] == "replay"]
    assert len(replays) == 2
    assert all(f["word_index"] == 4 and f["asset"] == "clipa" for f in replays)
    assert all(f["start"] == pytest.approx(30.0) for f in replays)
    # Reported, not refused — the call above did not raise, and the project
    # is exactly as usable afterward.
    assert ops.continuity_check(project.root, stubs=False)["shots_error"] is None


def test_a_short_shot_is_flagged_and_a_still_is_never_walked(project: Project) -> None:
    result = ops.continuity_check(project.root, stubs=False)

    shorts = [f for f in result["findings"] if f["kind"] == "short_shot"]
    assert len(shorts) == 1
    (finding,) = shorts
    assert finding["word_index"] == 2
    assert finding["asset"] == "clipb"
    # `card:filler` (word 3) never appears in any finding — stills are
    # skipped for rewind/replay/short-shot alike.
    assert all(f["asset"] != "card:filler" for f in result["findings"])


def test_overrun_is_not_a_finding(project: Project) -> None:
    """`mlt.plan_picture` already refuses overrun structurally, so a shot
    that reaches `continuity_check`'s walk at all cannot overrun its asset
    — there is no `kind == "overrun"` in the vocabulary at all."""
    result = ops.continuity_check(project.root, stubs=False)

    assert all(f["kind"] in {"rewind", "replay", "short_shot", "stub"} for f in result["findings"])


def test_stubs_off_by_default_skips_no_findings_here(project: Project) -> None:
    """`stubs=True` is the default; this project's footage is fake bytes, so
    the default call must not attempt to decode it — it would raise, and the
    rewind/replay/short-shot findings would vanish with it."""
    result = ops.continuity_check(project.root)

    assert result["stub_error"] is not None  # the scan was attempted, and fake bytes refuse
    kinds = {f["kind"] for f in result["findings"]}
    assert kinds == {"rewind", "replay", "short_shot"}


def test_accept_then_re_cue_reports_the_finding_again_as_stale(project: Project) -> None:
    """The single most important test in the set — `unspoken`'s own
    staleness rule, restated: a suppressed real problem is invisible, so an
    accepted mark must never silently outlive the shot it was accepted for.
    """
    accepted = ops.continuity_accept(project.root, "vo", 1, "rewind")
    assert accepted["accepted"] == 1

    suppressed = ops.continuity_check(project.root, stubs=False)
    assert [f for f in suppressed["findings"] if f["kind"] == "rewind"] == []
    assert suppressed["accepted"] == 1

    # Move the shot: re-cue word 1 to pin a *different* source instant (still
    # inside clipa's own 6s so the shot does not overrun and refuse), so the
    # same (clip_id=vo, word_index=1, kind=rewind) key now describes a
    # different rewind than the one that was accepted.
    ops.cue_rm(project.root, "vo", 1)
    ops.cue_add(project.root, "vo", 1, "clipa", src_start=0.5)

    after = ops.continuity_check(project.root, stubs=False)
    rewinds = [f for f in after["findings"] if f["kind"] == "rewind"]
    assert len(rewinds) == 1
    assert rewinds[0]["accepted_stale"] is True
    assert after["accepted_stale"] == rewinds
    # Never silently re-suppressed.
    assert after["accepted"] == 0


def test_continuity_reject_puts_a_finding_back(project: Project) -> None:
    ops.continuity_accept(project.root, "vo", 1, "rewind")
    assert ops.continuity_check(project.root, stubs=False)["accepted"] == 1

    rejected = ops.continuity_reject(project.root, "vo", 1, "rewind")
    assert rejected["accepted"] == 0

    result = ops.continuity_check(project.root, stubs=False)
    assert result["accepted"] == 0
    assert any(f["kind"] == "rewind" for f in result["findings"])


def test_continuity_reject_refuses_an_unmarked_finding(project: Project) -> None:
    with pytest.raises(ProjectError, match="no accepted"):
        ops.continuity_reject(project.root, "vo", 1, "rewind")


def test_continuity_accept_refuses_when_the_finding_is_not_there(project: Project) -> None:
    with pytest.raises(ProjectError, match="no .*rewind.* finding"):
        ops.continuity_accept(project.root, "vo", 4, "rewind")  # word 4 is a replay, not a rewind


def test_continuity_ls_reports_still_found_and_stale(project: Project) -> None:
    ops.continuity_accept(project.root, "vo", 1, "rewind")
    ops.cue_rm(project.root, "vo", 1)
    ops.cue_add(project.root, "vo", 1, "clipa", src_start=0.5)

    rows = ops.continuity_ls(project.root)

    assert rows["count"] == 1
    (row,) = rows["accepted"]
    assert row["clip_id"] == "vo"
    assert row["word_index"] == 1
    assert row["kind"] == "rewind"
    assert row["still_found"] is True
    assert row["stale"] is True
    assert rows["stale"] == 1


def test_continuity_ls_is_empty_with_nothing_accepted(project: Project) -> None:
    rows = ops.continuity_ls(project.root)
    assert rows == {
        "project": str(project.root),
        "count": 0,
        "stale": 0,
        "shots_error": None,
        "stub_error": None,
        "accepted": [],
    }


def test_a_stale_orphaned_cue_reports_shots_error_rather_than_raising(
    project: Project,
) -> None:
    ops.cut_by_time(project.root, spans=[[4.0, 4.4]])  # removes word 1's own span whole

    result = ops.continuity_check(project.root, stubs=False)

    assert result["shots_error"] is not None
    assert result["findings"] == []
    assert result["count"] == 0


# -- the stored head as pseudo-shot zero -----------------------------------


@pytest.fixture
def headed_project(tmp_path: Path) -> Project:
    """A stored cold open on `clipa`, and a first real shot that reuses
    `clipa` from behind where the head left off — WORK-ORDERS ruling 6: "a
    body-first-shot rewind against the cold open is caught natively".
    """
    project = Project.create(tmp_path / "proj")
    clipa = _fake_clip("clipa", tmp_path / "clipa.mp4", duration=10.0)

    manifest = project.read_manifest()
    manifest["clips"] = [{**VO, "duration": 3.0}, clipa]
    project.write_manifest(manifest)

    edit = tl.Edit([tl.Segment("vo", 0.0, 3.0)])
    tl.write(
        tl.to_otio(edit, {c["clip_id"]: c for c in manifest["clips"]}, rate=1000.0),
        project.timeline_path,
    )
    tx.save(_words(0.0), project.transcript_path("vo"))

    ops.head(project.root, asset="clipa", seconds=5.0, src_start=0.0)
    # The body's very first shot: `clipa` again, from behind the head's own
    # ending position (5.0) — a body-first-shot rewind against the cold open.
    ops.cue_add(project.root, "vo", 0, "clipa", src_start=1.0)
    return project


def test_a_body_first_shot_rewinds_against_the_stored_head(headed_project: Project) -> None:
    result = ops.continuity_check(headed_project.root, stubs=False)

    rewinds = [f for f in result["findings"] if f["kind"] == "rewind"]
    assert len(rewinds) == 1
    (finding,) = rewinds
    assert finding["word_index"] == 0
    assert finding["asset"] == "clipa"
    # Edit-relative: the body's first shot starts at 0.0, the two-clock rule.
    assert finding["start"] == pytest.approx(0.0)


def test_with_no_head_the_same_project_has_no_rewind(headed_project: Project) -> None:
    """The finding above is a fact about the *head*, not about the shot on
    its own — remove the head and the same cue is no longer a rewind."""
    ops.head(headed_project.root, reset=True)

    result = ops.continuity_check(headed_project.root, stubs=False)

    assert [f for f in result["findings"] if f["kind"] == "rewind"] == []


# -- film-internal-cut stubs (real ffmpeg) ---------------------------------


def _hard_cut_video(path: Path, seconds: float = 4.0) -> None:
    """One clip whose picture changes hard once, at `seconds` in —
    `test_ops_reframe_coverage.py`'s own `_video` helper: `testsrc` against
    `smptebars` is about as unambiguous a change of picture as exists, so the
    threshold is doing no work here — the boundary is.
    """
    inputs = []
    for pattern in ("testsrc", "smptebars"):
        inputs += ["-f", "lavfi", "-i", f"{pattern}=size=320x240:rate=30:duration={seconds}"]
    command = [
        "ffmpeg", "-v", "error", "-y", *inputs,
        "-filter_complex", "[0:v][1:v]concat=n=2:v=1[v]", "-map", "[v]",
        "-pix_fmt", "yuv420p", str(path),
    ]  # fmt: skip
    subprocess.run(command, check=True)


@pytest.fixture
def stub_project(tmp_path: Path) -> Project:
    """A shot that ends 0.7s past a real internal cut in its own footage —
    a fragment, not the shot the cue table claims."""
    project = Project.create(tmp_path / "proj")
    footage = tmp_path / "clipc.mp4"
    _hard_cut_video(footage, seconds=4.0)  # cut at src ~4.0s, 8.0s total

    manifest = project.read_manifest()
    manifest["clips"] = [
        {**VO, "duration": 4.7},
        {
            "clip_id": "clipc",
            "source": str(footage),
            "duration": 8.0,
            "has_video": True,
            "has_audio": False,
            "fps": 30.0,
            "width": 320,
            "height": 240,
        },
    ]
    project.write_manifest(manifest)

    edit = tl.Edit([tl.Segment("vo", 0.0, 4.7)])
    tl.write(
        tl.to_otio(edit, {c["clip_id"]: c for c in manifest["clips"]}, rate=1000.0),
        project.timeline_path,
    )
    tx.save(_words(0.0), project.transcript_path("vo"))
    ops.cue_add(project.root, "vo", 0, "clipc")  # unpinned: reads src [0, 4.7)
    return project


@needs_ffmpeg
def test_a_shot_ending_just_past_a_real_cut_is_a_stub(stub_project: Project) -> None:
    result = ops.continuity_check(stub_project.root)

    assert result["stub_error"] is None
    stubs = [f for f in result["findings"] if f["kind"] == "stub"]
    assert len(stubs) == 1
    (finding,) = stubs
    assert finding["asset"] == "clipc"
    assert "end" in finding["detail"]


@needs_ffmpeg
def test_a_cut_sitting_at_a_shots_own_edge_is_not_a_stub(tmp_path: Path) -> None:
    """A cut the timeline already cuts on is the expected case, not a
    defect — the same "steps"/"stale" asymmetry `reframe_coverage` draws.
    Same footage as `stub_project`, but the shot's own end lands exactly on
    the real cut (4.0s) instead of 0.7s past it."""
    project = Project.create(tmp_path / "proj")
    footage = tmp_path / "clipc.mp4"
    _hard_cut_video(footage, seconds=4.0)

    manifest = project.read_manifest()
    manifest["clips"] = [
        {**VO, "duration": 4.0},
        {
            "clip_id": "clipc",
            "source": str(footage),
            "duration": 8.0,
            "has_video": True,
            "has_audio": False,
            "fps": 30.0,
            "width": 320,
            "height": 240,
        },
    ]
    project.write_manifest(manifest)

    edit = tl.Edit([tl.Segment("vo", 0.0, 4.0)])
    tl.write(
        tl.to_otio(edit, {c["clip_id"]: c for c in manifest["clips"]}, rate=1000.0),
        project.timeline_path,
    )
    tx.save(_words(0.0), project.transcript_path("vo"))
    ops.cue_add(project.root, "vo", 0, "clipc")  # reads src [0, 4.0) — ends at the cut

    result = ops.continuity_check(project.root)

    assert result["stub_error"] is None
    assert [f for f in result["findings"] if f["kind"] == "stub"] == []
