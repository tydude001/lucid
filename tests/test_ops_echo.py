"""What a word range echoes back — the resolution, not the edit.

The defect these guard against is an index one word past the intended phrase:
six cues in the Scream shot plan had it, and every one read perfectly well as
text (HISTORY.md § 3). So the assertions here are mostly about the *neighbours*
of a range, which is the only place that error is visible.

`test_server_stdio.py` checks the same echo is actually wired into the tool;
this file exercises the resolution on its own.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from proofcut import ops
from proofcut import transcript as tx

#: Ten words, 0.3s each, 0.2s of silence between them.
WORDS = [{"word": f"w{n}", "start": n * 0.5, "end": n * 0.5 + 0.3} for n in range(10)]


@pytest.fixture
def parsed(tmp_path: Path) -> tx.Transcript:
    path = tmp_path / "vo.json"
    path.write_text(json.dumps({"language": "en", "words": WORDS}), encoding="utf-8")
    return tx.load(path, clip_id="vo")


def test_echo_resolves_indices_to_the_words_they_address(parsed: tx.Transcript) -> None:
    echo = ops._echo(parsed, 4, 5, 2.0, 2.8)

    assert echo["text"] == "w4 w5"
    assert echo["word_start"] == pytest.approx(2.0)
    assert echo["word_end"] == pytest.approx(2.8)


def test_echo_carries_the_words_either_side_of_the_range(parsed: tx.Transcript) -> None:
    """An off-by-one is only visible against where the phrase should have ended."""
    echo = ops._echo(parsed, 4, 5, 2.0, 2.8)

    assert [w["index"] for w in echo["context_before"]] == [1, 2, 3]
    assert [w["index"] for w in echo["context_after"]] == [6, 7, 8]
    # Context is strictly outside the range — it is what the range is *not*.
    inside = {4, 5}
    assert not inside & {w["index"] for w in echo["context_before"] + echo["context_after"]}


def test_echo_context_clamps_at_both_ends(parsed: tx.Transcript) -> None:
    """A range at the edge of the transcript has fewer neighbours, not negative ones."""
    first = ops._echo(parsed, 0, 1, 0.0, 0.8)
    assert first["context_before"] == []
    assert [w["index"] for w in first["context_after"]] == [2, 3, 4]

    last = ops._echo(parsed, 8, 9, 4.0, 4.8)
    assert [w["index"] for w in last["context_before"]] == [5, 6, 7]
    assert last["context_after"] == []


def test_unpadded_range_reaches_no_neighbour(parsed: tx.Transcript) -> None:
    echo = ops._echo(parsed, 4, 5, 2.0, 2.8)
    assert "pad_reach" not in echo


def test_pad_reach_names_the_neighbours_the_padding_eats(parsed: tx.Transcript) -> None:
    """`pad` is in seconds and the echoed text is not, so the words alone
    understate a padded cut. Both neighbours here are only *partly* covered —
    0.05s of each — which is the overlap-not-containment case (CLAUDE.md).
    """
    echo = ops._echo(parsed, 4, 5, 1.75, 3.05)

    reach = {w["index"]: w["side"] for w in echo["pad_reach"]}
    assert reach == {3: "before", 6: "after"}
    # The text still names only the range itself; pad_reach is the correction.
    assert echo["text"] == "w4 w5"


def test_pad_reach_is_an_overlap_test_not_a_containment_one(parsed: tx.Transcript) -> None:
    """Containment would report neither of these; overlap reports both."""
    contained = ops._pad_reach(parsed, 4, 5, 1.5, 3.3)
    partial = ops._pad_reach(parsed, 4, 5, 1.79, 3.01)

    assert [w["index"] for w in contained] == [3, 6]
    assert [w["index"] for w in partial] == [3, 6]


def test_overlap_words_is_an_overlap_test_not_containment(parsed: tx.Transcript) -> None:
    """A word whose (inflated, suspect-style) duration spans past `hi` still
    counts, because `word.start < hi` — containment would miss it.
    """
    words = tx.Transcript(
        clip_id="vo",
        words=(
            tx.Word(index=0, text="so", start=0.0, end=0.3),
            tx.Word(index=1, text="bit", start=0.5, end=4.86),
            tx.Word(index=2, text="on", start=5.0, end=5.3),
        ),
    )
    overlapping = ops._overlap_words(words, 0.4, 0.6)
    assert [w["index"] for w in overlapping] == [1]


def test_nearest_context_anchors_on_the_flanking_words_when_nothing_overlaps(
    parsed: tx.Transcript,
) -> None:
    """A `[lo, hi)` landing in silence between two words returns the two
    flanking words as context, with nothing "inside".
    """
    ctx = ops._nearest_context(parsed, 2.35, 2.45)
    assert [w["index"] for w in ctx["context_before"]] == [2, 3, 4]
    assert [w["index"] for w in ctx["context_after"]] == [5, 6, 7]
