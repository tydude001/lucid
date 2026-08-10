"""`reframe` — which part of each clip survives into the frame.

Step 3 of the aspect swap, and the step that makes a swapped canvas fill the
frame instead of pillarboxing it. Two properties carry most of these tests:

- **A rect is geometry in source pixels, never a length**, so no cut can
  invalidate one — the same rule a footage description follows. Here that
  extends one step further: the rect is stored *as asked* and refit to
  whatever canvas is in force, so a canvas change cannot invalidate one
  either.
- **An override is a floor, not a frame.** A rect that is not the canvas's
  shape is *grown* to it rather than shrunk into it, because growing keeps
  everything asked for on screen and shrinking would cut the subject in half.

Built by hand rather than through `import_media`, following
`test_ops_canvas.py`: no ffprobe is needed to have a project with a shape.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from lucid import mlt, ops
from lucid import timeline as tl
from lucid.project import Project, ProjectError

WIDE = {
    "clip_id": "cold-open",
    "source": "/tmp/cold-open.mp4",
    "duration": 12.0,
    "has_video": True,
    "has_audio": True,
    "width": 1920,
    "height": 816,
}

VO = {
    "clip_id": "vo",
    "source": "/tmp/vo.wav",
    "duration": 12.0,
    "has_video": False,
    "has_audio": True,
}


@pytest.fixture
def project(tmp_path: Path) -> Project:
    project = Project.create(tmp_path / "proj")
    manifest = project.read_manifest()
    manifest["clips"] = [WIDE, VO]
    project.write_manifest(manifest)
    edit = tl.Edit([tl.Segment("cold-open", 0.0, 12.0)])
    tl.write(tl.to_otio(edit, {WIDE["clip_id"]: WIDE}, rate=1000.0), project.timeline_path)
    return project


def _clip(result: dict, clip_id: str) -> dict:
    return next(entry for entry in result["clips"] if entry["clip_id"] == clip_id)


# -- reading -------------------------------------------------------------


def test_no_arguments_reads_without_writing(project: Project) -> None:
    before = project.manifest_path.stat().st_mtime_ns
    result = ops.reframe(project.root)

    assert result["written"] is False
    assert project.manifest_path.stat().st_mtime_ns == before
    assert ops.REFRAME_KEY not in project.read_manifest()


def test_a_matching_aspect_keeps_everything_and_emits_nothing(project: Project) -> None:
    """No canvas override, so the canvas *is* the footage: the crop is the
    whole frame and no filter is written at all."""
    entry = _clip(ops.reframe(project.root), "cold-open")

    assert entry["crop"] == "0,0,1920,816"
    assert entry["reframes"] is False
    assert entry["kept"] == 1.0
    assert entry["origin"] == "centre"


def test_a_swapped_canvas_crops_and_says_what_it_costs(project: Project) -> None:
    """The measured centre crop: 459 of 1920 columns, so 76% of the footage
    goes rather than 76% of the frame going black."""
    ops.canvas(project.root, size="1080x1920")

    entry = _clip(ops.reframe(project.root), "cold-open")

    assert entry["crop"] == "730,0,459,816"
    assert entry["reframes"] is True
    assert entry["kept"] == 0.2391


def test_an_audio_clip_has_no_picture_to_crop(project: Project) -> None:
    assert [entry["clip_id"] for entry in ops.reframe(project.root)["clips"]] == ["cold-open"]


# -- setting an override -------------------------------------------------


def test_setting_stores_the_rect_as_asked(project: Project) -> None:
    """As asked, not as fitted — the record has to survive the canvas moving
    under it, and a fitted rect would silently bake in one canvas's shape."""
    ops.canvas(project.root, size="1080x1920")
    ops.reframe(project.root, "cold-open", rect="1200,0,459,816")

    assert project.read_manifest()[ops.REFRAME_KEY] == [
        {"clip_id": "cold-open", "rect": [1200, 0, 459, 816]}
    ]


def test_an_override_moves_the_crop_off_centre(project: Project) -> None:
    ops.canvas(project.root, size="1080x1920")
    result = ops.reframe(project.root, "cold-open", rect="1200,0,459,816")

    entry = _clip(result, "cold-open")
    assert entry["crop"] == "1200,0,459,816"
    assert entry["origin"] == "override"
    assert entry["asked"] == "1200,0,459,816"


def test_a_rect_of_the_wrong_shape_is_grown_rather_than_shrunk(project: Project) -> None:
    """The asymmetry the design turns on: growing pulls in surroundings,
    shrinking would cut the subject in half. So the ask is a floor, and both
    the ask and what it became are reported."""
    ops.canvas(project.root, size="1080x1920")
    result = ops.reframe(project.root, "cold-open", rect="800,300,300,200")

    entry = _clip(result, "cold-open")
    assert entry["asked"] == "800,300,300,200"
    assert entry["crop"] == "800,134,300,533"

    asked_x, asked_y, asked_w, asked_h = 800, 300, 300, 200
    crop_x, crop_y, crop_w, crop_h = (int(part) for part in entry["crop"].split(","))
    assert crop_x <= asked_x and crop_x + crop_w >= asked_x + asked_w
    assert crop_y <= asked_y and crop_y + crop_h >= asked_y + asked_h


