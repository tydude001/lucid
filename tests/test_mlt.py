"""The MLT writer — step 4 of the layered timeline.

Every assertion here is about a failure mode that produces a *render* rather
than an error: MLT pads a short playlist with `<blank>`, melt renders to the
longest declared length in the document, and both exit 0. So the tests read
the document back rather than trusting the variables it was built from —
`declared_frames` exists for the same reason.

The counterpart evidence is a real render: the document this module writes was
handed to melt on this box and came back 1920x1080 at exactly the declared
frame count, with the card compositing and the audio at unity. That is in
HISTORY.md § The MLT writer; it cannot live in a unit test, because melt is
inside a flatpak that cannot see the `/tmp` `tmp_path` hands out.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

from lucid import mlt

RATE = 30.0


def _shot(asset: str, frames: int, *, is_image: bool = False, duration: float | None = None,
          path: str | None = None, start_frame: int = 0,
          src_pin: float | None = None) -> dict[str, object]:
    return {
        "asset": asset,
        "asset_path": path or f"/media/{asset}.mp4",
        "asset_duration": duration,
        "is_image": is_image,
        "frames": frames,
        "start_frame": start_frame,
        "clip_id": "vo",
        "word_index": 1,
        "src_pin": src_pin,
    }


def _audio(*frames: int) -> list[mlt.Entry]:
    entries, cursor = [], 0
    for count in frames:
        entries.append(mlt.Entry("/media/vo.wav", cursor, count))
        cursor += count
    return entries


# -- entries and the off-by-one ------------------------------------------


def test_src_out_is_the_last_frame_index_not_the_count() -> None:
    """The arithmetic auto-editor gets wrong in the other direction: it writes
    the count where MLT wants the inclusive end, and melt renders a trailing
    black frame for it (picture.KNOWN_TAIL_FRAME)."""
    assert mlt.Entry("/media/a.mp4", 0, 30).src_out == 29
    assert mlt.Entry("/media/a.mp4", 90, 60).src_out == 149


# -- plan_picture: where inside each asset a shot reads from --------------


def test_plan_picture_carries_a_cursor_across_re_uses_of_one_clip() -> None:
    entries = mlt.plan_picture(
        [_shot("film", 45, duration=10.0), _shot("film", 60, duration=10.0)], RATE
    )
    assert [(e.src_in, e.frames) for e in entries] == [(0, 45), (45, 60)]


def test_plan_picture_keeps_a_separate_cursor_per_asset() -> None:
    entries = mlt.plan_picture(
        [
            _shot("a", 30, duration=10.0, path="/media/a.mp4"),
            _shot("b", 30, duration=10.0, path="/media/b.mp4"),
            _shot("a", 30, duration=10.0, path="/media/a.mp4"),
        ],
        RATE,
    )
    assert [e.src_in for e in entries] == [0, 0, 30]


def test_plan_picture_rewinds_rather_than_running_off_the_end() -> None:
    """Clamping would hold a frozen frame, which reads as a render bug. A
    rewind reads as a re-use, which is what it is."""
    entries = mlt.plan_picture(
        [_shot("film", 45, duration=2.0), _shot("film", 30, duration=2.0)], RATE
    )
    assert [e.src_in for e in entries] == [0, 0]


def test_plan_picture_refuses_a_shot_longer_than_its_whole_asset() -> None:
    with pytest.raises(mlt.MLTError, match="only 2.0s long"):
        mlt.plan_picture([_shot("film", 90, duration=2.0)], RATE)


def test_plan_picture_holds_a_still_from_its_first_frame_every_time() -> None:
    entries = mlt.plan_picture(
        [
            _shot("card:x", 40, is_image=True, path="/cards/x.png"),
            _shot("card:x", 25, is_image=True, path="/cards/x.png"),
        ],
        RATE,
    )
    assert [(e.src_in, e.frames, e.is_image) for e in entries] == [(0, 40, True), (0, 25, True)]


def test_plan_picture_refuses_an_asset_with_no_known_duration() -> None:
    with pytest.raises(mlt.MLTError, match="no known duration"):
        mlt.plan_picture([_shot("film", 30, duration=None)], RATE)


def test_plan_picture_refuses_a_shot_with_no_frames_in_it() -> None:
    with pytest.raises(mlt.MLTError, match="a cue landed on top of the next one"):
        mlt.plan_picture([_shot("film", 0, duration=10.0)], RATE)


# -- the pinned cue: it shows the moment it names, or it refuses -----------


def test_plan_picture_reads_a_pinned_shot_from_its_in_point() -> None:
    """The whole point of the pin: somebody read a description and asked for
    *that* moment, so the cursor does not get a say."""
    entries = mlt.plan_picture([_shot("film", 30, duration=10.0, src_pin=4.0)], RATE)

    assert [(e.src_in, e.frames) for e in entries] == [(120, 30)]


def test_a_pin_beats_the_cursor_a_previous_use_of_the_same_asset_left() -> None:
    entries = mlt.plan_picture(
        [_shot("film", 60, duration=10.0), _shot("film", 30, duration=10.0, src_pin=6.0)], RATE
    )

    assert [e.src_in for e in entries] == [0, 180]


def test_an_unpinned_re_use_after_a_pin_carries_on_from_where_the_pin_ended() -> None:
    """A pin consumes its stretch like any other shot — otherwise the shot
    after it replays footage the viewer has just seen."""
    entries = mlt.plan_picture(
        [_shot("film", 30, duration=10.0, src_pin=4.0), _shot("film", 30, duration=10.0)], RATE
    )

    assert [e.src_in for e in entries] == [120, 150]


def test_plan_picture_refuses_a_pinned_shot_that_runs_past_its_asset() -> None:
    """The one thing this step exists to prevent. Unpinned, this rewinds to 0
    and shows the asset's opening seconds — correct pixels, wrong video, and
    nothing on screen saying the search result was not what got placed."""
    with pytest.raises(mlt.MLTError, match="pins 'film' to 8.0s and the shot runs 3.0s"):
        mlt.plan_picture([_shot("film", 90, duration=10.0, src_pin=8.0)], RATE)

    # And the edge it stops exactly at: ending on the asset's last frame fits.
    entries = mlt.plan_picture([_shot("film", 60, duration=10.0, src_pin=8.0)], RATE)
    assert [(e.src_in, e.src_out) for e in entries] == [(240, 299)]


def test_the_pinned_refusal_is_not_the_rewind_the_same_shot_would_have_got() -> None:
    """Stated as a pair, because the two answers to one arrangement of frames
    are the whole design: the rewind is right for a re-use and wrong for a
    placement."""
    unpinned = _shot("film", 45, duration=2.0)
    entries = mlt.plan_picture([_shot("film", 45, duration=2.0), unpinned], RATE)
    assert [e.src_in for e in entries] == [0, 0]

    with pytest.raises(mlt.MLTError, match="a pinned cue shows the moment it names"):
        mlt.plan_picture([_shot("film", 45, duration=2.0, src_pin=1.0)], RATE)


def test_plan_picture_refuses_a_pin_before_the_start_of_the_asset() -> None:
    with pytest.raises(mlt.MLTError, match="before the start of the asset"):
        mlt.plan_picture([_shot("film", 30, duration=10.0, src_pin=-1.0)], RATE)


def test_plan_picture_refuses_a_pin_on_a_still_rather_than_ignoring_it() -> None:
    """`cue_add` turns this away first. If one reached here it would be a
    silent no-op, which is the failure mode this file is written against."""
    with pytest.raises(mlt.MLTError, match="it is a still"):
        mlt.plan_picture(
            [_shot("card:x", 30, is_image=True, path="/cards/x.png", src_pin=2.0)], RATE
        )


def test_a_shot_with_no_src_pin_key_at_all_still_plans() -> None:
    """The projection is the only caller that sets the key, and a caller
    building shots by hand (the export path's own tests do) must not have to."""
    bare = {
        "asset": "film",
        "asset_path": "/media/film.mp4",
        "asset_duration": 10.0,
        "is_image": False,
        "frames": 30,
        "start_frame": 0,
        "clip_id": "vo",
        "word_index": 1,
    }
    assert [e.src_in for e in mlt.plan_picture([bare], RATE)] == [0]


# -- the document, read back off itself -----------------------------------


def test_every_declared_length_is_the_timeline_total() -> None:
    """melt renders to the longest of them, so they all have to agree. Read
    back off the built tree, because a number that was right in a variable and
    wrong in an attribute is precisely the bug."""
    document = mlt.document(audio=_audio(60, 60), rate=RATE)

    declared = mlt.declared_frames(document)
    assert declared, "the sweep found nothing to check, which means it is not checking"
    assert set(declared.values()) == {120}


def test_a_tractors_out_is_the_last_frame_index() -> None:
    """The exact spot auto-editor writes the frame *count* into, costing every
    kdenlive export a trailing black frame (picture.KNOWN_TAIL_FRAME). This
    writer does not have that defect, and this is the test that keeps it so."""
    document = mlt.document(audio=_audio(120), rate=RATE)

    assert [t.get("out") for t in document.findall("tractor")] == ["119"] * 3


def test_declared_frames_ignores_a_still_images_four_hour_length() -> None:
    """A `qimage` producer claims four hours so a shot can never outrun it.
    That is not a statement about the timeline, and sweeping it in would make
    every document with a card in it look wrong."""
    document = mlt.document(
        audio=_audio(60),
        picture=[mlt.Entry("/cards/x.png", 0, 60, is_image=True)],
        rate=RATE,
    )
    assert set(mlt.declared_frames(document).values()) == {60}


def test_the_picture_lane_must_cover_the_timeline_exactly() -> None:
    with pytest.raises(mlt.MLTError, match="covers 90 frames but the timeline is 120"):
        mlt.document(
            audio=_audio(120), picture=[mlt.Entry("/media/film.mp4", 0, 90)], rate=RATE
        )


def test_a_picture_lane_running_long_is_refused_too() -> None:
    """Short pads with `<blank>`; long extends the render past the audio. Both
    are silent, so both are refusals rather than warnings."""
    with pytest.raises(mlt.MLTError, match="covers 150 frames but the timeline is 120"):
        mlt.document(
            audio=_audio(120), picture=[mlt.Entry("/media/film.mp4", 0, 150)], rate=RATE
        )


def test_no_blank_is_ever_written() -> None:
    document = mlt.document(
        audio=_audio(30, 30),
        picture=[mlt.Entry("/media/film.mp4", 0, 45), mlt.Entry("/cards/x.png", 0, 15, is_image=True)],
        rate=RATE,
    )
    assert document.find(".//blank") is None


def test_an_empty_timeline_is_refused() -> None:
    with pytest.raises(mlt.MLTError, match="at least one entry"):
        mlt.document(audio=[], rate=RATE)


# -- what the producers say -----------------------------------------------


def _producer(document: ET.Element, node_id: str) -> ET.Element:
    found = document.find(f"*[@id='{node_id}']")
    assert found is not None, f"no node {node_id!r} in the document"
    return found


def _properties(node: ET.Element) -> dict[str, str]:
    return {p.get("name", ""): (p.text or "") for p in node.findall("property")}


def test_picture_from_a_video_clip_plays_silent() -> None:
    """Film under a VO is muted at the producer, so no downstream mix can let
    it back in — `audio_index` is a producer property, not a per-entry one."""
    document = mlt.document(
        audio=_audio(60), picture=[mlt.Entry("/media/film.mp4", 0, 60)], rate=RATE
    )
    assert _properties(_producer(document, "vchain0"))["audio_index"] == "-1"


def test_a_still_becomes_a_qimage_producer_that_holds_past_its_end() -> None:
    document = mlt.document(
        audio=_audio(60),
        picture=[mlt.Entry("/cards/x.png", 0, 60, is_image=True)],
        rate=RATE,
    )
    properties = _properties(_producer(document, "vchain0"))
    assert properties["mlt_service"] == "qimage"
    assert properties["eof"] == "continue"
    assert int(properties["length"]) == round(mlt.IMAGE_LENGTH_SECONDS * RATE)


def test_an_audio_only_edit_hides_video_on_its_own_track() -> None:
    document = mlt.document(audio=_audio(60), rate=RATE)

    track = _producer(document, "tractor0")
    assert {t.get("hide") for t in track.findall("track")} == {"video"}
    assert _properties(_producer(document, "chain0"))["set.test_video"] == "1"


def test_an_edit_carrying_video_is_composited_rather_than_hidden() -> None:
    """Otherwise the timeline's own picture renders as sound over black — and
    exits 0 doing it."""
    document = mlt.document(
        audio=[mlt.Entry("/media/talk.mp4", 0, 60, has_video=True)], rate=RATE
    )

    track = _producer(document, "tractor0")
    assert {t.get("hide") for t in track.findall("track")} == {None}
    assert _properties(_producer(document, "chain0"))["set.test_video"] == "0"
    services = [
        _properties(t)["mlt_service"] for t in document.findall(".//transition")
    ]
    assert services == ["mix", "qtblend"]


def test_the_picture_track_gets_its_own_composite() -> None:
    """Without a transition a tractor renders its first track and drops the
    rest, silently (HISTORY.md § 4)."""
    document = mlt.document(
        audio=_audio(60), picture=[mlt.Entry("/media/film.mp4", 0, 60)], rate=RATE
    )
    blends = [
        _properties(t)
        for t in document.findall(".//transition")
        if _properties(t)["mlt_service"] == "qtblend"
    ]
    assert [b["b_track"] for b in blends] == ["2"]


def test_a_wav_beside_a_video_clip_is_still_told_it_has_no_picture() -> None:
    """`set.test_video` is a fact about the file, so it cannot be answered
    once for a track holding both — told 0, MLT renders black frames off the
    wav for as long as it is on screen."""
    document = mlt.document(
        audio=[
            mlt.Entry("/media/vo.wav", 0, 30),
            mlt.Entry("/media/talk.mp4", 0, 30, has_video=True),
        ],
        rate=RATE,
    )
    assert _properties(_producer(document, "chain0"))["set.test_video"] == "1"
    assert _properties(_producer(document, "chain1"))["set.test_video"] == "0"


def test_one_bin_entry_per_source_however_many_producers_it_needs() -> None:
    """A file on both the edit and the picture lane gets two producers,
    because "is its audio on" is a producer property — but it is one piece of
    media and Kdenlive's bin should say so."""
    document = mlt.document(
        audio=_audio(60), picture=[mlt.Entry("/media/vo.wav", 0, 60)], rate=RATE
    )
    main_bin = _producer(document, "main_bin")
    assert len(main_bin.findall("entry")) == 2  # the sequence, plus one source
    assert _properties(_producer(document, "chain0"))["kdenlive:id"] == (
        _properties(_producer(document, "vchain0"))["kdenlive:id"]
    )


# -- the profile ----------------------------------------------------------


def test_a_fractional_rate_is_written_as_its_real_fraction() -> None:
    """29.97 is 30000/1001. Written flat it is a frame of drift every hundred
    seconds, which on a six-minute video is four frames of lip-sync."""
    profile = mlt.document(audio=_audio(60), rate=30000 / 1001).find("profile")
    assert profile is not None
    assert (profile.get("frame_rate_num"), profile.get("frame_rate_den")) == ("30000", "1001")


def test_an_integer_rate_stays_an_integer() -> None:
    profile = mlt.document(audio=_audio(60), rate=RATE).find("profile")
    assert profile is not None
    assert (profile.get("frame_rate_num"), profile.get("frame_rate_den")) == ("30", "1")


def test_the_same_project_written_twice_is_the_same_document() -> None:
    """The sequence uuid is derived, not random, so a diff of two exports
    shows what changed in the edit rather than a new uuid every time."""
    first = mlt.to_string(mlt.document(audio=_audio(60), rate=RATE, name="scream"))
    second = mlt.to_string(mlt.document(audio=_audio(60), rate=RATE, name="scream"))
    assert first == second
    other = mlt.to_string(mlt.document(audio=_audio(60), rate=RATE, name="other"))
    assert other != first


# -- positions are frames, not clock time ---------------------------------


def test_entry_positions_are_written_as_frame_integers() -> None:
    """Millisecond text cannot name a 1/29.97s edge; a frame index can. This
    is also what makes the arithmetic checkable by eye."""
    document = mlt.document(audio=_audio(60, 60), rate=RATE)

    playlist = _producer(document, "playlist0")
    assert [(e.get("in"), e.get("out")) for e in playlist.findall("entry")] == [
        ("0", "59"),
        ("60", "119"),
    ]


# -- the reframe ---------------------------------------------------------
#
# Step 3 of the aspect swap. Every assertion here is against geometry that was
# measured on this box before any of it was built (PLAN.md § Aspect swap,
# findings 2 and 3) — a 1920x816 source in a 1080x1920 profile — because on
# this path every failure mode produces a file and exit 0.

WIDE = (1920, 816)
VERTICAL = (1080, 1920)


def test_unaided_mlt_contains_rather_than_fills() -> None:
    """The measured pillarbox: 459 of 1920 rows, the rest black bar. This is
    what a reframe is defined against, not an incidental fact."""
    assert mlt.fit_rect(WIDE, VERTICAL) == (0, 730, 1080, 459)


def test_the_centre_crop_is_the_largest_rect_of_the_canvas_aspect() -> None:
    crop = mlt.centre_crop(WIDE, VERTICAL)

    assert crop == (730, 0, 459, 816)
    assert crop[2] * VERTICAL[1] == crop[3] * VERTICAL[0], "carries the canvas aspect exactly"


def test_the_dest_rect_is_the_measured_fill() -> None:
    """`qtblend`'s rect is a destination in profile pixels, which is why it is
    larger than the profile and starts negative. The probe rendered
    `-1719 0 4518 1920` off the half-pixel centre; the integer rect this
    speaks lands one pixel to its right."""
    reframe = mlt.Reframe(source=WIDE, crop=mlt.centre_crop(WIDE, VERTICAL))

    assert reframe.dest_rect(VERTICAL) == (-1718, 0, 4518, 1920)
    assert reframe.rect_property(VERTICAL) == "-1718 0 4518 1920 1"


def test_a_source_already_at_the_canvas_aspect_is_an_identity() -> None:
    """And so gets no filter at all — which is what keeps every document
    written before this existed byte-identical."""
    for resolution in [(1920, 1080), (1280, 720), (3840, 2160)]:
        reframe = mlt.Reframe(source=(1920, 1080), crop=(0, 0, 1920, 1080))
        assert reframe.is_identity(resolution) is True


def test_a_crop_inside_a_matching_aspect_is_not_an_identity() -> None:
    """A zoom into a 16:9 region of a 16:9 source changes the frame even
    though nothing about the shape did."""
    reframe = mlt.Reframe(source=(1920, 1080), crop=(480, 270, 960, 540))

    assert reframe.is_identity((1920, 1080)) is False
    assert reframe.dest_rect((1920, 1080)) == (-960, -540, 3840, 2160)


def test_the_filter_reaches_both_of_a_files_nodes() -> None:
    """The trap finding 3 names: one node per resource *per role*, so a file
    on the edit and on the picture lane has two. Reaching one of them renders
    a film cropped on one track and letterboxed on the other, at exit 0."""
    audio = [mlt.Entry("/media/cold-open.mp4", 0, 60, has_video=True)]
    lane = mlt.plan_picture([_shot("cold-open", 60, duration=30.0,
                                   path="/media/cold-open.mp4")], RATE)
    reframe = {"/media/cold-open.mp4": mlt.Reframe(WIDE, mlt.centre_crop(WIDE, VERTICAL))}

    root = mlt.document(audio=audio, picture=lane, rate=RATE,
                        resolution=VERTICAL, reframe=reframe)

    reframed = mlt.reframed_nodes(root)
    assert sorted(reframed) == ["chain0", "vchain0"]
    assert set(reframed.values()) == {"-1718 0 4518 1920 1"}


def test_the_bin_keeps_the_raw_media() -> None:
    """The bin is the project's media list, `xml_retain`-ed out of the render.
    A crop is a timeline placement, not a property of the file."""
    audio = [mlt.Entry("/media/cold-open.mp4", 0, 60, has_video=True)]
    reframe = {"/media/cold-open.mp4": mlt.Reframe(WIDE, mlt.centre_crop(WIDE, VERTICAL))}

    root = mlt.document(audio=audio, rate=RATE, resolution=VERTICAL, reframe=reframe)

    bins = [n for n in root.findall("chain") if (n.get("id") or "").startswith("bin")]
    assert bins, "the bin entry exists"
    assert all(not node.findall("filter") for node in bins)


def test_a_still_is_never_cropped() -> None:
    """A card is authored at the canvas and re-authored when it moves
    (`card_reauthor`) — cropping one would be lucid losing a corner of a
    title it drew itself."""
    audio = [mlt.Entry("/media/vo.wav", 0, 60)]
    lane = mlt.plan_picture([_shot("card:title", 60, is_image=True,
                                   path="/cards/title.png")], RATE)
    reframe = {"/cards/title.png": mlt.Reframe(WIDE, mlt.centre_crop(WIDE, VERTICAL))}

    root = mlt.document(audio=audio, picture=lane, rate=RATE,
                        resolution=VERTICAL, reframe=reframe)

    assert mlt.reframed_nodes(root) == {}


def test_no_reframe_leaves_the_document_exactly_as_it_was() -> None:
    audio = [mlt.Entry("/media/cold-open.mp4", 0, 60, has_video=True)]
    plain = mlt.to_string(mlt.document(audio=audio, rate=RATE, resolution=VERTICAL))
    empty = mlt.to_string(
        mlt.document(audio=audio, rate=RATE, resolution=VERTICAL, reframe={})
    )

    assert plain == empty
    assert "qtblend" not in mlt.reframed_nodes(ET.fromstring(plain))


# -- per-shot framing: one node, a window per camera shot ------------------
#
# PLAN.md § Per-shot framing. The address is `(clip_id, src_start, rect)` in
# *source* seconds, and finding 3 measured that this needs no new node: a
# `qtblend` rect is keyframable and its keyframes run on the producer's own
# source frames. So one node still carries every window for that file, which
# is what keeps `reframed_nodes`' one-per-role invariant intact.

LEFT = (0, 0, 459, 816)
RIGHT = (1461, 0, 459, 816)


def test_a_second_window_becomes_discrete_keyframes_in_source_frames() -> None:
    """Source frames, because that is the clock MLT runs a filter's animation
    on — measured from both directions in the probe. Discrete (`|=`) because
    a framing window steps at a camera cut; interpolating would slide the
    frame across the join."""
    reframe = mlt.Reframe(WIDE, LEFT, later=((10.0, RIGHT),))

    assert reframe.rect_property(VERTICAL, RATE) == (
        "0|=0 0 4518 1920 1;300|=-3438 0 4518 1920 1"
    )


def test_one_window_still_writes_the_bare_rect() -> None:
    """The per-clip reframe is the degenerate case, and its document must not
    change: an animated string where a plain one used to be would rewrite
    every project on disk to no effect."""
    reframe = mlt.Reframe(WIDE, mlt.centre_crop(WIDE, VERTICAL))

    assert reframe.rect_property(VERTICAL, RATE) == "-1718 0 4518 1920 1"
    assert reframe.rect_property(VERTICAL) == "-1718 0 4518 1920 1"


def test_keyframes_need_the_rate_and_say_so() -> None:
    reframe = mlt.Reframe(WIDE, LEFT, later=((10.0, RIGHT),))

    with pytest.raises(mlt.MLTError, match="source's own frames"):
        reframe.rect_property(VERTICAL)


def test_the_window_in_force_is_the_last_one_started() -> None:
    reframe = mlt.Reframe(WIDE, LEFT, later=((10.0, RIGHT), (20.0, LEFT)))

    assert reframe.crop_at(0.0) == LEFT
    assert reframe.crop_at(9.999) == LEFT
    assert reframe.crop_at(10.0) == RIGHT
    assert reframe.crop_at(19.0) == RIGHT
    assert reframe.crop_at(20.0) == LEFT
    assert reframe.dest_rect_at(10.0, VERTICAL) == reframe._dest(RIGHT, VERTICAL)


def test_a_moving_window_is_never_an_identity() -> None:
    """The head window can be the exact contain rect while a later one is not;
    skipping the filter on the strength of the first would render the rest of
    the file uncropped, at exit 0."""
    reframe = mlt.Reframe((1920, 1080), (0, 0, 1920, 1080), later=((5.0, (480, 270, 960, 540)),))

    assert reframe.is_identity((1920, 1080)) is False


def test_windows_must_be_ordered_distinct_and_after_the_head() -> None:
    with pytest.raises(mlt.MLTError, match="after the head"):
        mlt.Reframe(WIDE, LEFT, later=((0.0, RIGHT),))
    with pytest.raises(mlt.MLTError, match="source order"):
        mlt.Reframe(WIDE, LEFT, later=((20.0, RIGHT), (10.0, LEFT)))
    with pytest.raises(mlt.MLTError, match="source order"):
        mlt.Reframe(WIDE, LEFT, later=((10.0, RIGHT), (10.0, LEFT)))


def test_every_window_rides_one_node_per_role() -> None:
    """The whole point of finding 3: per-shot framing did not multiply the
    nodes, so the readback invariant that catches a half-applied reframe is
    unchanged."""
    audio = [mlt.Entry("/media/cold-open.mp4", 0, 60, has_video=True)]
    lane = mlt.plan_picture(
        [_shot("cold-open", 60, duration=30.0, path="/media/cold-open.mp4")], RATE
    )
    reframe = {"/media/cold-open.mp4": mlt.Reframe(WIDE, LEFT, later=((10.0, RIGHT),))}

    root = mlt.document(
        audio=audio, picture=lane, rate=RATE, resolution=VERTICAL, reframe=reframe
    )

    reframed = mlt.reframed_nodes(root)
    assert sorted(reframed) == ["chain0", "vchain0"]
    assert set(reframed.values()) == {"0|=0 0 4518 1920 1;300|=-3438 0 4518 1920 1"}
    rendered = [n for n in root.findall("chain") if not (n.get("id") or "").startswith("bin")]
    assert all(len(node.findall("filter")) == 1 for node in rendered)


# -- the stacked split: a second node, half a frame each --------------------
#
# PLAN.md § The stacked split, whose whole finding is that this needed no new
# render path. The mechanism was probed before it was built and the writer's
# own output was then rendered through melt and diffed against ffmpeg's two-
# pane composite of the same source frame — mean |diff| 1.59 against 66.6 for
# the solo crop it replaces, with the seam rows clean. That is HISTORY.md
# § The stacked split, built; it cannot live here, because melt is inside a
# flatpak that cannot see the `/tmp` `tmp_path` hands out.

#: A pane of a 1080x1920 canvas is 1080x960, so a pane window of a 1920x816
#: source is 816 * 1080/960 = 918 wide — twice the 459 one 9:16 crop gets.
PANE_LEFT = (0, 0, 918, 816)
PANE_RIGHT = (1002, 0, 918, 816)


def test_the_panes_tile_the_canvas_with_no_seam() -> None:
    """An odd height would otherwise leave a row of background showing
    between them, which reads as a hairline crack down the middle."""
    upper, lower = mlt.pane_boxes(VERTICAL)

    assert upper == (0, 0, 1080, 960)
    assert lower == (0, 960, 1080, 960)
    assert upper[3] + lower[3] == VERTICAL[1]
    odd_upper, odd_lower = mlt.pane_boxes((1080, 1921))
    assert odd_upper[3] + odd_lower[3] == 1921


def test_a_split_window_scales_each_pane_to_exactly_its_half() -> None:
    """The one thing holding the halves apart: no mask and no crop filter is
    involved anywhere, so a pane that scaled to more than 960 tall would draw
    into the other one. A pane window spans the full source height by
    construction, which makes the scaled frame exactly a pane tall."""
    reframe = mlt.Reframe(WIDE, PANE_LEFT, panes=((0.0, PANE_RIGHT),))

    upper, lower = mlt.pane_boxes(VERTICAL)
    top = reframe._dest(PANE_LEFT, VERTICAL, upper)
    bottom = reframe._dest(PANE_RIGHT, VERTICAL, lower)

    assert top[3] == 960 and bottom[3] == 960, "each scaled frame is one pane tall"
    assert top[1] == 0 and bottom[1] == 960, "and lands on its own half"


def test_a_split_writes_the_upper_pane_on_the_ordinary_node() -> None:
    """The primary node keeps drawing the whole way through and only its
    destination changes — which is why a split needs no `<blank>` on the lane
    itself and cannot leave a hole where it starts."""
    reframe = mlt.Reframe(WIDE, PANE_LEFT, panes=((0.0, PANE_RIGHT),))

    assert reframe.rect_property(VERTICAL, RATE) == "0|=0 0 2259 960 1"
    assert reframe.pane_rect_property(VERTICAL, RATE) == "0|=-1179 960 2259 960 1"


def test_the_pane_is_switched_off_by_opacity_at_every_other_window() -> None:
    """The failure this closes: a step that is not written is a value that
    carries on, so a pane left at opacity 1 past the end of its split draws
    the *next* shot's footage into the bottom half of the frame — at exit 0.
    Rendered rather than reasoned: solo/split/solo came back matching its own
    reference at each of the three, and 61 and 70 away from a pane still on."""
    reframe = mlt.Reframe(
        WIDE, LEFT, later=((2.0, PANE_LEFT), (5.0, RIGHT)), panes=((2.0, PANE_RIGHT),)
    )

    keys = reframe.pane_rect_property(VERTICAL, RATE).split(";")

    assert [key.split("|=")[0] for key in keys] == ["0", "60", "150"]
    assert keys[0].endswith(" 0") and keys[2].endswith(" 0"), "off either side"
    assert keys[1].endswith(" 1"), "and on for its own window"


def test_a_pane_needs_a_window_of_its_own_to_pair_with() -> None:
    """A pane addressed anywhere but at a window's own in-point would render
    as half a frame over whatever framing happened to be in force."""
    with pytest.raises(mlt.MLTError, match="no window of its own"):
        mlt.Reframe(WIDE, LEFT, later=((5.0, RIGHT),), panes=((3.0, PANE_RIGHT),))
    with pytest.raises(mlt.MLTError, match="source order"):
        mlt.Reframe(WIDE, LEFT, panes=((0.0, PANE_RIGHT), (0.0, PANE_LEFT)))


def test_a_split_is_never_an_identity() -> None:
    """Half the frame is being handed to a second node, which is not something
    MLT was already doing however innocent the rects look."""
    square = mlt.Reframe((1920, 1080), (0, 0, 1920, 1080), panes=((0.0, (0, 0, 1920, 1080)),))

    assert square.is_identity((1920, 1080)) is False


def test_a_split_grows_the_document_by_one_node_and_one_track() -> None:
    """A second *node*, not a second service. The pane track sits directly
    over the lane it is half of, so nothing that was already above it moves."""
    audio = [mlt.Entry("/media/vo.wav", 0, 60)]
    lane = mlt.plan_picture(
        [_shot("cold-open", 60, duration=30.0, path="/media/cold-open.mp4")], RATE
    )
    reframe = {"/media/cold-open.mp4": mlt.Reframe(WIDE, PANE_LEFT, panes=((0.0, PANE_RIGHT),))}

    root = mlt.document(
        audio=audio, picture=lane, rate=RATE, resolution=VERTICAL, reframe=reframe
    )

    assert sorted(mlt.reframed_nodes(root)) == ["pvchain0", "vchain0"]
    sequence = [t for t in root.findall("tractor") if t.find("property[@name='kdenlive:uuid']") is not None]
    stack = [track.get("producer") for track in sequence[0].findall("track")]
    assert stack == ["producer0", "tractor0", "tractor1", "tractor4"]
    # b_track is an index into that list, and a pane composites like any other
    # picture track — over the black background, above the lane it halves.
    blends = [
        t.find("property[@name='b_track']").text
        for t in sequence[0].findall("transition")
        if t.find("property[@name='mlt_service']").text == "qtblend"
    ]
    assert blends == ["2", "3"]


def test_the_pane_track_is_blanked_wherever_its_clip_is_not_split() -> None:
    """The one deliberate `<blank>` in this module. Its frame arithmetic is the
    lane's, entry for entry, so the pane track is exactly as long as the track
    it sits over — which `declared_frames` then checks."""
    audio = [mlt.Entry("/media/vo.wav", 0, 90)]
    lane = mlt.plan_picture(
        [
            _shot("card:title", 30, is_image=True, path="/cards/title.png"),
            _shot("cold-open", 30, duration=30.0, path="/media/cold-open.mp4"),
            _shot("card:end", 30, is_image=True, path="/cards/end.png"),
        ],
        RATE,
    )
    reframe = {"/media/cold-open.mp4": mlt.Reframe(WIDE, PANE_LEFT, panes=((0.0, PANE_RIGHT),))}

    root = mlt.document(
        audio=audio, picture=lane, rate=RATE, resolution=VERTICAL, reframe=reframe
    )

    pane_playlist = root.find("playlist[@id='playlist6']")
    assert pane_playlist is not None
    shape = [(child.tag, child.get("length") or child.get("producer")) for child in pane_playlist]
    assert shape == [("blank", "30"), ("entry", "pvchain0"), ("blank", "30")]
    assert sum(int(c.get("length")) for c in pane_playlist if c.tag == "blank") + 30 == 90


def test_the_edit_lanes_split_pane_is_silent() -> None:
    """It is a second producer of the same file — with its audio left on, the
    edit's own sound would be mixed in twice, at exit 0."""
    audio = [mlt.Entry("/media/talk.mp4", 0, 60, has_video=True)]
    reframe = {"/media/talk.mp4": mlt.Reframe(WIDE, PANE_LEFT, panes=((0.0, PANE_RIGHT),))}

    root = mlt.document(audio=audio, rate=RATE, resolution=VERTICAL, reframe=reframe)

    pane = root.find("chain[@id='pchain0']")
    assert pane is not None
    assert pane.find("property[@name='audio_index']").text == "-1"
    assert pane.find("property[@name='set.test_audio']").text == "1"


def test_pane_overlap_is_the_share_of_the_narrower_pane() -> None:
    """The number a stacked split is judged on. Nothing masks a pane, so what
    the two share is source shown twice — once in each half."""
    assert mlt.pane_overlap((0, 0, 900, 816), (900, 0, 900, 816)) == 0.0
    assert mlt.pane_overlap((0, 0, 900, 816), (450, 0, 900, 816)) == 0.5
    assert mlt.pane_overlap((450, 0, 900, 816), (0, 0, 900, 816)) == 0.5, "order does not matter"
    assert mlt.pane_overlap((0, 0, 900, 816), (0, 0, 900, 816)) == 1.0


def test_pane_overlap_separates_the_films_own_splits_from_its_duplicating_ones() -> None:
    """**The line is measured, not chosen.** These are real proposals off the
    Scream cut: the two that hold distinct groups against the two where the
    same face lands in both halves. A rule that could not tell them apart
    would be a number worth nothing to a reviewer.
    """
    distinct = [
        mlt.pane_overlap((153, 0, 900, 816), (845, 0, 900, 816)),  # s4-overexposed 7.632
        mlt.pane_overlap((131, 0, 904, 812), (810, 0, 904, 812)),  # s2022-reveal 4.087
    ]
    duplicating = [
        mlt.pane_overlap((447, 0, 904, 812), (878, 0, 904, 812)),  # vi-bailey 10.052
        mlt.pane_overlap((683, 0, 904, 812), (1016, 0, 904, 812)),  # vi-bailey 19.937
    ]
    assert max(distinct) < 0.30
    assert min(duplicating) > 0.50
