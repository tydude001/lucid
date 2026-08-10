"""`canvas` — the shape a project renders at, as project state.

The canvas is one field feeding two derivations that used to walk `clips`
independently (`_mlt_resolution` for the MLT profile, `_caption_canvas` for
the reference the caption sizes are quoted against). Most of these tests exist
to pin down that the two cannot drift apart again, and the rest to pin down
the routing consequence: an overridden project has to reach the writer that
can declare the canvas, because auto-editor would take the export and ignore
it. PLAN.md § Aspect swap.

Built by hand rather than through `import_media`, following
`test_ops_caption_style.py`: no ffprobe is needed to have a project with a
shape.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from lucid import ops
from lucid import timeline as tl
from lucid.project import Project, ProjectError

CLIP = {
    "clip_id": "cold-open",
    "source": "/tmp/cold-open.mp4",
    "duration": 12.0,
    "has_video": True,
    "has_audio": True,
    "width": 1920,
    "height": 816,
}


@pytest.fixture
def project(tmp_path: Path) -> Project:
    project = Project.create(tmp_path / "proj")
    manifest = project.read_manifest()
    manifest["clips"] = [CLIP]
    project.write_manifest(manifest)
    edit = tl.Edit([tl.Segment("cold-open", 0.0, 12.0)])
    tl.write(tl.to_otio(edit, {CLIP["clip_id"]: CLIP}, rate=1000.0), project.timeline_path)
    return project


# -- reading and writing -------------------------------------------------


def test_no_arguments_reads_without_writing(project: Project) -> None:
    """Also how a caller learns what it would be overriding, so not a mutation."""
    before = project.manifest_path.stat().st_mtime_ns
    result = ops.canvas(project.root)

    assert result["written"] is False
    assert result["canvas"] == "1920x816"
    assert result["source"] == "footage"
    assert project.manifest_path.stat().st_mtime_ns == before
    assert ops.CANVAS_KEY not in project.read_manifest()


def test_setting_stores_the_override(project: Project) -> None:
    result = ops.canvas(project.root, size="1080x1920")

    assert result["written"] is True
    assert result["source"] == "override"
    assert result["aspect"] == "9:16"
    assert project.read_manifest()[ops.CANVAS_KEY] == "1080x1920"


def test_the_stored_form_is_normalised(project: Project) -> None:
    """What comes back out has to be parseable by the same rule that went in."""
    ops.canvas(project.root, size=" 1080X1920 ")

    assert project.read_manifest()[ops.CANVAS_KEY] == "1080x1920"
    assert ops.canvas(project.root)["canvas"] == "1080x1920"


def test_reset_drops_the_key_rather_than_storing_the_footage(project: Project) -> None:
    """Storing the derived value would freeze it — replacing the footage later
    would then leave the project rendering at the old clip's shape."""
    ops.canvas(project.root, size="1080x1920")
    result = ops.canvas(project.root, reset=True)

    assert result["source"] == "footage"
    assert result["canvas"] == "1920x816"
    assert ops.CANVAS_KEY not in project.read_manifest()


def test_plan_resolves_without_writing(project: Project) -> None:
    planned = ops.canvas(project.root, size="1080x1920", plan=True)

    assert planned["canvas"] == "1080x1920"
    assert planned["written"] is False
    assert ops.CANVAS_KEY not in project.read_manifest()
    assert ops.canvas(project.root)["canvas"] == "1920x816", "the project never took it"


def test_a_project_with_no_footage_reports_the_default(tmp_path: Path) -> None:
    project = Project.create(tmp_path / "empty")

    result = ops.canvas(project.root)

    assert result["source"] == "default"
    assert result["canvas"] == "1920x1080"


# -- what it refuses -----------------------------------------------------


@pytest.mark.parametrize(
    "size, because",
    [
        ("1080", "WIDTHxHEIGHT"),
        ("wide", "WIDTHxHEIGHT"),
        ("1080x", "WIDTHxHEIGHT"),
        ("-1080x1920", "WIDTHxHEIGHT"),
        ("1081x1920", "even"),
        ("1080x1921", "even"),
    ],
)
def test_refusals_name_the_value(project: Project, size: str, because: str) -> None:
    with pytest.raises(ProjectError, match=because):
        ops.canvas(project.root, size=size)

    assert ops.CANVAS_KEY not in project.read_manifest(), "a refusal never half-writes"


def test_size_and_reset_together_are_refused(project: Project) -> None:
    """Ambiguous rather than harmless: one of them has to lose silently."""
    with pytest.raises(ProjectError, match="not both"):
        ops.canvas(project.root, size="1080x1920", reset=True)


# -- the derivations move together ---------------------------------------


def test_both_derivations_follow_the_override(project: Project) -> None:
    """The whole reason this is one field: quoting caption sizes against a
    16:9 reference over a 9:16 render stretches the glyphs."""
    assert ops._mlt_resolution(project) == (1920, 816)
    assert ops._caption_canvas(project) == (2541, 1080)

    ops.canvas(project.root, size="1080x1920")

    assert ops._mlt_resolution(project) == (1080, 1920)
    assert ops._caption_canvas(project) == (608, 1080)


def test_status_reports_the_canvas_in_force(project: Project) -> None:
    assert ops.status(project.root)["canvas"] == "1920x816"

    ops.canvas(project.root, size="1080x1920")

    assert ops.status(project.root)["canvas"] == "1080x1920"


# -- the routing consequence ---------------------------------------------


def test_an_override_routes_a_single_source_project_through_mlt(project: Project) -> None:
    """The hole this closes: auto-editor takes an export and ignores the
    canvas, so a single-source project with an override would render 16:9
    and exit 0 — the silent-wrong-output this item exists to prevent."""
    edit = ops._load_edit(project)
    assert ops._is_layered(project, edit) is False

    ops.canvas(project.root, size="1080x1920")

    assert ops._is_layered(project, edit) is True
    assert ops.canvas(project.root)["routes_through"] == "mlt"


def test_an_aspect_changing_override_says_it_does_not_fill_the_frame(project: Project) -> None:
    """Until the reframe lands a swapped canvas pillarboxes, and a 9:16 file
    that is 76% black bar looks exactly like a 9:16 file that is right."""
    assert ops.canvas(project.root, size="1080x1920")["fills_frame"] is False
    assert ops.canvas(project.root, size="960x408")["fills_frame"] is True, "same aspect, rescaled"
