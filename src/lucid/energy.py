"""The energy envelope — the one arbiter a transcript cannot outvote.

Every other check lucid runs believes a transcript about where the words are.
That belief has a documented ceiling: whisper collapses an immediate retake and
hands the *following* word a duration long enough to swallow it, so a whole
second reading of a sentence can sit inside what the transcript calls one word
(DOGFOOD § 2). On the Scream VO the worst case was a 4.12 s stretch between two
words holding 2.4 s of speech, and every transcript of that file — single pass,
windowed, `small`, `medium` — either merged it or wrote it down as silence.

The audio does not lie about it. Mask the waveform with the word map and
whatever audible energy is left over in the holes is *something*: a noise, or a
take the transcript dropped. This module measures that, and nothing else
decides what it means.

Two things worth knowing before reading a result:

- **The threshold calibrates off the file itself**, halfway in dB between its
  quiet tenth and the median level inside a word. Nothing here is an absolute
  dBFS number, because a VO stem and a scored render sit 20 dB apart and a
  fixed floor would be wrong on one of them.
- **A music bed raises the quiet end**, which is exactly what that
  self-calibration is for — but the bed is not flat, and a swell in a long pause
  can still clear the midpoint. Treat a reported gap as somewhere to listen,
  never as a verdict.

Stdlib only, on purpose: `audioop` went in 3.13 and numpy is not a dependency
lucid carries for one RMS loop.
"""

from __future__ import annotations

import array
import itertools
import math
import statistics
import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Any

FFMPEG = "ffmpeg"

#: Speech puts its energy under 4 kHz — fundamentals and the first two formants
#: — so 8 kHz keeps everything the question "is that a voice?" needs, and makes
#: the per-frame arithmetic below half what decoding at 16 kHz would cost.
RATE = 8000

#: 20 ms per envelope frame: shorter than any syllable, longer than a glottal
#: pulse, so a frame reads as either sound or not-sound rather than averaging
#: the two together.
FRAME = 0.02

#: Only gaps this long are asked about. Shorter ones are the ordinary pause
#: between two words, and there is nowhere in them for a retake to hide.
MIN_GAP = 1.0

#: And a gap has to hold this much sound to be worth a human's attention. A
#: click, a breath, or a chair creak does not reach it.
MIN_SOUND = 0.4

#: Where the threshold sits between the quiet tenth and speech level. 0.5 was
#: chosen to be obviously halfway rather than tuned — a real take clears it by
#: a wide margin, and tuning it against one video would be overfitting to that
#: video's noise floor.
THRESHOLD = 0.5

#: How far past the median a word's *duration* is believed when it is used to
#: mask the audio. Beyond this the word is masked for its first `CAP x median`
#: and the rest of its claimed span is treated as a hole to be measured.
#:
#: Without this the module cannot see the failure it was written for. A
#: collapsed retake does not leave a gap in the transcript — it inflates the
#: following word until that word's duration *covers* the second take, which is
#: the whole reason a diff cannot find it. Masking by the claimed span therefore
#: masks the evidence: on the Scream VO the word "bit" claims 3.96 s with a
#: complete second reading of its sentence inside, and believing it hides
#: exactly the 4.12 s hole that the method says cannot hide.
#:
#: 3x is the same multiple ROADMAP § 2 flags suspect durations at, and the two
#: are the same observation: no word is three times the median long, so whatever
#: is in there is not the word.
CAP = 3.0

#: 16-bit full scale, for converting RMS to dBFS.
FULL_SCALE = 32768.0


class EnergyError(Exception):
    """Raised when audio cannot be decoded or the envelope cannot be judged."""


def decode(media: Path | str, *, rate: int = RATE) -> array.array:
    """Decode `media` to mono 16-bit PCM samples at `rate`.

    Straight off ffmpeg's stdout rather than through a temp file — the envelope
    is the only consumer and it wants the samples in memory anyway. A five
    minute render is ~4.8 MB at the default rate.
    """
    source = Path(media).expanduser()
    if not source.exists():
        raise EnergyError(f"no media to measure: {source}")

    cmd = [
        FFMPEG,
        "-v",
        "error",
        "-nostdin",
        "-i",
        str(source),
        "-vn",
        "-ac",
        "1",
        "-ar",
        str(rate),
        "-f",
        "s16le",
        "-",
    ]
    try:
        completed = subprocess.run(cmd, capture_output=True, check=True)
    except FileNotFoundError as exc:
        raise EnergyError(f"{FFMPEG} not found on PATH") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or b"").decode("utf-8", "replace").strip()
        raise EnergyError(f"ffmpeg could not decode {source.name}: {detail}") from exc

    raw = completed.stdout
    samples = array.array("h")
    # A truncated final sample would raise rather than be dropped, and a torn
    # last 20 ms is not worth failing a verify over.
    samples.frombytes(raw[: len(raw) - len(raw) % samples.itemsize])
    if not samples:
        raise EnergyError(
            f"{source.name} decoded to no audio at all — it has no audio track, "
            "or the track is empty"
        )
    return samples


