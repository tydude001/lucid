"""Reading melt's answer, and the frame arithmetic the answer is compared to.

Both halves are pure — a string in, a number out — so the cases that matter are
cheap to state exactly. Whether melt is reachable, and whether the count it
gives back matches a real export, is checked over stdio in test_server_stdio.py.

The MLT document below is **verbatim** `melt <project> -consumer xml` output,
captured 2026-08-07 from Kdenlive 26.04.3 / MLT 7.40 reading an auto-editor
`--export kdenlive` project of a 12.0s, 360-frame, 30fps source. Rendering that
same project produced 361 frames, so `length` is the field that predicts a
render and 361 is the number this file is entitled to expect.
"""

from __future__ import annotations

import pytest

from lucid import autoeditor, picture
from lucid.timeline import Edit, Segment

MELT_XML = """<?xml version="1.0"?>
<mlt LC_NUMERIC="C" version="7.40.0" title="out.kdenlive">
  <profile description="automatic" width="320" height="240" progressive="1" \
sample_aspect_num="1" sample_aspect_den="1" display_aspect_num="4" \
display_aspect_den="3" frame_rate_num="30" frame_rate_den="1" colorspace="709"/>
  <producer id="tractor2" in="0" out="360">
    <property name="length">361</property>
    <property name="eof">pause</property>
    <property name="resource">proj/out.kdenlive</property>
    <property name="mlt_service">xml</property>
    <property name="kdenlive:projectTractor">1</property>
    <property name="xml">was here</property>
    <property name="seekable">1</property>
  </producer>
  <playlist id="playlist0">
    <entry producer="tractor2" in="0" out="360"/>
  </playlist>
  <tractor id="tractor0" title="out.kdenlive" in="0" out="360">
    <track producer="playlist0"/>
  </tractor>
</mlt>
"""


def test_the_wrapping_producers_length_is_the_frame_count() -> None:
    assert picture.parse_melt_xml(MELT_XML) == 361


def test_a_media_producers_length_is_not_mistaken_for_the_timelines() -> None:
    """A source clip carries a `length` too, and it is a different number.

    It also comes first in the document, so taking the first `length` seen —
    which is what a line-oriented read of this output does — reports the length
    of whatever media happens to be declared earliest instead of the timeline's.
    """
    document = MELT_XML.replace(
        '  <playlist id="playlist0">',
        """  <producer id="producer0" in="0" out="200">
    <property name="length">99999</property>
    <property name="mlt_service">avformat</property>
  </producer>
  <playlist id="playlist0">""",
    )

    assert picture.parse_melt_xml(document) == 361


def test_a_document_with_no_wrapping_producer_falls_back_to_the_tractor() -> None:
    """MLT's `out` is frame-inclusive, so the fallback has to add the one back."""
    document = """<?xml version="1.0"?>
<mlt LC_NUMERIC="C" version="7.40.0">
  <playlist id="playlist0"/>
  <tractor id="tractor0" in="0" out="360">
    <track producer="playlist0"/>
  </tractor>
</mlt>
"""
    assert picture.parse_melt_xml(document) == 361


def test_an_unreadable_or_countless_document_raises_rather_than_guesses() -> None:
    with pytest.raises(picture.PictureError, match="readable MLT document"):
        picture.parse_melt_xml("melt: could not open the project\n")

    with pytest.raises(picture.PictureError, match="no frame count"):
        picture.parse_melt_xml('<mlt version="7.40.0"><playlist id="p"/></mlt>')


def test_melt_command_prefers_an_explicit_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """LUCID_MELT is a command, not a path — the flatpak form is four words."""
    monkeypatch.setenv("LUCID_MELT", "flatpak run --command=melt org.kde.kdenlive")

    assert picture.melt_command() == [
        "flatpak",
        "run",
        "--command=melt",
        "org.kde.kdenlive",
    ]


# -- the number melt is compared against ---------------------------------


def test_frame_total_counts_the_grid_the_export_lays_down() -> None:
    edit = Edit([Segment("vo", 0.0, 2.0), Segment("vo", 3.4, 7.0), Segment("vo", 8.4, 12.0)])

    assert autoeditor.frame_layout(edit, 30.0) == [(0, 60), (102, 108), (252, 108)]
    assert autoeditor.frame_total(edit, 30.0) == 276


def test_quantising_each_edge_is_not_the_same_as_quantising_the_total() -> None:
    """Why the count comes from `frame_layout` and never from the duration.

    Two segments of 0.017s each are half a frame apiece; the export cannot lay
    down half a frame, so each becomes one and the timeline is two frames long.
    Rounding the 0.034s total instead says one. The exported timeline is the
    honest answer, and only the per-segment path knows it.
    """
    edit = Edit([Segment("vo", 0.0, 0.017), Segment("vo", 1.0, 1.017)])

    assert autoeditor.frame_total(edit, 30.0) == 2
    assert round(edit.duration * 30.0) == 1


def test_a_segment_shorter_than_a_frame_still_gets_one() -> None:
    """`max(1, ...)`: a segment that rounds to zero frames would vanish silently."""
    edit = Edit([Segment("vo", 0.0, 0.001)])

    assert autoeditor.frame_total(edit, 30.0) == 1
