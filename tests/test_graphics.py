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

from lucid import captions, graphics, ops
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


def _two_weight_family() -> str | None:
    """An installed family with two weights whose renders differ.

    Discovered rather than named: which fonts a box has is not this repo's
    to assume (wiki `tooling.md` § Fonts), and a test that hard-coded one
    would skip everywhere else rather than check anything.
    """
    found = subprocess.run(
        ["fc-list", "--format=%{family}\n"], capture_output=True, text=True, check=False
    )
    counts: dict[str, set[str]] = {}
    for line in found.stdout.splitlines():
        for family in (f.strip() for f in line.split(",")):
            if family:
                counts.setdefault(family, set())
    for family in counts:
        styles = subprocess.run(
            ["fc-list", family, "--format=%{style}\n"],
            capture_output=True,
            text=True,
            check=False,
        )
        upright = {
            s.split(",")[0].strip()
            for s in styles.stdout.splitlines()
            if s.strip() and "Italic" not in s and "Oblique" not in s
        }
        if {"Regular", "Bold"} <= upright:
            return family
    return None


def _ink_width(family: str, weight: int, tmp_path: Path) -> int:
    """The width of the ink a real render lays down, in pixels.

    Trimmed off the raster rather than computed, because the question is
    what librsvg drew — the whole point of measuring instead of asking
    fontconfig.
    """
    source = tmp_path / f"ink-{weight}.svg"
    source.write_text(
        _svg(
            f'<text x="20" y="120" font-family="{family}" font-size="80" '
            f'font-weight="{weight}" fill="#000">Handgloves WM 0123</text>',
            width=2200,
            height=200,
        ),
        encoding="utf-8",
    )
    rendered = tmp_path / f"ink-{weight}.png"
    graphics.render_svg(source, rendered)
    trimmed = subprocess.run(
        [*graphics.magick_command(), str(rendered), "-trim", "-format", "%w", "info:"],
        capture_output=True,
        text=True,
        check=True,
    )
    return int(trimmed.stdout.strip())


def _quote_ink_width(quote: str, tmp_path: Path, tag: str) -> int:
    """The ink width of `quote` alone, rendered through the real coder.

    The quote is drawn on its own rather than inside a filled card, because
    trimming a whole receipt measures its title and stars too — and those do
    not move, so they would mask exactly the difference being looked for.
    """
    markup = graphics._runs_markup(
        graphics.parse_runs(quote), x=20, line_height=58, colours=dict(graphics.PALETTE)
    )
    source = tmp_path / f"quote-{tag}.svg"
    source.write_text(
        _svg(
            f'<text x="20" y="120" font-family="serif" font-size="48" '
            f'font-weight="600">{markup}</text>',
            width=2200,
            height=200,
        ),
        encoding="utf-8",
    )
    rendered = tmp_path / f"quote-{tag}.png"
    graphics.render_svg(source, rendered)
    trimmed = subprocess.run(
        [*graphics.magick_command(), str(rendered), "-trim", "-format", "%w", "info:"],
        capture_output=True,
        text=True,
        check=True,
    )
    return int(trimmed.stdout.strip())


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


# -- the weight half of a face --------------------------------------------


def test_declared_faces_reports_a_tspan_that_changes_only_the_weight() -> None:
    """`receipt.svg`'s own shape: one family, two weights, one of them on a
    child that names no family at all.

    Reporting per family answers once, for neither of them — which is what
    made the report wrong about a shipped template.
    """
    svg = _svg(
        '<text font-family="Card Face" font-weight="700">Scream'
        '<tspan font-weight="400"> (1996)</tspan></text>'
    )
    assert graphics.declared_faces(svg) == [
        {"declared": "Card Face", "weight": 700},
        {"declared": "Card Face", "weight": 400},
    ]


def test_declared_faces_inherits_a_family_down_a_group() -> None:
    """A `<g>` that sets the family is reported once, not once per child."""
    svg = _svg(
        '<g font-family="Card Face">'
        "<text>one</text><text>two</text>"
        '<text font-weight="bold">three</text>'
        "</g>"
    )
    assert graphics.declared_faces(svg) == [
        {"declared": "Card Face", "weight": 400},
        {"declared": "Card Face", "weight": 700},
    ]


