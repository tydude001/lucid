"""Rasterise a card's SVG into the PNG a picture cue resolves to.

Step 1 of PLAN.md § Motion graphics and templates. The finding that shapes
this module is that motion graphics need no new timeline mechanism — the
Scream assembly's cards already ride the cue table as stills — so what was
missing is a *generator* for the asset. This is its renderer.

`magick` is shelled the way `asr` shells whisper and `picture` shells melt:
an external renderer with a resolution order and no Python API worth binding.
So this module has no lucid dependencies beyond `captions.font_match`, which
it reuses rather than growing a second font check.

Four things measured on this box, 2026-08-09, that the code below depends on:

* **There is a real SVG rasteriser here and the obvious probes miss it.**
  `rsvg-convert`, `inkscape`, `resvg` and `cairosvg` are all absent;
  ImageMagick 7.1.2 links **librsvg 2.62.0** as its SVG coder. The row that
  shows it is `RSVG` in `magick -list format`, not ImageMagick's own weak
  internal `MSVG`. Details: wiki `tooling.md` § Rasterising SVG.
* **`-size WxH` before the input is a vector render at that size; `-resize`
  after it is a resample.** Measured on the same 1920x1080 card: `-size`
  gave a clean 8-bit/256-colour raster, `-resize` a 16-bit one an order of
  magnitude larger — it rasterises at the document's native size and then
  scales the pixels, which is exactly what you do not want done to text. So
  the size knob goes *before* the input, and `RENDER_FIT` records that it
  fits rather than distorts: 1920x816 asked of a 16:9 document gives
  1450x816, not a squashed 1920.
* **A missing font renders pixel-identical at exit 0** — the caption trap
  (CLAUDE.md), reproduced on a second renderer. The same card naming
  `Noto Sans` and naming a face that does not exist compared at AE 0. So
  the font report is the *only* guard there is, and like `captions.font_match`
  it reports rather than prevents.
* **Unlike melt, magick's exit code can be trusted here.** A truncated SVG
  and a file that is not SVG at all both exit 1 with a message naming
  `RenderRSVGImage`. That is worth writing down only because so much else in
  this repo exits 0 on failure; it means this module does not need to prove
  the output exists by other means. It reads the finished raster's dimensions
  back anyway — `mlt.declared_frames`' discipline — because "what size is the
  card" is a question about the file, not about the arguments.
"""

from __future__ import annotations

import math
import os
import re
import shlex
import shutil
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from lucid.captions import font_match


class GraphicsError(RuntimeError):
    """A card could not be rendered."""


#: How `-size` treats an aspect it cannot match exactly. Recorded as a
#: constant because it is the whole of finding 4 in the design note: cards
#: pillarbox not because fitting is wrong but because a card authored at a
#: different aspect from its film has nowhere else to go. Step 3 closes that
#: by authoring at the canvas size; nothing here distorts to hide it.
RENDER_FIT = "fit"

#: CSS generic families. fontconfig resolves every one of them, so asking
#: `font_match` whether "sans-serif" is *installed* answers False about a
#: request that was never for a particular face — a false alarm of exactly
#: the kind the design note's finding 3 exists to not repeat.
GENERIC_FAMILIES = frozenset(
    {
        "serif",
        "sans-serif",
        "monospace",
        "cursive",
        "fantasy",
        "system-ui",
        "ui-serif",
        "ui-sans-serif",
        "ui-monospace",
        "ui-rounded",
        "math",
        "emoji",
        "fangsong",
        "inherit",
        "initial",
        "revert",
        "unset",
    }
)

_SVG_NS = "http://www.w3.org/2000/svg"

#: `selector { declarations }`, for the CSS inside a `<style>` element.
_RULE_BODY = re.compile(r"\{([^}]*)\}")


def magick_command() -> list[str]:
    """The argv prefix that runs ImageMagick, however it is installed here.

    A list rather than a path for the same reason `picture.melt_command` is
    one — `LUCID_MAGICK` may name a wrapper with arguments. IM6's `convert`
    is deliberately not searched: its SVG handling is a different renderer
    with different defaults, and silently rendering through one when the
    box's measurements were taken on the other is this repo's recurring
    failure shape.
    """
    override = os.environ.get("LUCID_MAGICK")
    if override:
        return shlex.split(override)
    found = shutil.which("magick")
    if found:
        return [found]
    raise GraphicsError(
        "magick not found. Card rendering needs ImageMagick 7 with its RSVG "
        "coder (`magick -list format | grep RSVG`), which is what rasterises "
        "the SVG. Install ImageMagick, or set LUCID_MAGICK to a command that "
        "runs it."
    )


