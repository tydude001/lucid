import json
import os
from pathlib import Path

import pytest

from lucid.project import (
    MANIFEST_NAME,
    SCHEMA_VERSION,
    Project,
    ProjectConflictError,
    ProjectError,
)


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
    """`lucid-v3.json` lives in `cache/history/` beside the numbered snapshots
    and must not become an undo step: rolling the timeline back one edit must
    not roll the schema back with it. Measured as a delta rather than against
    an empty stack, because a manifest write is itself a snapshot now — the
    fixture's own `write_manifest` takes one — and `migrate` is the write that
    must not."""
    project = _v1_project(tmp_path)
    before = project.snapshots()

    backup = Path(Project.migrate(project.root)["backup"])

    assert backup.parent == project.history_dir
    assert [s.index for s in project.snapshots()] == [s.index for s in before]
    assert backup not in {s.manifest for s in project.snapshots()}


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


# -- two writers on one project (TRIAL.md § Nothing in lucid notices two ----
# writers in one project) --------------------------------------------------


def test_write_manifest_refuses_a_write_the_file_has_moved_past(tmp_path: Path) -> None:
    """Two `Project` instances on the same root — a second `lucid web`, an
    agent panel, a CLI command beside either. The second writer's write must
    not silently discard the first's, so the first (stale) instance's write
    is refused rather than clobbering."""
    root = tmp_path / "demo"
    first = Project.create(root)
    manifest = first.read_manifest()

    second = Project.open(root)
    second.write_manifest({**second.read_manifest(), "name": "written-by-second"})

    manifest["name"] = "written-by-first"
    with pytest.raises(ProjectConflictError, match="changed on disk"):
        first.write_manifest(manifest)

    # The second writer's edit survived, untouched by the refused write.
    assert Project.open(root).read_manifest()["name"] == "written-by-second"


def test_write_manifest_succeeds_after_re_reading_past_a_conflict(tmp_path: Path) -> None:
    """The recovery path: re-read (picking up the stamp the other writer
    left) and the same instance can write again."""
    root = tmp_path / "demo"
    first = Project.create(root)
    first.read_manifest()

    second = Project.open(root)
    second.write_manifest({**second.read_manifest(), "name": "written-by-second"})

    refreshed = first.read_manifest()
    refreshed["name"] = "written-by-first-after-reread"
    first.write_manifest(refreshed)

    assert Project.open(root).read_manifest()["name"] == "written-by-first-after-reread"


def test_write_manifest_does_not_refuse_an_instance_that_never_read(tmp_path: Path) -> None:
    """`Project.create`'s own first write, and any other write with nothing
    to compare against, must not be caught up in a check meant for a stale
    *read*."""
    root = tmp_path / "demo"
    Project.create(root)  # writes once, with no prior read on this instance

    fresh = Project(root)  # never called read_manifest at all
    fresh.write_manifest({"schema_version": SCHEMA_VERSION, "name": "demo", "clips": []})

    assert Project.open(root).read_manifest()["name"] == "demo"


def test_undo_refuses_when_the_manifest_moved_past_the_snapshot_it_read(tmp_path: Path) -> None:
    """`restore()` bypasses `write_manifest` (a raw `shutil.copy2`, since the
    undo step is not itself an edit to snapshot) and would otherwise be the
    one path around this refusal."""
    root = tmp_path / "demo"
    first = Project.create(root)
    manifest = first.read_manifest()
    manifest["name"] = "renamed"
    first.write_manifest(manifest)  # one snapshot to undo back to

    stale = Project.open(root)  # reads the post-rename state

    second = Project.open(root)
    second.write_manifest({**second.read_manifest(), "name": "written-by-second"})

    with pytest.raises(ProjectConflictError, match="changed on disk"):
        stale.restore()

    assert Project.open(root).read_manifest()["name"] == "written-by-second"


def test_a_second_write_inside_the_same_clock_tick_is_still_a_conflict(tmp_path: Path) -> None:
    """The stamp is a digest of the bytes, not the file's mtime. Windows
    stamps two writes inside one timer tick (~15ms) with the same mtime, and
    with an mtime stamp the refusal above passed on one CI run and failed on
    the next with no code change between them (ci run 34793271514). Pin the
    mtime back to what the stale instance saw, so a clock-based check would
    read "unchanged", and the refusal has to fire on the bytes alone."""
    root = tmp_path / "demo"
    first = Project.create(root)
    stale = Project.open(root)
    held = stale.read_manifest()
    seen = first.manifest_path.stat()

    second = Project.open(root)
    second.write_manifest({**second.read_manifest(), "name": "written-by-second"})
    os.utime(first.manifest_path, ns=(seen.st_atime_ns, seen.st_mtime_ns))
    assert first.manifest_path.stat().st_mtime_ns == seen.st_mtime_ns

    with pytest.raises(ProjectConflictError, match="changed on disk"):
        stale.write_manifest({**held, "name": "written-by-stale"})
