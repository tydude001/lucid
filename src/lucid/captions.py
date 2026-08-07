"""Word-timed captions: ASS out, optionally burned in with ffmpeg.

The one thing to get right here is which clock the captions are on. A
transcript indexes the **source** recording and never renumbers (see
`transcript.py`), but a caption has to fire when the word is *heard*, which is
timeline time — and by the time captions are wanted the timeline is an
accumulation of cuts. So every word is mapped through `Edit.timeline_span`,
and a word that has been cut is simply absent from the output rather than
emitted at a stale time.

That mapping is also why captions are generated from the project rather than
from the whisper JSON directly: the JSON alone cannot know what was removed.

ASS rather than SRT, for two reasons that both matter downstream: it carries
styling (Kdenlive and libass both honour it, SRT forces the renderer to
invent one), and it has `\\k` karaoke tags, which is the only subtitle format
that can express per-word timing *within* a displayed line. A cue is a line of
several words; the `\\k` tags inside it are what makes it word-timed rather
than line-timed.

Burn-in is `ffmpeg -vf ass=…`. It is opt-in, because on this box the edit
leaves through Kdenlive as a project rather than a render (PLAN.md), and a
sidecar `.ass` stays editable there while burned pixels do not.
"""

from __future__ import annotations

import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from lucid.timeline import Edit
from lucid.transcript import Transcript

FFMPEG = "ffmpeg"

#: Whisper occasionally emits a word with start == end. A zero-length interval
#: overlaps no segment, so it would vanish; widen it to something a mapping can
#: catch. One millisecond is far below the 33ms frame grid it will land on.
MIN_WORD = 0.001

#: PlayResX/Y is the coordinate space a style's sizes and margins are quoted
#: in, and libass scales it to whatever it is actually drawing on. So it is a
#: *reference* canvas, not an output resolution — writing the media's real
#: dimensions here would make a 64pt caption fill a 240-line clip and vanish on
#: a 4K one. Every preset below is authored against this height.
REFERENCE_HEIGHT = 1080

DEFAULT_RESOLUTION = (1920, REFERENCE_HEIGHT)


def canvas(width: int | None, height: int | None) -> tuple[int, int]:
    """A reference canvas matching the media's aspect ratio.

    Height is fixed so font sizes mean the same thing everywhere; width follows
    the aspect ratio, because libass scales the two axes independently and a
    16:9 reference over 9:16 footage stretches the glyphs.
    """
    if not width or not height:
        return DEFAULT_RESOLUTION
    return max(1, round(REFERENCE_HEIGHT * (width / height))), REFERENCE_HEIGHT


class CaptionError(Exception):
    """Raised when captions cannot be built, written, or burned in."""


# -- cues ----------------------------------------------------------------


@dataclass(frozen=True)
class CueWord:
    """One word, in *timeline* seconds."""

    text: str
    start: float
    end: float

    def as_dict(self) -> dict[str, Any]:
        return {"text": self.text, "start": self.start, "end": self.end}


@dataclass(frozen=True)
class Cue:
    """One displayed line: several words, shown as a unit."""

    words: tuple[CueWord, ...]
    #: When the line leaves the screen. Not `words[-1].end` — see `_hold`.
    end: float

    @property
    def start(self) -> float:
        return self.words[0].start

    @property
    def text(self) -> str:
        return " ".join(w.text for w in self.words)

    def as_dict(self) -> dict[str, Any]:
        return {
            "start": self.start,
            "end": self.end,
            "text": self.text,
            "words": [w.as_dict() for w in self.words],
        }


#: A word ending a sentence, allowing for a closing quote or bracket after the
#: punctuation. Breaking cues here is what stops a caption running across the
#: full stop, which reads worse than a short line.
_SENTENCE_END = re.compile(r"[.!?…][\"'’”)\]]*$")