def test_declared_faces_resolves_the_weight_keywords_and_the_relative_ones() -> None:
    """`bolder`/`lighter` step through CSS's own table, not by ±100.

    Nested rather than listed side by side because these are the one weight
    value that depends on what it inherits — a flat document would resolve
    them all against `normal` and prove nothing about the walk.
    """
    climbing = _svg(
        '<text font-family="Card Face" font-weight="normal">a'
        '<tspan font-weight="bolder">b<tspan font-weight="bolder">c</tspan></tspan></text>'
    )
    assert [f["weight"] for f in graphics.declared_faces(climbing)] == [400, 700, 900]

    falling = _svg(
        '<text font-family="Card Face" font-weight="900">a'
        '<tspan font-weight="lighter">b<tspan font-weight="lighter">c</tspan></tspan></text>'
    )
    assert [f["weight"] for f in graphics.declared_faces(falling)] == [900, 700, 400]


def test_declared_faces_dedupes_a_weight_a_document_returns_to() -> None:
    """One face asked for twice is one face. The report is what will be
    drawn, not a log of where it was asked for."""
    svg = _svg(
        '<text font-family="Card Face" font-weight="400">a'
        '<tspan font-weight="700">b<tspan font-weight="400">c</tspan></tspan></text>'
    )
    assert graphics.declared_faces(svg) == [
        {"declared": "Card Face", "weight": 400},
        {"declared": "Card Face", "weight": 700},
    ]


def test_declared_faces_reads_an_inline_style_over_the_attribute() -> None:
    svg = _svg(
        '<text font-family="Attribute Face" font-weight="400" '
        'style="font-family: Inline Face; font-weight: 700">a</text>'
    )
    assert graphics.declared_faces(svg) == [{"declared": "Inline Face", "weight": 700}]


def test_declared_faces_leaves_a_css_rules_weight_unknown_when_it_states_none() -> None:
    """Null is "we did not evaluate the cascade", not `normal`.

    A rule is attached by a selector this does not evaluate, so which
    elements it reaches — and therefore what weight they inherit — is not
    knowable from the rule alone. Reporting 400 there would be a guess
    dressed as an answer.
    """
    svg = _svg(
        "<style>.a { font-family: 'Rule Face' } "
        ".b { font-family: 'Weighted Face'; font-weight: 600 }</style>"
    )
    assert graphics.declared_faces(svg) == [
        {"declared": "'Rule Face'", "weight": None},
        {"declared": "'Weighted Face'", "weight": 600},
    ]


def test_declared_fonts_still_answers_families_alone() -> None:
    """The older question, still asked by callers that do not care."""
    svg = _svg(
        '<text font-family="Card Face" font-weight="700">a'
        '<tspan font-weight="400">b</tspan></text>'
    )
    assert graphics.declared_fonts(svg) == ["Card Face"]


@needs_fontconfig
def test_font_match_does_not_let_a_family_name_become_fontconfig_syntax() -> None:
    """A fontconfig pattern is `family-size`, so an unescaped `-` truncates.

    Unescaped, `fc-match` reads the tail as a point size and answers about
    the head — reporting a face nobody has as installed, which is the one
    direction this report must never be wrong in.
    """
    installed = _installed_face()
    match = captions.font_match(f"{installed}-24")
    assert match["available"] is False


@needs_fontconfig
def test_font_match_maps_a_css_weight_onto_fontconfigs_own_scale() -> None:
    """CSS 700 is fontconfig 200. Handed over unmapped it is above every
    real value, so every query answers Bold — including the ones that should
    not."""
    family = _two_weight_family()
    if family is None:
        pytest.skip("no installed family has two distinguishable weights")
    light = captions.font_match(family, weight=400)
    heavy = captions.font_match(family, weight=700)
    assert light["style"] != heavy["style"]
    assert light["weight"] == 400 and heavy["weight"] == 700


