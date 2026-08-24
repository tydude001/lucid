"""`holds` — the manifest key, `_hold_plan`'s algebra, and `hold_add`/
`hold_rm`/`hold_ls` as project state.

Built by hand rather than through `import_media`, `test_ops_music.py`'s own
discipline: no ffprobe is needed to have a project with a shape. The fixture
mirrors `test_ops_music.py`'s VO transcript exactly ("the first twelve
minutes of scream") plus a film clip's own five-word line ("i know what you
did"), so the algebra in every test below can be checked by hand:

    elapsed = gap_at - cue_at = 1.9 - 1.0 = 0.9
    src_start = phrase_start - elapsed - head_margin = 10.0 - 0.9 - 0.15 = 8.95
    hold_length = (phrase_end - phrase_start) + head_margin + tail_margin
                = (11.3 - 10.0) + 0.15 + 0.45 = 1.9
    play_at = src_start + elapsed = 8.95 + 0.9 = 9.85 = phrase_start - head_margin
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from lucid import ops
from lucid import timeline as tl
from lucid import transcript as tx
from lucid.project import Project, ProjectError

needs_ffmpeg = pytest.mark.skipif(
    shutil.which("ffmpeg") is None, reason="ffmpeg is not installed"
)

CLIPS = {
    "vo": {
        "clip_id": "vo",
        "source": "/tmp/vo.wav",
        "duration": 6.0,
        "has_video": False,
        "has_audio": True,
    },
    "film": {
        "clip_id": "film",
        "source": "/tmp/film.mp4",
        "duration": 30.0,
        "has_video": True,
        "has_audio": True,
    },
}

RATE = 1000.0


def _words(clip_id: str, *specs: tuple[str, float, float]) -> tx.Transcript:
    return tx.Transcript(
        clip_id=clip_id,
        words=tuple(
            tx.Word(index=i, text=text, start=start, end=end)
            for i, (text, start, end) in enumerate(specs)
        ),
    )


@pytest.fixture
def project(tmp_path: Path) -> Project:
    project = Project.create(tmp_path / "proj")
    manifest = project.read_manifest()
    manifest["clips"] = list(CLIPS.values())
    project.write_manifest(manifest)
    tx.save(
        _words(
            "vo",
            ("the", 0.0, 0.3),
            ("first", 0.5, 0.9),
            ("twelve", 1.0, 1.4),
            ("minutes", 1.5, 1.9),
            ("of", 2.0, 2.2),
            ("scream", 5.0, 5.4),
        ),
        project.transcript_path("vo"),
    )
    tx.save(
        _words(
            "film",
            ("i", 10.0, 10.2),
            ("know", 10.2, 10.5),
            ("what", 10.5, 10.8),
            ("you", 10.8, 11.0),
            ("did", 11.0, 11.3),
        ),
        project.transcript_path("film"),
    )
    edit = tl.Edit([tl.Segment("vo", 0.0, 6.0)])
    tl.write(tl.to_otio(edit, {"vo": CLIPS["vo"]}, rate=RATE), project.timeline_path)
    return project


def _edit(project: Project) -> tl.Edit:
    return tl.read(project.timeline_path)


STORED_HOLD = {
    "clip_id": "vo",
    "gap_word_index": 3,
    "cue_word_index": 2,
    "asset": "film",
    "word_index_first": 0,
    "word_index_last": 4,
    "head_margin": ops.HOLD_HEAD_MARGIN,
    "tail_margin": ops.HOLD_TAIL_MARGIN,
    "under": ops.HOLD_UNDER,
    "fade_in": ops.HOLD_FADE_IN,
    "fade_out": ops.HOLD_FADE_OUT,
}


# -- _hold_plan's algebra ----------------------------------------------------


def test_the_algebra_lands_where_the_docstring_says(project: Project) -> None:
    plan = ops._hold_plan(project, _edit(project), RATE, STORED_HOLD)

    assert plan["elapsed"] == pytest.approx(0.9)
    assert plan["phrase_start"] == pytest.approx(10.0)
    assert plan["phrase_end"] == pytest.approx(11.3)
    assert plan["src_start"] == pytest.approx(8.95)
    assert plan["hold_length"] == pytest.approx(1.9)
    assert plan["play_at"] == pytest.approx(9.85)
    assert plan["play_at"] == pytest.approx(plan["phrase_start"] - STORED_HOLD["head_margin"])
    assert plan["hold_frames"] == round(1.9 * RATE)


def test_a_bigger_head_margin_moves_src_start_back_by_exactly_that_much(project: Project) -> None:
    baseline = ops._hold_plan(project, _edit(project), RATE, STORED_HOLD)
    grown = ops._hold_plan(project, _edit(project), RATE, {**STORED_HOLD, "head_margin": 1.0})

    assert grown["src_start"] == pytest.approx(baseline["src_start"] - (1.0 - STORED_HOLD["head_margin"]))


def test_src_start_exactly_zero_is_not_refused(project: Project) -> None:
    """The boundary is `< 0`, not `<= 0` — a hold landing exactly at the
    asset's own first frame is a real, valid placement."""
    # elapsed=0.9, phrase_start=10.0 -> head_margin=9.1 lands src_start at 0.0.
    plan = ops._hold_plan(project, _edit(project), RATE, {**STORED_HOLD, "head_margin": 9.1})
    assert plan["src_start"] == pytest.approx(0.0, abs=1e-9)


