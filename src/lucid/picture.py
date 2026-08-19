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

`render()` is the other half of that port: melt is also what *renders* a
multi-source timeline, since auto-editor degrades one to 720x576 while exiting
0 (CLAUDE.md). Its three traps and the memory cap are handled there, and
nothing about the render is believed on the strength of an exit code — the
finished file is probed, and the numbers it comes back with are compared
against the numbers the timeline promised.
"""

from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from lucid import media

#: Suffixes routed to `melt` rather than to ffprobe. `.xml` is here because
#: that is what a bare MLT document is called; auto-editor writes `.kdenlive`.
NLE_SUFFIXES = {".kdenlive", ".mlt", ".xml"}

KDENLIVE_FLATPAK = "org.kde.kdenlive"

#: How long to wait on a blackdetect pass — it decodes the whole render.
BLACKDETECT_TIMEOUT = 300

#: How long to wait on pulling one frame. Generous because a seek near the
#: start of a long file still has to demux up to it.
FRAME_EXTRACT_TIMEOUT = 60

#: How long to wait on rendering a tail's silence. Trivial work — `anullsrc`
#: reads nothing — so this is generous only for the same reason the others
#: are: a cold subprocess start, not the encode.
SILENCE_TIMEOUT = 30

#: The rate/layout every silent tail WAV is rendered at. Not derived from the
#: project — a tail's audio-track entry is played back through MLT the same
#: way any other audio-only clip is, resampled by the consumer to whatever it
#: needs, and 48kHz stereo is the shape `media.probe` already reports for real
#: footage on this box (tests/test_picture.py's own fixture).
SILENCE_SAMPLE_RATE = 48000

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

    **`WAYLAND_DISPLAY` alone is not a display**: it is a socket *name*, and Qt
    resolves it under `XDG_RUNTIME_DIR`. Both have to travel together, which
    they do not when lucid is launched from a scrubbed environment — the MCP
    stdio transport passes a handful of variables (HOME, PATH, USER, …) and
    `XDG_RUNTIME_DIR` is not among them. Measured 2026-08-08: naming the socket
    without the directory gives `Failed to create wl_display`, Qt then finds no
    platform plugin at all, and **melt aborts printing nothing** — which the
    empty-output guards read as a project that could not be loaded. So the
    directory this searched is exported alongside the socket it found.
    """
    env = dict(os.environ)
    runtime = Path(env.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}")
    if env.get("WAYLAND_DISPLAY") or env.get("DISPLAY"):
        if env.get("WAYLAND_DISPLAY") and (runtime / env["WAYLAND_DISPLAY"]).exists():
            env["XDG_RUNTIME_DIR"] = str(runtime)
        return env
    for socket in sorted(runtime.glob("wayland-*")):
        if socket.suffix != ".lock":
            env["WAYLAND_DISPLAY"] = socket.name
            env["XDG_RUNTIME_DIR"] = str(runtime)
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


# -- rendering a project: melt, its three traps, and the measurement -----


#: Where a render is staged before it is copied where it was asked for. Under
#: `$HOME` because the flatpak's `/tmp` is not the host's, and staged at all
#: because a render that dies halfway leaves a file behind — at the
#: destination it would be a half-muxed file that looks finished.
RENDER_SCRATCH = Path.home() / "lucid-render"

#: **The consumer gets the codec and nothing else.** Restating the project
#: profile on it is what unbounded memory growth correlated with: 2167 MB peak
#: with `vcodec crf preset acodec` alone, still climbing past 6873 MB once
#: `ab`, `width`, `height` and `progressive` were added, on the way to the
#: 14.6 GB that froze the machine. No single one of the four reproduces it
#: alone, so the rule is the whole list rather than a suspect (HISTORY.md § 4).
RENDER_ARGS = ("vcodec=libx264", "crf=18", "preset=medium", "acodec=aac")

#: The backstop for whatever the next surprise is: the render runs inside a
#: systemd scope that gets OOM-killed at this rather than swapping the desktop
#: out. Skipped — with a note in the reply, never silently — where
#: `systemd-run` is not available.
RENDER_MAX_MEMORY = "6G"
RENDER_MAX_SWAP = "1G"

#: How long to wait on an encode. Generous: this is a whole video through
#: libx264 at `preset=medium`, not a document being read.
RENDER_TIMEOUT = 4 * 3600