def test_a_grown_rect_is_shifted_to_stay_inside_the_source(project: Project) -> None:
    """A rect that leaves the frame renders MLT's idea of what is past the
    edge, not the footage's."""
    ops.canvas(project.root, size="1080x1920")
    result = ops.reframe(project.root, "cold-open", rect="1850,700,60,100")

    crop_x, crop_y, crop_w, crop_h = (
        int(part) for part in _clip(result, "cold-open")["crop"].split(",")
    )
    assert crop_x >= 0 and crop_x + crop_w <= WIDE["width"]
    assert crop_y >= 0 and crop_y + crop_h <= WIDE["height"]


def test_plan_resolves_without_writing(project: Project) -> None:
    ops.canvas(project.root, size="1080x1920")
    planned = ops.reframe(project.root, "cold-open", rect="1200,0,459,816", plan=True)

    assert planned["written"] is False
    assert _clip(planned, "cold-open")["crop"] == "1200,0,459,816"
    assert ops.REFRAME_KEY not in project.read_manifest()


def test_reset_drops_one_clip_and_reset_alone_drops_every_one(project: Project) -> None:
    ops.canvas(project.root, size="1080x1920")
    ops.reframe(project.root, "cold-open", rect="1200,0,459,816")

    ops.reframe(project.root, "cold-open", reset=True)
    assert ops.REFRAME_KEY not in project.read_manifest()

    ops.reframe(project.root, "cold-open", rect="1200,0,459,816")
    ops.reframe(project.root, reset=True)
    assert ops.REFRAME_KEY not in project.read_manifest()


# -- what it refuses -----------------------------------------------------


@pytest.mark.parametrize(
    "rect, because",
    [
        ("1200,0,459", "X,Y,W,H"),
        ("a,b,c,d", "X,Y,W,H"),
        ("1200,0,0,816", "positive"),
        ("-10,0,459,816", "inside the source"),
        ("1800,0,459,816", "past the source"),
    ],
)
def test_refusals_name_the_value(project: Project, rect: str, because: str) -> None:
    ops.canvas(project.root, size="1080x1920")

    with pytest.raises(ProjectError, match=because):
        ops.reframe(project.root, "cold-open", rect=rect)

    assert ops.REFRAME_KEY not in project.read_manifest(), "a refusal never half-writes"


def test_a_rect_that_cannot_be_shown_whole_names_the_one_that_can(project: Project) -> None:
    """"Use the whole 16:9 frame" in a 9:16 render is a genuinely impossible
    ask — refused rather than quietly clipped, and the refusal teaches the
    rect that works."""
    ops.canvas(project.root, size="1080x1920")

    with pytest.raises(ProjectError, match="730,0,459,816"):
        ops.reframe(project.root, "cold-open", rect="0,0,1920,816")


def test_a_rect_without_a_clip_is_refused(project: Project) -> None:
    with pytest.raises(ProjectError, match="needs a clip_id"):
        ops.reframe(project.root, rect="1200,0,459,816")


def test_a_rect_and_reset_together_are_refused(project: Project) -> None:
    with pytest.raises(ProjectError, match="not both"):
        ops.reframe(project.root, "cold-open", rect="1200,0,459,816", reset=True)


def test_an_audio_clip_cannot_be_reframed(project: Project) -> None:
    with pytest.raises(ProjectError, match="no picture to crop"):
        ops.reframe(project.root, "vo", rect="0,0,10,10")


def test_an_unknown_clip_is_refused(project: Project) -> None:
    with pytest.raises(ProjectError, match="no clip"):
        ops.reframe(project.root, "nope", rect="0,0,10,10")


# -- the canvas moving under a stored rect -------------------------------


def test_a_stored_rect_is_refit_when_the_canvas_moves(project: Project) -> None:
    """The reason the ask is stored rather than the fit: the same record has
    to mean something at both shapes."""
    ops.canvas(project.root, size="1080x1920")
    ops.reframe(project.root, "cold-open", rect="800,300,300,200")
    vertical = _clip(ops.reframe(project.root), "cold-open")["crop"]

    ops.canvas(project.root, size="1920x1080")
    square_ish = _clip(ops.reframe(project.root), "cold-open")["crop"]

    assert vertical == "800,134,300,533"
    assert square_ish == "772,300,356,200"
    assert project.read_manifest()[ops.REFRAME_KEY][0]["rect"] == [800, 300, 300, 200]


def test_a_canvas_change_reports_a_rect_it_has_outgrown_rather_than_raising(
    project: Project,
) -> None:
    """Raising here would leave the project half-swapped — the manifest is
    already written by the time the report is built. So `canvas` names the
    clip to fix, and `export` is where it is refused."""
    ops.canvas(project.root, size="1080x1920")
    ops.reframe(project.root, "cold-open", rect="900,0,100,800")

    result = ops.canvas(project.root, size="1920x408")

    assert result["written"] is True
    assert [c["clip_id"] for c in result["reframe_conflicts"]] == ["cold-open"]
    assert "cannot be shown whole" in result["reframe_conflicts"][0]["why"]


