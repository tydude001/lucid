"""Word-level transcripts, and the word -> source-time index.

The transcript is an **immutable index over source media**, never over the
timeline. A word's `start`/`end` are always coordinates in the original
recording, so word 412 means the same audio no matter how many cuts have
accumulated on top. That is what makes ranges stay addressable across an
editing session — see PLAN.md, "addressable ranges over an accumulating edit".

The consequence worth stating: word indices do *not* renumber after a cut, and
`proofcut` will happily report that a word range is no longer present in the
timeline rather than silently shifting what it points at.
"""

from __future__ import annotations

import difflib
import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class TranscriptError(Exception):
    """Raised when a transcript cannot be read or a range makes no sense."""


class AmbiguousPhraseError(TranscriptError):
    """`Transcript.resolve()` found more than one match and was given no way
    to choose.

    Carries `.phrase` and `.candidates` (each a dict shaped like a `resolve()`
    success payload) so a caller — human or agent — can read every option and
    either narrow the phrase or pass `occurrence=`. The message enumerates
    them, the same convention `cue_rm`'s "no cue" error lists every existing
    cue (`ops.py`).
    """

    def __init__(self, phrase: str, candidates: list[dict[str, Any]]) -> None:
        self.phrase = phrase
        self.candidates = candidates
        listing = "; ".join(
            f"words {c['first_word']}-{c['last_word']} ({c['text']!r})" for c in candidates
        )
        super().__init__(
            f"phrase {phrase!r} matches {len(candidates)} times: {listing} — "
            "pass occurrence= to pick one (1-based, in transcript order), or "
            "narrow the phrase, or pass after= to skip earlier occurrences"
        )


#: Below this, an "overlap" is arithmetic rather than timing: two words sharing
#: a boundary survive a JSON round-trip and a subtraction as 0.9 against
#: 0.8999999999999999, which is not a seam and must not be reported as one.
OVERLAP_EPSILON = 1e-6


@dataclass(frozen=True)
class Word:
    """One spoken word, located in *source* time.

    `speaker` is a label and never an address: every cue, description,
    unspoken mark, music anchor and caption still resolves through
    `(clip_id, word_index)`, so attributing a two-mic recording adds a
    per-word fact and moves nothing. It is additive and optional — absent
    means what every transcript already on disk means, which is why it is
    not a schema bump (CLAUDE.md § An additive *optional* key does not
    bump). PLAN.md § The co-hosted recording.
    """

    index: int
    text: str
    start: float
    end: float
    speaker: str | None = None

    def as_dict(self) -> dict[str, Any]:
        """The saved shape — and it omits `speaker` when there is none.

        `asdict` would write `"speaker": null` into every word of every
        transcript the moment this field existed, so re-saving an
        unattributed transcript would rewrite the file for no change. A
        transcript nobody has attributed round-trips byte-identical.
        """
        out: dict[str, Any] = {
            "index": self.index,
            "text": self.text,
            "start": self.start,
            "end": self.end,
        }
        if self.speaker is not None:
            out["speaker"] = self.speaker
        return out


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

    def resolve(
        self,
        phrase: str,
        *,
        after: int = -1,
        occurrence: int | None = None,
        fuzzy: bool = True,
        fuzzy_floor: float = 0.75,
    ) -> dict[str, Any]:
        """Find `phrase`, forward of word `after`, and return exactly one match.

        `find()` lists every occurrence and leaves the choosing to the
        caller; this is the resolver — it always hands back one word range,
        or explains exactly why it can't. Ported from goodsometimes
        `scripts/assemble_longlegs.py`'s `resolve()`, which ran this
        contraction-aware/fuzzy-fallback match by hand against a real
        re-record (v3 -> v4) before this existed inside proofcut.

        Matching is contraction-aware and punctuation-insensitive
        (`_phrase_tokens`, deliberately separate from `find()`'s `_normalise`
        — see that function's docstring) and tokenizes the whole transcript
        into a flat `(token, owning_word_index)` array, because contraction
        expansion can split one whisper word into two tokens ("there's" ->
        "there is"), so a multi-token match still has to resolve back to real
        word indices.

        Ambiguity policy — the point of this over `find()`:
        - 0 exact matches after `after`: try fuzzy (if `fuzzy`), else raise
          `TranscriptError`.
        - 1 exact match: return it, `match: "exact"`.
        - >1 exact matches:
            - `occurrence` is None: raise `AmbiguousPhraseError` listing
              every candidate's word range and text. Never picks for you.
            - `occurrence` given (1-based, in transcript order among the
              matches after `after`): return that one. Out-of-range
              `occurrence` raises `TranscriptError` naming how many exist.
        - A fuzzy match (only reachable on 0 exact matches) returns the
          single best-scoring token window >= `fuzzy_floor`, `match:
          "fuzzy"`, `ratio: <float>` — stamped, never disguised as exact.
          **This floor is validated on exactly one project** (the
          goodsometimes v3->v4 reproduction) — it is not a broadly-measured
          threshold the way `SCENE_THRESHOLD` is (CLAUDE.md).

        Returns `{"first_word", "last_word", "text", "start", "end", "match",
        "ratio", "matches_after_cursor"}`. `ratio` is `None` on an exact
        match — a fuzzy hit is the only kind that carries a similarity score.
        Does NOT include `context_before`/`context_after` — that is the
        ops-layer echo's job, the same split as `_echo` vs this method.
        """
        want = _phrase_tokens(phrase)
        if not want:
            raise TranscriptError("phrase is empty")

        flat: list[str] = []
        owner: list[int] = []
        for word in self.words:
            for token in _phrase_tokens(word.text):
                flat.append(token)
                owner.append(word.index)

        def _match(first: int, last: int, *, kind: str, ratio: float | None) -> dict[str, Any]:
            start, end = self.span(first, last)
            return {
                "first_word": first,
                "last_word": last,
                "text": " ".join(w.text for w in self.words[first : last + 1]),
                "start": start,
                "end": end,
                "match": kind,
                "ratio": ratio,
            }

        n = len(want)
        exact: list[tuple[int, int]] = []
        seen: set[tuple[int, int]] = set()
        for s in range(len(flat) - n + 1):
            if owner[s] <= after:
                continue
            if flat[s : s + n] == want:
                key = (owner[s], owner[s + n - 1])
                if key not in seen:
                    seen.add(key)
                    exact.append(key)

        if len(exact) == 1:
            first, last = exact[0]
            result = _match(first, last, kind="exact", ratio=None)
            result["matches_after_cursor"] = 1
            return result

        if len(exact) > 1:
            if occurrence is None:
                candidates = [_match(f, last, kind="exact", ratio=None) for f, last in exact]
                raise AmbiguousPhraseError(phrase, candidates)
            if occurrence < 1 or occurrence > len(exact):
                raise TranscriptError(
                    f"occurrence {occurrence} is out of range — phrase {phrase!r} "
                    f"matches {len(exact)} time(s) after word {after}"
                )
            first, last = exact[occurrence - 1]
            result = _match(first, last, kind="exact", ratio=None)
            result["matches_after_cursor"] = len(exact)
            return result

        # No exact matches — fuzzy fallback, verbatim the n-1/n/n+1-window
        # difflib.SequenceMatcher + edge-snap algorithm the reference
        # implementation validated, ported not redesigned.
        if fuzzy:
            best_ratio = 0.0
            best_window: tuple[int, int] | None = None
            for m in (n, n - 1, n + 1):
                if m < 1:
                    continue
                for s in range(len(flat) - m + 1):
                    if owner[s] <= after:
                        continue
                    ratio = difflib.SequenceMatcher(None, flat[s : s + m], want).ratio()
                    if ratio > best_ratio:
                        best_ratio, best_window = ratio, (s, s + m)
            if best_window is not None and best_ratio >= fuzzy_floor:
                s, e = best_window
                window = flat[s:e]
                if want[0] in window:
                    s = s + window.index(want[0])
                if want[-1] in window:
                    e = best_window[0] + len(window) - 1 - window[::-1].index(want[-1]) + 1
                first, last = owner[s], owner[e - 1]
                result = _match(first, last, kind="fuzzy", ratio=round(best_ratio, 4))
                result["matches_after_cursor"] = 0
                return result

        raise TranscriptError(
            f"phrase {phrase!r} not found in {self.clip_id!r} after word {after}"
            + ("" if fuzzy else " (fuzzy disabled)")
        )

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


