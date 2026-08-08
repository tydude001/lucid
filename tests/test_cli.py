"""Timecode and render-time span parsing — `cut-at`'s whole value rests here.

`_word_range` has no precedent test, but this parsing has no other coverage
at all (it lives only in the CLI, per design), so it is worth pinning
directly.
"""

from __future__ import annotations

import argparse

import pytest

from lucid.cli import _parse_timecode, _time_span


def test_parse_timecode_reads_colon_parts_optional_from_the_right() -> None:
    assert _parse_timecode("4.4") == pytest.approx(4.4)
    assert _parse_timecode("0:40.4") == pytest.approx(40.4)
    assert _parse_timecode("1:00:40.4") == pytest.approx(3640.4)


def test_time_span_start_plus_duration() -> None:
    assert _time_span("0:40.4+4.4") == pytest.approx([40.4, 44.8])


def test_time_span_start_dash_end() -> None:
    assert _time_span("0:40.4-0:44.8") == pytest.approx([40.4, 44.8])


def test_time_span_rejects_garbage() -> None:
    with pytest.raises(argparse.ArgumentTypeError):
        _time_span("banana")
