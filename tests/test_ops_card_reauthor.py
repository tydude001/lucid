"""Card records and `card_reauthor` — step 2 of PLAN.md § Aspect swap.

The item's finding 5 is what these pin down: **cards are the only project
state that is rasterised rather than derived.** Captions survive a canvas
change because they come off `caption_style` every time; a card has its
aspect baked into the SVG's viewBox and its pixels into the PNG, and nothing
on disk says what it was made from. So the record is the fix, and the test
that matters is the contrast between re-*rendering* a stale card at the new
size (which pillarboxes it, silently, at exit 0) and re-*authoring* it.

Built by hand where magick is not needed, following `test_ops_canvas.py`.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from lucid import graphics, ops
from lucid.project import Project, ProjectError

needs_magick = pytest.mark.skipif(
    shutil.which("magick") is None, reason="ImageMagick is not installed"
)

CLIP = {
    "clip_id": "cold-open",
    "source": "/nonexistent/cold-open.mp4",
    "duration": 12.0,
    "has_video": True,
    "has_audio": True,
    "width": 1920,
    "height": 816,
}


@pytest.fixture
def project(tmp_path: Path) -> Project:
    """A project whose footage is the Scream cut's 1920x816 crop."""
    project = Project.create(tmp_path / "proj")
    manifest = project.read_manifest()
    manifest["clips"] = [CLIP]
    project.write_manifest(manifest)
    return project


def _record(project: Project, name: str) -> dict:
    found = [r for r in project.read_manifest()["cards"] if r["card"] == name]
    assert len(found) == 1, f"expected one record for {name}, got {found}"
    return found[0]


# -- the record ----------------------------------------------------------


@needs_magick
def test_card_new_records_what_the_card_was_made_from(project: Project) -> None:
    ops.card_new(project.root, "reveal-two", "reveal", {"title": "Scream 2"})

    record = _record(project, "reveal-two")
    assert record["template"] == "reveal"
    assert record["slots"] == {"title": "Scream 2"}
    assert record["canvas"] == "1920x816"


@needs_magick
def test_a_remade_card_replaces_its_record_rather_than_gaining_a_second(
    project: Project,
) -> None:
    """Two records for one name would make "what is this card" a question with
    two answers, and `card_reauthor` would draw whichever came first."""
    ops.card_new(project.root, "reveal-two", "reveal", {"title": "Scream 2"})
    ops.card_new(project.root, "reveal-two", "reveal", {"title": "Scream 3"}, overwrite=True)

    assert len(project.read_manifest()["cards"]) == 1
    assert _record(project, "reveal-two")["slots"] == {"title": "Scream 3"}


@needs_magick
def test_a_template_error_leaves_no_record_of_a_card_that_does_not_exist(
    project: Project,
) -> None:
    with pytest.raises(graphics.GraphicsError):
        ops.card_new(project.root, "reveal-two", "reveal", {"nosuchslot": "x"})

    assert project.read_manifest()["cards"] == []


@needs_magick
def test_card_new_refuses_a_name_that_exists_as_a_png_alone(project: Project) -> None:
    """The Scream project's own case: twelve cards drawn outside lucid, PNG and
    no SVG. A guard that looked at the source alone would overwrite the raster
    a cue resolves to without ever tripping."""
    project.cards_dir.mkdir(parents=True, exist_ok=True)
    stray = project.cards_dir / "receipt-scream-1996.png"
    stray.write_bytes(b"not really a png")

    with pytest.raises(ProjectError, match="already exists"):
        ops.card_new(project.root, "receipt-scream-1996", "reveal", {"title": "Scream"})
    assert stray.read_bytes() == b"not really a png"


# -- re-authoring --------------------------------------------------------


@needs_magick
def test_reauthor_redraws_at_the_new_canvas_where_a_re_render_would_letterbox(
    project: Project,
) -> None:
    """The whole reason the op exists. `-size` *fits*, so rasterising the old
    16:9 document into a 9:16 frame pillarboxes the card inside the frame —
    a plausible-looking file at exit 0. Only `fill_template` can move the
    geometry, and only the record can feed it."""
    ops.card_new(project.root, "reveal-two", "reveal", {"title": "Scream 2"})
    ops.canvas(project.root, size="1080x1920")

    # What re-rendering the stale source at the new size would have produced.
    stale = graphics.render_svg(
        project.cards_dir / "reveal-two.svg",
        project.root / "letterboxed.png",
        width=1080,
        height=1920,
    )
    assert (stale["width"], stale["height"]) == (1080, 459)

    result = ops.card_reauthor(project.root)

    assert result["canvas"] == "1080x1920"
    assert result["redrawn"] == 1
    assert graphics.identify(project.cards_dir / "reveal-two.png") == (1080, 1920)
    assert _record(project, "reveal-two")["canvas"] == "1080x1920"


@needs_magick
def test_reauthor_keeps_the_content_it_redraws(project: Project) -> None:
    ops.card_new(project.root, "reveal-two", "reveal", {"title": "Scream 2"})
    ops.canvas(project.root, size="1080x1920")

    ops.card_reauthor(project.root)

    svg = (project.cards_dir / "reveal-two.svg").read_text(encoding="utf-8")
    assert "Scream 2" in svg
    assert 'width="1080"' in svg and 'height="1920"' in svg


