import json
from pathlib import Path

import pytest

from lucid.project import MANIFEST_NAME, SCHEMA_VERSION, Project, ProjectError


def _v1_project(tmp_path: Path, name: str = "old") -> Project:
    """A project directory as a pre-cue-table lucid left it: no `cues` key.

    Written through `create` then rewound, rather than assembled by hand, so
    the fixture is the real layout minus exactly the thing v2 added.
    """
    project = Project.create(tmp_path / name)
    project.write_manifest(
        {
            "schema_version": 1,
            "name": name,
            "timebase": 24.0,
            "clips": [{"clip_id": "a", "media": "media/a.wav"}],
        }
    )
    return project


def test_create_lays_out_the_directory(tmp_path: Path) -> None:
    project = Project.create(tmp_path / "demo")

    assert project.manifest_path.exists()
    assert project.media_dir.is_dir()
    assert project.transcript_dir.is_dir()
    assert project.render_dir.is_dir()

    manifest = project.read_manifest()
    assert manifest["schema_version"] == SCHEMA_VERSION
    assert manifest["name"] == "demo"
    assert manifest["clips"] == []
    assert manifest["cues"] == []


def test_create_refuses_to_clobber_an_existing_project(tmp_path: Path) -> None:
    Project.create(tmp_path / "demo")
    with pytest.raises(ProjectError, match="already exists"):
        Project.create(tmp_path / "demo")


def test_open_rejects_a_directory_with_no_manifest(tmp_path: Path) -> None:
    (tmp_path / "empty").mkdir()
    with pytest.raises(ProjectError, match="no lucid project"):
        Project.open(tmp_path / "empty")


def test_open_rejects_an_unknown_schema_version(tmp_path: Path) -> None:
    project = Project.create(tmp_path / "demo")
    project.write_manifest({"schema_version": SCHEMA_VERSION + 1})

    with pytest.raises(ProjectError, match="schema_version"):
        Project.open(project.root)


def test_open_rejects_a_corrupt_manifest(tmp_path: Path) -> None:
    project = Project.create(tmp_path / "demo")
    project.manifest_path.write_text("{ not json", encoding="utf-8")

    with pytest.raises(ProjectError, match="not valid JSON"):
        Project.open(project.root)


def test_open_refusal_names_migrate_when_there_is_a_path_forward(tmp_path: Path) -> None:
    """The refusal is a dead end unless it says what clears it."""
    project = _v1_project(tmp_path)

    with pytest.raises(ProjectError, match="lucid migrate"):
        Project.open(project.root)


def test_open_refusal_does_not_offer_migrate_for_a_newer_project(tmp_path: Path) -> None:
    project = Project.create(tmp_path / "demo")
    project.write_manifest({"schema_version": SCHEMA_VERSION + 1})

    with pytest.raises(ProjectError, match="no migration path"):
        Project.open(project.root)


def test_migrate_brings_a_v1_project_forward(tmp_path: Path) -> None:
    project = _v1_project(tmp_path)

    report = Project.migrate(project.root)

    assert report["schema_version"] == SCHEMA_VERSION
    # Stepwise, so a v1 project reaches the present through every step in
    # turn rather than through a v1 -> current shortcut nobody else takes.
    assert report["steps"] == ["1 -> 2", "2 -> 3", "3 -> 4"]
    assert report["migrated"] is True

    manifest = Project.open(project.root).read_manifest()
    assert manifest["schema_version"] == SCHEMA_VERSION
    assert manifest["cues"] == []
    assert manifest["descriptions"] == []
    assert manifest["cards"] == []
    # v1's keys mean in v4 what they meant in v1; every step is additive only.
    assert manifest["name"] == "old"
    assert manifest["timebase"] == 24.0
    assert manifest["clips"] == [{"clip_id": "a", "media": "media/a.wav"}]


def test_migrate_copies_the_manifest_aside_before_writing(tmp_path: Path) -> None:
    project = _v1_project(tmp_path)

    backup = Path(Project.migrate(project.root)["backup"])

    assert backup.exists()
    assert json.loads(backup.read_text(encoding="utf-8"))["schema_version"] == 1


def test_the_manifest_backup_is_invisible_to_undo(tmp_path: Path) -> None:
    """`snapshots()` globs `*.otio` and parses stems as ints — a stray `.json`
    in there must not become an undo step, or land in `int()`."""
    project = _v1_project(tmp_path)
    Project.migrate(project.root)

    assert project.snapshots() == []


def test_migrate_plans_without_writing(tmp_path: Path) -> None:
    project = _v1_project(tmp_path)

    report = Project.migrate(project.root, plan=True)

    assert report["plan"] is True
    assert report["schema_version"] == 1
    assert report["steps"] == ["1 -> 2", "2 -> 3", "3 -> 4"]
    assert report["migrated"] is False
    assert report["backup"] is None
    assert project.read_manifest()["schema_version"] == 1
    assert "cues" not in project.read_manifest()
    assert "descriptions" not in project.read_manifest()
    assert "cards" not in project.read_manifest()


def test_migrate_is_a_no_op_on_a_current_project(tmp_path: Path) -> None:
    """Running it twice is how it will actually be used — over a directory of
    projects, some already forward. The second pass must not error or churn."""
    project = Project.create(tmp_path / "demo")

    report = Project.migrate(project.root)

    assert report["steps"] == []
    assert report["migrated"] is False
    assert report["backup"] is None
    assert not list(project.history_dir.glob("*.json"))


def test_migrate_refuses_a_newer_project(tmp_path: Path) -> None:
    project = Project.create(tmp_path / "demo")
    project.write_manifest({"schema_version": SCHEMA_VERSION + 1})

    with pytest.raises(ProjectError, match="forward-only"):
        Project.migrate(project.root)


def test_migrate_refuses_a_non_integer_schema_version(tmp_path: Path) -> None:
    """`True` is an `int` subclass, so an unguarded check migrates it as v1."""
    project = Project.create(tmp_path / "demo")
    project.write_manifest({"schema_version": True})

    with pytest.raises(ProjectError, match="no migration step is registered"):
        Project.migrate(project.root)


def test_migrate_rejects_a_directory_with_no_manifest(tmp_path: Path) -> None:
    (tmp_path / "empty").mkdir()
    with pytest.raises(ProjectError, match="no lucid project"):
        Project.migrate(tmp_path / "empty")


def test_write_manifest_leaves_no_temp_file_behind(tmp_path: Path) -> None:
    project = Project.create(tmp_path / "demo")
    project.write_manifest({"schema_version": SCHEMA_VERSION, "name": "demo", "clips": []})

    assert [p.name for p in project.root.glob("lucid.json*")] == [MANIFEST_NAME]
