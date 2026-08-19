"""The attribution rule on its own, against the shape the design note measured.

The fixture here is the note's fixture rebuilt in the stdlib: alternating
turns, one mic hot per turn with the other carrying a bleed at a chosen dB.
It needs no ffmpeg and no model, which is the point — the rule is an energy
ratio and it should be pinnable without either. PLAN.md § The co-hosted
recording.

What it cannot show, and neither could the original: two real voices, two mic
gains, a room. Every accuracy number here is an upper bound, which is why
`MARGIN_DB` is reported by the op rather than trusted by it.
"""

from __future__ import annotations

import math
import wave
from pathlib import Path

import pytest

from lucid import speakers as spk

RATE = 16000
TURN = 3.0
TURNS = 8
LOUD = 8000.0


def _write_mic(dest: Path, *, hot_turns: set[int], bleed_db: float, seconds: float) -> Path:
    """One mic: full level inside its own turns, `bleed_db` down outside them."""
    bleed = LOUD * (10.0 ** (bleed_db / 20.0))
    frames = int(seconds * RATE)
    samples = bytearray()
    for n in range(frames):
        turn = int((n / RATE) // TURN)
        level = LOUD if turn in hot_turns else bleed
        value = int(level * math.sin(2 * math.pi * 200.0 * n / RATE))
        samples += int(value).to_bytes(2, "little", signed=True)
    with wave.open(str(dest), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(RATE)
        handle.writeframes(bytes(samples))
    return dest


def _turn_pair(tmp_path: Path, *, bleed_db: float = -12.0) -> tuple[spk.MicTrack, spk.MicTrack]:
    seconds = TURN * TURNS
    even = {t for t in range(TURNS) if t % 2 == 0}
    odd = {t for t in range(TURNS) if t % 2 == 1}
    a = _write_mic(tmp_path / "a.wav", hot_turns=even, bleed_db=bleed_db, seconds=seconds)
    b = _write_mic(tmp_path / "b.wav", hot_turns=odd, bleed_db=bleed_db, seconds=seconds)
    return spk.load_mic(a, "ana"), spk.load_mic(b, "ben")


def _words(*, per_turn: int = 5) -> list[tuple[tuple[float, float], str]]:
    """Word spans inside the turns, with the label each one should get."""
    out = []
    step = TURN / (per_turn + 1)
    for turn in range(TURNS):
        for k in range(per_turn):
            start = turn * TURN + step * (k + 1)
            out.append(((start, start + 0.2), "ana" if turn % 2 == 0 else "ben"))
    return out


def test_the_energy_ratio_separates_the_turns(tmp_path: Path) -> None:
    """The finding the note built the fixture for: the loudest mic is the speaker."""
    mics = _turn_pair(tmp_path)
    expected = _words()

    decisions = spk.attribute([span for span, _ in expected], mics)

    correct = sum(1 for d, (_, want) in zip(decisions, expected, strict=True) if d.label == want)
    assert correct == len(expected)


@pytest.mark.parametrize("bleed_db", [-6.0, -12.0, -18.0, -24.0])
def test_isolation_barely_moves_the_answer(tmp_path: Path, bleed_db: float) -> None:
    """Across 18 dB of isolation the rule holds — the note's own column.

    The mirror finding, which this cannot show and `speakers.py` records:
    transcribing each mic *separately* does not separate speakers at any of
    these levels, because half of each mic's transcript is the other person.
    """
    mics = _turn_pair(tmp_path, bleed_db=bleed_db)
    expected = _words()

    decisions = spk.attribute([span for span, _ in expected], mics)

    correct = sum(1 for d, (_, want) in zip(decisions, expected, strict=True) if d.label == want)
    assert correct == len(expected)


def test_simultaneous_speech_is_refused_rather_than_guessed(tmp_path: Path) -> None:
    """Both mics equally hot is the case the rule is at chance on, so it declines."""
    seconds = 4.0
    both = {0, 1}
    a = spk.load_mic(
        _write_mic(tmp_path / "a.wav", hot_turns=both, bleed_db=0.0, seconds=seconds), "ana"
    )
    b = spk.load_mic(
        _write_mic(tmp_path / "b.wav", hot_turns=both, bleed_db=0.0, seconds=seconds), "ben"
    )

    [decision] = spk.attribute([(1.0, 1.4)], [a, b])

    assert decision.label is None
    assert decision.margin_db is not None and decision.margin_db < 1.0
    assert "floor" in (decision.why or "")


def test_the_margin_floor_is_what_decides_a_close_call(tmp_path: Path) -> None:
    """The same word is called or refused by the floor alone, nothing else."""
    mics = _turn_pair(tmp_path, bleed_db=-3.0)
    span = [(TURN / 2, TURN / 2 + 0.2)]

    lenient = spk.attribute(span, mics, margin_db=1.0)[0]
    strict = spk.attribute(span, mics, margin_db=20.0)[0]

    assert lenient.label == "ana"
    assert strict.label is None
    # The measurement does not move with the floor — only the verdict does.
    assert strict.margin_db == pytest.approx(lenient.margin_db)


def test_a_zero_width_word_is_measured_rather_than_dropped(tmp_path: Path) -> None:
    """whisper emits `start == end` often, and a word with no span still has a speaker."""
    mics = _turn_pair(tmp_path)
    instant = TURN / 2

    [decision] = spk.attribute([(instant, instant)], mics)

    assert decision.label == "ana"


def test_a_word_past_the_end_of_the_mics_is_unmeasurable_not_silent(tmp_path: Path) -> None:
    """Not the same finding as an ambiguous word, and never a quiet `null`.

    A transcript running past the mics means they are not the same recording,
    which is a thing to go and fix rather than a word nobody can attribute.
    """
    mics = _turn_pair(tmp_path)

    [decision] = spk.attribute([(TURN * TURNS + 5.0, TURN * TURNS + 5.2)], mics)

    assert decision.label is None
    assert decision.margin_db is None
    assert "past the end" in (decision.why or "")


def test_silence_on_every_mic_is_its_own_refusal(tmp_path: Path) -> None:
    seconds = 2.0
    quiet = tmp_path / "q.wav"
    with wave.open(str(quiet), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(RATE)
        handle.writeframes(b"\x00\x00" * int(seconds * RATE))
    mics = [spk.load_mic(quiet, "ana"), spk.load_mic(quiet, "ben")]

    [decision] = spk.attribute([(0.5, 0.7)], mics)

    assert decision.label is None
    assert decision.margin_db is None
    assert "silent" in (decision.why or "")


def test_a_silent_runner_up_reads_as_a_capped_margin_not_infinity(tmp_path: Path) -> None:
    """Every margin crosses a JSON boundary, so none of them can be `inf`."""
    seconds = 2.0
    hot = spk.load_mic(
        _write_mic(tmp_path / "a.wav", hot_turns={0}, bleed_db=-200.0, seconds=seconds), "ana"
    )
    silent = tmp_path / "b.wav"
    with wave.open(str(silent), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(RATE)
        handle.writeframes(b"\x00\x00" * int(seconds * RATE))

    [decision] = spk.attribute([(0.5, 0.7)], [hot, spk.load_mic(silent, "ben")])

    assert decision.label == "ana"
    assert decision.margin_db == spk.MAX_MARGIN_DB
    assert math.isfinite(decision.margin_db)


def test_two_mics_sharing_a_label_are_refused() -> None:
    """Both speakers would read as one, and the transcript could not say so."""
    with pytest.raises(spk.SpeakerError, match="share a label"):
        spk.check_labels(["ana", "ana"])


def test_an_empty_label_is_refused() -> None:
    with pytest.raises(spk.SpeakerError, match="cannot be empty"):
        spk.check_labels(["ana", "  "])


def test_one_mic_is_not_something_to_compare() -> None:
    with pytest.raises(spk.SpeakerError, match="at least two"):
        spk.check_labels(["ana"])


def test_attribute_refuses_a_single_mic(tmp_path: Path) -> None:
    mics = _turn_pair(tmp_path)

    with pytest.raises(spk.SpeakerError, match="at least two"):
        spk.attribute([(0.0, 1.0)], mics[:1])


def test_a_negative_margin_is_not_a_floor(tmp_path: Path) -> None:
    mics = _turn_pair(tmp_path)

    with pytest.raises(spk.SpeakerError, match="dB"):
        spk.attribute([(0.0, 1.0)], mics, margin_db=-3.0)


def test_a_stereo_wav_is_refused_rather_than_read_at_the_wrong_level(tmp_path: Path) -> None:
    """A wrong sample width reads as a mic at a different level, which is the
    one quantity this module compares — so it refuses instead of guessing."""
    stereo = tmp_path / "s.wav"
    with wave.open(str(stereo), "wb") as handle:
        handle.setnchannels(2)
        handle.setsampwidth(2)
        handle.setframerate(RATE)
        handle.writeframes(b"\x00\x00\x00\x00" * RATE)

    with pytest.raises(spk.SpeakerError, match="16-bit mono"):
        spk.load_mic(stereo, "ana")


def test_summarise_keeps_the_two_refusals_apart(tmp_path: Path) -> None:
    """`ambiguous` and `unmeasurable` are different findings about the recording."""
    mics = _turn_pair(tmp_path)
    spans = [
        (TURN / 2, TURN / 2 + 0.2),  # clear, mic A
        (TURN * 1.5, TURN * 1.5 + 0.2),  # clear, mic B
        (TURN * TURNS + 5.0, TURN * TURNS + 5.2),  # past both mics
    ]

    summary = spk.summarise(spk.attribute(spans, mics, margin_db=3.0))

    assert summary["words"] == 3
    assert summary["attributed"] == 2
    assert summary["unmeasurable"] == 1
    assert summary["by_label"] == {"ana": 1, "ben": 1}
    assert summary["margins"]["min"] > 3.0
