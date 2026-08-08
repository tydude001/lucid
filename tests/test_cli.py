"""CLI-only behaviour: timecode parsing, and how `init` resolves a directory.

Both live only in the CLI by design, so the stdio suite cannot reach them.
`cut-at`'s whole value rests on the span parsing; `init`'s on not creating a
project somewhere the caller did not name.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from lucid.cli import _parse_timecode, _time_span, main


def test_parse_timecode_reads_colon_parts_optional_from_the_right() -> None:
    assert _parse_timecode("4.4") == pytest.approx(4.4)
    assert _parse_timecode("0:40.4") == pytest.approx(40.4)
    assert _parse_timecode("1:00:40.4") == pytest.approx(3640.4)


def test_time_span_start_plus_duration() -> None:
    assert _time_span("0:40.4+4.4") == pytest.approx([40.4, 44.8])


def test_time_span_start_dash_end() -> None:
    assert _time_span("0:40.4-0:44.8") == pytest.approx([40.4, 44.8])


def test_time_span_rejects_garbage() -> None:
    with pytest.raises(argparse.ArgumentTypeError):
        _time_span("banana")


# -- `init` and the global `-C` -------------------------------------------
#
# `init` is the one subcommand whose directory is an argument rather than a
# lookup, so it is the one place `-C` and a positional can disagree. It used
# to read only the positional, which made `lucid -C myproj init` create a
# project in the *current* directory and report success.


def _project_exists(root: Path) -> bool:
    return (root / "lucid.json").is_file()


def test_init_honours_the_global_project_flag(tmp_path: Path) -> None:
    assert main(["-C", str(tmp_path / "proj"), "init"]) == 0
    assert _project_exists(tmp_path / "proj")


def test_init_still_takes_a_positional_path(tmp_path: Path) -> None:
    assert main(["init", str(tmp_path / "proj")]) == 0
    assert _project_exists(tmp_path / "proj")


def test_init_refuses_two_different_directories(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Neither spelling silently wins — the old behaviour picked the positional
    and created a project somewhere the caller had not named.
    """
    assert main(["-C", str(tmp_path / "flag"), "init", str(tmp_path / "positional")]) == 1
    assert not _project_exists(tmp_path / "flag")
    assert not _project_exists(tmp_path / "positional")
    assert "two directories" in capsys.readouterr().err


def test_init_with_neither_uses_the_working_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    assert main(["init"]) == 0
    assert _project_exists(tmp_path)


def test_explicit_dash_c_dot_is_not_mistaken_for_an_unset_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`-C .` is a real answer, so pairing it with a positional is still the
    two-directories error rather than being waved through as "no -C given".
    """
    monkeypatch.chdir(tmp_path)
    assert main(["-C", ".", "init", "proj"]) == 1
    assert not _project_exists(tmp_path)
    assert not _project_exists(tmp_path / "proj")