def test_src_start_just_negative_is_refused_with_the_measured_deficit(project: Project) -> None:
    with pytest.raises(ProjectError, match=r"0\.001s more"):
        ops._hold_plan(project, _edit(project), RATE, {**STORED_HOLD, "head_margin": 9.101})


def test_an_asset_too_short_is_refused_with_the_measured_shortfall(project: Project) -> None:
    manifest = project.read_manifest()
    for clip in manifest["clips"]:
        if clip["clip_id"] == "film":
            clip["duration"] = 10.5  # ends mid-phrase (phrase_end is 11.3)
    project.write_manifest(manifest)

    with pytest.raises(ProjectError, match="short by"):
        ops._hold_plan(project, _edit(project), RATE, STORED_HOLD)


def test_fades_that_do_not_fit_are_refused(project: Project) -> None:
    with pytest.raises(ProjectError, match="do not fit"):
        ops._hold_plan(
            project, _edit(project), RATE, {**STORED_HOLD, "fade_in": 1.0, "fade_out": 1.0}
        )


def test_an_orphaned_gap_word_refuses_by_name(project: Project) -> None:
    """Word-indexing keeps a cue valid across cuts; it does not keep the word
    on the timeline (CLAUDE.md) — a gap word a cut removed has no "after" a
    hold can open."""
    cut_edit = tl.Edit([tl.Segment("vo", 0.0, 1.2)])  # removes "minutes" (1.5-1.9) entirely
    with pytest.raises(ProjectError, match="not on the timeline"):
        ops._hold_plan(project, cut_edit, RATE, STORED_HOLD)


def test_a_missing_asset_transcript_refuses_by_name(project: Project) -> None:
    manifest = project.read_manifest()
    manifest["clips"].append(
        {"clip_id": "other", "source": "/tmp/other.mp4", "duration": 30.0, "has_video": True, "has_audio": True}
    )
    project.write_manifest(manifest)

    with pytest.raises(ProjectError, match="transcribe"):
        ops._hold_plan(project, _edit(project), RATE, {**STORED_HOLD, "asset": "other"})


# -- _stored_holds ------------------------------------------------------------


def test_stored_holds_is_empty_with_no_key(project: Project) -> None:
    assert ops._stored_holds(project) == []


def test_stored_holds_validates_the_shape(project: Project) -> None:
    manifest = project.read_manifest()
    manifest[ops.HOLDS_KEY] = "not a list"
    project.write_manifest(manifest)

    with pytest.raises(ProjectError, match="JSON array"):
        ops._stored_holds(project)


# -- hold_add: mix-only update path (no ffmpeg needed — nothing is spliced) --


def test_a_second_call_at_the_same_address_with_matching_fields_updates_in_place(
    project: Project,
) -> None:
    manifest = project.read_manifest()
    manifest[ops.HOLDS_KEY] = [dict(STORED_HOLD)]
    project.write_manifest(manifest)

    result = ops.hold_add(
        project.root,
        "vo",
        3,
        2,
        word_index_first=0,
        word_index_last=4,
        under=3.0,
    )

    assert result["resplice"] is False
    assert result["written"] is True
    stored = project.read_manifest()[ops.HOLDS_KEY]
    assert len(stored) == 1
    assert stored[0]["under"] == 3.0
    assert stored[0]["fade_in"] == STORED_HOLD["fade_in"]  # untouched field survives


def test_changing_word_index_first_on_an_already_spliced_hold_is_refused(project: Project) -> None:
    manifest = project.read_manifest()
    manifest[ops.HOLDS_KEY] = [dict(STORED_HOLD)]
    project.write_manifest(manifest)

    with pytest.raises(ProjectError, match="cannot change without re-splicing"):
        ops.hold_add(project.root, "vo", 3, 2, word_index_first=1, word_index_last=4)


