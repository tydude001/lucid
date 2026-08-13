"""The transcript index — parsing, and word-range addressing."""

from __future__ import annotations

import json

import pytest

from lucid import transcript as tx

WHISPER = {
    "language": "en",
    "segments": [
        {"words": [{"word": " The", "start": 0.0, "end": 0.4}, {"word": " first", "start": 0.4, "end": 0.9}]},
        {"words": [{"word": " twelve", "start": 1.0, "end": 1.6}, {"word": " minutes.", "start": 1.6, "end": 2.2}]},
    ],
}


def _parse(payload: dict | None = None) -> tx.Transcript:
    return tx.parse_whisper(payload or WHISPER, clip_id="vo")


def test_parses_openai_whisper_segments() -> None:
    parsed = _parse()
    assert [w.text for w in parsed.words] == ["The", "first", "twelve", "minutes."]
    assert [w.index for w in parsed.words] == [0, 1, 2, 3]
    assert parsed.language == "en"


def test_parses_flat_word_list() -> None:
    flat = {"words": [{"word": "hello", "start": 0.0, "end": 0.5}]}
    assert [w.text for w in _parse(flat).words] == ["hello"]


def test_rejects_segment_only_timings() -> None:
    """Segment-level timings would put cuts mid-word, so this must not degrade."""
    with pytest.raises(tx.TranscriptError, match="word timestamps"):
        _parse({"segments": [{"start": 0.0, "end": 2.0, "text": "no words here"}]})


def test_span_is_inclusive_of_both_ends() -> None:
    parsed = _parse()
    assert parsed.span(1, 2) == (0.4, 1.6)
    # A single word is a valid range.
    assert parsed.span(0, 0) == (0.0, 0.4)


def test_span_rejects_out_of_range_and_backwards() -> None:
    parsed = _parse()
    with pytest.raises(tx.TranscriptError, match="outside this transcript"):
        parsed.span(0, 99)
    with pytest.raises(tx.TranscriptError, match="backwards"):
        parsed.span(3, 1)


def test_find_ignores_case_and_punctuation() -> None:
    matches = _parse().find("TWELVE minutes")
    assert len(matches) == 1
    assert (matches[0]["first_word"], matches[0]["last_word"]) == (2, 3)
    assert matches[0]["start"] == 1.0 and matches[0]["end"] == 2.2


def test_find_returns_every_occurrence() -> None:
    """Retake trimming depends on this: take 1 and take 2 both have to show up."""
    doubled = {
        "words": [
            {"word": "test", "start": 0.0, "end": 0.5},
            {"word": "it", "start": 0.5, "end": 0.8},
            {"word": "test", "start": 1.0, "end": 1.5},
            {"word": "it", "start": 1.5, "end": 1.8},
        ]
    }
    matches = _parse(doubled).find("test it")
    assert [(m["first_word"], m["last_word"]) for m in matches] == [(0, 1), (2, 3)]


def test_roundtrips_through_the_cache(tmp_path) -> None:
    parsed = _parse()
    dest = tmp_path / "vo.json"
    tx.save(parsed, dest)
    reloaded = tx.load(dest, clip_id="vo")
    assert [w.as_dict() for w in reloaded.words] == [w.as_dict() for w in parsed.words]


def test_load_reports_a_missing_file_clearly(tmp_path) -> None:
    with pytest.raises(tx.TranscriptError, match="no transcript at"):
        tx.load(tmp_path / "absent.json", clip_id="vo")


