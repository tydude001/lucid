"""The framing control — the fifteen hand numbers, in proofcut's address space.

PLAN.md § Per-shot framing, step 5: *"then, and only then, the detector —
judged on whether it beats the 15 hand numbers, which is the control that
already exists and was watched and approved"*, and § Three uncosted parity
items' standing rule that the dumb control gets **built as a test** rather
than remembered. This is that test: the control, the metric, and — written
afterwards and scored on both — the detector. The order is the point. The bar
existed before the thing being judged against it did, so it could not have been
set to fit.

**Provenance.** The control is `~/proofcut-work/projects/final-cut/render.py`'s `CROP` table —
one 9:16 window per shot of the 44s teaser that was framed by hand, watched
and approved (HISTORY.md § The hand-framed teaser, watched). That table is
addressed in *timeline* seconds against a scratch render, which is the one
thing per-shot framing exists to stop being true: a single upstream cut
invalidates every number in it. Here it is re-addressed as
`(clip_id, src_start, rect)` in **source** seconds, which no cut can reach.

**How the two address spaces were joined**, because it was measured and not
reasoned: a 2fps grayscale fingerprint of the approved render against the
film's own render put 81 of 88 frames at +96.0s on a 0.5s grid; two of the
hand shot boundaries then fall on the film's own placement boundaries at
95.930 and 95.929, which pins the offset to a third of a frame. Each ported
window was then checked by pixel readback — the source frame cropped at the
ported window against the approved render's own frame, scored also against a
deliberately wrong x so the number is an answer rather than a number. All
sixteen reproduce.

**The detector is now scored against it**, at the bottom of this file, which is
the point of having written the control down first: `faces.window_centre` and
`faces.window_x` are the shipped placement rule and they are measured on
`data/framing_detections.json` — the detector's own raw boxes over these
sixteen windows, sampled exactly as `ops.reframe_detect` samples them. The
fixture is checked in so the gate runs without insightface, an ONNX session or
the footage; regenerating it needs all three (`~/proofcut-work/projects/framing-detect/`).

**Sixteen, for fifteen shots.** Shot 9 is the one hand-eased move, and
proofcut's series is discrete by design (a window steps at a camera cut, it does
not slide), so the ramp is carried as one step at its own midpoint. That is
the one place the control is an approximation of what was approved, and it is
named here rather than smoothed over.
"""

from __future__ import annotations

import json
import statistics
from pathlib import Path
from typing import Any

import pytest

from proofcut import describe as dsc
from proofcut import faces, ops
from proofcut import timeline as tl
from proofcut.project import Project

# The source geometry the control is written against. Heights differ per clip,
# and the full-height 9:16 window differs with them — the hand table was a set
# of scalars because it cropped one flattened 816-tall render, and a stored
# rect is not constrained that way.
SOURCES = {
    "s1996-billy-stu": (1920, 816),
    "s1996-randy": (1920, 816),
    "s4-reveal": (1920, 800),
}

# (clip_id, src_start, x) — the approved framing, source-addressed. `w`/`h` are
# the clip's own full-height 9:16 window, derived rather than repeated.
CONTROL = [
    ("s1996-billy-stu", 0.5012, 220),
    ("s1996-billy-stu", 5.5889, 1100),
    ("s1996-billy-stu", 11.2195, 700),
    ("s1996-billy-stu", 17.6009, 600),
    ("s1996-randy", 0.0, 830),
    ("s1996-randy", 0.8342, 560),
    ("s1996-randy", 1.9603, 740),
    ("s1996-randy", 6.6733, 480),
    ("s4-reveal", 3.6703, 600),
    ("s4-reveal", 6.0477, 520),
    ("s4-reveal", 7.3428, 930),      # shot 9, the eased move, as one step
    ("s4-reveal", 8.8005, 310),
    ("s4-reveal", 11.0527, 780),
    ("s4-reveal", 12.6793, 300),
    ("s4-reveal", 15.3904, 820),
    ("s4-reveal", 18.727, 650),
]

CANVAS = (1080, 1920)


def window_width(clip_id: str) -> int:
    """The full-height window of the canvas's shape, in this clip's pixels."""
    _w, h = SOURCES[clip_id]
    return round(h * CANVAS[0] / CANVAS[1])


