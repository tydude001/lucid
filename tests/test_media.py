"""Pure unit tests for `media.media_path()`'s selection order.

`media_path()` preferring `clip["attenuated"]` over `clip["media"]` was
called out (in review) as the single highest-blast-radius edit behind
`attenuate_noises`: every downstream op (seed/cut/export/verify) trusts this
function to route to the calmer copy once one exists. No end-to-end test
exercises the selection order directly against fabricated clip dicts, so it
is pinned here, independent of ffmpeg/ffprobe/any project on disk — `Project`
is "cheap to construct; does no I/O" (project.py), so this needs no tmp_path
fixture beyond a bare root.
"""

from __future__ import annotations

from pathlib import Path

from lucid import media
from lucid.project import Project


def test_media_path_resolves_to_media_when_no_attenuated_key_exists() -> None:
    """Pins the pre-attenuation behaviour: a clip with only `media` set must
    keep resolving exactly as it did before `attenuate_noises` existed.
    """
    project = Project(root=Path("/tmp/lucid-test-project"))
    clip = {"clip_id": "c1", "source": "/orig/loud.wav", "media": "media/c1.wav"}

    assert media.media_path(project, clip) == project.root / "media/c1.wav"


def test_media_path_prefers_attenuated_over_media_when_both_are_set() -> None:
    """The attenuated-first selection `attenuate_noises` depends on for its
    "downstream ops pick this up for free" claim (ops.py's own docstring).
    """
    project = Project(root=Path("/tmp/lucid-test-project"))
    clip = {
        "clip_id": "c1",
        "source": "/orig/loud.wav",
        "media": "media/c1.wav",
        "attenuated": "cache/attenuated/c1.wav",
    }

    assert media.media_path(project, clip) == project.root / "cache/attenuated/c1.wav"
