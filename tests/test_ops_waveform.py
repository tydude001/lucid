"""`ops.waveform` — the fixed contract, the 0-255 normalisation, and the cache.

A short real wav decoded through real ffmpeg, following test_energy.py's
rationale for synthetic-but-real audio over a captured fixture file: the
point under test is the decode/envelope/normalise/cache pipeline, not any
particular recording.
"""

from __future__ import annotations

import math
import shutil
import struct
import wave
from pathlib import Path

import pytest

from lucid import energy, ops
from lucid.project import Project

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is not installed")
needs_ffprobe = pytest.mark.skipif(shutil.which("ffprobe") is None, reason="ffprobe is not installed")


def _write_wav(
    path: Path, *, tones: list[tuple[float, float]], duration: float, rate: int = 22050
) -> None:
    with wave.open(str(path), "w") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        frames = bytearray()
        for i in range(int(rate * duration)):
            t = i / rate
            loud = any(a <= t < b for a, b in tones)
            value = int(12000 * math.sin(2 * math.pi * 220 * t)) if loud else 0
            frames += struct.pack("<h", value)
        out.writeframes(bytes(frames))


@pytest.fixture
def project_with_clip(tmp_path: Path) -> tuple[Path, str, Path]:
    """A project with one imported clip: 3s, a tone from 0.5-2.0s."""
    source = tmp_path / "src" / "vo.wav"
    source.parent.mkdir()
    _write_wav(source, tones=[(0.5, 2.0)], duration=3.0)

    project_root = tmp_path / "proj"
    ops.init(project_root)
    record = ops.import_media(project_root, source)
    return project_root, record["clip_id"], source


@needs_ffmpeg
@needs_ffprobe
def test_waveform_matches_the_fixed_contract(project_with_clip: tuple[Path, str, Path]) -> None:
    project_root, clip_id, _source = project_with_clip
    result = ops.waveform(project_root, clip_id=clip_id)

    assert set(result) == {"clip_id", "frame_ms", "rms", "duration_s"}
    assert result["clip_id"] == clip_id
    assert result["frame_ms"] == 20
    assert isinstance(result["rms"], list)
    assert result["rms"], "a 3s clip should decode to more than zero frames"
    assert all(isinstance(v, int) for v in result["rms"])
    assert all(0 <= v <= 255 for v in result["rms"])
    assert result["duration_s"] == pytest.approx(3.0, abs=0.05)


@needs_ffmpeg
@needs_ffprobe
def test_the_loudest_frame_normalises_to_255(project_with_clip: tuple[Path, str, Path]) -> None:
    project_root, clip_id, _source = project_with_clip
    result = ops.waveform(project_root, clip_id=clip_id)
    assert max(result["rms"]) == 255


@needs_ffmpeg
@needs_ffprobe
def test_a_default_clip_id_resolves_when_none_is_given(
    project_with_clip: tuple[Path, str, Path],
) -> None:
    project_root, clip_id, _source = project_with_clip
    result = ops.waveform(project_root)
    assert result["clip_id"] == clip_id


def test_no_clips_at_all_is_refused(tmp_path: Path) -> None:
    project_root = tmp_path / "proj"
    ops.init(project_root)
    with pytest.raises(ops.ProjectError, match="no clips to measure"):
        ops.waveform(project_root)


@needs_ffmpeg
@needs_ffprobe
def test_missing_media_is_refused(project_with_clip: tuple[Path, str, Path]) -> None:
    project_root, clip_id, source = project_with_clip
    source.unlink()  # the media/ entry is a symlink to it, now dangling
    with pytest.raises(ops.ProjectError, match="missing from disk"):
        ops.waveform(project_root, clip_id=clip_id)


@needs_ffmpeg
@needs_ffprobe
def test_waveform_prefers_the_attenuated_copy_over_the_manifest_media_field(
    project_with_clip: tuple[Path, str, Path],
) -> None:
    """CLAUDE.md: resolve through `media.media_path()`, never
    `root / clip["media"]` — a clip with an attenuated copy must be measured
    from that copy, the same file every other op reads.
    """
    project_root, clip_id, _source = project_with_clip
    project = Project.open(project_root)

    attenuated = project.attenuated_dir / f"{clip_id}.wav"
    _write_wav(attenuated, tones=[(0.5, 2.0)], duration=6.0)

    manifest = project.read_manifest()
    for clip in manifest["clips"]:
        if clip["clip_id"] == clip_id:
            clip["attenuated"] = str(attenuated.relative_to(project.root))
    project.write_manifest(manifest)

    result = ops.waveform(project_root, clip_id=clip_id)
    assert result["duration_s"] == pytest.approx(6.0, abs=0.05)


@needs_ffmpeg
@needs_ffprobe
def test_a_second_call_is_served_from_the_cache(
    project_with_clip: tuple[Path, str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    project_root, clip_id, _source = project_with_clip
    project = Project.open(project_root)

    first = ops.waveform(project_root, clip_id=clip_id)
    cache_path = project.waveform_path(clip_id)
    assert cache_path.exists(), "a fresh computation must write the cache file"

    def _must_not_run(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("energy.decode must not run on a cache hit")

    monkeypatch.setattr(energy, "decode", _must_not_run)

    second = ops.waveform(project_root, clip_id=clip_id)
    assert second == first


@needs_ffmpeg
@needs_ffprobe
def test_a_changed_media_file_invalidates_the_cache(
    project_with_clip: tuple[Path, str, Path],
) -> None:
    """Keyed by size and mtime: the same `clip_id` pointed at different media
    (a re-attenuation, a re-import) must not keep serving the stale envelope.
    """
    project_root, clip_id, source = project_with_clip
    first = ops.waveform(project_root, clip_id=clip_id)

    _write_wav(source, tones=[(0.5, 2.0)], duration=5.0)  # same path, longer file
    second = ops.waveform(project_root, clip_id=clip_id)

    assert second["duration_s"] != first["duration_s"]
    assert second["duration_s"] == pytest.approx(5.0, abs=0.05)
