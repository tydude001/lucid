"""Caption generation: the timeline mapping, the grouping, and the ASS text.

The mapping is the part that can be silently wrong — a caption emitted at a
source time still *looks* like a caption, it just fires at the wrong moment on
a timeline that has been cut. So the arithmetic gets pinned down here rather
than eyeballed in a player.
"""

from __future__ import annotations

import re
from itertools import pairwise

import pytest

from lucid.captions import (
    DEFAULT_GROUPING,
    PRESETS,
    CaptionError,
    CueWord,
    ass_colour,
    css_colour,
    font_match,
    group,
    place,
    preset,
    resolve,
    to_ass,
)
from lucid.timeline import Edit, Segment
from lucid.transcript import Transcript, Word


def _edit(*spans: tuple[float, float], clip_id: str = "vo") -> Edit:
    return Edit([Segment(clip_id, a, b) for a, b in spans])


def _transcript(*words: tuple[str, float, float], clip_id: str = "vo") -> Transcript:
    return Transcript(
        clip_id=clip_id,
        words=tuple(
            Word(index=n, text=t, start=a, end=b) for n, (t, a, b) in enumerate(words)
        ),
    )


def _words(*spans: tuple[float, float]) -> list[CueWord]:
    return [CueWord(text=f"w{n}", start=a, end=b) for n, (a, b) in enumerate(spans)]


# -- placing words on the timeline ---------------------------------------


def test_words_are_placed_in_timeline_time() -> None:
    """A cut earlier in the recording moves every later caption earlier."""
    edit = _edit((0.0, 2.0), (5.0, 10.0))
    placed, cut = place(edit, {"vo": _transcript(("one", 0.5, 1.0), ("two", 6.0, 6.5))})

    assert cut == 0
    assert placed[0].start == pytest.approx(0.5)
    # Source 6.0 is 1.0s into the second segment, which begins at timeline 2.0.
    assert placed[1].start == pytest.approx(3.0)
    assert placed[1].end == pytest.approx(3.5)


def test_cut_words_are_dropped_and_counted() -> None:
    edit = _edit((0.0, 2.0), (5.0, 10.0))
    placed, cut = place(edit, {"vo": _transcript(("gone", 3.0, 3.5), ("kept", 6.0, 6.5))})

    assert [w.text for w in placed] == ["kept"]
    assert cut == 1


def test_a_word_straddling_a_cut_is_truncated_not_stretched() -> None:
    """Only the audible half survives, so the caption matches what is heard."""
    edit = _edit((0.0, 2.0))
    placed, _ = place(edit, {"vo": _transcript(("half", 1.5, 3.0))})

    assert placed[0].start == pytest.approx(1.5)
    assert placed[0].end == pytest.approx(2.0)


def test_zero_length_words_survive() -> None:
    """Whisper emits start == end occasionally; it must not vanish."""
    placed, cut = place(_edit((0.0, 5.0)), {"vo": _transcript(("blip", 1.0, 1.0))})
    assert cut == 0 and [w.text for w in placed] == ["blip"]


def test_words_from_several_clips_interleave_by_timeline_position() -> None:
    """Source order says nothing across clips — only timeline order does."""
    edit = Edit([Segment("b", 0.0, 5.0), Segment("a", 0.0, 5.0)])
    placed, _ = place(
        edit,
        {
            "a": _transcript(("second", 1.0, 1.5), clip_id="a"),
            "b": _transcript(("first", 1.0, 1.5), clip_id="b"),
        },
    )
    assert [w.text for w in placed] == ["first", "second"]


# -- grouping ------------------------------------------------------------


def test_grouping_breaks_at_the_word_limit() -> None:
    cues = group(_words((0.0, 0.4), (0.5, 0.9), (1.0, 1.4)), max_words=2, hold=0.0)
    assert [c.text for c in cues] == ["w0 w1", "w2"]


def test_grouping_breaks_on_a_silence() -> None:
    cues = group(_words((0.0, 0.4), (2.0, 2.4)), max_gap=0.5, hold=0.0)
    assert len(cues) == 2


def test_grouping_breaks_after_a_sentence() -> None:
    words = [
        CueWord("Right.", 0.0, 0.4),
        CueWord("Next", 0.5, 0.9),
    ]
    assert [c.text for c in group(words, hold=0.0)] == ["Right.", "Next"]


def test_grouping_breaks_when_a_line_runs_too_long() -> None:
    cues = group(_words((0.0, 1.0), (1.1, 2.0), (2.1, 3.0)), max_duration=2.5, hold=0.0)
    assert len(cues) == 2


def test_grouping_measures_gaps_after_the_cut_not_before_it() -> None:
    """Two words far apart in the source but adjacent after a cut are one cue."""
    edit = _edit((0.0, 1.0), (9.0, 10.0))
    placed, _ = place(edit, {"vo": _transcript(("a", 0.1, 0.5), ("b", 9.1, 9.5))})
    assert len(group(placed, max_gap=0.7, hold=0.0)) == 1