def centre_x(clip_id: str) -> int:
    """The dumb default — what proofcut crops to with nothing stored."""
    w, _h = SOURCES[clip_id]
    return (w - window_width(clip_id)) // 2


def overlap(clip_id: str, a: int, b: int) -> float:
    """Fraction of the control window a candidate window covers.

    Horizontal only, deliberately: every window here is full-height, so the
    one axis a framing decision moves on is the one that gets scored.
    """
    width = window_width(clip_id)
    return max(0.0, width - abs(a - b)) / width


def score(candidate: dict[tuple[str, float], int]) -> dict[str, float]:
    """Score a framing against the control. Lower `displacement` is better,
    higher `overlap` is better, and `lost` counts windows sharing no pixel
    with the approved one — the failure a watch does not show, because a
    mis-framed shot reads as a shot the editor chose."""
    overlaps, displacements, lost = [], [], 0
    for clip_id, src_start, x in CONTROL:
        got = candidate[(clip_id, src_start)]
        cover = overlap(clip_id, got, x)
        overlaps.append(cover)
        displacements.append(abs(got - x))
        lost += cover == 0.0
    return {
        "overlap": sum(overlaps) / len(overlaps),
        "displacement": sum(displacements) / len(displacements),
        "lost": lost,
        "worst": min(overlaps),
    }


CENTRE = {(c, s): centre_x(c) for c, s, _x in CONTROL}
APPROVED = {(c, s): x for c, s, x in CONTROL}


def test_the_control_is_well_formed() -> None:
    """One window per `(clip_id, src_start)`, in source order, inside the source."""
    keys = [(c, s) for c, s, _x in CONTROL]
    assert len(set(keys)) == len(keys), "one entry per (clip_id, src_start)"
    for clip_id in SOURCES:
        starts = [s for c, s, _x in CONTROL if c == clip_id]
        assert starts == sorted(starts), f"{clip_id} windows are in source order"
    for clip_id, _src, x in CONTROL:
        width, _h = SOURCES[clip_id]
        assert 0 <= x <= width - window_width(clip_id), f"{clip_id} x={x} is inside its source"


def test_the_metric_scores_the_control_perfectly_against_itself() -> None:
    """A metric that cannot recognise the control is not a metric."""
    assert score(APPROVED) == {"overlap": 1.0, "displacement": 0.0, "lost": 0, "worst": 1.0}


def test_the_centre_crop_is_the_bar_a_detector_has_to_beat() -> None:
    """What the default costs against the approved framing, as a number.

    This is the whole point of writing the control down: the centre crop was
    refused on a watch (HISTORY.md § `tiktok-reels`), and until now that
    refusal had no number attached to it that anything could be compared to.
    """
    got = score(CENTRE)
    assert got["overlap"] == pytest.approx(0.568, abs=0.01)
    assert got["displacement"] == pytest.approx(199.4, abs=1.0)
    # At least one approved window and the centre crop share no pixel at all.
    assert got["lost"] >= 1
    assert got["worst"] == 0.0


def test_the_metric_discriminates() -> None:
    """It has to separate a wrong framing from a nearly-right one, or a
    detector could beat the centre crop by accident."""
    near = {k: v + 20 for k, v in APPROVED.items()}
    assert score(near)["overlap"] > score(CENTRE)["overlap"]
    assert score(near)["displacement"] < score(CENTRE)["displacement"]


@pytest.fixture
def project(tmp_path: Path) -> Project:
    """The control's three clips, at their real geometry, on a vertical canvas."""
    project = Project.create(tmp_path / "proj")
    manifest = project.read_manifest()
    clips = []
    for clip_id, (width, height) in SOURCES.items():
        clips.append({
            "clip_id": clip_id,
            "source": f"/tmp/{clip_id}.mp4",
            "duration": 30.0,
            "has_video": True,
            "has_audio": True,
            "width": width,
            "height": height,
        })
    manifest["clips"] = clips
    manifest["canvas"] = f"{CANVAS[0]}x{CANVAS[1]}"
    project.write_manifest(manifest)
    edit = tl.Edit([tl.Segment(clips[0]["clip_id"], 0.0, 30.0)])
    tl.write(
        tl.to_otio(edit, {c["clip_id"]: c for c in clips}, rate=1000.0),
        project.timeline_path,
    )
    return project


