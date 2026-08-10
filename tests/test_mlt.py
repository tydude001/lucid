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
