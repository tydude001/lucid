"""Track surgery: subtracting source intervals, and the OTIO round trip.

OTIO's own edit algorithms are C++ only (CLAUDE.md), so this arithmetic is
hand-rolled and is exactly the part that has to be pinned down by tests.
"""

from __future__ import annotations

import pytest

from lucid.timeline import Edit, Segment, TimelineError, from_otio, to_otio

CLIPS = {
    "vo": {"clip_id": "vo", "source": "/tmp/vo.wav", "duration": 60.0, "has_video": False, "has_audio": True},
    "cam": {"clip_id": "cam", "source": "/tmp/cam.mp4", "duration": 60.0, "has_video": True, "has_audio": True},
}


def _edit(*spans: tuple[float, float], clip_id: str = "vo") -> Edit:
    return Edit([Segment(clip_id, a, b) for a, b in spans])


def _spans(edit: Edit) -> list[tuple[float, float]]:
    return [(s.start, s.end) for s in edit.segments]


# -- removal -------------------------------------------------------------


def test_removing_the_middle_splits_a_segment() -> None:
    edit = _edit((0.0, 10.0))
    assert edit.remove("vo", 4.0, 6.0) == 1
    assert _spans(edit) == [(0.0, 4.0), (6.0, 10.0)]


def test_removing_a_whole_segment_drops_it() -> None:
    edit = _edit((0.0, 4.0), (5.0, 9.0))
    edit.remove("vo", 5.0, 9.0)
    assert _spans(edit) == [(0.0, 4.0)]


def test_removal_spanning_segments_trims_both_and_drops_the_middle() -> None:
    edit = _edit((0.0, 4.0), (5.0, 9.0), (10.0, 14.0))
    assert edit.remove("vo", 3.0, 11.0) == 3
    assert _spans(edit) == [(0.0, 3.0), (11.0, 14.0)]


def test_removal_ripples_so_the_hole_closes() -> None:
    edit = _edit((0.0, 4.0), (5.0, 9.0))
    edit.remove("vo", 1.0, 2.0)
    # Total duration drops by exactly the removed span; nothing is left behind.
    assert edit.duration == pytest.approx(7.0)


def test_removal_leaves_other_clips_alone() -> None:
    edit = Edit([Segment("vo", 0.0, 10.0), Segment("cam", 0.0, 10.0)])
    edit.remove("vo", 0.0, 10.0)
    assert _spans(edit) == [(0.0, 10.0)]
    assert edit.segments[0].clip_id == "cam"


def test_removing_an_already_cut_range_is_a_no_op() -> None:
    """An agent retrying a cut must not damage the timeline."""
    edit = _edit((0.0, 4.0), (6.0, 10.0))
    assert edit.remove("vo", 4.0, 6.0) == 0
    assert _spans(edit) == [(0.0, 4.0), (6.0, 10.0)]


def test_removal_rejects_an_empty_or_backwards_interval() -> None:
    edit = _edit((0.0, 10.0))
    with pytest.raises(TimelineError, match="empty or backwards"):
        edit.remove("vo", 5.0, 5.0)
    with pytest.raises(TimelineError, match="empty or backwards"):
        edit.remove("vo", 6.0, 5.0)


def test_slivers_below_the_floor_are_dropped() -> None:
    edit = _edit((0.0, 10.0))
    edit.remove("vo", 0.0, 9.9999)
    assert _spans(edit) == []


# -- keep ----------------------------------------------------------------


def test_keep_only_retains_the_requested_intervals() -> None:
    edit = _edit((0.0, 10.0))
    edit.keep_only("vo", [(1.0, 2.0), (5.0, 6.0)])
    assert _spans(edit) == [(1.0, 2.0), (5.0, 6.0)]


def test_keep_only_clips_to_what_is_still_on_the_timeline() -> None:
    """Asking to keep something already cut yields nothing, not a resurrection."""
    edit = _edit((0.0, 4.0))
    edit.keep_only("vo", [(2.0, 8.0)])
    assert _spans(edit) == [(2.0, 4.0)]


def test_keep_only_merges_overlapping_intervals() -> None:
    edit = _edit((0.0, 10.0))
    edit.keep_only("vo", [(1.0, 4.0), (3.0, 6.0)])
    assert _spans(edit) == [(1.0, 6.0)]


def test_keep_only_leaves_other_clips_alone() -> None:
    edit = Edit([Segment("vo", 0.0, 10.0), Segment("cam", 0.0, 10.0)])
    edit.keep_only("vo", [(1.0, 2.0)])
    assert [(s.clip_id, s.start, s.end) for s in edit.segments] == [
        ("vo", 1.0, 2.0),
        ("cam", 0.0, 10.0),
    ]


def test_keep_only_needs_an_interval() -> None:
    with pytest.raises(TimelineError, match="at least one interval"):
        _edit((0.0, 10.0)).keep_only("vo", [])


# -- addressing ----------------------------------------------------------


def test_timeline_time_accounts_for_earlier_cuts() -> None:
    edit = _edit((0.0, 4.0), (6.0, 10.0))
    assert edit.timeline_time("vo", 1.0) == pytest.approx(1.0)
    # Source 7.0 sits 1s into the second segment, which starts at timeline 4.0.
    assert edit.timeline_time("vo", 7.0) == pytest.approx(5.0)


def test_timeline_time_is_none_for_cut_material() -> None:
    """Reporting the cut honestly beats silently pointing somewhere else."""
    assert _edit((0.0, 4.0), (6.0, 10.0)).timeline_time("vo", 5.0) is None


