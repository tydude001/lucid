"""Inline pause markers — `[N.Ns]` gaps rendered between word spans.

`ops._gap_after` is the one place both `_paragraphs`' opportunistic break and
`_word_placements`' `pause_after` field read a gap from (CLAUDE.md, docs/plans/DAYDREAM.md
§ Transcript document: "derive both from the same place"). These are pure
unit tests over `_gap_after` and `_word_placements` — no I/O — mirroring
tests/test_ops_paragraphs.py's style and construction helpers. Wire-level
coverage (a real `timeline_view` call) lives in test_server_stdio.py.
"""

from __future__ import annotations

import pytest

from lucid import ops
from lucid import timeline as tl
from lucid import transcript as tx

Spec = tuple[str, float, float]


def _words(specs: list[Spec]) -> tuple[tx.Word, ...]:
    return tuple(
        tx.Word(index=i, text=text, start=start, end=end)
        for i, (text, start, end) in enumerate(specs)
    )


def _plain(n: int) -> list[Spec]:
    """`n` ordinary words, one per second, none of them sentence-ending."""
    return [(f"w{i}", float(i), float(i) + 0.9) for i in range(n)]


def _uncut_edit(clip_id: str, duration: float) -> tl.Edit:
    """An edit whose one segment covers the whole source, unmodified."""
    return tl.Edit(segments=[tl.Segment(clip_id=clip_id, start=0.0, end=duration)])


def test_a_gap_under_threshold_gets_no_pause_after() -> None:
    specs = _plain(5)
    specs[1] = ("w1", 1.0, 1.6)
    specs[2] = ("w2", 1.9, 2.9)  # gap = 0.3s, under PAUSE_MARKER_MIN
    words = _words(specs)
    parsed = tx.Transcript(clip_id="vo", words=words)
    edit = _uncut_edit("vo", 10.0)

    placements = ops._word_placements(edit, "vo", parsed)
    assert "pause_after" not in placements[1]


def test_a_gap_at_or_over_threshold_gets_pause_after_with_its_duration() -> None:
    specs = _plain(5)
    specs[1] = ("w1", 1.0, 1.5)
    specs[2] = ("w2", 2.0, 3.0)  # gap = 0.5s, at/over PAUSE_MARKER_MIN
    words = _words(specs)
    parsed = tx.Transcript(clip_id="vo", words=words)
    edit = _uncut_edit("vo", 10.0)

    placements = ops._word_placements(edit, "vo", parsed)
    assert placements[1]["pause_after"]["duration"] == pytest.approx(0.5)

    specs2 = _plain(5)
    specs2[1] = ("w1", 1.0, 1.6)
    specs2[2] = ("w2", 2.8, 3.8)  # gap = 1.2s
    words2 = _words(specs2)
    parsed2 = tx.Transcript(clip_id="vo", words=words2)
    placements2 = ops._word_placements(edit, "vo", parsed2)
    assert placements2[1]["pause_after"]["duration"] == pytest.approx(1.2)


def test_an_inflated_duration_can_only_suppress_a_marker_never_invent_one() -> None:
    """Same construction as test_ops_paragraphs.py's identically-named test:
    inflate a word's `end` so the true 0.6s gap (which would mark) reports
    smaller and the marker is suppressed.
    """
    specs = _plain(5)
    specs[1] = ("w1", 1.0, 1.6)
    specs[2] = ("w2", 2.2, 3.2)  # true gap = 0.6s, clears PAUSE_MARKER_MIN
    edit = _uncut_edit("vo", 10.0)

    words = _words(specs)
    parsed = tx.Transcript(clip_id="vo", words=words)
    placements = ops._word_placements(edit, "vo", parsed)
    assert placements[1]["pause_after"]["duration"] == pytest.approx(0.6)

    # Inflate word 1's end to swallow a retake: reported gap shrinks to 0.1s,
    # under threshold — the marker is suppressed, never invented larger.
    inflated_specs = list(specs)
    inflated_specs[1] = ("w1", 1.0, 2.1)
    inflated_words = _words(inflated_specs)
    inflated_parsed = tx.Transcript(clip_id="vo", words=inflated_words)
    inflated_placements = ops._word_placements(edit, "vo", inflated_parsed)
    assert "pause_after" not in inflated_placements[1]


def test_pause_after_present_is_false_once_the_gap_is_cut_away() -> None:
    specs = _plain(5)
    specs[1] = ("w1", 1.0, 1.6)
    specs[2] = ("w2", 2.8, 3.8)  # gap = 1.2s, source [1.6, 2.8)
    words = _words(specs)
    parsed = tx.Transcript(clip_id="vo", words=words)

    # The whole surrounding region survives: present is True.
    whole_edit = _uncut_edit("vo", 10.0)
    placements = ops._word_placements(whole_edit, "vo", parsed)
    assert placements[1]["pause_after"]["present"] is True

    # Segments already exclude the gap's source interval [1.6, 2.8): present
    # is False, even though both flanking words still survive.
    cut_edit = tl.Edit(
        segments=[
            tl.Segment(clip_id="vo", start=0.0, end=1.6),
            tl.Segment(clip_id="vo", start=2.8, end=10.0),
        ]
    )
    cut_placements = ops._word_placements(cut_edit, "vo", parsed)
    assert cut_placements[1]["present"] is True
    assert cut_placements[2]["present"] is True
    assert cut_placements[1]["pause_after"]["present"] is False


def test_a_zero_width_last_word_is_present_not_cut() -> None:
    """The bug `restore` exposed: whisper's final word is often zero-width and
    sits exactly on the last segment's end, where the half-open test called it
    cut. It has always been wrong; `restore` made it visible by reporting a
    range fully restored while half of it still drew as struck.
    """
    specs = _plain(4)
    specs.append(("you.", 10.0, 10.0))  # zero-width, on the source's own end
    parsed = tx.Transcript(clip_id="vo", words=_words(specs))

    placements = ops._word_placements(_uncut_edit("vo", 10.0), "vo", parsed)
    assert placements[-1]["present"] is True
    assert placements[-1]["timeline_start"] == pytest.approx(10.0)

    # And it is still honestly reported cut when the material really is gone.
    trimmed = tl.Edit(segments=[tl.Segment(clip_id="vo", start=0.0, end=5.0)])
    assert ops._word_placements(trimmed, "vo", parsed)[-1]["present"] is False


def test_the_last_word_in_the_transcript_never_gets_a_pause_after() -> None:
    words = _words(_plain(5))
    assert ops._gap_after(words, len(words) - 1) is None

    parsed = tx.Transcript(clip_id="vo", words=words)
    edit = _uncut_edit("vo", 10.0)
    placements = ops._word_placements(edit, "vo", parsed)
    assert "pause_after" not in placements[-1]
