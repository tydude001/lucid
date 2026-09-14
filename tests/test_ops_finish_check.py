"""`finish_check` — the pure pieces: `_time_overlaps`, `_boundary_recheck`'s
merge logic, and `_resolved_hold_spans`'s stored-holds fallback.

`_boundary_recheck` takes its transcription as an injected callable
specifically so the direction-correctness of the missing/boundary_misses
split — the whole point of the feature — can be checked with canned data,
`test_verify.py`'s own discipline for `compare` one level up: no ffmpeg, no
whisper. The end-to-end wiring (a real `finish_check` call against a real
project and a real delivered file) is `tests/test_ops_finish_check_e2e.py`
and the stdio round trip in `tests/test_server_stdio.py`.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from proofcut import asr, ops
from proofcut import timeline as tl
from proofcut import transcript as tx
from proofcut.project import Project, ProjectError

# -- _time_overlaps -----------------------------------------------------------


def test_time_overlaps_true_for_genuinely_overlapping_spans() -> None:
    assert ops._time_overlaps(1.0, 3.0, 2.0, 4.0) is True


def test_time_overlaps_false_for_touching_but_not_overlapping_spans() -> None:
    """Half-open on both sides — [1,2) and [2,3) share no instant."""
    assert ops._time_overlaps(1.0, 2.0, 2.0, 3.0) is False


def test_time_overlaps_false_for_disjoint_spans() -> None:
    assert ops._time_overlaps(0.0, 1.0, 5.0, 6.0) is False


def test_time_overlaps_true_when_one_span_contains_the_other() -> None:
    assert ops._time_overlaps(0.0, 10.0, 2.0, 3.0) is True


# -- _boundary_recheck ---------------------------------------------------------


@dataclass
class _W:
    """A stand-in for `Transcript.words`' entries — `_boundary_recheck` only
    ever reads `.start`/`.end`."""

    start: float
    end: float


HEARD = [_W(0.0, 1.0), _W(1.0, 2.0), _W(2.5, 3.0), _W(3.0, 4.0)]  # "one two five six"
FINAL_DURATION = 6.0


def test_a_recheck_that_finds_the_missing_text_is_recovered_not_a_fault() -> None:
    """The core direction: found close to the missing text -> boundary_misses."""
    dropped = [{"text": "three four", "at_expected_word": 2, "at_heard_word": 2}]

    def transcribe(start: float, length: float) -> str:
        assert start == pytest.approx(1.0)  # heard[1].end(2.0) - pad(1.0)
        assert length == pytest.approx(2.5)  # up to heard[2].start(2.5) + pad(1.0) = 3.5
        return "two three four five"

    missing, boundary_misses = ops._boundary_recheck(
        dropped, HEARD, FINAL_DURATION, pad=1.0, transcribe=transcribe
    )

    assert missing == []
    assert len(boundary_misses) == 1
    assert boundary_misses[0]["text"] == "three four"
    assert boundary_misses[0]["recheck_text"] == "two three four five"
    assert boundary_misses[0]["recheck_similarity"] >= ops.vfy.SIMILAR


def test_a_recheck_that_does_not_find_the_missing_text_stays_a_real_miss() -> None:
    """The other direction: a recheck that genuinely lacks the words stays
    in `missing` — getting this backwards would hide every real defect."""
    dropped = [{"text": "three four", "at_expected_word": 2, "at_heard_word": 2}]

    missing, boundary_misses = ops._boundary_recheck(
        dropped, HEARD, FINAL_DURATION, pad=1.0, transcribe=lambda s, length: "nothing like it"
    )

    assert boundary_misses == []
    assert len(missing) == 1
    assert missing[0]["text"] == "three four"
    assert missing[0]["recheck_text"] == "nothing like it"
    assert missing[0]["recheck_similarity"] < ops.vfy.SIMILAR


def test_a_drop_at_heard_word_zero_rechecks_from_the_start_of_the_file() -> None:
    dropped = [{"text": "zero one", "at_expected_word": 0, "at_heard_word": 0}]
    seen: dict[str, float] = {}

    def transcribe(start: float, length: float) -> str:
        seen["start"] = start
        return "zero one"

    missing, boundary_misses = ops._boundary_recheck(
        dropped, HEARD, FINAL_DURATION, pad=1.0, transcribe=transcribe
    )

    assert seen["start"] == 0.0  # clamped: raw_start(0.0) - pad would be negative
    assert missing == []
    assert len(boundary_misses) == 1


def test_a_drop_at_heard_word_len_heard_rechecks_to_the_end_of_the_file() -> None:
    dropped = [{"text": "seven eight", "at_expected_word": 6, "at_heard_word": len(HEARD)}]
    seen: dict[str, float] = {}

    def transcribe(start: float, length: float) -> str:
        seen["start"], seen["length"] = start, length
        return "seven eight"

    ops._boundary_recheck(dropped, HEARD, FINAL_DURATION, pad=1.0, transcribe=transcribe)

    # raw_start = heard[-1].end (4.0) - pad -> 3.0; raw_end = final_duration
    # (6.0), clamped there rather than growing past it with + pad.
    assert seen["start"] == pytest.approx(3.0)
    assert seen["start"] + seen["length"] == pytest.approx(6.0)


def test_an_empty_span_after_clamping_never_calls_transcribe() -> None:
    """A drop whose own boundary words touch, with pad=0 — nothing to re-cut."""
    dropped = [{"text": "x y", "at_expected_word": 0, "at_heard_word": 1}]
    heard = [_W(0.0, 2.0), _W(2.0, 3.0)]  # heard[0].end == heard[1].start == 2.0

    def transcribe(start: float, length: float) -> str:
        raise AssertionError("must not be called for an empty span")

    missing, boundary_misses = ops._boundary_recheck(
        dropped, heard, FINAL_DURATION, pad=0.0, transcribe=transcribe
    )

    assert boundary_misses == []
    assert missing[0]["recheck_error"] == "nothing to re-cut — the span is empty"


def test_a_transcribe_failure_is_reported_and_the_entry_stays_missing() -> None:
    dropped = [{"text": "three four", "at_expected_word": 2, "at_heard_word": 2}]

    def transcribe(start: float, length: float) -> str:
        raise asr.ASRError("whisper fell over")

    missing, boundary_misses = ops._boundary_recheck(
        dropped, HEARD, FINAL_DURATION, pad=1.0, transcribe=transcribe
    )

    assert boundary_misses == []
    assert "whisper fell over" in missing[0]["recheck_error"]
    assert "recheck_text" not in missing[0]


def test_every_dropped_entry_is_processed_independently() -> None:
    dropped = [
        {"text": "three four", "at_expected_word": 2, "at_heard_word": 2},
        {"text": "seven eight", "at_expected_word": 6, "at_heard_word": len(HEARD)},
    ]

    def transcribe(start: float, length: float) -> str:
        return "three four" if start < 3.0 else "unrelated words entirely"

    missing, boundary_misses = ops._boundary_recheck(
        dropped, HEARD, FINAL_DURATION, pad=1.0, transcribe=transcribe
    )

    assert [m["text"] for m in missing] == ["seven eight"]
    assert [b["text"] for b in boundary_misses] == ["three four"]


# -- _resolved_hold_spans -------------------------------------------------------

CLIPS = {
    "vo": {
        "clip_id": "vo",
        "source": "/tmp/vo.wav",
        "duration": 6.0,
        "has_video": False,
        "has_audio": True,
    },
    "film": {
        "clip_id": "film",
        "source": "/tmp/film.mp4",
        "duration": 30.0,
        "has_video": True,
        "has_audio": True,
    },
}

RATE = 1000.0


def _words(clip_id: str, *specs: tuple[str, float, float]) -> tx.Transcript:
    return tx.Transcript(
        clip_id=clip_id,
        words=tuple(
            tx.Word(index=i, text=text, start=start, end=end) for i, (text, start, end) in enumerate(specs)
        ),
    )


@pytest.fixture
def project(tmp_path: Path) -> Project:
    project = Project.create(tmp_path / "proj")
    manifest = project.read_manifest()
    manifest["clips"] = list(CLIPS.values())
    project.write_manifest(manifest)
    tx.save(
        _words(
            "vo",
            ("the", 0.0, 0.3),
            ("first", 0.5, 0.9),
            ("twelve", 1.0, 1.4),
            ("minutes", 1.5, 1.9),
            ("of", 2.0, 2.2),
            ("scream", 5.0, 5.4),
        ),
        project.transcript_path("vo"),
    )
    tx.save(
        _words(
            "film",
            ("i", 10.0, 10.2),
            ("know", 10.2, 10.5),
            ("what", 10.5, 10.8),
            ("you", 10.8, 11.0),
            ("did", 11.0, 11.3),
        ),
        project.transcript_path("film"),
    )
    edit = tl.Edit([tl.Segment("vo", 0.0, 6.0)])
    tl.write(tl.to_otio(edit, {"vo": CLIPS["vo"]}, rate=RATE), project.timeline_path)
    return project


STORED_HOLD = {
    "clip_id": "vo",
    "gap_word_index": 3,
    "cue_word_index": 2,
    "asset": "film",
    "word_index_first": 0,
    "word_index_last": 4,
    "head_margin": ops.HOLD_HEAD_MARGIN,
    "tail_margin": ops.HOLD_TAIL_MARGIN,
    "under": ops.HOLD_UNDER,
    "fade_in": ops.HOLD_FADE_IN,
    "fade_out": ops.HOLD_FADE_OUT,
}


def test_resolved_hold_spans_is_empty_with_no_stored_holds(project: Project) -> None:
    edit = tl.read(project.timeline_path)
    spans, errors = ops._resolved_hold_spans(project, edit, RATE, 0.0)
    assert spans == []
    assert errors == []


def test_resolved_hold_spans_matches_the_algebra_and_is_never_ducked(project: Project) -> None:
    manifest = project.read_manifest()
    manifest[ops.HOLDS_KEY] = [dict(STORED_HOLD)]
    project.write_manifest(manifest)
    edit = tl.read(project.timeline_path)

    spans, errors = ops._resolved_hold_spans(project, edit, RATE, 0.0)

    assert errors == []
    assert len(spans) == 1
    span = spans[0]
    assert span["name"] == "vo#3"
    # gap_at, from test_ops_holds.py's own worked example.
    assert span["start"] == pytest.approx(1.9)
    assert span["length"] == pytest.approx(1.9)
    assert span["ducked"] is False


def test_resolved_hold_spans_offsets_by_head_seconds(project: Project) -> None:
    """WORK-ORDERS ruling 5: a head prepends real seconds in front of the
    Edit, so every hold's own `start` in `final`'s absolute time must carry
    that offset."""
    manifest = project.read_manifest()
    manifest[ops.HOLDS_KEY] = [dict(STORED_HOLD)]
    project.write_manifest(manifest)
    edit = tl.read(project.timeline_path)

    no_head, _ = ops._resolved_hold_spans(project, edit, RATE, 0.0)
    with_head, _ = ops._resolved_hold_spans(project, edit, RATE, 4.5)

    assert with_head[0]["start"] == pytest.approx(no_head[0]["start"] + 4.5)
    assert with_head[0]["length"] == pytest.approx(no_head[0]["length"])


def test_resolved_hold_spans_reports_an_unresolvable_hold_and_keeps_going(
    project: Project,
) -> None:
    """`hold_ls`'s own policy: one bad hold is reported, not fatal."""
    manifest = project.read_manifest()
    manifest[ops.HOLDS_KEY] = [dict(STORED_HOLD)]
    project.write_manifest(manifest)
    # Cut the gap word entirely, orphaning this hold (test_ops_holds.py's
    # own way of provoking `_hold_plan`'s "not on the timeline" refusal).
    cut_edit = tl.Edit([tl.Segment("vo", 0.0, 1.2)])

    spans, errors = ops._resolved_hold_spans(project, cut_edit, RATE, 0.0)

    assert spans == []
    assert len(errors) == 1
    assert errors[0]["clip_id"] == "vo"
    assert errors[0]["gap_word_index"] == 3
    assert "not on the timeline" in errors[0]["hold_error"]


# -- finish_check: argument validation, no I/O ----------------------------------


def test_finish_check_refuses_a_missing_final_file(project: Project) -> None:
    with pytest.raises(Exception, match="no such file"):
        ops.finish_check(project.root, project.root / "nope.mp4")


def test_finish_check_refuses_a_negative_prepend(project: Project, tmp_path: Path) -> None:
    final = tmp_path / "final.wav"
    final.write_bytes(b"not real media, never reached")
    with pytest.raises(ProjectError, match="prepend_seconds must not be negative"):
        ops.finish_check(project.root, final, prepend_seconds=-1.0)


def test_finish_check_refuses_a_malformed_explicit_hold(project: Project, tmp_path: Path) -> None:
    final = tmp_path / "final.wav"
    final.write_bytes(b"not real media, never reached")
    with pytest.raises(ProjectError, match=r"holds\[0\]"):
        ops.finish_check(project.root, final, holds=[{"name": "x"}])
