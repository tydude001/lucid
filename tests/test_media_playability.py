"""`media.playability` against real encodes, because the verdict is about bytes.

Every case here is a file ffmpeg and melt read without complaint and a browser
does not, which is the whole reason the function exists: "lucid can edit this"
and "the preview pane can show this" are different questions, and only the
second one has an answer that changes with the container and the pixel format.

Real encodes rather than fabricated probe output — a stub would pin the parsing
and not the thing that actually goes wrong, which is ffprobe reporting a field
under a name or a value the checks did not anticipate (`High 10` vs `high10`,
`hev1` vs `hvc1`).
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from lucid import media

needs_ffmpeg = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg/ffprobe are not installed",
)

pytestmark = needs_ffmpeg


def _encode(path: Path, *args: str, source: str = "testsrc=size=160x120:rate=24:duration=1") -> Path:
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", source, *args, str(path)],
        check=True,
        capture_output=True,
    )
    return path


def _needs_encoder(name: str) -> None:
    encoders = subprocess.run(
        ["ffmpeg", "-hide_banner", "-encoders"], capture_output=True, text=True, check=True
    ).stdout
    if f" {name} " not in encoders:
        pytest.skip(f"this ffmpeg has no {name} encoder")


def test_plain_h264_in_mp4_is_playable(tmp_path: Path) -> None:
    """The baseline the other cases are deviations from, and the shape every
    piece of the Scream footage is in — so a regression here would black out a
    preview that works today."""
    path = _encode(tmp_path / "ok.mp4", "-c:v", "libx264", "-pix_fmt", "yuv420p")

    verdict = media.playability(path)

    assert verdict["playable"] is True
    assert verdict["reason"] is None
    assert verdict["video_codec"] == "h264"
    assert verdict["pix_fmt"] == "yuv420p"


def test_a_pcm_wav_stays_playable(tmp_path: Path) -> None:
    """The VO case, pinned deliberately: `pcm_s16le` is on no video codec list
    and browsers play it anyway. The transport's own element loads this file on
    every VO project, so a stricter audio list would break the pane that works."""
    path = _encode(tmp_path / "vo.wav", source="sine=frequency=440:duration=1")

    verdict = media.playability(path)

    assert verdict["playable"] is True
    assert verdict["audio_codec"] == "pcm_s16le"
    assert verdict["video_codec"] is None


def test_hevc_is_refused_and_the_tag_is_named(tmp_path: Path) -> None:
    """The case the wiki row was opened for. `hev1` vs `hvc1` decides iOS Safari
    and neither plays here, so the tag rides along in the message rather than in
    the verdict — a person reading "tagged hev1" can tell this from the other
    HEVC failure without re-probing."""
    _needs_encoder("libx265")
    path = _encode(tmp_path / "h265.mp4", "-c:v", "libx265", "-tag:v", "hev1", "-pix_fmt", "yuv420p")

    verdict = media.playability(path)

    assert verdict["playable"] is False
    assert "hevc" in verdict["reason"]
    assert "hev1" in verdict["reason"]


def test_ten_bit_h264_is_refused_on_the_pixel_format_not_the_codec(tmp_path: Path) -> None:
    """`h264` passes the codec gate and the file still will not decode, which is
    why the pixel format is checked separately instead of being assumed from the
    codec name."""
    path = _encode(
        tmp_path / "main10.mp4", "-c:v", "libx264", "-profile:v", "high10", "-pix_fmt", "yuv420p10le"
    )

    verdict = media.playability(path)

    assert verdict["playable"] is False
    assert verdict["video_codec"] == "h264"
    assert "yuv420p10le" in verdict["reason"]


def test_a_container_browsers_do_not_open_is_refused_before_the_codecs(tmp_path: Path) -> None:
    """Perfectly playable H.264 in a Matroska file. The refusal has to come from
    the container, and the message has to say so — "h264 is fine" is exactly the
    wrong thing to conclude from the streams here."""
    path = _encode(tmp_path / "fine.mkv", "-c:v", "libx264", "-pix_fmt", "yuv420p")

    verdict = media.playability(path)

    assert verdict["playable"] is False
    assert ".mkv" in verdict["reason"]


def test_an_undecodable_audio_track_refuses_the_whole_file(tmp_path: Path) -> None:
    """A browser plays a file or it does not; there is no partial state where the
    picture shows and the sound is missing, so an audio codec it cannot decode
    refuses the file even though the video stream is fine."""
    _needs_encoder("ac3")
    path = _encode(tmp_path / "ac3.mp4", "-c:a", "ac3", source="sine=frequency=440:duration=1")

    verdict = media.playability(path)

    assert verdict["playable"] is False
    assert "ac3" in verdict["reason"]


def test_a_missing_file_raises_rather_than_answering_unplayable(tmp_path: Path) -> None:
    """"Unplayable" would be a true statement about a file that is not there and
    a useless one — the caller's next move for a missing file is nothing like its
    next move for a bad codec."""
    with pytest.raises(media.MediaError, match="no such media file"):
        media.playability(tmp_path / "absent.mp4")