@needs_magick
@needs_fontconfig
def test_font_report_agrees_with_what_librsvg_actually_draws(tmp_path: Path) -> None:
    """The check this repo's rule demands: settle which face draws by
    measuring a render, never by `fc-match`.

    Two weights of one family are rendered through `render_svg`'s own coder
    and compared by ink width. A heavier CSS weight must draw wider ink, and
    the report must name a different style for it — if the mapping were
    dropped, both queries would answer Bold while the renders still differed,
    and the report would agree with neither.
    """
    family = _two_weight_family()
    if family is None:
        pytest.skip("no installed family has two distinguishable weights")

    widths = {w: _ink_width(family, w, tmp_path) for w in (400, 700)}
    assert widths[700] > widths[400], (
        f"{family} renders {widths} — the two weights are not distinguishable "
        "by ink, so this test cannot tell whether the report is right"
    )

    styles = {}
    for weight in (400, 700):
        (entry,) = graphics.font_report(
            _card(f'font-family="{family}" font-weight="{weight}"')
        )
        assert entry["weight"] == weight
        styles[weight] = entry["drawn_style"]
    assert styles[400] != styles[700]


# -- the measured flow -----------------------------------------------------

#: Finding 2's own rows: three real Scream quote lines, then the two
#: adversaries. `WWW MMM` is the one that decides whether the wrap is safe or
#: merely usually right — a character count *underestimates* it by a third,
#: which is the direction that overflows a card at exit 0.
FLOW_CASES = [
    (
        "I just realized I never watched this movie all the way through, and it "
        "might be the perfect horror slasher. I might bump it to 9/10."
    ),
    (
        "Matthew Lillard is incredible. Costume and villain design is perfectly "
        "iconic. The satire is great. I know I am late to the party but wow."
    ),
    (
        "Falls apart a bit in the second half. There is enough charm to keep this "
        "from being a boring teen drama reboot but it still suffers."
    ),
    "WWW MMM " * 12,
    "illillillill iiii llll iiii llll " * 4,
]

#: The dumb control the measured wrap has to beat: characters times a
#: plausible average advance. Deliberately the *obvious* build, so that when
#: it overflows below, it is this repo's own finding being reproduced rather
#: than a straw man.
_CHARACTER_ADVANCE = 46 * 0.5


def _flow(text: str, *, width: float = 1640, font: str = "serif", size: float = 46):
    return graphics.flow_runs(
        graphics.parse_runs(text), width=width, font=font, size=size
    )


@needs_magick
@pytest.mark.parametrize("text", FLOW_CASES)
def test_every_flowed_line_fits_the_width_it_was_flowed_to(text: str) -> None:
    """The safety property, stated as the only thing that actually matters.

    Not "the wrap is accurate" — accurate is a percentage. The card either
    stays inside its body width or it does not, so every produced line is
    measured back and checked.
    """
    for line in _flow(text):
        measured = graphics.measure_runs(line, font="serif", size=46, box=1640)
        rendered = "".join(run for run, _ in line)
        assert measured <= 1640, f"{rendered!r} flowed to {measured} units, over 1640"


@needs_magick
def test_a_character_count_would_overflow_where_the_measurement_does_not() -> None:
    """The control, run rather than asserted.

    A wrap is only worth its renders if the cheap alternative actually
    fails — so the cheap alternative is built here and measured on the same
    adversary. `WWW MMM` is finding 2's −34.6% row: the count thinks it fits
    and it does not.
    """
    adversary = "WWW MMM " * 12
    words = adversary.split()

    counted: list[str] = []
    line: list[str] = []
    for word in words:
        candidate = [*line, word]
        if line and len(" ".join(candidate)) * _CHARACTER_ADVANCE > 1640:
            counted.append(" ".join(line))
            line = [word]
        else:
            line = candidate
    if line:
        counted.append(" ".join(line))

    widest = max(
        graphics.measure_runs([(text, "key")], font="serif", size=46, box=1640)
        for text in counted
    )
    assert widest > 1640, (
        "the character count fitted this adversary, so it is not the adversary "
        f"finding 2 measured — widest counted line is {widest} units"
    )

    for line_runs in _flow(adversary):
        measured = graphics.measure_runs(line_runs, font="serif", size=46, box=1640)
        assert measured <= 1640


@needs_magick
def test_a_flow_keeps_the_runs_a_line_break_lands_inside() -> None:
    """A break inside an emphasised phrase must not lose the emphasis."""
    text = "plain words before [em]" + ("emphasised words " * 14) + "[/em] and after"
    flowed = _flow(text)
    assert len(flowed) > 1, "this case is only interesting once it wraps"
    levels = {level for line in flowed for _, level in line}
    assert "em" in levels and "key" in levels
    for line in flowed:
        joined = "".join(text for text, _ in line)
        assert joined == joined.strip(), "a wrapped line keeps the space it broke at"