def test_source_at_returns_the_playing_clip_and_source_time() -> None:
    edit = _edit((0.0, 4.0), (6.0, 10.0))
    assert edit.source_at(1.0) == ("vo", 1.0)
    # Timeline 5.0 sits 1s into the second segment, which starts at source 6.0.
    assert edit.source_at(5.0) == ("vo", 7.0)
    # The very last instant on the timeline still resolves, at the last
    # segment's own end.
    assert edit.source_at(8.0) == ("vo", 10.0)


def test_source_at_returns_none_past_the_end() -> None:
    edit = _edit((0.0, 4.0), (6.0, 10.0))
    assert edit.source_at(8.001) is None
    assert edit.source_at(-1.0) is None


def test_source_at_is_the_inverse_of_timeline_time() -> None:
    """Documents the pairing explicitly rather than leaving it implicit."""
    edit = _edit((0.0, 4.0), (6.0, 10.0))
    for source_time in (0.5, 3.9, 6.0, 9.999):
        timeline_time = edit.timeline_time("vo", source_time)
        assert timeline_time is not None
        clip_id, back = edit.source_at(timeline_time)
        assert clip_id == "vo"
        assert back == pytest.approx(source_time)


def test_covers_measures_surviving_overlap() -> None:
    edit = _edit((0.0, 4.0), (6.0, 10.0))
    assert edit.covers("vo", 3.0, 7.0) == pytest.approx(2.0)
    assert edit.covers("vo", 4.0, 6.0) == pytest.approx(0.0)


def test_source_spans_matches_a_simple_offset_inside_one_segment() -> None:
    edit = _edit((10.0, 20.0))
    assert edit.source_spans(2.0, 5.0) == [("vo", 12.0, 15.0)]


def test_source_spans_splits_across_a_ripple_closed_seam() -> None:
    """A cut in the middle closes the timeline; a render-time range straddling
    where the seam now sits must come back as two pieces of the same clip,
    non-adjacent in source time, that together cover exactly the request.
    """
    edit = _edit((0.0, 4.0), (6.0, 10.0))  # source 4.0-6.0 already cut
    pieces = edit.source_spans(3.0, 5.0)

    assert [p[0] for p in pieces] == ["vo", "vo"]
    assert pieces[0][1:] == pytest.approx((3.0, 4.0))
    assert pieces[1][1:] == pytest.approx((6.0, 7.0))
    assert sum(b - a for _, a, b in pieces) == pytest.approx(2.0)


def test_source_spans_crosses_a_clip_boundary() -> None:
    """Representable now even though `seed_timeline` doesn't build it yet."""
    edit = Edit([Segment("vo", 0.0, 4.0), Segment("cam", 0.0, 4.0)])
    pieces = edit.source_spans(3.0, 5.0)

    assert [p[0] for p in pieces] == ["vo", "cam"]
    assert pieces[0][1:] == pytest.approx((3.0, 4.0))
    assert pieces[1][1:] == pytest.approx((0.0, 1.0))


def test_source_spans_rejects_past_the_end() -> None:
    edit = _edit((0.0, 10.0))
    with pytest.raises(TimelineError, match="outside the timeline"):
        edit.source_spans(8.0, 11.0)


def test_source_spans_rejects_empty_or_backwards() -> None:
    edit = _edit((0.0, 10.0))
    with pytest.raises(TimelineError, match="empty or backwards"):
        edit.source_spans(5.0, 5.0)
    with pytest.raises(TimelineError, match="empty or backwards"):
        edit.source_spans(6.0, 5.0)


def test_source_spans_rejects_negative_start() -> None:
    edit = _edit((0.0, 10.0))
    with pytest.raises(TimelineError, match="outside the timeline"):
        edit.source_spans(-1.0, 5.0)


def test_source_spans_zero_length_at_the_very_end_is_still_refused() -> None:
    """Pinning the "zero-length never allowed" decision, rather than leaving
    it to fall out of the `end<=start` check by accident.
    """
    edit = _edit((0.0, 10.0))
    with pytest.raises(TimelineError, match="empty or backwards"):
        edit.source_spans(10.0, 10.0)


# -- OTIO ----------------------------------------------------------------


def test_otio_round_trip_preserves_segments() -> None:
    edit = _edit((1.5, 4.25), (10.0, 12.5))
    restored = from_otio(to_otio(edit, CLIPS, rate=1000))
    assert _spans(restored) == _spans(edit)
    assert [s.clip_id for s in restored.segments] == ["vo", "vo"]


def test_otio_track_kind_follows_the_media() -> None:
    audio = to_otio(_edit((0.0, 1.0)), CLIPS, rate=1000)
    video = to_otio(_edit((0.0, 1.0), clip_id="cam"), CLIPS, rate=30)
    assert audio.tracks[0].kind == "Audio"
    assert video.tracks[0].kind == "Video"


def test_otio_rejects_an_unregistered_clip() -> None:
    with pytest.raises(TimelineError, match="unregistered clip"):
        to_otio(_edit((0.0, 1.0), clip_id="ghost"), CLIPS, rate=30)


def test_from_otio_rejects_a_foreign_timeline() -> None:
    """Without lucid metadata there is no clip_id, and guessing one is worse."""
    timeline = to_otio(_edit((0.0, 1.0)), CLIPS, rate=1000)
    del timeline.tracks[0][0].metadata["lucid"]
    with pytest.raises(TimelineError, match="not written by lucid"):
        from_otio(timeline)
