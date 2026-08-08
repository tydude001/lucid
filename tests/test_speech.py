"""Speech-run arithmetic, pinned on its own.

`ops.speech_overlap` is the only caller, but the merge/intersect/subtract math
is exactly the part worth checking independently of any project or transcript
(the same reasoning `autoeditor.frame_layout` gets its own test file for).
"""

from __future__ import annotations

import pytest

from lucid import speech


def test_merge_runs_closes_gaps_within_threshold() -> None:
    """A 0.05s gap between two spans is not a seam worth keeping open."""
    merged = speech.merge_runs([(1.0, 1.5), (1.55, 2.0)], max_gap=0.3)
    assert merged == [(1.0, 2.0)]


def test_merge_runs_leaves_wider_gaps_apart() -> None:
    """The same spans, asked about with the strictest tolerance, stay apart."""
    merged = speech.merge_runs([(1.0, 1.5), (1.55, 2.0)], max_gap=0.0)
    assert merged == [(1.0, 1.5), (1.55, 2.0)]


def test_merge_runs_sorts_unsorted_input() -> None:
    merged = speech.merge_runs([(3.0, 3.5), (1.0, 1.5), (1.5, 2.0)], max_gap=0.3)
    assert merged == [(1.0, 2.0), (3.0, 3.5)]


def test_merge_runs_drops_empty_and_backwards_spans() -> None:
    merged = speech.merge_runs([(1.0, 1.5), (2.0, 2.0), (3.0, 2.5)], max_gap=0.3)
    assert merged == [(1.0, 1.5)]


def test_merge_runs_of_nothing_is_nothing() -> None:
    assert speech.merge_runs([]) == []


def test_intersect_runs_is_overlap_not_containment() -> None:
    """Two runs touching at an endpoint produce no intersection; partial
    overlap does — the same overlap-not-containment rule CLAUDE.md states for
    word survival, applied here to whole runs.
    """
    touching = speech.intersect_runs([(1.0, 2.0)], [(2.0, 3.0)])
    partial = speech.intersect_runs([(1.0, 2.0)], [(1.5, 3.0)])

    assert touching == []
    assert partial == [(1.5, 2.0)]


def test_intersect_runs_finds_every_pairwise_hit() -> None:
    hits = speech.intersect_runs([(0.0, 1.0), (5.0, 6.0)], [(0.5, 2.0), (5.5, 7.0)])
    assert hits == [(0.5, 1.0), (5.5, 6.0)]


def test_subtract_runs_returns_pieces_around_a_removal() -> None:
    pieces = speech.subtract_runs((0.0, 10.0), [(4.0, 6.0)])
    assert pieces == [(0.0, 4.0), (6.0, 10.0)]


def test_subtract_runs_returns_the_whole_run_when_nothing_overlaps() -> None:
    pieces = speech.subtract_runs((0.0, 10.0), [(12.0, 14.0)])
    assert pieces == [(0.0, 10.0)]


def test_subtract_runs_returns_nothing_when_fully_covered() -> None:
    pieces = speech.subtract_runs((2.0, 4.0), [(0.0, 10.0)])
    assert pieces == []


def test_subtract_runs_coalesces_overlapping_removals_first() -> None:
    """Two overlapping removals must not leave a false sliver of `run`
    between them — they are one hole, not two.
    """
    pieces = speech.subtract_runs((0.0, 10.0), [(3.0, 6.0), (5.0, 8.0)])
    assert pieces == [(0.0, 3.0), (8.0, 10.0)]


@pytest.mark.parametrize("run", [(5.0, 5.0), (5.0, 4.0)])
def test_subtract_runs_of_an_empty_or_backwards_run_is_nothing(run: tuple[float, float]) -> None:
    assert speech.subtract_runs(run, [(0.0, 10.0)]) == []