#: How far a render's duration may sit from the timeline's before it counts as
#: a disagreement. Only ever consulted for a render with **no frames to
#: count** — an audio-only one — where a container duration is all there is.
#: A frame of AAC is 1024 samples (~23 ms) and the muxer pads to it, so a
#: tolerance below that would fail correct renders.
RENDER_DURATION_TOLERANCE = 0.15


#: How long a staging directory a render left behind is kept before the next
#: render sweeps it. A failed render's directory survives on purpose — the
#: document melt was given is the evidence for what it did with it — but that
#: retention had no expiry, and 235 of them accumulated over ten days. Two
#: weeks is well past any live investigation.
SCRATCH_RETENTION_DAYS = 14

#: What `scratch()` is allowed to sweep: exactly the names it makes itself, a
#: known prefix followed by `mkdtemp`'s eight characters. Anything a person
#: named — `kf-manual`, `kf-mini` — fails this and is never touched, which is
#: the whole guard: the sweep runs unattended inside somebody else's render.
_SCRATCH_NAME = re.compile(r"^(?:render|timeline)-[a-z0-9_]{8}$")


def sweep_scratch(*, retention_days: int = SCRATCH_RETENTION_DAYS) -> list[Path]:
    """Drop staging directories older than `retention_days`. Never raises.

    A sweep is a side effect of doing something else, so a failure here must
    not fail the render that triggered it — every step is guarded and the
    return value is what actually went, not what was chosen.
    """
    if not RENDER_SCRATCH.is_dir():
        return []
    cutoff = time.time() - retention_days * 86400
    swept: list[Path] = []
    try:
        entries = sorted(RENDER_SCRATCH.iterdir())
    except OSError:
        return []
    for entry in entries:
        if not _SCRATCH_NAME.match(entry.name):
            continue
        try:
            #: `is_dir()` follows symlinks, and a link named like a staging
            #: directory would be read through to whatever it points at.
            #: `rmtree` refuses one anyway, but silently — say it here instead.
            if entry.is_symlink() or not entry.is_dir():
                continue
            if entry.stat().st_mtime >= cutoff:
                continue
        except OSError:
            continue
        shutil.rmtree(entry, ignore_errors=True)
        if not entry.exists():
            swept.append(entry)
    return swept


def scratch(prefix: str = "render-") -> Path:
    """A fresh working directory somewhere melt can actually read.

    Under `$HOME`, not `/tmp`: the flatpak cannot see the host's `/tmp` and
    exits 0 having read nothing (CLAUDE.md), so `tempfile.mkdtemp()`'s default
    would produce a project melt silently ignores.

    Making one is also when old ones go: `sweep_scratch` bounds a retention
    that otherwise had no expiry at all.
    """
    RENDER_SCRATCH.mkdir(parents=True, exist_ok=True)
    sweep_scratch()
    return Path(tempfile.mkdtemp(prefix=prefix, dir=RENDER_SCRATCH))


def render_problems(
    measured: dict[str, Any],
    *,
    expect_frames: int | None = None,
    expect_resolution: tuple[int, int] | None = None,
    expect_duration: float | None = None,
    tolerance: float = RENDER_DURATION_TOLERANCE,
) -> list[str]:
    """Every way this render disagrees with the timeline it was made from.

    Split from `render()` for the reason `parse_melt_xml` is split from
    `project_frames`: the interesting cases are a dict in and a list out, and
    stating them exactly should not cost an encode.

    The frame count is the check that matters and the resolution is the one
    that catches a degraded render. **Duration is a fallback, applied only
    when there are no frames to count** — an mp4's duration is the longest of
    its streams and an audio stream routinely outruns the video by a frame of
    AAC padding, so comparing it on a video render would fail correct ones.
    """
    problems: list[str] = []
    width, height = measured.get("width"), measured.get("height")
    if expect_resolution and measured.get("has_video") and (width, height) != expect_resolution:
        problems.append(
            f"rendered {width}x{height} where the timeline's profile declares "
            f"{expect_resolution[0]}x{expect_resolution[1]}. This is the shape a "
            "silently degraded render has (auto-editor's multi-source downgrade "
            "is 720x576, with exit 0) — the pixels, not the status, are what say so"
        )

    frames = measured.get("frames")
    if expect_frames is not None and frames is not None and frames != expect_frames:
        problems.append(
            f"rendered {frames} frames where the timeline is {expect_frames} "
            f"({frames - expect_frames:+d}). melt renders to the longest declared "
            "length in the document rather than to the playlist, so a difference "
            "here is a length that disagreed with the edit and padded or truncated it"
        )

    duration = measured.get("duration")
    if (
        expect_duration is not None
        and frames is None
        and duration is not None
        and abs(duration - expect_duration) > tolerance
    ):
        problems.append(
            f"rendered {duration:.3f}s where the timeline is {expect_duration:.3f}s. "
            "This render has no video stream, so its duration is the only length "
            f"there is to compare (tolerance {tolerance}s)"
        )
    return problems