def test_hold_extends_a_cue_but_never_into_the_next_one() -> None:
    cues = group(_words((0.0, 0.4), (3.0, 3.4)), max_gap=0.5, hold=5.0)
    assert cues[0].end == pytest.approx(3.0)  # clamped to the next cue's start
    assert cues[1].end == pytest.approx(8.4)  # nothing follows, so held in full


def test_cues_never_overlap() -> None:
    cues = group(_words((0.0, 0.4), (1.0, 1.4), (2.0, 2.4)), max_words=1, hold=0.4)
    for earlier, later in pairwise(cues):
        assert earlier.end <= later.start + 1e-9


def test_grouping_rejects_a_nonsense_word_limit() -> None:
    with pytest.raises(CaptionError, match="at least 1"):
        group(_words((0.0, 0.4)), max_words=0)


# -- ASS -----------------------------------------------------------------


def test_ass_has_the_sections_libass_needs() -> None:
    text = to_ass(group(_words((0.0, 0.4)), hold=0.0), style=preset("clean"))
    assert "[Script Info]" in text
    assert "[V4+ Styles]" in text
    assert "[Events]" in text
    assert text.count("Dialogue:") == 1


def test_ass_times_are_centisecond_stamps() -> None:
    cues = group([CueWord("x", 3661.23, 3661.5)], hold=0.0)
    assert "Dialogue: 0,1:01:01.23,1:01:01.50," in to_ass(cues, style=preset("clean"))


def test_karaoke_tags_cover_the_whole_cue() -> None:
    """The \\k durations must sum to the cue, or the highlight drifts off the audio."""
    cues = group(_words((0.0, 0.4), (0.5, 1.0), (1.2, 1.6)), max_words=3, hold=0.0)
    text = to_ass(cues, style=preset("karaoke"))

    import re

    tags = [int(v) for v in re.findall(r"\\k(\d+)", text)]
    assert tags == [40, 60, 60]
    assert sum(tags) == pytest.approx((cues[0].end - cues[0].start) * 100, abs=1)


def test_the_clean_preset_emits_no_karaoke_tags() -> None:
    assert "\\k" not in to_ass(group(_words((0.0, 0.4)), hold=0.0), style=preset("clean"))


def test_braces_in_a_word_cannot_open_an_override_block() -> None:
    """`{` starts ASS markup — a word containing one would be swallowed."""
    text = to_ass(group([CueWord("{drop}", 0.0, 0.4)], hold=0.0), style=preset("clean"))
    assert "(drop)" in text
    assert "{drop}" not in text


def test_resolution_reaches_the_script_header() -> None:
    text = to_ass(group(_words((0.0, 0.4)), hold=0.0), style=preset("clean"), resolution=(3840, 2160))
    assert "PlayResX: 3840" in text
    assert "PlayResY: 2160" in text


def test_the_canvas_keeps_a_fixed_height_so_font_sizes_travel() -> None:
    """PlayRes is a reference frame; writing real pixel sizes there breaks scale."""
    from lucid.captions import canvas

    assert canvas(3840, 2160) == (1920, 1080)
    assert canvas(320, 240) == (1440, 1080)  # 4:3, not 320x240
    assert canvas(1080, 1920) == (608, 1080)  # vertical stays vertical
    assert canvas(None, None) == (1920, 1080)


def test_every_preset_renders() -> None:
    cues = group(_words((0.0, 0.4), (0.5, 1.0)), hold=0.0)
    for name in PRESETS:
        assert to_ass(cues, style=preset(name)).count("Dialogue:") == 1


def test_an_unknown_preset_lists_the_real_ones() -> None:
    with pytest.raises(CaptionError, match="clean"):
        preset("neon")


# -- the stored style ----------------------------------------------------
#
# The colour tests are the load-bearing ones. ASS quotes a colour as
# `&HAABBGGRR` — the channels reversed *and* the alpha byte inverted relative
# to CSS — so a value that survived a careless port is not slightly off, it is
# a different colour at a different opacity, and it still renders.


def test_a_colour_is_reversed_and_alpha_inverted() -> None:
    # Pure red, fully opaque: CSS ff0000 / alpha ff, ASS 0000FF / alpha 00.
    assert ass_colour("#ff0000") == "&H000000FF"
    assert ass_colour("#0000ff") == "&H00FF0000"
    # Half-transparent black: CSS alpha 0x80 opacity -> ASS 0x7f transparency.
    assert ass_colour("#00000080") == "&H7F000000"


def test_every_colour_form_survives_a_round_trip() -> None:
    for value in ("#ff0000", "#0000ffff", "#12345678", "#abc", "yellow", "transparent"):
        there = ass_colour(value)
        assert ass_colour(css_colour(there)) == there, value


def test_an_ass_colour_passes_straight_through() -> None:
    """Otherwise a stored style would be re-inverted every time it was read."""
    assert ass_colour("&H80FF00FF") == "&H80FF00FF"
    assert ass_colour(ass_colour("#ff0000")) == "&H000000FF"


