"""The Linux-shaped resolvers, widened, and the GPU workers — PORTABILITY.md steps 2 and 3.

Each resolver here found only what a Linux box has: melt in the Kdenlive
flatpak, auto-editor's Linux build, a chromium on PATH, `tailscale` on PATH,
fonts where fontconfig reads them. None of them crashed off Linux; each one
silently narrowed what a Mac or a Windows box could find. These tests stand
in for either OS by setting `sys.platform`, and every one of them also pins
what Linux still gets, since that is the only platform any of it has run on.

**None of this is a measurement of macOS or Windows.** The install locations
are leads the plan names; whether a Shotcut melt carries `qtblend`, or a
registered face draws under DirectWrite, is steps 4 and 5, on real machines.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import types
from pathlib import Path, PureWindowsPath
from typing import Self

import pytest

from lucid import (
    autoeditor,
    describe,
    doctor,
    fonts,
    media,
    picture,
    timeline,
    tts,
    webui,
)

_PROBE = media.MediaInfo(
    duration=5.0,
    has_video=True,
    has_audio=True,
    fps=30.0,
    width=1920,
    height=1080,
    sample_rate=48000,
    channels=2,
    video_codec="h264",
    audio_codec="aac",
    vfr=False,
)

# -- melt ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("platform", "bundle"),
    [("darwin", "Shotcut.app/Contents/MacOS/melt"), ("win32", "melt.exe")],
)
def test_melt_is_found_in_an_editor_bundle_off_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, platform: str, bundle: str
) -> None:
    """Shotcut and Kdenlive ship melt inside the app on both OSes and put
    neither on PATH, so PATH-then-flatpak found nothing on a Mac."""
    monkeypatch.setattr(sys, "platform", platform)
    monkeypatch.delenv("LUCID_MELT", raising=False)
    monkeypatch.setattr(picture.shutil, "which", lambda name: None)
    assert any(p.as_posix().endswith(bundle) for p in picture.melt_bundles())

    installed = tmp_path / "melt"
    installed.touch()
    monkeypatch.setattr(picture, "melt_bundles", lambda: [tmp_path / "absent", installed])
    assert picture.melt_command() == [str(installed)]


@pytest.mark.parametrize("platform", ["darwin", "win32"])
def test_melt_not_found_off_linux_names_the_editors_not_the_flatpak(
    monkeypatch: pytest.MonkeyPatch, platform: str
) -> None:
    """Doctor told a Mac to `flatpak install` — a package manager it has not got."""
    monkeypatch.setattr(sys, "platform", platform)
    monkeypatch.delenv("LUCID_MELT", raising=False)
    monkeypatch.setattr(picture.shutil, "which", lambda name: None)
    monkeypatch.setattr(picture, "melt_bundles", list)

    with pytest.raises(picture.PictureError) as refused:
        picture.melt_command()
    assert "Shotcut" in str(refused.value)
    assert "flatpak" not in str(refused.value)

    row = doctor._melt_entry()
    assert "Shotcut" in row["fix"] and "Shotcut" in row["looked_for"]
    assert "flatpak" not in row["fix"]
    assert "single-source cuts still render through auto-editor" in row["fix"]


def test_linux_still_looks_at_the_flatpak_and_no_bundle(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    assert picture.melt_bundles() == []
    where, install = picture.melt_search()
    assert picture.KDENLIVE_FLATPAK in where
    assert "flatpak install org.kde.kdenlive" in install


def test_linux_melt_advice_leads_with_the_distribution_package(monkeypatch: pytest.MonkeyPatch) -> None:
    """A clean Ubuntu 24.04 told only about the flatpak had a working `apt install
    melt` one line away. HISTORY.md § A stranger's install, on a clean Ubuntu."""
    monkeypatch.setattr(sys, "platform", "linux")
    _, install = picture.melt_search()
    assert "apt install melt" in install
    assert install.index("apt install melt") < install.index("flatpak install")
    assert "dnf install mlt" in install