def test_the_control_stores_and_reads_back_unchanged(project: Project) -> None:
    """The port is a change of address, not of geometry — so every number
    survives the round trip through the store."""
    for clip_id, src_start, x in CONTROL:
        _w, h = SOURCES[clip_id]
        ops.reframe(
            project.root,
            clip_id,
            rect=f"{x},0,{window_width(clip_id)},{h}",
            src_start=src_start,
        )
    read = ops.reframe(project.root)
    got = {}
    for entry in read["clips"]:
        for window in entry["windows"]:
            if window["origin"] == "override":
                got[(entry["clip_id"], window["src_start"])] = int(window["crop"].split(",")[0])
    assert got == APPROVED
    assert score(got)["overlap"] == 1.0


def test_a_control_window_at_the_head_stays_a_bare_entry(project: Project) -> None:
    """`s1996-randy`'s first window is at source 0.0, which is what every rect
    on disk already meant — so it writes without an `src_start` key and an
    unwindowed manifest is untouched by the port."""
    ops.reframe(project.root, "s1996-randy", rect="830,0,459,816", src_start=0.0)
    records = [
        r for r in project.read_manifest()["reframe"] if r["clip_id"] == "s1996-randy"
    ]
    assert records == [{"clip_id": "s1996-randy", "rect": [830, 0, 459, 816]}]


# -- the detector, scored against the control -----------------------------
#
# PLAN.md § The auto-framing detector, item 4: *"the detector must beat
# 0.568/199.4 on the control and must never return `lost > 0`."* Everything
# below is that gate. It scores `proofcut.faces`' own two functions rather than a
# re-derivation of them, because a test that re-implements the rule it is
# checking passes whatever the shipped code does.

DETECTIONS = Path(__file__).parent / "data" / "framing_detections.json"


def _fixture() -> dict[tuple[str, float], dict[str, Any]]:
    """The detector's raw boxes over the sixteen control windows, by address."""
    windows = json.loads(DETECTIONS.read_text(encoding="utf-8"))
    return {(w["clip"], w["src_start"]): w for w in windows}


def _place(centre: float | None, clip_id: str) -> int | None:
    """One centre through the shipped placement rule, or None for a refusal."""
    if centre is None:
        return None
    return faces.window_x(centre, SOURCES[clip_id][0], window_width(clip_id))


def _detector() -> tuple[dict[tuple[str, float], int], list[tuple[str, float]]]:
    """What the pass proposes per control window, and which ones it refuses.

    A refusal is scored **as the centre crop**, because that is what the film
    actually gets there: the pass declines to frame the window and the default
    stands. Scoring it as a miss would flatter the rule and scoring it as a hit
    would invent one; scoring it as what ships is the only honest accounting.
    """
    fixture = _fixture()
    candidate, refused = {}, []
    for clip_id, src_start, _x in CONTROL:
        window = fixture[(clip_id, src_start)]
        proposed = _place(faces.window_centre(window["frames"]), clip_id)
        if proposed is None:
            refused.append((clip_id, src_start))
            proposed = centre_x(clip_id)
        candidate[(clip_id, src_start)] = proposed
    return candidate, refused


def test_the_fixture_is_the_sampling_the_pass_actually_uses() -> None:
    """Three frames per window, at `describe.frame_times`' offsets.

    A gate measured at a denser sampling than the code takes is a gate on
    something that does not ship. The earlier probe sampled up to sixteen
    frames a window; this pins the fixture to `ops.DETECT_FRAMES` and to the
    same timestamps `reframe_detect` asks for.
    """
    fixture = _fixture()
    assert set(fixture) == {(c, s) for c, s, _x in CONTROL}
    for (clip_id, src_start), window in fixture.items():
        assert window["source"] == list(SOURCES[clip_id])
        assert len(window["frames"]) == ops.DETECT_FRAMES
        want = dsc.frame_times(src_start, window["src_end"], ops.DETECT_FRAMES)
        assert [f["ts"] for f in window["frames"]] == [round(t, 4) for t in want]


