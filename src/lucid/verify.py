"""Comparing what the timeline should say against what the render says.

Pure sequence work: two lists of word tokens in, a diff out. No I/O, no ASR —
`ops.verify` supplies both sides and this decides what changed.

The comparison is over *word order*, not timings. That is the point. Whisper
collapses an immediate retake into one utterance and hides the second take
inside the duration of the following word (DOGFOOD § 2), so timings cannot
prove the retake was removed — but the render's own transcript will contain the
phrase twice, and the timeline's expected sequence contains it once. Order is
the signal that survives.

Similarity is triage, not a verdict: ~0.97 is a clean render, because whisper
spells its own output differently on a second pass ("whodunit" / "who done it",
"4" / "four"). The diff is the artifact a human or an agent reads.
"""

from __future__ import annotations

import difflib
from collections.abc import Iterable
from typing import Any

from lucid.transcript import _normalise

#: Shorter runs are noise. A single extra word is usually a filler whisper
#: caught on one pass and not the other; two in a row that also appear in the
#: expected sequence is a phrase that played twice.
MIN_RUN = 2


class VerifyError(Exception):
    """Raised when there is nothing to verify against."""


def tokens(texts: Iterable[str]) -> list[str]:
    """Flatten text into comparable word tokens.

    Uses the transcript module's own normalisation so that "the same word"
    means the same thing here as it does in `Transcript.find` — a phrase an
    agent searched for and a phrase this diff reports must not disagree about
    punctuation.
    """
    out: list[str] = []
    for text in texts:
        out.extend(_normalise(text).split())
    return out


def _index_of(haystack: list[str], needle: list[str]) -> int:
    """First position of `needle` as a contiguous run in `haystack`, or -1."""
    if not needle or len(needle) > len(haystack):
        return -1
    first = needle[0]
    for i in range(len(haystack) - len(needle) + 1):
        if haystack[i] == first and haystack[i : i + len(needle)] == needle:
            return i
    return -1


def compare(expected: list[str], heard: list[str]) -> dict[str, Any]:
    """Diff the timeline's expected words against the render's heard words.

    `repeated` and `dropped` are heuristics over the diff, surfaced because
    reading a 900-line word diff to find one duplicated phrase is exactly the
    work this tool exists to avoid. Neither is authoritative — `diff` is.
    """
    matcher = difflib.SequenceMatcher(a=expected, b=heard, autojunk=False)

    repeated: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag in ("insert", "replace"):
            extra = heard[j1:j2]
            # Extra words the timeline also expects *somewhere* are a phrase
            # played twice: a retake the transcript never showed as a retake.
            if len(extra) >= MIN_RUN and _index_of(expected, extra) >= 0:
                repeated.append({"text": " ".join(extra), "at_heard_word": j1})
        if tag in ("delete", "replace"):
            missing = expected[i1:i2]
            # The opposite failure: a cut that reached past its word range.
            if len(missing) >= MIN_RUN:
                dropped.append({"text": " ".join(missing), "at_expected_word": i1})

    return {
        "similarity": round(matcher.ratio(), 3),
        "repeated": repeated,
        "dropped": dropped,
        # One word per line, so the diff reads as a word-level diff rather than
        # two enormous paragraphs marked wholly changed.
        "diff": list(
            difflib.unified_diff(
                expected, heard, fromfile="timeline", tofile="render", n=2, lineterm=""
            )
        ),
    }