def place(edit: Edit, transcripts: dict[str, Transcript]) -> tuple[list[CueWord], int]:
    """Map every transcribed word onto the timeline, dropping what was cut.

    Returns the surviving words in timeline order, and how many were dropped —
    the count is reported rather than swallowed, because "my captions are
    missing a sentence" and "I cut that sentence" look identical otherwise.
    """
    placed: list[CueWord] = []
    dropped = 0
    for clip_id, transcript in transcripts.items():
        for word in transcript.words:
            span = edit.timeline_span(clip_id, word.start, max(word.end, word.start + MIN_WORD))
            if span is None:
                dropped += 1
                continue
            placed.append(CueWord(text=word.text, start=span[0], end=span[1]))

    # Several clips can contribute, and their words interleave only by where
    # they sit on the timeline — source order says nothing across clips.
    placed.sort(key=lambda w: (w.start, w.end))
    return placed, dropped


def group(
    words: list[CueWord],
    *,
    max_words: int = 7,
    max_gap: float = 0.7,
    max_duration: float = 6.0,
    hold: float = 0.3,
) -> list[Cue]:
    """Gather words into displayable lines.

    Every break rule is measured in *timeline* time, which is the only clock
    the viewer has. That is deliberate and has a consequence worth knowing:
    two words seconds apart in the recording but adjacent after a cut belong
    to one cue, because that is how they now play.
    """
    if max_words < 1:
        raise CaptionError("max_words must be at least 1")

    lines: list[list[CueWord]] = []
    current: list[CueWord] = []
    for word in words:
        if current and (
            len(current) >= max_words
            or word.start - current[-1].end > max_gap
            or word.end - current[0].start > max_duration
            or _SENTENCE_END.search(current[-1].text) is not None
        ):
            lines.append(current)
            current = []
        current.append(word)
    if current:
        lines.append(current)

    return [
        Cue(words=tuple(line), end=_hold(line, lines[n + 1] if n + 1 < len(lines) else None, hold))
        for n, line in enumerate(lines)
    ]


def _hold(line: list[CueWord], following: list[CueWord] | None, hold: float) -> float:
    """Keep a line up briefly after its last word, without overlapping the next.

    A cue that vanishes on the final consonant is unreadable, but two cues on
    screen at once is worse — libass will draw both, stacked.
    """
    end = line[-1].end + max(0.0, hold)
    return min(end, following[0].start) if following else end


# -- styling -------------------------------------------------------------


@dataclass(frozen=True)
class Preset:
    """One caption look. Colours are ASS `&HAABBGGRR` — alpha first, then BGR."""

    font: str
    size: int
    #: In karaoke, `primary` is the colour a word turns *as it is spoken* and
    #: `secondary` is how it sits before then. With the two equal, `\\k` tags
    #: are still emitted but nothing visibly changes.
    primary: str
    secondary: str
    outline_colour: str
    back: str
    bold: int
    #: 1 = outline + drop shadow, 3 = opaque box behind the text.
    border_style: int
    outline: float
    shadow: float
    #: numpad layout: 2 is bottom-centre, 8 top-centre.
    alignment: int
    margin_v: int
    karaoke: bool


#: Deliberately small (PLAN.md). DejaVu Sans is chosen because it ships with
#: essentially every Linux distribution — libass silently substitutes a missing
#: font, so a fancier default would render differently per machine.
PRESETS: dict[str, Preset] = {
    "clean": Preset(
        font="DejaVu Sans",
        size=64,
        primary="&H00FFFFFF",
        secondary="&H00FFFFFF",
        outline_colour="&H00000000",
        back="&H80000000",
        bold=-1,
        border_style=1,
        outline=3.0,
        shadow=0.0,
        alignment=2,
        margin_v=80,
        karaoke=False,
    ),
    "karaoke": Preset(
        font="DejaVu Sans",
        size=64,
        primary="&H0000C8FF",
        secondary="&H00FFFFFF",
        outline_colour="&H00000000",
        back="&H80000000",
        bold=-1,
        border_style=1,
        outline=3.0,
        shadow=0.0,
        alignment=2,
        margin_v=80,
        karaoke=True,
    ),
    "boxed": Preset(
        font="DejaVu Sans",
        size=56,
        primary="&H00FFFFFF",
        secondary="&H00FFFFFF",
        outline_colour="&HB0000000",
        back="&HB0000000",
        bold=0,
        border_style=3,
        outline=8.0,
        shadow=0.0,
        alignment=2,
        margin_v=90,
        karaoke=False,
    ),
}


def preset(name: str) -> Preset:
    try:
        return PRESETS[name]
    except KeyError:
        raise CaptionError(
            f"unknown caption preset {name!r} — available: {', '.join(sorted(PRESETS))}"
        ) from None


