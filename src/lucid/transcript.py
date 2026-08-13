"""Word-level transcripts, and the word -> source-time index.

The transcript is an **immutable index over source media**, never over the
timeline. A word's `start`/`end` are always coordinates in the original
recording, so word 412 means the same audio no matter how many cuts have
accumulated on top. That is what makes ranges stay addressable across an
editing session — see PLAN.md, "addressable ranges over an accumulating edit".

The consequence worth stating: word indices do *not* renumber after a cut, and
`lucid` will happily report that a word range is no longer present in the
timeline rather than silently shifting what it points at.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


class TranscriptError(Exception):
    """Raised when a transcript cannot be read or a range makes no sense."""


#: Below this, an "overlap" is arithmetic rather than timing: two words sharing
#: a boundary survive a JSON round-trip and a subtraction as 0.9 against
#: 0.8999999999999999, which is not a seam and must not be reported as one.
OVERLAP_EPSILON = 1e-6


@dataclass(frozen=True)
class Word:
    """One spoken word, located in *source* time."""

    index: int
    text: str
    start: float
    end: float

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Transcript:
    clip_id: str
    words: tuple[Word, ...]
    language: str | None = None
    #: Where the timings came from, so a bad cut can be traced to its ASR run.
    origin: str | None = None

    def __len__(self) -> int:
        return len(self.words)

    @property
    def text(self) -> str:
        return " ".join(w.text for w in self.words)

    # -- addressing ------------------------------------------------------

    def span(self, first: int, last: int) -> tuple[float, float]:
        """Source interval covering words `first`..`last`, both inclusive.

        Inclusive because "cut words 30-45" in an editing conversation means
        45 goes too. An exclusive end here would be a silent off-by-one in
        every agent-authored call.
        """
        if first > last:
            raise TranscriptError(f"word range {first}-{last} runs backwards")
        try:
            a, b = self.words[first], self.words[last]
        except IndexError:
            raise TranscriptError(
                f"word range {first}-{last} is outside this transcript "
                f"(it has {len(self.words)} words, 0-{len(self.words) - 1})"
            ) from None
        return a.start, b.end

    def find(self, pattern: str, *, limit: int = 20) -> list[dict[str, Any]]:
        """Locate a phrase in the transcript, case- and punctuation-insensitive.

        Returns each match as a word range plus its source interval, which is
        exactly what `cut_by_transcript` takes. This exists so finding a retake
        does not require reading 929 words into a context window first.
        """
        needle = _normalise(pattern).split()
        if not needle:
            raise TranscriptError("search pattern is empty")

        haystack = [_normalise(w.text) for w in self.words]
        matches: list[dict[str, Any]] = []
        for i in range(len(haystack) - len(needle) + 1):
            if haystack[i : i + len(needle)] == needle:
                last = i + len(needle) - 1
                start, end = self.span(i, last)
                matches.append(
                    {
                        "first_word": i,
                        "last_word": last,
                        "start": start,
                        "end": end,
                        "text": " ".join(w.text for w in self.words[i : last + 1]),
                    }
                )
                if len(matches) >= limit:
                    break
        return matches

    def window(self, first: int, last: int, *, context: int = 0) -> list[Word]:
        """Words `first`..`last` inclusive, optionally padded for readability."""
        lo = max(0, first - context)
        hi = min(len(self.words), last + context + 1)
        return list(self.words[lo:hi])

    # -- serialisation ---------------------------------------------------

    def as_dict(self) -> dict[str, Any]:
        return {
            "clip_id": self.clip_id,
            "language": self.language,
            "origin": self.origin,
            "words": [w.as_dict() for w in self.words],
        }


_PUNCT = re.compile(r"[^\w\s']+")


def _normalise(text: str) -> str:
    return _PUNCT.sub("", text).lower().strip()


def _seam(words: Sequence[Word], run: Sequence[int]) -> dict[str, Any]:
    """One splice, as the word range it garbled.

    `end` is the widest end in the range rather than the last word's, because
    an invented word routinely ends *before* the word it follows — that
    inversion is the whole finding, so the range's own extent cannot be read
    off its final member.
    """
    first, last = run[0] - 1, run[-1]
    inside = words[first : last + 1]
    return {
        "first_word": first,
        "last_word": last,
        "text": " ".join(w.text for w in inside),
        "start": min(w.start for w in inside),
        "end": max(w.end for w in inside),
        "pairs": len(run),
        "worst": round(max(words[i - 1].end - words[i].start for i in run), 3),
    }


def find_overlaps(words: Sequence[Word]) -> list[dict[str, Any]]:
    """Find seams where the timings say two words were spoken at once.

    A word cannot begin before the one ahead of it ends, so wherever that
    happens the transcript is describing something other than one clean take.
    The mechanism is a retake splice: whisper reads straight *across* it and
    interleaves words from both takes, inventing words nobody said.

    **The tell is the overlap, never the reading.** Nine invented words were
    burned to screen in 44s of the Scream teaser; eight were removed by eye in
    one pass and the ninth survived it, because "Billy and Stu *do* spend the
    entire film" is grammatical English where "Billy *Billions* and Stu" is
    not. Reading for sense finds the nonsense ones and is blind to the rest.
    HISTORY.md § The hand-framed teaser, watched.

    Reported as **seams rather than pairs**: one splice overlaps several words
    in a row — `Billy Billions and`, `Stu do - spend` — and reporting each
    pair on its own turns one event into five findings. Same reason
    `verify.find_adjacent_repeats` collapses its overlapping candidates.

    Deliberately unfiltered, and not a verdict. Whisper quantises its
    timestamps (0.02s on every transcript measured here), so two ordinary
    consecutive words can overlap by exactly one step through rounding alone.
    Those surface as a one-pair seam whose `worst` *is* that step — legible to
    whoever reads the result, which is who decides. A threshold would instead
    be lucid silently discarding a real seam it happened to mis-size, and the
    words a seam invents are drawn on screen.
    """
    seams: list[dict[str, Any]] = []
    run: list[int] = []
    for i in range(1, len(words)):
        if words[i].start < words[i - 1].end - OVERLAP_EPSILON:
            # A run is consecutive pair indices: one splice, not several.
            if run and i != run[-1] + 1:
                seams.append(_seam(words, run))
                run = []
            run.append(i)
    if run:
        seams.append(_seam(words, run))
    return seams


def find_repeats(
    words: Sequence[Word],
    *,
    min_words: int = 3,
    max_words: int = 25,
    max_gap: float = 3.0,
) -> list[dict[str, Any]]:
    """Find back-to-back duplicated phrases: the shape a retake makes.

    Ported from goodsometimes `scripts/vo_windows.py`'s `find_repeats`, which
    lives outside lucid and is what a human ran by hand to catch the Scream
    VO's retake pass — 72s of exactly this shape sat uncut in the timeline
    while every check lucid had agreed with itself (HISTORY.md § The VO the
    project was holding). `min_words`/`max_words`/`max_gap` are its defaults,
    unchanged: a run of 3-25 words that repeats itself verbatim within 3.0s
    of its own end.

    For each unconsumed starting position, the *longest* matching repeat
    wins — a 20-word duplicate should not also be reported as the 3-word one
    buried inside it — and every word in a match is consumed before scanning
    resumes, so one retake is one finding rather than several overlapping
    ones.

    **Its blind spot is not this function's own — it is whisper's, and it is
    the mirror image of `find_overlaps`'s.** This can only find a repeat that
    survived transcription as distinct, cleanly-timed words, because the
    match is exact normalised text over two separate runs. § The hand-framed
    teaser, watched found that whisper does not reliably write a retake that
    way: it routinely reads straight across the splice and hands the *word
    after it* a duration long enough to swallow the abandoned take whole —
    which is precisely `find_overlaps`'s tell, and precisely the shape this
    function has nothing to match against, because there are no second-take
    words here to find. The two are not redundant and neither subsumes the
    other: a retake is either words this can see or timing `find_overlaps`
    can see, and a transcript can hold either kind. Reading the transcript's
    prose is not a substitute for either — the Scream VO reads as clean,
    grammatical text with the retakes still in it.

    Reported as **whole matched runs, never scored or thresholded** — the
    same discipline `find_overlaps` documents for the same reason. This one
    already carries structural bounds (`min_words`, `max_words`, `max_gap`)
    that describe the *shape* a retake makes, but nothing here judges whether
    a hit is a flub rather than a deliberate callback line said twice on
    purpose — those match identically. A list to listen to, not a cut list.
    """
    keys = [_normalise(w.text) for w in words]
    found: list[dict[str, Any]] = []
    used: set[int] = set()
    index = 0
    while index < len(words):
        best: dict[str, Any] | None = None
        for length in range(max_words, min_words - 1, -1):
            first, second = index, index + length
            if second + length > len(words):
                continue
            if any(i in used for i in range(first, second + length)):
                continue
            if keys[first:second] != keys[second : second + length]:
                continue
            gap = words[second].start - words[second - 1].end
            if gap > max_gap:
                continue
            best = {
                "first_word": first,
                "second_word": second,
                "last_word": second + length - 1,
                "words": length,
                "first_start": words[first].start,
                "first_end": words[second - 1].end,
                "second_start": words[second].start,
                "second_end": words[second + length - 1].end,
                "gap": gap,
                "text": " ".join(w.text for w in words[first:second]),
            }
            break
        if best:
            found.append(best)
            used.update(range(best["first_word"], best["last_word"] + 1))
            index = best["last_word"] + 1
        else:
            index += 1
    return found


def parse_whisper(payload: dict[str, Any], *, clip_id: str, origin: str | None = None) -> Transcript:
    """Normalise a whisper JSON dump into a `Transcript`.

    Handles both shapes seen in practice: openai-whisper's
    `segments[].words[]`, and a flat top-level `words[]` (faster-whisper
    dumps and hand-written fixtures). A file with segments but no word
    timings is rejected loudly — segment-level timings would produce cuts
    that land mid-word, which is worse than refusing.
    """
    raw: list[dict[str, Any]] = []
    if isinstance(payload.get("words"), list):
        raw = payload["words"]
    else:
        segments = payload.get("segments")
        if not isinstance(segments, list):
            raise TranscriptError("transcript JSON has neither 'words' nor 'segments'")
        for segment in segments:
            raw.extend(segment.get("words") or [])
        if not raw:
            raise TranscriptError(
                "transcript has segments but no word timings — re-run whisper "
                "with word timestamps enabled (--word_timestamps True)"
            )

    words: list[Word] = []
    for entry in raw:
        text = (entry.get("word") if "word" in entry else entry.get("text")) or ""
        text = text.strip()
        if not text:
            continue
        try:
            start, end = float(entry["start"]), float(entry["end"])
        except (KeyError, TypeError, ValueError) as exc:
            raise TranscriptError(f"word {text!r} has unusable timings: {entry}") from exc
        words.append(Word(index=len(words), text=text, start=start, end=end))

    if not words:
        raise TranscriptError("transcript contains no usable words")

    return Transcript(
        clip_id=clip_id,
        words=tuple(words),
        language=payload.get("language"),
        origin=origin,
    )


def load(path: Path | str, *, clip_id: str) -> Transcript:
    """Read a transcript JSON from disk, in either whisper or lucid form."""
    src = Path(path).expanduser()
    try:
        payload = json.loads(src.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise TranscriptError(f"no transcript at {src}") from exc
    except json.JSONDecodeError as exc:
        raise TranscriptError(f"{src} is not valid JSON: {exc}") from exc
    return parse_whisper(payload, clip_id=clip_id, origin=str(src))


def save(transcript: Transcript, path: Path | str) -> None:
    """Write the normalised form into the project's transcript cache."""
    dest = Path(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(transcript.as_dict(), indent=2) + "\n", encoding="utf-8")
