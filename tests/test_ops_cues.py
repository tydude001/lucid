"""`cue_add`/`cue_rm`/`cue_ls` — step 1 of the layered timeline.

The cue table lives in the manifest, source-addressed by `(clip_id,
word_index, asset)` and nothing in timeline coordinates (PLAN.md § The
layered timeline). No `project.otio` is needed for any of this — a clip and
its transcript are enough — so these tests skip seeding a timeline entirely,
following `test_ops_speech_overlap.py`'s pattern for building a project by
hand rather than through `import_media` (no ffprobe needed either).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from lucid import ops
from lucid import transcript as tx
from lucid.media import MediaError
from lucid.project import Project

CLIPS = {
    "vo": {
        "clip_id": "vo",
        "source": "/tmp/vo.wav",
        "duration": 5.0,
        "has_video": False,
        "has_audio": True,
    },
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
            ("scream", 2.3, 2.7),
        ),
        project.transcript_path("vo"),
    )
    return project


def test_cue_add_returns_the_resolved_word_and_its_neighbours(project: Project) -> None:
    added = ops.cue_add(project.root, "vo", 2, "cold-open")

    assert added["clip_id"] == "vo"
    assert added["asset"] == "cold-open"
    assert added["word_index"] == 2
    assert added["text"] == "twelve"
    assert added["cues"] == 1
    assert [w["text"] for w in added["context_before"]] == ["the", "first"]
    assert [w["text"] for w in added["context_after"]] == ["minutes", "of", "scream"]


def test_cue_add_persists_to_the_manifest(project: Project) -> None:
    ops.cue_add(project.root, "vo", 0, "cold-open")
    ops.cue_add(project.root, "vo", 3, "card:receipt")

    cues = project.read_manifest()["cues"]
    assert cues == [
        {"clip_id": "vo", "word_index": 0, "asset": "cold-open"},
        {"clip_id": "vo", "word_index": 3, "asset": "card:receipt"},
    ]


def test_cue_add_refuses_a_second_cue_at_the_same_word(project: Project) -> None:
    ops.cue_add(project.root, "vo", 2, "cold-open")

    with pytest.raises(tx.TranscriptError, match="already has a cue"):
        ops.cue_add(project.root, "vo", 2, "s4-reveal")


def test_cue_add_rejects_an_out_of_range_word(project: Project) -> None:
    with pytest.raises(tx.TranscriptError):
        ops.cue_add(project.root, "vo", 99, "cold-open")


def test_cue_add_rejects_an_unknown_clip(project: Project) -> None:
    with pytest.raises(MediaError):
        ops.cue_add(project.root, "nope", 0, "cold-open")


def test_cue_rm_removes_the_matching_cue_and_echoes_it(project: Project) -> None:
    ops.cue_add(project.root, "vo", 2, "cold-open")
    ops.cue_add(project.root, "vo", 3, "s4-reveal")

    removed = ops.cue_rm(project.root, "vo", 2)

    assert removed["asset"] == "cold-open"
    assert removed["text"] == "twelve"
    assert removed["cues"] == 1
    assert project.read_manifest()["cues"] == [
        {"clip_id": "vo", "word_index": 3, "asset": "s4-reveal"}
    ]


def test_cue_rm_refuses_a_word_with_no_cue(project: Project) -> None:
    with pytest.raises(tx.TranscriptError, match="no cue"):
        ops.cue_rm(project.root, "vo", 5)


def test_cue_ls_is_read_only_and_sorted_by_word_index(project: Project) -> None:
    ops.cue_add(project.root, "vo", 3, "s4-reveal")
    ops.cue_add(project.root, "vo", 0, "cold-open")

    listed = ops.cue_ls(project.root)

    assert listed["count"] == 2
    assert [c["word_index"] for c in listed["cues"]] == [0, 3]
    assert [c["asset"] for c in listed["cues"]] == ["cold-open", "s4-reveal"]
    assert listed["cues"][0]["text"] == "the"
    # Read-only: nothing was written beyond the two adds above.
    assert len(project.read_manifest()["cues"]) == 2


def test_cue_ls_filters_by_clip_id(project: Project) -> None:
    manifest = project.read_manifest()
    manifest["clips"].append(
        {"clip_id": "vo2", "source": "/tmp/vo2.wav", "duration": 2.0, "has_video": False, "has_audio": True}
    )
    project.write_manifest(manifest)
    tx.save(_words("vo2", ("hi", 0.0, 0.3)), project.transcript_path("vo2"))

    ops.cue_add(project.root, "vo", 0, "cold-open")
    ops.cue_add(project.root, "vo2", 0, "s4-reveal")

    listed = ops.cue_ls(project.root, clip_id="vo2")
    assert [c["clip_id"] for c in listed["cues"]] == ["vo2"]


def test_cue_ls_on_an_empty_table_reports_nothing(project: Project) -> None:
    listed = ops.cue_ls(project.root)
    assert listed == {"cues": [], "count": 0}


# -- the pinned in-point (PLAN.md § B-roll by description) -----------------


def test_cue_add_stores_a_pinned_in_point_and_echoes_it(project: Project) -> None:
    added = ops.cue_add(project.root, "vo", 2, "cold-open", src_start=12.5)

    assert added["src_start"] == 12.5
    assert project.read_manifest()["cues"] == [
        {"clip_id": "vo", "word_index": 2, "asset": "cold-open", "src_start": 12.5}
    ]


def test_an_unpinned_cue_is_written_exactly_as_it_was_before_the_pin_existed(
    project: Project,
) -> None:
    """The migration rests on this: a v2 cue means in v3 what it meant in v2,
    so `_v2_to_v3` rewrites no cue. A `"src_start": None` written into the
    table would be a fourth key those manifests do not have."""
    ops.cue_add(project.root, "vo", 2, "cold-open")

    assert project.read_manifest()["cues"] == [
        {"clip_id": "vo", "word_index": 2, "asset": "cold-open"}
    ]


def test_cue_add_refuses_an_in_point_before_the_start_of_the_asset(project: Project) -> None:
    with pytest.raises(tx.TranscriptError, match="before the start of"):
        ops.cue_add(project.root, "vo", 2, "cold-open", src_start=-0.5)

    assert project.read_manifest().get("cues", []) == []


def test_cue_add_refuses_an_in_point_on_a_card(project: Project) -> None:
    """A still is held, not played, so a pin on one could only ever be
    ignored — and a silently ignored in-point is a cue that says it shows a
    moment and does not."""
    with pytest.raises(tx.TranscriptError, match="no playhead to move"):
        ops.cue_add(project.root, "vo", 2, "card:receipt", src_start=3.0)

    assert project.read_manifest().get("cues", []) == []


def test_cue_add_does_not_check_the_pin_against_the_assets_length(project: Project) -> None:
    """`asset` is opaque here — resolving it needs media on disk and belongs
    to the projection. A pin 90s into a 5s clip is accepted and refused by
    `build_shots`/`plan_picture`, which is where the duration is known."""
    added = ops.cue_add(project.root, "vo", 2, "no-such-clip", src_start=90.0)

    assert added["src_start"] == 90.0


def test_cue_ls_and_cue_rm_report_the_pin(project: Project) -> None:
    ops.cue_add(project.root, "vo", 0, "cold-open", src_start=4.25)
    ops.cue_add(project.root, "vo", 3, "s4-reveal")

    listed = ops.cue_ls(project.root)
    assert [c["src_start"] for c in listed["cues"]] == [4.25, None]

    removed = ops.cue_rm(project.root, "vo", 0)
    assert removed["src_start"] == 4.25


# -- phrase addressing (feature: phrase-addressed cues) ----------------------
#
# The fixture transcript is "the first twelve minutes of scream" (indices
# 0-5). `test_cue_add_returns_the_resolved_word_and_its_neighbours` above
# pins index-form word 2 ("twelve") as the control this compares against.


def test_cue_add_by_phrase_resolves_to_the_same_word_as_the_index_form(
    project: Project,
) -> None:
    added = ops.cue_add(project.root, "vo", asset="cold-open", phrase="twelve minutes")

    assert added["word_index"] == 2
    assert added["text"] == "twelve"


def test_cue_add_by_phrase_stores_the_phrase_as_additive_metadata(project: Project) -> None:
    ops.cue_add(project.root, "vo", asset="cold-open", phrase="twelve minutes")

    assert project.read_manifest()["cues"] == [
        {"clip_id": "vo", "word_index": 2, "asset": "cold-open", "phrase": "twelve minutes"}
    ]


def test_cue_add_by_index_stores_no_phrase_key(project: Project) -> None:
    """The additive-optional rule: an index-addressed cue round-trips exactly
    like it did before this feature existed."""
    ops.cue_add(project.root, "vo", 2, "cold-open")

    assert "phrase" not in project.read_manifest()["cues"][0]


def test_cue_add_refuses_both_word_index_and_phrase(project: Project) -> None:
    with pytest.raises(tx.TranscriptError, match="not both"):
        ops.cue_add(project.root, "vo", 2, "cold-open", phrase="twelve minutes")


def test_cue_add_refuses_neither_word_index_nor_phrase(project: Project) -> None:
    with pytest.raises(tx.TranscriptError, match="not neither"):
        ops.cue_add(project.root, "vo", asset="cold-open")


def test_cue_add_refuses_a_missing_asset(project: Project) -> None:
    with pytest.raises(tx.TranscriptError, match="asset"):
        ops.cue_add(project.root, "vo", 2)


def test_cue_rm_by_phrase_removes_the_same_cue_the_index_form_would(
    project: Project,
) -> None:
    ops.cue_add(project.root, "vo", 2, "cold-open")

    removed = ops.cue_rm(project.root, "vo", phrase="twelve minutes")

    assert removed["asset"] == "cold-open"
    assert project.read_manifest()["cues"] == []


def _ambiguous_project(tmp_path: Path) -> Project:
    """A transcript with "the" appearing twice, for the ambiguity tests —
    the fixture transcript's own words are all distinct."""
    project = Project.create(tmp_path / "ambiguous")
    manifest = project.read_manifest()
    manifest["clips"] = list(CLIPS.values())
    project.write_manifest(manifest)
    tx.save(
        _words(
            "vo",
            ("the", 0.0, 0.3),
            ("cat", 0.5, 0.8),
            ("and", 0.9, 1.1),
            ("the", 1.2, 1.5),
            ("dog", 1.6, 1.9),
        ),
        project.transcript_path("vo"),
    )
    return project