def test_fedoras_mlt_is_found_ahead_of_its_freeze_melt(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fedora's `mlt` installs `mlt-melt` and `melt-7` and no `melt`, and its
    `melt` package is freeze, a compression tool. With both installed, a bare
    `melt` searched first rendered through freeze. HISTORY.md § A stranger's
    install, on a clean Fedora."""
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.delenv("LUCID_MELT", raising=False)
    fedora = {"melt": "/usr/bin/melt", "melt-7": "/usr/bin/melt-7", "mlt-melt": "/usr/bin/mlt-melt"}
    monkeypatch.setattr(picture.shutil, "which", fedora.get)
    assert picture.melt_command() == ["/usr/bin/mlt-melt"]

    only_mlt = {"melt-7": "/usr/bin/melt-7"}
    monkeypatch.setattr(picture.shutil, "which", only_mlt.get)
    assert picture.melt_command() == ["/usr/bin/melt-7"]


@pytest.mark.parametrize(
    ("platform", "note"),
    [("darwin", "Linux-only"), ("win32", "Linux-only"), ("linux", "systemd-run is not available")],
)
def test_the_uncapped_render_note_says_why_for_the_platform(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, platform: str, note: str
) -> None:
    """The memory cap is a systemd scope. "Not available here" on a Mac reads
    as something to install; it is something that does not exist there."""
    monkeypatch.setattr(sys, "platform", platform)
    monkeypatch.setenv("LUCID_MELT", "melt")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    # Named, so standing in for Linux on a Windows runner never reaches for
    # `os.getuid` to build `/run/user/<uid>` — Windows has none.
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    monkeypatch.setattr(picture, "RENDER_SCRATCH", tmp_path / "scratch")
    monkeypatch.setattr(picture.shutil, "which", lambda name: None)

    def fake_run(command: list[str], **kwargs: object) -> object:
        target = next(a for a in command if a.startswith("avformat:")).removeprefix("avformat:")
        Path(target).write_bytes(b"a render")
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(picture.subprocess, "run", fake_run)
    monkeypatch.setattr(picture.media, "probe", lambda p: _PROBE)
    monkeypatch.setattr(
        picture.media,
        "count_frames",
        lambda p: {"frames": 150, "container_frames": 150, "duration": 5.0, "has_video": True},
    )
    project = tmp_path / "timeline.mlt"
    project.write_text("<mlt/>", encoding="utf-8")

    result = picture.render(project, tmp_path / "out.mp4", expect_frames=150)
    assert result["memory_cap"] is None
    assert any(note in n for n in result["notes"])


@pytest.mark.parametrize("bus", [False, True])
def test_the_memory_cap_needs_a_user_bus_not_just_systemd_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, bus: bool
) -> None:
    """A clean Ubuntu container has `systemd-run` on PATH and no user session
    bus, so every capped render died with "Failed to connect to bus" before melt
    started, and was reported as "melt rendered nothing". On PATH is not the
    same as usable. HISTORY.md § A stranger's install, on a clean Ubuntu."""
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("LUCID_MELT", "melt")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.delenv("DBUS_SESSION_BUS_ADDRESS", raising=False)
    monkeypatch.setattr(picture, "qt_draws", lambda env: True)
    runtime = tmp_path / "run"
    runtime.mkdir()
    if bus:
        (runtime / "bus").write_bytes(b"")
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(runtime))
    monkeypatch.setattr(picture, "RENDER_SCRATCH", tmp_path / "scratch")
    monkeypatch.setattr(picture.shutil, "which", lambda name: f"/usr/bin/{name}")
    commands: list[list[str]] = []

    def fake_run(command: list[str], **kwargs: object) -> object:
        commands.append(command)
        target = next(a for a in command if a.startswith("avformat:")).removeprefix("avformat:")
        Path(target).write_bytes(b"a render")
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(picture.subprocess, "run", fake_run)
    monkeypatch.setattr(picture.media, "probe", lambda p: _PROBE)
    monkeypatch.setattr(
        picture.media,
        "count_frames",
        lambda p: {"frames": 150, "container_frames": 150, "duration": 5.0, "has_video": True},
    )
    project = tmp_path / "timeline.mlt"
    project.write_text("<mlt/>", encoding="utf-8")

    result = picture.render(project, tmp_path / "out.mp4", expect_frames=150)
    assert (commands[0][0] == "systemd-run") is bus
    assert (result["memory_cap"] is not None) is bus
    if not bus:
        assert any("user session bus" in n for n in result["notes"])