def test_reading_the_table_still_works_with_a_rect_the_canvas_outgrew(
    project: Project,
) -> None:
    """Otherwise finding out which clip to reset would be impossible."""
    ops.canvas(project.root, size="1080x1920")
    ops.reframe(project.root, "cold-open", rect="900,0,100,800")
    ops.canvas(project.root, size="1920x408")

    entry = _clip(ops.reframe(project.root), "cold-open")

    assert entry["crop"] is None
    assert "cannot be shown whole" in entry["error"]

    ops.reframe(project.root, "cold-open", reset=True)
    assert _clip(ops.reframe(project.root), "cold-open")["error"] is None


# -- what `canvas` now says ----------------------------------------------


def test_canvas_reports_the_clips_a_swap_crops(project: Project) -> None:
    assert ops.canvas(project.root)["cropped"] == []

    result = ops.canvas(project.root, size="1080x1920")

    assert result["fills_frame"] is True
    assert result["cropped"] == ["cold-open"]


def test_plan_costs_the_canvas_being_planned_not_the_one_in_force(project: Project) -> None:
    """The whole point of planning is to see what the new shape costs."""
    planned = ops.canvas(project.root, size="1080x1920", plan=True)

    assert planned["cropped"] == ["cold-open"]
    assert ops.canvas(project.root)["cropped"] == [], "the project never took it"


# -- reaching the document -----------------------------------------------


def test_the_built_document_carries_the_crop(project: Project) -> None:
    """The end of the chain: a rect in the manifest becomes a `qtblend` filter
    on the timeline producer, keyed by resource rather than by clip_id."""
    ops.canvas(project.root, size="1080x1920")
    built = ops._build_mlt(project, ops._load_edit(project), fps=30.0)

    assert built["reframed"] == ["cold-open"]
    assert set(mlt.reframed_nodes(built["document"]).values()) == {"-1718 0 4518 1920 1"}


def test_an_unswapped_project_reaches_the_document_with_no_filter(project: Project) -> None:
    built = ops._build_mlt(project, ops._load_edit(project), fps=30.0)

    assert built["reframed"] == []
    assert mlt.reframed_nodes(built["document"]) == {}


# -- reaching the viewer -------------------------------------------------
#
# Step 4. The document half above is what melt renders; this is what the
# window draws, and the two have to be the same rectangle or the preview
# shows footage the export drops (PLAN.md § Aspect swap, step 4).


def test_the_view_carries_the_canvas_the_profile_declares(project: Project) -> None:
    assert ops.timeline_view(project.root)["canvas"] == [1920, 816]

    ops.canvas(project.root, size="1080x1920")

    assert ops.timeline_view(project.root)["canvas"] == [1080, 1920]


def test_the_view_hands_the_writers_own_destination_rect_to_the_page(
    project: Project,
) -> None:
    """The same numbers the `qtblend` filter carries, so the preview places
    media by reading the render's answer rather than re-deriving a crop."""
    ops.canvas(project.root, size="1080x1920")
    built = ops._build_mlt(project, ops._load_edit(project), fps=30.0)

    entry = ops.timeline_view(project.root)["reframe"]["cold-open"]

    assert entry["crop"] == [730, 0, 459, 816]
    assert entry["crops"] is True
    assert " ".join(str(n) for n in entry["dest"]) + " 1" in set(
        mlt.reframed_nodes(built["document"]).values()
    )


def test_an_unswapped_clip_is_still_placed_and_it_is_the_contain(
    project: Project,
) -> None:
    """One code path draws both. A clip the render does not crop still gets a
    `dest`, and it is `fit_rect` — what MLT does when no filter is emitted —
    so the page never has to choose between two ways of placing an element."""
    entry = ops.timeline_view(project.root)["reframe"]["cold-open"]

    assert entry["crops"] is False
    assert entry["dest"] == list(mlt.fit_rect((1920, 816), (1920, 816)))


def test_a_clip_with_no_picture_is_not_placed_at_all(project: Project) -> None:
    """There is nothing to crop, and an entry would invite the page to place
    an element that has no frame to put anywhere."""
    assert "vo" not in ops.timeline_view(project.root)["reframe"]


def test_a_rect_the_canvas_outgrew_is_reported_rather_than_raised(
    project: Project,
) -> None:
    """`shots_error`'s policy, for the same reason: the view is how a person
    finds the rect to fix, so it must not be what the stale rect takes down."""
    ops.canvas(project.root, size="1080x1920")
    ops.reframe(project.root, "cold-open", rect="900,0,100,800")
    ops.canvas(project.root, size="1920x408")

    view = ops.timeline_view(project.root)

    assert view["reframe"] == {}
    assert "cannot be shown whole" in view["reframe_error"]
    assert view["segments"], "the rest of the view still answers"
