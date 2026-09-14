"""`head` — a cold open on the very front, as project state.

`tail`'s mirror at the other end of the film: the same read/partial-update/
reset/plan shape, the same `_frame_total_with_tail` single-answer discipline
(extended in place to cover this end too), but the asset rule runs the exact
opposite way — a head must be a registered clip_id, never a card, because a
cold open is real footage by definition (`tail` forbids real audio, a head
requires it).

Built by hand rather than through `import_media`, `test_ops_tail.py`'s own
precedent: no ffprobe is needed to have a project with a clip in it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from proofcut import autoeditor, ops
from proofcut import timeline as tl
from proofcut.project import Project, ProjectError

VO = {
    "clip_id": "vo",
    "source": "/tmp/vo.wav",
    "duration": 6.0,
    "has_video": False,
    "has_audio": True,
}

#: The head's own asset — real footage, 12s so `src_start + seconds` has room
#: to run past it deliberately in the overrun test.
FILM = {
    "clip_id": "film",
    "source": "/tmp/film.mp4",
    "duration": 12.0,
    "has_video": True,
    "has_audio": True,
}


@pytest.fixture
def project(tmp_path: Path) -> Project:
    project = Project.create(tmp_path / "proj")
    manifest = project.read_manifest()
    manifest["clips"] = [VO, FILM]
    project.write_manifest(manifest)
    edit = tl.Edit([tl.Segment("vo", 0.0, 6.0)])
    tl.write(
        tl.to_otio(edit, {VO["clip_id"]: VO, FILM["clip_id"]: FILM}, rate=1000.0),
        project.timeline_path,
    )
    return project


# -- reading and writing ---------------------------------------------------


def test_no_arguments_reads_without_writing(project: Project) -> None:
    before = project.manifest_path.stat().st_mtime_ns
    result = ops.head(project.root)

    assert result["head"] is None
    assert result["written"] is False
    assert project.manifest_path.stat().st_mtime_ns == before
    assert ops.HEAD_KEY not in project.read_manifest()


def test_setting_stores_all_six_fields_and_defaults_the_optional_ones(
    project: Project,
) -> None:
    result = ops.head(project.root, asset="film", seconds=6.0)

    assert result["written"] is True
    assert result["head"] == {
        "asset": "film",
        "src_start": 0.0,
        "seconds": 6.0,
        "fade_in": 0.0,
        "fade_out": 0.0,
        "gain_db": 0.0,
    }
    assert project.read_manifest()[ops.HEAD_KEY] == result["head"]


def test_every_field_can_be_set_alongside_asset_and_seconds(project: Project) -> None:
    result = ops.head(
        project.root,
        asset="film",
        src_start=4.2,
        seconds=6.0,
        fade_in=0.15,
        fade_out=0.5,
        gain_db=15.1,
    )

    assert result["head"] == {
        "asset": "film",
        "src_start": 4.2,
        "seconds": 6.0,
        "fade_in": 0.15,
        "fade_out": 0.5,
        "gain_db": 15.1,
    }


def test_seconds_alone_updates_only_that_field(project: Project) -> None:
    """`tail`'s own partial-update shape: a field set once, then touched
    again on its own, leaves everything else alone."""
    ops.head(project.root, asset="film", src_start=4.2, seconds=6.0, gain_db=15.1)
    result = ops.head(project.root, seconds=5.0)

    assert result["head"] == {
        "asset": "film",
        "src_start": 4.2,
        "seconds": 5.0,
        "fade_in": 0.0,
        "fade_out": 0.0,
        "gain_db": 15.1,
    }


def test_asset_alone_updates_only_that_field(project: Project) -> None:
    """`tail`'s own partial-update shape, on the other field: a second
    registered video clip stands in for `film` and nothing else moves."""
    manifest = project.read_manifest()
    manifest["clips"].append(
        {**FILM, "clip_id": "second-unit", "duration": 20.0}
    )
    project.write_manifest(manifest)

    ops.head(project.root, asset="film", seconds=6.0, gain_db=15.1)
    result = ops.head(project.root, asset="second-unit")

    assert result["head"] == {
        "asset": "second-unit",
        "src_start": 0.0,
        "seconds": 6.0,
        "fade_in": 0.0,
        "fade_out": 0.0,
        "gain_db": 15.1,
    }


def test_a_full_revalidation_runs_on_every_partial_update(project: Project) -> None:
    """Every field is re-merged and re-checked on any change — `tail`'s own
    behavior, restated: swapping `asset` alone to a clip with no video is
    caught immediately rather than only on the next full set."""
    ops.head(project.root, asset="film", seconds=6.0)
    with pytest.raises(ProjectError, match="no video"):
        ops.head(project.root, asset="vo")


def test_reset_drops_the_key(project: Project) -> None:
    ops.head(project.root, asset="film", seconds=6.0)
    result = ops.head(project.root, reset=True)

    assert result["head"] is None
    assert result["written"] is True
    assert ops.HEAD_KEY not in project.read_manifest()


def test_plan_resolves_without_writing(project: Project) -> None:
    planned = ops.head(project.root, asset="film", seconds=6.0, plan=True)

    assert planned["head"] == {
        "asset": "film",
        "src_start": 0.0,
        "seconds": 6.0,
        "fade_in": 0.0,
        "fade_out": 0.0,
        "gain_db": 0.0,
    }
    assert planned["written"] is False
    assert ops.HEAD_KEY not in project.read_manifest()
    assert ops.head(project.root)["head"] is None, "the project never took it"


def test_asset_registered_reports_whether_the_clip_is_still_in_the_manifest(
    project: Project,
) -> None:
    result = ops.head(project.root, asset="film", seconds=6.0)
    assert result["asset_registered"] is True

    manifest = project.read_manifest()
    manifest["clips"] = [VO]
    project.write_manifest(manifest)
    assert ops.head(project.root)["asset_registered"] is False


# -- what it refuses --------------------------------------------------------


def test_reset_and_a_field_together_are_refused(project: Project) -> None:
    with pytest.raises(ProjectError, match="not both"):
        ops.head(project.root, seconds=6.0, reset=True)


def test_the_first_set_needs_both_asset_and_seconds(project: Project) -> None:
    with pytest.raises(ProjectError, match="both"):
        ops.head(project.root, asset="film")
    with pytest.raises(ProjectError, match="both"):
        ops.head(project.root, seconds=6.0)
    assert ops.HEAD_KEY not in project.read_manifest()


def test_a_card_asset_is_refused(project: Project) -> None:
    """The exact inverse of `tail`'s own refusal — a cold open is real
    footage by definition, so `card:name` is refused rather than a clip."""
    with pytest.raises(ProjectError, match="registered clip_id"):
        ops.head(project.root, asset="card:outro", seconds=6.0)
    assert ops.HEAD_KEY not in project.read_manifest()


def test_an_audio_only_asset_is_refused(project: Project) -> None:
    with pytest.raises(ProjectError, match="no video"):
        ops.head(project.root, asset="vo", seconds=6.0)
    assert ops.HEAD_KEY not in project.read_manifest()


def test_negative_src_start_is_refused(project: Project) -> None:
    with pytest.raises(ProjectError, match="negative"):
        ops.head(project.root, asset="film", src_start=-0.1, seconds=6.0)


def test_nonpositive_seconds_is_refused(project: Project) -> None:
    with pytest.raises(ProjectError, match="positive"):
        ops.head(project.root, asset="film", seconds=0.0)
    with pytest.raises(ProjectError, match="positive"):
        ops.head(project.root, asset="film", seconds=-1.0)


def test_negative_fades_are_refused(project: Project) -> None:
    with pytest.raises(ProjectError, match="negative"):
        ops.head(project.root, asset="film", seconds=6.0, fade_in=-0.1)
    with pytest.raises(ProjectError, match="negative"):
        ops.head(project.root, asset="film", seconds=6.0, fade_out=-0.1)


def test_fades_summing_over_seconds_are_refused(project: Project) -> None:
    """`tail`'s own "spent inside the length" rule, restated for two fades."""
    with pytest.raises(ProjectError, match="cannot exceed"):
        ops.head(project.root, asset="film", seconds=1.0, fade_in=0.6, fade_out=0.6)


