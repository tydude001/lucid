"""Which mic was loudest while a word was spoken — the whole rule.

Pure arithmetic over decoded mics, `speech.py`'s tier: no project, no ffmpeg,
no manifest. `load_mic` is the one function here that touches a file, and it
reads a WAV this module did not create with the stdlib `wave` module, so the
rule below can be pinned on its own the way `autoeditor.frame_layout` is
pinned apart from `check_frames`.

**The rule is an energy ratio between two streams, per word, and it is a
report rather than a fix.** PLAN.md § The co-hosted recording measured it on a
built fixture: 98.9% correct per word on clear speech and barely moving across
18 dB of mic isolation, against **chance** on words spoken over each other.
The margin — how many dB louder the winner is — is what half-knows the
difference, and at a 6 dB floor it flags 44% of the overlapped words for 1% of
the clear ones. It does not repair the ones it flags, and nothing here
pretends the floor makes the answer safe: what survives the floor is still
about half wrong on simultaneous speech.

Two designs were measured and lost, recorded so nobody builds them twice:

- **Transcribing each mic separately does not separate speakers.** Half of
  each mic's own transcript is the *other* person, at every isolation from
  −6 dB to −24 dB. Pushing the isolation further only changes the failure
  mode: an isolated mic is a track that is silent half the time, which is
  whisper's own documented hallucination trigger.
- **An envelope-only "both mics hot at once" detector does not find the
  overlaps.** Given its fair form — `speech.merge_runs` per mic then
  `speech.intersect_runs` — recall 0.86–0.90 buys precision 0.21–0.32: 81.6s
  of "simultaneous" in a clip holding 19.0s of it.

The fixture behind those numbers is synthetic in the way that matters most —
one voice, an injected bleed, turns alternating on a metronome — so every
number above is an upper bound, and `MARGIN_DB` is deliberately **reported
and never pinned by it**. A five-minute two-mic test recording of two people
actually talking over each other is what would settle the floor.
"""

from __future__ import annotations

import array
import math
import wave
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

#: dB the loudest mic must beat the runner-up by before the word is called.
#: The fixture's own asymmetry at this value: 44% of overlapped words flagged
#: for 1% of the clear ones. Reported with every decision, never silently
#: applied — see the module docstring on why it is not pinned.
MARGIN_DB = 6.0

#: A zero-width word has no span to measure, and whisper emits `start == end`
#: often (CLAUDE.md § Segments are half-open). Anything shorter than this is
#: measured over this much audio, centred where the word is.
MIN_SPAN = 0.02

#: Energy is accumulated per block so a span's RMS is two subtractions rather
#: than a walk: an hour of 16 kHz mono is 57M samples and 720k blocks.
BLOCK_SECONDS = 0.005

#: What a margin reads as when the runner-up is digital silence. A real number
#: rather than `inf`, because every one of these crosses a JSON boundary.
MAX_MARGIN_DB = 120.0


class SpeakerError(Exception):
    """Raised when a mic cannot be read, or the labels make no sense."""


