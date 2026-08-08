"""`build_shots` — step 2 of the layered timeline.

Maps the cue table (step 1, `test_ops_cues.py`) through the edit's surviving
ranges to contiguous shots. Builds a project by hand — clips, a transcript,
and a hand-written `Edit` with a real cut gap in it — the same pattern
`test_ops_speech_overlap.py` uses, so the fixture can name a cut range on
purpose rather than relying on `seed_timeline`'s auto-editor pass.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from lucid import ops
from lucid import timeline as tl
from lucid import transcript as tx
from lucid.media import MediaError
from lucid.project import Project, ProjectError

CLIPS = {
    "vo": {
        "clip_id": "vo",
        "source": "/tmp/vo.wav",
        "duration": 4.0,
        "has_video": False,
        "has_audio": True,
    },
    "clipa": {
        "clip_id": "clipa",
        "duration": 10.0,
        "has_video": True,
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
    """A VO clip cut to two surviving source ranges — [0.0, 1.0) and
    [2.0, 3.5) — with a gap at [1.0, 2.0) and nothing kept past 3.5, plus a
    registered video clip whose media file actually exists on disk and an
    `outro` card under `assets/cards/`.
    """
    project = Project.create(tmp_path / "proj")

    clip_a_media = tmp_path / "clipa.mp4"
    clip_a_media.write_bytes(b"not really a video, just needs to exist")

    manifest = project.read_manifest()
    manifest["clips"] = [CLIPS["vo"], {**CLIPS["clipa"], "source": str(clip_a_media)}]
    project.write_manifest(manifest)

    edit = tl.Edit([tl.Segment("vo", 0.0, 1.0), tl.Segment("vo", 2.0, 3.5)])
    clips_by_id = {c["clip_id"]: c for c in manifest["clips"]}
    tl.write(tl.to_otio(edit, clips_by_id, rate=1000.0, name="proj"), project.timeline_path)

    tx.save(
        _words(
            "vo",
            ("cold", 0.0, 0.3),
            ("open", 0.5, 0.8),
            ("cut1", 1.2, 1.5),  # inside the cut gap [1.0, 2.0)
            ("after", 2.2, 2.5),
            ("gap2", 3.6, 3.9),  # past the end of the second segment
            ("last", 3.0, 3.3),
            ("dup", 2.2, 2.4),  # same source time as "after", for the tie test
            ("straddle", 1.8, 2.3),  # starts in the gap, tail overlaps the next segment
        ),
        project.transcript_path("vo"),
    )

    project.cards_dir.joinpath("outro.png").write_bytes(b"\x89PNG")
    return project


def test_build_shots_maps_cues_through_the_edit_and_runs_each_to_the_next(
    project: Project,
) -> None:
    ops.cue_add(project.root, "vo", 1, "clipa")  # "open", 0.5s -> forced to frame 0
    ops.cue_add(project.root, "vo", 3, "card:outro")  # "after", 2.2s -> frame 1200
    ops.cue_add(project.root, "vo", 5, "clipa")  # "last", 3.0s -> frame 2000

    result = ops.build_shots(project.root)

    assert result["rate"] == 1000.0
    assert result["total_frames"] == 2500
    assert result["count"] == 3

    shots = result["shots"]
    assert [s["word_index"] for s in shots] == [1, 3, 5]
    assert [s["start_frame"] for s in shots] == [0, 1200, 2000]
    assert [s["frames"] for s in shots] == [1200, 800, 500]
    assert shots[0]["start"] == 0.0
    assert shots[2]["duration"] == pytest.approx(0.5)

    assert shots[0]["asset"] == "clipa"
    assert shots[0]["is_image"] is False
    assert shots[0]["asset_path"].endswith("clipa.mp4")
    assert shots[1]["asset"] == "card:outro"
    assert shots[1]["is_image"] is True
    assert shots[1]["asset_path"].endswith("assets/cards/outro.png")


def test_build_shots_refuses_a_cue_whose_word_was_cut(project: Project) -> None:
    ops.cue_add(project.root, "vo", 2, "clipa")  # "cut1" sits inside the removed gap

    with pytest.raises(tl.TimelineError, match="was cut from the edit"):
        ops.build_shots(project.root)


def test_build_shots_survives_a_word_whose_start_is_cut_but_whose_tail_overlaps(
    project: Project,
) -> None:
    """Overlap, never containment of the word's start alone (CLAUDE.md) — the
    real Scream VO has exactly this shape at word 115, a swallowed false
    start whose *next* word's tail is the surviving take."""
    ops.cue_add(project.root, "vo", 0, "clipa")  # "cold", frame 0 — forced anyway
    ops.cue_add(project.root, "vo", 7, "card:outro")  # "straddle": 1.8-2.3, gap ends at 2.0

    result = ops.build_shots(project.root)

    assert result["count"] == 2
    # The word's own start (1.8s) sits in the cut gap; a point-containment
    # check would call this cut. The word overlaps the second segment from
    # its start (2.0s = frame 1000), which is where the surviving portion —
    # and so the shot — actually begins.
    assert result["shots"][1]["start_frame"] == 1000


def test_build_shots_refuses_a_cue_whose_word_falls_past_the_kept_material(
    project: Project,
) -> None:
    ops.cue_add(project.root, "vo", 4, "clipa")  # "gap2" is past the second segment's end

    with pytest.raises(tl.TimelineError, match="was cut from the edit"):
        ops.build_shots(project.root)


def test_build_shots_refuses_when_the_cue_table_is_empty(project: Project) -> None:
    with pytest.raises(tl.TimelineError, match="no cues yet"):
        ops.build_shots(project.root)


def test_build_shots_refuses_an_asset_naming_an_unknown_clip(project: Project) -> None:
    ops.cue_add(project.root, "vo", 0, "nope")

    with pytest.raises(MediaError):
        ops.build_shots(project.root)


def test_build_shots_refuses_an_asset_clip_with_no_video(project: Project) -> None:
    ops.cue_add(project.root, "vo", 0, "vo")  # itself: audio-only

    with pytest.raises(ProjectError, match="no video"):
        ops.build_shots(project.root)


def test_build_shots_refuses_an_empty_card_name(project: Project) -> None:
    ops.cue_add(project.root, "vo", 0, "card:")

    with pytest.raises(ProjectError, match="names no card"):
        ops.build_shots(project.root)


def test_build_shots_refuses_a_card_that_does_not_exist_on_disk(project: Project) -> None:
    ops.cue_add(project.root, "vo", 0, "card:missing")

    with pytest.raises(ProjectError, match="does not exist"):
        ops.build_shots(project.root)


def test_build_shots_refuses_two_cues_resolving_to_the_same_instant(project: Project) -> None:
    ops.cue_add(project.root, "vo", 1, "clipa")  # forced to frame 0
    ops.cue_add(project.root, "vo", 3, "card:outro")  # "after", frame 1200
    ops.cue_add(project.root, "vo", 6, "card:outro")  # "dup" — same source time as word 3

    with pytest.raises(tl.TimelineError, match="resolved to the same instant"):
        ops.build_shots(project.root)
