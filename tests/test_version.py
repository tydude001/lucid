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

import json
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


def _listing(name: str) -> dict:
    """One of the launch listings, or a skip when running against an installed wheel."""
    path = _REPO / name
    if not path.exists():  # the listings sit beside the tests, not inside the package
        pytest.skip(f"no {name} beside the tests")
    return json.loads(path.read_text(encoding="utf-8"))


def test_every_launch_listing_states_the_package_version() -> None:
    """Four more hand-typed copies of the number, held to the two above.

    docs/plans/LAUNCH.md step 4 put the version into `server.json` (where the
    registry schema requires it) and into the plugin and marketplace manifests
    (where it is optional but is what a user sees). That took the literal from
    two places to six, and the reasoning in this file's docstring applies
    unchanged to the four new ones: nothing else reads them, so nothing else
    would ever notice a bump that missed one — and the way it surfaces is a
    registry entry advertising a version the release does not have.
    """
    version = lucid.__version__
    marketplace = _listing(".claude-plugin/marketplace.json")
    stated = {
        "server.json": [_listing("server.json")["version"]],
        ".claude-plugin/plugin.json": [_listing(".claude-plugin/plugin.json")["version"]],
        ".claude-plugin/marketplace.json": [
            marketplace["version"],
            *(entry["version"] for entry in marketplace["plugins"]),
        ],
    }
    for name, versions in stated.items():
        for found in versions:
            assert found == version, f"{name} says {found!r}, the package says {version!r}"