@needs_magick
def test_a_flow_keeps_the_callers_own_line_breaks() -> None:
    """A break is an instruction; re-flowing across one joins two paragraphs."""
    flowed = _flow("short one\nshort two\nshort three")
    assert [("".join(t for t, _ in line)) for line in flowed] == [
        "short one",
        "short two",
        "short three",
    ]


@needs_magick
def test_a_quote_that_does_not_fit_its_box_is_refused_not_shrunk() -> None:
    """Growing the card is the tempting build and it is the wrong one — the
    canvas is the project's, not a slot value's."""
    with pytest.raises(GraphicsError, match="too many"):
        graphics.fill_template(
            "receipt",
            {**_required("receipt"), "quote": "a fairly ordinary sentence. " * 40},
        )


@needs_magick
def test_the_same_quote_fits_a_taller_canvas() -> None:
    """The box is derived from the canvas, so 9:16 holds more lines. A
    hard-coded box would refuse a quote that plainly fits."""
    quote = "a fairly ordinary sentence. " * 40
    filled = graphics.fill_template(
        "receipt", {**_required("receipt"), "quote": quote}, width=1080, height=1920
    )
    assert filled.count('xml:space="preserve"') > 10


def test_the_runs_slot_geometry_agrees_with_the_svg_it_is_drawn_in() -> None:
    """The spec states `x`, `y`, `size` and the SVG states them again.

    That duplication is how `x` has always worked here, but a body width
    read from one and a font size read from the other is a wrap measured at
    a size the card is not drawn at — silently, and only visible as a line
    that is slightly too long.
    """
    declared = graphics.TEMPLATES["receipt"]["slots"]["quote"]
    svg = graphics.template_path("receipt").read_text(encoding="utf-8")
    line = next(row for row in svg.splitlines() if "{{quote}}" in row)
    assert f'x="{declared["x"]}"' in line
    assert f'y="{declared["y"]}"' in line
    assert f'font-size="{declared["size"]}"' in line
    assert declared["width"] == 1920 - 2 * declared["x"]


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


# -- templates -------------------------------------------------------------


def _required(name: str) -> dict[str, object]:
    """Minimal slots for `name`: a value for everything it insists on."""
    return {
        slot: (3.5 if meta["kind"] == "rating" else f"{slot}-value")
        for slot, meta in graphics.template_slots(name).items()
        if meta["required"]
    }


@pytest.mark.parametrize("name", sorted(graphics.TEMPLATES))
def test_every_shipped_template_agrees_with_its_manifest(name: str) -> None:
    """The drift guard, run against each SVG lucid actually ships.

    `template_slots` raises when the placeholders in the file and the slots in
    the manifest disagree either way. A template with a placeholder nothing
    fills would otherwise ship a card with `{{year}}` printed on its face.
    """
    slots = graphics.template_slots(name)
    assert slots, f"{name} declares no slots"


@pytest.mark.parametrize("name", sorted(graphics.TEMPLATES))
def test_every_shipped_template_fills_and_parses(name: str) -> None:
    filled = graphics.fill_template(name, _required(name), flow=False)
    assert "{{" not in filled, "a placeholder survived the fill"
    graphics.declared_fonts(filled)  # raises unless the result is well-formed


def test_fill_template_refuses_a_missing_required_slot() -> None:
    with pytest.raises(GraphicsError, match="which nothing supplied"):
        graphics.fill_template("receipt", {"title": "Scream"}, flow=False)


def test_fill_template_refuses_a_slot_that_does_not_exist() -> None:
    with pytest.raises(GraphicsError, match="no slot"):
        graphics.fill_template(
            "receipt", {**_required("receipt"), "subtitle": "no such thing"}, flow=False
        )


def test_fill_template_refuses_an_unknown_template() -> None:
    with pytest.raises(GraphicsError, match="no template named"):
        graphics.fill_template("nonexistent", {}, flow=False)


