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