def test_the_detector_beats_the_centre_crop_on_every_column() -> None:
    """The gate. Better on the mean, better on the displacement, and — the
    column a watch would notice — it never leaves an approved subject entirely
    outside the frame, which the centre crop does on one shot of fifteen."""
    got = score(_detector()[0])
    bar = score(CENTRE)

    assert got["overlap"] > bar["overlap"]
    assert got["displacement"] < bar["displacement"]
    assert got["lost"] == 0 < bar["lost"]
    assert got["worst"] > bar["worst"]

    # Pinned, so a regression is a failure rather than a slightly worse pass
    # that still clears a bar set by the dumbest possible rule.
    assert got["overlap"] == pytest.approx(0.750, abs=0.01)
    assert got["displacement"] == pytest.approx(114.0, abs=2.0)


def test_the_luma_centroid_is_worse_than_not_asking() -> None:
    """The negative control, and the reason it is in the suite.

    A saliency-flavoured signal is what anyone reaches for first, and this one
    scores **below the centre crop it would replace** — CLAUDE.md's standing
    warning that a brightness bbox answers "where is the bright part", never
    "where is the frame", with a number on it. Measured on the same frames as
    the faces above, so the comparison is the signal and not the sampling.
    """
    fixture = _fixture()
    luma = {
        (clip_id, src_start): _place(
            statistics.median(f["luma_cx"] for f in fixture[(clip_id, src_start)]["frames"]),
            clip_id,
        )
        for clip_id, src_start, _x in CONTROL
    }
    got, bar = score(luma), score(CENTRE)
    assert got["overlap"] < bar["overlap"]
    assert got["displacement"] > bar["displacement"]
    # And it loses a subject too, so there is no column on which it is the
    # better answer. Nothing in proofcut picks a framing this way.
    assert got["lost"] >= bar["lost"]


def test_the_window_with_no_face_is_refused_and_not_quietly_centred() -> None:
    """One window in sixteen has no signal, and it must arrive as a refusal.

    `s1996-randy` 0.834 is a woman on a CRT playing inside the shot — the
    subject is a screen, RetinaFace sees nothing, and a fallback to the centre
    crop would be 170px wrong while reading in the output exactly like a
    framing decision. `window_centre` returns None so the caller has to say so.
    """
    _candidate, refused = _detector()
    assert refused == [("s1996-randy", 0.8342)]

    frames = _fixture()[("s1996-randy", 0.8342)]["frames"]
    assert all(f["faces"] == [] for f in frames)
    assert faces.window_centre(frames) is None


def test_the_placement_rule_clamps_into_the_source() -> None:
    """A face near the edge of frame cannot be centred, and the window stops at
    the edge rather than hanging off the source for `reframe` to refuse later."""
    width, source_width = window_width("s4-reveal"), SOURCES["s4-reveal"][0]
    assert faces.window_x(10.0, source_width, width) == 0
    assert faces.window_x(source_width - 10.0, source_width, width) == source_width - width
    assert faces.window_x(source_width / 2, source_width, width) == centre_x("s4-reveal")


def test_the_aggregation_rule_is_area_weighted() -> None:
    """The near face in a two-shot pulls harder than the far one.

    Not a tuning knob — largest, mean and area-weighted land within 0.006 of
    each other on the control — but it is the rule the numbers above were
    measured with, so it is pinned rather than left to drift.
    """
    near = {"box": [100.0, 0.0, 300.0, 200.0]}   # 200x200, centred on 200
    far = {"box": [1000.0, 0.0, 1050.0, 50.0]}   # 50x50, centred on 1025
    got = faces.frame_centre([near, far])
    assert got == pytest.approx(248.5, abs=0.5)
    # The unweighted mean of the two centres is 612.5, so the weighting is
    # doing the work rather than riding along: sixteen times the area pulls the
    # window sixteen times as hard, and the far figure barely moves it.
    assert got < statistics.fmean([200.0, 1025.0])
    assert faces.frame_centre([near]) == 200.0
    assert faces.frame_centre([]) is None