def test_changing_cue_word_index_on_an_already_spliced_hold_is_refused(project: Project) -> None:
    manifest = project.read_manifest()
    manifest[ops.HOLDS_KEY] = [dict(STORED_HOLD)]
    manifest["cues"] = [{"clip_id": "vo", "word_index": 2, "asset": "film", "src_start": 8.95}]
    project.write_manifest(manifest)

    with pytest.raises(ProjectError, match="cannot change without re-splicing"):
        ops.hold_add(project.root, "vo", 3, 4, under=5.0)

    # Refused before anything is written: the stored hold and the cue it
    # owns are both untouched.
    after = project.read_manifest()
    assert after[ops.HOLDS_KEY] == [dict(STORED_HOLD)]
    assert after["cues"] == [{"clip_id": "vo", "word_index": 2, "asset": "film", "src_start": 8.95}]


def test_a_mix_only_update_plan_does_not_write(project: Project) -> None:
    manifest = project.read_manifest()
    manifest[ops.HOLDS_KEY] = [dict(STORED_HOLD)]
    project.write_manifest(manifest)
    before = project.manifest_path.read_text()

    result = ops.hold_add(project.root, "vo", 3, 2, under=5.0, plan=True)

    assert result["written"] is False
    assert project.manifest_path.read_text() == before


# -- hold_rm ------------------------------------------------------------------


def test_hold_rm_drops_the_record_and_its_owned_cue_but_not_the_segment(project: Project) -> None:
    manifest = project.read_manifest()
    manifest[ops.HOLDS_KEY] = [dict(STORED_HOLD)]
    manifest["cues"] = [{"clip_id": "vo", "word_index": 2, "asset": "film", "src_start": 8.95}]
    project.write_manifest(manifest)

    result = ops.hold_rm(project.root, "vo", 3)

    assert result["removed"]["gap_word_index"] == 3
    manifest_after = project.read_manifest()
    assert manifest_after[ops.HOLDS_KEY] == []
    assert manifest_after["cues"] == []


def test_hold_rm_refuses_an_address_with_no_hold(project: Project) -> None:
    with pytest.raises(ProjectError, match="no hold"):
        ops.hold_rm(project.root, "vo", 3)


# -- hold_ls --------------------------------------------------------------------


def test_hold_ls_reports_the_live_plan_alongside_the_stored_fields(project: Project) -> None:
    manifest = project.read_manifest()
    manifest[ops.HOLDS_KEY] = [dict(STORED_HOLD)]
    manifest["cues"] = [{"clip_id": "vo", "word_index": 2, "asset": "film", "src_start": 8.95}]
    project.write_manifest(manifest)

    result = ops.hold_ls(project.root)

    assert result["count"] == 1
    item = result["holds"][0]
    assert item["src_start"] == pytest.approx(8.95)
    assert item.get("hold_error") is None
    assert item["cue_drift"] is None


def test_hold_ls_reports_an_unresolvable_hold_inline_never_raising(project: Project) -> None:
    """One bad hold cannot break the list — `shots_error`'s policy."""
    manifest = project.read_manifest()
    manifest[ops.HOLDS_KEY] = [dict(STORED_HOLD)]
    project.write_manifest(manifest)
    # Cut the gap word entirely, orphaning this hold.
    cut_edit = tl.Edit([tl.Segment("vo", 0.0, 1.2)])
    ops._save_edit(project, cut_edit)

    result = ops.hold_ls(project.root)

    assert result["count"] == 1
    assert result["holds"][0]["hold_error"] is not None
    assert result["holds"][0]["cue_drift"] is None


def test_hold_ls_flags_cue_drift_when_the_owned_cue_was_hand_edited(project: Project) -> None:
    manifest = project.read_manifest()
    manifest[ops.HOLDS_KEY] = [dict(STORED_HOLD)]
    # Owned cue exists but with a stale src_start — a hand `cue_rm`/`cue_add`
    # by an unrelated caller, the retro's own "two lists drift apart" shape.
    manifest["cues"] = [{"clip_id": "vo", "word_index": 2, "asset": "film", "src_start": 0.0}]
    project.write_manifest(manifest)

    result = ops.hold_ls(project.root)

    assert result["holds"][0]["cue_drift"] is not None
    assert "8.95" in result["holds"][0]["cue_drift"] or "src_start" in result["holds"][0]["cue_drift"]


