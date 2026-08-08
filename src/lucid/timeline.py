"""The timeline, and the track surgery that mutates it.

OTIO is the on-disk source of truth (`project.otio`), but it is a poor working
representation for cutting: its edit algorithms — `overwrite`, `ripple`,
`trim`, `slice` — are C++ only and have no Python bindings, so `algorithms`
gives us trimming, flattening and transition expansion and nothing else (see
CLAUDE.md). Everything here is therefore hand-rolled over a flat list of
segments, and OTIO is used for serialisation and NLE interchange.

The model is deliberately narrow, and the narrowness is the point for now:

* One track. A/V are **linked** — a clip carries both streams, the way a NLE
  treats a linked pair — so there is no way to cut picture without sound yet.
* Cut-and-concat only. Removing an interval ripples: the hole closes. There
  are no gaps, no overlaps, no transitions and no speed changes.

Both restrictions match what the auto-editor v3 round-trip can express, and
laying clips and graphics *over* a VO is currently Kdenlive's job. Widening
this is a real change, not a config flag — see PLAN.md.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import opentimelineio as otio

#: Segments shorter than this are dropped rather than emitted. A one-sample
#: sliver is never a real edit; it is a rounding artifact from a cut boundary
#: landing on top of an existing one.
MIN_SEGMENT = 0.001


class TimelineError(Exception):
    """Raised when an edit operation cannot be applied."""


@dataclass(frozen=True)
class Segment:
    """A half-open source interval `[start, end)` of one registered clip."""

    clip_id: str
    start: float
    end: float

    @property
    def duration(self) -> float:
        return self.end - self.start

    def as_dict(self) -> dict[str, Any]:
        return {
            "clip_id": self.clip_id,
            "start": self.start,
            "end": self.end,
            "duration": self.duration,
        }


@dataclass(frozen=True)
class Placement:
    """Where one piece of a source interval currently plays on the timeline.

    Carries both coordinate systems because the answer to "where does this
    play" is only checkable against the question: `source_start`/`source_end`
    say which part of the interval this piece is, which is what makes a
    partially-cut range readable rather than just short.
    """

    timeline_start: float
    timeline_end: float
    source_start: float
    source_end: float

    @property
    def duration(self) -> float:
        return self.timeline_end - self.timeline_start

    def contiguous_with(self, other: Placement) -> bool:
        """Does `other` start exactly where this piece ends, on the timeline?

        True across a cut seam — the hole closed, so the two play back-to-back
        — and false across an intervening segment of other material.
        """
        return abs(other.timeline_start - self.timeline_end) <= MIN_SEGMENT

    def as_dict(self) -> dict[str, Any]:
        return {
            "timeline_start": self.timeline_start,
            "timeline_end": self.timeline_end,
            "source_start": self.source_start,
            "source_end": self.source_end,
            "duration": self.duration,
        }


@dataclass
class Edit:
    """An ordered list of source segments — the whole timeline state."""

    segments: list[Segment]

    @property
    def duration(self) -> float:
        return sum(s.duration for s in self.segments)

    def as_dict(self) -> dict[str, Any]:
        return {
            "duration": self.duration,
            "segments": [s.as_dict() for s in self.segments],
        }

    # -- addressing ------------------------------------------------------

    def timeline_time(self, clip_id: str, source_time: float) -> float | None:
        """Where a source instant currently sits on the timeline.

        Returns None when that instant has been cut — which is the honest
        answer, and the reason cuts are reported rather than silently skipped.
        """
        offset = 0.0
        for seg in self.segments:
            if seg.clip_id == clip_id and seg.start <= source_time < seg.end:
                return offset + (source_time - seg.start)
            offset += seg.duration
        return None

    def timeline_span(self, clip_id: str, start: float, end: float) -> tuple[float, float] | None:
        """Where a source *interval* currently sits on the timeline.

        Returns the part of `[start, end)` that survives in the first segment
        overlapping it, mapped to timeline time — or None when the whole
        interval has been cut. An interval straddling a cut comes back
        truncated rather than stretched across material that is gone, which
        matters for captions: a word half-removed by a cut should show for the
        half that is still audible, not for its original length.
        """
        offset = 0.0
        for seg in self.segments:
            if seg.clip_id == clip_id:
                a, b = max(seg.start, start), min(seg.end, end)
                if b > a:
                    return offset + (a - seg.start), offset + (b - seg.start)
            offset += seg.duration
        return None

    def timeline_spans(self, clip_id: str, start: float, end: float) -> list[Placement]:
        """Every timeline interval a source interval now plays at, in order.

        The aggregate inverse of `source_spans`, and the aggregate form of
        `timeline_span` — which deliberately stops at the first survivor
        because captions want one span per word, not a list. This one walks
        every segment, so a range a prior cut split comes back as >=2 pieces
        and a range fully cut comes back empty.

        The pieces are *not* merged even when their timeline coordinates touch.
        Two adjacent pieces mean the material is continuous to a listener but
        has a cut seam inside it, and those are different facts: merging would
        report the seam as absent. `Placement.contiguous_with` is how a caller
        that only cares about playback re-joins them.
        """
        placements: list[Placement] = []
        offset = 0.0
        for seg in self.segments:
            if seg.clip_id == clip_id:
                a, b = max(seg.start, start), min(seg.end, end)
                if b > a:
                    placements.append(
                        Placement(
                            timeline_start=offset + (a - seg.start),
                            timeline_end=offset + (b - seg.start),
                            source_start=a,
                            source_end=b,
                        )
                    )
            offset += seg.duration
        return placements

    def source_at(self, time: float) -> tuple[str, float] | None:
        """The (clip_id, source_time) playing at timeline instant `time`.

        The single-instant counterpart to `source_spans`: same timeline-time
        walk, but for one point rather than a range. The two disagree on
        purpose about what happens past the end — `source_spans` raises,
        because a *requested range* naming material that is not on the
        timeline at all is almost certainly a mistake worth stopping on. This
        instead returns None, matching `timeline_time`'s own policy for a cut
        source instant: a single sampled point (as `spot_frames` produces one
        per frame, from evenly-spaced arithmetic that can round to the exact
        duration) is routine, not a caller error, so the honest answer is
        reported rather than raised.
        """
        offset = 0.0
        for seg in self.segments:
            if offset <= time < offset + seg.duration:
                return seg.clip_id, seg.start + (time - offset)
            offset += seg.duration
        if self.segments and time == offset:
            last = self.segments[-1]
            return last.clip_id, last.end
        return None

    def covers(self, clip_id: str, start: float, end: float) -> float:
        """How much of a source interval is still present, in seconds."""
        total = 0.0
        for seg in self.segments:
            if seg.clip_id != clip_id:
                continue
            overlap = min(seg.end, end) - max(seg.start, start)
            if overlap > 0:
                total += overlap
        return total

    def source_spans(self, start: float, end: float) -> list[tuple[str, float, float]]:
        """Where a timeline (render) interval currently maps back to source.

        The aggregate inverse of `timeline_span`: that walks source->timeline
        for one clip and returns the single truncated survivor, this walks
        timeline->source across however many segments (and, in a future
        multi-clip timeline, clips) `[start, end)` touches, in playback order.

        `[start, end)` is timeline time, half-open, like every interval in
        this module. Past-the-end is refused rather than clamped — unlike
        `pad`'s deliberate overreach, it names material that is not on the
        timeline at all.

        Segments are laid contiguously in timeline coordinates (only source
        coordinates have gaps), so a valid `[start, end)` inside
        `[0, duration)` can never come back with zero pieces. A range crossing
        a prior cut comes back as >=2 pieces of the same clip_id, now
        non-adjacent in source time; a range crossing a clip boundary comes
        back with a different clip_id per piece.
        """
        if end <= start:
            raise TimelineError(f"interval {start:.3f}-{end:.3f} is empty or backwards")
        if start < -1e-6 or end > self.duration + 1e-6:
            raise TimelineError(
                f"interval {start:.3f}-{end:.3f} is outside the timeline "
                f"(0.000-{self.duration:.3f}) — it names material that is not "
                "on the timeline at all"
            )

        pieces: list[tuple[str, float, float]] = []
        offset = 0.0
        for seg in self.segments:
            lo, hi = max(offset, start), min(offset + seg.duration, end)
            if hi > lo:
                pieces.append((seg.clip_id, seg.start + (lo - offset), seg.start + (hi - offset)))
            offset += seg.duration
        return pieces

    # -- mutation --------------------------------------------------------

    def remove(self, clip_id: str, start: float, end: float) -> int:
        """Ripple-delete a source interval. Returns the segments it touched."""
        if end <= start:
            raise TimelineError(f"interval {start:.3f}-{end:.3f} is empty or backwards")

        touched = 0
        out: list[Segment] = []
        for seg in self.segments:
            if seg.clip_id != clip_id or seg.end <= start or seg.start >= end:
                out.append(seg)
                continue
            touched += 1
            out.extend(_subtract(seg, start, end))
        self.segments = [s for s in out if s.duration >= MIN_SEGMENT]
        return touched

    def keep_only(self, clip_id: str, intervals: Iterable[tuple[float, float]]) -> None:
        """Keep only these source intervals of `clip_id`; drop the rest of it.

        Other clips are left alone, so this is "keep these bits of the VO",
        not "throw away everything else on the timeline".
        """
        wanted = _merge(sorted((float(a), float(b)) for a, b in intervals))
        if not wanted:
            raise TimelineError("keep_only needs at least one interval")

        out: list[Segment] = []
        for seg in self.segments:
            if seg.clip_id != clip_id:
                out.append(seg)
                continue
            for lo, hi in wanted:
                a, b = max(seg.start, lo), min(seg.end, hi)
                if b - a >= MIN_SEGMENT:
                    out.append(replace(seg, start=a, end=b))
        self.segments = out


def _subtract(seg: Segment, start: float, end: float) -> list[Segment]:
    """Remove `[start, end)` from one segment: 0, 1 or 2 segments come back."""
    pieces = []
    if seg.start < start:
        pieces.append(replace(seg, end=min(start, seg.end)))
    if seg.end > end:
        pieces.append(replace(seg, start=max(end, seg.start)))
    return pieces


def _merge(intervals: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Coalesce sorted, possibly overlapping intervals."""
    merged: list[tuple[float, float]] = []
    for lo, hi in intervals:
        if hi <= lo:
            continue
        if merged and lo <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], hi))
        else:
            merged.append((lo, hi))
    return merged