def test_user_text_is_escaped_and_cannot_rewrite_the_document() -> None:
    """String substitution's one real hazard, closed and asserted."""
    hostile = '</text><script>alert("x")</script><text>'
    filled = graphics.fill_template(
        "receipt", {**_required("receipt"), "title": hostile}, flow=False
    )
    assert "<script>" not in filled
    assert "&lt;/text&gt;" in filled
    graphics.declared_fonts(filled)  # still well-formed


def test_a_slot_landing_in_an_attribute_cannot_close_it() -> None:
    """`font-family="{{title_font}}"` is an attribute, so `"` has to escape."""
    filled = graphics.fill_template(
        "receipt", {**_required("receipt"), "title_font": 'x" onload="boom'}
    )
    assert 'onload="boom' not in filled
    graphics.declared_fonts(filled)


def test_lucid_generated_markup_is_not_escaped() -> None:
    """Derived slots are the only unescaped insertion, and they must render."""
    filled = graphics.fill_template("receipt", {**_required("receipt"), "rating": 3}, flow=False)
    assert filled.count("<polygon") == 3
    assert "&lt;polygon" not in filled


def test_a_half_rating_draws_a_clipped_star_rather_than_a_second_path() -> None:
    filled = graphics.fill_template("receipt", {**_required("receipt"), "rating": 4.5}, flow=False)
    assert filled.count("<polygon") == 5
    assert filled.count("<clipPath") == 1


def test_a_whole_rating_draws_no_clip() -> None:
    filled = graphics.fill_template("receipt", {**_required("receipt"), "rating": 3}, flow=False)
    assert "<clipPath" not in filled


def test_the_two_rows_of_a_comparison_do_not_share_a_clip_id() -> None:
    """Two halves in one document, which a single id would collapse into one."""
    filled = graphics.fill_template(
        "rerate", {**_required("rerate"), "before": 2.5, "after": 3.5}
    )
    assert 'id="before-half"' in filled
    assert 'id="after-half"' in filled


def test_a_rating_must_be_a_number_out_of_five() -> None:
    with pytest.raises(GraphicsError, match="rating out of five"):
        graphics.fill_template(
            "receipt", {**_required("receipt"), "rating": "four and a half"}, flow=False
        )
    with pytest.raises(GraphicsError, match="outside it"):
        graphics.fill_template("receipt", {**_required("receipt"), "rating": 7}, flow=False)


def test_unflowed_a_newline_is_a_line_break_and_nothing_else_breaks() -> None:
    """`flow=False` is the older contract, kept exactly rather than relaxed.

    Without a measurement there is no safe wrap, so there is no wrap: the
    caller's newlines are the only line breaks, and 200 words run off the
    card in one line. That is the claim `_lines_markup` used to make, and it
    still holds for the mode that does not measure. Step 2 did not soften it;
    it added a mode that measures.
    """
    filled = graphics.fill_template(
        "receipt", {**_required("receipt"), "quote": "first line\nsecond line"}, flow=False
    )
    assert filled.count("<tspan") >= 2
    assert "first line" in filled and "second line" in filled

    long = "word " * 200
    once = graphics.fill_template("receipt", {**_required("receipt"), "quote": long}, flow=False)
    assert once.count('dy="58"') == 0, "nothing may wrap on its own"


# -- the runs a quote is made of -------------------------------------------


def test_parse_runs_reads_the_three_levels_and_defaults_the_rest() -> None:
    parsed = graphics.parse_runs("might be the [em]perfect[/em] horror [dim]slasher[/dim].")
    assert parsed == [
        [
            ("might be the ", "key"),
            ("perfect", "em"),
            (" horror ", "key"),
            ("slasher", "dim"),
            (".", "key"),
        ]
    ]


def test_parse_runs_nests_innermost_first() -> None:
    parsed = graphics.parse_runs("[dim]a [em]b[/em] c[/dim]")
    assert parsed == [[("a ", "dim"), ("b", "em"), (" c", "dim")]]


def test_a_run_spans_a_line_break_so_a_paragraph_is_marked_once() -> None:
    parsed = graphics.parse_runs("[dim]first\nsecond[/dim]")
    assert parsed == [[("first", "dim")], [("second", "dim")]]