# -- auto-editor -------------------------------------------------------------


@pytest.mark.parametrize(
    ("platform", "machine", "asset"),
    [
        # Every name on the right is on the 31.6.0 release's asset list, read
        # off GitHub 2026-09-10 — the plan's own guess had Windows wrong.
        ("linux", "x86_64", "auto-editor-linux-x86_64"),
        ("linux", "aarch64", "auto-editor-linux-aarch64"),
        ("linux", "armv7l", "auto-editor-linux-armv7"),
        ("darwin", "arm64", "auto-editor-macos-arm64"),
        ("darwin", "x86_64", "auto-editor-macos-x86_64"),
        ("win32", "AMD64", "auto-editor-windows-x86_64.exe"),
        ("win32", "ARM64", "auto-editor-windows-aarch64.exe"),
    ],
)
def test_the_not_found_message_names_this_machines_download(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, platform: str, machine: str, asset: str
) -> None:
    monkeypatch.setattr(sys, "platform", platform)
    monkeypatch.setattr(autoeditor.platform, "machine", lambda: machine)
    assert autoeditor.release_asset() == asset

    monkeypatch.delenv("LUCID_AUTO_EDITOR", raising=False)
    monkeypatch.setattr(autoeditor.shutil, "which", lambda name: None)
    monkeypatch.setenv("HOME", str(tmp_path))  # no ~/.local/bin/auto-editor
    with pytest.raises(autoeditor.AutoEditorError, match=asset.replace(".", r"\.")):
        autoeditor.binary()
    assert asset in doctor._auto_editor_entry()["fix"]


def test_an_os_upstream_does_not_build_for_gets_no_invented_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "platform", "freebsd14")
    monkeypatch.setattr(autoeditor.platform, "machine", lambda: "amd64")
    assert not autoeditor.release_asset().startswith("auto-editor-")


# -- tailscale ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("platform", "tail"),
    [("darwin", "Tailscale.app/Contents/MacOS/Tailscale"), ("win32", "tailscale.exe")],
)
def test_tailscale_is_found_where_the_app_installs_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, platform: str, tail: str
) -> None:
    monkeypatch.setattr(sys, "platform", platform)
    monkeypatch.delenv(webui.LUCID_TAILSCALE_ENV, raising=False)
    monkeypatch.setattr(webui.shutil, "which", lambda name: None)
    assert any(p.as_posix().endswith(tail) for p in webui._tailscale_installs())

    installed = tmp_path / "tailscale"
    installed.touch()
    monkeypatch.setattr(webui, "_tailscale_installs", lambda: [installed])
    assert webui._find_tailscale() == str(installed)


def test_tailscale_still_refuses_when_nothing_is_anywhere(monkeypatch: pytest.MonkeyPatch) -> None:
    """`--tailscale` refuses rather than falling back to loopback — unchanged."""
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.delenv(webui.LUCID_TAILSCALE_ENV, raising=False)
    monkeypatch.setattr(webui.shutil, "which", lambda name: None)
    monkeypatch.setattr(webui, "_tailscale_installs", lambda: [Path("/nowhere/Tailscale")])
    with pytest.raises(webui.ProjectError, match=re.escape(str(Path("/nowhere/Tailscale")))):
        webui.tailscale_identity()


# -- `lucid open`'s browser --------------------------------------------------