def render(
    project: Path | str,
    output: Path | str,
    *,
    expect_frames: int | None = None,
    expect_resolution: tuple[int, int] | None = None,
    expect_duration: float | None = None,
    max_memory: str | None = RENDER_MAX_MEMORY,
    timeout: int = RENDER_TIMEOUT,
    consumer_args: tuple[str, ...] = RENDER_ARGS,
) -> dict[str, Any]:
    """Render an MLT project with `melt`, and check what actually came out.

    melt is the renderer for a multi-source timeline because auto-editor gates
    one to 720x576 while exiting 0 (CLAUDE.md). Its own three traps all produce
    output rather than an error, so all three are handled here rather than
    hoped past (HISTORY.md § 4):

    * **the codec and nothing else** goes on the consumer — `RENDER_ARGS` by
      default, or `consumer_args` — but never anything past those same four
      keys (`vcodec`/`crf`/`preset`/`acodec`): adding `ab`/`width`/`height`/
      `progressive` on top of them is what correlated with the unbounded
      memory growth this comment cites below, and no one has since isolated
      which of those additions was the cause. A caller may vary the *values*
      of the four measured-safe keys (`ops.EXPORT_PRESETS`); widening the key
      set itself needs that isolation work redone first;
    * **Qt needs a display**, or every `qimage` producer and the `qtblend`
      transition refuse to load, the picture lane vanishes and the render still
      exits 0. Missing one is a refusal here, not a warning, because the
      resulting file looks like a success;
    * **the flatpak's `/tmp` is not the host's**, so the staging directory is
      under `$HOME` (`scratch()`), and the project has to be somewhere melt can
      read too.

    Plus the memory cap `goodsometimes/scripts/render.py` added after a
    hand-run render filled 16 GB of swap and froze the machine.

    **The exit code is trusted for nothing.** The staged file is probed and its
    resolution, frame count and duration compared against what the timeline
    promised; only a render that agrees is copied to `output`. One that does
    not is left in its scratch directory and named in the error, because the
    evidence is the file.
    """
    path = Path(project).expanduser()
    if not path.exists():
        raise PictureError(f"no such NLE project to render: {path}")
    destination = Path(output).expanduser()

    env = display_env()
    if not (env.get("WAYLAND_DISPLAY") or env.get("DISPLAY")):
        raise PictureError(
            "no display for MLT's Qt module to open, so this render would drop "
            "every `qimage` producer and the `qtblend` transition — the picture "
            "lane would be missing and melt would still exit 0 (HISTORY.md § 4). "
            "Set WAYLAND_DISPLAY or DISPLAY, or run this where a session exists."
        )

    work = scratch("render-")
    staged = work / (destination.name or "render.mp4")
    melt = melt_command()
    command = [*melt, str(path), "-consumer", f"avformat:{staged}", *consumer_args]
    capped = bool(max_memory) and shutil.which("systemd-run") is not None
    if capped:
        command = [
            "systemd-run", "--user", "--scope", "--quiet",
            "-p", f"MemoryMax={max_memory}",
            "-p", f"MemorySwapMax={RENDER_MAX_SWAP}",
            "nice", "-n", "10",
            *command,
        ]  # fmt: skip

    try:
        completed = subprocess.run(
            command, capture_output=True, text=True, env=env, timeout=timeout, check=False
        )
    except FileNotFoundError as exc:
        raise PictureError(f"could not run melt: {' '.join(command)}") from exc
    except subprocess.TimeoutExpired as exc:
        raise PictureError(
            f"melt did not finish rendering {path} within {timeout}s. The partial "
            f"render is at {staged}."
        ) from exc

    if not staged.exists() or staged.stat().st_size == 0:
        detail = (completed.stderr or completed.stdout or "").strip()[-2000:]
        raise PictureError(
            f"melt rendered nothing for {path} (exit {completed.returncode}, which "
            f"proves nothing either way — the missing file is the finding).\n{detail}"
            f"{_TMP_HINT if _invisible_to_flatpak(path, melt) else ''}"
        )

    info = media.probe(staged)
    counts = media.count_frames(staged)
    measured: dict[str, Any] = {
        "width": info.width,
        "height": info.height,
        "frames": counts["frames"],
        "container_frames": counts["container_frames"],
        "duration": counts["duration"],
        "has_video": info.has_video,
        "has_audio": info.has_audio,
        "video_codec": info.video_codec,
        "audio_codec": info.audio_codec,
    }
    problems = render_problems(
        measured,
        expect_frames=expect_frames,
        expect_resolution=expect_resolution,
        expect_duration=expect_duration,
    )
    if problems:
        raise PictureError(
            f"the render disagrees with the timeline it was made from, so it has "
            f"not been copied to {destination}. It is at {staged}, kept so the "
            "numbers can be checked against it:\n- " + "\n- ".join(problems)
        )

    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(staged, destination)
    shutil.rmtree(work, ignore_errors=True)

    notes: list[str] = []
    if measured["frames"] is None:
        notes.append(
            "this render has no video stream, so there were no frames to count "
            "and its duration was compared instead"
        )
    if max_memory and not capped:
        notes.append(
            f"systemd-run is not available here, so the render ran without the "
            f"{max_memory} memory cap"
        )
    return {
        "output": str(destination),
        "project": str(path),
        "exit_code": completed.returncode,
        "memory_cap": max_memory if capped else None,
        "consumer": list(consumer_args),
        **measured,
        "expected_frames": expect_frames,
        "expected_resolution": list(expect_resolution) if expect_resolution else None,
        "agrees": True,
        "notes": notes,
    }


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


