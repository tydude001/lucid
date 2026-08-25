"""Manifest-aware undo — docs/plans/POLISH.md § Step 03.

`snapshot()` copied `project.otio` and `restore()` put it back, which covered
cuts and nothing else. Most authoring state stopped living in the timeline
some time ago: the cue table, framing rects, the music bed, the caption style,
head/tail/holds, unspoken marks and card records are manifest keys that touch
no `project.otio` at all. So a mis-dragged cue had no undo while a cut undid
fine, and the window is what made both one gesture.

What is asserted here is the pair, the two asymmetric absences (an older
snapshot with no manifest; a snapshot from before there was a timeline), and
the once-per-instance guard that keeps an op writing both files to one undo
step. The wire-level half is in test_server_stdio.py.

Built by hand rather than through `import_media`, following
test_ops_reel.py: no ffprobe is needed to have a project with a shape.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from lucid import ops
from lucid import timeline as tl
from lucid import transcript as tx
from lucid.ops import REFRAME_KEY
from lucid.project import MANIFEST_SNAPSHOT_SUFFIX, Project, ProjectError

CLIP: dict[str, Any] = {
    "clip_id": "vo",
    "source": "/tmp/vo.mp4",
    "media": "media/vo.mp4",
    "duration": 12.0,
    "has_video": True,
    "has_audio": True,
    "width": 1920,
    "height": 816,
    "fps": 25.0,
}


def _transcript() -> tx.Transcript:
    """One word a second, so a timeline second reads as a word index."""
    return tx.Transcript(
        clip_id="vo",
        words=tuple(tx.Word(index=i, text=f"w{i}", start=float(i), end=float(i) + 0.4) for i in range(12)),
    )


@pytest.fixture
def project(tmp_path: Path) -> Project:
    """A 12s single-clip project with a timeline and a transcript."""
    project = Project.create(tmp_path / "proj")
    (tmp_path / "footage").mkdir()
    real = tmp_path / "footage" / "vo.mp4"
    real.write_bytes(b"not really an mp4")
    (project.media_dir / "vo.mp4").symlink_to(real)

    manifest = project.read_manifest()
    manifest["clips"] = [dict(CLIP)]
    manifest["timebase"] = 25.0
    project.write_manifest(manifest, snapshot=False)

    edit = tl.Edit([tl.Segment(clip_id="vo", start=0.0, end=12.0)])
    tl.write(tl.to_otio(edit, {"vo": dict(CLIP)}, rate=25.0, name="proj"), project.timeline_path)
    tx.save(_transcript(), project.transcript_path("vo"))
    return project


# -- the pair --------------------------------------------------------------


def test_a_snapshot_saves_both_files(project: Project) -> None:
    taken = project.snapshot()

    assert taken is not None
    assert taken.timeline is not None and taken.timeline.exists()
    assert taken.manifest is not None and taken.manifest.exists()
    assert taken.legacy is False


def test_a_manifest_only_mutation_is_undoable(project: Project) -> None:
    """The hole this step closes: a cue touches no `project.otio` at all."""
    before = ops.cue_ls(project.root)["cues"]
    ops.cue_add(project.root, clip_id="vo", word_index=4, asset="card:title")
    assert len(ops.cue_ls(project.root)["cues"]) == len(before) + 1

    report = ops.undo(project.root)

    assert report["manifest_restored"] is True
    assert ops.cue_ls(project.root)["cues"] == before


def test_undo_reports_which_halves_came_back(project: Project) -> None:
    """Three answers look identical from outside; only the flags separate them."""
    ops.cue_add(project.root, clip_id="vo", word_index=4, asset="card:title")

    report = ops.undo(project.root)

    assert report["timeline_restored"] is True
    assert report["manifest_restored"] is True
    assert report["timeline_removed"] is False
    assert report["segments"] == 1


def test_a_framing_rect_undoes(project: Project) -> None:
    """`reframe` is manifest-only too, and is a one-gesture mutation in Frame mode."""
    ops.reframe(project.root, clip_id="vo", rect="100,0,1720,816")
    assert project.read_manifest()[REFRAME_KEY]

    ops.undo(project.root)

    assert not project.read_manifest().get(REFRAME_KEY)


def test_a_mixed_sequence_undoes_in_reverse_one_mutation_at_a_time(project: Project) -> None:
    """A cut, a cue and a cut — each undo walks back exactly one decision.

    The failure this rules out is an op that snapshots twice (it writes both
    files) and so costs two presses to take back one thing.
    """
    ops.cut_by_time(project.root, spans=[[1.0, 2.0]])
    ops.cue_add(project.root, clip_id="vo", word_index=6, asset="card:title")
    ops.cut_by_time(project.root, spans=[[8.0, 9.0]])

    assert ops.status(project.root)["timeline_duration"] == pytest.approx(10.0)
    assert len(ops.cue_ls(project.root)["cues"]) == 1

    ops.undo(project.root)  # the second cut
    assert ops.status(project.root)["timeline_duration"] == pytest.approx(11.0)
    assert len(ops.cue_ls(project.root)["cues"]) == 1

    ops.undo(project.root)  # the cue
    assert ops.status(project.root)["timeline_duration"] == pytest.approx(11.0)
    assert ops.cue_ls(project.root)["cues"] == []

    ops.undo(project.root)  # the first cut
    assert ops.status(project.root)["timeline_duration"] == pytest.approx(12.0)


# -- the once-per-instance guard ------------------------------------------


def test_one_op_is_one_undo_step_even_when_it_writes_both_files(project: Project) -> None:
    """`_save_edit` snapshots and so does `write_manifest`; an op doing both
    must still cost one press. The guard is per `Project` instance, which is
    per op, because every op opens its own at the top."""
    handle = Project.open(project.root)
    first = handle.snapshot()
    second = handle.snapshot()

    assert first is not None
    assert second is first
    assert len(handle.snapshots()) == 1


def test_two_instances_take_two_snapshots(project: Project) -> None:
    """Two ops, two undo steps — the guard must not span calls."""
    Project.open(project.root).snapshot()
    Project.open(project.root).snapshot()

    assert [s.index for s in project.snapshots()] == [0, 1]


# -- the two asymmetric absences ------------------------------------------


def test_a_legacy_timeline_only_snapshot_never_guesses_at_a_manifest(project: Project) -> None:
    """A history written by a lucid that only saved timelines. It restores the
    timeline alone and says so, rather than inventing a manifest for it."""
    cut = ops.cut_by_time(project.root, spans=[[1.0, 2.0]])
    assert cut["duration_after"] == pytest.approx(11.0)
    # Rewind the stack to what an older lucid would have left: the `.otio`
    # half alone. Seeded by hand, because no lucid writes this shape any more.
    for path in project.history_dir.glob(f"*{MANIFEST_SNAPSHOT_SUFFIX}"):
        path.unlink()
    ops.cue_add(project.root, clip_id="vo", word_index=4, asset="card:title")
    for path in sorted(project.history_dir.glob(f"*{MANIFEST_SNAPSHOT_SUFFIX}")):
        path.unlink()

    report = ops.undo(project.root)

    assert report["manifest_restored"] is False
    assert report["timeline_restored"] is True
    assert "before lucid saved manifests" in report["note"]
    # Untouched, not guessed at — the cue is still there.
    assert len(ops.cue_ls(project.root)["cues"]) == 1


def test_undoing_a_state_that_had_no_timeline_removes_the_one_that_was_laid_down(
    tmp_path: Path,
) -> None:
    """Undoing a seed. The snapshot holds a manifest and no timeline, so the
    state being restored is one with no timeline in it — leaving the seeded
    edit in place would report an undo that did not happen."""
    project = Project.create(tmp_path / "fresh")
    manifest = project.read_manifest()
    manifest["clips"] = [dict(CLIP)]
    project.write_manifest(manifest)  # snapshots: manifest only, no timeline yet
    assert project.snapshots()[-1].timeline is None

    edit = tl.Edit([tl.Segment(clip_id="vo", start=0.0, end=12.0)])
    tl.write(tl.to_otio(edit, {"vo": dict(CLIP)}, rate=25.0, name="fresh"), project.timeline_path)

    report = ops.undo(project.root)

    assert report["timeline_removed"] is True
    assert report["timeline_duration"] is None
    assert report["segments"] is None
    assert "was removed" in report["note"]
    assert not project.timeline_path.exists()


def test_nothing_to_undo_still_refuses(tmp_path: Path) -> None:
    project = Project.create(tmp_path / "fresh")

    with pytest.raises(ProjectError, match="nothing to undo"):
        ops.undo(project.root)


# -- what a whole-manifest restore drags with it, stated rather than hidden --


def test_undoing_an_import_leaves_the_media_on_disk(project: Project) -> None:
    """A manifest is a registry. Un-registering a clip is an undo; deleting
    somebody's footage is not, and undo's docstring says so rather than the
    behaviour being discovered."""
    media_file = project.media_dir / "vo.mp4"
    manifest = project.read_manifest()
    manifest["clips"] = [*manifest["clips"], {**CLIP, "clip_id": "broll"}]
    project.write_manifest(manifest)

    ops.undo(project.root)

    assert [c["clip_id"] for c in project.read_manifest()["clips"]] == ["vo"]
    assert media_file.exists()


def test_the_migration_backup_is_not_an_undo_step(tmp_path: Path) -> None:
    """`lucid-v3.json` shares `cache/history/` with the numbered snapshots and
    must stay invisible: rolling the timeline back one edit must not roll the
    schema back with it."""
    project = Project.create(tmp_path / "old")
    project.write_manifest({"schema_version": 1, "name": "old", "clips": []}, snapshot=False)

    Project.migrate(project.root)

    assert project.snapshots() == []
    assert (project.history_dir / "lucid-v1.json").exists()


def test_a_snapshot_pair_is_numbered_together(project: Project) -> None:
    """The two halves find each other by index, so a half-written pair is
    still a readable snapshot rather than a crash in `int()`."""
    project.snapshot()
    (project.history_dir / "notes.txt").write_text("not a snapshot", encoding="utf-8")

    snapshots = project.snapshots()

    assert [s.index for s in snapshots] == [0]
    assert snapshots[0].manifest is not None
    assert json.loads(snapshots[0].manifest.read_text(encoding="utf-8"))["clips"]