def _families(declaration: str) -> list[str]:
    """Split one `font-family` value into the faces it lists, in order."""
    families = []
    for part in declaration.split(","):
        name = part.strip().strip("\"'").strip()
        if name:
            families.append(name)
    return families


def _declarations(style: str, prop_name: str = "font-family") -> list[str]:
    """Every value for `prop_name` in a CSS declaration block."""
    found = []
    for chunk in style.split(";"):
        prop, sep, value = chunk.partition(":")
        if sep and prop.strip().casefold() == prop_name and value.strip():
            found.append(value.strip())
    return found


#: CSS's own `bolder`/`lighter` table (CSS Fonts 4 § relative weights). Kept
#: because the alternative — treating them as "inherit" — is wrong in
#: silence, and this is nine lines rather than a measurement.
#: Read as "inherited at or below `above` becomes `to`".
_RELATIVE_WEIGHT = {
    "bolder": ((300, 400), (500, 700), (1000, 900)),
    "lighter": ((500, 100), (700, 400), (1000, 700)),
}

#: The CSS default. An element that names a family and no weight is drawn at
#: `normal`, and saying so beats reporting the weight as unknown — unknown is
#: reserved for the case below where it genuinely is.
DEFAULT_WEIGHT = 400


def _weight(value: str | None, inherited: int) -> int:
    """One `font-weight` value resolved against the weight it inherits."""
    if value is None:
        return inherited
    text = value.strip().casefold()
    if not text or text == "inherit":
        return inherited
    if text == "normal":
        return 400
    if text == "bold":
        return 700
    if text in _RELATIVE_WEIGHT:
        return next(to for above, to in _RELATIVE_WEIGHT[text] if inherited <= above)
    try:
        return max(1, min(1000, int(float(text))))
    except ValueError:
        return inherited


def _declared_weight(element: ET.Element) -> str | None:
    """The `font-weight` an element states, attribute or inline style."""
    inline = _declarations(element.get("style") or "", "font-weight")
    if inline:
        return inline[-1]
    return element.get("font-weight")


def declared_faces(svg: str) -> list[dict[str, Any]]:
    """Every distinct `(font-family, font-weight)` an SVG asks for.

    Walks the parsed tree rather than pattern-matching the markup, because
    the three places a family can be named — the presentation attribute, an
    inline `style=`, and CSS in a `<style>` element — do not share a syntax,
    and a regex loose enough to catch all three swallows the rest of the tag.

    **A family alone does not say which face gets drawn, and that is the
    whole reason this walks rather than collects.** Both properties inherit,
    so `receipt.svg`'s title — `font-family="…" font-weight="700"` around a
    `<tspan font-weight="400">` — asks for *two* faces of one family, and the
    tspan names no family at all. Reporting per family would answer once, for
    neither of them.

    `weight` is null only for a family named inside a `<style>` rule whose
    own body states no weight: a rule is attached by a selector this does not
    evaluate, so which elements it reaches — and what they inherit — is not
    knowable here. Null is "we did not evaluate the cascade", not `normal`.
    """
    try:
        root = ET.fromstring(svg)
    except ET.ParseError as exc:
        raise GraphicsError(f"not well-formed XML: {exc}") from exc

    seen: dict[tuple[str, int | None], dict[str, Any]] = {}

    def note(declaration: str, weight: int | None) -> None:
        seen.setdefault((declaration, weight), {"declared": declaration, "weight": weight})

    def walk(element: ET.Element, family: str | None, weight: int) -> None:
        if element.tag in ("style", f"{{{_SVG_NS}}}style") and element.text:
            for body in _RULE_BODY.findall(element.text):
                stated = _declarations(body, "font-weight")
                rule_weight = _weight(stated[-1], DEFAULT_WEIGHT) if stated else None
                for declaration in _declarations(body):
                    note(declaration, rule_weight)

        stated_family = element.get("font-family")
        inline = _declarations(element.get("style") or "")
        if inline:
            stated_family = inline[-1]
        stated_weight = _declared_weight(element)

        if stated_family and stated_family.strip():
            family = stated_family.strip()
        weight = _weight(stated_weight, weight)

        # Emitted when the element *states* something, so a `<g>` that sets a
        # family for its children is reported once rather than once per child,
        # and a `<tspan>` that changes only the weight is reported at all.
        if family and (stated_family or stated_weight):
            note(family, weight)

        for child in element:
            walk(child, family, weight)

    walk(root, None, DEFAULT_WEIGHT)
    return list(seen.values())