@needs_magick
def test_a_sweep_leaves_a_card_already_at_the_canvas_alone(project: Project) -> None:
    ops.card_new(project.root, "reveal-two", "reveal", {"title": "Scream 2"})
    before = (project.cards_dir / "reveal-two.png").stat().st_mtime_ns

    result = ops.card_reauthor(project.root)

    assert result["redrawn"] == 0
    assert result["to_redraw"] == 0
    assert result["cards"][0]["why"] == "already at the project canvas"
    assert (project.cards_dir / "reveal-two.png").stat().st_mtime_ns == before


@needs_magick
def test_naming_a_card_redraws_it_whatever_its_canvas(project: Project) -> None:
    """An explicit ask is not second-guessed — which is also how a card whose
    SVG somebody hand-edited gets put back to what the record says."""
    ops.card_new(project.root, "reveal-two", "reveal", {"title": "Scream 2"})
    (project.cards_dir / "reveal-two.svg").write_text("<svg/>", encoding="utf-8")

    result = ops.card_reauthor(project.root, "reveal-two")

    assert result["redrawn"] == 1
    assert result["cards"][0]["why"] == "asked for"
    assert "Scream 2" in (project.cards_dir / "reveal-two.svg").read_text(encoding="utf-8")


@needs_magick
def test_a_recorded_card_whose_files_are_gone_is_redrawn_at_the_same_canvas(
    project: Project,
) -> None:
    ops.card_new(project.root, "reveal-two", "reveal", {"title": "Scream 2"})
    (project.cards_dir / "reveal-two.png").unlink()

    result = ops.card_reauthor(project.root)

    assert result["redrawn"] == 1
    assert "missing reveal-two.png" in result["cards"][0]["why"]
    assert (project.cards_dir / "reveal-two.png").is_file()


@needs_magick
def test_reauthor_sweeps_every_stale_card_in_one_call(project: Project) -> None:
    ops.card_new(project.root, "reveal-two", "reveal", {"title": "Scream 2"})
    ops.card_new(project.root, "reveal-three", "reveal", {"title": "Scream 3"})
    ops.canvas(project.root, size="1080x1920")

    result = ops.card_reauthor(project.root)

    assert result["redrawn"] == 2
    for name in ("reveal-two", "reveal-three"):
        assert graphics.identify(project.cards_dir / f"{name}.png") == (1080, 1920)


# -- what it refuses to do quietly ---------------------------------------


def test_an_unrecorded_card_is_named_rather_than_skipped(project: Project) -> None:
    project.cards_dir.mkdir(parents=True, exist_ok=True)
    (project.cards_dir / "receipt-scream-1996.png").write_bytes(b"drawn elsewhere")

    result = ops.card_reauthor(project.root)

    assert result["unrecorded"] == ["receipt-scream-1996"]
    assert result["cards"] == []


def test_naming_an_unrecorded_card_refuses_and_says_the_way_back(project: Project) -> None:
    project.cards_dir.mkdir(parents=True, exist_ok=True)
    (project.cards_dir / "receipt-scream-1996.png").write_bytes(b"drawn elsewhere")

    with pytest.raises(ProjectError, match="card new"):
        ops.card_reauthor(project.root, "receipt-scream-1996")


def test_naming_a_card_that_does_not_exist_at_all_says_so(project: Project) -> None:
    with pytest.raises(ProjectError, match="no such card"):
        ops.card_reauthor(project.root, "nothing-here")


@needs_magick
def test_plan_resolves_and_writes_nothing(project: Project) -> None:
    ops.card_new(project.root, "reveal-two", "reveal", {"title": "Scream 2"})
    ops.canvas(project.root, size="1080x1920")
    before = (project.cards_dir / "reveal-two.png").stat().st_mtime_ns

    result = ops.card_reauthor(project.root, plan=True)

    assert result["plan"] is True
    assert result["to_redraw"] == 1
    assert result["redrawn"] == 0
    assert result["cards"][0]["why"] == "1920x816 -> 1080x1920"
    assert (project.cards_dir / "reveal-two.png").stat().st_mtime_ns == before
    assert _record(project, "reveal-two")["canvas"] == "1920x816"


def test_reauthor_takes_no_size_argument() -> None:
    """A card authored at anything but the project canvas is finding 4 of the
    note again; the knob for a different shape is `canvas`, one level up."""
    import inspect

    taken = set(inspect.signature(ops.card_reauthor).parameters)
    assert not taken & {"width", "height", "size", "canvas"}


# -- what the canvas op says about them ----------------------------------


@needs_magick
def test_canvas_names_the_cards_a_swap_has_left_behind(project: Project) -> None:
    """The moment the shape moves is the moment to say which cards no longer
    agree with it — the one piece of project state a swap cannot re-derive."""
    ops.card_new(project.root, "reveal-two", "reveal", {"title": "Scream 2"})
    (project.cards_dir / "receipt-scream-1996.png").write_bytes(b"drawn elsewhere")

    result = ops.canvas(project.root, size="1080x1920")

    assert result["cards_stale"] == ["reveal-two"]
    assert result["cards_unrecorded"] == ["receipt-scream-1996"]


@needs_magick
def test_canvas_stops_naming_a_card_once_it_has_been_redrawn(project: Project) -> None:
    ops.card_new(project.root, "reveal-two", "reveal", {"title": "Scream 2"})
    ops.canvas(project.root, size="1080x1920")
    ops.card_reauthor(project.root)

    assert ops.canvas(project.root)["cards_stale"] == []
