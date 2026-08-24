#!/usr/bin/env python3
"""Build the demo footage `docs/DEMO.md` walks through — nothing is vendored.

The README quickstart assumes you have a voiceover with retakes lying around.
Most people do not, and a demo you can run in two minutes is the difference
between reading about lucid and using it (POLISH.md § Step 02).

**Everything here is generated, and that is the design.** The repo carries no
media at all: the voiceover is synthesised from a script written a few lines
below, and the b-roll is ffmpeg's own test sources. Nothing to licence,
nothing to keep in step with an upstream, and the repo does not grow. It also
means the demo is *inspectable* — you can read exactly what the narrator is
about to say, including the fluff the walkthrough cuts out.

The voiceover carries a **deliberate retake**: the narrator starts a sentence,
stops, and says it again. That is the thing lucid was built to remove, and
cutting it is what `docs/DEMO.md` does. The two takes are rendered separately
and joined with real silence between them, exactly the way a retake sits in a
real recording — which is what makes the cut land in silence rather than
clipping a consonant.

The b-roll is two clips that could not be confused for each other and whose
every second names itself (a burnt-in counter over a flat colour), the same
precedent the repo already uses when the question is "which source second is
this" — see CLAUDE.md. Real footage screenshots better and is the open half of
this step; synthetic footage is what ships by default because it costs nobody
a licence review.

    python scripts/make_demo.py ~/lucid-demo          # just the media
    python scripts/make_demo.py ~/lucid-demo --build  # ...and a seeded project

`--build` runs the same `lucid` commands `docs/DEMO.md` lists, so a reader can
skip ahead or check their own run against it.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

#: The narration, in the order it is spoken. `retake=True` marks the fluffed
#: take — the one `docs/DEMO.md` cuts. Kept as data rather than prose in a
#: string so the walkthrough can quote the exact words the transcript will
#: hold, and so a reader can see what is about to be removed before it is.
SCRIPT: list[tuple[str, bool]] = [
    ("This is a demo of lucid, a local first video editor.", False),
    ("Every cut you make names a, hmm, no, let me try that again.", True),
    ("Every cut you make names a word in the transcript.", False),
    ("So the edit stays addressable, and the render can be checked against it.", False),
]

#: Seconds of silence between takes. Long enough that auto-editor's silence
#: pass has something to find and that a cut boundary lands in quiet rather
#: than on a consonant, short enough that the demo is not mostly waiting.
GAP = 0.6

#: The two b-roll clips. Flat, unmistakable colours with a burnt-in second
#: counter, so a frame of the finished render says which clip it came from and
#: how far into it — the "every moment names itself" rule.
BROLL = [
    ("broll-blue.mp4", "#1b3a5c", "BLUE"),
    ("broll-rust.mp4", "#7a3218", "RUST"),
]
#: Long enough that either clip can carry a whole shot of the demo cut. A
#: shorter one is not wrong — `plan_picture` refuses a shot longer than its
#: asset rather than rewinding, which is the right behaviour and a bad first
#: five minutes.
BROLL_SECONDS = 12
BROLL_SIZE = "640x360"
BROLL_FPS = 24


class DemoError(RuntimeError):
    """A dependency is missing, or a generation step failed."""


def _require(binary: str, why: str, install: str) -> str:
    found = shutil.which(binary)
    if found is None:
        raise DemoError(f"{binary} is not on PATH — {why}. {install}")
    return found


def _run(command: list[str]) -> None:
    done = subprocess.run(command, capture_output=True, text=True, check=False)
    if done.returncode != 0:
        detail = (done.stderr or done.stdout or "").strip()[-600:]
        raise DemoError(f"{command[0]} failed:\n{' '.join(command)}\n{detail}")


def make_voiceover(out: Path) -> Path:
    """Render the script to one wav, with a real gap at every take boundary.

    Each line is synthesised on its own and the silences are inserted between
    them, rather than letting the synthesiser run the whole script: a
    text-to-speech pause is a comma's worth of breath, and a retake seam is
    the speaker stopping. The difference is exactly what the demo's cut needs
    to land in.
    """
    espeak = _require(
        "espeak-ng",
        "the demo voiceover is synthesised rather than vendored",
        "Install it (`dnf install espeak-ng`, `apt install espeak-ng`, "
        "`brew install espeak-ng`) — it is a few megabytes and is needed only "
        "to build the demo, never by lucid itself.",
    )
    _require("ffmpeg", "every media step goes through it", "Install ffmpeg.")

    work = out.parent / "_demo-parts"
    work.mkdir(parents=True, exist_ok=True)
    parts: list[Path] = []
    for index, (line, _retake) in enumerate(SCRIPT):
        raw = work / f"line{index}.wav"
        # `-s 150` is close to an unhurried read; the default gabbles.
        _run([espeak, "-w", str(raw), "-s", "150", line])
        if index:
            silence = work / f"gap{index}.wav"
            _run([
                "ffmpeg", "-y", "-v", "error",
                "-f", "lavfi", "-i", f"anullsrc=r=22050:cl=mono:d={GAP}",
                "-c:a", "pcm_s16le", str(silence),
            ])  # fmt: skip
            parts.append(silence)
        parts.append(raw)

    listing = work / "parts.txt"
    listing.write_text(
        "".join(f"file '{p.name}'\n" for p in parts), encoding="utf-8"
    )
    # Resampled to one rate on the way out: espeak-ng and the silence source
    # can disagree, and concat demuxing files that disagree is a fast way to
    # a wav whose declared duration is not its real one.
    _run([
        "ffmpeg", "-y", "-v", "error",
        "-f", "concat", "-safe", "0", "-i", str(listing),
        "-ar", "22050", "-ac", "1", "-c:a", "pcm_s16le", str(out),
    ])  # fmt: skip
    shutil.rmtree(work, ignore_errors=True)
    return out


def make_broll(directory: Path) -> list[Path]:
    """Two clips nobody could mix up, each second labelled with its own number."""
    _require("ffmpeg", "every media step goes through it", "Install ffmpeg.")
    made = []
    for name, colour, label in BROLL:
        dest = directory / name
        # `%{eif:t:d}` is ffmpeg's own frame-time expression — the counter is
        # the *source* second, which is the number a cue's `src_start` and a
        # contact sheet's label both quote.
        draw = (
            f"drawtext=text='{label} %{{eif\\:t\\:d}}s':font=sans:fontsize=48:"
            "fontcolor=white:x=(w-text_w)/2:y=(h-text_h)/2"
        )
        _run([
            "ffmpeg", "-y", "-v", "error",
            "-f", "lavfi",
            "-i", f"color=c={colour}:s={BROLL_SIZE}:r={BROLL_FPS}:d={BROLL_SECONDS}",
            "-vf", draw,
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(dest),
        ])  # fmt: skip
        made.append(dest)
    return made


def build_project(root: Path, media: Path) -> None:
    """Run the walkthrough's own commands, so `--build` and DEMO.md cannot drift."""
    lucid = [sys.executable, "-m", "lucid.cli"]
    steps = [
        [*lucid, "init", str(root)],
        [*lucid, "-C", str(root), "import", str(media / "vo.wav"), "--clip-id", "vo"],
        [*lucid, "-C", str(root), "import", str(media / "broll-blue.mp4"), "--clip-id", "blue"],
        [*lucid, "-C", str(root), "import", str(media / "broll-rust.mp4"), "--clip-id", "rust"],
        [*lucid, "-C", str(root), "transcribe", "vo"],
        [*lucid, "-C", str(root), "seed", "vo"],
    ]
    for step in steps:
        print("  $", " ".join(step[2:] if step[:2] == lucid[:2] else step))
        _run(step)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("dest", help="directory to write the demo media into")
    parser.add_argument(
        "--build",
        action="store_true",
        help="also create and seed a lucid project from it (needs whisper and auto-editor)",
    )
    args = parser.parse_args(argv)

    media = Path(args.dest).expanduser()
    media.mkdir(parents=True, exist_ok=True)
    try:
        print(f"voiceover  -> {media / 'vo.wav'}")
        make_voiceover(media / "vo.wav")
        for clip in make_broll(media):
            print(f"b-roll     -> {clip}")
        if args.build:
            root = media / "proj"
            print(f"project    -> {root}")
            build_project(root, media)
            print(f"\nOpen it:  lucid -C {root} open")
        else:
            print(f"\nNext:  {Path(__file__).parent.parent / 'docs' / 'DEMO.md'}")
    except DemoError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
