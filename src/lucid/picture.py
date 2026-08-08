"""The picture half of checking a render, starting with the frame count.

`verify` re-transcribes a render and diffs word order; it covers the audio and
says so. This covers the picture, and the frame count ranks first of its three checks: exact agreement between lucid's
computed total and what `melt` says it will render is what made 68 cut
positions on the Scream essay trustworthy **before** anything was rendered
(HISTORY.md § 3). `blackdetect` (a black-run scan) and spot frames (sampled
PNGs with luma stats) are its siblings, reading a finished render directly
rather than a document melt would produce.

The check earns its place because the two numbers are arrived at differently.
lucid's total comes from quantising every segment edge onto the export's frame
grid (`autoeditor.frame_layout`). melt's comes from an MLT document auto-editor
wrote, in which the timeline's length is declared in several places at once and
**melt renders to the longest of them** — the failure goodsometimes
`pipeline.md` § Rendering documents for hand-written MLT, where four declared
lengths had to be swept in step and the one that actually bit was a black
background track nobody had touched.

`melt` is not a host package on this box; it ships inside the Kdenlive flatpak.
`melt_command` resolves it, and `display_env` carries the Qt trap that costs a
render its card track — both ported from goodsometimes `scripts/render.py`
rather than rediscovered.
"""

from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

#: Suffixes routed to `melt` rather than to ffprobe. `.xml` is here because
#: that is what a bare MLT document is called; auto-editor writes `.kdenlive`.
NLE_SUFFIXES = {".kdenlive", ".mlt", ".xml"}

KDENLIVE_FLATPAK = "org.kde.kdenlive"

#: How long to wait on a blackdetect pass — it decodes the whole render.
BLACKDETECT_TIMEOUT = 300

#: How long to wait on pulling one frame. Generous because a seek near the
#: start of a long file still has to demux up to it.
FRAME_EXTRACT_TIMEOUT = 60

_BLACK_RE = re.compile(
    r"black_start:(?P<start>[0-9.]+)\s+black_end:(?P<end>[0-9.]+)\s+black_duration:(?P<duration>[0-9.]+)"
)

#: How long to wait on melt. It is reading a document, not rendering one, so
#: this is generous — it exists because a cold flatpak start is slow and a
#: `melt` pointed at unreachable media can sit rather than fail.
MELT_TIMEOUT = 180

#: **auto-editor's `--export kdenlive` output is one frame too long, and the
#: extra frame is black.** Measured on this box 2026-08-07, auto-editor 31.x
#: against MLT 7.40: a 360-frame timeline came back from `-consumer xml` as
#: `length` 361, rendered 361 frames, and the last one measured YAVG 16 against
#: ~123 for real picture. A 276-frame cut of the same source reported 277, and
#: an audio-only export carried the same +1 — so it is structural, not a
#: rounding accident.
#:
#: The cause is the shape goodsometimes already documents from the other side:
#: MLT's `out` is frame-*inclusive*, and auto-editor writes the tractors' `out`
#: as the frame *count* instead of the last frame *index*. The entries
#: themselves are right (`out="00:00:11.967"` is frame 359, correct for 360
#: frames); the three tractors declaring `00:00:12.000` are not.
#:
#: This is named so a reader can tell it apart from a timeline that is
#: genuinely wrong. It is **not** subtracted anywhere: the frame is really in
#: the render, `agrees` stays False, and rendering with auto-editor directly
#: (`export --render`) does not have it — that path counted 360, exactly.
KNOWN_TAIL_FRAME = 1

TAIL_FRAME_NOTE = (
    "melt reports exactly one frame more than the timeline holds, which is the "
    "known auto-editor kdenlive-export defect rather than a wrong cut: it "
    "declares the tractors' frame-inclusive `out` as a frame count, so melt "
    "renders a trailing black frame. Reported, not corrected — the frame is "
    "really there. `export --render` (auto-editor's own renderer) does not "
    "have it. See picture.KNOWN_TAIL_FRAME."
)


class PictureError(Exception):
    """Raised when a picture-side check cannot be run or cannot be read."""


def melt_command() -> list[str]:
    """The argv prefix that runs `melt`, however it is installed here.

    Returns a list rather than a path because the flatpak form is four words
    and there is no binary to point at.
    """
    override = os.environ.get("LUCID_MELT")
    if override:
        return shlex.split(override)
    found = shutil.which("melt")
    if found:
        return [found]
    if shutil.which("flatpak"):
        installed = subprocess.run(
            ["flatpak", "info", KDENLIVE_FLATPAK], capture_output=True, text=True, check=False
        )
        if installed.returncode == 0:
            return ["flatpak", "run", "--command=melt", KDENLIVE_FLATPAK]
    raise PictureError(
        "melt not found. It has no host package on this box — it ships inside "
        f"the Kdenlive flatpak ({KDENLIVE_FLATPAK}), so either install that "
        "with `flatpak install org.kde.kdenlive`, or set LUCID_MELT to a melt "
        "command. Without it the timeline's own frame total is still reported; "
        "only the comparison against melt needs melt."
    )


