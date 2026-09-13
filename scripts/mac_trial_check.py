#!/usr/bin/env python3
"""Judge a `scripts/mac_trial.sh` run, for the CI job that runs it unattended.

The kit was written for a person, who reads its report. Nothing in it fails:
`verify` and `frames` print their findings and exit 0 whether the render
agrees with the timeline or not, and the kit itself exits 0 after stopping at
a step. So a CI job gated on exit codes would go green on a render with the
retake still in it. This reads what the run printed and what it rendered:

- the log's summary says ALL STEPS RAN;
- `frames` reported `agrees: true`;
- `verify`'s similarity is at least 0.9 — `scripts/agent_trial.py`'s own
  floor, because whisper on another machine mishears the demo voice a word or
  two (this box's dry run heard "are" for "a" at 0.971) and a retake left in
  costs far more than that;
- the frames at 3 s and 10 s are the blue and rust b-roll, judged by mean
  colour against `make_demo.BROLL`'s own colours — DEMO.md § 7's "BLUE 3s" and
  "RUST 0s", the check a person makes by looking. The two colours are ~116
  apart in RGB, and a frame of the wrong clip, or of black, measured 112–116
  from the right one; this box's frames came back within 3.

    python scripts/mac_trial_check.py ~/lucid-mac-trial

Exit 1 on any failure. What it cannot say is anything a person would notice
and a number would not — that is what the tester's issue form is for.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from make_demo import BROLL

SIMILARITY_FLOOR = 0.9
#: Euclidean RGB distance a frame's mean colour may sit from its clip's colour.
COLOUR_TOLERANCE = 30
FRAMES = [("frame-3s.png", "BLUE"), ("frame-10s.png", "RUST")]


def step_json(log: str, step: str) -> dict | None:
    """The JSON a step printed: the first object after its `── <step>` header."""
    at = log.find(f"── {step}\n")
    if at < 0:
        return None
    brace = log.find("{", at)
    if brace < 0:
        return None
    try:
        value, _ = json.JSONDecoder().raw_decode(log, brace)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def mean_rgb(png: Path) -> tuple[int, int, int]:
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(png), "-vf", "scale=1:1:flags=area",
         "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        capture_output=True, check=True,
    ).stdout
    return raw[0], raw[1], raw[2]


def hex_rgb(colour: str) -> tuple[int, int, int]:
    return int(colour[1:3], 16), int(colour[3:5], 16), int(colour[5:7], 16)


def distance(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    return sum((x - y) ** 2 for x, y in zip(a, b)) ** 0.5


def check(trial: Path) -> list[tuple[bool, str]]:
    results: list[tuple[bool, str]] = []
    log_path = trial / "report.txt"
    log = log_path.read_text(errors="replace") if log_path.exists() else ""
    stopped = [line for line in log.splitlines() if line.startswith("STOPPED AT:")]
    results.append(("ALL STEPS RAN" in log, stopped[-1] if stopped else
                    "ALL STEPS RAN" if "ALL STEPS RAN" in log else f"no summary in {log_path}"))

    frames = step_json(log, "DEMO 6 frames")
    if frames is None:
        results.append((False, "frames: no output in the log"))
    else:
        line = (f"frames: agrees {frames.get('agrees')}, delta {frames.get('delta')} "
                f"({frames.get('expected_frames')} expected, {frames.get('target_frames')} in the file)")
        results.append((frames.get("agrees") is True, line))

    verify = step_json(log, "DEMO 6 verify")
    if verify is None:
        results.append((False, "verify: no output in the log"))
    else:
        similarity = verify.get("similarity")
        line = (f"verify: similarity {similarity} (floor {SIMILARITY_FLOOR}), "
                f"{verify.get('heard_words')} heard of {verify.get('expected_words')}, "
                f"{len(verify.get('dropped') or [])} dropped, {len(verify.get('repeated') or [])} repeated")
        results.append((isinstance(similarity, (int, float)) and similarity >= SIMILARITY_FLOOR, line))

    colours = {tag: hex_rgb(colour) for _, colour, tag in BROLL}
    for name, want in FRAMES:
        png = trial / name
        if not png.exists():
            results.append((False, f"{name}: missing"))
            continue
        got = mean_rgb(png)
        near = {tag: distance(got, rgb) for tag, rgb in colours.items()}
        nearest = min(near, key=near.get)
        line = f"{name}: mean rgb {got}, {near[want]:.0f} from {want} (tolerance {COLOUR_TOLERANCE}), nearest {nearest}"
        results.append((nearest == want and near[want] <= COLOUR_TOLERANCE, line))
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("trial", type=Path, help="the kit's working folder (~/lucid-mac-trial)")
    args = parser.parse_args()
    results = check(args.trial.expanduser())
    for ok, line in results:
        print(f"{'✓' if ok else '✗'} {line}")
    return 0 if all(ok for ok, _ in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