def test_cue_add_by_ambiguous_phrase_with_no_occurrence_raises(tmp_path: Path) -> None:
    project = _ambiguous_project(tmp_path)

    with pytest.raises(tx.AmbiguousPhraseError) as excinfo:
        ops.cue_add(project.root, "vo", asset="cold-open", phrase="the")

    assert len(excinfo.value.candidates) == 2
    assert project.read_manifest().get("cues", []) == []


def test_cue_add_by_ambiguous_phrase_with_occurrence_picks_that_one(
    tmp_path: Path,
) -> None:
    project = _ambiguous_project(tmp_path)

    added = ops.cue_add(project.root, "vo", asset="cold-open", phrase="the", occurrence=2)

    assert added["word_index"] == 3


def test_cue_add_by_phrase_after_skips_the_earlier_occurrence(tmp_path: Path) -> None:
    project = _ambiguous_project(tmp_path)

    added = ops.cue_add(project.root, "vo", asset="cold-open", phrase="the", after=0)

    assert added["word_index"] == 3


def test_unspoken_add_by_phrase_refuses_a_multi_word_match(project: Project) -> None:
    with pytest.raises(tx.TranscriptError, match="exactly one word"):
        ops.unspoken_add(project.root, "vo", phrase="twelve minutes")


def test_unspoken_add_by_phrase_resolves_a_single_word(project: Project) -> None:
    added = ops.unspoken_add(project.root, "vo", phrase="twelve")

    assert added["word_index"] == 2
    assert project.read_manifest()[ops.UNSPOKEN_KEY] == [
        {"clip_id": "vo", "word_index": 2, "text": "twelve", "phrase": "twelve"}
    ]


