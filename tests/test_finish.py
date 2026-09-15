"""`proofcut.finish` — the seam machinery `hold_check` and (later) `finish_check`
share (WORK-ORDERS ruling 5): `parse_ebur128`, `loudness`, `hold_seams`, all
built on a 48 kHz stdlib-`array` decode, no numpy (CLAUDE.md).

Synthetic audio built to a known shape, `test_energy.py`'s own discipline:
the point of each seam case is that the right answer is known by
construction, which a recording cannot give you.
"""

from __future__ import annotations

import math
import shutil
import struct
import subprocess
import wave
from pathlib import Path

import pytest

from proofcut import finish

needs_ffmpeg = pytest.mark.skipif(
    shutil.which("ffmpeg") is None, reason="ffmpeg is not installed"
)


def _wav(path: Path, *, duration: float, rate: int = 48000, tone_spans: list[tuple[float, float, int]]) -> None:
    """A mono 16-bit WAV, silent except where `tone_spans` (start, end, amplitude) say otherwise."""
    with wave.open(str(path), "w") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        frames = bytearray()
        for i in range(int(rate * duration)):
            t = i / rate
            value = 0.0
            for start, end, amp in tone_spans:
                if start <= t < end:
                    value = amp * math.sin(2 * math.pi * 220 * t)
                    break
            frames += struct.pack("<h", int(max(-32768, min(32767, value))))
        out.writeframes(bytes(frames))


# -- parse_ebur128 -----------------------------------------------------------


def test_parse_ebur128_reads_the_summary_block() -> None:
    stderr = """
[Parsed_ebur128_0 @ 0x1] t: 1.0    M: -23.0  S: -23.0     I: -23.1 LUFS       LRA:   1.0 LU
[Parsed_ebur128_0 @ 0x1] Summary:

  Integrated loudness:
    I:         -18.4 LUFS
    Threshold:  -28.9 LUFS

  Loudness range:
    LRA:         3.2 LU
    Threshold:  -38.5 LUFS
    LRA low:    -30.1 LUFS
    LRA high:   -26.9 LUFS

  True peak:
    Peak:        -1.2 dBTP
"""
    result = finish.parse_ebur128(stderr)
    assert result == {"integrated": -18.4, "lra": 3.2, "true_peak": -1.2}


def test_parse_ebur128_with_nothing_to_read_reports_none() -> None:
    assert finish.parse_ebur128("no ebur128 output here at all") == {
        "integrated": None,
        "lra": None,
        "true_peak": None,
    }


# -- loudness -----------------------------------------------------------------


@needs_ffmpeg
def test_loudness_measures_a_real_file(tmp_path: Path) -> None:
    path = tmp_path / "tone.wav"
    _wav(path, duration=3.0, tone_spans=[(0.0, 3.0, 12000)])

    result = finish.loudness(path)

    assert result["integrated"] is not None
    assert result["true_peak"] is not None
    # A full-scale-ish tone lands well above digital silence — loose bounds,
    # this is a sanity check on the mechanism, not a golden LUFS number.
    assert -20.0 < result["integrated"] < 5.0


@needs_ffmpeg
def test_loudness_refuses_a_missing_file(tmp_path: Path) -> None:
    with pytest.raises(finish.FinishError, match="no media"):
        finish.loudness(tmp_path / "nope.wav")


# -- master_loudness ----------------------------------------------------------


def _stream_seconds(path: Path, kind: str) -> float:
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", f"{kind}:0", "-show_entries", "stream=duration",
         "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True,
    )
    return float(probe.stdout.strip())


