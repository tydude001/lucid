"""`describe` — step 1 of PLAN.md § B-roll by description.

The vision model itself is a subprocess under another interpreter and is not
exercised here: loading it costs 15s and 31 GB of weights, and what these
tests are about is the *shape* around it — how footage is split into windows,
what gets stored, what is skipped, and what is refused. `describe_windows` is
substituted for a stub in the op tests, the same way nothing here shells out
to whisper to test `transcribe`'s bookkeeping.

The one thing worth stating as a test rather than a comment is the property
the whole design rests on: **a description indexes the source, so cutting the
edit cannot invalidate one.** That is the last test in the file.
"""

from __future__ import annotations

from itertools import pairwise
from pathlib import Path
from typing import Any

import pytest

from lucid import describe as dsc
from lucid import ops
from lucid import timeline as tl
from lucid import transcript as tx
from lucid.describe import DescribeError
from lucid.project import Project, ProjectError

CLIPS = {
    "vo": {
        "clip_id": "vo",
        "source": "/tmp/vo.wav",
        "duration": 4.0,
        "has_video": False,
        "has_audio": True,
    },
    "clipa": {
        "clip_id": "clipa",
        "duration": 25.0,
        "has_video": True,
        "has_audio": True,
    },
}


@pytest.fixture
def project(tmp_path: Path) -> Project:
    """One audio-only VO clip and one 25s video clip whose media exists."""
    project = Project.create(tmp_path / "proj")

    clip_a_media = tmp_path / "clipa.mp4"
    clip_a_media.write_bytes(b"not really a video, just needs to exist")

    manifest = project.read_manifest()
    manifest["clips"] = [CLIPS["vo"], {**CLIPS["clipa"], "source": str(clip_a_media)}]
    project.write_manifest(manifest)
    return project


def _stub(texts: list[str | Exception]) -> Any:
    """Stand in for the worker, returning one canned result per window."""

    def describe_windows(windows: list[dict[str, Any]], **_: Any) -> list[dict[str, Any]]:
        assert len(windows) == len(texts), f"expected {len(texts)} windows, got {len(windows)}"
        out = []
        for window, text in zip(windows, texts, strict=True):
            if isinstance(text, Exception):
                out.append({"index": window["index"], "error": f"RuntimeError: {text}"})
            else:
                out.append({"index": window["index"], "text": text})
        return out

    return describe_windows


# -- windowing ---------------------------------------------------------------


def test_windows_are_equal_rather_than_a_tail_remainder() -> None:
    """The remainder is the whole problem: a 0.4s tail window samples three
    frames from one instant and gets described as ten seconds of footage."""
    windows = dsc.plan_windows(30.4, window=10.0)

    lengths = [end - start for start, end in windows]
    assert all(length == pytest.approx(lengths[0]) for length in lengths)
    assert windows[0][0] == 0.0
    assert windows[-1][1] == pytest.approx(30.4)
    # Contiguous: every second of footage is inside exactly one window.
    for (_, end), (start, _) in pairwise(windows):
        assert end == start


def test_a_window_is_never_longer_than_the_one_asked_for() -> None:
    """Widening is the one direction that fails — a whole-clip pass is just a
    window widened far enough, and it describes six frames as six people. So
    the count rounds up: 14s at 10s windows is two 7s windows, not one 14s.
    """
    assert dsc.plan_windows(14.0, window=10.0) == [(0.0, 7.0), (7.0, 14.0)]
    for duration in (4.0, 14.0, 25.0, 30.4, 730.0):
        windows = dsc.plan_windows(duration, window=10.0)
        assert all(end - start <= 10.0 + 1e-9 for start, end in windows)


def test_a_clip_shorter_than_a_window_is_one_window() -> None:
    assert dsc.plan_windows(4.0, window=10.0) == [(0.0, 4.0)]


def test_windowing_refuses_nonsense_rather_than_returning_an_empty_list() -> None:
    with pytest.raises(DescribeError, match="cannot describe"):
        dsc.plan_windows(0.0)
    with pytest.raises(DescribeError, match="window must be positive"):
        dsc.plan_windows(30.0, window=0.0)


def test_frames_are_sampled_off_the_window_edges() -> None:
    """A window boundary is where a cut is most likely to be, and a frame
    landing on one is as likely to catch the next shot as this one."""
    times = dsc.frame_times(10.0, 20.0, count=3)

    assert times == pytest.approx([11.667, 15.0, 18.333], abs=1e-3)
    assert all(10.0 < t < 20.0 for t in times)


def test_truncation_is_detected_rather_than_assumed_away() -> None:
    """A description that stops mid-fact reads exactly like a complete one."""
    assert dsc.truncated("A kitchen with white cabinets and a knife on the") is True
    assert dsc.truncated("A kitchen with white cabinets.") is False
    assert dsc.truncated('She says "get out of the house."') is False
    assert dsc.truncated("") is False


