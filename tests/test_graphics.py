"""`graphics.render_svg` and `ops.card_render` — step 1 of motion graphics.

The claims under test are the ones PLAN.md § Motion graphics and templates
measured on this box: `-size` is a vector render that fits rather than
distorts, a missing font is invisible in the output so the report is the only
guard, and the PNG has to land under exactly the name `card:<name>` resolves
to or the failure arrives at export.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from lucid import graphics, ops
from lucid.graphics import GraphicsError
from lucid.project import Project, ProjectError

needs_magick = pytest.mark.skipif(
    shutil.which("magick") is None, reason="ImageMagick is not installed"
)
needs_fontconfig = pytest.mark.skipif(
    shutil.which("fc-match") is None, reason="fc-match is not installed"
)

#: A face nobody has. Long and specific so it cannot collide with a real one.
ABSENT_FACE = "Lucid Test Face That Is Not Installed"


def _installed_face() -> str:
    """A font family this box actually has, whichever one that is."""
    found = subprocess.run(
        ["fc-match", "--format=%{family}", "sans-serif"],
        capture_output=True,
        text=True,
        check=True,
    )
    return found.stdout.split(",")[0].strip()


def _svg(body: str, *, width: int = 1920, height: int = 1080) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">{body}</svg>'
    )


def _card(text_attrs: str = "") -> str:
    return _svg(
        '<rect width="1920" height="1080" fill="#101418"/>'
        f'<text x="960" y="540" text-anchor="middle" font-size="96" fill="#faf5ec" '
        f"{text_attrs}>Scream 1996</text>"
    )


# -- reading the fonts a document names ------------------------------------


def test_declared_fonts_finds_all_three_spellings() -> None:
    """Attribute, inline style, and a CSS rule — deduped, in document order."""
    svg = _svg(
        "<style>.title { font-family: 'Rule Face'; fill: red }</style>"
        '<text font-family="Attribute Face">a</text>'
        '<text style="fill: blue; font-family: Inline Face">b</text>'
        '<text font-family="Attribute Face">again</text>'
    )
    assert graphics.declared_fonts(svg) == [
        "'Rule Face'",
        "Attribute Face",
        "Inline Face",
    ]


def test_declared_fonts_refuses_a_document_that_is_not_xml() -> None:
    with pytest.raises(GraphicsError, match="not well-formed"):
        graphics.declared_fonts("<svg><rect")


@needs_fontconfig
def test_font_report_passes_an_installed_face() -> None:
    face = _installed_face()
    (entry,) = graphics.font_report(_card(f'font-family="{face}"'))
    assert entry["available"] is True
    assert entry["drawn"] == face
    assert "warning" not in entry


@needs_fontconfig
def test_font_report_warns_about_a_missing_face() -> None:
    (entry,) = graphics.font_report(_card(f'font-family="{ABSENT_FACE}"'))
    assert entry["available"] is False
    assert entry["families"] == [ABSENT_FACE]
    assert entry["drawn"] and entry["drawn"] != ABSENT_FACE
    assert ABSENT_FACE in entry["warning"]


@needs_fontconfig
def test_font_report_does_not_warn_when_the_stack_has_an_installed_face() -> None:
    """The false alarm this shape exists to avoid.

    A fallback stack whose *later* entry is missing is not a substitution —
    the author's first choice is what gets drawn. Reporting per face rather
    than per declaration would warn about working output.
    """
    face = _installed_face()
    (entry,) = graphics.font_report(_card(f"font-family=\"'{face}', '{ABSENT_FACE}'\""))
    assert entry["available"] is True
    assert entry["drawn"] == face
    assert "warning" not in entry


@needs_fontconfig
def test_font_report_treats_a_generic_stack_as_asking_for_no_face() -> None:
    """`sans-serif` is not an uninstalled font; it is a request with no face."""
    (entry,) = graphics.font_report(_card('font-family="sans-serif"'))
    assert entry["available"] is True
    assert "warning" not in entry


# -- rendering -------------------------------------------------------------


@needs_magick
def test_render_svg_uses_the_documents_own_size_by_default(tmp_path: Path) -> None:
    source = tmp_path / "card.svg"
    source.write_text(_card(), encoding="utf-8")
    result = graphics.render_svg(source, tmp_path / "card.png")
    assert (result["width"], result["height"]) == (1920, 1080)
    assert result["requested_size"] is None
    assert Path(result["output"]).is_file()


@needs_magick
def test_render_svg_renders_at_an_asked_for_size(tmp_path: Path) -> None:
    source = tmp_path / "card.svg"
    source.write_text(_svg('<rect width="1920" height="816" fill="#101418"/>', height=816))
    result = graphics.render_svg(source, tmp_path / "card.png", width=1920, height=816)
    assert (result["width"], result["height"]) == (1920, 816)


@needs_magick
def test_render_svg_fits_rather_than_distorts(tmp_path: Path) -> None:
    """The measurement behind `RENDER_FIT`, and behind finding 4's pillarbox.

    A 16:9 document asked for 1920x816 comes back 816 tall and *narrower*
    than 1920. Nothing here stretches to fill the ask, which is why a card
    authored at the wrong aspect pillarboxes instead of looking squashed —
    and why step 3 authors at the canvas size rather than resizing here.
    """
    source = tmp_path / "card.svg"
    source.write_text(_card(), encoding="utf-8")
    result = graphics.render_svg(source, tmp_path / "card.png", width=1920, height=816)
    assert result["height"] == 816
    assert result["width"] < 1920
    assert result["requested_size"] == "1920x816"
    assert result["size_policy"] == graphics.RENDER_FIT


@needs_magick
def test_render_svg_refuses_half_a_size(tmp_path: Path) -> None:
    source = tmp_path / "card.svg"
    source.write_text(_card(), encoding="utf-8")
    with pytest.raises(GraphicsError, match="both width and height"):
        graphics.render_svg(source, tmp_path / "card.png", width=1920)


@needs_magick
def test_render_svg_refuses_a_malformed_document_before_shelling_out(tmp_path: Path) -> None:
    source = tmp_path / "card.svg"
    source.write_text("<svg><rect", encoding="utf-8")
    with pytest.raises(GraphicsError, match="not well-formed"):
        graphics.render_svg(source, tmp_path / "card.png")


@needs_magick
@needs_fontconfig
def test_a_missing_font_renders_anyway_and_only_the_report_says_so(tmp_path: Path) -> None:
    """The caption trap on a second renderer, asserted rather than assumed.

    Rendering does not fail, the PNG is the right size, and nothing about the
    file records that the face was substituted — so `font_warnings` is the
    only place the substitution is visible at all.
    """
    source = tmp_path / "card.svg"
    source.write_text(_card(f'font-family="{ABSENT_FACE}"'), encoding="utf-8")
    result = graphics.render_svg(source, tmp_path / "card.png")
    assert (result["width"], result["height"]) == (1920, 1080)
    assert len(result["font_warnings"]) == 1
    assert ABSENT_FACE in result["font_warnings"][0]


# -- the project-level operation -------------------------------------------


@pytest.fixture
def project(tmp_path: Path) -> Project:
    project = Project.create(tmp_path / "proj")
    project.cards_dir.mkdir(parents=True, exist_ok=True)
    return project


@needs_magick
def test_card_render_lands_where_the_cue_resolves(project: Project) -> None:
    """The claim that makes the op worth having over `render_svg` alone."""
    (project.cards_dir / "receipt.svg").write_text(_card(), encoding="utf-8")
    result = ops.card_render(project.root, "receipt")

    assert result["asset"] == "card:receipt"
    assert Path(result["output"]) == project.cards_dir / "receipt.png"
    resolved = ops._resolve_asset(project, "card:receipt")
    assert Path(resolved["asset_path"]) == project.cards_dir / "receipt.png"
    assert resolved["is_image"] is True


@needs_magick
def test_card_render_keeps_the_svg_source(project: Project) -> None:
    """Both files, so a card can be re-edited rather than redrawn."""
    (project.cards_dir / "receipt.svg").write_text(_card(), encoding="utf-8")
    ops.card_render(project.root, "receipt")
    assert (project.cards_dir / "receipt.svg").is_file()
    assert (project.cards_dir / "receipt.png").is_file()


def test_card_render_refuses_a_name_that_is_a_path(project: Project) -> None:
    with pytest.raises(ProjectError, match="not a card name"):
        ops.card_render(project.root, "../elsewhere/receipt")


def test_card_render_names_the_cards_that_do_have_a_source(project: Project) -> None:
    (project.cards_dir / "receipt.svg").write_text(_card(), encoding="utf-8")
    with pytest.raises(ProjectError, match="receipt.svg"):
        ops.card_render(project.root, "reveal")
