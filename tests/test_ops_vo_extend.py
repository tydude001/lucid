"""`vo_extend` — the one item authorized to bend `Edit`'s subtractive invariant.

PLAN.md § `vo_extend` — the design note settles the shape this pins down: a
real generated-silence clip spliced in via `Edit.insert` (never a clip_id
widened past its registered duration), word indices upstream of the hold
untouched, `restore`'s existing interleaved-segments check and `_is_layered`'s
existing clip-count test both catching the consequence for free, and the one
new obligation — reporting what picture (if any) now covers the span the hold
opened, because `build_shots` would otherwise auto-extend stale picture across
it with every other check staying clean.

Built by hand rather than through `import_media`, following
`test_ops_tail.py`/`test_ops_cues.py`: no ffprobe is needed to have a project
with a timeline and a transcript. `vo_extend` itself does call `import_media`
(for the real, non-plan path) — over a real silence WAV `picture.render_silence`
renders via ffmpeg, no display required.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from lucid import ops
from lucid import timeline as tl
from lucid import transcript as tx
from lucid.project import Project

CLIP = {
    "clip_id": "vo",
    "source": "/tmp/vo.wav",
    "duration": 5.0,
    "has_video": False,
    "has_audio": True,
}


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
    manifest["clips"] = [CLIP]
    project.write_manifest(manifest)

    tx.save(
        _words(
            "vo",
            ("one", 0.0, 0.5),
            ("two", 1.0, 1.5),
            ("three", 2.0, 2.5),
            ("four", 3.0, 3.5),
            ("five", 4.0, 4.5),
        ),
        project.transcript_path("vo"),
    )

    edit = tl.Edit([tl.Segment("vo", 0.0, 5.0)])
    tl.write(tl.to_otio(edit, {CLIP["clip_id"]: CLIP}, rate=1000.0), project.timeline_path)
    return project


# -- the splice --------------------------------------------------------------


def test_extend_inserts_a_hold_right_after_the_named_word(project: Project) -> None:
    result = ops.vo_extend(project.root, "vo", 2, 3.0)

    assert result["text"] == "three"
    assert result["timeline_start"] == pytest.approx(2.5)
    assert result["timeline_end"] == pytest.approx(5.5)
    assert result["duration_before"] == pytest.approx(5.0)
    assert result["duration_after"] == pytest.approx(8.0)
    assert result["written"] is True
    assert [w["text"] for w in result["context_before"]] == ["one", "two"]
    assert [w["text"] for w in result["context_after"]] == ["four", "five"]

    edit = ops._load_edit(project)
    spans = [(s.clip_id, s.start, s.end) for s in edit.segments]
    assert spans == [
        ("vo", 0.0, 2.5),
        (result["hold_clip_id"], 0.0, 3.0),
        ("vo", 2.5, 5.0),
    ]
    assert edit.duration == pytest.approx(8.0)


def test_the_hold_clip_is_registered_with_a_real_source_file(project: Project) -> None:
    result = ops.vo_extend(project.root, "vo", 0, 1.5)
    clips = project.read_manifest()["clips"]
    hold = next(c for c in clips if c["clip_id"] == result["hold_clip_id"])
    assert Path(hold["source"]).is_file()
    assert hold["has_video"] is False
    # render_silence pads half a second past what was asked, so the file
    # outlasts the 1.5s the Segment actually reads.
    assert hold["duration"] >= 1.5


def test_a_second_call_at_the_same_seconds_reuses_the_registered_clip(project: Project) -> None:
    first = ops.vo_extend(project.root, "vo", 0, 2.0)
    before = len(project.read_manifest()["clips"])
    second = ops.vo_extend(project.root, "vo", 4, 2.0)

    assert second["hold_clip_id"] == first["hold_clip_id"]
    assert len(project.read_manifest()["clips"]) == before


def test_words_after_the_hold_reposition_for_free(project: Project) -> None:
    """§ `vo_extend` — the design note: word indices are safe under growth —
    every cue after the insertion repositions because `timeline_span` walks
    the (now longer) segment list, not because anything renumbers a word."""
    ops.vo_extend(project.root, "vo", 1, 2.0)  # after "two" (ends 1.5)
    edit = ops._load_edit(project)
    # "five" (4.0-4.5) used to resolve to timeline 4.0-4.5; it now sits 2.0s
    # later, past the hold.
    assert edit.timeline_span("vo", 4.0, 4.5) == pytest.approx((6.0, 6.5))


# -- plan ----------------------------------------------------------------


def test_plan_writes_neither_the_manifest_nor_the_timeline(project: Project) -> None:
    manifest_before = project.manifest_path.read_text()
    timeline_before = project.timeline_path.read_text()

    result = ops.vo_extend(project.root, "vo", 2, 3.0, plan=True)

    assert result["written"] is False
    assert result["plan"] is True
    assert result["duration_after"] == pytest.approx(8.0)
    assert project.manifest_path.read_text() == manifest_before
    assert project.timeline_path.read_text() == timeline_before


def test_plan_and_a_real_call_report_the_same_shape(project: Project) -> None:
    planned = ops.vo_extend(project.root, "vo", 2, 3.0, plan=True)
    real = ops.vo_extend(project.root, "vo", 2, 3.0)

    assert planned["timeline_start"] == real["timeline_start"]
    assert planned["timeline_end"] == real["timeline_end"]
    assert planned["covered_by"] == real["covered_by"]
    # The one field a plan cannot promise: nothing was registered to give it.
    assert planned["hold_clip_id"] != real["hold_clip_id"]


# -- covered_by: the silent-success case this item exists to catch ----------


def test_covered_by_is_empty_with_no_cue_table(project: Project) -> None:
    result = ops.vo_extend(project.root, "vo", 2, 3.0)
    assert result["covered_by"] == []


def test_covered_by_names_the_shot_that_would_freeze_across_the_hold(project: Project) -> None:
    project.cards_dir.joinpath("cold-open.png").write_bytes(b"\x89PNG")
    ops.cue_add(project.root, "vo", 0, "card:cold-open")
    result = ops.vo_extend(project.root, "vo", 2, 3.0)

    assert len(result["covered_by"]) == 1
    covering = result["covered_by"][0]
    assert covering["asset"] == "card:cold-open"
    assert covering["start"] <= result["timeline_start"]
    assert covering["start"] + covering["duration"] >= result["timeline_end"]


# -- consequences already true of the machinery ------------------------------


def test_the_project_becomes_layered(project: Project) -> None:
    edit = ops._load_edit(project)
    assert ops._is_layered(project, edit) is False

    ops.vo_extend(project.root, "vo", 2, 3.0)
    edit = ops._load_edit(project)
    assert ops._is_layered(project, edit) is True


def test_restore_is_refused_once_it_would_cross_the_hold(project: Project) -> None:
    edit = ops._load_edit(project)
    edit.remove("vo", 1.5, 2.0)
    ops._save_edit(project, edit)

    ops.vo_extend(project.root, "vo", 2, 3.0)  # after "three", ends 2.5

    with pytest.raises(tl.TimelineError, match="not contiguous"):
        ops.restore(project.root, "vo", [[1, 2]])


# -- refusals ---------------------------------------------------------------


def test_refuses_nonpositive_seconds(project: Project) -> None:
    with pytest.raises(tl.TimelineError, match="positive"):
        ops.vo_extend(project.root, "vo", 2, 0.0)
    with pytest.raises(tl.TimelineError, match="positive"):
        ops.vo_extend(project.root, "vo", 2, -1.0)


def test_refuses_a_word_that_is_already_cut(project: Project) -> None:
    edit = ops._load_edit(project)
    # Removal is half-open [start, end) — this has to reach past 2.5 itself
    # (word 2's own end, where vo_extend would open the gap) or that instant
    # survives as the start of the next segment and is not cut at all.
    edit.remove("vo", 1.8, 2.6)  # cuts "three" (2.0-2.5) entirely
    ops._save_edit(project, edit)

    with pytest.raises(tl.TimelineError, match="not on the timeline"):
        ops.vo_extend(project.root, "vo", 2, 3.0)


# -- phrase addressing (feature: phrase-addressed cues) ----------------------
#
# `word_index` names "the last word before the gap" — edge="last" — so a
# phrase spanning two-or-more words is the only fixture that can catch an
# accidental edge="first" (CLAUDE.md: a single-word phrase cannot).


def test_phrase_binds_to_its_last_word(project: Project) -> None:
    """"two three" must open the gap after "three" (word 2), matching
    `test_extend_inserts_a_hold_right_after_the_named_word`'s word_index=2."""
    result = ops.vo_extend(project.root, "vo", phrase="two three", seconds=3.0)

    assert result["text"] == "three"
    assert result["timeline_start"] == pytest.approx(2.5)
    assert result["timeline_end"] == pytest.approx(5.5)


def test_word_index_and_phrase_together_are_refused(project: Project) -> None:
    with pytest.raises(tx.TranscriptError, match="not both"):
        ops.vo_extend(project.root, "vo", 2, 3.0, phrase="two three")


def test_neither_word_index_nor_phrase_is_refused(project: Project) -> None:
    with pytest.raises(tx.TranscriptError, match="not neither"):
        ops.vo_extend(project.root, "vo", seconds=3.0)


def test_seconds_is_required_even_when_addressed_by_phrase(project: Project) -> None:
    with pytest.raises(tl.TimelineError, match="seconds"):
        ops.vo_extend(project.root, "vo", phrase="two three")
