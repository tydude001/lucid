"""The version literal exists twice, and this is what keeps the two one fact.

`pyproject.toml` is what a build stamps into the wheel's metadata;
`lucid.__version__` is what `lucid --version` prints. A bump that touches one
of them ships a package whose own metadata disagrees with the code inside it,
and nothing else in this repo reads either number, so nothing else would ever
notice.

The obvious fix is to delete one copy — `importlib.metadata.version("lucid")`
in `__init__` — and it is worse here, because that reads the *installed*
dist-info rather than the source tree. Under this repo's editable install
(`.venv/…/lucid.pth` beside a `lucid-0.1.0.dist-info` written at sync time) a
bump with no `uv sync` behind it leaves `lucid --version` printing the old
number, correctly-looking and wrong, with no check anywhere disagreeing.
A test that fails loudly beats an answer that is silently stale, so the copy
stays and this file is the guard on it.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

import lucid
from lucid.cli import main

_REPO = Path(__file__).resolve().parent.parent
_PYPROJECT = _REPO / "pyproject.toml"


def _project_table() -> dict:
    if not _PYPROJECT.exists():  # running against an installed wheel, not the tree
        pytest.skip("no pyproject.toml beside the tests")
    return tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))["project"]


def test_pyproject_and_package_agree_on_the_version() -> None:
    assert lucid.__version__ == _project_table()["version"]


def test_cli_version_flag_prints_the_package_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert capsys.readouterr().out.strip() == f"lucid {lucid.__version__}"


def test_every_declared_licence_file_is_actually_there() -> None:
    """`license-files` names paths a build resolves; a missing one ships nothing.

    The wheel carries the LICENSE text in `dist-info/licenses/`, and the four OFL
    texts ride along inside the package directories they document
    (`src/lucid/fonts/`, `src/lucid/web/`) rather than through this key.
    """
    declared = _project_table()["license-files"]
    assert declared, "the project declares no licence file"
    for pattern in declared:
        assert list(_REPO.glob(pattern)), f"license-files names {pattern!r}, which matches nothing"