def render_silence(output: Path | str, seconds: float) -> Path:
    """Write a WAV of digital silence, at least `seconds` long.

    There is no silence producer in MLT's own vocabulary, and this is not one
    either — a tail's audio-track entry is an ordinary avformat clip like any
    other, and this is where the file it points at comes from, rendered the
    way a card PNG is rendered rather than checked in (PLAN.md § Tail time —
    the design note). `anullsrc` over `-t` is exact only to the encoder's own
    rounding, and a tail's requested length is quantised again onto whatever
    frame rate the project exports at — two roundings that need not agree — so
    this pads a half second past what was asked rather than matching it
    exactly. The MLT `Entry` built over the file states the tail's real frame
    count itself (`src_in`/`out`); the file only has to outlast it, the same
    way a still image's `IMAGE_LENGTH_SECONDS` outlasts every shot that could
    ever hold one.
    """
    if seconds <= 0:
        raise PictureError(f"silence must be a positive number of seconds, not {seconds}")

    dest = Path(output).expanduser()
    dest.parent.mkdir(parents=True, exist_ok=True)

    command = [
        "ffmpeg", "-y",
        "-f", "lavfi",
        "-i", f"anullsrc=channel_layout=stereo:sample_rate={SILENCE_SAMPLE_RATE}",
        "-t", f"{seconds + 0.5:.6f}",
        "-c:a", "pcm_s16le",
        str(dest),
    ]  # fmt: skip
    try:
        completed = subprocess.run(
            command, capture_output=True, text=True, timeout=SILENCE_TIMEOUT, check=False
        )
    except FileNotFoundError as exc:
        raise PictureError(f"could not run ffmpeg: {' '.join(command)}") from exc
    except subprocess.TimeoutExpired as exc:
        raise PictureError(
            f"ffmpeg did not answer within {SILENCE_TIMEOUT}s rendering {seconds}s of silence"
        ) from exc

    if completed.returncode != 0 or not dest.exists():
        raise PictureError(
            f"ffmpeg could not render {seconds}s of silence to {dest} "
            f"(exit {completed.returncode}):\n{completed.stderr[-2000:]}"
        )
    return dest
