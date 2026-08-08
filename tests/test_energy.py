"""The energy envelope, on audio built to have a known answer.

The cases here are the ones the method exists for. The load-bearing one is
`test_a_hole_in_the_word_map_that_holds_speech_is_reported`: a stretch the
transcript calls empty, with a voice in it. That is the shape of the defect
that beat a correctly run single-pass verify on the Scream v1 export — a 4.12 s
"gap" between two words holding 2.4 s of speech — and no transcript-versus-
transcript comparison can see it, because both transcripts agree it is silence.

Synthetic audio rather than a fixture file: the point of each test is that the
answer is known by construction, which a recording cannot give you.
"""

from __future__ import annotations

import array
import math
import shutil
import struct
import wave
from pathlib import Path

import pytest

from lucid import energy

RATE = energy.RATE


def _tone(
    duration: float, bursts: list[tuple[float, float]], *, level: int = 9000, bed: int = 0
) -> array.array:
    """Samples with a tone during each burst, and an optional bed throughout."""
    out = array.array("h")
    for i in range(int(RATE * duration)):
        t = i / RATE
        value = bed * math.sin(2 * math.pi * 90 * t)
        if any(a <= t < b for a, b in bursts):
            value += level * math.sin(2 * math.pi * 220 * t)
        out.append(int(max(-32768, min(32767, value))))
    return out


# -- the envelope itself --------------------------------------------------


def test_the_envelope_is_one_frame_per_20ms() -> None:
    env = energy.envelope(_tone(1.0, []))

    assert len(env) == pytest.approx(1.0 / energy.FRAME, abs=1)