def envelope(samples: Sequence[int], *, rate: int = RATE, frame: float = FRAME) -> list[float]:
    """RMS per fixed-length frame, in raw sample units.

    A trailing partial frame is dropped: it would be measured over fewer
    samples than every other frame and so read quieter than it is.
    """
    width = max(1, round(rate * frame))
    return [
        math.sqrt(sum(s * s for s in samples[i : i + width]) / width)
        for i in range(0, len(samples) - width + 1, width)
    ]


def _db(rms: float) -> float:
    """dBFS for an RMS in raw sample units, floored so silence is finite."""
    return 20.0 * math.log10(max(rms, 1e-6) / FULL_SCALE)


def _mask(spans: Sequence[tuple[float, float]], count: int, frame: float) -> list[bool]:
    """Which envelope frames a word covers."""
    covered = [False] * count
    for start, end in spans:
        lo = max(0, int(start / frame))
        hi = min(count, math.ceil(end / frame))
        for i in range(lo, hi):
            covered[i] = True
    return covered


def _runs(loud: Sequence[bool], lo: int, hi: int) -> list[tuple[int, int]]:
    """Contiguous above-threshold frame runs within [lo, hi)."""
    out: list[tuple[int, int]] = []
    start: int | None = None
    for i in range(lo, hi):
        if loud[i] and start is None:
            start = i
        elif not loud[i] and start is not None:
            out.append((start, i))
            start = None
    if start is not None:
        out.append((start, hi))
    return out


