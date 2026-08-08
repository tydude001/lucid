"""The noise-attenuation safety filter, isolated from ffmpeg and disk.

`ops._classify_noise_events` is the whole safety property `attenuate_noises`
exists to protect: an event only qualifies automatically when it is both
short *and* sitting in a gap narrow enough to prove the word map is dense
around it. Fabricated `Transcript`/gap dicts, no I/O — `test_server_stdio.py`
checks the same filter wired into the real tool over real audio.
"""

from __future__ import annotations

import pytest

from lucid import ops
from lucid import transcript as tx


def _words(*specs: tuple[str, float, float]) -> tx.Transcript:
    return tx.Transcript(
        clip_id="vo",
        words=tuple(
            tx.Word(index=i, text=text, start=start, end=end)
            for i, (text, start, end) in enumerate(specs)
        ),
    )


def _gap(
    start: float, end: float, runs: list[dict[str, float]]
) -> dict[str, object]:
    return {"start": start, "end": end, "duration": round(end - start, 3), "runs": runs}


def test_a_short_event_in_a_narrow_gap_qualifies() -> None:
    parsed = _words(("quiet", 9.0, 10.0), ("for", 11.3, 11.9))
    gap = _gap(10.0, 11.3, [{"start": 10.41, "end": 10.87, "duration": 0.46, "peak_db": -18.4}])

    events = ops._classify_noise_events(
        parsed, [10.0, 11.9], [gap],
        max_event_seconds=1.5, max_gap_seconds=2.0, pad=0.05, suspect={},
    )

    assert len(events) == 1
    event = events[0]
    assert event["status"] == "attenuated"
    assert event["reasons"] == []
    assert event["padded_start"] == pytest.approx(10.36)
    assert event["padded_end"] == pytest.approx(10.92)


def test_a_wide_gap_disqualifies_even_a_short_event() -> None:
    """The Scream incident: a 0.6s run in a 4.12s hole must stay disqualified
    on gap width, never on event length — the hole is what makes the map
    untrustworthy there, not the event's own duration (`ideas/scream.md`).
    """
    parsed = _words(("bit", 100.0, 100.5), ("on", 104.62, 105.1))
    gap = _gap(100.5, 104.62, [{"start": 102.0, "end": 102.6, "duration": 0.6, "peak_db": -14.0}])

    events = ops._classify_noise_events(
        parsed, [100.5, 105.1], [gap],
        max_event_seconds=1.5, max_gap_seconds=2.0, pad=0.05, suspect={},
    )

    event = events[0]
    assert event["status"] == "disqualified"
    assert any("max_gap_seconds" in reason for reason in event["reasons"])
    assert not any("max_event_seconds" in reason for reason in event["reasons"])


def test_a_long_event_disqualifies_even_in_a_narrow_gap() -> None:
    parsed = _words(("so", 5.0, 5.5), ("then", 6.8, 7.4))
    gap = _gap(5.5, 6.8, [{"start": 5.6, "end": 7.4 - 0.1, "duration": 1.7, "peak_db": -20.0}])

    events = ops._classify_noise_events(
        parsed, [5.5, 7.4], [gap],
        max_event_seconds=1.5, max_gap_seconds=2.0, pad=0.05, suspect={},
    )

    event = events[0]
    assert event["status"] == "disqualified"
    assert any("max_event_seconds" in reason for reason in event["reasons"])
    assert not any("max_gap_seconds" in reason for reason in event["reasons"])


def test_pad_is_clamped_to_the_gap_never_into_a_neighbouring_word() -> None:
    """Padding may widen into quiet air inside the gap, never past its edge."""
    parsed = _words(("quiet", 9.0, 10.0), ("for", 10.4, 11.0))
    gap = _gap(10.0, 10.4, [{"start": 10.02, "end": 10.38, "duration": 0.36, "peak_db": -20.0}])

    events = ops._classify_noise_events(
        parsed, [10.0, 11.0], [gap],
        max_event_seconds=1.5, max_gap_seconds=2.0, pad=0.05, suspect={},
    )

    event = events[0]
    # Unclamped this would be 9.97/10.43 — past the gap on both sides.
    assert event["padded_start"] == pytest.approx(10.0)
    assert event["padded_end"] == pytest.approx(10.4)


def test_a_suspect_neighbour_withholds_without_confirming() -> None:
    """A bounding word with a suspect duration compromises the "gap is
    narrow" evidence itself, so the event is held back even though it
    otherwise qualifies on length and gap width.
    """
    parsed = _words(("quiet", 9.0, 10.0), ("for", 11.3, 11.9))
    gap = _gap(10.0, 11.3, [{"start": 10.41, "end": 10.87, "duration": 0.46, "peak_db": -18.4}])
    suspect = {0: {"index": 0, "text": "quiet", "duration": 3.5, "limit": 1.2}}

    events = ops._classify_noise_events(
        parsed, [10.0, 11.9], [gap],
        max_event_seconds=1.5, max_gap_seconds=2.0, pad=0.05, suspect=suspect,
    )

    event = events[0]
    assert event["status"] == "suspect_neighbour"
    assert event["reasons"]


def test_events_echo_the_nearest_word_either_side_by_index_and_text() -> None:
    """No word index for the event itself — only its nearest neighbours."""
    parsed = _words(
        ("well", 0.0, 0.4), ("quiet", 9.0, 10.0), ("for", 11.3, 11.9), ("now", 20.0, 20.4)
    )
    gap = _gap(10.0, 11.3, [{"start": 10.41, "end": 10.87, "duration": 0.46, "peak_db": -18.4}])

    events = ops._classify_noise_events(
        parsed, [0.4, 10.0, 11.9, 20.4], [gap],
        max_event_seconds=1.5, max_gap_seconds=2.0, pad=0.05, suspect={},
    )

    event = events[0]
    assert event["neighbour_before"] == {"index": 1, "text": "quiet"}
    assert event["neighbour_after"] == {"index": 2, "text": "for"}