def test_src_start_plus_seconds_past_the_asset_duration_is_refused(
    project: Project,
) -> None:
    """`plan_picture`'s "a shot longer than its asset" refusal, restated."""
    with pytest.raises(ProjectError, match="runs past"):
        ops.head(project.root, asset="film", src_start=10.0, seconds=6.0)
    assert ops.HEAD_KEY not in project.read_manifest()


# -- the single frame-total helper ------------------------------------------


def test_with_no_head_the_helper_is_frame_total_alone(project: Project) -> None:
    edit = ops._load_edit(project)
    rate = 30.0

    assert ops._frame_total_with_tail(project, edit, rate) == autoeditor.frame_total(edit, rate)


def test_a_head_adds_exactly_seconds(project: Project) -> None:
    edit = ops._load_edit(project)
    rate = 30.0
    without_head = autoeditor.frame_total(edit, rate)

    ops.head(project.root, asset="film", seconds=2.0, fade_in=0.2, fade_out=0.2)

    assert ops._frame_total_with_tail(project, edit, rate) == without_head + round(2.0 * rate)


def test_a_head_and_a_tail_together_sum_both(project: Project) -> None:
    edit = ops._load_edit(project)
    rate = 30.0
    without_either = autoeditor.frame_total(edit, rate)

    ops.head(project.root, asset="film", seconds=2.0)
    ops.tail(project.root, asset="card:outro", seconds=3.0)

    assert ops._frame_total_with_tail(project, edit, rate) == (
        without_either + round(2.0 * rate) + round(3.0 * rate)
    )


def test_status_echoes_the_head_and_the_expected_total(project: Project) -> None:
    before = ops.status(project.root)
    assert before["head"] is None

    ops.head(project.root, asset="film", seconds=2.0)
    after = ops.status(project.root)

    assert after["head"] == {
        "asset": "film",
        "src_start": 0.0,
        "seconds": 2.0,
        "fade_in": 0.0,
        "fade_out": 0.0,
        "gain_db": 0.0,
    }
    # timeline_duration is the Edit's own length and never moves for a head —
    # the Edit never grows to describe one.
    assert after["timeline_duration"] == pytest.approx(6.0, abs=1e-3)
    assert after["expected_frames"] > before["expected_frames"]


def test_check_frames_picks_up_the_head(project: Project) -> None:
    without = ops.check_frames(project.root)
    ops.head(project.root, asset="film", seconds=2.0)
    with_head = ops.check_frames(project.root)

    rate = with_head["fps"]
    assert with_head["expected_frames"] == without["expected_frames"] + round(2.0 * rate)


def test_a_head_alone_makes_the_project_layered(project: Project) -> None:
    """No cues, no second clip on the edit's own track, no canvas override —
    a head is what tips the routing decision on its own, `tail`'s own test
    restated: auto-editor has no export concept for the resource a head
    prepends."""
    edit = ops._load_edit(project)
    assert ops._is_layered(project, edit) is False

    ops.head(project.root, asset="film", seconds=2.0)
    assert ops._is_layered(project, edit) is True