def test_an_unreadable_colour_names_what_is_accepted() -> None:
    with pytest.raises(CaptionError, match="#rrggbb"):
        ass_colour("chartreuse")


# -- resolution ----------------------------------------------------------


def test_only_the_overrides_are_stored() -> None:
    """A flattened copy would freeze a preset's other fields at today's values."""
    style = resolve({"preset": "boxed", "size": 72})
    assert style.stored == {"preset": "boxed", "size": 72}
    assert style.ass.size == 72
    assert style.ass.font == PRESETS["boxed"].font
    assert style.ass.border_style == PRESETS["boxed"].border_style


def test_text_is_the_secondary_slot_when_karaoke_is_on() -> None:
    """ASS's Primary is the *spoken* colour — the trap this layer exists for."""
    style = resolve({"preset": "karaoke", "text": "#ffffff", "highlight": "#ff0000"})
    assert style.ass.secondary == ass_colour("#ffffff")
    assert style.ass.primary == ass_colour("#ff0000")
    assert style.describe()["resolved"]["text"] == "#ffffffff"
    assert style.describe()["resolved"]["highlight"] == "#ff0000ff"


def test_text_takes_both_slots_when_karaoke_is_off() -> None:
    style = resolve({"preset": "clean", "text": "#00ff00"})
    assert style.ass.primary == style.ass.secondary == ass_colour("#00ff00")


def test_karaoke_over_a_plain_preset_still_shows_a_highlight() -> None:
    """Both slots equal would emit \\k tags that change nothing visible."""
    style = resolve({"preset": "clean", "karaoke": True})
    assert style.ass.primary != style.ass.secondary
    assert "\\k" in to_ass(group(_words((0.0, 0.4)), hold=0.0), style=style.ass)


def test_a_named_position_becomes_an_alignment_and_back() -> None:
    style = resolve({"position": "top-right"})
    assert style.ass.alignment == 9
    assert style.describe()["resolved"]["position"] == "top-right"


def test_an_unknown_field_is_refused_rather_than_ignored() -> None:
    """A silently dropped typo looks exactly like a setting that had no effect."""
    with pytest.raises(CaptionError, match="fontsize"):
        resolve({"fontsize": 40})


def test_an_unknown_preset_is_refused_at_store_time() -> None:
    with pytest.raises(CaptionError, match="neon"):
        resolve({"preset": "neon"})


def test_grouping_is_part_of_the_stored_style() -> None:
    """Line breaks are as much of the look as the font — and if they were not
    stored, the preview and the burn-in would group differently."""
    style = resolve({"max_words": 2})
    assert style.max_words == 2
    assert style.max_gap == DEFAULT_GROUPING["max_gap"]
    cues = group(_words((0.0, 0.4), (0.5, 1.0), (1.1, 1.5)), max_words=style.max_words, hold=0.0)
    assert [len(c.words) for c in cues] == [2, 1]


def test_the_default_style_is_the_clean_preset() -> None:
    assert resolve(None).ass == PRESETS["clean"]
    assert resolve({}).stored == {}


# -- the karaoke spans the preview and the burn-in share -----------------


def test_a_highlight_span_covers_the_gap_before_its_word() -> None:
    """`\\k` durations are cumulative from the cue's start, so a word lights up
    the moment the previous one ended — not at its own start. The preview
    overlay reads these same numbers off `as_dict`."""
    cue = group(_words((0.0, 0.4), (0.9, 1.3)), hold=0.0)[0]
    spans = cue.karaoke_spans()
    assert [(lit, until) for _, lit, until in spans] == [(0.0, 0.4), (0.4, 1.3)]

    words = cue.as_dict()["words"]
    assert words[1]["start"] == 0.9, "the word still reports when it is spoken"
    assert words[1]["highlight_start"] == 0.4, "but lights up when the last one ended"


def test_the_spans_and_the_k_tags_are_the_same_numbers() -> None:
    cue = group(_words((0.0, 0.4), (0.9, 1.3), (1.35, 2.0)), hold=0.0)[0]
    text = to_ass([cue], style=resolve({"preset": "karaoke"}).ass)
    tags = [int(n) for n in re.findall(r"\\k(\d+)", text)]
    assert tags == [round((until - lit) * 100) for _, lit, until in cue.karaoke_spans()]


# -- the font that is not there ------------------------------------------


def test_a_missing_font_is_reported_rather_than_substituted_silently() -> None:
    """The one styling failure with no symptom: libass swaps the font, ffmpeg
    exits 0, and the render is in a typeface nobody picked."""
    match = font_match("Definitely Not A Real Font 91537")

    assert match["available"] is False
    assert match["resolves_to"]
    assert "not installed" in match["warning"]


def test_a_font_that_is_there_carries_no_warning() -> None:
    installed = font_match("Definitely Not A Real Font 91537")["resolves_to"]
    match = font_match(installed)

    assert match["available"] is True
    assert "warning" not in match