# -- the op ------------------------------------------------------------------


def test_plan_resolves_the_work_list_without_describing(
    project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The only way to ask what a run costs without paying for it."""

    def never(*_: Any, **__: Any) -> Any:  # pragma: no cover - must not run
        raise AssertionError("plan=True loaded the model")

    monkeypatch.setattr(dsc, "describe_windows", never)

    report = ops.describe(project.root, plan=True)

    assert report["plan"] is True
    assert report["clips"] == [{"clip_id": "clipa", "windows": 3}]
    assert report["windows"] == 3
    # 3.5s a window plus the load the run pays once.
    assert report["estimated_seconds"] == 26
    assert "runtime" in report
    assert project.read_manifest()["descriptions"] == []


def test_descriptions_are_stored_in_source_seconds(
    project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(dsc, "describe_windows", _stub(["A kitchen.", "A hallway.", "A car."]))

    report = ops.describe(project.root)

    assert report["described"] == 3
    assert report["errors"] == []
    assert report["truncated"] == []

    stored = project.read_manifest()["descriptions"]
    assert [d["text"] for d in stored] == ["A kitchen.", "A hallway.", "A car."]
    assert [d["clip_id"] for d in stored] == ["clipa"] * 3
    assert [d["src_start"] for d in stored] == [0.0, pytest.approx(8.333), pytest.approx(16.667)]
    assert stored[-1]["src_end"] == 25.0
    assert stored[0]["origin"] == "qwen2.5-vl:10s/3f"
    assert stored[0]["truncated"] is False


def test_an_audio_only_clip_is_refused_by_name(project: Project) -> None:
    """Skipping it quietly reads the same as describing it and finding
    nothing — and the Scream project's VO is exactly this clip."""
    with pytest.raises(ProjectError, match="no video track"):
        ops.describe(project.root, "vo")


def test_a_whole_project_pass_leaves_audio_only_clips_alone(
    project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(dsc, "describe_windows", _stub(["A kitchen.", "A hallway.", "A car."]))

    report = ops.describe(project.root)

    assert [c["clip_id"] for c in report["clips"]] == ["clipa"]


def test_an_already_described_clip_is_skipped(
    project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(dsc, "describe_windows", _stub(["one.", "two.", "three."]))
    ops.describe(project.root)

    def never(*_: Any, **__: Any) -> Any:  # pragma: no cover - must not run
        raise AssertionError("a described clip was described again without force")

    monkeypatch.setattr(dsc, "describe_windows", never)
    report = ops.describe(project.root)

    assert report["windows"] == 0
    assert report["described"] == 0
    assert report["skipped"] == [
        {
            "clip_id": "clipa",
            "why": "already described — pass force to describe it again",
            "windows": 3,
        }
    ]


def test_force_replaces_rather_than_appends(
    project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Appending would leave two descriptions of the same second of footage,
    and nothing downstream could say which one was current."""
    monkeypatch.setattr(dsc, "describe_windows", _stub(["one.", "two.", "three."]))
    ops.describe(project.root)

    monkeypatch.setattr(dsc, "describe_windows", _stub(["ONE.", "TWO.", "THREE."]))
    ops.describe(project.root, force=True)

    stored = project.read_manifest()["descriptions"]
    assert [d["text"] for d in stored] == ["ONE.", "TWO.", "THREE."]


def test_a_narrower_window_makes_more_of_them(
    project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(dsc, "describe_windows", _stub(["a."] * 5))

    report = ops.describe(project.root, window=5.0)

    assert report["windows"] == 5
    assert project.read_manifest()["descriptions"][0]["origin"] == "qwen2.5-vl:5s/3f"


def test_one_failed_window_does_not_throw_the_others_away(
    project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unseekable moment in a 130-window run is not a reason to lose 129
    good descriptions — but it is not silently dropped either."""
    monkeypatch.setattr(
        dsc, "describe_windows", _stub(["A kitchen.", RuntimeError("frame at 12.5s failed"), "A car."])
    )

    report = ops.describe(project.root)

    assert report["described"] == 2
    assert len(report["errors"]) == 1
    assert report["errors"][0]["clip_id"] == "clipa"
    assert "frame at 12.5s failed" in report["errors"][0]["error"]
    assert len(project.read_manifest()["descriptions"]) == 2


def test_a_truncated_description_is_stored_and_reported(
    project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Stored, because a description that stops mid-fact still indexes what
    it did say. Reported, because it reads as complete to whoever searches."""
    monkeypatch.setattr(
        dsc, "describe_windows", _stub(["A kitchen.", "A hallway with a", "A car."])
    )

    report = ops.describe(project.root)

    assert report["described"] == 3
    assert len(report["truncated"]) == 1
    assert report["truncated"][0]["src_start"] == pytest.approx(8.333)

    stored = project.read_manifest()["descriptions"]
    assert [d["truncated"] for d in stored] == [False, True, False]


# -- reading them back -------------------------------------------------------
#
# `describe_ls` is not a listing beside the search — it *is* the search, so
# what these check is that the filter cannot quietly mislead: an empty result
# still says what it filtered out of, and the terms it split into come back.


def test_describe_ls_returns_the_table_in_source_order(
    project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(dsc, "describe_windows", _stub(["A kitchen.", "A hallway.", "A car."]))
    ops.describe(project.root)

    listed = ops.describe_ls(project.root)

    assert listed["count"] == 3
    assert listed["total"] == 3
    assert [d["text"] for d in listed["descriptions"]] == ["A kitchen.", "A hallway.", "A car."]
    assert [d["src_start"] for d in listed["descriptions"]] == sorted(
        d["src_start"] for d in listed["descriptions"]
    )
    assert listed["words"] == 6


def test_describe_ls_counts_every_video_clip_including_undescribed_ones(
    project: Project,
) -> None:
    """A zero has to read as "not described yet" rather than "no such clip" —
    otherwise the only way to tell them apart is to go and describe it."""
    listed = ops.describe_ls(project.root)

    assert listed["clips"] == [
        {
            "clip_id": "clipa",
            "windows": 0,
            "described_seconds": 0,
            "duration": 25.0,
            "truncated": 0,
        }
    ]
    assert listed["descriptions"] == []
    assert listed["total"] == 0


def test_describe_ls_summary_reports_coverage_and_truncation(
    project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Truncated entries read exactly like complete ones to whoever searches,
    so the count rides along rather than waiting to be noticed."""
    monkeypatch.setattr(
        dsc, "describe_windows", _stub(["A kitchen.", "A hallway with a", "A car."])
    )
    ops.describe(project.root)

    listed = ops.describe_ls(project.root)

    assert listed["clips"][0]["windows"] == 3
    assert listed["clips"][0]["described_seconds"] == pytest.approx(25.0)
    assert listed["clips"][0]["truncated"] == 1


def test_describe_ls_contains_requires_every_term_anywhere(
    project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Not a phrase match: "kitchen knife" has to find "a knife on the kitchen
    counter", which is how anyone actually types a search for b-roll."""
    monkeypatch.setattr(
        dsc,
        "describe_windows",
        _stub(
            [
                "A knife on the kitchen counter.",
                "A kitchen with white cabinets.",
                "A car in a driveway.",
            ]
        ),
    )
    ops.describe(project.root)

    listed = ops.describe_ls(project.root, contains="Kitchen KNIFE")

    assert listed["count"] == 1
    assert listed["descriptions"][0]["text"] == "A knife on the kitchen counter."
    # What it filtered out of, and what it split into — an empty or narrow
    # result otherwise reads as a project with nothing in it.
    assert listed["total"] == 3
    assert listed["filter"] == {
        "clip_id": None,
        "contains": "Kitchen KNIFE",
        "terms": ["Kitchen", "KNIFE"],
    }


def test_describe_ls_narrows_to_one_clip(
    project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(dsc, "describe_windows", _stub(["A kitchen.", "A hallway.", "A car."]))
    ops.describe(project.root)

    assert ops.describe_ls(project.root, "clipa")["count"] == 3
    empty = ops.describe_ls(project.root, "vo")
    assert empty["count"] == 0
    assert empty["total"] == 3


# -- the property the design rests on ----------------------------------------


def test_cutting_the_edit_cannot_invalidate_a_description(
    project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Descriptions are in *source* seconds, and the b-roll asset is not the
    thing being cut — so there is deliberately no re-describe hook anywhere,
    and this is what says so. If a cut ever starts rewriting these, the
    design has quietly changed and this fails.
    """
    monkeypatch.setattr(dsc, "describe_windows", _stub(["A kitchen.", "A hallway.", "A car."]))
    ops.describe(project.root)
    before = project.read_manifest()["descriptions"]

    tx.save(
        tx.Transcript(
            clip_id="vo",
            words=(
                tx.Word(index=0, text="cold", start=0.0, end=0.3),
                tx.Word(index=1, text="open", start=0.5, end=0.8),
                tx.Word(index=2, text="here", start=1.2, end=1.5),
                tx.Word(index=3, text="after", start=2.2, end=2.5),
            ),
        ),
        project.transcript_path("vo"),
    )
    edit = tl.Edit([tl.Segment("vo", 0.0, 4.0)])
    clips_by_id = {c["clip_id"]: c for c in project.read_manifest()["clips"]}
    tl.write(tl.to_otio(edit, clips_by_id, rate=1000.0, name="proj"), project.timeline_path)

    ops.cut_by_transcript(project.root, "vo", cut=[[1, 2]])

    assert project.read_manifest()["descriptions"] == before
