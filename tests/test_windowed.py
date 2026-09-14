"""The windowed transcription pass, with no whisper and no GPU.

Everything here is the arithmetic between ffmpeg and whisper: where the windows
land, whose copy of an overlapping word survives, and how a window's timings
become whole-file timings. That arithmetic is what makes a windowed result
addressable at all — a word stamped with its window's clock instead of the
file's would point at the wrong audio, which is the one failure this module
cannot be allowed to introduce.

The whisper subprocess itself is exercised against real media by hand; there is
nothing to learn from mocking it.
"""

from __future__ import annotations

import itertools

import pytest

from proofcut import asr


def _word(text: str, start: float, end: float) -> dict[str, object]:
    return {"word": text, "start": start, "end": end}


# -- where the windows land ----------------------------------------------


def test_windows_step_by_window_minus_overlap() -> None:
    windows = asr.plan_windows(25.0, window=10.0, overlap=3.0)

    assert windows == [(0.0, 10.0), (7.0, 17.0), (14.0, 24.0), (21.0, 25.0)]


def test_a_file_shorter_than_one_window_gets_one_window() -> None:
    assert asr.plan_windows(6.0, window=10.0, overlap=3.0) == [(0.0, 6.0)]


def test_the_windows_cover_the_whole_file_with_no_hole() -> None:
    """A hole would be audio no window transcribed, i.e. words silently lost."""
    windows = asr.plan_windows(311.0, window=10.0, overlap=3.0)

    assert windows[0][0] == 0.0
    assert windows[-1][1] == 311.0
    for (_, previous_end), (next_start, _) in itertools.pairwise(windows):
        assert next_start < previous_end


def test_the_last_window_is_never_shorter_than_the_overlap() -> None:
    """Documented in plan_windows, and cheap enough to hold it to."""
    for tenths in range(1, 1200):
        windows = asr.plan_windows(tenths / 10, window=10.0, overlap=3.0)
        start, end = windows[-1]
        assert end - start > 3.0 or len(windows) == 1


def test_window_starts_do_not_drift_over_a_long_file() -> None:
    """`k * step`, not an accumulating sum — the offsets are stamped onto words."""
    windows = asr.plan_windows(3600.0, window=10.0, overlap=3.0)

    assert windows[-2][0] == pytest.approx(len(windows[:-2]) * 7.0, abs=1e-9)


def test_a_window_that_is_all_overlap_is_refused() -> None:
    with pytest.raises(asr.ASRError, match="overlap must be"):
        asr.plan_windows(30.0, window=10.0, overlap=10.0)
    with pytest.raises(asr.ASRError, match="window must be positive"):
        asr.plan_windows(30.0, window=0.0, overlap=0.0)
    with pytest.raises(asr.ASRError, match="nothing to window"):
        asr.plan_windows(0.0)


# -- whose copy of an overlapping word survives ---------------------------


def test_each_word_is_kept_exactly_once() -> None:
    """The property the whole pass rests on: a partition, not a merge.

    Both windows heard "inside", because it sits in their overlap. Keeping both
    copies would read downstream as a phrase the render played twice — the
    windowed pass would invent a retake at every seam.
    """
    windows = [(0.0, 10.0), (7.0, 17.0)]
    heard = [
        [_word("the", 6.0, 6.4), _word("inside", 8.0, 8.6)],
        [_word("inside", 8.0, 8.6), _word("house", 11.0, 11.5)],
    ]

    kept = asr._reconcile(windows, heard)

    assert [w["word"] for w in kept] == ["the", "inside", "house"]


def test_the_copy_nearer_its_own_window_centre_wins() -> None:
    """A window transcribes its middle better than its edge, so prefer the middle.

    8.0 s is 3.0 from window 0's centre (5.0) and 4.0 from window 1's (12.0),
    so window 0's spelling is the one that survives — even though window 1 also
    heard the word.
    """
    windows = [(0.0, 10.0), (7.0, 17.0)]
    heard = [[_word("centre", 7.8, 8.2)], [_word("edge", 7.8, 8.2)]]

    assert [w["word"] for w in asr._reconcile(windows, heard)] == ["centre"]

    # And past the midpoint of the overlap it flips.
    heard = [[_word("edge", 9.4, 9.8)], [_word("centre", 9.4, 9.8)]]
    assert [w["word"] for w in asr._reconcile(windows, heard)] == ["centre"]


