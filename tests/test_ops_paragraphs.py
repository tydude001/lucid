"""The transcript's paragraph breaks — word-order-driven, not duration-driven.

`ops._paragraphs` is a pure function over word order and timing: no ffmpeg, no
project, no I/O — the same rationale test_ops_attenuate.py gives for isolating
`ops._classify_noise_events` the same way. The field's presence on a real
`timeline_view` call is checked in test_server_stdio.py's timeline_view
section, wired into the real server.
"""

from __future__ import annotations

from proofcut import ops
from proofcut import transcript as tx

Spec = tuple[str, float, float]


def _words(specs: list[Spec]) -> tuple[tx.Word, ...]:
    return tuple(
        tx.Word(index=i, text=text, start=start, end=end)
        for i, (text, start, end) in enumerate(specs)
    )


def _plain(n: int) -> list[Spec]:
    """`n` ordinary words, one per second, none of them sentence-ending."""
    return [(f"w{i}", float(i), float(i) + 0.9) for i in range(n)]


def test_a_short_transcript_is_one_paragraph() -> None:
    paragraphs = ops._paragraphs(_words(_plain(10)))
    assert set(paragraphs.values()) == {0}


def test_a_sentence_end_alone_is_not_enough_to_break() -> None:
    """Punctuation with neither the word count nor the silence behind it does
    nothing — both arms require their own threshold, and this trips neither.
    """
    specs = _plain(5)
    specs[2] = ("done.", specs[2][1], specs[2][2])
    paragraphs = ops._paragraphs(_words(specs))
    assert set(paragraphs.values()) == {0}


def test_forty_words_and_a_sentence_end_breaks_even_with_almost_no_gap() -> None:
    """The word-count arm is the guarantee: it fires on count alone."""
    specs = _plain(45)
    specs[39] = ("done.", 39.0, 39.9)
    specs[40] = ("next", 40.0, 40.9)  # 0.1s gap, nowhere near PARAGRAPH_GAP_SILENCE
    paragraphs = ops._paragraphs(_words(specs))

    assert paragraphs[39] == 0
    assert paragraphs[40] == 1
    assert len({paragraphs[i] for i in range(40)}) == 1


def test_a_wide_gap_breaks_early_once_fifteen_words_are_in() -> None:
    """The opportunistic arm: >=15 words plus >=0.75s of silence after the
    sentence end breaks well short of the 40-word guarantee.
    """
    specs = _plain(20)
    specs[14] = ("done.", 14.0, 14.9)
    specs[15] = ("next", 16.5, 17.0)  # gap = 1.6s
    paragraphs = ops._paragraphs(_words(specs))

    assert paragraphs[14] == 0
    assert paragraphs[15] == 1


def test_a_wide_gap_before_fifteen_words_does_not_break() -> None:
    """The word count is a floor under the gap arm, not just under the
    guarantee — an early sentence end with silence after it still waits.
    """
    specs = _plain(20)
    specs[5] = ("done.", 5.0, 5.9)
    specs[6] = ("next", 8.0, 8.5)  # gap = 2.1s, but only 6 words in
    paragraphs = ops._paragraphs(_words(specs))
    assert set(paragraphs.values()) == {0}


def test_a_short_gap_after_fifteen_words_does_not_break() -> None:
    """The gap arm's own threshold — 0.75s — is not satisfied by an ordinary
    pause between sentences.
    """
    specs = _plain(20)
    specs[14] = ("done.", 14.0, 14.9)
    specs[15] = ("next", 15.2, 15.7)  # gap = 0.3s
    paragraphs = ops._paragraphs(_words(specs))
    assert set(paragraphs.values()) == {0}


def test_question_and_exclamation_marks_end_a_sentence_too() -> None:
    specs = _plain(20)
    specs[14] = ("really?", 14.0, 14.9)
    specs[15] = ("next", 16.0, 16.5)
    paragraphs = ops._paragraphs(_words(specs))
    assert paragraphs[15] == 1

    specs2 = _plain(20)
    specs2[14] = ("stop!", 14.0, 14.9)
    specs2[15] = ("next", 16.0, 16.5)
    paragraphs2 = ops._paragraphs(_words(specs2))
    assert paragraphs2[15] == 1


def test_a_sentence_end_on_the_final_word_creates_no_trailing_paragraph() -> None:
    """Nothing follows the last word, so a break there would only number a
    paragraph that holds no words — the check is skipped rather than firing
    into empty air.
    """
    specs = _plain(41)
    specs[40] = ("done.", 40.0, 40.9)
    paragraphs = ops._paragraphs(_words(specs))
    assert set(paragraphs.values()) == {0}


def test_an_inflated_duration_can_only_suppress_a_break_never_invent_one() -> None:
    """CLAUDE.md's rule about durations, applied here: a word's `end` pushed
    later by a swallowed retake can only shrink the gap to the next word, so
    it can defeat the opportunistic arm but never trigger a break the true
    audio would not support.
    """
    specs = _plain(20)
    specs[14] = ("done.", 14.0, 14.9)
    specs[15] = ("next", 15.5, 16.0)
    # True gap would be 0.6s (no break); inflate word 14's end to swallow a
    # retake and the *reported* gap only shrinks further, still no break.
    inflated = list(specs)
    inflated[14] = ("done.", 14.0, 15.2)
    paragraphs = ops._paragraphs(_words(inflated))
    assert set(paragraphs.values()) == {0}


def test_multiple_breaks_number_paragraphs_in_order() -> None:
    specs = _plain(20)
    specs[14] = ("first.", 14.0, 14.9)
    specs[15] = ("next", 16.5, 17.0)
    specs[19] = ("last.", 22.5, 23.0)
    words = _words(specs)
    paragraphs = ops._paragraphs(words)

    assert paragraphs[14] == 0
    assert paragraphs[15] == 1
    # Word 19 is both a sentence end and the last word in the transcript —
    # nothing follows it to start a third paragraph with, so it stays in the
    # second.
    assert paragraphs[19] == 1
