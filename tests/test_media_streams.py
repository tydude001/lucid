"""A container with more than one audio stream, and what import does with it.

The failure this guards is silent in every direction: every audio field on a
clip record describes the container's *first* stream, `asr.transcribe` hands
whisper the container and lets ffmpeg pick, and `mlt.py` writes no
`audio_index` for the Edit lane so MLT picks too. A dual-mic capture would
reach the film as mic A with `verify`, `check_frames` and `film_check` all
clean, because each compares the render against the timeline and the timeline
never knew there was a second stream. PLAN.md § The co-hosted recording.

The readback is a Goertzel power at each mic's own tone rather than a level
meter or a stream count: a two-track container "has" both mics while
everything that decodes it hears one, so counting streams answers the wrong
question. Tones are the same instrument the design note's own melt probe used.
"""

from __future__ import annotations

import array
import math
import shutil
import subprocess
import wave
from pathlib import Path

import pytest

from lucid import media, ops
from lucid.project import Project

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is not installed")
needs_ffprobe = pytest.mark.skipif(
    shutil.which("ffprobe") is None, reason="ffprobe is not installed"
)

MIC_A_HZ = 300.0
MIC_B_HZ = 1200.0


def _two_mic_container(dest: Path, *, seconds: float = 2.0, video: bool = True) -> Path:
    """A container holding two mics: a `MIC_A_HZ` tone and a `MIC_B_HZ` one."""
    command = ["ffmpeg", "-nostdin", "-v", "error", "-y"]
    if video:
        command += ["-f", "lavfi", "-i", f"testsrc=size=160x120:rate=25:duration={seconds}"]
    for hz in (MIC_A_HZ, MIC_B_HZ):
        command += ["-f", "lavfi", "-i", f"sine=frequency={hz}:duration={seconds}:sample_rate=48000"]
    first_audio = 1 if video else 0
    if video:
        command += ["-map", "0:v", "-c:v", "libx264", "-pix_fmt", "yuv420p"]
    command += ["-map", f"{first_audio}:a", "-map", f"{first_audio + 1}:a"]
    command += ["-c:a", "aac", "-shortest", str(dest)]
    subprocess.run(command, capture_output=True, check=True)
    return dest


def _tone_power(path: Path, hz: float) -> float:
    """Goertzel power at `hz` over the file's first audio stream, decoded."""
    decoded = path.with_suffix(".probe.wav")
    subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(path), "-vn", "-ac", "1",
         "-c:a", "pcm_s16le", str(decoded)],
        capture_output=True,
        check=True,
    )  # fmt: skip
    with wave.open(str(decoded), "rb") as handle:
        rate, frames = handle.getframerate(), handle.getnframes()
        raw = handle.readframes(frames)
    samples = array.array("h")
    samples.frombytes(raw)
    k = int(0.5 + (len(samples) * hz) / rate)
    w = 2 * math.pi * k / len(samples)
    coeff = 2 * math.cos(w)
    q1 = q2 = 0.0
    for sample in samples:
        q0 = coeff * q1 - q2 + sample
        q2, q1 = q1, q0
    return math.sqrt(abs(q1 * q1 + q2 * q2 - coeff * q1 * q2)) / len(samples)


@needs_ffprobe
@needs_ffmpeg
def test_probe_counts_every_audio_stream(tmp_path: Path) -> None:
    """The count is the only field that separates one mic from two — every
    other audio field on the record describes the first stream either way.
    """
    container = _two_mic_container(tmp_path / "cohost.mkv")

    info = media.probe(container)

    assert info.audio_streams == 2
    assert info.has_audio is True


@needs_ffprobe
@needs_ffmpeg
def test_probe_reports_one_stream_for_ordinary_media(tmp_path: Path) -> None:
    single = tmp_path / "vo.wav"
    subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-y", "-f", "lavfi",
         "-i", "sine=frequency=300:duration=1", str(single)],
        capture_output=True,
        check=True,
    )  # fmt: skip

    assert media.probe(single).audio_streams == 1


def test_a_hand_built_media_info_still_means_one_stream() -> None:
    """The default is what makes this additive: an older clip record has no
    `audio_streams` key, and absent has to keep meaning what it meant.
    """
    info = media.MediaInfo(
        duration=1.0,
        has_video=False,
        has_audio=True,
        fps=None,
        width=None,
        height=None,
        sample_rate=48000,
        channels=1,
        video_codec=None,
        audio_codec="pcm_s16le",
        vfr=False,
    )

    assert info.audio_streams == 1
    assert info.as_dict()["audio_streams"] == 1


def test_deriving_from_a_single_stream_file_refuses(tmp_path: Path) -> None:
    """Nothing to choose between, so a derived copy would only be a second
    file saying the same thing — and a caller asking has misread the record.
    """
    with pytest.raises(media.MediaError, match="nothing to derive"):
        media.derive_single_audio(tmp_path / "vo.wav", tmp_path / "out.wav", streams=1)


def test_picking_a_stream_that_is_not_there_refuses(tmp_path: Path) -> None:
    with pytest.raises(media.MediaError, match="numbered 0-1"):
        media.derive_single_audio(tmp_path / "vo.mkv", tmp_path / "out.mkv", streams=2, pick=2)


@needs_ffmpeg
def test_the_sum_carries_both_mics(tmp_path: Path) -> None:
    """The whole claim: after the derivation one track holds both people."""
    container = _two_mic_container(tmp_path / "cohost.mkv")
    dest = tmp_path / "out" / "cohost.mkv"

    report = media.derive_single_audio(container, dest, streams=2, has_video=True)

    assert report == {"streams": 2, "mode": "sum", "stream": None, "codec": "aac"}
    a, b = _tone_power(dest, MIC_A_HZ), _tone_power(dest, MIC_B_HZ)
    assert a > 100.0 and b > 100.0
    # Summed, not favoured: `normalize=1` averages, so neither mic is louder.
    assert abs(a - b) / max(a, b) < 0.1