def declared_fonts(svg: str) -> list[str]:
    """Every distinct `font-family` declaration in an SVG, in document order.

    The families of `declared_faces`, deduped. Kept because "which families
    does this document name" is a question two callers ask without caring
    about weight, and because it is the cheapest well-formedness check there
    is.
    """
    families: dict[str, None] = {}
    for face in declared_faces(svg):
        families.setdefault(face["declared"], None)
    return list(families)


def font_report(svg: str) -> list[dict[str, Any]]:
    """What fontconfig will actually draw for each face `svg` asks for.

    One entry per *declaration and weight* rather than per face, because a
    declaration is a fallback stack and the stack is what decides the
    outcome: `'Card Face', sans-serif` with the first installed is not a
    substitution, and reporting its second entry as missing would be a
    warning about working output.

    **The weight is half the answer.** Two faces of one family report the
    same family name, so `drawn` alone cannot say which got picked — `style`
    is what separates SemiBold from Bold, and the weight is what selects it.
    Before this was weight-aware the report was already wrong about a shipped
    template: `receipt.svg`'s title is `font-weight="700"`, librsvg draws
    Bold, and asking fontconfig for the family alone answers SemiBold
    wherever both are installed.

    `available` is tri-state, inherited from `captions.font_match`: True when
    some named face in the stack is installed, False when none is and the
    card will be drawn in whatever fontconfig picks, and None when `fc-match`
    could not be reached at all — "we could not tell" and "the font is not
    here" send someone to different places.
    """
    cache: dict[tuple[str, int | None], dict[str, Any]] = {}

    def match(family: str, weight: int | None) -> dict[str, Any]:
        # Cached for this document only. A process-lifetime cache would go
        # stale against a font installed while lucid is running, and the
        # thing this report exists to catch is a font that is not there.
        if (family, weight) not in cache:
            cache[(family, weight)] = font_match(family, weight=weight)
        return cache[(family, weight)]

    report = []
    for face in declared_faces(svg):
        declaration, weight = face["declared"], face["weight"]
        families = _families(declaration)
        named = [f for f in families if f.casefold() not in GENERIC_FAMILIES]
        matches = [match(f, weight) for f in named]

        installed = next((m for m in matches if m["available"]), None)
        style = None
        if installed is not None:
            available: bool | None = True
            drawn = installed["resolves_to"]
            style = installed["style"]
        elif not named:
            # An all-generic stack asked for no particular face, so nothing
            # was substituted for anything.
            available = True
            generic = match(families[0], weight) if families else None
            drawn = generic["resolves_to"] if generic else None
            style = generic["style"] if generic else None
        elif all(m["available"] is None for m in matches):
            available = None
            drawn = None
        else:
            available = False
            fallback = next((m for m in matches if m["resolves_to"]), None)
            drawn = fallback["resolves_to"] if fallback else None
            style = fallback["style"] if fallback else None

        entry: dict[str, Any] = {
            "declared": declaration,
            "families": families,
            "weight": weight,
            "available": available,
            "drawn": drawn,
            "drawn_style": style,
        }
        if available is False:
            entry["warning"] = (
                f"none of {named!r} is installed — this card will be drawn in "
                f"{drawn!r} without a warning from the renderer, and it renders "
                "pixel-identically either way, so nothing downstream can catch it"
            )
        report.append(entry)
    return report


