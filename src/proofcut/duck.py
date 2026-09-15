"""The duck — a music bed pulled down under the voice and let back up in its pauses.

A bed at one level is louder than it should be under a line and quieter than it
could be in a pause. Scream v8's bed was ducked by a sidechain compressor keyed
off the VO (`goodsometimes/scripts/music_bed.py`), applied to the finished
render with ffmpeg, which is the step proofcut exists to own. So the duck here
is project state and rides the render: a gain envelope drawn as keyframes on
the bed's own `volume` filter (`mlt.Entry.gain_keys`), nothing after `melt`.

**It is driven by the Edit's audio, never by the transcript's words** — the
repo's standing rule (trust a transcript's word order, never its durations),
and measured here too: scored against v8's bed recovered from the render, a
duck gated on believable word spans was 3.39 dB off, barely better than no duck
at all (3.62), where a gate on the VO's own level was 2.72 and a full
compressor emulation 2.67 — within the measurement's noise of the gate, and a
compressor writes a key on almost every frame. HISTORY.md § The duck.

**A gate, not a compressor**: while the voice is above the threshold the bed
heads for `-depth` dB, and it comes back up when the voice stops. One number
to set, and the one a person means by "duck it 8 dB". The threshold is
relative to the VO's own integrated loudness, never an absolute dBFS — v8's
`threshold=0.03` was right for one recording's level and a VO 6 dB hotter
would have ducked on its breaths.

Stdlib only, `energy.py`'s reason.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

#: The detector's block, in seconds. Short enough that a syllable's onset
#: lands inside the attack, long enough to be an RMS rather than a sample.
BLOCK = 0.01

#: The gate opens where a block is this many LU above (negative: below) the
#: VO's integrated loudness. Fitted against Scream v8's recovered bed over
#: -8…0 on a 2 LU grid; -2 was the interior best.
THRESHOLD_LU = -2.0

#: Seconds to settle toward the ducked level (one-pole time constant) —
#: `music_bed.py`'s 15 ms. Under a frame at any rate proofcut renders, so on
#: the keyframe grid it reads as "ducked by the frame the word starts in".
ATTACK = 0.015

#: Seconds to settle back up — `music_bed.py`'s 380 ms, and the best of
#: 0.25/0.38/0.5 against v8. A *hold* (staying down for a while after the
#: voice stops) scored worse at every length tried, 0.1 through 0.3 s.
RELEASE = 0.38

#: How far, in dB, the keyframes may stray from the envelope they stand for.
#: 0.5 dB kept v8's fit (2.713 → 2.722) at 2799 keys over Scream's 10094
#: frames; 1.0 dB cost 2016 keys and more of the fit.
TOLERANCE_DB = 0.5

#: A silent block's level. Finite, so arithmetic on it stays finite.
FLOOR_DB = -120.0

#: Loud enough to count as one, in `mlt.Entry.gain_keys`'s units: a frame
#: ducked this far or further is reported as ducked.
DUCKED_DB = -3.0


def block_levels(samples: Sequence[int], rate: int, *, full_scale: float = 32768.0) -> list[float]:
    """dBFS per `BLOCK` of 16-bit samples. A trailing partial block is dropped."""
    width = max(1, round(rate * BLOCK))
    levels: list[float] = []
    for i in range(0, len(samples) - width + 1, width):
        block = samples[i : i + width]
        power = math.sumprod(block, block) / width
        levels.append(20.0 * math.log10(math.sqrt(power) / full_scale) if power > 0 else FLOOR_DB)
    return levels


def gate(
    levels: Sequence[float],
    *,
    threshold_db: float,
    depth_db: float,
    attack: float = ATTACK,
    release: float = RELEASE,
) -> list[float]:
    """The bed's gain in dB per block: 0 with the voice quiet, heading for
    `-depth_db` while it is above `threshold_db`, one-pole smoothed each way."""
    down = math.exp(-BLOCK / attack) if attack > 0 else 0.0
    up = math.exp(-BLOCK / release) if release > 0 else 0.0
    gain = 0.0
    out: list[float] = []
    for level in levels:
        target = -depth_db if level > threshold_db else 0.0
        coefficient = down if target < gain else up
        gain = coefficient * gain + (1.0 - coefficient) * target
        out.append(gain)
    return out


def per_frame(envelope: Sequence[float], *, rate: float, frames: int) -> list[float]:
    """The envelope on the render's frame grid: each frame takes the deepest
    block it covers, so a word starting mid-frame is ducked from that frame's
    start rather than the next one's."""
    out: list[float] = []
    for frame in range(frames):
        first = int(frame / rate / BLOCK)
        last = max(first + 1, math.ceil((frame + 1) / rate / BLOCK))
        window = envelope[first:last]
        out.append(min(window) if window else 0.0)
    return out


def simplify(values: Sequence[float], *, tolerance: float = TOLERANCE_DB) -> list[tuple[int, float]]:
    """`(index, value)` keys whose straight lines stay within `tolerance` of
    every value — Ramer–Douglas–Peucker, iterative, since a film is ten
    thousand frames and recursion is not. Both ends are always keys."""
    count = len(values)
    if count == 0:
        return []
    if count == 1:
        return [(0, values[0])]
    keep = {0, count - 1}
    stack = [(0, count - 1)]
    while stack:
        lo, hi = stack.pop()
        if hi - lo < 2:
            continue
        a, b = values[lo], values[hi]
        worst, at = -1.0, lo
        for i in range(lo + 1, hi):
            line = a + (b - a) * (i - lo) / (hi - lo)
            error = abs(values[i] - line)
            if error > worst:
                worst, at = error, i
        if worst > tolerance:
            keep.add(at)
            stack += [(lo, at), (at, hi)]
    return [(i, values[i]) for i in sorted(keep)]


def keys_for(
    frames_db: Sequence[float], start: int, frames: int, *, tolerance: float = TOLERANCE_DB
) -> tuple[tuple[int, float], ...]:
    """`mlt.Entry.gain_keys` for a piece playing `frames` frames from `start`
    on the envelope's own grid: offsets relative to the piece, and nothing at
    all when the voice never ducks it — an entry with no keys writes the
    document it wrote before the duck existed."""
    window = [frames_db[i] if 0 <= i < len(frames_db) else 0.0 for i in range(start, start + frames)]
    if not any(value < -tolerance for value in window):
        return ()
    return tuple((offset, round(value, 2)) for offset, value in simplify(window, tolerance=tolerance))