# -- ASS -----------------------------------------------------------------


def _ass_time(seconds: float) -> str:
    """`H:MM:SS.cc` — ASS keeps centiseconds, and only one hour digit."""
    total = max(0, round(max(0.0, seconds) * 100))
    hours, total = divmod(total, 360_000)
    minutes, total = divmod(total, 6_000)
    secs, centis = divmod(total, 100)
    return f"{hours}:{minutes:02d}:{secs:02d}.{centis:02d}"


#: `{` and `}` open and close override blocks and `\` starts a tag, so a word
#: containing one would be swallowed as markup. Transliterate rather than
#: escape: ASS has no escape for these inside dialogue text.
_UNSAFE = str.maketrans({"{": "(", "}": ")", "\\": "/"})


def _escape(text: str) -> str:
    return " ".join(text.translate(_UNSAFE).split())


def _dialogue_text(cue: Cue, style: Preset) -> str:
    if not style.karaoke:
        return _escape(cue.text)

    # Each \k is the duration of its own word *plus the gap before it*, so the
    # highlight stays locked to the audio instead of drifting forward by the
    # accumulated silence between words.
    parts = []
    cursor = cue.start
    for word in cue.words:
        centis = max(0, round((word.end - cursor) * 100))
        parts.append(f"{{\\k{centis}}}{_escape(word.text)}")
        cursor = word.end
    return " ".join(parts)


def to_ass(
    cues: list[Cue],
    *,
    style: Preset,
    resolution: tuple[int, int] = DEFAULT_RESOLUTION,
    title: str = "lucid",
) -> str:
    """Render cues as an ASS subtitle file."""
    width, height = resolution
    lines = [
        "[Script Info]",
        f"Title: {title}",
        "ScriptType: v4.00+",
        f"PlayResX: {width}",
        f"PlayResY: {height}",
        "WrapStyle: 0",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        (
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
            "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, "
            "ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, "
            "MarginL, MarginR, MarginV, Encoding"
        ),
        (
            f"Style: lucid,{style.font},{style.size},{style.primary},{style.secondary},"
            f"{style.outline_colour},{style.back},{style.bold},0,0,0,100,100,0,0,"
            f"{style.border_style},{style.outline:g},{style.shadow:g},{style.alignment},"
            f"{round(width * 0.08)},{round(width * 0.08)},{style.margin_v},1"
        ),
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    lines.extend(
        f"Dialogue: 0,{_ass_time(cue.start)},{_ass_time(cue.end)},lucid,,0,0,0,,"
        f"{_dialogue_text(cue, style)}"
        for cue in cues
    )
    return "\n".join(lines) + "\n"


# -- burn-in -------------------------------------------------------------


def burn(video: Path | str, subtitles: Path | str, output: Path | str) -> Path:
    """Burn `subtitles` into `video` with ffmpeg, writing `output`.

    The subtitle file is staged into a temporary directory under a fixed name
    and ffmpeg is run from there. That is not tidiness: the `ass=` filter
    argument lives inside a filtergraph, where `:`, `,`, `'` and `\\` all have
    meaning, and project paths on this box contain spaces and punctuation.
    Staging sidesteps the escaping problem instead of trying to win it.
    """
    source = Path(video).expanduser().resolve()
    if not source.exists():
        raise CaptionError(f"no video to burn captions onto: {source}")

    destination = Path(output).expanduser()
    destination.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="lucid-ass-") as tmp:
        staged = Path(tmp) / "lucid.ass"
        staged.write_text(Path(subtitles).read_text(encoding="utf-8"), encoding="utf-8")
        cmd = [
            FFMPEG,
            "-y",
            "-i",
            str(source),
            "-vf",
            "ass=lucid.ass",
            "-c:a",
            "copy",
            str(destination.resolve()),
        ]
        try:
            subprocess.run(cmd, cwd=tmp, capture_output=True, text=True, check=True)
        except FileNotFoundError as exc:
            raise CaptionError(f"{FFMPEG} not found on PATH") from exc
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or exc.stdout or "").strip().splitlines()
            raise CaptionError(
                "ffmpeg failed burning in captions:\n" + "\n".join(detail[-12:])
            ) from exc

    return destination