@needs_ffmpeg
def test_the_container_itself_plays_only_the_first_mic(tmp_path: Path) -> None:
    """The control, and the reason the derivation exists at all.

    Read the same way as the derived file, the untouched container answers
    with mic A alone — which is exactly what a render made from it plays.
    """
    container = _two_mic_container(tmp_path / "cohost.mkv")

    assert _tone_power(container, MIC_A_HZ) > 100.0
    assert _tone_power(container, MIC_B_HZ) < 10.0


@needs_ffmpeg
def test_a_pick_keeps_the_stream_asked_for(tmp_path: Path) -> None:
    """`pick` is ffmpeg's audio ordinal, so 1 is the second *mic* — the
    numbering MLT's `audio_index` would call 2 on this container.
    """
    container = _two_mic_container(tmp_path / "cohost.mkv")
    dest = tmp_path / "out" / "cohost.mkv"

    report = media.derive_single_audio(container, dest, streams=2, pick=1, has_video=True)

    assert report == {"streams": 2, "mode": "pick", "stream": 1, "codec": "copy"}
    assert _tone_power(dest, MIC_A_HZ) < 10.0
    assert _tone_power(dest, MIC_B_HZ) > 100.0


@needs_ffmpeg
def test_the_derivation_keeps_the_picture(tmp_path: Path) -> None:
    """A mixdown that dropped the video would take the co-hosts' faces with
    it, and `media_path()` hands this file to every op including `export`.
    """
    container = _two_mic_container(tmp_path / "cohost.mkv")
    dest = tmp_path / "out" / "cohost.mkv"

    media.derive_single_audio(container, dest, streams=2, has_video=True)

    assert media.probe(dest).has_video is True
    assert media.probe(dest).audio_streams == 1


@needs_ffmpeg
def test_an_audio_only_two_mic_file_needs_no_video_map(tmp_path: Path) -> None:
    """The audio-only case is every fixture anyone writes first, and it is
    the one where MLT's numbering and ffmpeg's happen to agree.
    """
    container = _two_mic_container(tmp_path / "mics.mkv", video=False)
    dest = tmp_path / "out" / "mics.mkv"

    media.derive_single_audio(container, dest, streams=2, has_video=False)

    assert media.probe(dest).has_video is False
    assert _tone_power(dest, MIC_A_HZ) > 100.0
    assert _tone_power(dest, MIC_B_HZ) > 100.0


@needs_ffprobe
@needs_ffmpeg
def test_reimporting_a_resolved_container_is_still_a_no_op(tmp_path: Path) -> None:
    """The refusal must sit *behind* the source dedup, not in front of it.

    Re-importing the same source path is a documented no-op that returns the
    existing record — which is also what stops anyone reaching the second
    stream by importing the file twice. A refusal ahead of that would raise
    about a container whose mics were summed days ago.
    """
    project = Project.create(tmp_path / "proj")
    container = _two_mic_container(tmp_path / "cohost.mkv")

    first = media.import_media(project, container, mix=True)
    again = media.import_media(project, container)

    assert again["clip_id"] == first["clip_id"]
    assert again["mixed"] == first["mixed"]
    assert len(project.read_manifest()["clips"]) == 1


@needs_ffprobe
@needs_ffmpeg
def test_mix_and_a_stream_pick_together_are_refused(tmp_path: Path) -> None:
    """Two different answers to one question — take neither silently."""
    project = Project.create(tmp_path / "proj")
    container = _two_mic_container(tmp_path / "cohost.mkv")

    with pytest.raises(media.MediaError, match="one or the other"):
        media.import_media(project, container, mix=True, audio_stream=0)


@needs_ffprobe
@needs_ffmpeg
def test_a_failed_derivation_leaves_nothing_behind(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`_place` writes a symlink — or a whole copy under `--copy` — so a
    derivation that fails after it would strand a file no clip record names.
    """
    project = Project.create(tmp_path / "proj")
    container = _two_mic_container(tmp_path / "cohost.mkv")

    def _boom(*args: object, **kwargs: object) -> dict[str, object]:
        raise media.MediaError("ffmpeg fell over")

    monkeypatch.setattr(media, "derive_single_audio", _boom)
    with pytest.raises(media.MediaError, match="fell over"):
        media.import_media(project, container, mix=True)

    assert project.read_manifest()["clips"] == []
    assert list(project.media_dir.glob("*")) == []
    assert not project.mixed_dir.exists() or list(project.mixed_dir.glob("*")) == []


@needs_ffprobe
@needs_ffmpeg
def test_a_reel_carries_the_mixdown(tmp_path: Path) -> None:
    """`media_path()` prefers `mixed`, so a derivation that does not carry it
    hands the reel a path with nothing at it — worse than the silent
    single-mic render the key exists to prevent.
    """
    project = Project.create(tmp_path / "proj")
    container = _two_mic_container(tmp_path / "cohost.mkv")
    clip = media.import_media(project, container, mix=True)

    reel = Project.create(tmp_path / "reel")
    manifest = project.read_manifest()
    linked = ops._reel_media(project, reel, manifest)

    keys = {entry["key"] for entry in linked if entry["clip_id"] == clip["clip_id"]}
    assert "mixed" in keys
    assert all(not entry["missing"] for entry in linked)
    assert media.media_path(reel, manifest["clips"][0]).is_file()
