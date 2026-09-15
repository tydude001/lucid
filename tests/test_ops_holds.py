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
from typing import Any

import pytest

from proofcut import finish, mlt, ops
from proofcut import timeline as tl
from proofcut import transcript as tx
from proofcut.project import Project, ProjectError

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


@needs_ffmpeg
def test_one_undo_takes_back_a_whole_spliced_hold(project: Project) -> None:
    """A hold is one decision, so it is one undo press — the gap and the
    record together. Walking back only the manifest half leaves a spliced
    silence with no hold behind it: a gap in the VO that plays nothing, which
    reads as a pause in the read, not as a missing hold.
    """
    ops.hold_add(project.root, "vo", 3, 2, asset="film", word_index_first=0, word_index_last=4)
    assert len(_edit(project).segments) > 1
    assert project.read_manifest()[ops.HOLDS_KEY]

    ops.undo(project.root)

    assert len(_edit(project).segments) == 1
    assert not project.read_manifest().get(ops.HOLDS_KEY)


@needs_ffmpeg
def test_a_hold_refused_by_the_shot_plan_registers_nothing_and_costs_no_undo(project: Project) -> None:
    """The splice's shot-plan check runs on the edit *with* the gap in it, so
    it can refuse a hold whose own algebra fits: here the hold needs film
    8.95–10.85 of a 27 s asset, but an earlier cue's shot of that asset from
    20.0 runs the whole 6.0 s timeline — 26.0, fits — and the gap stretches it
    to 7.9 s, past the asset's end. The refusal used to come after the silence was
    registered — a manifest write, and so an undo snapshot — leaving an
    orphaned clip and an undo press that changes nothing. Found on the
    Lambs/Longlegs native rebuild, where the first undo after a refused hold
    walked back no edit at all.
    """
    manifest = project.read_manifest()
    for clip in manifest["clips"]:
        if clip["clip_id"] == "film":
            clip["duration"] = 27.0
            clip["source"] = str(project.root / "film.mp4")  # the shot plan resolves the file; its bytes are never read
    (project.root / "film.mp4").touch()
    manifest["cues"] = [{"clip_id": "vo", "word_index": 0, "asset": "film", "src_start": 20.0}]
    project.write_manifest(manifest)
    clips_before = [c["clip_id"] for c in project.read_manifest()["clips"]]
    depth_before = len(Project.open(project.root).snapshots())

    with pytest.raises(mlt.MLTError, match="past the asset's 27.0s"):
        ops.hold_add(project.root, "vo", 3, 2, asset="film", word_index_first=0, word_index_last=4)

    assert [c["clip_id"] for c in project.read_manifest()["clips"]] == clips_before
    assert len(Project.open(project.root).snapshots()) == depth_before
    assert len(_edit(project).segments) == 1


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


# -- hold_check ---------------------------------------------------------------
#
# `_transcribe_span` and `finish.hold_seams` both shell out (whisper, ffmpeg
# decode) — stood in here, `test_ops_finish_report.py`'s own
# "monkeypatch the real op to lie" discipline, so what is under test is
# `hold_check`'s own composition (cue_drift folded into faults alongside a
# seam fault), not the transcription/decode machinery underneath it.


def _seam_row(name: str, t: float, *, fault: str | None = None) -> dict[str, Any]:
    return {
        "name": name,
        "time": round(t, 3),
        "pre": -40.0,
        "post": -40.0,
        "peak_pre": -40.0,
        "floor_post": -40.0,
        "fault": fault,
    }