def test_a_doubled_bracket_is_the_escape_and_a_lone_one_is_just_prose() -> None:
    """`[sic]` is not markup, so the escape is only owed for a real marker."""
    assert graphics.parse_runs("[sic] and [nonsense]") == [
        [("[sic] and [nonsense]", "key")]
    ]
    assert graphics.parse_runs("[[em]not emphasis[[/em]") == [
        [("[em]not emphasis[/em]", "key")]
    ]


def test_parse_runs_refuses_a_close_with_nothing_open() -> None:
    with pytest.raises(GraphicsError, match="closes a run that is not open"):
        graphics.parse_runs("plain text[/em]")
    with pytest.raises(GraphicsError, match="closes a run that is not open"):
        graphics.parse_runs("[dim]crossed [em]over[/dim][/em]")


def test_parse_runs_refuses_a_run_left_open() -> None:
    """It would draw the rest of the card in that ink and look deliberate."""
    with pytest.raises(GraphicsError, match="still open at the end"):
        graphics.parse_runs("the [em]rest of the card")


def test_a_run_value_cannot_smuggle_markup_into_the_card() -> None:
    filled = graphics.fill_template(
        "receipt", {**_required("receipt"), "quote": '</text><script>x</script>'}
    )
    assert "<script>" not in filled
    assert "&lt;script&gt;" in filled


