"""`ops.resolve_phrase` — the standalone phrase resolver, echoed.

Narrow-focus, mirroring `test_ops_echo.py`: `Transcript.resolve()` itself is
covered in `test_transcript.py`; this file only checks the ops-layer wrapper
— that it echoes the resolution the way every word-indexed tool here does
(CONTEXT_WORDS=3), and that its error paths (ambiguity, out-of-range
occurrence) read the way `cue_reresolve`/CLI callers depend on.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from lucid import ops
from lucid import transcript as tx
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


def test_resolve_phrase_echoes_the_resolved_range_and_its_neighbours(
    project: Project,
) -> None:
    resolved = ops.resolve_phrase(project.root, "vo", "twelve minutes")

    assert resolved["clip_id"] == "vo"
    assert resolved["phrase"] == "twelve minutes"
    assert resolved["first_word"] == 2
    assert resolved["last_word"] == 3
    assert resolved["match"] == "exact"
    assert [w["text"] for w in resolved["context_before"]] == ["the", "first"]
    assert [w["text"] for w in resolved["context_after"]] == ["of", "scream"]


def test_resolve_phrase_is_read_only(project: Project) -> None:
    before = project.manifest_path.stat().st_mtime_ns
    ops.resolve_phrase(project.root, "vo", "twelve minutes")
    assert project.manifest_path.stat().st_mtime_ns == before


def test_resolve_phrase_ambiguous_lists_every_candidate(tmp_path: Path) -> None:
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

    with pytest.raises(tx.AmbiguousPhraseError) as excinfo:
        ops.resolve_phrase(project.root, "vo", "the")

    err = excinfo.value
    assert len(err.candidates) == 2
    assert [(c["first_word"], c["last_word"]) for c in err.candidates] == [(0, 0), (3, 3)]
    assert "occurrence=" in str(err)


def test_resolve_phrase_occurrence_out_of_range_names_the_count(tmp_path: Path) -> None:
    project = Project.create(tmp_path / "ambiguous")
    manifest = project.read_manifest()
    manifest["clips"] = list(CLIPS.values())
    project.write_manifest(manifest)
    tx.save(
        _words("vo", ("the", 0.0, 0.3), ("cat", 0.5, 0.8), ("the", 0.9, 1.2), ("dog", 1.3, 1.6)),
        project.transcript_path("vo"),
    )

    with pytest.raises(tx.TranscriptError, match="matches 2 time"):
        ops.resolve_phrase(project.root, "vo", "the", occurrence=3)


def test_resolve_phrase_no_fuzzy_refuses_a_near_miss(project: Project) -> None:
    with pytest.raises(tx.TranscriptError, match="fuzzy disabled"):
        ops.resolve_phrase(project.root, "vo", "twelv minuts", fuzzy=False)


def test_resolve_phrase_refuses_an_unknown_clip(project: Project) -> None:
    with pytest.raises(tx.TranscriptError, match="no transcript"):
        ops.resolve_phrase(project.root, "nope", "twelve minutes")
