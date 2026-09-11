"""`lucid doctor` — the probes, and the sentence after each ✗.

The report itself is trivially true on a working box, which is exactly why
these tests drive the *failing* shapes instead: a binary that is not there, an
auto-editor that is PyPI's stale fork, a melt that exits 0 with nothing to say,
a voice that is deliberately unset. Doctor's whole value is what it says in
those cases, so what is asserted is the named trap and the fix, not the ✗.

Every probe is monkeypatched at the resolver rather than shelled out, so this
file runs identically on a box with none of the six installed.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import pytest
from stubs import write_stub

from lucid import asr, autoeditor, doctor, graphics, ops, picture, tts
from lucid.cli import main


@pytest.fixture(autouse=True)
def _no_voice(monkeypatch: pytest.MonkeyPatch) -> None:
    """A voice on the developer's box would change what these tests measure."""
    monkeypatch.delenv("LUCID_TTS_VOICE", raising=False)


def _row(rows: list[dict[str, Any]], name: str) -> dict[str, Any]:
    return next(r for r in rows if r["name"] == name)


# -- shape ----------------------------------------------------------------


def test_every_row_carries_every_key() -> None:
    """A renderer should never need `.get` — an absent key and a null one
    would look the same to it, and one of them is a bug."""
    payload = doctor.report()
    keys = {"name", "what", "ok", "looked_for", "found", "version", "note", "why", "fix"}
    for row in payload["required"] + payload["optional"]:
        assert keys <= set(row), row["name"]


def test_ok_reads_the_required_section_alone(monkeypatch: pytest.MonkeyPatch) -> None:
    """An optional capability that is absent gates a feature, not the install."""
    monkeypatch.setattr(
        doctor, "_vlm_entry", lambda: doctor._entry("LUCID_VLM", "describe", ok=False)
    )
    monkeypatch.setattr(
        doctor, "_face_entry", lambda: doctor._entry("LUCID_FACE", "reframe", ok=False)
    )
    monkeypatch.setattr(doctor, "_tts_entry", lambda: doctor._entry("LUCID_TTS", "vo", ok=False))
    payload = doctor.report()
    assert payload["ok"] == all(r["ok"] for r in payload["required"])
    assert not any(r["ok"] for r in payload["optional"])


def test_doctor_needs_no_project(tmp_path: Path) -> None:
    """The one op that answers a question asked before a project exists."""
    assert ops.doctor()["lucid"]
    assert not list(tmp_path.iterdir())  # and it wrote nothing anywhere


# -- a missing required binary -------------------------------------------


def test_missing_ffmpeg_names_the_fix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(doctor.shutil, "which", lambda name: None)
    row = doctor._ffmpeg_entry("ffmpeg", "everything")
    assert row["ok"] is False
    assert "not on PATH" in row["why"]
    assert "install ffmpeg" in row["fix"]


def test_missing_whisper_carries_the_resolution_chain(monkeypatch: pytest.MonkeyPatch) -> None:
    """The chain is three steps and none of them is obvious, so it is printed."""

    def refuse() -> Path:
        raise asr.ASRError("whisper not found. Looked at $LUCID_WHISPER (unset), then PATH")

    monkeypatch.setattr(doctor.asr, "whisper_binary", refuse)
    row = doctor._whisper_entry()
    assert row["ok"] is False
    assert "LUCID_WHISPER" in row["looked_for"]
    assert "does not have to live in lucid's own venv" in row["fix"]


def test_whisper_on_disk_but_unstartable_is_not_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    """A venv that has lost torch resolves fine and dies minutes into a job."""
    monkeypatch.setattr(doctor.asr, "whisper_binary", lambda: Path("/nope/whisper"))
    monkeypatch.setattr(
        doctor, "_run", lambda cmd: ("", "ModuleNotFoundError: No module named 'torch'", 1)
    )
    row = doctor._whisper_entry()
    assert row["ok"] is False
    assert "cannot start" in row["why"]
    assert "torch" in row["fix"]


def test_whisper_without_word_timestamps_is_noted_not_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """It starts, so it is not broken — but every cut lucid makes is word-indexed."""
    monkeypatch.setattr(doctor.asr, "whisper_binary", lambda: Path("/bin/whisper"))
    monkeypatch.setattr(doctor, "_run", lambda cmd: ("usage: whisper [-h]", "", 0))
    row = doctor._whisper_entry()
    assert row["ok"] is True
    assert "--word_timestamps" in row["note"]


