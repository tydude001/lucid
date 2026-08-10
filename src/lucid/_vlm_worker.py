"""The vision-model side of `describe`, run under a *different* interpreter.

**This module is never imported by lucid.** It is executed by the Python that
`describe.vlm_python()` resolves — a venv with torch, transformers and
bitsandbytes in it — which is the whole reason it is a separate file. lucid's
own venv stays free of torch, exactly as `asr.py` keeps whisper behind a
binary. It lives inside the package only so it ships with it.

It reads one JSON job from `argv[1]` and writes one JSON result to `argv[2]`.
A file rather than stdout because transformers, bitsandbytes and torch all
write to whichever stream they feel like, and a progress bar landing in the
middle of a JSON document is a parse error that reads like a model failure.

The model is loaded **once** for the whole job — every window of every clip
goes through one process. Loading is ~15s and the description of a single
window is ~3s, so a process per window would spend more time loading than
describing.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def _frames(media: str, timestamps: list[float], size: str) -> list:
    """Pull one RGB frame per timestamp, through the ffmpeg binary.

    Deliberately not `ffmpeg-python`: this file's dependencies are whatever
    the resolved interpreter happens to have, and every extra import is
    another way for it to fail on a box that could otherwise describe.
    torch, transformers, numpy and PIL are unavoidable; a convenience wrapper
    around a subprocess is not.
    """
    import numpy as np
    from PIL import Image

    width, height = (int(x) for x in size.split("x"))
    out = []
    for ts in timestamps:
        completed = subprocess.run(
            [
                "ffmpeg", "-nostdin", "-v", "error",
                "-ss", f"{ts:.3f}", "-i", media,
                "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24",
                "-s", size, "pipe:",
            ],
            capture_output=True,
            check=True,
        )
        want = width * height * 3
        if len(completed.stdout) < want:
            raise RuntimeError(
                f"ffmpeg returned {len(completed.stdout)} bytes for the frame at "
                f"{ts:.2f}s, wanted {want} — seeking past the end of {media}?"
            )
        buf = np.frombuffer(completed.stdout[:want], np.uint8).reshape(height, width, 3)
        out.append(Image.fromarray(buf))
    return out


def main() -> int:
    job = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    destination = Path(sys.argv[2])

    # The loader and the generation pass come from vaultmedia's tagger_core —
    # the measured-working 4-bit config, reused rather than reimplemented.
    # Its *prompt and vocabulary* are specific to that repo's own library and are not
    # reused: lucid passes its own prompt (PLAN.md § B-roll by description).
    sys.path.insert(0, job["tagger_dir"])
    import tagger_core

    model, processor = tagger_core.load_qwen()

    results = []
    for window in job["windows"]:
        try:
            frames = _frames(window["media"], window["timestamps"], job["frame_size"])
            text = tagger_core.run_vlm(
                model, processor, frames, job["prompt"], max_new_tokens=job["max_new_tokens"]
            )
            results.append({"index": window["index"], "text": text})
        except Exception as exc:  # noqa: BLE001 — reported per window, not fatal
            results.append({"index": window["index"], "error": f"{type(exc).__name__}: {exc}"})
        # Freeing between windows is what keeps peak VRAM at one window's
        # worth rather than the run's. This box has 11.5 GiB usable and an
        # always-on llama-server holding 3.5 of it.
        _empty_cache()

    destination.write_text(json.dumps({"results": results}), encoding="utf-8")
    return 0


def _empty_cache() -> None:
    import torch

    torch.cuda.empty_cache()


if __name__ == "__main__":
    raise SystemExit(main())
