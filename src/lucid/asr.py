"""Running whisper as a subprocess.

Whisper is a binary here, not a library. Importing `whisper` into this process
would pull torch and a GPU context into every `lucid` invocation — including
`lucid status`, which needs neither — so ASR stays behind `subprocess`, the
same shape as ffmpeg and auto-editor.

**It is not on PATH on this box.** The working install is openai-whisper inside
a sibling project's venv, which is why the resolution order below ends in a
hardcoded path rather than an error. `LUCID_WHISPER` overrides it anywhere
else.

Failures are frequently opaque: when another job holds the GPU, whisper exits
non-zero with the real reason buried several frames up a CUDA traceback. So the
tail of stderr is carried into the exception rather than dropped.

This module has no lucid dependencies on purpose — `verify` uses it now and the
`transcribe` tool will use it next.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

#: openai-whisper's default. `turbo` is ~8x faster than `large-v3` at close to
#: its accuracy, which is the right trade for checking a render.
DEFAULT_MODEL = "turbo"

#: The install that actually exists here — the same one goodsometimes'
#: scripts/clipcut.py hardcodes.
SIBLING_VENV = Path.home() / "projects" / "vaultmedia" / ".venv-tag" / "bin" / "whisper"


class ASRError(Exception):
    """Raised when whisper is missing, or fails on a media file."""


def whisper_binary() -> Path:
    """Locate the whisper binary: env override, then PATH, then the venv."""
    override = os.environ.get("LUCID_WHISPER")
    if override and Path(override).expanduser().exists():
        return Path(override).expanduser()

    found = shutil.which("whisper")
    if found:
        return Path(found)

    if SIBLING_VENV.exists():
        return SIBLING_VENV

    raise ASRError(
        "whisper not found. Looked at $LUCID_WHISPER "
        f"({override or 'unset'}), then PATH, then {SIBLING_VENV}. "
        "Set LUCID_WHISPER to the binary in a venv that has openai-whisper."
    )


def transcribe(
    media: Path | str,
    *,
    model: str = DEFAULT_MODEL,
    language: str | None = None,
) -> dict[str, Any]:
    """Transcribe `media` with word timestamps, returning whisper's JSON.

    The output lands in a temporary directory and is read back rather than
    written beside the media: callers decide where a transcript belongs, and
    dropping a `.json` next to someone's render is not lucid's call.

    Deliberately no timeout. A five-minute render legitimately takes minutes on
    this box, and killing a nearly-finished transcription is worse than waiting.
    """
    source = Path(media).expanduser()
    if not source.exists():
        raise ASRError(f"no media to transcribe: {source}")

    binary = whisper_binary()
    with tempfile.TemporaryDirectory(prefix="lucid-asr-") as tmp:
        cmd = [
            str(binary),
            str(source),
            "--model",
            model,
            "--output_format",
            "json",
            "--word_timestamps",
            "True",
            "--output_dir",
            tmp,
        ]
        if language:
            cmd += ["--language", language]

        try:
            subprocess.run(cmd, capture_output=True, text=True, check=True)
        except FileNotFoundError as exc:
            raise ASRError(f"{binary} is not executable") from exc
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or exc.stdout or "").strip().splitlines()
            raise ASRError(
                f"whisper failed on {source.name} (model {model}). It fails this "
                "way when another job holds the GPU — check `nvidia-smi`.\n"
                + "\n".join(detail[-12:])
            ) from exc

        # whisper names the output after the input stem, in --output_dir.
        written = Path(tmp) / f"{source.stem}.json"
        if not written.exists():
            found = ", ".join(sorted(p.name for p in Path(tmp).iterdir())) or "nothing"
            raise ASRError(
                f"whisper exited cleanly but wrote no {written.name} ({found} instead)"
            )
        return json.loads(written.read_text(encoding="utf-8"))
