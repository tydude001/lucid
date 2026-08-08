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

#: How closely an extra run has to resemble something the timeline expects
#: before it is called a repeat rather than left in the diff.
#:
#: It cannot be an exact match, and that is measured, not assumed. Two takes of
#: a line differ — that is *how you tell them apart*. On the Scream v1 export
#: the render says "falls apart a bit **at** the second half" and then "**in**
#: the second half", and "I don't think **that it's** a coincidence" then "I
#: don't think **that's** a coincidence"; the notes call the wrong preposition
#: the tell. Requiring the run verbatim reported one of those three retakes and
#: left the other two for whoever read all 900 lines of the diff.
#:
#: 0.5, because the second take is transcribed *worse* than the first — it is
#: the one whisper was already inclined to swallow. On the Scream v1 export the
#: repeat of "Scream 4 falls apart a bit" came back as "screen 4", and that one
#: substitution took the run to 0.556; at 0.6 the retake went unreported. An
#: unrelated insert does not come close, because it must also share a
#: contiguous run of `MIN_RUN` before it is scored at all.
SIMILAR = 0.5


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


def _closest_run(needle: list[str], haystack: list[str]) -> tuple[int, float]:
    """Where `haystack` most resembles `needle`, and how much: (index, ratio).

    Anchored on the longest shared run and then scored over a window of the
    same length, so that a second take is recognised as the same line as the
    first even though the two are not word-for-word — which they never are.

    Returns (-1, 0.0) when nothing of `MIN_RUN` length is shared at all.
    """
    if len(needle) < MIN_RUN or len(haystack) < MIN_RUN:
        return -1, 0.0

    anchor = difflib.SequenceMatcher(a=needle, b=haystack, autojunk=False).find_longest_match(
        0, len(needle), 0, len(haystack)
    )
    if anchor.size < MIN_RUN:
        return -1, 0.0

    # Line the window up so the shared run sits where it sits in `needle`.
    start = max(0, min(len(haystack) - len(needle), anchor.b - anchor.a))
    window = haystack[start : start + len(needle)]
    return start, difflib.SequenceMatcher(a=needle, b=window, autojunk=False).ratio()


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
            # Extra words that closely resemble a run the timeline expects
            # *somewhere* are that line played twice: a retake the transcript
            # never showed as a retake.
            at, ratio = _closest_run(extra, expected)
            if at >= 0 and ratio >= SIMILAR:
                repeated.append(
                    {
                        "text": " ".join(extra),
                        "at_heard_word": j1,
                        # The take the timeline does account for, so a reader
                        # can see both readings side by side and pick.
                        "expects": " ".join(expected[at : at + len(extra)]),
                        "at_expected_word": at,
                        "similarity": round(ratio, 3),
                    }
                )
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