def display_env() -> dict[str, str]:
    """Give MLT's Qt module a display, or it silently drops what it cannot load.

    Without `WAYLAND_DISPLAY` or `DISPLAY`, every `qimage` producer and the
    `qtblend` transition refuse to load and the render still exits 0 — a card
    track just vanishes (HISTORY.md § 4). Reading a document is less exposed
    than rendering one, but a project melt could not fully load is a project
    whose reported length is not the length it would render, so the display
    goes in either way.
    """
    env = dict(os.environ)
    if env.get("WAYLAND_DISPLAY") or env.get("DISPLAY"):
        return env
    runtime = Path(env.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}"))
    for socket in sorted(runtime.glob("wayland-*")):
        if socket.suffix != ".lock":
            env["WAYLAND_DISPLAY"] = socket.name
            return env
    if Path("/tmp/.X11-unix/X0").exists():
        env["DISPLAY"] = ":0"
    return env


def parse_melt_xml(document: str) -> int:
    """The frame count melt says it will render, out of `-consumer xml` output.

    melt flattens the whole project into one wrapping producer whose `length`
    property is that count. `length` and not the outer tractor's `out`, because
    MLT's `out` is frame-inclusive and the two differ by one — verified by
    rendering rather than reasoned about: a project reporting `length` 361
    produced exactly 361 frames.
    """
    try:
        root = ET.fromstring(document)
    except ET.ParseError as exc:
        raise PictureError(f"melt did not return a readable MLT document: {exc}") from exc

    for producer in root.iter("producer"):
        properties = {p.get("name"): (p.text or "").strip() for p in producer.findall("property")}
        if properties.get("mlt_service") == "xml" and properties.get("length", "").isdigit():
            return int(properties["length"])

    # No wrapping producer — read the outermost tractor instead, converting
    # MLT's inclusive `out` to a count so both paths return the same thing.
    outs = [t.get("out", "") for t in root.iter("tractor")]
    for out in reversed(outs):
        if out.isdigit():
            return int(out) + 1

    raise PictureError(
        "melt returned an MLT document with no frame count in it — neither a "
        "wrapping producer with a `length` property nor a tractor with a "
        "frame-numbered `out`."
    )


def project_frames(project: Path | str) -> int:
    """Ask melt how many frames it would render `project` to.

    `-consumer xml` resolves the document and prints what it would use without
    encoding anything, which is what makes this check cheap enough to run
    before committing to a render.
    """
    path = Path(project).expanduser()
    if not path.exists():
        raise PictureError(f"no such NLE project: {path}")

    command = [*melt_command(), str(path), "-consumer", "xml"]
    try:
        # `check=False` on purpose: melt exits 0 having failed to load a project
        # (see `_TMP_HINT`), so the return code proves nothing either way and the
        # output is the only evidence there is.
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            env=display_env(),
            timeout=MELT_TIMEOUT,
            check=False,
        )
    except FileNotFoundError as exc:
        raise PictureError(f"could not run melt: {' '.join(command)}") from exc
    except subprocess.TimeoutExpired as exc:
        raise PictureError(
            f"melt did not answer within {MELT_TIMEOUT}s for {path}. Usually the "
            "project references media it cannot reach — check that every "
            "`resource` path in it resolves."
        ) from exc

    if not completed.stdout.strip():
        detail = (completed.stderr or "").strip()
        raise PictureError(
            f"melt printed no timeline for {path}.\n{detail}"
            f"{_TMP_HINT if _invisible_to_flatpak(path, command) else ''}"
        )
    return parse_melt_xml(completed.stdout)


_TMP_HINT = (
    "\n\nThis project is under /tmp and melt is running from the flatpak, "
    "which cannot see the host's /tmp — `filesystems=host` does not cover it "
    "(HISTORY.md § 4). Note melt exits 0 while failing to load, so the only "
    "evidence is the empty output above. Export somewhere under $HOME instead."
)


def _invisible_to_flatpak(path: Path, command: list[str]) -> bool:
    """Is this the flatpak reading a path its sandbox does not have?"""
    return command[:1] == ["flatpak"] and path.resolve().is_relative_to(Path("/tmp"))


# -- reading a render directly: black runs and spot-checked frames -------