def test_unspoken_rm_by_phrase(project: Project) -> None:
    ops.unspoken_add(project.root, "vo", 2)

    removed = ops.unspoken_rm(project.root, "vo", phrase="twelve")

    assert removed["word_index"] == 2
    assert project.read_manifest().get(ops.UNSPOKEN_KEY, []) == []


# -- cue_reresolve -------------------------------------------------------


def test_cue_reresolve_reports_unchanged_for_an_index_only_cue(project: Project) -> None:
    ops.cue_add(project.root, "vo", 2, "cold-open")

    report = ops.cue_reresolve(project.root)

    assert report["applied"] is False
    assert report["cues"][0]["action"] == "unchanged (no phrase to re-resolve)"
    assert report["cues"][0]["phrase"] is None


def test_cue_reresolve_reports_no_move_when_the_phrase_still_resolves_the_same(
    project: Project,
) -> None:
    ops.cue_add(project.root, "vo", asset="cold-open", phrase="twelve minutes")

    report = ops.cue_reresolve(project.root)

    assert report["cues"][0]["action"] == "resolved"
    assert report["cues"][0]["word_index"] == 2
    assert report["applied"] is False  # nothing moved, so nothing to apply


def test_cue_reresolve_reports_a_moved_phrase_and_apply_writes_it(project: Project) -> None:
    ops.cue_add(project.root, "vo", asset="cold-open", phrase="twelve minutes")

    # Re-attach a transcript with an extra word inserted before the phrase —
    # the same wording now lives one word later.
    tx.save(
        _words(
            "vo",
            ("well", -1.0, -0.5),
            ("the", 0.0, 0.3),
            ("first", 0.5, 0.9),
            ("twelve", 1.0, 1.4),
            ("minutes", 1.5, 1.9),
            ("of", 2.0, 2.2),
            ("scream", 2.3, 2.7),
        ),
        project.transcript_path("vo"),
    )

    report = ops.cue_reresolve(project.root)
    assert report["cues"][0]["action"] == "resolved"
    assert report["cues"][0]["word_index"] == 3
    assert report["applied"] is False
    # Report-only by default: the manifest is untouched.
    assert project.read_manifest()["cues"][0]["word_index"] == 2

    applied = ops.cue_reresolve(project.root, apply=True)
    assert applied["applied"] is True
    assert applied["cues"][0]["applied"] is True
    assert project.read_manifest()["cues"][0]["word_index"] == 3


def test_cue_reresolve_reports_an_entry_that_no_longer_resolves(project: Project) -> None:
    ops.cue_add(project.root, "vo", asset="cold-open", phrase="twelve minutes")
    tx.save(
        _words("vo", ("completely", 0.0, 0.3), ("different", 0.5, 0.9)),
        project.transcript_path("vo"),
    )

    report = ops.cue_reresolve(project.root, apply=True)

    assert report["cues"][0]["action"] == "not found"
    assert report["applied"] is False
    # Never guessed at — the manifest is untouched on a failed re-resolve.
    assert project.read_manifest()["cues"][0]["word_index"] == 2