# -- auto-editor: the stale-fork trap ------------------------------------


def test_stale_auto_editor_is_refused_by_major(monkeypatch: pytest.MonkeyPatch) -> None:
    """29.3.1 is PyPI's fork of a different program wearing the same name."""
    monkeypatch.setattr(doctor.autoeditor, "binary", lambda: "/usr/bin/auto-editor")
    monkeypatch.setattr(doctor, "_run", lambda cmd: ("29.3.1\n", "", 0))
    row = doctor._auto_editor_entry()
    assert row["ok"] is False
    assert row["version"] == "29.3.1"
    assert "needs 31 or newer" in row["why"]
    assert "pip install auto-editor" in row["fix"]
    assert "GitHub release" in row["fix"]


def test_current_auto_editor_reports_the_gate_as_designed_around(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The paid-key gate is real and lucid routes around it — say so, don't scare."""
    monkeypatch.setattr(doctor.autoeditor, "binary", lambda: "/usr/bin/auto-editor")
    monkeypatch.setattr(doctor, "_run", lambda cmd: ("31.4.2\n", "", 0))
    row = doctor._auto_editor_entry()
    assert row["ok"] is True
    assert "Nothing here needs the key" in row["note"]


def test_absent_auto_editor_still_names_the_stale_pypi_build(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def refuse() -> str:
        raise autoeditor.AutoEditorError("auto-editor not found.")

    monkeypatch.setattr(doctor.autoeditor, "binary", refuse)
    row = doctor._auto_editor_entry()
    assert row["ok"] is False
    assert "stale fork" in row["fix"]


# -- melt: probed by output, never by exit code --------------------------


def test_melt_exiting_zero_with_no_banner_is_a_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """melt's exit code is evidence of nothing — CLAUDE.md, measured twice."""
    monkeypatch.setattr(sys, "platform", "linux")  # the fix names the flatpak there
    monkeypatch.setattr(doctor.picture, "melt_command", lambda: ["melt"])
    monkeypatch.setattr(doctor, "_run", lambda cmd: ("Failed to load\n", "", 0))
    row = doctor._melt_entry()
    assert row["ok"] is False
    assert "exit code is not evidence" in row["why"]
    assert "org.kde.kdenlive" in row["fix"]


def test_melt_banner_is_what_passes_it(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(doctor.picture, "melt_command", lambda: ["melt"])
    monkeypatch.setattr(doctor, "_run", lambda cmd: ("melt 7.40.0\nCopyright…\n", "", 0))
    row = doctor._melt_entry()
    assert row["ok"] is True
    assert row["version"] == "7.40.0"


def test_missing_melt_says_what_still_works(monkeypatch: pytest.MonkeyPatch) -> None:
    """Single-source cuts render without it; only layered timelines do not."""

    def refuse() -> list[str]:
        raise picture.PictureError("melt not found.")

    monkeypatch.setattr(doctor.picture, "melt_command", refuse)
    row = doctor._melt_entry()
    assert row["ok"] is False
    assert "single-source cuts still render through auto-editor" in row["fix"]


# -- magick ---------------------------------------------------------------


def test_magick_without_rsvg_is_noted(monkeypatch: pytest.MonkeyPatch) -> None:
    """A different SVG renderer draws cards nobody measured on this box."""
    monkeypatch.setattr(doctor.graphics, "magick_command", lambda: ["magick"])
    monkeypatch.setattr(
        doctor, "_run", lambda cmd: (("Version: ImageMagick 7.1.2-27 Q16", "", 0) if "-version" in cmd else ("PNG* rw+\n", "", 0))
    )
    row = doctor._magick_entry()
    assert row["ok"] is True
    assert "RSVG coder" in row["note"]


def test_missing_magick_says_everything_else_works(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse() -> list[str]:
        raise graphics.GraphicsError("magick not found.")

    monkeypatch.setattr(doctor.graphics, "magick_command", refuse)
    row = doctor._magick_entry()
    assert row["ok"] is False
    assert "everything else works" in row["fix"]


# -- the voice, which is a person and not tooling ------------------------


def test_unset_voice_is_an_expected_refusal_not_an_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "platform", "linux")  # the voice is asked after the device
    monkeypatch.setattr(doctor.tts, "tts_python", lambda: Path("/venv/bin/python"))
    monkeypatch.setattr(doctor.tts, "model_dir", lambda: Path("/models/Qwen3-TTS"))
    row = doctor._tts_entry()
    assert row["ok"] is False
    assert "no default voice on purpose" in row["why"]
    assert "expected refusal" in row["why"]
    assert "LUCID_TTS_VOICE" in row["fix"]


def test_a_configured_voice_never_has_its_path_printed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A voice is somebody's recorded speech; doctor prints on a shared screen."""
    voice = tmp_path / "private-voice"
    voice.mkdir()
    (voice / "ref.wav").write_bytes(b"")
    (voice / "ref.txt").write_text("hello", encoding="utf-8")
    monkeypatch.setenv("LUCID_TTS_VOICE", str(voice))
    monkeypatch.setattr(sys, "platform", "linux")  # the voice is asked after the device
    monkeypatch.setattr(doctor.tts, "tts_python", lambda: Path("/venv/bin/python"))
    monkeypatch.setattr(doctor.tts, "model_dir", lambda: Path("/models/Qwen3-TTS"))
    row = doctor._tts_entry()
    assert row["ok"] is True
    assert str(voice) not in json.dumps(row)
    assert "not printed" in row["note"]


def test_an_incomplete_voice_names_the_files_and_not_the_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    voice = tmp_path / "private-voice"
    voice.mkdir()
    (voice / "ref.wav").write_bytes(b"")
    monkeypatch.setenv("LUCID_TTS_VOICE", str(voice))
    monkeypatch.setattr(sys, "platform", "linux")  # the voice is asked after the device
    monkeypatch.setattr(doctor.tts, "tts_python", lambda: Path("/venv/bin/python"))
    monkeypatch.setattr(doctor.tts, "model_dir", lambda: Path("/models/Qwen3-TTS"))
    row = doctor._tts_entry()
    assert row["ok"] is False
    assert "ref.txt" in row["why"]
    assert str(voice) not in json.dumps(row)


def test_missing_synthesiser_is_reported_before_the_voice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def refuse() -> Path:
        raise tts.TTSError("no interpreter with a voice synthesiser.")

    monkeypatch.setattr(doctor.tts, "tts_python", refuse)
    row = doctor._tts_entry()
    assert row["ok"] is False
    assert "synthesiser" in row["why"]


# -- display --------------------------------------------------------------


def test_no_display_names_offscreen_rather_than_just_refusing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unattended box needs no session at all — say which variable to set."""
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(doctor.picture, "display_env", dict)
    monkeypatch.setattr(doctor.picture, "qt_is_headless", lambda env=None: False)
    display = doctor._display()
    assert display["ok"] is False
    assert "QT_QPA_PLATFORM=offscreen" in display["fix"]
    assert "still exit 0" in display["why"]


def test_headless_qt_counts_as_a_display(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(doctor.picture, "display_env", lambda: {"QT_QPA_PLATFORM": "offscreen"})
    display = doctor._display()
    assert display["ok"] is True
    assert display["headless_qt"] is True
    assert "no display server" in display["how"]


@pytest.mark.parametrize(("platform", "plugin"), [("darwin", "cocoa"), ("win32", "windows")])
def test_a_native_qt_platform_is_not_applicable_rather_than_a_pass_or_a_cross(
    monkeypatch: pytest.MonkeyPatch, platform: str, plugin: str
) -> None:
    """Windows has no `os.getuid`, so doctor raised there before it printed a
    line; and neither OS has a display server to find, so a ✗ would be wrong
    and a ✓ would claim a measurement nobody has made (PORTABILITY.md step 1)."""
    monkeypatch.setattr(sys, "platform", platform)
    monkeypatch.delattr(os, "getuid", raising=False)
    for name in ("WAYLAND_DISPLAY", "DISPLAY", "XDG_RUNTIME_DIR", "QT_QPA_PLATFORM"):
        monkeypatch.delenv(name, raising=False)

    display = doctor._display()
    assert display["ok"] is None
    assert display["applicable"] is False
    assert plugin in display["note"]

    text = doctor.render(
        {
            "lucid": "0.0.0",
            "ok": True,
            "required": [],
            "optional": [],
            "display": display,
            "caption_font": {"ok": True, "font": "Outfit", "resolves_to": "Outfit"},
        }
    )
    assert "– not applicable on this platform" in text
    assert "✗ no display" not in text
    assert "Everything required is here." in text


# -- the caption face -----------------------------------------------------


def test_a_substituted_caption_face_carries_the_install_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """libass substitutes and ffmpeg exits 0 — the only symptom is this check."""
    # fontconfig is asked on Linux only; off it, `test_portability` covers
    # the CoreText/DirectWrite branch, and the macOS runner met that one.
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(
        doctor.fonts,
        "probe",
        lambda family, **kw: {"drew": False, "warning": "renders identically to a family that cannot exist"},
    )
    monkeypatch.setattr(
        doctor.captions, "font_match", lambda name, **kw: {"available": False, "resolves_to": "DejaVu Sans"}
    )
    font = doctor._caption_font()
    assert font["ok"] is False
    assert font["resolves_to"] == "DejaVu Sans"
    assert "lucid fonts --install" in font["fix"]


def test_fontconfig_and_the_render_are_reported_side_by_side(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The two disagree on this box, so neither is folded into the other."""
    monkeypatch.setattr(sys, "platform", "linux")  # fontconfig is Linux's question
    monkeypatch.setattr(doctor.fonts, "probe", lambda family, **kw: {"drew": True})
    monkeypatch.setattr(
        doctor.captions,
        "font_match",
        lambda name, **kw: {"available": False, "resolves_to": "Noto Sans"},
    )
    font = doctor._caption_font()
    assert font["ok"] is True  # the render is what settles it
    assert font["fontconfig_available"] is False
    assert font["resolves_to"] == "Noto Sans"


# -- the human render, and the CLI ---------------------------------------


def test_render_puts_the_fix_under_every_cross() -> None:
    payload = {
        "lucid": "0.0.0",
        "ok": False,
        "required": [
            doctor._entry(
                "melt", "layered renders", why="not here", fix="flatpak install org.kde.kdenlive"
            )
        ],
        "optional": [],
        "display": {"ok": True, "how": "a Wayland session"},
        "caption_font": {"ok": True, "font": "Outfit", "resolves_to": "Outfit"},
    }
    text = doctor.render(payload)
    assert "✗ melt" in text
    assert "flatpak install org.kde.kdenlive" in text
    assert "Missing or unusable: melt." in text


def test_cli_doctor_exits_nonzero_when_something_required_is_missing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A command that always exits 0 cannot be gated on by a setup script."""
    broken = {
        "lucid": "0.0.0",
        "ok": False,
        "required": [doctor._entry("melt", "layered renders", why="not here", fix="install it")],
        "optional": [],
        "display": {"ok": True, "how": "a Wayland session"},
        "caption_font": {"ok": True, "font": "Outfit", "resolves_to": "Outfit"},
    }
    monkeypatch.setattr(ops, "doctor", lambda: broken)
    assert main(["doctor"]) == 1
    assert "install it" in capsys.readouterr().out


def test_cli_doctor_json_is_the_same_dict_the_tool_returns(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fine = {
        "lucid": "0.0.0",
        "ok": True,
        "required": [doctor._entry("melt", "layered renders", ok=True)],
        "optional": [],
        "display": {"ok": True, "how": "a Wayland session"},
        "caption_font": {"ok": True, "font": "Outfit", "resolves_to": "Outfit"},
    }
    monkeypatch.setattr(ops, "doctor", lambda: fine)
    assert main(["doctor", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["required"][0]["name"] == "melt"


# -- the agent panel -------------------------------------------------------


def test_an_absent_claude_is_unavailable_and_never_moves_ok(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The agent pane is one client's feature: missing is `–`, not a failure."""
    monkeypatch.setenv("LUCID_AGENT_BIN", "lucid-test-no-such-claude")
    payload = doctor.report()
    agent = payload["agent"]
    assert agent["ok"] is False
    assert "lucid-test-no-such-claude" in agent["why"]
    assert "LUCID_AGENT_BIN" in agent["fix"]
    assert payload["ok"] == all(r["ok"] for r in payload["required"])
    text = doctor.render(payload)
    assert "– claude" in text
    assert "✗ claude" not in text


def test_a_claude_is_run_for_its_version_rather_than_found(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Found-but-silent is not a pass — the rule every other probe holds to."""
    fake = write_stub(tmp_path / "claude", "print('9.9.9 (Claude Code)')\n")
    monkeypatch.setenv("LUCID_AGENT_BIN", str(fake))
    agent = doctor._agent()
    assert agent["ok"] is True
    assert agent["version"] == "9.9.9 (Claude Code)"

    assert write_stub(tmp_path / "claude", "raise SystemExit(3)\n") == fake
    agent = doctor._agent()
    assert agent["ok"] is False
    assert agent["found"] == str(fake)
    assert "exited 3" in agent["why"]
