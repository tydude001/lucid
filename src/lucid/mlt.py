"""Writing MLT — step 4 of the layered timeline, the multi-source path only.

Single-source export still goes through `auto-editor --export kdenlive` and
nothing here touches it. This file exists because on the multi-source path
auto-editor writes nothing at all: its kdenlive exporter **refuses, exit 2**,
and its renderer degrades a two-`src` timeline to 720x576 with **exit 0**
(CLAUDE.md; HISTORY.md § The multi-track costing spike). `melt` has no
source-count gate — 23 distinct sources rendered 1920x1080 from the real
Scream assembly — so the picture lane is rendered by melt, and somebody has to
hand melt a document. That somebody is now this module.

**Generated, never mutated.** The rule "lucid never writes MLT" is narrowed
rather than dropped (PLAN.md § What this does to "lucid never writes MLT"):
every document here is built from scratch out of the `Edit` plus the cue
table, so there is still no in-place MLT surgery anywhere in lucid, and the
document is disposable — rebuild it, don't patch it.

Generating means owning MLT's two sharp edges, both of which produce a wrong
render rather than an error:

- **`<blank>`.** A playlist shorter than its neighbours pads with blank, which
  is runtime every cue downstream of it is blind to — the cut positions still
  say what they said and the picture is now late. No *lane* here ever emits a
  `<blank>`: both playlists are contiguous by construction, and `document()`
  refuses a picture lane whose frames do not sum to exactly the audio's. The
  one place a blank is written is a **split pane's** overlay playlist, where
  it is the point rather than an accident — the pane covers the stretches its
  clip is split over and nothing else, and a blank on an overlay track shows
  the track below. That is the opposite case from the one this rule guards:
  the danger is a lane *silently* becoming short, and a pane track is short
  deliberately and by the same frame arithmetic as the lane it sits over,
  which `document()` checks.
- **The declared lengths.** melt renders to the *longest* declared length in
  the document, not to the playlist, so a stale one pads the render out with
  a frozen frame and still exits 0. There are four of them (the two track
  tractors' `out`, the sequence tractor's `out`, and the black background
  producer's `length`), plus the outer project tractor. They are all written
  from one number and then read back and checked — `declared_frames()` is the
  assertion PLAN.md asked for in place of a comment.

Positions are **frame integers, not timecode**. MLT parses a bare integer as a
frame position and `HH:MM:SS.mmm` as a clock time; the clock form is what
Kdenlive and auto-editor write, and it is the form that cost auto-editor a
frame — millisecond text cannot name a 1/29.97 s edge exactly. Frames can, so
frames are what this writes. And `out` is **frame-inclusive**: an entry of
`frames` frames starting at `src_in` ends at `src_in + frames - 1`, which is
the arithmetic `KNOWN_TAIL_FRAME` records auto-editor getting wrong in the
other direction (it writes the count where the last index belongs, and melt
renders one black frame past the end).

Picture is silent. Film under a VO plays with its audio muted — the producers
carry `audio_index=-1`, and the sequence gets no audio mix for the picture
track because there is no picture audio to mix. Unmuting a shot is a real
feature (it needs a producer of its own and a second `mix` transition, since
`audio_index` is a producer property and not a per-entry one) and it lands
with the cue that asks for it, not speculatively.
"""

from __future__ import annotations

import uuid
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from fractions import Fraction
from math import gcd
from pathlib import Path
from typing import Any

#: What auto-editor writes and what the Kdenlive on this box reads. The
#: attribute is advisory — melt does not gate on it — but a document claiming
#: a version nobody here runs is a lie a reader would have to chase.
MLT_VERSION = "7.22.0"

#: The canvas when the project has no picture clip to take one from. A cue
#: table can be all cards, and a card is whatever size it was drawn at.
DEFAULT_RESOLUTION = (1920, 1080)

#: How long a still image claims to be. A `qimage` producer needs *some*
#: length or it ends after one frame; four hours is Kdenlive's own answer and
#: it is longer than any shot will ever be. `eof=continue` holds the last
#: frame if a shot somehow outruns it anyway, so the failure is a freeze
#: rather than a gap that MLT would fill with blank.
IMAGE_LENGTH_SECONDS = 4 * 3600


class MLTError(Exception):
    """Raised when a timeline cannot be written as MLT, or when the document
    written disagrees with the frame total it was built from."""


@dataclass(frozen=True)
class Entry:
    """`frames` frames of `resource`, read from `src_in` on.

    Frames throughout, and a *count* rather than an end — `src_out` derives
    the frame-inclusive end in one place so the off-by-one lives exactly once.

    `has_video` is a fact about the file, and it has to be one: a document
    with a wav and an mp4 on the same track cannot answer "does this carry
    picture" once for both, and answering it wrong tells MLT to render black
    frames off the wav.
    """

    resource: str
    src_in: int
    frames: int
    is_image: bool = False
    has_video: bool = False

    @property
    def src_out(self) -> int:
        """MLT's `out` is the last frame *index*, not the frame count."""
        return self.src_in + self.frames - 1


def fit_rect(source: tuple[int, int], resolution: tuple[int, int]) -> tuple[int, int, int, int]:
    """Where MLT puts a source frame when nothing tells it otherwise.

    Contain, never stretch: the source is scaled by the *smaller* of the two
    ratios and centred, so a 1920x816 source in a 1080x1920 profile occupies
    459 of 1920 rows and the other 76% is black bar. Measured on this box
    against the real footage before any of this was built — PLAN.md § Aspect
    swap, finding 2 — and written down here because it is the thing a reframe
    is defined *against*: a filter that reproduces this rect changes nothing
    and should not be emitted at all.
    """
    src_w, src_h = source
    width, height = resolution
    scale = min(width / src_w, height / src_h)
    dest_w = round(src_w * scale)
    dest_h = round(src_h * scale)
    return (round((width - dest_w) / 2), round((height - dest_h) / 2), dest_w, dest_h)


