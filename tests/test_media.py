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

from proofcut import media
from proofcut.project import Project


def test_media_path_resolves_to_media_when_no_attenuated_key_exists() -> None:
    """Pins the pre-attenuation behaviour: a clip with only `media` set must
    keep resolving exactly as it did before `attenuate_noises` existed.
    """
    project = Project(root=Path("/tmp/proofcut-test-project"))
    clip = {"clip_id": "c1", "source": "/orig/loud.wav", "media": "media/c1.wav"}

    assert media.media_path(project, clip) == project.root / "media/c1.wav"


def test_media_path_prefers_attenuated_over_media_when_both_are_set() -> None:
    """The attenuated-first selection `attenuate_noises` depends on for its
    "downstream ops pick this up for free" claim (ops.py's own docstring).
    """
    project = Project(root=Path("/tmp/proofcut-test-project"))
    clip = {
        "clip_id": "c1",
        "source": "/orig/loud.wav",
        "media": "media/c1.wav",
        "attenuated": "cache/attenuated/c1.wav",
    }

    assert media.media_path(project, clip) == project.root / "cache/attenuated/c1.wav"


def test_media_path_prefers_mixed_over_media() -> None:
    """A two-mic container's `mixed` copy is what every op must be handed.

    The container itself carries both mics and nothing downstream chooses
    between them — whisper lets ffmpeg pick and MLT picks again — so routing
    here is what keeps a co-hosted recording whole. PLAN.md § The co-hosted
    recording.
    """
    project = Project(root=Path("/tmp/proofcut-test-project"))
    clip = {
        "clip_id": "c1",
        "source": "/orig/cohost.mkv",
        "media": "media/c1.mkv",
        "mixed": "cache/mixed/c1.mkv",
    }

    assert media.media_path(project, clip) == project.root / "cache/mixed/c1.mkv"


def test_media_path_prefers_attenuated_over_mixed() -> None:
    """Attenuation runs *on* the mixdown, so its output is the later word."""
    project = Project(root=Path("/tmp/proofcut-test-project"))
    clip = {
        "clip_id": "c1",
        "source": "/orig/cohost.mkv",
        "media": "media/c1.mkv",
        "mixed": "cache/mixed/c1.mkv",
        "attenuated": "cache/attenuated/c1.mkv",
    }

    assert media.media_path(project, clip) == project.root / "cache/attenuated/c1.mkv"


def test_original_media_path_keeps_the_mixdown() -> None:
    """`attenuate_noises` rebuilds from here, and the untouched original of a
    two-mic container is the mixdown — reading the container instead would
    attenuate mic A alone and hand `media_path()` back a one-mic file.
    """
    project = Project(root=Path("/tmp/proofcut-test-project"))
    clip = {
        "clip_id": "c1",
        "source": "/orig/cohost.mkv",
        "media": "media/c1.mkv",
        "mixed": "cache/mixed/c1.mkv",
        "attenuated": "cache/attenuated/c1.mkv",
    }

    assert media.original_media_path(project, clip) == project.root / "cache/mixed/c1.mkv"


def test_bit_depth_reads_the_field_then_the_pixel_format() -> None:
    """A luma reading is meaningless without this, so it is pinned per format.

    `signalstats` reports on the source's own scale: the film's
    `s4-overexposed` measures YAVG 429 against its 8-bit neighbours' 26-132
    and is 10-bit, not brighter. Every path is exercised because the regex
    branch was dead until it was not — `bits_per_raw_sample` covered the only
    10-bit clip in the repo, and the fallback carried a group-lookup bug that
    no probe of real media would have reached.

    `p010le`/`p016le` earn their own pattern: they are what hardware encoders
    emit, which is phone and action-cam footage.
    """
    assert media._bit_depth(None) == 8
    assert media._bit_depth({}) == 8
    assert media._bit_depth({"pix_fmt": None}) == 8

    # The field wins where ffprobe reports one.
    assert media._bit_depth({"bits_per_raw_sample": "10", "pix_fmt": "yuv420p"}) == 10
    # ...and a junk field falls through rather than raising.
    assert media._bit_depth({"bits_per_raw_sample": "weird", "pix_fmt": "yuv420p10le"}) == 10

    for fmt, depth in (
        ("yuv420p", 8),
        ("rgb24", 8),
        ("yuv420p10le", 10),
        ("yuva420p10le", 10),
        ("yuv422p12be", 12),
        ("gbrp16le", 16),
        ("p010le", 10),
        ("p016le", 16),
    ):
        assert media._bit_depth({"pix_fmt": fmt}) == depth, fmt
