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

import os
import re
import shlex
import shutil
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

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


def _declarations(style: str) -> list[str]:
    """Every `font-family` value in a CSS declaration block."""
    found = []
    for chunk in style.split(";"):
        prop, sep, value = chunk.partition(":")
        if sep and prop.strip().casefold() == "font-family" and value.strip():
            found.append(value.strip())
    return found


def declared_fonts(svg: str) -> list[str]:
    """Every distinct `font-family` declaration in an SVG, in document order.

    Walks the parsed tree rather than pattern-matching the markup, because
    the three places a family can be named — the presentation attribute, an
    inline `style=`, and CSS in a `<style>` element — do not share a syntax,
    and a regex loose enough to catch all three swallows the rest of the tag.
    """
    try:
        root = ET.fromstring(svg)
    except ET.ParseError as exc:
        raise GraphicsError(f"not well-formed XML: {exc}") from exc

    seen: dict[str, None] = {}
    for element in root.iter():
        attribute = element.get("font-family")
        if attribute and attribute.strip():
            seen.setdefault(attribute.strip(), None)
        for declaration in _declarations(element.get("style") or ""):
            seen.setdefault(declaration, None)
        if element.tag in ("style", f"{{{_SVG_NS}}}style") and element.text:
            for body in _RULE_BODY.findall(element.text):
                for declaration in _declarations(body):
                    seen.setdefault(declaration, None)
    return list(seen)


def font_report(svg: str) -> list[dict[str, Any]]:
    """What fontconfig will actually draw for each `font-family` in `svg`.

    One entry per *declaration* rather than per face, because a declaration
    is a fallback stack and the stack is what decides the outcome:
    `'Card Face', sans-serif` with the first installed is not a substitution,
    and reporting its second entry as missing would be a warning about
    working output.

    `available` is tri-state, inherited from `captions.font_match`: True when
    some named face in the stack is installed, False when none is and the
    card will be drawn in whatever fontconfig picks, and None when `fc-match`
    could not be reached at all — "we could not tell" and "the font is not
    here" send someone to different places.
    """
    report = []
    for declaration in declared_fonts(svg):
        families = _families(declaration)
        named = [f for f in families if f.casefold() not in GENERIC_FAMILIES]
        matches = [font_match(f) for f in named]

        installed = next((m for m in matches if m["available"]), None)
        if installed is not None:
            available: bool | None = True
            drawn = installed["resolves_to"]
        elif not named:
            # An all-generic stack asked for no particular face, so nothing
            # was substituted for anything.
            available = True
            drawn = font_match(families[0])["resolves_to"] if families else None
        elif all(m["available"] is None for m in matches):
            available = None
            drawn = None
        else:
            available = False
            drawn = next((m["resolves_to"] for m in matches if m["resolves_to"]), None)

        entry: dict[str, Any] = {
            "declared": declaration,
            "families": families,
            "available": available,
            "drawn": drawn,
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
