"""The one `speech_overlap` scenario no shipped tool can build via the server:
a timeline that already carries more than one clip_id.

`seed_timeline` only ever seeds a single clip, so a multi-clip `Edit` has to
be hand-written straight through `timeline.write`/`to_otio` — bypassing the
tool surface entirely, the same way `test_timeline.py` builds `Edit`/`Segment`
objects directly. Every other `speech_overlap` scenario is exercised over
stdio in `test_server_stdio.py`, on a real (single-clip) seeded timeline.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from lucid import ops
from lucid import timeline as tl
from lucid import transcript as tx
from lucid.project import Project, ProjectError

CLIPS = {
    "vo1": {
        "clip_id": "vo1",
        "source": "/tmp/vo1.wav",
        "duration": 5.0,
        "has_video": False,
        "has_audio": True,
    },
    "vo2": {
        "clip_id": "vo2",
        "source": "/tmp/vo2.wav",
        "duration": 5.0,
        "has_video": False,
        "has_audio": True,
    },
    "clipb": {
        "clip_id": "clipb",
        "source": "/tmp/clipb.wav",
        "duration": 3.0,
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
    """A two-clip_id timeline (vo1, vo2), each carrying a transcript, plus an
    unplaced clip_id (clipb) with its own transcript — the shape
    `speech_overlap`'s `vo_clip_id` disambiguation guard exists for.
    """
    project = Project.create(tmp_path / "proj")
    manifest = project.read_manifest()
    manifest["clips"] = list(CLIPS.values())
    project.write_manifest(manifest)

    edit = tl.Edit([tl.Segment("vo1", 0.0, 5.0), tl.Segment("vo2", 0.0, 5.0)])
    tl.write(tl.to_otio(edit, CLIPS, rate=1000.0, name="proj"), project.timeline_path)

    tx.save(_words("vo1", ("a", 0.0, 0.5)), project.transcript_path("vo1"))
    tx.save(_words("vo2", ("b", 0.0, 0.5)), project.transcript_path("vo2"))
    tx.save(_words("clipb", ("say", 0.0, 0.5)), project.transcript_path("clipb"))
    return project


def test_speech_overlap_requires_vo_clip_id_when_the_timeline_has_more_than_one_clip(
    project: Project,
) -> None:
    with pytest.raises(ProjectError) as excinfo:
        ops.speech_overlap(project.root, "clipb")
    message = str(excinfo.value)
    assert "vo1" in message
    assert "vo2" in message


def test_speech_overlap_resolves_once_vo_clip_id_is_given_explicitly(project: Project) -> None:
    result = ops.speech_overlap(project.root, "clipb", vo_clip_id="vo1")
    assert result["vo_clip_id"] == "vo1"
    assert result["vo_words"][0]["text"] == "a"


def test_speech_overlap_refuses_a_vo_clip_id_not_on_the_timeline(project: Project) -> None:
    with pytest.raises(ProjectError) as excinfo:
        ops.speech_overlap(project.root, "clipb", vo_clip_id="clipb")
    message = str(excinfo.value)
    assert "vo1" in message
    assert "vo2" in message
