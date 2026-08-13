"""The vendored caption face, and the probe that settles which face drew.

`test_captions.py` covers `font_match`, which asks fontconfig. These cover the
half fontconfig cannot answer. The two are kept apart on purpose: this repo
has measured them disagreeing, and a suite that folded the render check into
the fontconfig check would report one answer where there are two.
"""

from __future__ import annotations

import shutil

import pytest

from lucid import fonts
from lucid.captions import CAPTION_FONT, font_match

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("magick") is None,
    reason="the probe is a render comparison; it needs ffmpeg with libass and ImageMagick",
)


# -- the vendoring --------------------------------------------------------


def test_the_face_the_presets_name_ships_in_the_package() -> None:
    """The failure this closes: the caption default resolved on the build box
    by coincidence, because a sibling repo's tooling had left the file in
    `~/.local/share/fonts` months earlier."""
    names = [p.name for p in fonts.vendored()]

    assert names, "no face ships in src/lucid/fonts/"
    assert any(CAPTION_FONT.split()[0].lower() in name.lower() for name in names), (
        f"nothing vendored looks like {CAPTION_FONT!r}, which every caption preset names"
    )


def test_installing_twice_changes_nothing_the_second_time(tmp_path) -> None:
    first = fonts.install(dest=tmp_path)
    second = fonts.install(dest=tmp_path)

    assert first["changed"] is True
    assert all(face["state"] == "installed" for face in first["faces"])
    assert second["changed"] is False
    assert all(face["state"] == "unchanged" for face in second["faces"])


def test_a_face_already_there_is_compared_by_content_not_by_name(tmp_path) -> None:
    """A same-named file with different bytes is a *different* face, and
    leaving it would be the silent-substitution failure wearing the right
    filename."""
    face = fonts.vendored()[0]
    (tmp_path / face.name).write_bytes(b"not a font")

    report = fonts.install(dest=tmp_path)

    assert report["changed"] is True
    assert (tmp_path / face.name).read_bytes() == face.read_bytes()


def test_the_font_dir_is_resolved_the_way_fontconfig_resolves_it(monkeypatch) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", "/somewhere/else")
    assert fonts.user_font_dir() == fonts.Path("/somewhere/else/fonts")

    monkeypatch.setenv("XDG_DATA_HOME", "")
    assert fonts.user_font_dir() == fonts.Path.home() / ".local" / "share" / "fonts"


# -- the probe ------------------------------------------------------------


def test_a_name_that_cannot_resolve_is_reported_as_not_drawing() -> None:
    """The whole point of the second burn. libass draws *something* for a name
    it cannot find, ffmpeg exits 0, and the frame looks like a caption."""
    report = fonts.probe("Definitely Not A Real Font 91537")

    assert report["drew"] is False
    assert report["rmse_against_substitute"] == 0.0
    assert "substituting" in report["warning"]


def test_the_caption_default_actually_draws() -> None:
    """`fc-match` answers 'is the family present'. This answers 'did it
    draw', which is the only question a burn settles."""
    report = fonts.probe(CAPTION_FONT)

    assert report["drew"] is True, report
    assert report["rmse_against_substitute"] > 0.0
    assert "warning" not in report


def test_fontconfig_and_the_render_are_reported_separately() -> None:
    """They are different questions and this repo has measured them
    disagreeing, so neither result is folded into the other."""
    match = font_match(CAPTION_FONT)
    report = fonts.probe(CAPTION_FONT)

    assert match["available"] is True
    assert report["drew"] is True
    assert set(match) & set(report) == {"font"}


def test_the_probe_draws_enough_ink_to_be_comparing_anything() -> None:
    """Two renders of nothing are also identical, so a blank probe would
    score as a clean substitution rather than as a broken check."""
    report = fonts.probe(CAPTION_FONT)

    assert report["ink"] > 0.0
    assert report["control_ink"] > 0.0
    assert report["ink"] != report["control_ink"]