def centre_crop(source: tuple[int, int], resolution: tuple[int, int]) -> tuple[int, int, int, int]:
    """The largest rect of the canvas's aspect that fits inside the source.

    The default reframe, and the one PLAN.md § Aspect swap insists is
    *reported* rather than assumed: a centre crop is wrong whenever the
    subject is not centred, which in this footage is often, so the caller is
    told which rect it got and can name another.

    Integer pixels, so the centring is exact only when the leftover is even —
    1920x816 into 9:16 crops to 459 wide with 1461 to share, and this returns
    x=730 where the true centre is 730.5. The probe in finding 3 rendered the
    half-pixel version and read x back one pixel further left; a rect that
    cannot be typed is worse than a pixel, so the integer rect is what the
    override format and the default both speak.
    """
    src_w, src_h = source
    width, height = resolution
    if src_w * height >= src_h * width:
        crop_w, crop_h = round(src_h * width / height), src_h
    else:
        crop_w, crop_h = src_w, round(src_w * height / width)
    return ((src_w - crop_w) // 2, (src_h - crop_h) // 2, crop_w, crop_h)


def pane_boxes(resolution: tuple[int, int]) -> tuple[tuple[int, int, int, int], ...]:
    """Where the two panes of a stacked split sit inside the frame.

    Full width, half height each, the remainder going to the lower pane so
    the two always tile the canvas exactly — an odd height would otherwise
    leave a one-pixel seam of background showing between them.

    **Stacked rather than side by side, and that is not a preference.** The
    canvas this exists for is 9:16; two panes beside each other would be
    540x1920 apiece, taller than they are wide by nearly 4:1, and a face in
    one is a sliver. Stacked they are 1080x960 — wider than the 459px window
    a single crop of this footage gets, which is the whole gain.
    """
    width, height = resolution
    half = height // 2
    return ((0, 0, width, half), (0, half, width, height - half))


def pane_overlap(rect: tuple[int, int, int, int], pane: tuple[int, int, int, int]) -> float:
    """How much of the narrower pane the two panes share, 0.0 to 1.0.

    **The number a stacked split is judged on**, and until now the one nobody
    reported. Nothing masks a pane, so two crops that overlap are showing the
    same strip of source twice — once in each half — and a viewer reads that as
    a duplicated face rather than as two subjects. Where the line sits was
    measured on the film rather than chosen: its splits separate at 23–24%,
    where the halves hold distinct groups, against 52–63%, where the same face
    is in both (HISTORY.md § The thirty-nine windows, reviewed).

    It is reported and never enforced, for `reframe_detect`'s standing reason:
    the pass proposes and `reframe_sheet` disposes, and a duplicating split is
    sometimes the least bad answer for a shot one window cannot hold. What was
    wrong was making a reviewer compute it by hand every time the tool offered
    one.

    Horizontal only, because a pane is full source height by construction —
    growing a crop shorter than the source is what scales one pane into the
    other, which is a different failure and `_fit_pane_rect`'s job.
    """
    lower, upper = sorted((rect, pane), key=lambda box: box[0])
    shared = max(0, (lower[0] + lower[2]) - upper[0])
    narrower = min(rect[2], pane[2])
    return round(shared / narrower, 3) if narrower else 0.0


@dataclass(frozen=True)
class Reframe:
    """A source's size, and the rects of it that survive into the frame.

    **Geometry in source pixels, never a length** — the same rule a footage
    description follows (CLAUDE.md), and for the same reason: an edit cannot
    invalidate a rect, so no cut has to re-derive one. `source` rides along
    because the placement needs it — MLT is told where the *whole* frame goes,
    and the crop is expressed by letting the rest overflow the profile.

    `crop` is the window from the head of the file onward and `later` holds
    the rest, each `(src_start seconds, rect)` and in force from that point in
    the **source** onward. That address is what makes framing per *shot*
    rather than per clip (PLAN.md § Per-shot framing, finding 1: a cue cannot
    carry it, because cues and camera cuts are unrelated clocks). Everything
    the source address buys falls out rather than being engineered: a clip
    used seven times picks up whichever windows each placement happens to read
    over, no cut can invalidate one, and none of them is a length.

    A per-clip reframe is the degenerate one-window case, and still writes the
    same single `rect` string it always did.

    `panes` is the **second** rect of a stacked split, addressed by the same
    source in-point as the window it belongs to: a window carrying one is
    drawn as two half-height panes, this series holding the lower one and the
    ordinary window series the upper. Empty on every project that has no
    split, which is what keeps their documents byte-identical.
    """

    source: tuple[int, int]
    crop: tuple[int, int, int, int]
    later: tuple[tuple[float, tuple[int, int, int, int]], ...] = ()
    panes: tuple[tuple[float, tuple[int, int, int, int]], ...] = ()

    def __post_init__(self) -> None:
        at = [seconds for seconds, _ in self.later]
        if any(seconds <= 0 for seconds in at):
            raise MLTError(
                "a later reframe window starts after the head of the source — "
                "the window from 0 onward is `crop`"
            )
        if at != sorted(set(at)):
            raise MLTError(f"reframe windows must be in source order and distinct, not {at}")
        pane_at = [seconds for seconds, _ in self.panes]
        if pane_at != sorted(set(pane_at)):
            raise MLTError(f"split panes must be in source order and distinct, not {pane_at}")
        # A pane is the *other half* of a window, never a window of its own —
        # one without a partner would render as half a frame over whatever the
        # governing window happens to be, which is a picture nobody asked for.
        starts = {seconds for seconds, _ in self.windows()}
        orphans = [seconds for seconds in pane_at if seconds not in starts]
        if orphans:
            raise MLTError(
                f"a split pane at {orphans} has no window of its own to pair with — "
                "a pane is the lower half of a window, so both halves are addressed "
                "by the same source in-point"
            )

    def windows(self) -> tuple[tuple[float, tuple[int, int, int, int]], ...]:
        """Every window in source order, the head one included."""
        return ((0.0, self.crop), *self.later)

    def pane_at(self, seconds: float) -> tuple[int, int, int, int] | None:
        """The lower pane of the window starting exactly here, if it is a split.

        Keyed on the window's own start rather than "in force from here",
        because that is what a pane is: the other half of one window. Asking
        which pane covers an arbitrary moment is `crop_at`'s question, and the
        answer for the lower half is found by looking up that window's start.
        """
        for start, rect in self.panes:
            if abs(start - seconds) < 1e-9:
                return rect
        return None

    def window_start(self, seconds: float) -> float:
        """Where the window in force at this point in the source begins."""
        start = 0.0
        for at, _ in self.later:
            if seconds + 1e-9 < at:
                break
            start = at
        return start

    def is_split(self, seconds: float) -> bool:
        """Is the window in force at this point in the source a stacked split?"""
        return self.pane_at(self.window_start(seconds)) is not None

    def crop_at(self, seconds: float) -> tuple[int, int, int, int]:
        """The window in force at that point in the source."""
        found = self.crop
        for start, rect in self.later:
            if seconds + 1e-9 < start:
                break
            found = rect
        return found

    def _dest(
        self,
        crop: tuple[int, int, int, int],
        resolution: tuple[int, int],
        box: tuple[int, int, int, int] | None = None,
    ) -> tuple[int, int, int, int]:
        """Where the whole source frame lands, so that `crop` fills `box`.

        `qtblend`'s rect is a *destination* in profile pixels, not a crop —
        which is why this returns something much larger than the profile and
        with a negative origin. Scale is `max` of the two ratios (fill), and
        the crop's centre is put on the box's centre; when the crop already
        carries the box's aspect the two ratios are equal and nothing is
        lost off the second axis.

        `box` is the whole frame for an ordinary window and one half of it for
        a pane of a stacked split. The profile does the clipping either way —
        nothing is masked and no crop filter is involved — which is why a pane
        needs a crop of *exactly* the pane's aspect to stay inside it. That is
        `ops` refitting each pane against `pane_boxes`, and it is the one thing
        holding the two panes apart. Measured rather than assumed: a pane
        window spans the full source height by construction, so the scaled
        frame is exactly the pane's height and cannot reach the other half.
        """
        src_w, src_h = self.source
        crop_x, crop_y, crop_w, crop_h = crop
        box_x, box_y, box_w, box_h = box if box is not None else (0, 0, *resolution)
        scale = max(box_w / crop_w, box_h / crop_h)
        return (
            round(box_x + box_w / 2 - (crop_x + crop_w / 2) * scale),
            round(box_y + box_h / 2 - (crop_y + crop_h / 2) * scale),
            round(src_w * scale),
            round(src_h * scale),
        )

    def dest_rect(self, resolution: tuple[int, int]) -> tuple[int, int, int, int]:
        """Where the whole source frame lands for the head window."""
        return self.dest_rect_at(0.0, resolution)

    def dest_rect_at(self, seconds: float, resolution: tuple[int, int]) -> tuple[int, int, int, int]:
        """The same, for whichever window that point in the source reads.

        A split window answers with its **upper** pane, because that is what
        this reframe's own node draws there — a preview taking the whole-canvas
        rect instead would place the shot at more than twice the render's
        scale and show one person where the film shows two.
        """
        upper, _lower = pane_boxes(resolution)
        box = upper if self.is_split(seconds) else None
        return self._dest(self.crop_at(seconds), resolution, box)

    def pane_dest_at(
        self, seconds: float, resolution: tuple[int, int]
    ) -> tuple[int, int, int, int] | None:
        """Where the *lower* pane's source frame lands, or None if not a split.

        The second half of what `dest_rect_at` answers, and the two together
        are the whole of what the render draws — which is what a preview has to
        have to draw the same picture rather than half of it.
        """
        start = self.window_start(seconds)
        pane = self.pane_at(start)
        if pane is None:
            return None
        _upper, lower = pane_boxes(resolution)
        return self._dest(pane, resolution, lower)

    def is_identity(self, resolution: tuple[int, int]) -> bool:
        """Would this filter tell MLT anything it was not already doing?

        A source already at the canvas's aspect, uncropped, lands on exactly
        `fit_rect`. Emitting a filter for that case would change every
        existing document to no effect, so the writer skips it — which is what
        keeps a project with no canvas override byte-identical to the one it
        exported before any of this existed. **Every** window has to be that
        rect: one window that moves is a filter worth emitting.

        A split is never identity whatever its rects say — half the frame is
        being handed to a second node, which is not something MLT was already
        doing.
        """
        if self.panes:
            return False
        fitted = fit_rect(self.source, resolution)
        return all(self._dest(crop, resolution) == fitted for _, crop in self.windows())

    def rect_property(self, resolution: tuple[int, int], rate: float | None = None) -> str:
        """The `rect` value: `x y w h opacity`, or MLT's animation of them.

        One window writes the bare string it always wrote. More than one
        writes keyframes — **discrete (`|=`), because a framing window steps
        at a camera cut and does not slide into the next one** — numbered in
        the producer's own **source** frames, which is the clock MLT runs a
        filter's animation on. That was measured rather than assumed, and
        refuted from both directions: a step keyed at source frame 310 on a
        producer read from 300 lands at output frame 10, and one keyed at 20
        is already up at output frame 0 (PLAN.md § Per-shot framing, finding
        3). A timeline clock would have shown the opposite of both.

        A window that is a split writes the *upper* pane here — the same rect
        against a half-height box — so this node keeps drawing the whole way
        through and only its destination changes. The lower pane is a second
        node, `pane_rect_property`.
        """
        upper, _ = pane_boxes(resolution)
        if not self.later and not self.panes:
            return " ".join(str(value) for value in self.dest_rect(resolution)) + " 1"
        if not rate:
            raise MLTError(
                "a reframe with more than one window needs the frame rate — its "
                "keyframes are numbered in the source's own frames"
            )
        keys = []
        for seconds, crop in self.windows():
            box = upper if self.pane_at(seconds) is not None else None
            values = " ".join(str(value) for value in self._dest(crop, resolution, box))
            keys.append(f"{round(seconds * rate)}|={values} 1")
        return ";".join(keys)

    def pane_rect_property(self, resolution: tuple[int, int], rate: float) -> str:
        """The lower pane's own `rect`, on its own node — off where there is no split.

        **The pane is hidden by opacity, never by moving it off-canvas.** Both
        render byte-identical frames (the probe behind PLAN.md § The stacked
        split rendered the pair), and opacity is the one to write because a
        rect parked at -9999 reads as a bug to whoever opens the document next
        and invites being "fixed" into view.

        Keyed at every window boundary rather than only at the splits: a step
        that is not written is a value that carries on, so a pane left at
        opacity 1 past the end of its split would draw the following shot's
        footage into the bottom half of the frame. `melt` would exit 0.
        """
        if not self.panes:
            raise MLTError("this reframe has no split panes, so there is no second node")
        if not rate:
            raise MLTError(
                "a split pane needs the frame rate — its keyframes are numbered "
                "in the source's own frames"
            )
        _, lower = pane_boxes(resolution)
        parked = " ".join(str(value) for value in fit_rect(self.source, resolution))
        keys = []
        for seconds, crop in self.windows():
            pane = self.pane_at(seconds)
            if pane is None:
                keys.append(f"{round(seconds * rate)}|={parked} 0")
                continue
            values = " ".join(str(value) for value in self._dest(pane, resolution, lower))
            keys.append(f"{round(seconds * rate)}|={values} 1")
        return ";".join(keys)


def plan_picture(shots: list[dict[str, Any]], rate: float) -> list[Entry]:
    """Decide what each shot actually shows, and from where in its asset.

    `build_shots` (step 2) says when each shot starts and how long it runs and
    deliberately stops there — where inside the asset to read is a question
    about the XML, so it is answered here. A clip used three times shows three
    different stretches of itself: the cursor per asset carries on from where
    the previous shot left it, the way `assemble_scream.py` did by hand,
    because replaying the same opening seconds under every third beat is the
    thing that reads as stock footage.

    A cursor that would run past the end of its asset rewinds to the start
    rather than clamping — clamping would hold a frozen frame, which looks
    like a render bug rather than a re-use. A single shot longer than its
    whole asset cannot be solved by rewinding and refuses instead.

    **A pinned shot has no cursor and never rewinds** — it refuses (PLAN.md
    § B-roll by description). `src_pin` is source seconds, put there by a cue
    carrying `src_start`: somebody read a description and asked for *that*
    moment. Rewinding a pin to 0 would show footage the search did not find —
    correct pixels, wrong video, and nothing on screen saying so — which is
    the one failure a b-roll placement can make silently. The rewind above
    stays right for an unpinned re-use, where the only claim being made is
    "some of this clip".

    A pin still advances the cursor, so an unpinned re-use after one carries
    on from where the pinned stretch ended rather than replaying it.

    Stills have no cursor: a card is one frame held for the shot's length. A
    pin on one refuses rather than being ignored — `cue_add` turns it away
    first, and a pin that reached here anyway would be a silent no-op.
    """
    cursors: dict[str, int] = {}
    entries: list[Entry] = []
    for shot in shots:
        resource = str(shot["asset_path"])
        frames = int(shot["frames"])
        pin = shot.get("src_pin")
        if frames < 1:
            raise MLTError(
                f"shot for {shot['asset']!r} at frame {shot['start_frame']} is "
                f"{frames} frames long — a cue landed on top of the next one"
            )

        if shot["is_image"]:
            if pin is not None:
                raise MLTError(
                    f"the cue at {shot['clip_id']!r} word {shot['word_index']} pins "
                    f"{shot['asset']!r} to {float(pin):.1f}s, but it is a still — a "
                    "held frame has no playhead to move; drop the in-point"
                )
            entries.append(Entry(resource, 0, frames, is_image=True, has_video=True))
            continue

        duration = shot.get("asset_duration")
        if not duration:
            raise MLTError(
                f"asset {shot['asset']!r} has no known duration, so there is no "
                "way to tell whether the shot fits inside it"
            )
        available = round(float(duration) * rate)
        if frames > available:
            raise MLTError(
                f"the shot at {shot['clip_id']!r} word {shot['word_index']} runs "
                f"{frames / rate:.1f}s but {shot['asset']!r} is only "
                f"{available / rate:.1f}s long — split the shot with another cue, "
                "or point it at longer material"
            )
        if pin is None:
            cursor = cursors.get(resource, 0)
            if cursor + frames > available:
                cursor = 0
        else:
            cursor = round(float(pin) * rate)
            if cursor < 0:
                raise MLTError(
                    f"the cue at {shot['clip_id']!r} word {shot['word_index']} pins "
                    f"{shot['asset']!r} to {float(pin):.1f}s, which is before the "
                    "start of the asset"
                )
            if cursor + frames > available:
                raise MLTError(
                    f"the cue at {shot['clip_id']!r} word {shot['word_index']} pins "
                    f"{shot['asset']!r} to {cursor / rate:.1f}s and the shot runs "
                    f"{frames / rate:.1f}s, which ends past the asset's "
                    f"{available / rate:.1f}s — a pinned cue shows the moment it "
                    "names or nothing, so move the in-point earlier or shorten the "
                    "shot with another cue"
                )
        entries.append(Entry(resource, cursor, frames, has_video=True))
        cursors[resource] = cursor + frames
    return entries


def _property(parent: ET.Element, name: str, value: str) -> ET.Element:
    node = ET.SubElement(parent, "property", {"name": name})
    node.text = value
    return node


def _frame_rate(rate: float) -> tuple[int, int]:
    """`rate` as MLT's numerator/denominator pair.

    Exact for the integer rates and for the 1001-denominator ones (29.97 is
    30000/1001, and writing 29.97 flat is a frame of drift every 100 seconds).
    """
    if float(rate).is_integer():
        return int(rate), 1
    fraction = Fraction(rate).limit_denominator(1001)
    return fraction.numerator, fraction.denominator


def _profile(rate: float, resolution: tuple[int, int]) -> ET.Element:
    width, height = resolution
    num, den = _frame_rate(rate)
    divisor = gcd(width, height) or 1
    return ET.Element(
        "profile",
        {
            "description": "lucid",
            "width": str(width),
            "height": str(height),
            "progressive": "1",
            "sample_aspect_num": "1",
            "sample_aspect_den": "1",
            "display_aspect_num": str(width // divisor),
            "display_aspect_den": str(height // divisor),
            "frame_rate_num": str(num),
            "frame_rate_den": str(den),
            "colorspace": "709",
        },
    )


def _source_node(node_id: str, entry: Entry, bin_id: int, rate: float) -> ET.Element:
    """The producer a playlist entry reads from.

    Three shapes, and the differences are the whole reason distinct sources
    cannot share one node: a still is a `qimage` producer, picture is a chain
    with its audio switched off, and the edit's own track is a chain with its
    audio on.
    """
    if entry.is_image:
        node = ET.Element("producer", {"id": node_id})
        properties = {
            "resource": entry.resource,
            "mlt_service": "qimage",
            "length": str(round(IMAGE_LENGTH_SECONDS * rate)),
            "eof": "continue",
            "ttl": "1",
        }
    else:
        node = ET.Element("chain", {"id": node_id})
        properties = {
            "resource": entry.resource,
            "mlt_service": "avformat-novalidate",
            "vstream": "0",
            "astream": "0",
        }
    for name, value in properties.items():
        _property(node, name, value)
    _property(node, "kdenlive:id", str(bin_id))
    return node


def _playlist(playlist_id: str, entries: list[Entry], nodes: dict[str, str]) -> ET.Element:
    """One track's entries, laid end to end.

    No `<blank>` is emitted, ever — see this module's docstring. The entries
    are contiguous because the caller has already been refused if they were
    not, so a gap cannot arrive here to be papered over.
    """
    playlist = ET.Element("playlist", {"id": playlist_id})
    for entry in entries:
        ET.SubElement(
            playlist,
            "entry",
            {
                "producer": nodes[entry.resource],
                "in": str(entry.src_in),
                "out": str(entry.src_out),
            },
        )
    return playlist


def _pane_playlist(
    playlist_id: str, entries: list[Entry], nodes: dict[str, str], split: set[str]
) -> ET.Element:
    """A split pane's overlay track: the lane's own entries, blanked where it is not split.

    The deliberate `<blank>` this module's docstring carves out. The frame
    arithmetic is the lane's, entry for entry, so this track is exactly as
    long as the one it sits over and the run of blanks is what lets the lower
    half of the frame show the picture underneath.

    Consecutive blanks are merged, which is cosmetic and worth it: an
    unsplit film of 400 shots would otherwise write 400 one-shot blanks.
    """
    playlist = ET.Element("playlist", {"id": playlist_id})
    pending = 0
    for entry in entries:
        if entry.resource not in split:
            pending += entry.frames
            continue
        if pending:
            ET.SubElement(playlist, "blank", {"length": str(pending)})
            pending = 0
        ET.SubElement(
            playlist,
            "entry",
            {
                "producer": nodes[entry.resource],
                "in": str(entry.src_in),
                "out": str(entry.src_out),
            },
        )
    if pending:
        ET.SubElement(playlist, "blank", {"length": str(pending)})
    return playlist


def _transition(parent: ET.Element, transition_id: str, properties: dict[str, str]) -> None:
    node = ET.SubElement(parent, "transition", {"id": transition_id})
    for name, value in properties.items():
        _property(node, name, value)


def _reframe_filter(
    node: ET.Element, reframe: Reframe, resolution: tuple[int, int], rate: float
) -> bool:
    """Hang the crop-to-fill filter on one timeline producer, if it says anything.

    `qtblend` as a *filter* rather than a transition — the same service the
    compositing transitions below use, which is why this needed no new
    dependency and no consumer change (PLAN.md § Aspect swap, finding 3).

    Still **one filter per node however many windows it carries**: the rect is
    keyframable and the keys run on source frames, so per-shot framing needed
    no second node and no new service (PLAN.md § Per-shot framing, finding 3).
    """
    if reframe.is_identity(resolution):
        return False
    node_filter = ET.SubElement(node, "filter", {"id": f"filter_{node.get('id')}"})
    _property(node_filter, "mlt_service", "qtblend")
    _property(node_filter, "rect", reframe.rect_property(resolution, rate))
    return True


def _pane_filter(
    node: ET.Element, reframe: Reframe, resolution: tuple[int, int], rate: float
) -> None:
    """The same filter on a split's second node, carrying the lower pane.

    A second *node*, not a second service: the split needed no new MLT
    machinery at all, which the probe behind PLAN.md § The stacked split
    settled against the plan's own claim that it was a new render path.
    """
    node_filter = ET.SubElement(node, "filter", {"id": f"filter_{node.get('id')}"})
    _property(node_filter, "mlt_service", "qtblend")
    _property(node_filter, "rect", reframe.pane_rect_property(resolution, rate))


def reframed_nodes(root: ET.Element) -> dict[str, str]:
    """Every rendered producer carrying a reframe, as node id → rect.

    The readback half of the trap finding 3 names: `mlt.py` writes one node
    per distinct resource **per role**, so a file used by both the edit and
    the picture lane has two, and a reframe applied per *resource* would crop
    it on one track and letterbox it on the other in the same frame. The bin's
    producers are excluded on purpose — `xml_retain` keeps them out of the
    render, and a bin entry is the raw media, not a timeline placement.
    """
    found: dict[str, str] = {}
    for node in [*root.findall("chain"), *root.findall("producer")]:
        node_id = node.get("id") or ""
        if node_id.startswith("bin"):
            continue
        for node_filter in node.findall("filter"):
            rect = node_filter.find("property[@name='rect']")
            if rect is not None and rect.text:
                found[node_id] = rect.text
    return found


def document(
    *,
    audio: list[Entry],
    picture: list[Entry] | None = None,
    rate: float,
    resolution: tuple[int, int] = DEFAULT_RESOLUTION,
    reframe: dict[str, Reframe] | None = None,
    name: str = "lucid",
) -> ET.Element:
    """Build the whole MLT document, and check it against its own frame total.

    `audio` is the `Edit` — lucid's single subtractive track, whatever media
    it holds; `picture` is the cue table's lane over the top of it. The names
    are the roles they play in the finished video, not a claim about streams:
    an edit whose own clips carry video gets that track composited too, rather
    than rendered as sound over black, and each entry says for itself whether
    it has any.

    The picture lane must cover the timeline exactly. A short lane would
    become a `<blank>` and a long one would extend the render past the audio,
    and both are silent — hence a refusal here rather than a warning.

    `reframe` maps a resource to the rects of it that survive into the frame —
    one, or a window per camera shot — and is what turns a swapped canvas from
    a pillarbox into a filled one. It is applied per *node* rather than per
    resource, and never to a still: a card is authored at the canvas and
    re-authored when the canvas moves
    (`card_reauthor`), so cropping one would be lucid deciding to lose a
    corner of a title it drew itself.

    A reframe carrying **split panes** grows the document by a track per lane
    that has one: a second node of the same resource, a playlist holding that
    lane's entries with everything unsplit blanked out, and one more compositing
    transition. Nothing else changes — no new service, no mask, no crop filter.
    """
    if not audio:
        raise MLTError("an MLT document needs at least one entry on the edit's track")
    total_frames = sum(entry.frames for entry in audio)
    picture = picture or []
    if picture:
        covered = sum(entry.frames for entry in picture)
        if covered != total_frames:
            raise MLTError(
                f"the picture lane covers {covered} frames but the timeline is "
                f"{total_frames} — MLT would pad the difference with a silent "
                "<blank> (or run the render long), so the lane has to be exact"
            )

    root = ET.Element(
        "mlt",
        {
            "LC_NUMERIC": "C",
            "version": MLT_VERSION,
            "producer": "main_bin",
        },
    )
    root.append(_profile(rate, resolution))

    # The black background every track composites over. Its `length` is one of
    # the four declared lengths melt takes the longest of.
    background = ET.SubElement(root, "producer", {"id": "producer0"})
    for prop_name, value in {
        "length": str(total_frames),
        "eof": "continue",
        "resource": "black",
        "mlt_service": "color",
        "kdenlive:playlistid": "black_track",
        "mlt_image_format": "rgba",
        "aspect_ratio": "1",
    }.items():
        _property(background, prop_name, value)

    # One node per distinct resource per role. A file used by both the edit
    # and the picture lane gets two, because "is its audio on" is a property
    # of the producer, not of the entry — but both point at one bin entry, so
    # `kdenlive:id` is keyed on the resource and not on the node.
    sources: dict[str, Entry] = {}
    for entry in [*audio, *picture]:
        sources.setdefault(entry.resource, entry)
    bin_ids = {resource: index + 2 for index, resource in enumerate(sources)}

    reframe = reframe or {}
    # Every rendered node this should have reached, counted before the nodes
    # exist so the readback below has something independent to check against.
    wants_reframe = {
        (role, entry.resource)
        for role, lane in (("edit", audio), ("picture", picture))
        for entry in lane
        if not entry.is_image
        and entry.has_video
        and entry.resource in reframe
        and not reframe[entry.resource].is_identity(resolution)
    }

    def _split_in(lane: list[Entry]) -> dict[str, Entry]:
        """The resources on this lane that are drawn as a stacked split.

        Ordered by first appearance, so a document's pane nodes are numbered
        the way its ordinary ones are and a rebuild is byte-identical.
        """
        found: dict[str, Entry] = {}
        for entry in lane:
            if entry.is_image or not entry.has_video:
                continue
            if entry.resource in reframe and reframe[entry.resource].panes:
                found.setdefault(entry.resource, entry)
        return found

    audio_nodes: dict[str, str] = {}
    for entry in audio:
        if entry.resource in audio_nodes:
            continue
        node_id = f"chain{len(audio_nodes)}"
        audio_nodes[entry.resource] = node_id
        node = _source_node(node_id, entry, bin_ids[entry.resource], rate)
        _property(node, "set.test_audio", "0")
        _property(node, "set.test_video", "0" if entry.has_video else "1")
        if entry.has_video and entry.resource in reframe:
            _reframe_filter(node, reframe[entry.resource], resolution, rate)
        root.append(node)

    root.append(_playlist("playlist0", audio, audio_nodes))
    root.append(ET.Element("playlist", {"id": "playlist1"}))
    edit_track = ET.SubElement(
        root, "tractor", {"id": "tractor0", "in": "0", "out": str(total_frames - 1)}
    )
    _property(edit_track, "kdenlive:timeline_active", "1")
    _property(edit_track, "kdenlive:track_name", "Edit")
    audio_has_video = any(entry.has_video for entry in audio)
    hide = {} if audio_has_video else {"hide": "video"}
    for playlist_id in ("playlist0", "playlist1"):
        ET.SubElement(edit_track, "track", {"producer": playlist_id, **hide})

    # The split's second half, one overlay track per lane that has one. Its
    # node is a *silent* copy of the lane's — `audio_index=-1` for the picture
    # lane's own reason, and here it also stops the edit's sound being mixed
    # in twice, which is a doubled VO at exit 0.
    edit_panes: dict[str, str] = {}
    for resource, entry in _split_in(audio).items():
        node_id = f"pchain{len(edit_panes)}"
        edit_panes[resource] = node_id
        node = _source_node(node_id, entry, bin_ids[resource], rate)
        _property(node, "audio_index", "-1")
        _property(node, "video_index", "0")
        _property(node, "set.test_audio", "1")
        _pane_filter(node, reframe[resource], resolution, rate)
        root.append(node)
    if edit_panes:
        root.append(_pane_playlist("playlist4", audio, edit_panes, set(edit_panes)))
        root.append(ET.Element("playlist", {"id": "playlist5"}))
        edit_pane_track = ET.SubElement(
            root, "tractor", {"id": "tractor3", "in": "0", "out": str(total_frames - 1)}
        )
        _property(edit_pane_track, "kdenlive:timeline_active", "1")
        _property(edit_pane_track, "kdenlive:track_name", "Edit split")
        for playlist_id in ("playlist4", "playlist5"):
            ET.SubElement(edit_pane_track, "track", {"producer": playlist_id, "hide": "audio"})

    picture_nodes: dict[str, str] = {}
    if picture:
        for entry in picture:
            if entry.resource in picture_nodes:
                continue
            node_id = f"vchain{len(picture_nodes)}"
            picture_nodes[entry.resource] = node_id
            node = _source_node(node_id, entry, bin_ids[entry.resource], rate)
            if not entry.is_image:
                # Film under a VO plays silent — and `audio_index=-1` is what
                # makes it silent at the source, so no mix downstream can
                # accidentally let it back in.
                _property(node, "audio_index", "-1")
                _property(node, "video_index", "0")
                _property(node, "set.test_audio", "1")
                if entry.resource in reframe:
                    _reframe_filter(node, reframe[entry.resource], resolution, rate)
            root.append(node)

        root.append(_playlist("playlist2", picture, picture_nodes))
        root.append(ET.Element("playlist", {"id": "playlist3"}))
        picture_track = ET.SubElement(
            root, "tractor", {"id": "tractor1", "in": "0", "out": str(total_frames - 1)}
        )
        _property(picture_track, "kdenlive:timeline_active", "1")
        _property(picture_track, "kdenlive:track_name", "Picture")
        for playlist_id in ("playlist2", "playlist3"):
            ET.SubElement(picture_track, "track", {"producer": playlist_id, "hide": "audio"})

    picture_panes: dict[str, str] = {}
    for resource, entry in _split_in(picture).items():
        node_id = f"pvchain{len(picture_panes)}"
        picture_panes[resource] = node_id
        node = _source_node(node_id, entry, bin_ids[resource], rate)
        _property(node, "audio_index", "-1")
        _property(node, "video_index", "0")
        _property(node, "set.test_audio", "1")
        _pane_filter(node, reframe[resource], resolution, rate)
        root.append(node)
    if picture_panes:
        root.append(_pane_playlist("playlist6", picture, picture_panes, set(picture_panes)))
        root.append(ET.Element("playlist", {"id": "playlist7"}))
        picture_pane_track = ET.SubElement(
            root, "tractor", {"id": "tractor4", "in": "0", "out": str(total_frames - 1)}
        )
        _property(picture_pane_track, "kdenlive:timeline_active", "1")
        _property(picture_pane_track, "kdenlive:track_name", "Picture split")
        for playlist_id in ("playlist6", "playlist7"):
            ET.SubElement(picture_pane_track, "track", {"producer": playlist_id, "hide": "audio"})

    # A deterministic uuid: the same project rebuilt twice should produce the
    # same document, so a diff of two exports shows what actually changed.
    sequence_uuid = f"{{{uuid.uuid5(uuid.NAMESPACE_URL, f'lucid:{name}')}}}"
    sequence = ET.SubElement(
        root, "tractor", {"id": sequence_uuid, "in": "0", "out": str(total_frames - 1)}
    )
    _property(sequence, "kdenlive:uuid", sequence_uuid)
    _property(sequence, "kdenlive:clipname", name)
    # Bottom to top: the black background, the edit, its split's second pane,
    # the picture lane, and that lane's second pane. A pane sits directly over
    # the track it is half of and under everything that was already above it,
    # so adding one cannot change what covers what.
    stack = ["producer0", "tractor0"]
    if edit_panes:
        stack.append("tractor3")
    if picture:
        stack.append("tractor1")
    if picture_panes:
        stack.append("tractor4")
    for producer in stack:
        ET.SubElement(sequence, "track", {"producer": producer})

    # Without transitions a tractor renders its first track and drops the
    # rest, silently (HISTORY.md § 4) — the sound needs an additive mix and
    # every picture track needs compositing over the black background.
    _transition(
        sequence,
        "transition0",
        {
            "a_track": "0",
            "b_track": "1",
            "mlt_service": "mix",
            "internal_added": "237",
            "always_active": "1",
            "sum": "1",
        },
    )
    # `b_track` is an index into the track list just written, which is why the
    # order above and the order here are one loop and not two lists that have
    # to be kept in step. The edit is the only track that can be soundless
    # picture-less audio; every other one carries video by construction.
    blended = 0
    for index, producer in enumerate(stack):
        if index == 0 or (producer == "tractor0" and not audio_has_video):
            continue
        _transition(
            sequence,
            f"transition{blended + 1}",
            {
                "a_track": "0",
                "b_track": str(index),
                "mlt_service": "qtblend",
                "internal_added": "237",
                "always_active": "1",
                "disable": "0",
            },
        )
        blended += 1

    # The bin. `xml_retain` keeps this playlist out of the render — it is the
    # project's media list, not a track — and every timeline producer points
    # at its bin entry through `kdenlive:id`, which is what stops Kdenlive
    # opening the file with a populated timeline over an empty bin.
    main_bin = ET.SubElement(root, "playlist", {"id": "main_bin"})
    _property(main_bin, "kdenlive:docproperties.uuid", sequence_uuid)
    _property(main_bin, "kdenlive:docproperties.version", "1.1")
    _property(main_bin, "xml_retain", "1")
    ET.SubElement(main_bin, "entry", {"producer": sequence_uuid, "in": "0", "out": "0"})
    for index, (resource, entry) in enumerate(sources.items()):
        node = _source_node(f"bin{index}", entry, bin_ids[resource], rate)
        root.insert(list(root).index(main_bin), node)
        ET.SubElement(main_bin, "entry", {"producer": f"bin{index}", "in": "0"})

    project = ET.SubElement(
        root, "tractor", {"id": "tractor2", "in": "0", "out": str(total_frames - 1)}
    )
    _property(project, "kdenlive:projectTractor", "1")
    ET.SubElement(
        project, "track", {"producer": sequence_uuid, "in": "0", "out": str(total_frames - 1)}
    )

    # The same discipline as the frame check below, for the same reason: a
    # reframe that reached one of a file's two nodes renders a film that is
    # cropped on one track and letterboxed on the other, and melt exits 0.
    expected = {
        (audio_nodes if role == "edit" else picture_nodes)[resource]
        for role, resource in wants_reframe
    } | set(edit_panes.values()) | set(picture_panes.values())
    found = set(reframed_nodes(root))
    if expected != found:
        raise MLTError(
            f"the reframe reached nodes {sorted(found)} but belongs on "
            f"{sorted(expected)} — one node per resource *per role*, so a file on "
            "both the edit and the picture lane needs it twice or it renders "
            "cropped on one track and letterboxed on the other"
        )

    declared = declared_frames(root)
    wrong = {where: frames for where, frames in declared.items() if frames != total_frames}
    if wrong:
        raise MLTError(
            f"the document just written declares {wrong} where the timeline is "
            f"{total_frames} frames — melt renders to the longest declared "
            "length, so this would have padded the render out with a frozen "
            "frame and exited 0"
        )
    return root


def declared_frames(root: ET.Element) -> dict[str, int]:
    """Every place this document states how long the timeline is, as a count.

    The sweep melt's behaviour makes necessary: it renders to the longest of
    these, not to the playlist, so they have to agree and something has to
    check that they do. Read back off the built tree rather than tracked while
    building it — a value that was correct in a variable and wrong in the
    attribute is exactly the bug this is for.

    Frame *counts*, converted from whatever each spot declares: a tractor's
    `out` is the last frame index, the background producer's `length` is
    already a count. Producer lengths other than the background's are not
    timeline lengths at all — a still image claims four hours — and are left
    out on purpose.
    """
    found: dict[str, int] = {}
    for producer in root.findall("producer"):
        if producer.get("id") != "producer0":
            continue
        length = producer.find("property[@name='length']")
        if length is not None and (length.text or "").strip().isdigit():
            found["producer0 length"] = int(length.text.strip())
    for tractor in root.findall("tractor"):
        out = tractor.get("out", "")
        if out.isdigit():
            found[f"tractor {tractor.get('id')} out"] = int(out) + 1
        for track in tractor.findall("track"):
            track_out = track.get("out", "")
            if track_out.isdigit():
                found[f"tractor {tractor.get('id')} track {track.get('producer')} out"] = (
                    int(track_out) + 1
                )
    return found


def to_string(root: ET.Element) -> str:
    """The document as text, indented — a generated file still gets read."""
    ET.indent(root, space="  ")
    return ET.tostring(root, encoding="unicode", xml_declaration=True) + "\n"


def write(root: ET.Element, output: Path | str) -> Path:
    """Write the document, and say where it landed.

    Nothing here checks that `output` is somewhere melt can reach it — the
    flatpak cannot see `/tmp` and exits 0 having read nothing (CLAUDE.md) —
    because the caller picks the path and `picture.project_frames` already
    explains that failure when it happens.
    """
    destination = Path(output).expanduser()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(to_string(root), encoding="utf-8")
    return destination
