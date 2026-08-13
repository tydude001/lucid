# The vendored caption face

`src/lucid/web/FONTS.md` ships three typefaces for the *browser*. This
directory ships one for the *renderers* — libass, and librsvg through
`magick` — and the two deliveries have nothing in common but the word "font".
A `woff2` beside `app.css` does not put a face where `fc-match`, libass or
librsvg can see it (PLAN.md § A default font), so neither directory can stand
in for the other.

| file | family | role | licence |
|---|---|---|---|
| `Outfit[wght].ttf` | Outfit (variable, 100–900) | `captions.CAPTION_FONT` — the caption default every `PRESETS` entry names | OFL-1.1 — `OFL-Outfit.txt` |

## Why one file and not the brand set

Captions are the only exposed surface. libass's `\fn` takes exactly one family
name, so a caption style that names an absent face has nowhere to fall back to.
Card templates use CSS fallback *stacks* ending in a generic
(`graphics.py`'s `title_font`/`body_font`/`quote_font`), which is the
SVG-native survival trick, so they degrade rather than vanish. Zilla Slab is
the brand's other face and belongs to the channel preset pack
(PLAN.md § The completion queue), not here — nothing lucid draws asks for it.

## Provenance

Byte-identical to `Branding/Fonts/Outfit[wght].ttf` on the NAS, which
goodsometimes `branding.md` § Type names as canonical, together with its
licence. Both faces there are SIL OFL, which is what makes vendoring the file
rather than naming the family legal as well as sensible.

`~/.local/share/fonts/Outfit[wght].ttf` on this box has the same md5
(`e31a3aa5fce3366bcadb8e9027f26178`) but was fetched incidentally, by
goodsometimes' own brand-art tooling, months before captions named the family.
That is the failure this directory exists to close: the caption default
resolved on this machine **by coincidence**, and on a fresh box it would have
resolved to whatever fontconfig substitutes, silently, with every check still
clean.

## Installing it where fontconfig looks

`fonts.install()` copies this file into `$XDG_DATA_HOME/fonts`
(`~/.local/share/fonts` by default), which `/etc/fonts/fonts.conf` puts on the
search path via `<dir prefix="xdg">fonts</dir>`. It is idempotent and compares
by content, so a box that already has the face is left alone.

## Settling which face actually drew

Never by `fc-match`. It answers "is the family present", and libass asks
something else — on this box its first pick for `Noto Sans` is a Nerd Font
symbol face that only reaches the real one by failing to find a Latin glyph
(HISTORY.md § The approvals round, answered).

There are **two** flavours of wrong here and they do not look like each other,
which is why the probe compares against the machine's own substitute rather
than against any particular wrong answer. Traced through `ffmpeg -v verbose`:
an *absent* family and `DejaVu Sans` both primary-pick `NotoSansArabic-Bold`,
fail the glyph, and fall back to `NotoSans-Bold.ttf`; the literal `Noto Sans`
primary-picks the Nerd Font face, fails the same glyph, and falls back to the
same file. All three draw their Latin glyphs out of one face — the pixels that
differ are the **space advance**, still supplied by whichever primary was
picked. A probe scored against "does it differ from font X" would therefore
score two wrong answers as one right one.

`fonts.probe()` burns the same line twice, once under the family and once
under a family that cannot exist, and compares the pixels. Identical renders
mean the name is not drawing, whatever `fc-match` says. That calibration is
the whole point of the second burn: it needs no golden image, so it cannot
rot, and it is the one comparison that distinguishes "substituted" from
"resolved" without knowing in advance what the substitute would look like.
