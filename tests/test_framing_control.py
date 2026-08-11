"""The framing control — the fifteen hand numbers, in lucid's address space.

PLAN.md § Per-shot framing, step 5: *"then, and only then, the detector —
judged on whether it beats the 15 hand numbers, which is the control that
already exists and was watched and approved"*, and § Three uncosted parity
items' standing rule that the dumb control gets **built as a test** rather
than remembered. This is that test. It holds no detector, because there is
none; what it holds is the control and the metric, so that whatever is built
next is measured against a number that existed before it did.

**Provenance.** The control is `~/lucid-final-cut/render.py`'s `CROP` table —
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

**Sixteen, for fifteen shots.** Shot 9 is the one hand-eased move, and
lucid's series is discrete by design (a window steps at a camera cut, it does
not slide), so the ramp is carried as one step at its own midpoint. That is
the one place the control is an approximation of what was approved, and it is
named here rather than smoothed over.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from lucid import ops
from lucid import timeline as tl
from lucid.project import Project

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
    """The dumb default — what lucid crops to with nothing stored."""
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