def test_a_word_is_never_handed_to_a_window_that_did_not_cover_it() -> None:
    """The short final window's centre sits left of where even spacing implies.

    At 13.9 s the nearest centre is the last window's (15.75), but that window
    starts at 14.0 and never heard the word. Awarding it there would drop the
    word from the transcript entirely: the window that has it discards its copy
    and the winner has none.
    """
    windows = asr.plan_windows(17.5, window=10.0, overlap=3.0)
    assert windows[-1] == (14.0, 17.5)

    heard: list[list[dict[str, object]]] = [[], [_word("orphan", 13.8, 14.0)], []]

    assert [w["word"] for w in asr._reconcile(windows, heard)] == ["orphan"]


def test_reconciled_words_come_back_in_time_order() -> None:
    """Word *order* is the entire signal verify reads; window order is not it."""
    windows = [(0.0, 10.0), (7.0, 17.0), (14.0, 24.0)]
    heard = [
        # Out of order inside the window too, which whisper does not do — but
        # the sort must not be relying on it not doing it.
        [_word("two", 6.9, 7.4), _word("one", 1.0, 1.5)],
        [_word("three", 12.0, 12.5)],
        [_word("four", 20.0, 20.5)],
    ]

    assert [w["word"] for w in asr._reconcile(windows, heard)] == [
        "one",
        "two",
        "three",
        "four",
    ]


def test_a_word_only_the_non_owning_window_heard_is_kept_anyway() -> None:
    """Ownership decides between two copies; it must not discard the only one.

    7.15 s belongs to window 0 — it is nearer that centre. Window 0 did not
    hear the word, so discarding window 1's copy on ownership alone would lose
    it outright. Measured on the scored Scream v3 export: partitioning on
    ownership alone dropped 22 words mid-sentence, and re-admitting recovered
    14 of them.
    """
    windows = [(0.0, 10.0), (7.0, 17.0)]
    heard: list[list[dict[str, object]]] = [[], [_word("missed", 6.9, 7.4)]]

    assert [w["word"] for w in asr._reconcile(windows, heard)] == ["missed"]


def test_a_backfilled_word_is_admitted_once_however_many_windows_have_it() -> None:
    """Two copies re-admitted would read downstream as a phrase played twice."""
    windows = asr.plan_windows(24.0, window=10.0, overlap=3.0)
    # 7.15s is owned by window 0, which heard nothing; both other windows have
    # a copy, and only one of them may come back.
    heard: list[list[dict[str, object]]] = [
        [],
        [_word("missed", 6.9, 7.4)],
        [_word("missed", 6.95, 7.45)],
    ]

    assert [w["word"] for w in asr._reconcile(windows, heard)] == ["missed"]


def test_backfill_does_not_override_a_word_the_owner_did_hear() -> None:
    """The owner's copy is the better one; a backfill is a last resort, not a merge."""
    windows = [(0.0, 10.0), (7.0, 17.0)]
    heard = [[_word("centre", 7.8, 8.2)], [_word("edge", 7.9, 8.3)]]

    assert [w["word"] for w in asr._reconcile(windows, heard)] == ["centre"]


def test_every_instant_of_a_long_file_has_an_owner_that_covers_it() -> None:
    """Swept rather than argued: an orphaned instant is a silently lost word."""
    windows = asr.plan_windows(311.0, window=10.0, overlap=3.0)
    centres = [(a + b) / 2 for a, b in windows]

    for tenths in range(3111):
        t = tenths / 10
        start, end = windows[asr._owner(windows, centres, t)]
        assert start <= t <= end, f"{t}s was awarded to a window that excludes it"


# -- whisper's repetition loop --------------------------------------------


def test_a_stack_of_words_on_one_instant_is_dropped_as_a_repetition_loop() -> None:
    """Measured on the Scream v1 export: sixteen words all stamped 229.98 s.

    A verbatim copy of an earlier phrase, spliced mid-sentence, which `verify`
    then reported as a retake that is not in the audio. Short windows make this
    likelier, so the windowed pass has to clean up after itself.
    """
    words = [
        _word("real", 1.0, 1.4),
        *[_word(w, 2.0, 2.0) for w in ("a", "hallucinated", "run", "of", "words")],
        _word("also-real", 3.0, 3.4),
    ]

    kept, dropped = asr._drop_stacked(words)

    assert [w["word"] for w in kept] == ["real", "also-real"]
    assert dropped == 5


