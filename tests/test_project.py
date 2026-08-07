from pathlib import Path

import pytest

from lucid.project import MANIFEST_NAME, SCHEMA_VERSION, Project, ProjectError


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


def test_write_manifest_leaves_no_temp_file_behind(tmp_path: Path) -> None:
    project = Project.create(tmp_path / "demo")
    project.write_manifest({"schema_version": SCHEMA_VERSION, "name": "demo", "clips": []})

    assert [p.name for p in project.root.glob("lucid.json*")] == [MANIFEST_NAME]