def _median_limit(spans: Sequence[tuple[float, float]], cap: float) -> float:
    durations = sorted(end - start for start, end in spans)
    return cap * durations[len(durations) // 2]


def believable(spans: Sequence[tuple[float, float]], *, cap: float = CAP) -> list[tuple[float, float]]:
    """Trim each span to a duration a single word could plausibly have.

    A word's *order* is reliable and its *duration* is not (CLAUDE.md), so the
    mask is built from what a word could have covered rather than what the
    transcript claims it did. See `CAP`.
    """
    if not spans:
        return []
    limit = _median_limit(spans, cap)
    return [(start, min(end, start + limit)) for start, end in spans]


def suspect_durations(
    spans: Sequence[tuple[float, float]], *, cap: float = CAP
) -> list[dict[str, Any]]:
    """Which spans, by index, claim more than `cap` times the median duration.

    The same rule `believable` masks by (see `CAP`), surfaced as a finding
    instead of only ever being consumed silently downstream. No word is
    legitimately three times the median word long, so whatever a span this
    long covers is not just the word — usually a swallowed retake
    (DOGFOOD.md § 2). PLAN.md § Suspect word durations at `attach-transcript`.
    """
    if not spans:
        return []
    limit = _median_limit(spans, cap)
    return [
        {
            "index": i,
            "start": round(start, 3),
            "end": round(end, 3),
            "duration": round(end - start, 3),
            "limit": round(limit, 3),
        }
        for i, (start, end) in enumerate(spans)
        if end - start > limit
    ]


def loud_gaps(
    spans: Sequence[tuple[float, float]],
    env: Sequence[float],
    *,
    frame: float = FRAME,
    min_gap: float = MIN_GAP,
    min_sound: float = MIN_SOUND,
    threshold: float = THRESHOLD,
    cap: float = CAP,
) -> dict[str, Any]:
    """Find holes in the word map that the audio says are not empty.

    `spans` is the word map — (start, end) per word, in the same clock as the
    envelope. It is trimmed by `believable` first: a word that claims four
    seconds is masking a hole rather than filling one.

    Returns the calibration it used alongside the gaps, because a result whose
    numbers cannot be checked is not evidence of anything.
    """
    if not env:
        raise EnergyError("no envelope to measure — the audio decoded to nothing")
    if not spans:
        raise EnergyError(
            "no words to mask the audio with, so every frame is a gap and the "
            "threshold has no speech to calibrate against"
        )

    claimed, spans = spans, believable(spans, cap=cap)
    doubted = sum(1 for a, b in zip(claimed, spans, strict=True) if b[1] < a[1])
    covered = _mask(spans, len(env), frame)
    speech = [_db(env[i]) for i, hit in enumerate(covered) if hit]
    if not speech:
        raise EnergyError(
            "the word map lands outside the audio entirely — the transcript and "
            "the media are not the same recording, or not the same clock"
        )

    # The quiet tenth of the *whole* file, not of the gaps: a file whose gaps
    # are all full of a retake would otherwise calibrate its floor off the
    # retake and then find nothing.
    ordered = sorted(_db(v) for v in env)
    quiet_db = ordered[len(ordered) // 10]
    speech_db = statistics.median(speech)
    threshold_db = quiet_db + threshold * (speech_db - quiet_db)

    loud = [_db(v) >= threshold_db for v in env]
    gaps: list[dict[str, Any]] = []

    # Between words only. The head and tail of a render legitimately hold a
    # title card, a music sting or a bed tail, and flagging those every time
    # would train a reader to skip the whole field.
    ordered_spans = sorted(spans)
    for (_, gap_start), (gap_end, _) in itertools.pairwise(ordered_spans):
        if gap_end - gap_start < min_gap:
            continue
        lo = min(len(env), math.ceil(gap_start / frame))
        hi = min(len(env), int(gap_end / frame))
        runs = _runs(loud, lo, hi)
        sound = sum(b - a for a, b in runs) * frame
        if sound < min_sound:
            continue
        longest = max(runs, key=lambda r: r[1] - r[0])
        gaps.append(
            {
                "start": round(gap_start, 3),
                "end": round(gap_end, 3),
                "duration": round(gap_end - gap_start, 3),
                "sound_seconds": round(sound, 3),
                # Every contiguous loud run in the gap, not just the longest —
                # a gap can hold more than one noise event, and `attenuate_noises`
                # (ops.py) needs each one addressed on its own.
                "runs": [
                    {
                        "start": round(a * frame, 3),
                        "end": round(b * frame, 3),
                        "duration": round((b - a) * frame, 3),
                        "peak_db": round(max(_db(env[i]) for i in range(a, b)), 1),
                    }
                    for a, b in runs
                ],
                "loudest_run": {
                    "start": round(longest[0] * frame, 3),
                    "end": round(longest[1] * frame, 3),
                    "duration": round((longest[1] - longest[0]) * frame, 3),
                },
                "peak_db": round(max(_db(env[i]) for i in range(lo, hi)), 1),
            }
        )

    return {
        "speech_db": round(speech_db, 1),
        "quiet_db": round(quiet_db, 1),
        "threshold_db": round(threshold_db, 1),
        "min_gap": min_gap,
        "min_sound": min_sound,
        # How many words claimed a duration long enough that the mask did not
        # believe it. A gap next to one of these is a gap the transcript was
        # actively hiding, not one it merely failed to fill.
        "doubted_durations": doubted,
        "gaps": gaps,
    }


def unaccounted_sound(media: Path | str, spans: Sequence[tuple[float, float]]) -> dict[str, Any]:
    """Decode `media` and report the gaps in `spans` that hold sound anyway."""
    return loud_gaps(spans, envelope(decode(media)))


def attenuate(
    media: Path | str,
    spans: Sequence[tuple[float, float]],
    *,
    db: float,
    has_video: bool,
    output: Path | str,
) -> Path:
    """Pull `spans` (in seconds, source clock) down `db` and write `output`.

    One ffmpeg pass, one `volume=<gain>:enable='between(t,a,b)'` filter per
    span, comma-chained (goodsometimes `music_bed.py --tame`'s mechanism,
    verbatim: same filter shape, same `10**(db/20)` linear gain). A gain step
    cannot be written into a compressed stream without decoding it, so audio is
    always re-encoded — `aac -b:a 320k` when there is a picture to keep the
    container's video codec compatible with, `pcm_s16le` when the source is
    audio-only. Picture, when there is one, is never touched: `-c:v copy`.

    This only ever *applies* spans it is given — deciding which events in a
    clip qualify as noise lives in `ops._classify_noise_events`, not here.
    """
    source = Path(media).expanduser()
    if not source.exists():
        raise EnergyError(f"no media to attenuate: {source}")
    if not spans:
        raise EnergyError("attenuate needs at least one span")

    destination = Path(output).expanduser()
    destination.parent.mkdir(parents=True, exist_ok=True)

    gain = 10 ** (db / 20)
    filt = ",".join(
        f"volume={gain:.4f}:enable='between(t,{start:.3f},{end:.3f})'" for start, end in spans
    )
    cmd = [FFMPEG, "-v", "error", "-nostdin", "-y", "-i", str(source), "-af", filt]
    if has_video:
        cmd += ["-c:v", "copy", "-c:a", "aac", "-b:a", "320k"]
    else:
        cmd += ["-c:a", "pcm_s16le"]
    cmd.append(str(destination))

    try:
        subprocess.run(cmd, capture_output=True, check=True)
    except FileNotFoundError as exc:
        raise EnergyError(f"{FFMPEG} not found on PATH") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or b"").decode("utf-8", "replace").strip()
        raise EnergyError(f"ffmpeg could not attenuate {source.name}: {detail}") from exc
    return destination