# -- OTIO interchange ----------------------------------------------------


def _rational(seconds: float, rate: float) -> otio.opentime.RationalTime:
    return otio.opentime.RationalTime(round(seconds * rate), rate)


def to_otio(
    edit: Edit,
    clips: dict[str, dict[str, Any]],
    *,
    rate: float,
    name: str = "lucid",
) -> otio.schema.Timeline:
    """Serialise an `Edit` to OTIO, resolving clip_ids against the manifest."""
    timeline = otio.schema.Timeline(name=name)
    has_video = any(clips.get(s.clip_id, {}).get("has_video") for s in edit.segments)
    track = otio.schema.Track(
        name="V1" if has_video else "A1",
        kind=otio.schema.TrackKind.Video if has_video else otio.schema.TrackKind.Audio,
    )
    timeline.tracks.append(track)

    for n, seg in enumerate(edit.segments):
        record = clips.get(seg.clip_id)
        if record is None:
            raise TimelineError(f"segment {n} references unregistered clip {seg.clip_id!r}")
        reference = otio.schema.ExternalReference(
            target_url=Path(record["source"]).as_uri(),
            available_range=otio.opentime.TimeRange(
                _rational(0.0, rate), _rational(float(record["duration"]), rate)
            ),
        )
        clip = otio.schema.Clip(
            name=f"{seg.clip_id}-{n:04d}",
            media_reference=reference,
            source_range=otio.opentime.TimeRange(
                _rational(seg.start, rate), _rational(seg.duration, rate)
            ),
        )
        clip.metadata["lucid"] = {"clip_id": seg.clip_id}
        track.append(clip)

    timeline.metadata["lucid"] = {"rate": rate}
    return timeline


def from_otio(timeline: otio.schema.Timeline) -> Edit:
    """Read an `Edit` back out of an OTIO timeline written by `to_otio`."""
    segments: list[Segment] = []
    for track in timeline.tracks:
        for item in track:
            if not isinstance(item, otio.schema.Clip):
                continue
            meta = dict(item.metadata.get("lucid") or {})
            clip_id = meta.get("clip_id")
            if clip_id is None:
                raise TimelineError(
                    f"clip {item.name!r} has no lucid metadata — "
                    "this timeline was not written by lucid"
                )
            source_range = item.source_range
            start = source_range.start_time.to_seconds()
            segments.append(
                Segment(clip_id=clip_id, start=start, end=start + source_range.duration.to_seconds())
            )
        break  # single-track model; see the module docstring
    return Edit(segments=segments)


def read(path: Path | str) -> Edit:
    return from_otio(otio.adapters.read_from_file(str(path)))


def write(timeline: otio.schema.Timeline, path: Path | str) -> None:
    otio.adapters.write_to_file(timeline, str(path))