def test_hold_check_folds_cue_drift_into_faults(
    project: Project, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    manifest = project.read_manifest()
    manifest[ops.HOLDS_KEY] = [dict(STORED_HOLD)]
    # Owned cue exists but with a stale src_start — an unrelated hand
    # cue_rm/cue_add, the retro's own "two lists drift apart" shape.
    manifest["cues"] = [{"clip_id": "vo", "word_index": 2, "asset": "film", "src_start": 0.0}]
    project.write_manifest(manifest)

    render = tmp_path / "render.mp4"
    render.write_bytes(b"not a real render, just needs to exist")

    monkeypatch.setattr(ops, "_transcribe_span", lambda *a, **k: "i know what you did")
    monkeypatch.setattr(
        finish,
        "hold_seams",
        lambda media, marks, **k: [_seam_row(name, t) for name, t in marks],
    )

    result = ops.hold_check(project.root, render)

    assert result["count"] == 1
    item = result["holds"][0]
    assert item["cue_drift"] is not None
    assert "src_start" in item["cue_drift"]
    assert all(seam["fault"] is None for seam in item["seams"])
    # No seam fault fired — the one fault counted is the cue drift.
    assert result["faults"] == 1


def test_hold_check_reports_no_faults_when_the_owned_cue_agrees(
    project: Project, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    manifest = project.read_manifest()
    manifest[ops.HOLDS_KEY] = [dict(STORED_HOLD)]
    manifest["cues"] = [{"clip_id": "vo", "word_index": 2, "asset": "film", "src_start": 8.95}]
    project.write_manifest(manifest)

    render = tmp_path / "render.mp4"
    render.write_bytes(b"not a real render, just needs to exist")

    monkeypatch.setattr(ops, "_transcribe_span", lambda *a, **k: "i know what you did")
    monkeypatch.setattr(
        finish,
        "hold_seams",
        lambda media, marks, **k: [_seam_row(name, t) for name, t in marks],
    )

    result = ops.hold_check(project.root, render)

    assert result["holds"][0]["cue_drift"] is None
    assert result["faults"] == 0


def test_hold_check_counts_a_hold_that_plays_the_wrong_stretch_of_its_line(
    project: Project, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`hold_check` printed `phrase` beside `heard` and compared neither: a hold
    playing the seconds before its line — every hold on the Lambs/Longlegs
    native rebuild — counted only its seam faults. A line whose end is not
    heard is a fault of its own."""
    manifest = project.read_manifest()
    manifest[ops.HOLDS_KEY] = [dict(STORED_HOLD)]
    manifest["cues"] = [{"clip_id": "vo", "word_index": 2, "asset": "film", "src_start": 8.95}]
    project.write_manifest(manifest)
    render = tmp_path / "render.mp4"
    render.write_bytes(b"not a real render, just needs to exist")
    monkeypatch.setattr(ops, "_transcribe_span", lambda *a, **k: "something before i know what")
    monkeypatch.setattr(
        finish, "hold_seams", lambda media, marks, **k: [_seam_row(name, t) for name, t in marks]
    )

    result = ops.hold_check(project.root, render)

    assert result["holds"][0]["line_edges"] == {"start": True, "end": False}
    assert result["faults"] == 1


def test_line_edges_separate_the_measured_right_and_wrong_holds() -> None:
    """Pinned on real whisper output off Lambs/Longlegs v10 (right) and its
    native rebuild before the `play_at` fix (wrong), both halves of the
    measurement `_line_edges_heard`'s docstring states."""
    miggs = "He hissed at you. What did he say? He said, I can smell your cunt."
    assert all(ops._line_edges_heard(miggs, "He hissed at you. What did he say? He said, I can smell your cunt.").values())
    assert not ops._line_edges_heard(
        miggs, "What did Migs say to you? Multiple Migs in the next cell. He hissed at you. What did he say?"
    )["end"]
    # A respelt first word is still a heard start: "Longlegs" came back "Long Legs".
    witch = "Longlegs is just a man, Harker. Not a witch doctor."
    assert all(ops._line_edges_heard(witch, "Long Legs is just a man, Hawker, not a witch doctor.").values())
    # 0.94 of the words, and still the wrong placement — the end is what is missing.
    point = (
        "When I told the sheriff we shouldn't talk in front of a woman, that really burned you, didn't it? "
        "It was just smoke, Starling. I had to get rid of him. It matters, Mr. Crawford. "
        "Cops look at you to see how to act. It matters. Point taken."
    )
    early = (
        "I'm Starling When I told that sheriff We shouldn't talk in front of a woman That really burned you, "
        "didn't it? It was just smoke, Starling I had to get rid of him It matters, Mr. Crawford "
        "Cops look at you to see how to act It matters"
    )
    assert ops._line_edges_heard(point, early) == {"start": True, "end": False}


@needs_ffmpeg
def test_transcribe_span_reads_words_nested_under_whisper_segments(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """openai-whisper's JSON has no top-level `words`; they are under
    `segments[].words[]`, and `_transcribe_span` read only the top level — so
    every real span came back "" and `hold_check` never heard a hold. The fakes
    in the tests above replace `_transcribe_span` whole, which is how it went
    unnoticed; this one fakes only whisper, in whisper's own shape."""
    import subprocess

    media = tmp_path / "span.wav"
    subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono",
         "-t", "2", str(media)],
        check=True, capture_output=True,
    )  # fmt: skip
    whisper_shaped = {
        "text": " He hissed at you.",
        "segments": [{"text": " He hissed at you.", "words": [
            {"word": " He", "start": 0.0, "end": 0.5},
            {"word": " hissed", "start": 0.5, "end": 1.1},
            {"word": " at", "start": 1.1, "end": 1.2},
            {"word": " you.", "start": 1.2, "end": 1.5},
        ]}],
        "language": "en",
    }  # fmt: skip
    monkeypatch.setattr(ops.asr, "transcribe", lambda *a, **k: whisper_shaped)
    assert ops._transcribe_span(media, 0.0, 2.0) == "He hissed at you."

    monkeypatch.setattr(ops.asr, "transcribe", lambda *a, **k: {"text": "", "segments": [], "language": "en"})
    assert ops._transcribe_span(media, 0.0, 2.0) == ""


# -- _hold_gain_db --------------------------------------------------------------


def test_hold_gain_db_lands_the_hold_under_the_vo_by_exactly_under() -> None:
    assert ops._hold_gain_db(vo_lufs=-16.0, hold_lufs=-20.0, under=0.0) == pytest.approx(4.0)
    assert ops._hold_gain_db(vo_lufs=-16.0, hold_lufs=-20.0, under=3.0) == pytest.approx(1.0)


# -- _gate_music_lane: the bed goes OUT, not ducked --------------------------


@needs_ffmpeg
def test_gate_music_lane_is_a_no_op_with_no_hold_spans(project: Project) -> None:
    from proofcut import mlt

    lane = [mlt.Entry("/tmp/bed.wav", 0, 100, has_video=False)]
    assert ops._gate_music_lane(project, lane, "/tmp/bed.wav", [], 30.0) is lane


@needs_ffmpeg
def test_gate_music_lane_splits_the_bed_entry_around_one_span(project: Project) -> None:
    from proofcut import mlt

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
def test_a_hold_that_cuts_a_piece_off_inside_its_crossfade_shortens_the_fade(project: Project) -> None:
    """The Lambs/Longlegs native rebuild's render refused here: a hold opened
    2.5 s after one bed piece started crossfading in, leaving a 60-frame
    segment carrying the 60-frame crossfade *and* the gate's ramp out. The
    hold is what ends that segment, so its ramp takes the fade over — the
    fade at the real edge shrinks to what the segment can hold, rather than
    the whole bed being unbuildable next to a hold. Both edges keep their
    configured fade whenever it fits."""
    from proofcut import mlt

    ramp = round(ops.HOLD_GATE_RAMP * 24.0)
    lane = [mlt.Entry("/tmp/bed.wav", 0, 300, has_video=False, fade_in_frames=60, crossfade_in=True)]
    gated = ops._gate_music_lane(project, lane, "/tmp/bed.wav", [(60, 160)], 24.0)

    before = gated[0]
    assert before.frames == 60
    assert before.fade_in_frames + before.fade_out_frames <= before.frames - 1
    assert before.fade_out_frames == ramp
    assert before.crossfade_in is True
    # And the same document now builds: every entry's fades fit.
    for entry in gated:
        assert entry.fade_in_frames + entry.fade_out_frames <= max(entry.frames - 1, 0)


@needs_ffmpeg
def test_gate_music_lane_leaves_a_span_outside_the_bed_entry_untouched(project: Project) -> None:
    from proofcut import mlt

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



# -- film audio under the VO (docs/plans/NATIVE.md § A2) ------------------------


def _cued(project: Project, *, src_start: float = 8.0) -> None:
    (project.root / "film.mp4").touch()
    manifest = project.read_manifest()
    for clip in manifest["clips"]:
        if clip["clip_id"] == "film":
            clip["source"] = str(project.root / "film.mp4")
    manifest["cues"] = [{"clip_id": "vo", "word_index": 2, "asset": "film", "src_start": src_start}]
    project.write_manifest(manifest)


def test_under_vo_reads_the_film_from_where_its_shot_has_got_to(project: Project) -> None:
    """Cued from src 8.0 — and the first shot is forced to frame 0
    (`build_shots`), so the film is showing from the open. A span starting at
    "minutes" (1.5 s) reads it from 9.5: the picture's own playhead, never a
    stored in-point, and never the cue's 8.0."""
    _cued(project)
    result = ops.hold_under(project.root, "vo", "film", word_index_start=3, word_index_end=4, plan=True)

    assert result["play_at"] == pytest.approx(9.5)
    assert result["timeline_start"] == pytest.approx(1.5)
    assert result["timeline_end"] == pytest.approx(2.2)
    assert result["start_word"]["text"] == "minutes"
    assert result["written"] is False


def test_under_vo_refuses_an_asset_that_is_not_on_screen(project: Project) -> None:
    with pytest.raises(ProjectError, match="not on screen"):
        ops.hold_under(project.root, "vo", "film", word_index_start=3, word_index_end=4)


def test_under_vo_is_stored_by_address_and_replaced_not_duplicated(project: Project) -> None:
    _cued(project)
    ops.hold_under(project.root, "vo", "film", word_index_start=3, word_index_end=4)
    ops.hold_under(project.root, "vo", "film", word_index_start=3, word_index_end=4, under=9.0)

    stored = project.read_manifest()[ops.UNDER_VO_KEY]
    assert len(stored) == 1 and stored[0]["under"] == 9.0
    listed = ops.hold_ls(project.root)["under_vo"]
    assert listed[0]["play_at"] == pytest.approx(9.5)

    ops.hold_under_rm(project.root, "vo", 3)
    assert ops.UNDER_VO_KEY not in project.read_manifest()


def test_under_vo_alone_makes_the_project_layered_and_blocks_clip_rm(project: Project) -> None:
    _cued(project)
    ops.hold_under(project.root, "vo", "film", word_index_start=3, word_index_end=4)
    manifest = project.read_manifest()
    manifest["cues"] = []
    project.write_manifest(manifest)

    assert ops._is_layered(project, _edit(project)) is True
    with pytest.raises(ProjectError, match="under the VO"):
        ops.clip_rm(project.root, "film")
