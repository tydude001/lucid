"""Speech-run arithmetic: merge, intersect, subtract — nothing else.

Pure, stdlib-only, no I/O — same tier as `verify.py`/`energy.py`'s own pure
helpers. `ops.speech_overlap` is the only caller; the math lives here so it
can be pinned on its own, the same way `autoeditor.frame_layout` is tested
apart from `check_frames`.

Every interval in this module is `(start, end)` seconds, half-open, and every
comparison here is an overlap test, never containment — the same rule
CLAUDE.md states for word survival, because a run that only partly reaches
another is still the case worth reporting.
"""

from __future__ import annotations

from collections.abc import Sequence


def merge_runs(
    spans: Sequence[tuple[float, float]], *, max_gap: float = 0.3
) -> list[tuple[float, float]]:
    """Coalesce `spans` into runs, closing gaps of `max_gap` seconds or less.

    Input need not be sorted. Empty or backwards spans (`end <= start`) are
    dropped rather than raising — they carry no duration to merge. Touching
    or overlapping spans always merge regardless of `max_gap`; `max_gap=0.0`
    recovers touch-only merging, the strictest useful setting.
    """
    cleaned = sorted((float(start), float(end)) for start, end in spans if end > start)
    if not cleaned:
        return []

    merged = [cleaned[0]]
    for start, end in cleaned[1:]:
        last_start, last_end = merged[-1]
        if start - last_end <= max_gap:
            merged[-1] = (last_start, max(last_end, end))
        else:
            merged.append((start, end))
    return merged


def intersect_runs(
    a: Sequence[tuple[float, float]], b: Sequence[tuple[float, float]]
) -> list[tuple[float, float]]:
    """Every nonempty pairwise intersection of `a` against `b`, earliest first.

    Overlap, never containment: two runs that only touch at an endpoint
    produce nothing, since `hi > lo` is strict — the same test shape as
    `Edit.timeline_span`'s survival check and `ops._pad_reach`.
    """
    out = [
        (max(a0, b0), min(a1, b1))
        for a0, a1 in a
        for b0, b1 in b
        if min(a1, b1) > max(a0, b0)
    ]
    out.sort()
    return out


def subtract_runs(
    run: tuple[float, float], others: Sequence[tuple[float, float]]
) -> list[tuple[float, float]]:
    """`run` minus every span in `others`. Returns 0, 1 or N remaining pieces.

    `others` is coalesced first via `merge_runs(others, max_gap=0.0)` so two
    overlapping removals don't leave a false sliver of `run` between them —
    the same shape as `timeline._subtract`, but against a list of removals
    rather than one.
    """
    lo, hi = run
    if hi <= lo:
        return []

    pieces: list[tuple[float, float]] = []
    cursor = lo
    for r_start, r_end in merge_runs(others, max_gap=0.0):
        a, b = max(r_start, lo), min(r_end, hi)
        if b <= a:
            continue
        if a > cursor:
            pieces.append((cursor, a))
        cursor = max(cursor, b)
    if cursor < hi:
        pieces.append((cursor, hi))
    return pieces
