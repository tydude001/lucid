"""Probing the six external binaries lucid depends on, and naming their traps.

Every dependency here has a documented way of failing *silently* — that is the
whole reason this module exists. `melt` prints `Failed to load` and exits 0.
PyPI's auto-editor is a stale 29.x whose multi-source render degrades to
720x576 and exits 0. libass substitutes a font nobody chose and ffmpeg exits 0.
The repo's CLAUDE.md records each of them; a newcomer has none of that, so `lucid doctor`
probes each one and — when a probe fails — prints the named trap and the fix
rather than a bare ✗.

Two rules the probes hold to:

**Never trust an exit code where the repo has measured it lying.** melt is
probed by reading its `-version` banner out of stdout; whisper by reading its
own `usage:` line back. A subprocess that returns 0 with nothing to say is a
failure here, not a pass.

**Cost nothing.** Every probe on this box totals well under two seconds, which
is what makes doctor something to run first rather than something to be talked
into. Nothing loads a model, decodes a frame, or writes into the project — and
`report()` needs no project at all.

No lucid state is touched, and the only lucid imports are the resolver modules
whose answers are being reported, so doctor says exactly what the real ops
would resolve rather than a second opinion about it.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from lucid import (
    asr,
    autoeditor,
    captions,
    describe,
    faces,
    fonts,
    graphics,
    picture,
    tts,
)

#: The auto-editor major this repo is built against. 29.x is PyPI's stale fork
#: (CLAUDE.md) and is a different program wearing the same name, so the check
#: is a floor rather than a presence test.
MIN_AUTO_EDITOR = 31

#: Seconds. Generous, because the first `flatpak run` of a session pays a
#: cold start, and because a probe that times out reads as a broken binary.
PROBE_TIMEOUT = 60.0

#: auto-editor's paid-key gate, stated the way CLAUDE.md states it: a
#: condition lucid already designs around, not a warning to hand the user.
AUTO_EDITOR_GATE = (
    "31.x gates multi-*source* timelines behind a paid key — the render "
    "degrades to 720x576 and still exits 0. lucid designs around it: "
    "single-source goes through auto-editor, and anything layered (b-roll, "
    "cards, music) is written as MLT and rendered through melt, which has no "
    "source-count gate. Nothing here needs the key."
)


def _run(command: list[str]) -> tuple[str, str, int | None]:
    """Run `command`, returning (stdout, stderr, returncode) — never raising.

    `returncode` is `None` when the process could not be started or timed out,
    which is a different answer from a non-zero exit and is reported as one.
    """
    try:
        done = subprocess.run(
            command, capture_output=True, text=True, timeout=PROBE_TIMEOUT, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return "", "", None
    return done.stdout or "", done.stderr or "", done.returncode


def _entry(name: str, what: str, **fields: Any) -> dict[str, Any]:
    """One dependency row, with every key present so a renderer needs no `get`."""
    row: dict[str, Any] = {
        "name": name,
        "what": what,
        "ok": False,
        "looked_for": None,
        "found": None,
        "version": None,
        "note": None,
        "why": None,
        "fix": None,
    }
    row.update(fields)
    return row


# -- required ------------------------------------------------------------


def _ffmpeg_entry(binary: str, what: str) -> dict[str, Any]:
    """ffmpeg or ffprobe, both of which lucid calls by bare name on PATH."""
    found = shutil.which(binary)
    if not found:
        return _entry(
            binary,
            what,
            looked_for="PATH",
            why=f"{binary} is not on PATH",
            fix=(
                "install ffmpeg (it ships both binaries). Every media operation "
                "in lucid goes through them, so nothing works without this one."
            ),
        )
    out, err, _ = _run([found, "-version"])
    banner = (out or err).splitlines()
    version = None
    if banner and banner[0].startswith(f"{binary} version "):
        version = banner[0].split(" ", 2)[2].split(" ")[0]
    if version is None:
        return _entry(
            binary,
            what,
            looked_for="PATH",
            found=found,
            why=f"{found} ran but printed no version banner",
            fix=(
                f"check that {found} is really ffmpeg and not a wrapper — "
                "`ffmpeg -version` should print `ffmpeg version …` on its first line"
            ),
        )
    return _entry(binary, what, ok=True, looked_for="PATH", found=found, version=version)


def _whisper_entry() -> dict[str, Any]:
    """whisper, probed by reading its own usage line back.

    It is deliberately *run*: the failure this catches is an interpreter on
    PATH whose venv has lost torch, which resolves fine and dies minutes into
    a transcription. `--help` imports the package and costs about a second.
    """
    looked_for = f"$LUCID_WHISPER ({os.environ.get('LUCID_WHISPER') or 'unset'}), then PATH"
    try:
        binary = asr.whisper_binary()
    except asr.ASRError as exc:
        return _entry(
            "whisper",
            "transcription, and reading a render back to check it",
            looked_for=looked_for,
            why=str(exc),
            fix=(
                "install openai-whisper (`uv tool install openai-whisper`, or "
                "into any venv) and put its `whisper` on PATH, or point "
                "LUCID_WHISPER at the binary. lucid never imports it — it is a "
                "subprocess, so it does not have to live in lucid's own venv."
            ),
        )
    out, err, code = _run([str(binary), "--help"])
    text = out + err
    if "usage: whisper" not in text:
        return _entry(
            "whisper",
            "transcription, and reading a render back to check it",
            looked_for=looked_for,
            found=str(binary),
            why=(
                f"{binary} exited {code} without printing its usage line — it is "
                "on disk but cannot start"
                + (f": {text.strip().splitlines()[-1]}" if text.strip() else "")
            ),
            fix=(
                "that venv has lost a dependency (usually torch). Reinstall "
                "openai-whisper into it, or point LUCID_WHISPER at a venv that works."
            ),
        )
    note = None
    if "--word_timestamps" not in text:
        note = (
            "this build does not advertise --word_timestamps, which is the "
            "only thing lucid asks whisper for — every cut is addressed by "
            "word index. Check that it is openai-whisper and not a lookalike."
        )
    return _entry(
        "whisper",
        "transcription, and reading a render back to check it",
        ok=True,
        looked_for=looked_for,
        found=str(binary),
        note=note,
    )


def _auto_editor_entry() -> dict[str, Any]:
    """auto-editor, checked for presence *and* for a major of at least 31."""
    looked_for = (
        f"$LUCID_AUTO_EDITOR ({os.environ.get('LUCID_AUTO_EDITOR') or 'unset'}), "
        "then PATH, then ~/.local/bin/auto-editor"
    )
    stale_fix = (
        "install the auto-editor-linux-x86_64 binary from the GitHub release. "
        "`pip install auto-editor` gets 29.3.1 — a stale fork of the old "
        "Python program under the same name, which does not speak the v3 "
        "timeline lucid writes."
    )
    try:
        binary = autoeditor.binary()
    except autoeditor.AutoEditorError as exc:
        return _entry(
            "auto-editor",
            "silence removal, and rendering a single-source cut",
            looked_for=looked_for,
            why=str(exc),
            fix=stale_fix,
        )
    out, err, code = _run([binary, "--version"])
    version = (out or err).strip().splitlines()[0].strip() if (out or err).strip() else None
    if not version:
        return _entry(
            "auto-editor",
            "silence removal, and rendering a single-source cut",
            looked_for=looked_for,
            found=binary,
            why=f"{binary} exited {code} without printing a version",
            fix=stale_fix,
        )
    major = _major(version)
    if major is not None and major < MIN_AUTO_EDITOR:
        return _entry(
            "auto-editor",
            "silence removal, and rendering a single-source cut",
            looked_for=looked_for,
            found=binary,
            version=version,
            why=(
                f"this is {version}, and lucid needs {MIN_AUTO_EDITOR} or newer. "
                f"{version} is almost certainly PyPI's build."
            ),
            fix=stale_fix,
        )
    return _entry(
        "auto-editor",
        "silence removal, and rendering a single-source cut",
        ok=True,
        looked_for=looked_for,
        found=binary,
        version=version,
        note=AUTO_EDITOR_GATE,
    )


def _major(version: str) -> int | None:
    head = version.strip().lstrip("v").split(".", 1)[0]
    return int(head) if head.isdigit() else None


def _melt_entry() -> dict[str, Any]:
    """melt, probed by its banner — **never by its exit code** (CLAUDE.md).

    Pointed at a project it cannot read, melt prints `Failed to load` and
    exits 0, so a zero return here proves nothing. What is checked is that
    stdout carries melt's own `melt <version>` line.
    """
    looked_for = (
        f"$LUCID_MELT ({os.environ.get('LUCID_MELT') or 'unset'}), then PATH, "
        f"then the Kdenlive flatpak ({picture.KDENLIVE_FLATPAK})"
    )
    fix = (
        "melt has no host package on many boxes — it ships inside Kdenlive. "
        "`flatpak install org.kde.kdenlive`, or set LUCID_MELT to a melt "
        "command. Without it, single-source cuts still render through "
        "auto-editor; anything layered (b-roll, cards, music) does not."
    )
    try:
        command = picture.melt_command()
    except picture.PictureError as exc:
        return _entry(
            "melt",
            "rendering layered timelines — b-roll, cards, the music bed",
            looked_for=looked_for,
            why=str(exc),
            fix=fix,
        )
    out, err, code = _run([*command, "-version"])
    banner = next((ln for ln in (out + err).splitlines() if ln.startswith("melt ")), None)
    if banner is None:
        return _entry(
            "melt",
            "rendering layered timelines — b-roll, cards, the music bed",
            looked_for=looked_for,
            found=" ".join(command),
            why=(
                f"`{' '.join(command)} -version` exited {code} and printed no "
                "`melt …` banner. Its exit code is not evidence either way — "
                "melt exits 0 on failures it only mentions in its output."
            ),
            fix=fix,
        )
    return _entry(
        "melt",
        "rendering layered timelines — b-roll, cards, the music bed",
        ok=True,
        looked_for=looked_for,
        found=" ".join(command),
        version=banner.split(" ", 1)[1].strip(),
    )


def _magick_entry() -> dict[str, Any]:
    """ImageMagick 7, plus the RSVG coder cards are rasterised through."""
    looked_for = f"$LUCID_MAGICK ({os.environ.get('LUCID_MAGICK') or 'unset'}), then PATH"
    fix = (
        "install ImageMagick 7 (`magick`), or set LUCID_MAGICK to a command "
        "that runs it. IM6's `convert` is deliberately not searched: it is a "
        "different SVG renderer with different defaults. Without magick, title "
        "and end cards cannot be drawn; everything else works."
    )
    try:
        command = graphics.magick_command()
    except graphics.GraphicsError as exc:
        return _entry(
            "magick", "rasterising title and end cards", looked_for=looked_for, why=str(exc), fix=fix
        )
    out, err, code = _run([*command, "-version"])
    text = out + err
    line = next((ln for ln in text.splitlines() if "ImageMagick" in ln), None)
    if line is None:
        return _entry(
            "magick",
            "rasterising title and end cards",
            looked_for=looked_for,
            found=" ".join(command),
            why=f"`{' '.join(command)} -version` exited {code} and printed no ImageMagick banner",
            fix=fix,
        )
    version = line.split("ImageMagick", 1)[1].strip().split(" ")[0]
    formats, _, _ = _run([*command, "-list", "format"])
    note = None
    if "RSVG" not in formats:
        note = (
            "this build has no RSVG coder (`magick -list format | grep RSVG`), "
            "so card SVGs will rasterise through a different renderer than the "
            "one lucid's templates were measured on."
        )
    return _entry(
        "magick",
        "rasterising title and end cards",
        ok=True,
        looked_for=looked_for,
        found=" ".join(command),
        version=version,
        note=note,
    )


# -- optional ------------------------------------------------------------


def _optional(name: str, feature: str, report: dict[str, Any], **fields: Any) -> dict[str, Any]:
    """An optional capability. Missing is `unavailable`, never a failure.

    Everything lucid promises works without these, so a doctor run on a box
    with none of them is still a clean bill of health — `ok` on the report as
    a whole reads only the required section.
    """
    row = _entry(name, feature, ok=bool(report.get("available")), **fields)
    if not row["ok"]:
        row["why"] = report.get("why")
    return row


def _vlm_entry() -> dict[str, Any]:
    report = describe.available()
    row = _optional(
        "LUCID_VLM",
        "describe — searching b-roll by what is on screen",
        report,
        looked_for=f"$LUCID_VLM ({os.environ.get('LUCID_VLM') or 'unset'})",
        found=report.get("python"),
    )
    if not row["ok"]:
        row["fix"] = (
            "point LUCID_VLM at a python in a venv with torch, transformers, "
            "bitsandbytes and Pillow, on a machine with a CUDA GPU; the model "
            f"({describe.MODEL}) downloads on first use. `lucid describe --plan` "
            "reports the same answer without paying for a model load."
        )
    return row


def _face_entry() -> dict[str, Any]:
    report = faces.available()
    row = _optional(
        "LUCID_FACE",
        "reframe-detect — face-aware crop proposals when the canvas moves",
        report,
        looked_for=f"$LUCID_FACE ({os.environ.get('LUCID_FACE') or 'unset'})",
        found=report.get("python"),
    )
    if not row["ok"]:
        row["fix"] = (
            "point LUCID_FACE at a python in a venv with insightface, "
            "onnxruntime and opencv-python. Framing still works by hand (`lucid reframe`); only "
            "the proposals need this."
        )
    return row


def _tts_entry() -> dict[str, Any]:
    """The synthesiser, and — separately — whether a voice is configured.

    **The voice path is never reported.** A voice is a directory holding
    somebody's recorded speech, and doctor prints on a screen someone may be
    sharing; that it is set is the whole answer anyone needs. It has no
    default on purpose, so unset is an expected refusal rather than an error.
    """
    looked_for = f"$LUCID_TTS ({os.environ.get('LUCID_TTS') or 'unset'}), then {tts.SIBLING_VENV}"
    row = _entry(
        "LUCID_TTS",
        "vo-synth — synthesising a line in the project's own voice",
        looked_for=looked_for,
    )
    try:
        row["found"] = str(tts.tts_python())
        row["version"] = Path(str(tts.model_dir())).name
    except tts.TTSError as exc:
        row["why"] = str(exc)
        row["fix"] = (
            "point LUCID_TTS at a python with qwen-tts and a CUDA torch, and "
            "LUCID_TTS_MODEL at a local Qwen3-TTS snapshot. Everything else in "
            "lucid works without them."
        )
        return row

    voice = os.environ.get("LUCID_TTS_VOICE")
    if not voice:
        row["why"] = (
            "no voice is configured. There is no default voice on purpose — a "
            "voice is a person, not tooling — so this is an expected refusal, "
            "not a broken install."
        )
        row["fix"] = (
            "set LUCID_TTS_VOICE to a directory holding ref.wav (≈10–20 s of "
            "one speaker, no music) and ref.txt (its words), or pass "
            "`--voice <dir>` per call."
        )
        return row
    missing = [n for n in ("ref.wav", "ref.txt") if not (Path(voice).expanduser() / n).is_file()]
    if missing:
        row["why"] = f"the directory $LUCID_TTS_VOICE names is missing {', '.join(missing)}"
        row["fix"] = (
            "a voice is a directory holding ref.wav (≈10–20 s of one speaker, "
            "no music) and ref.txt (its words). Both are needed: the reference "
            "audio alone synthesises against whatever the model guessed the "
            "words were."
        )
        return row
    row["ok"] = True
    row["note"] = "a voice is configured (its path is deliberately not printed here)"
    return row


# -- display, and the caption face ---------------------------------------


def _display() -> dict[str, Any]:
    """Whether MLT's Qt module has something to draw into.

    Without one, every `qimage` producer and the `qtblend` transition refuse
    to load and **melt still exits 0** — the picture lane simply is not in the
    file. An unattended box does not need a session: `QT_QPA_PLATFORM=offscreen`
    draws with no display server at all, measured on this repo's own box, and
    doctor says so rather than reporting a bare "no display".
    """
    env = picture.display_env()
    headless = picture.qt_is_headless(env)
    wayland, x11 = env.get("WAYLAND_DISPLAY"), env.get("DISPLAY")
    report: dict[str, Any] = {
        "ok": bool(wayland or x11 or headless),
        "wayland_display": wayland,
        "display": x11,
        "xdg_runtime_dir": env.get("XDG_RUNTIME_DIR"),
        "qt_platform": env.get("QT_QPA_PLATFORM") or None,
        "headless_qt": headless,
        "why": None,
        "fix": None,
    }
    if report["ok"]:
        report["how"] = (
            "QT_QPA_PLATFORM draws with no display server"
            if headless
            else ("a Wayland session" if wayland else "an X11 session")
        )
        return report
    report["how"] = None
    report["why"] = (
        "MLT's Qt module has no display and no headless platform, so a layered "
        "render would drop every card and every `qtblend` transition — and melt "
        "would still exit 0."
    )
    report["fix"] = (
        "run this where a desktop session exists, or set "
        "QT_QPA_PLATFORM=offscreen, which is the route for any unattended "
        "render. `lucid export --render` refuses rather than rendering a film "
        "with its picture missing."
    )
    return report


def _caption_font() -> dict[str, Any]:
    """Does the default caption face actually draw, or is libass substituting?

    Two questions, kept apart because this repo has measured them disagreeing:
    `fonts.probe` asks the renderer whether the named family drew at all, and
    `captions.font_match` asks fontconfig which family it *thinks* resolves.
    A clean `resolves_to` is not a claim about the burn, so both are reported
    and neither is folded into the other.
    """
    family = captions.CAPTION_FONT
    report: dict[str, Any] = {
        "font": family,
        "ok": False,
        "drew": None,
        "resolves_to": None,
        "why": None,
        "fix": None,
    }
    try:
        drew = fonts.probe(family)
    except fonts.FontError as exc:
        report["why"] = str(exc)
        report["fix"] = (
            "the probe needs ffmpeg with libass (`ffmpeg -filters | grep ass`) "
            "and magick. Fix those first; captions cannot be burnt without them."
        )
        return report
    matched = captions.font_match(family)
    report["drew"] = drew.get("drew")
    report["resolves_to"] = matched.get("resolves_to")
    report["fontconfig_available"] = matched.get("available")
    report["ok"] = drew.get("drew") is True
    if report["ok"]:
        report["note"] = (
            "fontconfig's answer and the render's agree here. They do not "
            "always: a family fc-match calls installed can still burn in a "
            "substitute, which is why both are asked."
        )
        return report
    report["why"] = drew.get("warning") or (
        f"{family!r} could not be shown to draw — the probe rendered nothing at all"
    )
    report["fix"] = (
        "`lucid fonts --install` copies the vendored face where fontconfig "
        "looks. Until then captions burn in a face nobody chose and ffmpeg "
        "exits 0 about it."
    )
    return report


def _agent() -> dict[str, Any]:
    """The agent panel's `claude`, run for its version rather than found.

    Its own section, like the display: it is not a capability of lucid's
    engine but of one client — `lucid web`'s agent pane spawns `claude -p`
    and nothing else does — so absent is `–`, never a failure, and `ok` on
    the report does not read it. The binary is resolved by `webui._agent_bin`
    itself rather than restated, so this answers what the pane will spawn.
    Whether that `claude` is logged in is not probed: finding out costs a
    model call.
    """
    from lucid import webui

    binary = webui._agent_bin()
    found = shutil.which(binary)
    fix = (
        "install Claude Code (https://docs.claude.com/en/docs/claude-code) and "
        f"log in, or set {webui.AGENT_BIN_ENV} to its binary. Everything else — "
        "the CLI, `lucid mcp` for any MCP client, and the rest of the workspace "
        "— works without it."
    )
    if not found:
        return {
            "ok": False,
            "found": None,
            "version": None,
            "why": f"no `{binary}` on PATH — the workspace's agent pane has nothing to spawn",
            "fix": fix,
        }
    out, _err, code = _run([found, "--version"])
    version = out.strip().splitlines()[0] if out.strip() else None
    if code != 0 or not version:
        return {
            "ok": False,
            "found": found,
            "version": None,
            "why": f"{found} --version exited {code} without printing a version",
            "fix": fix,
        }
    return {"ok": True, "found": found, "version": version, "why": None, "fix": None}


# -- the report ----------------------------------------------------------


def report() -> dict[str, Any]:
    """Probe every dependency, and name the trap behind each one that fails.

    Report-only: nothing is installed, nothing is written, and no project is
    opened or needed. `ok` reads the **required** section alone — an optional
    capability that is absent is a feature that is unavailable, not a broken
    install, and everything lucid promises works without all three of them.
    """
    from lucid import __version__

    required = [
        _ffmpeg_entry("ffmpeg", "every media read, write and burn"),
        _ffmpeg_entry("ffprobe", "probing what a media file actually holds"),
        _whisper_entry(),
        _auto_editor_entry(),
        _melt_entry(),
        _magick_entry(),
    ]
    optional = [_vlm_entry(), _face_entry(), _tts_entry()]
    return {
        "lucid": __version__,
        "ok": all(entry["ok"] for entry in required),
        "required": required,
        "optional": optional,
        "display": _display(),
        "caption_font": _caption_font(),
        "agent": _agent(),
    }


# -- the human render ----------------------------------------------------

_TICK, _CROSS, _DASH = "✓", "✗", "–"


def _wrap(text: str, *, indent: str, width: int = 78) -> list[str]:
    """Wrap `text` to `width`, prefixing every line with `indent`."""
    lines, current = [], indent
    for word in text.split():
        candidate = f"{current} {word}" if current.strip() else f"{indent}{word}"
        if len(candidate) > width and current.strip():
            lines.append(current)
            current = f"{indent}{word}"
        else:
            current = candidate
    if current.strip():
        lines.append(current)
    return lines


def _render_entry(entry: dict[str, Any], *, optional: bool) -> list[str]:
    """One dependency, as the mark, the headline, and the sentence after it.

    The sentence after the mark is the whole value of doctor: knowing that
    melt is missing is worth very little, and knowing that it lives inside the
    Kdenlive flatpak is worth the command.
    """
    mark = _TICK if entry["ok"] else (_DASH if optional else _CROSS)
    head = f"  {mark} {entry['name']}"
    if entry["version"]:
        head += f" {entry['version']}"
    # `found` is shown even for a row that is not ok: "LUCID_TTS is here but
    # has no voice" and "LUCID_TTS is not here at all" are different answers,
    # and the path is what tells them apart at a glance.
    if entry["found"]:
        head += f" — {entry['found']}"
    lines = [head, *_wrap(entry["what"], indent="      ")]
    if entry["why"]:
        lines += _wrap(entry["why"], indent="      ")
    if not entry["ok"] and entry["looked_for"]:
        lines += _wrap(f"looked at: {entry['looked_for']}", indent="      ")
    if entry["fix"]:
        lines += _wrap(f"fix: {entry['fix']}", indent="      ")
    if entry["note"]:
        lines += _wrap(f"note: {entry['note']}", indent="      ")
    return lines


def render(payload: dict[str, Any]) -> str:
    """`report()` as something to read — the CLI's own rendering of the dict."""
    lines = [f"lucid {payload['lucid']}", ""]

    lines.append("Required")
    for entry in payload["required"]:
        lines += _render_entry(entry, optional=False)

    lines += ["", "Optional — every one of these gates a single feature"]
    for entry in payload["optional"]:
        lines += _render_entry(entry, optional=True)

    display = payload["display"]
    lines += ["", "Display (MLT's Qt module)"]
    if display["ok"]:
        lines.append(f"  {_TICK} {display['how']}")
    else:
        lines.append(f"  {_CROSS} no display")
        lines += _wrap(display["why"], indent="      ")
        lines += _wrap(f"fix: {display['fix']}", indent="      ")

    font = payload["caption_font"]
    lines += ["", "Caption font"]
    if font["ok"]:
        lines.append(f"  {_TICK} {font['font']} draws (fontconfig: {font['resolves_to']})")
    else:
        lines.append(f"  {_CROSS} {font['font']}")
        lines += _wrap(font["why"], indent="      ")
        lines += _wrap(f"fix: {font['fix']}", indent="      ")

    # `.get`, because the section is younger than the report's other keys and
    # a payload built by hand (the CLI's own tests build two) predates it.
    agent = payload.get("agent")
    if agent is not None:
        lines += ["", "Agent panel (`lucid web`'s agent pane — optional)"]
        if agent["ok"]:
            lines.append(f"  {_TICK} {agent['version']} — {agent['found']}")
        else:
            lines.append(f"  {_DASH} claude" + (f" — {agent['found']}" if agent["found"] else ""))
            lines += _wrap(agent["why"], indent="      ")
            lines += _wrap(f"fix: {agent['fix']}", indent="      ")

    failures = [e["name"] for e in payload["required"] if not e["ok"]]
    lines.append("")
    lines.append(
        "Everything required is here."
        if payload["ok"]
        else f"Missing or unusable: {', '.join(failures)}."
    )
    return "\n".join(lines)
