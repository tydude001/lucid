"""The comparison itself, with no ASR and no project on disk.

`verify.compare` is pure sequence work, so the cases that matter — a clean
render, a surviving retake, an over-long cut — are cheap to state exactly here.
The end-to-end wiring is checked over stdio in test_server_stdio.py.
"""

from __future__ import annotations

from lucid import verify


def test_tokens_normalise_away_punctuation_and_case() -> None:
    assert verify.tokens(["Hello, World!"]) == ["hello", "world"]
    # Multi-word strings flatten; apostrophes are part of the word, not noise.
    assert verify.tokens(["It's a", "cut."]) == ["it's", "a", "cut"]
    assert verify.tokens(["", "  ", "one"]) == ["one"]


def test_identical_sequences_are_a_clean_render() -> None:
    words = ["the", "killer", "calls", "from", "inside", "the", "house"]
    result = verify.compare(words, list(words))

    assert result["similarity"] == 1.0
    assert result["repeated"] == []
    assert result["dropped"] == []
    assert result["diff"] == []


def test_spelling_and_case_differences_do_not_register_as_changes() -> None:
    """The two sides are normalised before comparison, not after."""
    expected = verify.tokens(["The killer calls,", "from inside the house."])
    heard = verify.tokens(["the KILLER calls from inside the HOUSE"])

    assert verify.compare(expected, heard)["similarity"] == 1.0


def test_a_phrase_played_twice_is_reported_as_repeated() -> None:
    """The defect verify exists for: a retake whisper collapsed on the way in."""
    expected = ["w00", "w01", "w20", "w21", "w30", "w31"]
    heard = ["w00", "w01", "w20", "w21", "w20", "w21", "w30", "w31"]

    result = verify.compare(expected, heard)

    assert result["repeated"] == [{"text": "w20 w21", "at_heard_word": 4}]
    assert result["dropped"] == []
    assert result["similarity"] < 1.0


def test_extra_words_the_timeline_never_expected_are_not_called_repeats() -> None:
    """`repeated` means "played twice", not "unexpected" — the diff covers that."""
    expected = ["one", "two", "three"]
    heard = ["one", "two", "brand", "new", "three"]

    result = verify.compare(expected, heard)

    assert result["repeated"] == []
    assert any(line.startswith("+brand") for line in result["diff"])


def test_words_the_render_never_played_are_reported_as_dropped() -> None:
    """A cut that reached past its word range: the inverse failure."""
    expected = ["one", "two", "three", "four", "five"]
    heard = ["one", "two", "five"]

    result = verify.compare(expected, heard)

    assert result["dropped"] == [{"text": "three four", "at_expected_word": 2}]
    assert result["repeated"] == []


def test_a_single_missing_word_is_below_the_noise_floor() -> None:
    """One word differing between two passes is whisper, not an edit."""
    expected = ["one", "two", "three"]
    heard = ["one", "three"]

    assert verify.compare(expected, heard)["dropped"] == []


def test_the_diff_is_word_per_line() -> None:
    """So a 900-word transcript diffs as words, not as two changed paragraphs."""
    result = verify.compare(["alpha", "beta"], ["alpha", "gamma"])
    diff = result["diff"]

    assert diff[0].startswith("--- timeline") and diff[1].startswith("+++ render")
    assert "-beta" in diff and "+gamma" in diff
