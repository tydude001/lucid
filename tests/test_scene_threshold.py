"""`SCENE_THRESHOLD` — pinned by judging the detections, not by a preference.

PLAN.md § The auto-framing detector, finding 1, **re-measured**. The first pin
scored ffmpeg's candidates against the sixteen approved framing boundaries and
called precision the share of detections that matched one. That is the wrong
question in the one direction that matters here: a real camera cut in a shot
nobody had chosen to frame counted *against* the floor, so "precision climbs
monotonically to 0.20" was measuring the hand table's coverage — fifteen
windows over three of the film's nine clips — rather than whether a detection
was a cut.

So every candidate ffmpeg reports inside a placement of the film, over all nine
clips, was looked at: the frame ~2 frames before and the frame at the reported
time, side by side, judged as one of

- `cut` — a change of camera. What a window is for.
- `same` — the same shot either side. A false positive.
- `again` — a cut already counted from an adjacent frame. Neither right nor
  wrong; the scan reports a transition on more than one frame, and counting the
  second as a false positive would understate the floor while counting it as a
  hit would overstate it.

`data/scene_cut_judgements.json` is that table, 59 rows over the band
`[0.05, 0.25)`. Above 0.25 nothing was judged: those are the detections the
first pin already accepted, and a floor is decided at its own edge.

**The result is one-sided enough that it does not need a metric.** From 0.141
to 0.244 every one of the 31 candidates is a real cut. The first `same` is at
0.137. There is no trade-off in the band the old floor sat in — 0.20 was
discarding 21 real cuts and buying nothing.

**A cut with no window is framing that walks through it**, which is why this is
a framing number and not a detector nicety: on the film's own vertical
projection the floor moving from 0.20 to 0.15 takes the stale share from 6.3%
to 28.0% of placed seconds. That is not a regression — it is 21 cuts that were
always being walked through and were not being reported.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from lucid import media, ops

JUDGEMENTS: list[dict[str, Any]] = json.loads(
    (Path(__file__).parent / "data" / "scene_cut_judgements.json").read_text(encoding="utf-8")
)

#: Judged rows are only meaningful up to here — above it nothing was looked at,
#: because a floor is decided at its own edge and everything above 0.25 was
#: already accepted by the first pin.
JUDGED_TO = 0.25


def _at(floor: float) -> list[dict[str, Any]]:
    """The judged candidates a floor admits."""
    return [row for row in JUDGEMENTS if row["score"] >= floor]


def test_the_shipped_floor_admits_no_false_positive() -> None:
    """The half a floor can only get wrong by being too low."""
    admitted = _at(ops.SCENE_THRESHOLD)
    wrong = [row for row in admitted if row["verdict"] == "same"]
    assert not wrong, (
        f"SCENE_THRESHOLD={ops.SCENE_THRESHOLD} admits {len(wrong)} judged non-cuts, "
        f"first at score {wrong[0]['score']} in {wrong[0]['asset']}"
    )
    assert admitted, "a floor that admits nothing is not being tested by this"


def test_the_shipped_floor_is_not_higher_than_the_evidence_asks() -> None:
    """The other half, and the one the first pin got wrong.

    Raising the floor is free in the precision column and expensive in the
    thing that column was standing in for, so a floor has to be pinned from
    below as well: every step up from here has to *cost* real cuts, or the
    number is higher than anything measured supports.
    """
    kept = {row["score"] for row in _at(ops.SCENE_THRESHOLD) if row["verdict"] == "cut"}
    for higher in (0.16, 0.18, 0.20):
        lost = len([score for score in kept if score < higher])
        assert lost, f"raising the floor to {higher} would lose nothing — {ops.SCENE_THRESHOLD} is arbitrary"


def test_the_old_floor_was_discarding_twenty_one_real_cuts() -> None:
    """The measurement that moved it, kept as an assertion so it cannot quietly
    stop being true if the judgements are ever revised."""
    band = [row for row in JUDGEMENTS if 0.15 <= row["score"] < 0.20]
    assert len(band) == 21
    assert all(row["verdict"] == "cut" for row in band), (
        "the whole case for 0.15 is that this band holds no false positive"
    )


def test_the_first_non_cut_is_below_the_floor_with_a_margin() -> None:
    """0.14 also admits only cuts, and is rejected anyway: it sits 0.003 from
    the first mistake, which is not a margin, it is a coincidence.

    "First" is the highest-scoring false positive — the one a floor coming down
    from the top meets first — and not the lowest.
    """
    first_bad = max(row["score"] for row in JUDGEMENTS if row["verdict"] == "same")
    assert first_bad == 0.137
    assert ops.SCENE_THRESHOLD - first_bad >= 0.01, (
        "a floor within a rounding error of a known false positive is not pinned"
    )


def test_the_scan_floor_is_below_the_threshold() -> None:
    """The scan is scored, not thresholded, and `reframe_coverage` reads
    sub-threshold scores to *explain* a window boundary as well as to demand
    one. A scan floor at or above the decision floor would silently make that
    second question unanswerable."""
    assert media.SCENE_FLOOR < ops.SCENE_THRESHOLD