def test_a_partial_trailing_frame_is_dropped_rather_than_read_as_quiet() -> None:
    """Averaged over fewer samples it would look quieter than it is."""
    whole = energy.envelope(_tone(1.0, [(0.0, 1.0)]))
    ragged = energy.envelope(_tone(1.0, [(0.0, 1.0)])[: -RATE // 100])

    assert len(ragged) == len(whole) - 1
    assert ragged[-1] == pytest.approx(whole[-2])


def test_loud_frames_read_loud_and_silence_reads_as_the_floor() -> None:
    env = energy.envelope(_tone(2.0, [(0.0, 1.0)]))
    loud, quiet = env[: len(env) // 2 - 1], env[len(env) // 2 + 1 :]

    assert min(loud) > 1000
    assert max(quiet) == 0


# -- the arbitration ------------------------------------------------------


def test_a_hole_in_the_word_map_that_holds_speech_is_reported() -> None:
    """The defect this module exists for, in miniature.

    Three bursts of sound; the word map accounts for the first and the third.
    The middle one is a take nothing wrote down, and the audio says so
    regardless of what any transcript claims about that stretch.
    """
    env = energy.envelope(_tone(12.0, [(0.0, 2.0), (4.0, 6.5), (9.0, 11.0)]))
    words = [(0.0, 2.0), (9.0, 11.0)]

    result = energy.loud_gaps(words, env)

    assert len(result["gaps"]) == 1
    gap = result["gaps"][0]
    assert (gap["start"], gap["end"]) == (2.0, 9.0)
    assert gap["sound_seconds"] == pytest.approx(2.5, abs=0.1)
    assert gap["loudest_run"]["start"] == pytest.approx(4.0, abs=0.05)
    assert gap["loudest_run"]["end"] == pytest.approx(6.5, abs=0.05)


def test_a_gap_that_is_genuinely_silent_is_not_reported() -> None:
    """Every ordinary pause is a gap. Reporting them would bury the real one."""
    env = energy.envelope(_tone(12.0, [(0.0, 2.0), (9.0, 11.0)]))

    assert energy.loud_gaps([(0.0, 2.0), (9.0, 11.0)], env)["gaps"] == []


def test_a_click_in_a_gap_is_below_the_floor_of_attention() -> None:
    """A breath, a mouth noise or a chair does not reach `min_sound`."""
    env = energy.envelope(_tone(12.0, [(0.0, 2.0), (5.0, 5.15), (9.0, 11.0)]))

    assert energy.loud_gaps([(0.0, 2.0), (9.0, 11.0)], env)["gaps"] == []


def test_a_short_pause_is_not_asked_about_however_loud_it_is() -> None:
    """There is nowhere in half a second for a retake to hide."""
    env = energy.envelope(_tone(6.0, [(0.0, 2.0), (2.1, 2.6), (2.6, 5.0)]))
    words = [(0.0, 2.0), (2.6, 5.0)]

    assert energy.loud_gaps(words, env)["gaps"] == []


def test_the_threshold_calibrates_off_the_file_rather_than_a_fixed_dbfs() -> None:
    """A VO stem and a scored render sit ~20 dB apart; a fixed floor is wrong on one.

    The same material at a tenth the level has to produce the same verdict.
    """
    loud = energy.envelope(_tone(12.0, [(0.0, 2.0), (4.0, 6.5), (9.0, 11.0)]))
    faint = energy.envelope(_tone(12.0, [(0.0, 2.0), (4.0, 6.5), (9.0, 11.0)], level=900))
    words = [(0.0, 2.0), (9.0, 11.0)]

    assert len(energy.loud_gaps(words, loud)["gaps"]) == 1
    assert len(energy.loud_gaps(words, faint)["gaps"]) == 1
    # And the calibration moved with the material rather than staying put.
    assert energy.loud_gaps(words, faint)["speech_db"] < energy.loud_gaps(words, loud)["speech_db"]


def test_a_music_bed_under_everything_does_not_make_every_pause_a_gap() -> None:
    """v3 of the Scream essay has a 1996 score under the whole runtime.

    A bed means no stretch of the render is silent, so an absolute threshold
    would report every pause. The quiet tenth lands *on* the bed instead, and
    the midpoint up to speech level sits well above it.
    """
    env = energy.envelope(_tone(12.0, [(0.0, 2.0), (9.0, 11.0)], bed=700))

    result = energy.loud_gaps([(0.0, 2.0), (9.0, 11.0)], env)

    assert result["gaps"] == []
    assert result["quiet_db"] < result["threshold_db"] < result["speech_db"]


def test_a_take_hiding_under_a_music_bed_is_still_found() -> None:
    """The bed raises the floor; it must not raise it over the voice."""
    env = energy.envelope(_tone(12.0, [(0.0, 2.0), (4.0, 6.5), (9.0, 11.0)], bed=700))

    assert len(energy.loud_gaps([(0.0, 2.0), (9.0, 11.0)], env)["gaps"]) == 1


def test_the_calibration_is_reported_so_a_result_can_be_checked() -> None:
    """A number nobody can second-guess is not evidence of anything."""
    env = energy.envelope(_tone(12.0, [(0.0, 2.0), (9.0, 11.0)]))

    result = energy.loud_gaps([(0.0, 2.0), (9.0, 11.0)], env)

    assert set(result) >= {"speech_db", "quiet_db", "threshold_db", "min_gap", "min_sound"}
    assert result["speech_db"] < 0.0  # dBFS, so at or below full scale


def test_the_head_and_tail_of_a_render_are_not_gaps() -> None:
    """A title card hold or a music tail is not a hole between two words."""
    env = energy.envelope(_tone(12.0, [(0.0, 3.0), (5.0, 6.0), (8.0, 12.0)]))

    assert energy.loud_gaps([(5.0, 6.0)], env)["gaps"] == []


# -- suspect durations -----------------------------------------------------


def test_a_word_past_the_cap_is_flagged() -> None:
    """The Scream VO shape in miniature: one word far longer than the rest."""
    spans = [(0.0, 0.3), (0.3, 0.6), (0.6, 0.9), (0.9, 4.86), (4.86, 5.16)]

    flagged = energy.suspect_durations(spans)

    assert [f["index"] for f in flagged] == [3]
    assert flagged[0]["duration"] == pytest.approx(3.96, abs=0.01)


def test_ordinary_word_durations_are_not_flagged() -> None:
    spans = [(0.0, 0.3), (0.3, 0.6), (0.6, 0.9), (0.9, 1.2)]

    assert energy.suspect_durations(spans) == []


def test_no_spans_flags_nothing() -> None:
    assert energy.suspect_durations([]) == []


# -- refusals -------------------------------------------------------------


def test_measuring_nothing_is_refused_rather_than_answered() -> None:
    env = energy.envelope(_tone(2.0, [(0.0, 2.0)]))

    with pytest.raises(energy.EnergyError, match="no words to mask"):
        energy.loud_gaps([], env)
    with pytest.raises(energy.EnergyError, match="no envelope"):
        energy.loud_gaps([(0.0, 1.0)], [])


def test_a_word_map_from_a_different_recording_is_refused() -> None:
    """Silently calibrating off nothing would report the whole file as a gap."""
    env = energy.envelope(_tone(2.0, [(0.0, 2.0)]))

    with pytest.raises(energy.EnergyError, match="not the same recording"):
        energy.loud_gaps([(600.0, 601.0)], env)


# -- the decode ------------------------------------------------------------


needs_ffmpeg = pytest.mark.skipif(
    shutil.which("ffmpeg") is None, reason="ffmpeg is not installed"
)


@needs_ffmpeg
def test_decoding_real_audio_lands_on_the_same_clock_as_the_word_map(
    tmp_path: Path,
) -> None:
    """A resample that shifted time would misreport where a gap is.

    Written at 22050 Hz and read back at 8000, so the resample is exercised
    rather than being a no-op copy.
    """
    path = tmp_path / "render.wav"
    with wave.open(str(path), "w") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(22050)
        frames = bytearray()
        for i in range(int(22050 * 12.0)):
            t = i / 22050
            loud = any(a <= t < b for a, b in [(0.0, 2.0), (4.0, 6.5), (9.0, 11.0)])
            frames += struct.pack("<h", int(9000 * math.sin(2 * math.pi * 220 * t)) if loud else 0)
        out.writeframes(bytes(frames))

    result = energy.unaccounted_sound(path, [(0.0, 2.0), (9.0, 11.0)])

    assert len(result["gaps"]) == 1
    assert result["gaps"][0]["loudest_run"]["start"] == pytest.approx(4.0, abs=0.1)
    assert result["gaps"][0]["loudest_run"]["end"] == pytest.approx(6.5, abs=0.1)


def test_a_file_that_is_not_there_says_so(tmp_path: Path) -> None:
    with pytest.raises(energy.EnergyError, match="no media to measure"):
        energy.decode(tmp_path / "absent.wav")