def parse_blackdetect(stderr: str) -> list[dict[str, float]]:
    """Every black_start/black_end/black_duration triple ffmpeg wrote to stderr.

    Split from `blackdetect()` for the same reason `parse_melt_xml` is split
    from `project_frames`: a parser is testable on a captured string, without
    a subprocess.
    """
    return [
        {"start": float(m["start"]), "end": float(m["end"]), "duration": float(m["duration"])}
        for m in _BLACK_RE.finditer(stderr)
    ]


def blackdetect(
    target: Path | str, *, pix_th: float = 0.10, min_duration: float = 0.1
) -> list[dict[str, float]]:
    """Scan a render for black stretches with ffmpeg's `blackdetect` filter.

    Decodes the whole file — there is no cheap document-only path here the
    way `project_frames` has with melt, because a black run is a property of
    the pixels, not of a declared length. `min_duration` is the caller's
    responsibility to set relative to the export's frame rate; this function
    keeps a generic standalone default since it does not know that rate.
    """
    path = Path(target).expanduser()
    if not path.exists():
        raise PictureError(f"no such file to scan for black: {path}")

    command = [
        "ffmpeg",
        "-i", str(path),
        "-vf", f"blackdetect=d={min_duration}:pix_th={pix_th}",
        "-an",
        "-f", "null",
        "-",
    ]  # fmt: skip
    try:
        completed = subprocess.run(
            command, capture_output=True, text=True, timeout=BLACKDETECT_TIMEOUT, check=False
        )
    except FileNotFoundError as exc:
        raise PictureError(f"could not run ffmpeg: {' '.join(command)}") from exc
    except subprocess.TimeoutExpired as exc:
        raise PictureError(
            f"ffmpeg did not finish scanning {path} for black within "
            f"{BLACKDETECT_TIMEOUT}s"
        ) from exc

    if completed.returncode != 0:
        raise PictureError(
            f"ffmpeg exited {completed.returncode} scanning {path} for black:\n"
            f"{completed.stderr[-2000:]}"
        )
    return parse_blackdetect(completed.stderr)


_STAT_RE = re.compile(r"lavfi\.signalstats\.(?P<key>\w+)=(?P<value>-?[0-9.]+)")


def parse_signalstats(output: str) -> dict[str, float]:
    """Every lavfi.signalstats.KEY=value line from a metadata=print dump.

    Keyed generically (YAVG, YMIN, YMAX, YDIF, ...) rather than hardcoding the
    handful one investigation needed — this is the same filter that measured
    `KNOWN_TAIL_FRAME` (YAVG 16 vs ~123). Named `output`, not `stdout`: verified
    against the installed ffmpeg (8.1.2) that `metadata=print` with no `file=`
    writes through the ordinary log, i.e. to **stderr**, not stdout — a
    training-prior trap of exactly the kind CLAUDE.md warns about.
    """
    return {m["key"]: float(m["value"]) for m in _STAT_RE.finditer(output)}


def extract_frame(target: Path | str, at: float, output: Path | str) -> dict[str, float]:
    """Pull one frame from `target` at `at` seconds, and report its luma stats.

    One ffmpeg call writes the PNG and prints its own signalstats — the filter
    doesn't touch pixels, so the frame it reports on is exactly the frame
    written, with no second pass to fall out of sync with the first.
    """
    path = Path(target).expanduser()
    if not path.exists():
        raise PictureError(f"no such file to pull a frame from: {path}")

    dest = Path(output).expanduser()
    dest.parent.mkdir(parents=True, exist_ok=True)

    command = [
        "ffmpeg", "-y",
        "-ss", f"{at:.6f}",
        "-i", str(path),
        "-frames:v", "1",
        "-an",
        "-vf", "signalstats,metadata=print",
        "-f", "image2",
        str(dest),
    ]  # fmt: skip
    try:
        completed = subprocess.run(
            command, capture_output=True, text=True, timeout=FRAME_EXTRACT_TIMEOUT, check=False
        )
    except FileNotFoundError as exc:
        raise PictureError(f"could not run ffmpeg: {' '.join(command)}") from exc
    except subprocess.TimeoutExpired as exc:
        raise PictureError(
            f"ffmpeg did not answer within {FRAME_EXTRACT_TIMEOUT}s pulling a "
            f"frame from {path} at {at:.3f}s"
        ) from exc

    if completed.returncode != 0 or not dest.exists():
        raise PictureError(
            f"ffmpeg could not pull a frame from {path} at {at:.3f}s "
            f"(exit {completed.returncode}):\n{completed.stderr[-2000:]}"
        )
    return parse_signalstats(completed.stderr)
