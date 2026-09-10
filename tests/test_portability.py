"""The Linux-shaped resolvers, widened — docs/plans/PORTABILITY.md step 2.

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

import sys
import types
from pathlib import Path
from typing import Self

import pytest

from lucid import autoeditor, doctor, fonts, media, picture, webui

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
    assert any(str(p).endswith(bundle) for p in picture.melt_bundles())

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
    assert any(str(p).endswith(tail) for p in webui._tailscale_installs())

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
    with pytest.raises(webui.ProjectError, match="/nowhere/Tailscale"):
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