@needs_magick
@needs_fontconfig
def test_the_three_run_levels_render_the_inks_they_were_measured_from(
    tmp_path: Path,
) -> None:
    """Step 1's own success criterion: the levels are not a new look, they
    are `make_scream_cards.py`'s `STYLES` reproduced.

    Sampled back off the raster rather than eyeballed, because a fill that
    renders at the wrong opacity still renders — this is the one check that
    would notice.
    """
    source = tmp_path / "inks.svg"
    source.write_text(
        graphics.fill_template(
            "receipt",
            {
                **_required("receipt"),
                "quote": "[dim]dimmed[/dim]\nplain key ink\n[em]amber emphasis[/em]",
            },
        ),
        encoding="utf-8",
    )
    graphics.render_svg(source, tmp_path / "inks.png")

    histogram = subprocess.run(
        [*graphics.magick_command(), str(tmp_path / "inks.png"), "-format", "%c", "histogram:info:"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    present = set()
    for line in histogram.splitlines():
        if "(" not in line or ")" not in line:
            continue
        channels = line[line.find("(") + 1 : line.find(")")].split(",")
        try:
            present.add(tuple(int(float(c)) for c in channels[:3]))
        except ValueError:
            continue

    # PLAN.md § The emphasis-capable quote slot, finding 1.
    for level, expected in (
        ("key", (26, 23, 20)),
        ("em", (232, 161, 60)),
        ("dim", (155, 151, 145)),
    ):
        assert expected in present, (
            f"{level} should render {expected}; nearest in the raster is "
            f"{min(present, key=lambda p: sum(abs(a - b) for a, b in zip(p, expected)))}"
        )


@needs_magick
@needs_fontconfig
def test_splitting_a_line_into_runs_does_not_eat_the_spaces_between_them(
    tmp_path: Path,
) -> None:
    """The measured trap `xml:space="preserve"` exists for.

    Per-run `<tspan>`s collapse the whitespace at every chunk boundary, so
    "the [em]perfect[/em] horror" renders as "theperfecthorror" — narrower,
    at exit 0, looking like a deliberate ligature. `[key]` is the control
    that isolates it: same weight, same fill, same opacity as unmarked text,
    so the *only* difference between the two renders is the tspan split.
    """
    plain = _quote_ink_width("might be the perfect horror slasher.", tmp_path, "plain")
    split = _quote_ink_width(
        "might be the [key]perfect[/key] horror slasher.", tmp_path, "split"
    )
    assert split == plain, (
        f"the same words render {plain}px whole and {split}px split into runs — "
        "the space at a run boundary is being collapsed"
    )


def test_the_viewbox_follows_the_canvas_aspect() -> None:
    """Why a template can be authored once and rendered at any canvas."""
    name = min(graphics.TEMPLATES)
    wide = graphics.fill_template(name, _required(name), width=1920, height=816, flow=False)
    assert 'viewBox="0 0 1920 816"' in wide
    tall = graphics.fill_template(name, _required(name), width=1080, height=1920, flow=False)
    assert 'viewBox="0 0 1920 3413"' in tall


@needs_magick
@pytest.mark.parametrize("name", sorted(graphics.TEMPLATES))
def test_a_template_renders_at_exactly_the_canvas_it_was_filled_for(
    name: str, tmp_path: Path
) -> None:
    """Step 3's claim, at the level that can prove it.

    The card comes back 1920x816 — not 1450x816, which is what fitting a
    16:9 document into that frame gives (see the fit test above). No
    pillarbox, because the document was authored at the aspect.
    """
    source = tmp_path / f"{name}.svg"
    source.write_text(graphics.fill_template(name, _required(name), width=1920, height=816))
    result = graphics.render_svg(source, tmp_path / f"{name}.png")
    assert (result["width"], result["height"]) == (1920, 816)


# -- card_new --------------------------------------------------------------


@pytest.fixture
def wide_project(tmp_path: Path) -> Project:
    """A project whose footage is the Scream cut's 1920x816 crop."""
    project = Project.create(tmp_path / "wide")
    manifest = project.read_manifest()
    manifest["clips"] = [
        {
            "clip_id": "film",
            "source": "/nonexistent/film.mp4",
            "duration": 10.0,
            "has_video": True,
            "has_audio": True,
            "width": 1920,
            "height": 816,
        }
    ]
    project.write_manifest(manifest)
    return project


@needs_magick
def test_card_new_defaults_to_the_projects_own_canvas(wide_project: Project) -> None:
    """Finding 4 closed: no 1920x1080 card in a 1920x816 frame."""
    out = ops.card_new(wide_project.root, "reveal-two", "reveal", {"title": "Scream 2"})
    assert out["canvas"] == "1920x816"
    assert out["canvas_from"] == "project"
    assert (out["width"], out["height"]) == (1920, 816)


@needs_magick
def test_card_new_takes_an_explicit_canvas_when_told(wide_project: Project) -> None:
    out = ops.card_new(
        wide_project.root, "reveal-two", "reveal", {"title": "Scream 2"}, width=1080, height=1920
    )
    assert out["canvas_from"] == "requested"
    assert (out["width"], out["height"]) == (1080, 1920)


def test_card_new_refuses_half_a_canvas(wide_project: Project) -> None:
    with pytest.raises(ProjectError, match="both width and height"):
        ops.card_new(wide_project.root, "reveal-two", "reveal", {"title": "S"}, width=1080)


@needs_magick
def test_card_new_lands_both_files_where_the_cue_looks(wide_project: Project) -> None:
    out = ops.card_new(wide_project.root, "reveal-two", "reveal", {"title": "Scream 2"})
    assert out["asset"] == "card:reveal-two"
    assert (wide_project.cards_dir / "reveal-two.svg").is_file()
    assert (wide_project.cards_dir / "reveal-two.png").is_file()
    resolved = ops._resolve_asset(wide_project, "card:reveal-two")
    assert Path(resolved["asset_path"]) == wide_project.cards_dir / "reveal-two.png"


@needs_magick
def test_card_new_refuses_to_replace_a_card_a_cue_may_point_at(wide_project: Project) -> None:
    ops.card_new(wide_project.root, "reveal-two", "reveal", {"title": "Scream 2"})
    with pytest.raises(ProjectError, match="already exists"):
        ops.card_new(wide_project.root, "reveal-two", "reveal", {"title": "Scream 3"})

    replaced = ops.card_new(
        wide_project.root, "reveal-two", "reveal", {"title": "Scream 3"}, overwrite=True
    )
    assert "Scream 3" in (wide_project.cards_dir / "reveal-two.svg").read_text()
    assert replaced["card"] == "reveal-two"


def test_card_templates_lists_every_template_with_its_slots() -> None:
    listed = ops.card_templates()["templates"]
    assert {t["template"] for t in listed} == set(graphics.TEMPLATES)
    for entry in listed:
        assert entry["description"]
        assert entry["slots"]
        # Style is reported apart from content, so the required fields are not
        # buried under the palette once the front ends sort their JSON.
        assert set(entry["style"]) == set(graphics.STYLE_SLOTS)
        assert not set(entry["slots"]) & set(graphics.STYLE_SLOTS)
        assert all(not meta["required"] for meta in entry["style"].values())