@dataclass(frozen=True)
class MicTrack:
    """One decoded mic, as block energies plus the label it stands for.

    `energy` is a prefix sum of squared samples — `energy[i]` is the total
    over blocks `0..i-1` — so `rms` over any span costs one subtraction and a
    square root regardless of how long the span is.
    """

    label: str
    rate: int
    block: int
    energy: tuple[float, ...]

    @property
    def duration(self) -> float:
        return (len(self.energy) - 1) * self.block / self.rate

    def rms(self, start: float, end: float) -> float | None:
        """Root-mean-square over `start`..`end` seconds, or None past the end.

        None is not zero, and the caller has to keep them apart: zero is a mic
        that was silent while the word was spoken, None is a mic that had
        already run out of audio. The second means the transcript and the mics
        are not the same recording, which is a finding rather than a quiet
        `speaker: null`.
        """
        blocks = len(self.energy) - 1
        if blocks <= 0:
            return None

        lo, hi = (start, end) if end > start else (start, start)
        if hi - lo < MIN_SPAN:
            middle = (lo + hi) / 2
            lo, hi = middle - MIN_SPAN / 2, middle + MIN_SPAN / 2

        first = max(0, int(lo * self.rate) // self.block)
        last = min(blocks, math.ceil(hi * self.rate / self.block))
        if first >= blocks or last <= first:
            return None

        total = self.energy[last] - self.energy[first]
        return math.sqrt(max(0.0, total) / ((last - first) * self.block))


@dataclass(frozen=True)
class Decision:
    """What the mics said about one word.

    `label` is None whenever this refuses to call it, and `why` says which
    refusal it is — the two are different findings and a report that collapses
    them says "unattributed" about a recording problem.
    """

    label: str | None
    margin_db: float | None
    levels: tuple[float, ...]
    why: str | None = None


def load_mic(path: Path | str, label: str, *, block_seconds: float = BLOCK_SECONDS) -> MicTrack:
    """Read a 16-bit mono WAV into block energies.

    The only I/O in this module. It takes what `media.decode_stream_wav`
    writes and refuses anything else rather than guessing at a sample width —
    a wrong width reads as a mic at a different level, which is exactly the
    quantity this module compares.
    """
    src = Path(path)
    try:
        with wave.open(str(src), "rb") as handle:
            channels, width = handle.getnchannels(), handle.getsampwidth()
            rate, frames = handle.getframerate(), handle.getnframes()
            raw = handle.readframes(frames)
    except (OSError, wave.Error) as exc:
        raise SpeakerError(f"could not read {src} as a WAV: {exc}") from exc

    if channels != 1 or width != 2:
        raise SpeakerError(
            f"{src.name} is {channels}-channel {width * 8}-bit; this reads 16-bit mono, "
            "which is what the decode writes"
        )
    if not frames:
        raise SpeakerError(f"{src.name} holds no audio at all")

    samples = array.array("h")
    samples.frombytes(raw)
    block = max(1, int(rate * block_seconds))

    running = 0.0
    energy = [0.0]
    for start in range(0, len(samples), block):
        chunk = samples[start : start + block]
        running += sum(float(s) * float(s) for s in chunk)
        energy.append(running)

    return MicTrack(label=str(label), rate=rate, block=block, energy=tuple(energy))


def check_labels(labels: Sequence[str]) -> list[str]:
    """Normalise mic labels, refusing the two that silently merge speakers."""
    cleaned = [str(label).strip() for label in labels]
    if len(cleaned) < 2:
        raise SpeakerError(
            f"attribution compares mics against each other, so it needs at least two, not "
            f"{len(cleaned)}"
        )
    if any(not label for label in cleaned):
        raise SpeakerError("a mic label cannot be empty — it is what lands on the word")
    if len(set(cleaned)) != len(cleaned):
        raise SpeakerError(
            f"two mics share a label ({', '.join(cleaned)}), so every word attributed to "
            "either would read as one speaker"
        )
    return cleaned


def attribute(
    spans: Sequence[tuple[float, float]],
    mics: Sequence[MicTrack],
    *,
    margin_db: float = MARGIN_DB,
) -> list[Decision]:
    """One decision per span: the loudest mic, if it is loud enough by `margin_db`.

    Spans are in the recording's own seconds, which is what a transcript
    indexes — the source, never the timeline (CLAUDE.md § Anything that emits
    times *for playback*). No cut can invalidate one of these, and running
    this after an edit gives the same answer.
    """
    if len(mics) < 2:
        raise SpeakerError(
            f"attribution compares mics against each other, so it needs at least two, not "
            f"{len(mics)}"
        )
    if margin_db < 0:
        raise SpeakerError(f"a margin is a number of dB the winner leads by, not {margin_db}")

    out: list[Decision] = []
    for start, end in spans:
        levels = [mic.rms(start, end) for mic in mics]
        if any(level is None for level in levels):
            out.append(
                Decision(
                    label=None,
                    margin_db=None,
                    levels=tuple(level or 0.0 for level in levels),
                    why="this moment is past the end of at least one mic",
                )
            )
            continue

        measured = [float(level) for level in levels if level is not None]
        order = sorted(range(len(measured)), key=lambda i: measured[i], reverse=True)
        best, runner_up = measured[order[0]], measured[order[1]]

        if best <= 0.0:
            out.append(
                Decision(
                    label=None,
                    margin_db=None,
                    levels=tuple(measured),
                    why="every mic is silent here",
                )
            )
            continue

        margin = MAX_MARGIN_DB if runner_up <= 0.0 else 20.0 * math.log10(best / runner_up)
        margin = min(margin, MAX_MARGIN_DB)
        if margin < margin_db:
            out.append(
                Decision(
                    label=None,
                    margin_db=margin,
                    levels=tuple(measured),
                    why=f"the loudest mic leads by {margin:.1f} dB, under the {margin_db:g} dB floor",
                )
            )
            continue

        out.append(
            Decision(label=mics[order[0]].label, margin_db=margin, levels=tuple(measured))
        )
    return out


def summarise(decisions: Sequence[Decision]) -> dict[str, Any]:
    """Counts and margin spread — the report's own arithmetic, kept pure."""
    margins = sorted(d.margin_db for d in decisions if d.margin_db is not None)
    by_label: dict[str, int] = {}
    for decision in decisions:
        if decision.label is not None:
            by_label[decision.label] = by_label.get(decision.label, 0) + 1

    summary: dict[str, Any] = {
        "words": len(decisions),
        "attributed": sum(1 for d in decisions if d.label is not None),
        "ambiguous": sum(1 for d in decisions if d.label is None and d.margin_db is not None),
        "unmeasurable": sum(1 for d in decisions if d.label is None and d.margin_db is None),
        "by_label": by_label,
    }
    if margins:
        summary["margins"] = {
            "min": round(margins[0], 2),
            "median": round(margins[len(margins) // 2], 2),
            "max": round(margins[-1], 2),
        }
    return summary