@needs_ffmpeg
@pytest.mark.skipif(shutil.which("ffprobe") is None, reason="ffprobe is not installed")
def test_a_master_keeps_the_audio_the_length_it_was(tmp_path: Path) -> None:
    """`loudnorm`'s frame timestamps run ahead of its samples, so a master
    carried one AAC packet claiming up to ~90 ms more than the 1024 samples it
    holds. Every sample after it played that late, and the stream read longer
    than its picture — 3.000 s became 3.100 s here, with the same samples
    decoded. On a real render the packet sits where loudnorm flushes its 3 s
    lookahead: 3 s before the end of both essay rebuilds and the agent trial's
    film, whose 47 ms overrun was enough for `spot_frames` to call it stale
    (`mapping_trusted` is half a frame).

    **The packets are the witness, and only their durations.** Decoding to PCM
    ignores timestamps, so a sample count cannot see this, and the long packet
    still abuts the next one, so a pts-contiguity check cannot either. TRIAL.md
    § The third trial — a whole film, the queue."""
    render = tmp_path / "render.mp4"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=s=160x90:r=24:d=3",
         "-f", "lavfi", "-i", "sine=f=220:d=3:sample_rate=48000", "-af", "volume=-20dB",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(render)],
        check=True,
    )
    audio_before, video_before = _stream_seconds(render, "a"), _stream_seconds(render, "v")

    report = finish.master_loudness(render, integrated=-16.0)

    assert report["after"]["integrated"] == pytest.approx(-16.0, abs=finish.MASTER_LU_TOLERANCE)
    half_frame = 0.5 / 24
    assert abs(_stream_seconds(render, "a") - audio_before) <= half_frame
    assert _stream_seconds(render, "v") == pytest.approx(video_before, abs=1e-6)
    packets = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries", "packet=pts,duration",
         "-of", "csv=p=0", str(render)],
        capture_output=True, text=True, check=True,
    ).stdout.split()
    stamps = [tuple(int(v) for v in line.strip(",").split(",")) for line in packets]
    frame = 1024  # AAC's own frame size
    long = [(pts, duration) for pts, duration in stamps[:-1] if duration > frame]
    assert not long, f"audio packets claiming more than one AAC frame: {long[:3]}"


# -- hold_seams ----------------------------------------------------------------


@needs_ffmpeg
def test_a_clean_cut_reports_no_fault(tmp_path: Path) -> None:
    """Tone stops well before the mark, silence either side of it — nothing
    still loud at the cut, nothing to cliff from."""
    path = tmp_path / "clean.wav"
    _wav(path, duration=6.0, tone_spans=[(0.0, 2.0, 9000)])

    rows = finish.hold_seams(path, [("cut", 3.0)])

    assert len(rows) == 1
    assert rows[0]["fault"] is None


@needs_ffmpeg
def test_a_word_cut_off_reports_still_loud(tmp_path: Path) -> None:
    """The tone plays straight through the mark — the last 150ms before it
    is loud, so the cut lands on a word or a line, not on silence."""
    path = tmp_path / "cutoff.wav"
    _wav(path, duration=6.0, tone_spans=[(0.0, 6.0, 8000)])

    rows = finish.hold_seams(path, [("cut", 3.0)])

    assert rows[0]["fault"] == "still_loud"
    assert rows[0]["peak_pre"] > finish.STILL_LOUD_DB


@needs_ffmpeg
def test_a_hard_drop_reports_a_noise_floor_cliff(tmp_path: Path) -> None:
    """A quiet room-tone-shaped level plays right up to the mark and then
    stops dead — not loud enough to be "still loud", but the drop to true
    silence after it is a cliff, not a fade."""
    path = tmp_path / "cliff.wav"
    _wav(path, duration=6.0, tone_spans=[(0.0, 3.0, 1465)])  # ~-30 dBFS RMS

    rows = finish.hold_seams(path, [("cut", 3.0)])

    assert rows[0]["fault"] == "noise_floor_cliff"
    assert rows[0]["peak_pre"] > finish.CLIFF_FLOOR_DB
    assert rows[0]["peak_pre"] - rows[0]["floor_post"] > finish.CLIFF_DROP_DB


@needs_ffmpeg
def test_hold_seams_reports_multiple_marks_from_one_decode(tmp_path: Path) -> None:
    path = tmp_path / "two.wav"
    _wav(path, duration=6.0, tone_spans=[(0.0, 2.0, 9000), (4.0, 6.0, 9000)])

    rows = finish.hold_seams(path, [("in", 2.0), ("out", 4.0)])

    assert [r["name"] for r in rows] == ["in", "out"]


@needs_ffmpeg
def test_hold_seams_refuses_a_missing_file(tmp_path: Path) -> None:
    with pytest.raises(finish.FinishError, match="no media"):
        finish.hold_seams(tmp_path / "nope.wav", [("cut", 1.0)])