def render_svg(
    source: Path | str,
    dest: Path | str,
    *,
    width: int | None = None,
    height: int | None = None,
) -> dict[str, Any]:
    """Rasterise `source` to the PNG at `dest`, reporting its fonts.

    `width`/`height` are a *render* size, not a resize: they go before the
    input so librsvg draws at that scale (see this module's docstring), and
    they fit rather than distort, so a size at a different aspect from the
    document's own comes back smaller on one axis. Both must be given
    together — half a size is an aspect assumption, and this is the one
    place that assumption would be silent.

    Omitted, the document renders at its own declared size. That is the
    honest default at this step: which size a card *should* be is the
    project's canvas, which step 3 computes and passes in here.
    """
    src = Path(source).expanduser()
    out = Path(dest).expanduser()
    if not src.is_file():
        raise GraphicsError(f"no SVG to render: {src}")
    if (width is None) != (height is None):
        raise GraphicsError(
            "render_svg takes both width and height or neither — one alone "
            "would have to guess the other from the document's aspect, and "
            "the guess would not be visible in the output"
        )

    # Parsed for its fonts before anything is rendered, so a malformed
    # document is refused with a line number rather than with magick's
    # `RenderRSVGImage` message.
    text = src.read_text(encoding="utf-8", errors="replace")
    fonts = font_report(text)

    command = magick_command()
    command += ["-background", "none"]
    if width is not None and height is not None:
        if width <= 0 or height <= 0:
            raise GraphicsError(f"render size must be positive, got {width}x{height}")
        command += ["-size", f"{width}x{height}"]
    command += [str(src), str(out)]

    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        done = subprocess.run(command, capture_output=True, text=True, timeout=120, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        raise GraphicsError(f"could not run {command[0]}: {exc}") from exc
    if done.returncode != 0:
        detail = (done.stderr or done.stdout or "").strip() or "no output"
        raise GraphicsError(f"magick could not render {src}: {detail}")

    rendered = identify(out)
    return {
        "source": str(src),
        "output": str(out),
        "width": rendered[0],
        "height": rendered[1],
        "requested_size": None if width is None else f"{width}x{height}",
        "size_policy": RENDER_FIT,
        "fonts": fonts,
        "font_warnings": [f["warning"] for f in fonts if "warning" in f],
    }


def identify(image: Path | str) -> tuple[int, int]:
    """The pixel dimensions of a finished raster, read off the file.

    Read back rather than assumed for the reason `mlt.declared_frames`
    exists: `-size` fits, so the size that was asked for and the size that
    landed are different numbers whenever the aspects disagree, and the one
    worth reporting is the one on disk.
    """
    path = Path(image).expanduser()
    command = [*magick_command(), "identify", "-format", "%w %h", str(path)]
    try:
        done = subprocess.run(command, capture_output=True, text=True, timeout=30, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        raise GraphicsError(f"could not run {command[0]}: {exc}") from exc
    if done.returncode != 0:
        detail = (done.stderr or done.stdout or "").strip() or "no output"
        raise GraphicsError(f"magick could not read {path}: {detail}")
    try:
        width, height = (int(n) for n in done.stdout.split()[:2])
    except ValueError as exc:
        raise GraphicsError(f"magick reported no size for {path}: {done.stdout!r}") from exc
    return width, height


# -- templates -------------------------------------------------------------
#
# Step 2 of PLAN.md § Motion graphics and templates. Templates are SVG files
# with `{{slot}}` placeholders filled by string substitution — deliberately
# not a template engine, because the whole vocabulary is "put this text
# there" and a dependency that can branch and loop is a dependency that can
# put logic in a card.
#
# The starter set is the three the Scream assembly actually used, not a
# speculative library, and they reproduce those cards' own design: the
# palette below is sampled from `receipt-scream-1996.png` and its siblings
# rather than invented.

#: Sampled off the real cards, not chosen: paper `(250,245,236)`, ink
#: `(26,23,20)`, amber `(232,161,60)`, muted `(110,99,87)`, faint
#: `(156,152,145)`. Every one is an ordinary slot with this as its default,
#: so a project restyles a card by passing a different value.
PALETTE = {
    "paper": "#faf5ec",
    "ink": "#1a1714",
    "amber": "#e8a13c",
    "muted": "#6e6357",
    "faint": "#9c9891",
}

#: Fallback *stacks* ending in a generic, never a single face. A stack whose
#: first entry is installed is not a substitution, and `font_report` scores it
#: that way — which is the whole reason the report is per declaration. The
#: named faces are ones this box has (wiki `tooling.md` § Fonts); the generic
#: tail is what keeps a card legible on a machine that has neither.
FONTS = {
    "title_font": "'Noto Serif', 'Liberation Serif', serif",
    "body_font": "'Lato', 'Noto Sans', sans-serif",
    "quote_font": "'Noto Serif', 'Liberation Serif', serif",
}

#: The card a template is authored against. Geometry inside a template is in
#: these units — 1920 wide, whatever the canvas aspect makes it tall — so a
#: template renders at any canvas size without rewriting its coordinates.
TEMPLATE_WIDTH = 1920

#: Star geometry, in template units. The ratio is the standard five-point
#: star's; the size is what matches the real cards' rows.
STAR_RADIUS = 42.0
STAR_INNER_RATIO = 0.382
STAR_GAP = 22.0

_PLACEHOLDER = re.compile(r"\{\{(\w+)\}\}")

_TEMPLATE_DIR = Path(__file__).parent / "templates"


def _escape(value: str) -> str:
    """Escape user text for either an attribute or element content.

    `"` is escaped as well as `&<>` because a slot can land inside a
    double-quoted attribute — `font-family="{{title_font}}"` does — and a
    value that closed the attribute early would rewrite the document rather
    than fail. `'` is left alone: nothing here emits single-quoted
    attributes, and CSS font stacks read better with it.
    """
    return escape(value, {'"': "&quot;"})


def _star_points(cx: float, cy: float) -> str:
    """One five-point star as an SVG polygon point list."""
    inner = STAR_RADIUS * STAR_INNER_RATIO
    points = []
    for step in range(10):
        radius = STAR_RADIUS if step % 2 == 0 else inner
        angle = math.radians(-90 + step * 36)
        points.append(f"{cx + radius * math.cos(angle):.2f},{cy + radius * math.sin(angle):.2f}")
    return " ".join(points)


def stars_markup(rating: float, fill: str, *, prefix: str) -> tuple[str, float]:
    """A row of stars for `rating`, anchored at (0, 0), plus its width.

    Rounded to the nearest half, and drawn as filled stars only — no empty
    outlines behind them, which is what the real cards do. A half is the same
    star under a clip rectangle rather than a second hand-drawn path, so the
    two halves cannot drift apart; the clip needs an id, and `prefix` is what
    keeps two rows in one document from sharing one.

    The width comes back because the caller may need to lay something out
    after the row, and a row's width depends on the rating — `comparison`
    below places its arrow that way rather than at a guessed offset.
    """
    halves = max(0, round(float(rating) * 2))
    full, half = divmod(halves, 2)
    step = STAR_RADIUS * 2 + STAR_GAP

    parts = []
    for index in range(full):
        parts.append(
            f'<polygon points="{_star_points(STAR_RADIUS + index * step, 0)}" fill="{fill}"/>'
        )
    if half:
        cx = STAR_RADIUS + full * step
        clip = f"{prefix}-half"
        parts.append(
            f'<clipPath id="{clip}">'
            f'<rect x="{cx - STAR_RADIUS:.2f}" y="{-STAR_RADIUS:.2f}" '
            f'width="{STAR_RADIUS:.2f}" height="{STAR_RADIUS * 2:.2f}"/>'
            f"</clipPath>"
            f'<polygon points="{_star_points(cx, 0)}" fill="{fill}" clip-path="url(#{clip})"/>'
        )

    count = full + half
    width = 0.0 if count == 0 else count * step - STAR_GAP
    return "".join(parts), width


def comparison_markup(before: float, after: float, muted: str, amber: str) -> str:
    """`before` stars, an arrow, then `after` stars — the re-rate row.

    Laid out left to right off the measured width of the first row, because
    the two ratings are what decide where the arrow goes. A fixed offset
    would collide the moment someone re-rates from four stars rather than
    from two.
    """
    gap = 78.0
    arrow_length = 118.0

    left, left_width = stars_markup(before, muted, prefix="before")
    arrow_x = left_width + gap
    right, _ = stars_markup(after, amber, prefix="after")
    right_x = arrow_x + arrow_length + gap

    head = arrow_x + arrow_length
    arrow = (
        f'<g fill="none" stroke="{amber}" stroke-width="11" stroke-linecap="round" '
        f'stroke-linejoin="round">'
        f'<path d="M {arrow_x:.2f} 0 L {head:.2f} 0"/>'
        f'<path d="M {head - 34:.2f} -26 L {head:.2f} 0 L {head - 34:.2f} 26"/>'
        f"</g>"
    )
    return f"{left}{arrow}<g transform=\"translate({right_x:.2f}, 0)\">{right}</g>"


#: The three ink levels one quote carries, as `(weight, palette slot,
#: fill-opacity)`. **Read off the real cards rather than invented** —
#: `make_scream_cards.py`'s own `STYLES` is `key: (zb600, INK, None)`,
#: `dim: (zb600, INK, 0.42)`, `em: (zb700, AMBER, None)`, and each of the
#: three was sampled back off a raster to confirm librsvg reproduces it
#: (PLAN.md § The emphasis-capable quote slot, finding 1).
#:
#: Note what `em` does: it is a *weight* change as well as a colour, which is
#: the whole reason the font report had to learn to read `font-weight` before
#: this landed. And `dim` is ink at 0.42 rather than a flat grey, so it stays
#: right when the paper is not cream.
RUN_STYLES: dict[str, tuple[int, str, float | None]] = {
    "key": (600, "ink", None),
    "dim": (600, "ink", 0.42),
    "em": (700, "amber", None),
}

#: Unmarked text. `key` rather than `dim` because plain prose is the primary
#: reading and de-emphasis is the marked case, whichever happens to be more
#: frequent in one film's receipts.
RUN_DEFAULT = "key"

_RUN_MARKER = re.compile(r"\[(/?)(" + "|".join(RUN_STYLES) + r")\]")


def parse_runs(value: str) -> list[list[tuple[str, str]]]:
    """Split a marked-up slot value into lines of `(text, level)` runs.

    The vocabulary is `[em]…[/em]`, `[dim]…[/dim]`, `[key]…[/key]`, and
    unmarked text is `RUN_DEFAULT`. **Markers rather than JSON runs** because
    the value arrives from a CLI argument and an MCP string, where JSON is
    hostile to type and hostile to quote.

    `[[` is the escape and yields a literal `[`, which a marker syntax owes
    the moment it claims a character prose already uses. A `[` that does not
    begin a known marker is left alone — `[sic]` is not markup — so the
    escape is only needed to write a literal `[em]`.

    Runs nest, and the innermost wins: `[dim]a [em]b[/em] c[/dim]` is a dim
    run, an em run, and a dim run. They also span line breaks, so a marked
    paragraph does not have to be re-marked on every line.

    Refused rather than guessed: a close with no matching open, and a run
    still open at the end of the value. Both are cases where the drawn card
    would look deliberate and be wrong.
    """
    lines: list[list[tuple[str, str]]] = [[]]
    stack: list[str] = []
    buf: list[str] = []
    text = str(value)

    def flush() -> None:
        if buf:
            lines[-1].append(("".join(buf), stack[-1] if stack else RUN_DEFAULT))
            buf.clear()

    index = 0
    while index < len(text):
        char = text[index]
        if char == "\n":
            flush()
            lines.append([])
            index += 1
            continue
        if char == "[":
            if text.startswith("[[", index):
                buf.append("[")
                index += 2
                continue
            marker = _RUN_MARKER.match(text, index)
            if marker:
                closing, level = marker.group(1), marker.group(2)
                flush()
                if closing:
                    if not stack or stack[-1] != level:
                        open_now = f"{stack[-1]!r} is open" if stack else "nothing is open"
                        raise GraphicsError(
                            f"[/{level}] at character {index} closes a run that is not "
                            f"open — {open_now}. Write [[ for a literal '['."
                        )
                    stack.pop()
                else:
                    stack.append(level)
                index = marker.end()
                continue
        buf.append(char)
        index += 1
    flush()

    if stack:
        raise GraphicsError(
            f"{stack[-1]!r} is still open at the end of the value — a run that "
            f"never closes would draw the rest of the card in it. Close it with "
            f"[/{stack[-1]}], or write [[ for a literal '['."
        )
    return lines


def _runs_markup(
    value: str, *, x: float, line_height: float, colours: dict[str, str]
) -> str:
    """A multi-line, multi-ink slot as one `<tspan>` per line per run.

    **Lines are the caller's, never guessed.** SVG has no automatic wrapping,
    and a wrap computed from a character count is a wrap that overflows the
    frame silently on the first line of wide glyphs — the shape of failure
    this repo keeps finding. So a newline in the value is a line break and
    nothing else breaks. (A wrap *measured* through this module's own coder
    is a different thing and lands in its own step.)

    `xml:space="preserve"` is not decoration, and it is measured: splitting
    one line into per-run `<tspan>`s collapses the whitespace at every chunk
    boundary, so "the [em]perfect[/em] horror" renders as "theperfecthorror"
    — 19px narrower at 48px, at exit 0, looking like a deliberate ligature
    rather than a bug. It is set once per line because `xml:space` inherits.
    """
    markup = []
    for index, runs in enumerate(parse_runs(value)):
        inner = "".join(
            f"<tspan{_run_attrs(level, colours)}>{_escape(text)}</tspan>"
            for text, level in runs
        )
        dy = 0 if index == 0 else line_height
        markup.append(f'<tspan x="{x:g}" dy="{dy:g}" xml:space="preserve">{inner}</tspan>')
    return "".join(markup)


def _run_attrs(level: str, colours: dict[str, str]) -> str:
    """One run's ink, stated in full rather than inherited.

    Every run names its own weight and fill even when they match the
    element's, so a run's look does not depend on what the template happens
    to set around it — and so the font report can see the weight.
    """
    weight, slot, opacity = RUN_STYLES[level]
    attrs = f' font-weight="{weight}" fill="{_escape(str(colours[slot]))}"'
    if opacity is not None:
        attrs += f' fill-opacity="{opacity:g}"'
    return attrs


#: What each template asks for. `placed` slots appear in the SVG as
#: `{{name}}`; the rest feed a `derived` entry, which is markup lucid
#: generates and the template positions. Descriptions are the tool surface an
#: agent reads, so they say what the field *is*, not what type it has.
TEMPLATES: dict[str, dict[str, Any]] = {
    "receipt": {
        "description": "A film, its rating out of five, when it was watched, and the note written then.",
        "slots": {
            "title": {"description": "the film's title"},
            "year": {"description": "its release year, drawn in brackets after the title"},
            "rating": {
                "kind": "rating",
                "placed": False,
                "description": "stars out of five, to the nearest half (e.g. 4.5)",
            },
            "date_line": {"default": "", "description": "the line under the stars, e.g. 'watched 20 May 2021'"},
            "quote": {
                "kind": "runs",
                "x": 140,
                "line_height": 58,
                "default": "",
                "description": (
                    "the note itself. A newline is a line break and nothing else wraps. "
                    "Mark a fragment with [em]…[/em] for the amber emphasis or "
                    "[dim]…[/dim] for the dimmed ink; unmarked text is full ink. "
                    "Write [[ for a literal '['."
                ),
            },
            "mark": {"default": "", "description": "a wordmark for the bottom right corner, if any"},
        },
        "derived": {"stars": ("stars", "rating", "amber")},
    },
    "reveal": {
        "description": "A title card on ink, with a footnote — the shape used for each sequel's reveal.",
        "slots": {
            "title": {"description": "the title, set large and centred"},
            "note": {"default": "", "description": "the footnote under it, after an amber asterisk"},
            "year": {"default": "", "description": "the year, drawn small in the bottom left"},
            "mark": {"default": "", "description": "a wordmark for the bottom right corner, if any"},
        },
        "derived": {},
    },
    "rerate": {
        "description": "A rating that changed: the old stars, an arrow, the new ones.",
        "slots": {
            "title": {"description": "the film's title"},
            "year": {"description": "its release year, drawn in brackets after the title"},
            "before": {
                "kind": "rating",
                "placed": False,
                "description": "the old rating out of five, to the nearest half",
            },
            "after": {
                "kind": "rating",
                "placed": False,
                "description": "the new rating out of five, to the nearest half",
            },
            "date_line": {"default": "", "description": "the line under the row, e.g. 're-rated 28 Feb 2026'"},
            "mark": {"default": "", "description": "a wordmark for the bottom right corner, if any"},
        },
        "derived": {"comparison": ("comparison", "before", "after")},
    },
}

#: Slots every template gets: the palette, the font stacks, and the geometry
#: lucid computes from the canvas. Style slots are overridable; the geometry
#: ones are not, because they are the canvas the caller already chose.
STYLE_SLOTS = {**PALETTE, **FONTS}
RESERVED_SLOTS = frozenset({"width", "height", "view_height", "mid_y", "note_y", "foot_y"})


def template_path(name: str) -> Path:
    path = _TEMPLATE_DIR / f"{name}.svg"
    if name not in TEMPLATES or not path.is_file():
        known = ", ".join(sorted(TEMPLATES)) or "none"
        raise GraphicsError(f"no template named {name!r} (there are: {known})")
    return path


def template_slots(name: str) -> dict[str, dict[str, Any]]:
    """Every slot `name` accepts, its default, and what it is for.

    Read against the template on disk rather than from the manifest alone:
    the placeholders in the file are the truth about what gets filled, and a
    manifest that has drifted from them is how a card ends up shipping with
    `{{year}}` printed on its face.
    """
    path = template_path(name)
    spec = TEMPLATES[name]
    found = set(_PLACEHOLDER.findall(path.read_text(encoding="utf-8")))

    placed = {n for n, s in spec["slots"].items() if s.get("placed", True)}
    expected = placed | set(spec["derived"]) | set(STYLE_SLOTS) | RESERVED_SLOTS
    if found - expected:
        raise GraphicsError(
            f"template {name!r} has placeholders nothing fills: "
            f"{sorted(found - expected)} — the manifest and the SVG disagree"
        )
    unplaced = (placed | set(spec["derived"])) - found
    if unplaced:
        raise GraphicsError(
            f"template {name!r} declares slots its SVG never places: "
            f"{sorted(unplaced)} — the manifest and the SVG disagree"
        )

    slots = {}
    for slot, meta in spec["slots"].items():
        slots[slot] = {
            "description": meta["description"],
            "kind": meta.get("kind", "text"),
            "required": "default" not in meta,
            "default": meta.get("default"),
        }
    for slot, value in STYLE_SLOTS.items():
        slots[slot] = {
            "description": "style; overridable",
            "kind": "text",
            "required": False,
            "default": value,
        }
    return slots


def templates() -> list[dict[str, Any]]:
    """Every template lucid ships, with its slots.

    Content and style are reported separately even though `fill_template`
    takes them in one dict. Both front ends sort their JSON, so a single map
    puts `amber` and `body_font` above `title` — burying the three fields a
    caller has to supply under twelve it can ignore.
    """
    listing = []
    for name in sorted(TEMPLATES):
        slots = template_slots(name)
        listing.append(
            {
                "template": name,
                "description": TEMPLATES[name]["description"],
                "slots": {s: v for s, v in slots.items() if s not in STYLE_SLOTS},
                "style": {s: v for s, v in slots.items() if s in STYLE_SLOTS},
            }
        )
    return listing


def _rating(slot: str, value: Any) -> float:
    try:
        rating = float(value)
    except (TypeError, ValueError):
        raise GraphicsError(f"slot {slot!r} is a rating out of five, not {value!r}") from None
    if not 0 <= rating <= 5:
        raise GraphicsError(f"slot {slot!r} is a rating out of five, and {rating} is outside it")
    return rating


def fill_template(
    name: str, values: dict[str, Any], *, width: int = 1920, height: int = 1080
) -> str:
    """Fill `name`'s slots with `values`, returning the SVG to write.

    Every user value is escaped; the only unescaped markup is what lucid
    generates itself for a `derived` slot. That split is the whole security
    story of a string-substitution template, and it is why a rating is parsed
    as a number here rather than pasted through as text.

    A missing required slot and an unknown slot are both refused. A card
    silently missing its year is the failure this exists to make loud — the
    render would still succeed and still be wrong.

    `width`/`height` are the canvas. Geometry inside a template is in
    1920-wide units and the viewBox is written to match the canvas aspect, so
    the same template renders at any size without pillarboxing.
    """
    path = template_path(name)
    spec = TEMPLATES[name]
    slots = template_slots(name)

    unknown = set(values) - set(slots)
    if unknown:
        raise GraphicsError(
            f"template {name!r} has no slot {sorted(unknown)} (it takes: {sorted(slots)})"
        )
    missing = [s for s, meta in slots.items() if meta["required"] and s not in values]
    if missing:
        raise GraphicsError(f"template {name!r} needs {sorted(missing)}, which nothing supplied")
    if width <= 0 or height <= 0:
        raise GraphicsError(f"canvas must be positive, got {width}x{height}")

    resolved = {s: values.get(s, meta["default"]) for s, meta in slots.items()}

    view_height = round(TEMPLATE_WIDTH * height / width)
    filled: dict[str, str] = {
        "width": str(width),
        "height": str(height),
        "view_height": str(view_height),
        "mid_y": str(round(view_height * 0.44)),
        "note_y": str(round(view_height * 0.44) + 130),
        "foot_y": str(view_height - 110),
    }
    for slot, meta in slots.items():
        if meta["kind"] == "rating" or not spec["slots"].get(slot, {}).get("placed", True):
            continue
        if meta["kind"] == "runs":
            declared = spec["slots"][slot]
            filled[slot] = _runs_markup(
                str(resolved[slot]),
                x=declared["x"],
                line_height=declared["line_height"],
                colours={name: str(resolved[name]) for name in PALETTE},
            )
        else:
            filled[slot] = _escape(str(resolved[slot]))

    for slot, (builder, *sources) in spec["derived"].items():
        if builder == "stars":
            source, colour = sources
            markup, _ = stars_markup(
                _rating(source, resolved[source]), resolved[colour], prefix=slot
            )
            filled[slot] = markup
        elif builder == "comparison":
            before, after = sources
            filled[slot] = comparison_markup(
                _rating(before, resolved[before]),
                _rating(after, resolved[after]),
                resolved["muted"],
                resolved["amber"],
            )
        else:  # pragma: no cover - a builder name only this module writes
            raise GraphicsError(f"template {name!r} names an unknown builder {builder!r}")

    def substitute(match: re.Match[str]) -> str:
        return filled[match.group(1)]

    return _PLACEHOLDER.sub(substitute, path.read_text(encoding="utf-8"))