def test_a_lone_zero_length_word_is_kept() -> None:
    """Whisper gives a short token a zero span often enough; that is not a loop."""
    words = [_word("a", 1.0, 1.4), _word("blip", 2.0, 2.0), _word("b", 3.0, 3.4)]

    kept, dropped = asr._drop_stacked(words)

    assert [w["word"] for w in kept] == ["a", "blip", "b"]
    assert dropped == 0


def test_zero_length_words_at_different_instants_are_not_a_stack() -> None:
    """It is the stacking that is impossible, not the zero length."""
    words = [_word("a", 1.0, 1.0), _word("b", 2.0, 2.0), _word("c", 3.0, 3.0)]

    kept, dropped = asr._drop_stacked(words)

    assert len(kept) == 3 and dropped == 0


# -- window time becomes file time ----------------------------------------


def test_words_are_stamped_back_into_whole_file_time() -> None:
    """A word carrying its window's clock would point at the wrong audio."""
    payload = {
        "segments": [
            {"words": [{"word": "bit", "start": 1.5, "end": 1.9}]},
            {"words": [{"word": "of", "start": 2.0, "end": 2.2}]},
        ]
    }

    words = asr._absolute(payload, 42.0)

    assert words == [
        {"word": "bit", "start": 43.5, "end": 43.9},
        {"word": "of", "start": 44.0, "end": 44.2},
    ]


def test_a_window_whisper_heard_nothing_in_contributes_nothing() -> None:
    assert asr._absolute({"segments": []}, 7.0) == []
    assert asr._absolute({}, 7.0) == []


def test_one_unusable_word_does_not_cost_the_window_its_others() -> None:
    """The overlapping window very likely has a good copy of the bad one."""
    payload = {
        "segments": [
            {
                "words": [
                    {"word": "good", "start": 0.1, "end": 0.4},
                    {"word": "bad", "start": None, "end": 1.0},
                    {"word": "  ", "start": 1.1, "end": 1.4},
                    {"word": "also-good", "start": 2.0, "end": 2.4},
                ]
            }
        ]
    }

    assert [w["word"] for w in asr._absolute(payload, 0.0)] == ["good", "also-good"]


def test_the_windowed_pass_reads_for_a_smaller_model_than_a_single_pass() -> None:
    """Not an oversight: a bigger model writes more fluent prose, and the whole
    point of the windowed pass is to catch disfluency it would tidy away."""
    assert asr.WINDOWED_MODEL != asr.DEFAULT_MODEL
    assert asr.OVERLAP < asr.WINDOW


def test_the_window_is_short_enough_that_a_retake_cannot_hide_in_one() -> None:
    """3.96 s is the longest single-word collapse measured (HISTORY.md § 2).

    The window has to be comfortably longer than that — otherwise the second
    take is not merely collapsed, it is cut off — and comfortably shorter than
    whisper's 30 s attention window, which is what gave it room in the first
    place.
    """
    assert 3.96 * 2 < asr.WINDOW < 30.0


def test_the_default_overlap_gives_every_instant_two_readings() -> None:
    """Backfill can only repair a hole where a second window also heard it.

    At an overlap below half the window, most of a file sits inside exactly one
    window and a word that window missed is gone for good — measured at 57% of
    the file, and eleven words, on the scored Scream v3 export.
    """
    assert asr.OVERLAP >= asr.WINDOW / 2

    # The first and last window each have nothing beyond them to double up
    # with; everything between them must be two-covered.
    windows = asr.plan_windows(302.0)
    interior = range(int(asr.OVERLAP * 10), int(windows[-1][0] * 10) + 1)
    for tenth in interior:
        t = tenth / 10
        assert sum(1 for a, b in windows if a <= t <= b) >= 2, f"{t}s has one reading"


# -- the ingest path's guard ----------------------------------------------
#
# `_drop_stacked` above ran only in the windowed pass, so `lucid transcribe`
# had no hallucination guard at all. Wiring the same rule across was the
# obvious fix and it is not sufficient: on the October scale spike's own
# artifact it drops three of eight. `_drop_dense` is the rest, and its two
# numbers come from sweeping every transcript on this box — see
# `asr.CLUSTER_WINDOW`.