def test_load_reports_bad_json(tmp_path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(tx.TranscriptError, match="not valid JSON"):
        tx.load(bad, clip_id="vo")


def _words(*spans: tuple[str, float, float]) -> tuple[tx.Word, ...]:
    return tuple(
        tx.Word(index=i, text=t, start=a, end=b) for i, (t, a, b) in enumerate(spans)
    )


def test_find_overlaps_is_silent_on_a_clean_transcript() -> None:
    """Words that merely touch at a boundary are the normal case, not a seam."""
    assert tx.find_overlaps(_words(("a", 0.0, 0.5), ("b", 0.5, 1.0), ("c", 1.0, 1.5))) == []


def test_find_overlaps_ignores_float_noise_at_a_shared_boundary() -> None:
    """0.9 against 0.8999999999999999 is arithmetic, not two words at once."""
    assert tx.find_overlaps(_words(("a", 0.0, 0.9), ("b", 0.8999999999999999, 1.4))) == []


def test_find_overlaps_flags_a_word_starting_before_the_last_one_ends() -> None:
    seams = tx.find_overlaps(_words(("horror", 9.76, 10.12), ("whore", 9.78, 9.98)))
    assert len(seams) == 1
    assert seams[0]["first_word"] == 0 and seams[0]["last_word"] == 1
    assert seams[0]["text"] == "horror whore"
    assert seams[0]["worst"] == 0.34


def test_find_overlaps_reports_one_splice_as_one_seam() -> None:
    """The Scream VO's `Stu do - spend`: three overlapping pairs, one event.

    Reporting per pair would make five findings out of the two real splices
    in this fixture, which is the failure `verify.find_adjacent_repeats`
    already collapses its candidates to avoid.
    """
    seams = tx.find_overlaps(
        _words(
            ("Billy", 149.04, 149.38),
            ("Billions", 149.08, 149.64),
            ("and", 149.38, 149.62),
            ("Stu", 149.62, 149.88),
            ("do", 149.64, 149.96),
            ("-", 149.88, 149.98),
            ("spend", 149.96, 150.40),
        )
    )
    assert [(s["first_word"], s["last_word"]) for s in seams] == [(0, 2), (3, 6)]
    assert [s["pairs"] for s in seams] == [2, 3]
    assert [s["text"] for s in seams] == ["Billy Billions and", "Stu do - spend"]


def test_a_seams_extent_is_not_read_off_its_last_word() -> None:
    """An invented word can end *before* the word it follows — that inversion
    is the finding, so `end` has to be the widest end in the range."""
    seam = tx.find_overlaps(_words(("horror", 9.76, 10.12), ("whore", 9.78, 9.98)))[0]
    assert seam["start"] == 9.76
    assert seam["end"] == 10.12


def test_find_overlaps_handles_a_zero_width_word() -> None:
    """Whisper emits `start == end` often (CLAUDE.md). One that lands exactly
    on the previous word's end is not an overlap; one that lands before it is.
    """
    assert tx.find_overlaps(_words(("sat", 30.98, 31.28), ("-", 31.28, 31.28))) == []
    seams = tx.find_overlaps(_words(("sat", 30.98, 31.28), ("-", 30.98, 30.98)))
    assert len(seams) == 1 and seams[0]["worst"] == 0.3


def test_find_overlaps_on_an_empty_or_single_word_transcript() -> None:
    assert tx.find_overlaps(()) == []
    assert tx.find_overlaps(_words(("alone", 0.0, 0.5))) == []


# -- find_repeats: the ported vo_windows.py --repeats -----------------------


def _run(*texts: str, word_len: float = 0.3) -> tuple[tuple[tx.Word, ...], float]:
    """`n` words in a row, each `word_len` long and back-to-back, starting at
    0.0. Returns the words and the last word's own `end`, so a caller can
    place a second run some exact number of seconds after the first.
    """
    spans = []
    t = 0.0
    for text in texts:
        spans.append((text, t, t + word_len))
        t += word_len
    return _words(*spans), t


def _two_takes(phrase: list[str], *, gap: float) -> tuple[tx.Word, ...]:
    """The phrase, spoken twice, `gap` seconds apart — the shape a retake
    makes when whisper writes both readings out as ordinary words."""
    first, end = _run(*phrase)
    second, _ = _run(*phrase)
    shifted = tuple(
        tx.Word(index=w.index + len(first), text=w.text, start=w.start + end + gap, end=w.end + end + gap)
        for w in second
    )
    return first + shifted


def test_find_repeats_is_silent_on_a_clean_transcript() -> None:
    words, _ = _run("the", "best", "twelve", "minutes", "of", "horror")
    assert tx.find_repeats(words) == []


def test_find_repeats_flags_a_phrase_said_twice_close_together() -> None:
    """The Scream VO's shape, in miniature: a retake read straight back into
    the transcript as ordinary, cleanly-timed words."""
    words = _two_takes(["the", "best", "twelve", "minutes"], gap=0.4)
    repeats = tx.find_repeats(words)
    assert len(repeats) == 1
    hit = repeats[0]
    assert hit["words"] == 4
    assert hit["first_word"] == 0 and hit["last_word"] == 7
    assert hit["second_word"] == 4
    assert hit["text"] == "the best twelve minutes"
    assert hit["gap"] == pytest.approx(0.4)


def test_find_repeats_respects_max_gap() -> None:
    """Two readings of the same line ten seconds apart are not back-to-back —
    reading it as a retake would flag every callback in the film."""
    words = _two_takes(["the", "best", "twelve", "minutes"], gap=10.0)
    assert tx.find_repeats(words) == []
    # Raising max_gap to cover it finds the same hit again.
    assert len(tx.find_repeats(words, max_gap=10.0)) == 1


def test_find_repeats_respects_min_words() -> None:
    """A two-word echo is below the default floor; explicitly lowering it
    reaches the same repeat."""
    words = _two_takes(["stop", "it"], gap=0.2)
    assert tx.find_repeats(words) == []
    hits = tx.find_repeats(words, min_words=2)
    assert len(hits) == 1 and hits[0]["words"] == 2


def test_find_repeats_prefers_the_longest_match_at_each_start() -> None:
    """`a a a a` could be read as two 1-word repeats or one 2-word repeat —
    the longer reading is preferred, so it is reported once, not twice."""
    words, _ = _run("a", "a", "a", "a")
    hits = tx.find_repeats(words, min_words=1, max_words=3, max_gap=1.0)
    assert len(hits) == 1
    assert hits[0]["words"] == 2
    assert hits[0]["first_word"] == 0 and hits[0]["last_word"] == 3


def test_find_repeats_on_an_empty_or_single_word_transcript() -> None:
    assert tx.find_repeats(()) == []
    assert tx.find_repeats(_words(("alone", 0.0, 0.5))) == []


def test_real_whisper_dump_shape(tmp_path) -> None:
    """The exact keys openai-whisper emits, including the probability field."""
    payload = {
        "text": " The first",
        "language": "en",
        "segments": [
            {
                "id": 0,
                "seek": 0,
                "start": 2.92,
                "end": 5.0,
                "text": " The first",
                "tokens": [1, 2],
                "words": [
                    {"word": " The", "start": 2.92, "end": 3.4, "probability": 0.72},
                    {"word": " first", "start": 3.4, "end": 3.8, "probability": 0.9},
                ],
            }
        ],
    }
    path = tmp_path / "VO.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    parsed = tx.load(path, clip_id="vo")
    assert parsed.span(0, 1) == (2.92, 3.8)
