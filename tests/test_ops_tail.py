"""`tail` — a finishing pass on the very end, as project state.

The mechanism this closes: a bumper or end card applied downstream of
`export` is dropped by every derivation at exit 0, with nothing in `status`,
`verify` or `check_frames` ever noticing (HISTORY.md § The bumper the teaser
never had, § The end card; PLAN.md § Tail time — the design note). Half these
tests pin down `tail` itself — the `canvas`/`caption_style` shape, minus the
derivation that would let a media clip in — and the other half pin down that
`_frame_total_with_tail` is the one helper every "how long is this" reader
moved to, so a duration cannot be answered two ways.

Built by hand rather than through `import_media`, following
`test_ops_canvas.py`: no ffprobe is needed to have a project with a shape.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from proofcut import autoeditor, ops
from proofcut import timeline as tl
from proofcut.project import Project, ProjectError

CLIP = {
    "clip_id": "vo",
    "source": "/tmp/vo.wav",
    "duration": 6.0,
    "has_video": False,
    "has_audio": True,
}


@pytest.fixture
def project(tmp_path: Path) -> Project:
    project = Project.create(tmp_path / "proj")
    manifest = project.read_manifest()
    manifest["clips"] = [CLIP]
    project.write_manifest(manifest)
    edit = tl.Edit([tl.Segment("vo", 0.0, 6.0)])
    tl.write(tl.to_otio(edit, {CLIP["clip_id"]: CLIP}, rate=1000.0), project.timeline_path)
    return project


# -- reading and writing ---------------------------------------------------


def test_no_arguments_reads_without_writing(project: Project) -> None:
    before = project.manifest_path.stat().st_mtime_ns
    result = ops.tail(project.root)

    assert result["tail"] is None
    assert result["written"] is False
    assert project.manifest_path.stat().st_mtime_ns == before
    assert ops.TAIL_KEY not in project.read_manifest()


def test_setting_stores_asset_and_seconds_and_defaults_fade(project: Project) -> None:
    result = ops.tail(project.root, asset="card:outro", seconds=6.0)

    assert result["written"] is True
    assert result["tail"] == {"asset": "card:outro", "seconds": 6.0, "fade": 0.0}
    assert project.read_manifest()[ops.TAIL_KEY] == {
        "asset": "card:outro",
        "seconds": 6.0,
        "fade": 0.0,
    }


def test_fade_can_be_set_alongside_asset_and_seconds(project: Project) -> None:
    result = ops.tail(project.root, asset="card:outro", seconds=6.0, fade=0.167)

    assert result["tail"] == {"asset": "card:outro", "seconds": 6.0, "fade": 0.167}


def test_seconds_alone_updates_only_that_field(project: Project) -> None:
    """The `caption_style` partial-update shape: a field set once, then
    touched again on its own, leaves everything else alone."""
    ops.tail(project.root, asset="card:outro", seconds=6.0, fade=0.167)
    result = ops.tail(project.root, seconds=5.0)

    assert result["tail"] == {"asset": "card:outro", "seconds": 5.0, "fade": 0.167}


def test_asset_alone_updates_only_that_field(project: Project) -> None:
    ops.tail(project.root, asset="card:outro", seconds=6.0, fade=0.167)
    result = ops.tail(project.root, asset="card:end-screen")

    assert result["tail"] == {"asset": "card:end-screen", "seconds": 6.0, "fade": 0.167}


def test_reset_drops_the_key(project: Project) -> None:
    ops.tail(project.root, asset="card:outro", seconds=6.0)
    result = ops.tail(project.root, reset=True)

    assert result["tail"] is None
    assert result["written"] is True
    assert ops.TAIL_KEY not in project.read_manifest()


def test_plan_resolves_without_writing(project: Project) -> None:
    planned = ops.tail(project.root, asset="card:outro", seconds=6.0, plan=True)

    assert planned["tail"] == {"asset": "card:outro", "seconds": 6.0, "fade": 0.0}
    assert planned["written"] is False
    assert ops.TAIL_KEY not in project.read_manifest()
    assert ops.tail(project.root)["tail"] is None, "the project never took it"


def test_asset_exists_reports_whether_the_card_is_on_disk(project: Project) -> None:
    result = ops.tail(project.root, asset="card:outro", seconds=6.0)
    assert result["asset_exists"] is False

    project.cards_dir.joinpath("outro.png").write_bytes(b"\x89PNG")
    assert ops.tail(project.root)["asset_exists"] is True


# -- what it refuses --------------------------------------------------------


def test_reset_and_a_field_together_are_refused(project: Project) -> None:
    with pytest.raises(ProjectError, match="not both"):
        ops.tail(project.root, seconds=6.0, reset=True)


def test_the_first_set_needs_both_asset_and_seconds(project: Project) -> None:
    with pytest.raises(ProjectError, match="both"):
        ops.tail(project.root, asset="card:outro")
    with pytest.raises(ProjectError, match="both"):
        ops.tail(project.root, seconds=6.0)
    assert ops.TAIL_KEY not in project.read_manifest()


def test_a_media_clip_asset_is_refused(project: Project) -> None:
    """`verify` diffs a render's own transcription against the timeline's
    words; a media clip's audio would give it something to disagree about on
    every check from here on, so this is refused here rather than discovered
    later as a permanent miss."""
    with pytest.raises(ProjectError, match="card"):
        ops.tail(project.root, asset="vo", seconds=6.0)
    assert ops.TAIL_KEY not in project.read_manifest()


def test_nonpositive_seconds_is_refused(project: Project) -> None:
    with pytest.raises(ProjectError, match="positive"):
        ops.tail(project.root, asset="card:outro", seconds=0.0)
    with pytest.raises(ProjectError, match="positive"):
        ops.tail(project.root, asset="card:outro", seconds=-1.0)


def test_negative_fade_is_refused(project: Project) -> None:
    with pytest.raises(ProjectError, match="negative"):
        ops.tail(project.root, asset="card:outro", seconds=6.0, fade=-0.1)


def test_fade_over_seconds_is_refused(project: Project) -> None:
    """The known trap this key exists to not repeat: `seconds` is the tail's
    whole length, so a fade cannot cost more than the tail has."""
    with pytest.raises(ProjectError, match="cannot exceed"):
        ops.tail(project.root, asset="card:outro", seconds=1.0, fade=2.0)


# -- the single frame-total helper ------------------------------------------


def test_with_no_tail_the_helper_is_frame_total_alone(project: Project) -> None:
    edit = ops._load_edit(project)
    rate = 30.0

    assert ops._frame_total_with_tail(project, edit, rate) == autoeditor.frame_total(edit, rate)


def test_a_tail_adds_exactly_seconds_never_seconds_plus_fade(project: Project) -> None:
    """The arithmetic trap this build exists to not repeat (HISTORY.md § The
    bumper the teaser never had): `xfade` finishes exactly at the length it is
    given, so treating `seconds` as a hold and adding `fade` on top of it runs
    the render long by exactly the fade. `seconds` alone is what must reach
    the frame count."""
    edit = ops._load_edit(project)
    rate = 30.0
    without_tail = autoeditor.frame_total(edit, rate)

    ops.tail(project.root, asset="card:outro", seconds=2.0, fade=0.5)

    assert ops._frame_total_with_tail(project, edit, rate) == without_tail + round(2.0 * rate)


def test_status_echoes_the_tail_and_the_expected_total(project: Project) -> None:
    before = ops.status(project.root)
    assert before["tail"] is None
    assert before["timeline_duration"] == pytest.approx(6.0, abs=1e-3)
    assert before["expected_duration"] == pytest.approx(6.0, abs=1e-1)

    ops.tail(project.root, asset="card:outro", seconds=2.0)
    after = ops.status(project.root)

    assert after["tail"] == {"asset": "card:outro", "seconds": 2.0, "fade": 0.0}
    # timeline_duration is the Edit's own length and never moves for a tail —
    # the Edit never grows to describe one.
    assert after["timeline_duration"] == pytest.approx(6.0, abs=1e-3)
    assert after["expected_frames"] > before["expected_frames"]


def test_check_frames_picks_up_the_tail(project: Project) -> None:
    without = ops.check_frames(project.root)
    ops.tail(project.root, asset="card:outro", seconds=2.0)
    with_tail = ops.check_frames(project.root)

    rate = with_tail["fps"]
    assert with_tail["expected_frames"] == without["expected_frames"] + round(2.0 * rate)


def test_a_tail_alone_makes_the_project_layered(project: Project) -> None:
    """No cues, no second clip, no canvas override — a tail is what tips the
    routing decision on its own, because auto-editor has no export for the
    card and the silence a tail adds."""
    edit = ops._load_edit(project)
    assert ops._is_layered(project, edit) is False

    ops.tail(project.root, asset="card:outro", seconds=2.0)
    assert ops._is_layered(project, edit) is True