def test_the_spike_tail_is_not_caught_by_the_stacked_rule_alone() -> None:
    """The shape that made a second rule necessary, transcribed verbatim.

    whisper's last 0.20 s of a 120 s slice: eight words echoing an earlier
    sentence. Only the first three share an instant, which is what the
    identical-instant rule can see.
    """
    tail = [
        _word("people", 119.78, 119.78),
        _word("were", 119.78, 119.78),
        _word("really", 119.78, 119.78),
        _word("well", 119.78, 119.88),
        _word("people", 119.88, 119.94),
        _word("of", 119.94, 119.94),
        _word("you", 119.94, 119.98),
        _word("know", 119.98, 119.98),
    ]
    words = [_word("alive", 118.12, 118.70), _word("you", 118.70, 119.64),
             _word("know", 119.64, 119.78), *tail]

    _, stacked_only = asr._drop_stacked(words)
    assert stacked_only == 3

    kept, dropped = asr.clean(words)
    assert dropped == 8
    assert [w["word"] for w in kept] == ["alive", "you", "know"]


def test_real_speech_at_its_densest_is_left_alone() -> None:
    """The Scream VO's tightest real cluster: three words inside 0.06 s.

    Whisper's word durations are not to be trusted (CLAUDE.md), so real speech
    reaches rates no mouth could — which is exactly why the rule counts words
    in a window rather than scoring a rate, and why the floor is 5 and not 3.
    """
    words = [
        _word("a", 93.90, 93.92),
        _word("b", 93.92, 93.94),
        _word("c", 93.94, 93.96),
        _word("d", 94.30, 94.60),
    ]

    kept, dropped = asr.clean(words)
    assert dropped == 0 and len(kept) == 4


def test_a_dense_run_gives_up_only_its_dense_head() -> None:
    """A loop that decays back into ordinary timings keeps its ordinary tail."""
    words = [
        *[_word(f"loop{i}", 10.0 + i * 0.02, 10.0 + i * 0.02) for i in range(6)],
        _word("real", 11.0, 11.4),
        _word("speech", 11.5, 11.9),
    ]

    kept, dropped = asr.clean(words)
    assert dropped == 6
    assert [w["word"] for w in kept] == ["real", "speech"]


def test_clean_payload_rewrites_the_segment_it_emptied() -> None:
    """A payload must never state a sentence it no longer holds the words for."""
    payload = {
        "language": "en",
        "segments": [
            {
                "start": 0.0,
                "end": 1.0,
                "text": " real speech here",
                "words": [
                    {"word": " real", "start": 0.0, "end": 0.3},
                    {"word": " speech", "start": 0.3, "end": 0.6},
                    {"word": " here", "start": 0.6, "end": 1.0},
                ],
            },
            {
                "start": 1.0,
                "end": 1.1,
                "text": " a b c d e",
                "words": [
                    {"word": " a", "start": 1.00, "end": 1.00},
                    {"word": " b", "start": 1.00, "end": 1.02},
                    {"word": " c", "start": 1.02, "end": 1.04},
                    {"word": " d", "start": 1.04, "end": 1.06},
                    {"word": " e", "start": 1.06, "end": 1.08},
                ],
            },
        ],
    }

    dropped = asr.clean_payload(payload)

    assert dropped == 5
    assert payload["segments"][0]["text"] == " real speech here"
    assert payload["segments"][1]["words"] == []
    assert payload["segments"][1]["text"] == ""


def test_clean_payload_handles_the_flat_shape_too() -> None:
    """`parse_whisper` takes a top-level `words` list; so does this, and first."""
    payload = {
        "words": [
            {"word": "real", "start": 0.0, "end": 0.5},
            *[{"word": "x", "start": 1.0 + i * 0.01, "end": 1.0 + i * 0.01} for i in range(5)],
        ]
    }

    assert asr.clean_payload(payload) == 5
    assert [w["word"] for w in payload["words"]] == ["real"]


def test_clean_payload_leaves_an_unusable_entry_for_parse_whisper_to_refuse() -> None:
    """Dropping it here would take away a refusal that is deliberate."""
    payload = {"words": [{"word": "broken"}, {"word": "fine", "start": 0.0, "end": 0.4}]}

    assert asr.clean_payload(payload) == 0
    assert len(payload["words"]) == 2