# -- phrase resolution ------------------------------------------------------
#
# Kept fully separate from `_normalise`/`_PUNCT` above, on purpose: those are
# shared by `find()` *and* `find_overlaps`/`find_repeats` (the retake-splice
# and duplicate detectors), and folding contraction expansion into them would
# silently change what those two consider identical text project-wide
# (CLAUDE.md). `resolve()` below is the only caller of everything in this
# section.

_CONTRACTIONS = [
    ("n't", " not"),
    ("'re", " are"),
    ("'ve", " have"),
    ("'ll", " will"),
    ("'d", " would"),
    ("'m", " am"),
    ("'s", " is"),
]
_PHRASE_PUNCT = re.compile(r"[^a-z0-9 ]+")


def _phrase_tokens(text: str) -> list[str]:
    """Lower-case, unify quotes/dashes, expand contractions both sides, tokenize.

    Whisper writes "There's" or "There is" as it pleases, and a phrase typed
    one way against a transcript written the other would otherwise miss —
    ported verbatim from goodsometimes `assemble_longlegs.py`'s `_norm`.
    """
    s = text.lower().replace("’", "'").replace("—", " ").replace("–", " ")
    for a, b in _CONTRACTIONS:
        s = s.replace(a, b)
    return _PHRASE_PUNCT.sub(" ", s).split()


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
    be proofcut silently discarding a real seam it happened to mis-size, and the
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
    lives outside proofcut and is what a human ran by hand to catch the Scream
    VO's retake pass — 72s of exactly this shape sat uncut in the timeline
    while every check proofcut had agreed with itself (HISTORY.md § The VO the
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


def _speaker(entry: dict[str, Any]) -> str | None:
    """The speaker label on one raw word entry, or None.

    Read through `.get` like every other optional key, and normalised to a
    non-empty string: an attributed transcript is proofcut's own output going
    back out and in again, but a hand-written one can carry an integer or a
    padded label, and a `speaker` that is sometimes `1` and sometimes `"1"`
    would compare unequal to itself across a round trip.
    """
    raw = entry.get("speaker")
    if raw is None:
        return None
    label = str(raw).strip()
    return label or None


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
        words.append(
            Word(index=len(words), text=text, start=start, end=end, speaker=_speaker(entry))
        )

    if not words:
        raise TranscriptError("transcript contains no usable words")

    return Transcript(
        clip_id=clip_id,
        words=tuple(words),
        language=payload.get("language"),
        origin=origin,
    )


def load(path: Path | str, *, clip_id: str) -> Transcript:
    """Read a transcript JSON from disk, in either whisper or proofcut form."""
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
