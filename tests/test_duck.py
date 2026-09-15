"""`duck.py` — the gate that pulls a music bed down under the voice.

The mechanism was chosen by scoring against Scream v8's bed recovered from its
render (HISTORY.md § The duck); these pin the pieces that choice rests on: a
quiet voice leaves the bed alone, a loud one takes it to the depth at the
attack's pace and lets it go at the release's, and the keyframes stay within
their tolerance of the envelope while writing nothing for a piece the voice
never touches.
"""

from __future__ import annotations

import math

import pytest

from proofcut import duck


def test_block_levels_reads_full_scale_and_silence() -> None:
    rate = 8000
    width = round(rate * duck.BLOCK)
    full = [32767, -32767] * width
    levels = duck.block_levels(full[: width * 2] + [0] * width, rate)

    assert levels[0] == pytest.approx(0.0, abs=0.01)
    assert levels[-1] == duck.FLOOR_DB


def test_a_voice_under_the_threshold_leaves_the_bed_alone() -> None:
    gains = duck.gate([-40.0] * 200, threshold_db=-24.0, depth_db=8.0)
    assert set(gains) == {0.0}


def test_the_gate_reaches_its_depth_at_the_attack_and_lets_go_at_the_release() -> None:
    blocks_on = 100
    gains = duck.gate([-10.0] * blocks_on + [-60.0] * 200, threshold_db=-24.0, depth_db=8.0)

    # One time constant in: 63% of the way down.
    attack_blocks = round(duck.ATTACK / duck.BLOCK)
    assert gains[attack_blocks] < -8.0 * 0.6
    assert gains[blocks_on - 1] == pytest.approx(-8.0, abs=0.01)
    # One release time constant after the voice stops: 37% of the depth left.
    release_blocks = round(duck.RELEASE / duck.BLOCK)
    assert gains[blocks_on - 1 + release_blocks] == pytest.approx(-8.0 * math.exp(-1), abs=0.2)
    assert gains[-1] > -0.1


def test_a_frame_takes_the_deepest_block_it_covers() -> None:
    envelope = [0.0] * 3 + [-5.0] + [0.0] * 10
    frames = duck.per_frame(envelope, rate=25.0, frames=3)  # 4 blocks a frame
    assert frames == [-5.0, 0.0, 0.0]


def test_simplify_stays_within_its_tolerance_and_keeps_both_ends() -> None:
    values = [-8.0 * math.exp(-i / 11) if i % 40 > 5 else -8.0 for i in range(400)]
    keys = duck.simplify(values, tolerance=0.5)

    assert keys[0][0] == 0 and keys[-1][0] == len(values) - 1
    assert len(keys) < len(values) / 4
    xs = [x for x, _ in keys]
    ys = [y for _, y in keys]
    for i, value in enumerate(values):
        j = max(k for k in range(len(xs)) if xs[k] <= i)
        line = ys[j] if xs[j] == i else ys[j] + (ys[j + 1] - ys[j]) * (i - xs[j]) / (xs[j + 1] - xs[j])
        assert abs(line - value) <= 0.5 + 1e-9


def test_keys_are_relative_to_the_piece_and_absent_where_nothing_ducks() -> None:
    frames = [0.0] * 50 + [-6.0] * 20 + [0.0] * 30

    assert duck.keys_for(frames, 0, 40) == ()
    keys = duck.keys_for(frames, 40, 40)
    assert keys[0][0] == 0 and keys[-1][0] == 39
    assert (10, -6.0) in keys