def test_hold_ls_flags_a_missing_owned_cue(project: Project) -> None:
    manifest = project.read_manifest()
    manifest[ops.HOLDS_KEY] = [dict(STORED_HOLD)]
    project.write_manifest(manifest)

    result = ops.hold_ls(project.root)

    assert result["holds"][0]["cue_drift"] == "the owned cue no longer exists"


# -- _hold_gain_db --------------------------------------------------------------


def test_hold_gain_db_lands_the_hold_under_the_vo_by_exactly_under() -> None:
    assert ops._hold_gain_db(vo_lufs=-16.0, hold_lufs=-20.0, under=0.0) == pytest.approx(4.0)
    assert ops._hold_gain_db(vo_lufs=-16.0, hold_lufs=-20.0, under=3.0) == pytest.approx(1.0)


# -- _gate_music_lane: the bed goes OUT, not ducked --------------------------


@needs_ffmpeg
def test_gate_music_lane_is_a_no_op_with_no_hold_spans(project: Project) -> None:
    from lucid import mlt

    lane = [mlt.Entry("/tmp/bed.wav", 0, 100, has_video=False)]
    assert ops._gate_music_lane(project, lane, "/tmp/bed.wav", [], 30.0) is lane


@needs_ffmpeg
def test_gate_music_lane_splits_the_bed_entry_around_one_span(project: Project) -> None:
    from lucid import mlt

    lane = [mlt.Entry("/tmp/bed.wav", 0, 100, has_video=False, fade_in_frames=5, fade_out_frames=5)]
    gated = ops._gate_music_lane(project, lane, "/tmp/bed.wav", [(40, 60)], 30.0)

    # Same total frame count, always — `mlt.document`'s own coverage check
    # depends on it.
    assert sum(e.frames for e in gated) == 100
    assert [e.frames for e in gated] == [40, 20, 40]
    before, gate, after = gated
    assert before.resource == "/tmp/bed.wav" and after.resource == "/tmp/bed.wav"
    assert gate.resource != "/tmp/bed.wav"  # a real silent file, never the bed's own
    assert not gate.has_video
    # The bed's own configured fade survives at its real edge...
    assert before.fade_in_frames == 5
    # ...and a gate ramp appears at the cut into and out of the gate.
    assert before.fade_out_frames == ops.HOLD_GATE_RAMP * 30.0
    assert after.fade_in_frames == ops.HOLD_GATE_RAMP * 30.0
    assert after.fade_out_frames == 5
    # Source position continues advancing across the gate — the bed is
    # muted, not paused, so it resumes where its own timeline would be.
    assert before.src_in == 0
    assert after.src_in == 60


@needs_ffmpeg
def test_gate_music_lane_leaves_a_span_outside_the_bed_entry_untouched(project: Project) -> None:
    from lucid import mlt

    lane = [mlt.Entry("/tmp/bed.wav", 0, 100, has_video=False)]
    gated = ops._gate_music_lane(project, lane, "/tmp/bed.wav", [(500, 600)], 30.0)

    assert gated == lane


# -- _is_layered's seventh trigger -------------------------------------------


def test_is_layered_true_on_holds_key_alone_even_with_one_clip_id(project: Project) -> None:
    """Belt-and-suspenders: a real `hold_add` always splices a second
    `clip_id` in, so the multi-clip check above already catches every hold
    that has actually been spliced — but `HOLDS_KEY` is checked as its own
    trigger too, on the same "never lag the writer" discipline `MUSIC_KEY`
    and `HEAD_KEY` follow, rather than trusting a path that happens to cover
    this case today. Constructed here with the edit still single-clip
    (bypassing a real splice) so the manifest-key check is what is actually
    being exercised, not the multi-clip one riding along for free."""
    manifest = project.read_manifest()
    manifest[ops.HOLDS_KEY] = [dict(STORED_HOLD)]
    project.write_manifest(manifest)
    single_clip_edit = tl.Edit([tl.Segment("vo", 0.0, 6.0)])

    assert ops._is_layered(project, single_clip_edit) is True


def test_is_layered_false_with_no_holds_and_one_clip_id(project: Project) -> None:
    assert ops._is_layered(project, _edit(project)) is False


# -- reel drops holds ---------------------------------------------------------


def test_reel_reports_holds_dropped_and_the_derived_manifest_has_none(project: Project) -> None:
    manifest = project.read_manifest()
    manifest[ops.HOLDS_KEY] = [dict(STORED_HOLD)]
    project.write_manifest(manifest)

    planned = ops.reel(project.root, project.root.parent / "reel-plan", start=0.0, end=6.0, plan=True)
    assert planned["holds_dropped"] == [dict(STORED_HOLD)]
