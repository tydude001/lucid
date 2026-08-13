"""The vendored caption face, and the only check that settles which face drew.

`captions.font_match` asks fontconfig. This module asks the renderer. They are
different questions and this repo has measured them disagreeing: on this box
libass's first pick for `Noto Sans` is a Nerd Font symbol face that only
reaches the real one by failing to find `E`, and two styles `fc-match` calls
identical render 3593 RMSE apart (HISTORY.md § The approvals round, answered).
So a clean `resolves_to` is not a claim about the burn, and nothing here
replaces `font_match` — it answers the half `font_match` deliberately does not.

The vendoring is the other half. `captions.CAPTION_FONT` names `Outfit`, and
until now it resolved on this machine *by coincidence*: the file arrived in
`~/.local/share/fonts` months earlier, fetched by a sibling repo's brand-art
tooling for its own reasons. On a fresh box the caption default would have
substituted silently, with `verify`, `check_frames` and `caption-view` all
still clean — the failure shape PLAN.md § A default font describes and the one
`src/lucid/fonts/FONTS.md` exists to close.

Why the two burns end up identical for an absent family, traced through
`ffmpeg -v verbose` on this box: `DejaVu Sans` and a name that cannot exist are
both primary-picked to `NotoSansArabic-Bold`, both fail to find `H`, and both
fall back to `NotoSans-Bold.ttf`. The literal string `Noto Sans` is
primary-picked to a **Nerd Font symbol face**, fails `H` too, and falls back to
that same `NotoSans-Bold.ttf`. So all three draw their visible Latin glyphs out
of one file, and the only pixels that differ are the **space advance**, which
the primary font still supplies. That is why `fc-match` and the render
disagree, and why a probe has to compare against the machine's own substitute
rather than against any particular wrong answer: there are at least two
distinct flavours of wrong here and they do not look like each other.

No lucid imports on purpose. Nothing in `captions` calls into this module —
installing a face is a write into `$HOME` and stays an explicit op, so a burn
can never quietly move a render by installing something first.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

#: Where the faces ship inside the package.
VENDORED_DIR = Path(__file__).parent / "fonts"

#: A family name no box can have. `probe` burns a second frame under this to
#: calibrate itself: whatever libass draws for a name that cannot resolve is
#: what "substituted" looks like *on this machine, today*, so the comparison
#: needs no golden image and cannot rot when a font is installed or removed.
#: Deliberately not a plausible typo of a real family.
IMPOSSIBLE_FAMILY = "lucid No Such Face 0000"


class FontError(RuntimeError):
    """A vendored face could not be installed, or a probe could not be run."""


def user_font_dir() -> Path:
    """The directory fontconfig searches for a user's own faces.

    Resolved the way `/etc/fonts/fonts.conf` resolves it — `<dir
    prefix="xdg">fonts</dir>`, i.e. `$XDG_DATA_HOME/fonts` with
    `~/.local/share` as XDG's own default — rather than hardcoded, because a
    box that sets `XDG_DATA_HOME` would otherwise get a copy in a directory
    nothing reads and a report saying the font was installed.
    """
    base = os.environ.get("XDG_DATA_HOME") or ""
    root = Path(base).expanduser() if base.strip() else Path.home() / ".local" / "share"
    return root / "fonts"


def vendored() -> list[Path]:
    """Every face shipped in the package, in a stable order."""
    if not VENDORED_DIR.is_dir():
        return []
    return sorted(p for p in VENDORED_DIR.iterdir() if p.suffix.lower() in {".ttf", ".otf"})


def install(*, dest: Path | str | None = None) -> dict[str, Any]:
    """Put the vendored faces where fontconfig looks. Idempotent.

    Compares by *content*, not by name or mtime: a box that already has the
    face — this one does, byte-identical, from the NAS copy `branding.md`
    names as canonical — is left alone and reports `unchanged`, so running
    this is never a reason for a render to move.

    Copying a file into `$HOME` is a real side effect, which is why it is an
    explicit op rather than something `burn` does on the way past. The
    alternative shape — a generated `FONTCONFIG_FILE` threaded through every
    subprocess that resolves a font — is more hermetic and was rejected as the
    first build: it touches `fc-match`, ffmpeg and `magick` call sites for no
    measured benefit over a directory fontconfig already reads.
    """
    target = Path(dest).expanduser() if dest is not None else user_font_dir()
    faces = vendored()
    if not faces:
        raise FontError(
            f"no vendored faces in {VENDORED_DIR} — the package is incomplete, "
            "and the caption default will resolve to whatever fontconfig substitutes"
        )

    try:
        target.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise FontError(f"cannot create {target}: {exc}") from exc

    installed: list[dict[str, Any]] = []
    changed = False
    for face in faces:
        there = target / face.name
        if there.exists() and there.read_bytes() == face.read_bytes():
            installed.append({"file": face.name, "path": str(there), "state": "unchanged"})
            continue
        try:
            shutil.copyfile(face, there)
        except OSError as exc:
            raise FontError(f"cannot install {face.name} into {target}: {exc}") from exc
        changed = True
        installed.append({"file": face.name, "path": str(there), "state": "installed"})

    refreshed = _refresh_cache(target) if changed else None
    return {
        "dir": str(target),
        "on_fontconfig_path": _on_search_path(target),
        "faces": installed,
        "changed": changed,
        "cache_refreshed": refreshed,
    }


def _on_search_path(directory: Path) -> bool | None:
    """Does fontconfig actually search `directory`?

    None rather than False when `fc-list` cannot be run, for the reason
    `font_match` returns a null `available`: "we could not tell" and "no" are
    different answers, and reporting the first as the second sends someone
    reinstalling a font that is already found.

    **Both sides are resolved before they are compared**, which on this box is
    the difference between a right answer and a wrong one: `/home` is a
    symlink to `/var/home` under ostree, so `fc-list` reports a face at
    `/home/<user>/.local/share/fonts/...` while `Path.home()` resolves to
    `/var/home/<user>/...`. A raw prefix test calls the directory unsearched
    and tells someone to go installing a font fontconfig already reads.
    """
    try:
        found = subprocess.run(
            ["fc-list", "--format=%{file}\n"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if found.returncode != 0 and not found.stdout:
        return None
    wanted = directory.resolve()
    for line in found.stdout.splitlines():
        name = line.strip()
        if not name:
            continue
        try:
            if Path(name).resolve().parent == wanted:
                return True
        except OSError:  # a face on a mount that has since gone away
            continue
    return False


def _refresh_cache(directory: Path) -> bool | None:
    """Ask fontconfig to rescan, so the face is visible without a re-login."""
    try:
        done = subprocess.run(
            ["fc-cache", "-f", str(directory)],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return done.returncode == 0


# -- the probe ------------------------------------------------------------


#: Mixed case with round and straight forms, plus digits — a string whose
#: shape differs measurably between any two real faces. A probe on "III"
#: would compare two renders of a stroke and call unlike faces identical.
PROBE_TEXT = "Handgloves 0123 quick brown fox"


def _probe_ass(family: str, *, size: int, width: int, height: int) -> str:
    """A one-line ASS naming `family` and nothing else that could differ."""
    return "\n".join(
        [
            "[Script Info]",
            "Title: lucid font probe",
            "ScriptType: v4.00+",
            f"PlayResX: {width}",
            f"PlayResY: {height}",
            "WrapStyle: 2",  # no wrapping: a wrap would confound the comparison
            "ScaledBorderAndShadow: yes",
            "",
            "[V4+ Styles]",
            (
                "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
                "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, "
                "ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, "
                "MarginL, MarginR, MarginV, Encoding"
            ),
            (
                f"Style: probe,{family},{size},&H00FFFFFF,&H00FFFFFF,&H00000000,"
                "&H00000000,0,0,0,0,100,100,0,0,1,0,0,5,0,0,0,1"
            ),
            "",
            "[Events]",
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
            f"Dialogue: 0,0:00:00.00,0:00:05.00,probe,,0,0,0,,{PROBE_TEXT}",
        ]
    ) + "\n"


def _burn_probe(family: str, out: Path, *, size: int, width: int, height: int) -> None:
    """Burn one frame of `PROBE_TEXT` in `family`, on black.

    The ASS is staged beside the output under a fixed name and ffmpeg is run
    from that directory, for the reason `captions.burn` does the same: the
    `ass=` argument lives inside a filtergraph where `:`, `,`, `'` and `\\`
    all have meaning.
    """
    script = out.parent / "probe.ass"
    script.write_text(_probe_ass(family, size=size, width=width, height=height), encoding="utf-8")
    done = subprocess.run(
        [
            "ffmpeg", "-v", "error", "-y",
            "-f", "lavfi", "-i", f"color=c=black:s={width}x{height}:d=1",
            "-vf", "ass=probe.ass",
            "-frames:v", "1", out.name,
        ],
        cwd=out.parent,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    if done.returncode != 0 or not out.exists():
        raise FontError(
            f"could not burn a probe for {family!r}: "
            f"{(done.stderr or '').strip()[-400:] or 'ffmpeg wrote nothing'}"
        )


def _rmse(a: Path, b: Path) -> float:
    """Root-mean-square difference between two renders, 0 for identical."""
    done = subprocess.run(
        ["magick", "compare", "-metric", "RMSE", str(a), str(b), "null:"],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    # `magick compare` writes the metric to stderr and exits non-zero when the
    # images differ, which is its normal case here, so the exit code says
    # nothing. The reading is `<absolute> (<normalised>)`.
    text = (done.stderr or done.stdout or "").strip()
    head = text.split("(")[0].strip().split()
    try:
        return float(head[-1])
    except (IndexError, ValueError):
        raise FontError(f"could not compare two probe renders: {text[-400:]!r}") from None


def _ink(png: Path) -> float:
    """Mean luminance of a render — how much was drawn at all."""
    done = subprocess.run(
        ["magick", str(png), "-format", "%[fx:mean]", "info:"],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    try:
        return float((done.stdout or "").strip())
    except ValueError:
        raise FontError(f"could not measure a probe render: {(done.stderr or '')[-400:]!r}") from None


def probe(family: str, *, size: int = 72, width: int = 1280, height: int = 200) -> dict[str, Any]:
    """Did `family` actually draw, or did something else draw for it?

    Burns `PROBE_TEXT` twice — once under `family`, once under a family that
    cannot exist — and compares the pixels. **Identical renders mean the name
    is not drawing**, whatever `fc-match` says, because a name libass cannot
    resolve and a name it will not resolve reach the same substitute.

    That second burn is the whole design. The obvious probe compares against a
    stored reference image, which rots the moment a face is updated and cannot
    be shipped for a family lucid does not vendor. Calibrating against the
    machine's own substitute costs one extra frame and answers the question
    for any family, on any box, with no stored state.

    `ink` guards the one way this could be quietly meaningless: two renders of
    *nothing* are also identical. A probe whose frames are blank is reported
    rather than scored.

    What it does not answer: **which** face drew when the answer is "not this
    one". `font_match`'s `resolves_to` is fontconfig's guess at that, and this
    repo has measured libass disagreeing with it, so the two are reported
    side by side and neither is folded into the other.
    """
    with tempfile.TemporaryDirectory(prefix="lucid-font-probe-") as tmp:
        root = Path(tmp)
        named, control = root / "named.png", root / "control.png"
        _burn_probe(family, named, size=size, width=width, height=height)
        _burn_probe(IMPOSSIBLE_FAMILY, control, size=size, width=width, height=height)
        difference = _rmse(named, control)
        ink = _ink(named)
        control_ink = _ink(control)

    blank = ink <= 0.0 or control_ink <= 0.0
    drew = None if blank else difference > 0.0
    report: dict[str, Any] = {
        "font": family,
        "drew": drew,
        "rmse_against_substitute": round(difference, 3),
        "ink": round(ink, 6),
        "control_ink": round(control_ink, 6),
        "control_family": IMPOSSIBLE_FAMILY,
    }
    if blank:
        report["warning"] = (
            "the probe drew nothing at all, so it says nothing about "
            f"{family!r} — check that ffmpeg has libass (`ffmpeg -filters | grep ass`)"
        )
    elif drew is False:
        report["warning"] = (
            f"{family!r} renders identically to a family that cannot exist, so libass "
            "is substituting — captions will draw in a face nobody chose, and ffmpeg "
            "will exit 0. `lucid fonts install` puts the vendored face where "
            "fontconfig looks."
        )
    return report
