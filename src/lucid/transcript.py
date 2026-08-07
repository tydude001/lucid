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
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


class TranscriptError(Exception):
    """Raised when a transcript cannot be read or a range makes no sense."""


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
