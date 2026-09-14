"""`synopsis` and `broll_brief` — the half of b-roll choice lucid can do.

The finding these two exist to encode is a negative one: no arrangement of
text-against-text scoring picks b-roll, because the sentence that earns a clip
routinely shares no word with any description of it. So there is no ranker
here to test. What there is instead is a corpus (`synopsis`) that a reader
with world knowledge can use, and a brief (`broll_brief`) that puts the whole
question in one read-only call. HISTORY.md § Choosing the b-roll.

The properties worth pinning down are therefore mostly about *not* deciding:
the brief never writes, it reports a refusal rather than raising it, it says
which clips have no synopsis instead of inventing one, and it marks card
positions as context rather than offering them as choices.

Built by hand the way `test_ops_shots.py` builds its fixture — clips, a
transcript and a hand-written `Edit` with a real cut in it — so the narration
each position carries can be asserted against a known edit.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from proofcut import ops
from proofcut import timeline as tl
from proofcut import transcript as tx
from proofcut.media import MediaError
from proofcut.project import Project, ProjectError

VO = {
    "clip_id": "vo",
    "source": "/tmp/vo.wav",
    "duration": 4.0,
    "has_video": False,
    "has_audio": True,
}
CLIP_A = {"clip_id": "clipa", "duration": 10.0, "has_video": True, "has_audio": True}
CLIP_B = {"clip_id": "clipb", "duration": 6.0, "has_video": True, "has_audio": True}


@pytest.fixture
def project(tmp_path: Path) -> Project:
    """A VO cut to [0.0, 1.0) and [2.0, 3.5), two video clips whose media
    exists on disk, and an `outro` card."""
    project = Project.create(tmp_path / "proj")
    media_a = tmp_path / "clipa.mp4"
    media_b = tmp_path / "clipb.mp4"
    media_a.write_bytes(b"not really a video, just needs to exist")
    media_b.write_bytes(b"nor is this one")

    manifest = project.read_manifest()
    manifest["clips"] = [
        VO,
        {**CLIP_A, "source": str(media_a)},
        {**CLIP_B, "source": str(media_b)},
    ]
    project.write_manifest(manifest)

    edit = tl.Edit([tl.Segment("vo", 0.0, 1.0), tl.Segment("vo", 2.0, 3.5)])
    tl.write(
        tl.to_otio(edit, {c["clip_id"]: c for c in manifest["clips"]}, rate=1000.0, name="proj"),
        project.timeline_path,
    )
    tx.save(
        tx.Transcript(
            clip_id="vo",
            words=tuple(
                tx.Word(index=i, text=text, start=start, end=end)
                for i, (text, start, end) in enumerate(
                    [
                        ("the", 0.0, 0.3),
                        ("reveal", 0.5, 0.8),
                        ("dropped", 1.2, 1.5),  # inside the cut gap [1.0, 2.0)
                        ("is", 2.2, 2.5),
                        ("the", 3.0, 3.2),
                        ("thesis", 3.3, 3.4),
                    ]
                )
            ),
        ),
        project.transcript_path("vo"),
    )
    project.cards_dir.joinpath("outro.png").write_bytes(b"\x89PNG")
    return project


# -- the synopsis field ---------------------------------------------------


def test_listing_reports_every_clip_and_which_have_no_synopsis(project: Project) -> None:
    ops.synopsis(project.root, "clipa", "Scream (1996) reveal. Billy and Stu unmask.")

    listed = ops.synopsis(project.root)

    assert listed["count"] == 3
    assert {c["clip_id"] for c in listed["clips"]} == {"vo", "clipa", "clipb"}
    assert listed["missing"] == ["vo", "clipb"]


def test_a_synopsis_round_trips_and_clears(project: Project) -> None:
    text = "Scream 3 reveal. Roman is Sidney's half-brother. Written by Ehren Kruger."
    written = ops.synopsis(project.root, "clipa", text)
    assert written == {
        "clip_id": "clipa",
        "synopsis": text,
        "written": True,
        "cleared": False,
    }
    assert ops.synopsis(project.root, "clipa")["synopsis"] == text

    cleared = ops.synopsis(project.root, "clipa", clear=True)
    assert cleared["cleared"] is True
    assert cleared["synopsis"] is None
    assert ops.synopsis(project.root)["missing"] == ["vo", "clipa", "clipb"]


def test_reading_one_does_not_write(project: Project) -> None:
    before = project.read_manifest()
    assert ops.synopsis(project.root, "clipa")["written"] is False
    assert project.read_manifest() == before


def test_whitespace_is_collapsed_so_a_pasted_paragraph_stays_one_line(
    project: Project,
) -> None:
    ops.synopsis(project.root, "clipa", "  Scream 4.\n\n  Jill  wants\tthe fame.  ")
    assert ops.synopsis(project.root, "clipa")["synopsis"] == "Scream 4. Jill wants the fame."


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"text": ""}, "not the same as no synopsis"),
        ({"text": "   "}, "not the same as no synopsis"),
        ({"text": "x" * (ops.SYNOPSIS_MAX + 1)}, "over the"),
        ({"text": "both", "clear": True}, "not both"),
    ],
)
def test_the_refusals(project: Project, kwargs: dict, message: str) -> None:
    text = kwargs.pop("text", None)
    with pytest.raises(ProjectError, match=message):
        ops.synopsis(project.root, "clipa", text, **kwargs)


def test_writing_without_naming_a_clip_is_refused(project: Project) -> None:
    with pytest.raises(ProjectError, match="which synopsis to write"):
        ops.synopsis(project.root, None, "a synopsis of what, exactly")


def test_an_unregistered_clip_says_which_ones_exist(project: Project) -> None:
    with pytest.raises(MediaError, match="registered: vo, clipa, clipb"):
        ops.synopsis(project.root, "nope", "text")


# -- the brief ------------------------------------------------------------


def test_the_brief_carries_the_narration_that_plays_over_each_position(
    project: Project,
) -> None:
    ops.cue_add(project.root, "vo", 1, "clipa")  # "reveal", forced to frame 0
    ops.cue_add(project.root, "vo", 3, "clipb")  # "is", 2.2s -> frame 1200

    brief = ops.broll_brief(project.root)

    assert brief["count"] == 2
    assert brief["choices"] == 2
    first, second = brief["positions"]
    # "dropped" sits in the cut gap, so it plays nowhere and belongs to neither.
    assert first["narration"] == "the reveal"
    assert second["narration"] == "is the thesis"
    assert [p["asset"] for p in brief["positions"]] == ["clipa", "clipb"]


def test_card_positions_are_context_and_never_candidates(project: Project) -> None:
    ops.cue_add(project.root, "vo", 1, "clipa")
    ops.cue_add(project.root, "vo", 3, "card:outro")

    brief = ops.broll_brief(project.root)

    assert [p["card"] for p in brief["positions"]] == [False, True]
    assert brief["count"] == 2
    assert brief["choices"] == 1
    assert "card:outro" not in {c["clip_id"] for c in brief["candidates"]}


def test_only_footage_is_a_candidate_and_each_carries_its_synopsis(
    project: Project,
) -> None:
    ops.cue_add(project.root, "vo", 1, "clipa")
    ops.synopsis(project.root, "clipa", "Scream (1996). Randy explains the rules.")

    brief = ops.broll_brief(project.root)

    # The VO has no video, so it is not something to cut away to.
    assert [c["clip_id"] for c in brief["candidates"]] == ["clipa", "clipb"]
    assert brief["candidates"][0]["synopsis"] == "Scream (1996). Randy explains the rules."
    assert brief["candidates"][0]["duration"] == 10.0
    assert brief["missing_synopsis"] == ["clipb"]


def test_the_brief_never_writes(project: Project) -> None:
    ops.cue_add(project.root, "vo", 1, "clipa")
    before = project.read_manifest()
    depth = len(project.snapshots())

    ops.broll_brief(project.root)

    assert project.read_manifest() == before
    assert len(project.snapshots()) == depth


def test_a_refused_picture_plan_is_reported_not_raised(project: Project) -> None:
    """A pin that outruns its asset is `plan_picture`'s refusal. The brief has
    to hand that back as text, because a brief listing a slot `export` will not
    produce invites a pick for a shot that cannot exist."""
    ops.cue_add(project.root, "vo", 1, "clipa", src_start=9.5)  # 10.0s asset, ~1.2s shot

    brief = ops.broll_brief(project.root)

    assert brief["positions"] == []
    assert brief["count"] == 0
    assert "clipa" in brief["shots_error"]
    # The catalogue still comes back — it is what the fix will be chosen from.
    assert [c["clip_id"] for c in brief["candidates"]] == ["clipa", "clipb"]


def test_a_project_with_no_cues_says_so_instead_of_briefing_nothing(
    project: Project,
) -> None:
    """The state a picker starts in. `_picture_plan` returns empty rather than
    refusing here — right for the picture lane, silent for a brief — so an
    empty answer needs to say which kind of empty it is."""
    brief = ops.broll_brief(project.root)

    assert brief["positions"] == []
    assert "shots_error" not in brief
    assert "no cues yet" in brief["note"]
    assert [c["clip_id"] for c in brief["candidates"]] == ["clipa", "clipb"]


def test_a_briefed_project_carries_no_note(project: Project) -> None:
    ops.cue_add(project.root, "vo", 1, "clipa")
    assert "note" not in ops.broll_brief(project.root)