@pytest.mark.parametrize(
    ("platform", "tail"),
    [
        ("darwin", "Google Chrome.app/Contents/MacOS/Google Chrome"),
        ("win32", "msedge.exe"),
    ],
)
def test_a_chromium_is_found_in_its_install_location(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, platform: str, tail: str
) -> None:
    """Neither OS puts a browser on PATH, so the chromeless `--app=` window
    was never offered there."""
    monkeypatch.setattr(sys, "platform", platform)
    monkeypatch.setenv("ProgramFiles", str(tmp_path / "pf"))
    monkeypatch.setenv("ProgramFiles(x86)", str(tmp_path / "pf86"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    assert any(str(p).replace("\\", "/").endswith(tail) for p in webui._app_browser_installs())

    monkeypatch.delenv(webui.LUCID_BROWSER_ENV, raising=False)
    monkeypatch.setattr(webui.shutil, "which", lambda name: None)
    installed = tmp_path / "browser"
    installed.touch()
    monkeypatch.setattr(webui, "_app_browser_installs", lambda: [tmp_path / "absent", installed])
    assert webui._resolve_app_browser() == [str(installed)]


def test_chrome_outranks_edge_the_way_it_does_on_linux(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every Windows box has Edge; one with Chrome too should open Chrome."""
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("ProgramFiles", "PF")
    names = [p.name for p in webui._app_browser_installs()]
    assert names.index("chrome.exe") < names.index("msedge.exe")


def _no_app_browser(monkeypatch: pytest.MonkeyPatch, platform: str) -> list[str]:
    opened: list[str] = []
    monkeypatch.setattr(sys, "platform", platform)
    monkeypatch.setattr(webui, "_resolve_app_browser", lambda: None)
    monkeypatch.setattr(webui.shutil, "which", lambda name: None)
    import webbrowser

    monkeypatch.setattr(webbrowser, "open", lambda url: opened.append(url) or True)
    return opened


@pytest.mark.parametrize("platform", ["darwin", "win32"])
def test_with_no_chromium_the_url_opens_in_a_normal_tab(
    monkeypatch: pytest.MonkeyPatch, platform: str
) -> None:
    opened = _no_app_browser(monkeypatch, platform)
    webui._launch_app("http://127.0.0.1:1/")
    assert opened == ["http://127.0.0.1:1/"]


def test_linux_with_no_xdg_open_still_opens_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    """`webbrowser` on a Linux box with no `xdg-open` can answer with w3m or
    lynx, which would seize the terminal `lucid open` is serving from."""
    opened = _no_app_browser(monkeypatch, "linux")
    webui._launch_app("http://127.0.0.1:1/")
    assert opened == []


# -- fonts -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("platform", "tail"),
    [("darwin", "Library/Fonts"), ("win32", "Microsoft/Windows/Fonts")],
)
def test_the_user_font_dir_is_the_os_s_own(
    monkeypatch: pytest.MonkeyPatch, platform: str, tail: str
) -> None:
    monkeypatch.setattr(sys, "platform", platform)
    monkeypatch.setenv("XDG_DATA_HOME", "/somewhere/else")  # ignored off Linux
    monkeypatch.setenv("LOCALAPPDATA", "/appdata/local")
    assert str(fonts.user_font_dir()).replace("\\", "/").endswith(tail)


def test_a_mac_install_asks_fontconfig_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """fontconfig is not the font system there: neither `fc-cache` nor
    `fc-list` is run, and "on its path" is null rather than a False that
    sends someone reinstalling."""
    monkeypatch.setattr(sys, "platform", "darwin")

    def no_subprocess(*args: object, **kwargs: object) -> None:
        raise AssertionError(f"fontconfig asked on a Mac: {args}")

    monkeypatch.setattr(fonts.subprocess, "run", no_subprocess)
    report = fonts.install(dest=tmp_path)
    assert report["font_system"] == "CoreText"
    assert report["on_fontconfig_path"] is None
    assert report["cache_refreshed"] is None
    assert report["registered"] is None
    assert report["changed"] is True


class _FakeWinreg(types.ModuleType):
    """`winreg`'s surface, over a dict — Linux has no registry to write."""

    HKEY_CURRENT_USER = "HKCU"
    REG_SZ = 1

    def __init__(self, *, drop: bool = False) -> None:
        super().__init__("winreg")
        self.values: dict[str, str] = {}
        self.drop = drop  # a write that does not read back

    def CreateKey(self, root: str, path: str) -> _FakeWinreg:
        assert (root, path) == ("HKCU", fonts._WINDOWS_FONTS_KEY)
        return self

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def SetValueEx(self, key: object, name: str, reserved: int, kind: int, data: str) -> None:
        if not self.drop:
            self.values[name] = data

    def QueryValueEx(self, key: object, name: str) -> tuple[str, int]:
        if name not in self.values:
            raise FileNotFoundError(name)
        return self.values[name], self.REG_SZ


def test_a_windows_install_registers_each_face_and_reads_it_back(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A face copied into the per-user directory with no HKCU value is not
    installed — the copy alone would be reported as an install that is not."""
    registry = _FakeWinreg()
    monkeypatch.setitem(sys.modules, "winreg", registry)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(fonts.subprocess, "run", lambda *a, **k: pytest.fail("fontconfig asked"))

    report = fonts.install(dest=tmp_path)

    assert report["font_system"] == "DirectWrite"
    assert report["registered"] is True
    face = fonts.vendored()[0]
    assert registry.values == {f"{face.stem} (TrueType)": str(tmp_path / face.name)}

    # Unchanged on a second run, and still registered: a face copied by an
    # older lucid (or by hand) gets its value on the next install.
    registry.values.clear()
    again = fonts.install(dest=tmp_path)
    assert again["changed"] is False
    assert again["registered"] is True


def test_a_registration_that_does_not_read_back_is_reported_false(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setitem(sys.modules, "winreg", _FakeWinreg(drop=True))
    monkeypatch.setattr(sys, "platform", "win32")
    assert fonts.install(dest=tmp_path)["registered"] is False


@pytest.mark.parametrize(("platform", "system"), [("darwin", "CoreText"), ("win32", "DirectWrite")])
def test_doctors_caption_font_does_not_ask_fontconfig_off_linux(
    monkeypatch: pytest.MonkeyPatch, platform: str, system: str
) -> None:
    """Homebrew has a fontconfig; asking it about a Mac's burn measures the
    wrong resolver, which is the disagreement CLAUDE.md records on Linux."""
    monkeypatch.setattr(sys, "platform", platform)
    monkeypatch.setattr(doctor.fonts, "probe", lambda family, **kw: {"drew": True})
    monkeypatch.setattr(
        doctor.captions, "font_match", lambda *a, **k: pytest.fail("fontconfig asked")
    )
    font = doctor._caption_font()
    assert font["ok"] is True
    assert font["font_system"] == system
    assert font["resolves_to"] is None

    text = doctor.render(
        {
            "lucid": "0.0.0",
            "ok": True,
            "required": [],
            "optional": [],
            "display": {"ok": True, "how": "a Wayland session"},
            "caption_font": font,
        }
    )
    assert f"{system} — fontconfig is not this platform's font system" in text


def test_a_substituting_face_off_linux_is_still_a_cross(monkeypatch: pytest.MonkeyPatch) -> None:
    """The render's answer is a measurement on any OS — only the fontconfig
    half is dropped, never the ✗ the probe earned."""
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(
        doctor.fonts, "probe", lambda family, **kw: {"drew": False, "warning": "substituting"}
    )
    font = doctor._caption_font()
    assert font["ok"] is False
    assert "where CoreText looks" in font["fix"]


# -- the GPU workers — step 3 -------------------------------------------------


def _synth_ready(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """A box where the interpreter, the model and a voice all resolve."""
    voice = tmp_path / "voice"
    voice.mkdir()
    (voice / "ref.wav").touch()
    (voice / "ref.txt").write_text("the words", encoding="utf-8")
    monkeypatch.setattr(tts, "tts_python", lambda: Path(sys.executable))
    monkeypatch.setattr(tts, "model_dir", lambda: tmp_path / "model")
    monkeypatch.setenv("LUCID_TTS_VOICE", str(voice))
    monkeypatch.delenv(tts.DEVICE_ENV, raising=False)
    return voice


def test_a_mac_reports_the_synthesiser_unavailable_rather_than_failing_in_the_worker(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Everything resolves and nothing can run: the worker loads onto CUDA.
    Said before the GPU is asked for, the way doctor reports any absent
    optional capability — and the device knob opens the door for whoever
    measures MPS, without claiming it works."""
    voice = _synth_ready(monkeypatch, tmp_path)
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(tts.subprocess, "run", lambda *a, **k: pytest.fail("worker spawned"))

    report = tts.available()
    assert report["available"] is False
    assert "no CUDA on macOS" in report["why"]
    with pytest.raises(tts.TTSError, match="no CUDA on macOS"):
        tts.synth("a line", voice, tmp_path / "out", [1], max_seconds=5)
    assert "no CUDA on macOS" in doctor._tts_entry()["why"]

    monkeypatch.setenv(tts.DEVICE_ENV, "mps")
    assert tts.available()["available"] is True


@pytest.mark.parametrize(("env", "expected"), [(None, "cuda"), ("cpu", "cpu")])
def test_the_synth_job_carries_the_device(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, env: str | None, expected: str
) -> None:
    voice = _synth_ready(monkeypatch, tmp_path)
    # CUDA is the default *on Linux*; a real Mac refuses before the device is
    # read (the test above), which is what the macOS runner met.
    monkeypatch.setattr(sys, "platform", "linux")
    if env:
        monkeypatch.setenv(tts.DEVICE_ENV, env)
    jobs: list[dict] = []

    def worker(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        jobs.append(json.loads(Path(command[2]).read_text(encoding="utf-8")))
        Path(command[3]).write_text(json.dumps({"candidates": []}), encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(tts.subprocess, "run", worker)
    with pytest.raises(tts.TTSError, match="returned nothing"):
        tts.synth("a line", voice, tmp_path / "out", [1], max_seconds=5)
    assert jobs[0]["device"] == expected


@pytest.mark.parametrize(
    ("platform", "env", "why"),
    [
        ("darwin", None, "no CUDA on macOS"),
        ("linux", "mps", "bitsandbytes, which is CUDA-only"),
        ("linux", "cpu", "bitsandbytes, which is CUDA-only"),
    ],
)
def test_describe_refuses_a_device_its_4bit_load_cannot_use(
    monkeypatch: pytest.MonkeyPatch, platform: str, env: str | None, why: str
) -> None:
    """bitsandbytes has no MPS backend, so a Mac cannot describe today and a
    non-CUDA device has no path in the worker. `available()` says so, which
    is what doctor and `describe --plan` both read."""
    monkeypatch.setattr(sys, "platform", platform)
    monkeypatch.setattr(describe, "vlm_python", lambda: Path(sys.executable))
    if env:
        monkeypatch.setenv(describe.DEVICE_ENV, env)
    else:
        monkeypatch.delenv(describe.DEVICE_ENV, raising=False)
    monkeypatch.setattr(describe.subprocess, "run", lambda *a, **k: pytest.fail("worker spawned"))

    report = describe.available()
    assert report["available"] is False
    assert why in report["why"]
    assert why in doctor._vlm_entry()["why"]
    with pytest.raises(describe.DescribeError, match=why.split(",")[0]):
        describe.describe_windows([{"index": 0, "media": "x.mp4", "timestamps": [0.0]}])


def test_linux_on_cuda_still_describes_and_says_so_in_the_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(describe, "vlm_python", lambda: Path(sys.executable))
    monkeypatch.delenv(describe.DEVICE_ENV, raising=False)
    assert describe.available()["available"] is True

    jobs: list[dict] = []

    def worker(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        jobs.append(json.loads(Path(command[2]).read_text(encoding="utf-8")))
        Path(command[3]).write_text(
            json.dumps({"results": [{"index": 0, "text": "a room"}]}), encoding="utf-8"
        )
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(describe.subprocess, "run", worker)
    describe.describe_windows([{"index": 0, "media": "x.mp4", "timestamps": [0.0]}])
    assert jobs[0]["device"] == "cuda"


def test_the_vision_worker_itself_refuses_before_importing_torch(tmp_path: Path) -> None:
    """Run the real worker the way lucid does — a subprocess, never an import.
    lucid's own venv has no torch, so a worker that reached for it first would
    die on `ModuleNotFoundError`; the refusal has to come before that."""
    job = tmp_path / "job.json"
    job.write_text(json.dumps({"model": "m", "device": "mps", "windows": []}), encoding="utf-8")
    worker = Path(describe.__file__).with_name("_vlm_worker.py")

    done = subprocess.run(
        [sys.executable, str(worker), str(job), str(tmp_path / "out.json")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 2
    assert "bitsandbytes" in done.stderr
    assert "ModuleNotFoundError" not in done.stderr
    assert not (tmp_path / "out.json").exists()


# -- what the first Windows CI run found -------------------------------------


def test_a_manifest_written_on_linux_still_writes_a_timeline_under_windows_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """On Windows `/footage/a.mp4` has no drive, so it is not absolute and
    `Path.as_uri()` raised — on every op that writes `project.otio`, over a URL
    nothing in lucid reads back. 470 of the first Windows run's 527 failures."""
    monkeypatch.setattr(timeline, "Path", PureWindowsPath)
    clip = {"clip_id": "a", "duration": 2.0, "has_video": True}
    edit = timeline.Edit([timeline.Segment("a", 0.0, 1.0)])

    def url(source: str) -> str:
        otio = timeline.to_otio(edit, {"a": {**clip, "source": source}}, rate=25.0)
        return otio.tracks[0][0].media_reference.target_url

    assert url("/footage/a.mp4") == "file:///footage/a.mp4"
    assert url(r"C:\footage\a.mp4") == "file:///C:/footage/a.mp4"
    with pytest.raises(ValueError, match="relative"):
        url("footage/a.mp4")


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is not installed")
def test_the_scene_scan_survives_a_colon_in_its_temp_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`:` separates a filter's options, so the scan's report file named by an
    absolute path ended at a Windows drive letter and ffmpeg refused the chain.
    Linux can hold a `:` in a directory name, so the same trap is reproduced
    here rather than only on a Windows runner, where the temp dir has one
    already. The input is passed relative, since the fix moves ffmpeg's cwd."""
    colons = tmp_path if os.name == "nt" else tmp_path / "C:scratch"
    colons.mkdir(exist_ok=True)
    monkeypatch.setattr(tempfile, "tempdir", str(colons))
    clip = tmp_path / "cut.mp4"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y",
         "-f", "lavfi", "-i", "color=c=red:size=160x120:rate=25:duration=1",
         "-f", "lavfi", "-i", "color=c=blue:size=160x120:rate=25:duration=1",
         "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0", "-pix_fmt", "yuv420p", str(clip)],
        check=True,
    )  # fmt: skip
    monkeypatch.chdir(tmp_path)

    cuts = media.scene_cuts("cut.mp4")

    assert [round(c["src_time"], 2) for c in cuts] == [1.0]


def test_the_agent_pane_spawns_the_claude_doctor_found(monkeypatch: pytest.MonkeyPatch) -> None:
    """An npm install on Windows is `claude.cmd`, which `shutil.which` finds
    and Popen does not — so doctor was ✓ over a pane that could not spawn."""
    monkeypatch.delenv(webui.AGENT_BIN_ENV, raising=False)
    monkeypatch.setattr(
        webui.shutil, "which", lambda name: r"C:\npm\claude.cmd" if name == "claude" else None
    )
    assert webui._agent_bin() == r"C:\npm\claude.cmd"

    monkeypatch.setattr(webui.shutil, "which", lambda name: None)
    assert webui._agent_bin() == "claude", "unresolved, the spawn's own error names it"


def test_the_probe_names_what_libass_drew_by_file_never_by_path() -> None:
    """Outfit did not draw on the Windows runner, and all the probe could say
    was "not Outfit". libass logs its provider and every face it picks under
    `-v verbose`, and the probe carries both. The Linux lines are verbatim from
    this box; the Windows line is **constructed** in the same shape — no
    DirectWrite log has been read yet, so this pins the parse, not the OS."""
    stderr = (
        "[Parsed_ass_0 @ 0x55] Using font provider fontconfig\n"
        "[Parsed_ass_0 @ 0x7f] fontselect: (lucid No Such Face 0000, 400, 0) -> "
        "/usr/share/fonts/google-noto-vf/NotoSansArabic[wght].ttf, 0, NotoSansArabic-Regular\n"
        "[Parsed_ass_0 @ 0x7f] Glyph 0x48 not found, selecting one more font for "
        "(lucid No Such Face 0000, 400, 0)\n"
        "[Parsed_ass_0 @ 0x7f] fontselect: (lucid No Such Face 0000, 400, 0) -> "
        "/usr/share/fonts/google-noto/NotoSans-Regular.ttf, 0, NotoSans-Regular\n"
    )
    chose = fonts._libass_choices(stderr)
    assert chose["provider"] == "fontconfig"
    assert chose["faces"] == [
        {"file": "NotoSansArabic[wght].ttf", "face": "NotoSansArabic-Regular"},
        {"file": "NotoSans-Regular.ttf", "face": "NotoSans-Regular"},
    ]

    windows = fonts._libass_choices(
        "[Parsed_ass_0 @ 0000] Using font provider directwrite (with GDI)\n"
        "[Parsed_ass_0 @ 0000] fontselect: (Outfit, 400, 0) -> "
        r"C:\Users\runneradmin\AppData\Local\Microsoft\Windows\Fonts\Outfit[wght].ttf, 0, Outfit-Regular"
    )
    assert windows["provider"] == "directwrite"
    assert windows["faces"] == [{"file": "Outfit[wght].ttf", "face": "Outfit-Regular"}]
    assert "runneradmin" not in json.dumps(windows)

    assert fonts._libass_choices("ffmpeg version n7.1\n") == {"provider": None, "faces": []}


def test_doctors_font_cross_says_what_drew_instead(monkeypatch: pytest.MonkeyPatch) -> None:
    """A ✗ that names the substitute is a finding; one that says only "not
    Outfit" is where the Windows run stopped."""
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(
        doctor.fonts,
        "probe",
        lambda family, **kw: {
            "drew": False,
            "warning": "substituting",
            "font_provider": "directwrite",
            "drawn_with": [{"file": "arial.ttf", "face": "ArialMT"}],
        },
    )
    font = doctor._caption_font()
    text = doctor.render(
        {
            "lucid": "0.0.0",
            "ok": False,
            "required": [],
            "optional": [],
            "display": {"ok": True, "how": "native"},
            "caption_font": font,
        }
    )
    assert "libass (directwrite) drew it with: ArialMT (arial.ttf)" in text


def test_a_headless_qt_that_draws_nothing_refuses_the_render(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Ubuntu 24.04's MLT 7.22 Qt module ignores QT_QPA_PLATFORM=offscreen and
    wants X11: a 9:16 render dropped its crop filter, letterboxed the footage,
    and still agreed with the timeline frame for frame. So a headless Qt is
    judged by what it draws, not by the variable. HISTORY.md § A stranger's
    install, on a clean Ubuntu."""
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("LUCID_MELT", "melt")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setattr(picture, "display_env", lambda: {"QT_QPA_PLATFORM": "offscreen"})
    monkeypatch.setattr(picture, "qt_draws", lambda env: False)
    monkeypatch.setattr(picture, "RENDER_SCRATCH", tmp_path / "scratch")
    project = tmp_path / "timeline.mlt"
    project.write_text("<mlt/>", encoding="utf-8")
    with pytest.raises(picture.PictureError, match="xvfb-run"):
        picture.render(project, tmp_path / "out.mp4", expect_frames=150)
