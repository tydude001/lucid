"""The lucid project directory.

A project is a directory on disk. Nothing is uploaded, and every artifact is
inspectable with ordinary tools::

    myproject/
      lucid.json            manifest — schema version, clip registry, cue table,
                            footage descriptions, settings
      media/                imported source media (copies or symlinks)
      project.otio          the timeline; the source of truth tools mutate
      cache/
        transcripts/        <clip_id>.json — word-level timings, per clip
        verify/             <render>.json — what a finished render was heard to say
        frames/             <render-stem>/*.png — spot-check frames pulled from a render
        attenuated/         <clip_id>.<ext> — derived, gain-reduced copies of clip media
        waveform/           <clip_id>.json — RMS envelope, keyed by media size+mtime
        agent_thumbs.jsonl  one JSON line per per-turn thumbs-up/down rating
      assets/
        cards/              <name>.png — static picture cards a `card:<name>` cue resolves to
      renders/              preview.mp4, final.mp4, …

The OTIO file is authoritative for the edit; renders are derived from it and
are safe to delete. The manifest is authoritative for *identity* — which clip
a `clip_id` refers to, and where its media lives.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

#: Bumped when the on-disk layout changes incompatibly.
#: 2 added the cue table (`cues`, PLAN.md § The layered timeline).
#: 3 added footage descriptions (`descriptions`, PLAN.md § B-roll by
#: description), and covers the optional in-point a cue gains with them.
SCHEMA_VERSION = 3

MANIFEST_NAME = "lucid.json"
TIMELINE_NAME = "project.otio"

MEDIA_DIR = "media"
CACHE_DIR = "cache"
TRANSCRIPT_DIR = "cache/transcripts"
HISTORY_DIR = "cache/history"
VERIFY_DIR = "cache/verify"
FRAMES_DIR = "cache/frames"
ATTENUATED_DIR = "cache/attenuated"
WAVEFORM_DIR = "cache/waveform"
RENDER_DIR = "renders"
CARDS_DIR = "assets/cards"
#: Per-turn thumbs-up/down log for the agent panel (DAYDREAM.md § Agent
#: panel) — one JSON line per rating. Lives under `cache/` because it is
#: derived telemetry, not part of the edit: nothing here is authoritative for
#: the timeline or the manifest, and `_revision()` in webui.py never stats it.
THUMBS_LOG = "cache/agent_thumbs.jsonl"

_SUBDIRS = (
    MEDIA_DIR,
    CACHE_DIR,
    TRANSCRIPT_DIR,
    HISTORY_DIR,
    VERIFY_DIR,
    FRAMES_DIR,
    ATTENUATED_DIR,
    WAVEFORM_DIR,
    RENDER_DIR,
    CARDS_DIR,
)


class ProjectError(Exception):
    """Raised when a path is not a usable lucid project."""


# -- schema migration --------------------------------------------------------


def _v1_to_v2(manifest: dict[str, Any]) -> dict[str, Any]:
    """v2 added the cue table (PLAN.md § The layered timeline).

    Additive: every v1 key means in v2 exactly what it meant in v1, so the
    step is the one missing list. `cue_add` would `setdefault` it anyway —
    writing it here is what makes the version number true rather than
    incidentally survivable.
    """
    manifest.setdefault("cues", [])
    return manifest


def _v2_to_v3(manifest: dict[str, Any]) -> dict[str, Any]:
    """v3 added footage descriptions (PLAN.md § B-roll by description).

    Additive, like v2 before it. It also covers the optional `src_start` a
    picture cue gains — one bump for both, because a v2 cue without one means
    in v3 exactly what it meant in v2 (take the asset from wherever the
    consumption cursor is), so no cue needs rewriting.
    """
    manifest.setdefault("descriptions", [])
    return manifest


#: Keyed by the version each step migrates *from*; a step returns the manifest
#: at version key+1, and `migrate` stamps the number. Stepwise rather than
#: one function per (from, to) pair, so the next bump is a single entry and
#: every older project reaches the present through the same path the one
#: before it took.
_MIGRATIONS: dict[int, Callable[[dict[str, Any]], dict[str, Any]]] = {
    1: _v1_to_v2,
    2: _v2_to_v3,
}


def _migratable(found: Any) -> bool:
    """Whether `Project.migrate` has a path from `found` to the current version.

    `bool` is excluded explicitly because it is an `int` subclass, so a
    manifest reading `"schema_version": true` would otherwise be treated as
    version 1 and migrated.
    """
    return (
        isinstance(found, int)
        and not isinstance(found, bool)
        and found < SCHEMA_VERSION
        and all(v in _MIGRATIONS for v in range(found, SCHEMA_VERSION))
    )


def _migration_steps(found: Any, manifest_path: Path) -> list[int]:
    """The versions to step through, or a refusal naming why there is no path."""
    if found == SCHEMA_VERSION:
        return []
    if not _migratable(found):
        if isinstance(found, int) and not isinstance(found, bool) and found > SCHEMA_VERSION:
            why = "it was written by a newer lucid, and migration is forward-only"
        else:
            why = f"no migration step is registered for schema_version {found!r}"
        raise ProjectError(
            f"cannot migrate {manifest_path}: {why} "
            f"(this lucid understands {SCHEMA_VERSION})"
        )
    return list(range(found, SCHEMA_VERSION))


@dataclass(frozen=True)
class Project:
    """A handle to a project directory. Cheap to construct; does no I/O."""

    root: Path

    # -- layout ----------------------------------------------------------

    @property
    def manifest_path(self) -> Path:
        return self.root / MANIFEST_NAME

    @property
    def timeline_path(self) -> Path:
        return self.root / TIMELINE_NAME

    @property
    def media_dir(self) -> Path:
        return self.root / MEDIA_DIR

    @property
    def transcript_dir(self) -> Path:
        return self.root / TRANSCRIPT_DIR

    @property
    def render_dir(self) -> Path:
        return self.root / RENDER_DIR

    @property
    def history_dir(self) -> Path:
        return self.root / HISTORY_DIR

    @property
    def verify_dir(self) -> Path:
        return self.root / VERIFY_DIR

    @property
    def frames_dir(self) -> Path:
        return self.root / FRAMES_DIR

    @property
    def attenuated_dir(self) -> Path:
        return self.root / ATTENUATED_DIR

    @property
    def waveform_dir(self) -> Path:
        return self.root / WAVEFORM_DIR

    @property
    def cards_dir(self) -> Path:
        return self.root / CARDS_DIR

    def transcript_path(self, clip_id: str) -> Path:
        return self.transcript_dir / f"{clip_id}.json"

    def waveform_path(self, clip_id: str) -> Path:
        return self.waveform_dir / f"{clip_id}.json"

    @property
    def thumbs_path(self) -> Path:
        return self.root / THUMBS_LOG

    # -- history ---------------------------------------------------------

    def snapshots(self) -> list[Path]:
        """Every saved timeline state, oldest first."""
        if not self.history_dir.exists():
            return []
        return sorted(self.history_dir.glob("*.otio"), key=lambda p: int(p.stem))

    def snapshot(self) -> Path | None:
        """Copy the current timeline into history before it is overwritten.

        A non-deterministic agent mutating a single source of truth in place is
        exactly the case where undo is not a tier-2 feature (PLAN.md). Returns
        None when there is no timeline yet — the first write has nothing to
        lose.
        """
        if not self.timeline_path.exists():
            return None
        self.history_dir.mkdir(parents=True, exist_ok=True)
        existing = self.snapshots()
        nxt = (int(existing[-1].stem) + 1) if existing else 0
        dest = self.history_dir / f"{nxt}.otio"
        shutil.copy2(self.timeline_path, dest)
        return dest

    def restore(self) -> Path:
        """Roll the timeline back to the most recent snapshot, consuming it."""
        existing = self.snapshots()
        if not existing:
            raise ProjectError("nothing to undo — this project has no history")
        latest = existing[-1]
        shutil.copy2(latest, self.timeline_path)
        latest.unlink()
        return latest

    # -- lifecycle -------------------------------------------------------

    @classmethod
    def create(cls, root: Path | str, *, name: str | None = None) -> Project:
        """Create a project directory. Refuses to overwrite an existing one."""
        project = cls(Path(root).expanduser().resolve())
        if project.manifest_path.exists():
            raise ProjectError(f"a lucid project already exists at {project.root}")

        project.root.mkdir(parents=True, exist_ok=True)
        for sub in _SUBDIRS:
            (project.root / sub).mkdir(parents=True, exist_ok=True)

        project.write_manifest(
            {
                "schema_version": SCHEMA_VERSION,
                "name": name or project.root.name,
                "clips": [],
                "cues": [],
                "descriptions": [],
            }
        )
        return project

    @classmethod
    def open(cls, root: Path | str) -> Project:
        """Open an existing project, validating its manifest."""
        project = cls(Path(root).expanduser().resolve())
        if not project.manifest_path.exists():
            raise ProjectError(f"no lucid project at {project.root} (no {MANIFEST_NAME})")

        manifest = project.read_manifest()
        found = manifest.get("schema_version")
        if found != SCHEMA_VERSION:
            way_out = (
                "run `lucid migrate` to bring it forward"
                if _migratable(found)
                else "there is no migration path from it"
            )
            raise ProjectError(
                f"{project.manifest_path} has schema_version {found!r}, "
                f"but this lucid understands {SCHEMA_VERSION} — {way_out}"
            )
        return project

    @classmethod
    def migrate(cls, root: Path | str, *, plan: bool = False) -> dict[str, Any]:
        """Bring an older manifest forward to `SCHEMA_VERSION`.

        Deliberately *not* folded into `Project.open`. Opening is a read, and a
        read that rewrites the file it just validated would migrate a project
        on `lucid info` — including one the reader only meant to look at, and
        one an older lucid elsewhere can still open until the moment it is
        touched. So `open` refuses and names this, and this does the writing.

        `plan=True` resolves the steps and writes nothing (CLAUDE.md), which is
        also the only way to ask "what version is this, and can it come
        forward?" without committing to the answer.
        """
        project = cls(Path(root).expanduser().resolve())
        if not project.manifest_path.exists():
            raise ProjectError(f"no lucid project at {project.root} (no {MANIFEST_NAME})")

        manifest = project.read_manifest()
        found = manifest.get("schema_version")
        steps = _migration_steps(found, project.manifest_path)

        report: dict[str, Any] = {
            "project": str(project.root),
            "schema_version": found,
            "target": SCHEMA_VERSION,
            "steps": [f"{v} -> {v + 1}" for v in steps],
            "migrated": False,
            "backup": None,
        }
        if plan:
            report["plan"] = True
            return report
        if not steps:
            return report

        report["backup"] = str(project._backup_manifest(found))
        for version in steps:
            manifest = _MIGRATIONS[version](manifest)
            manifest["schema_version"] = version + 1
        project.write_manifest(manifest)
        report["schema_version"] = SCHEMA_VERSION
        report["migrated"] = True
        return report

    def _backup_manifest(self, version: Any) -> Path:
        """Copy the manifest aside before a migration rewrites it.

        It sits beside the timeline snapshots because it is the same kind of
        thing: the state before a mutation. `snapshots()` globs `*.otio`, so a
        `.json` here is invisible to `undo` — which is right, since rolling the
        timeline back one edit must not roll the schema back with it.
        """
        self.history_dir.mkdir(parents=True, exist_ok=True)
        dest = self.history_dir / f"{Path(MANIFEST_NAME).stem}-v{version}.json"
        shutil.copy2(self.manifest_path, dest)
        return dest

    # -- manifest --------------------------------------------------------

    def read_manifest(self) -> dict[str, Any]:
        try:
            with self.manifest_path.open(encoding="utf-8") as fh:
                manifest = json.load(fh)
        except json.JSONDecodeError as exc:
            raise ProjectError(f"{self.manifest_path} is not valid JSON: {exc}") from exc
        if not isinstance(manifest, dict):
            raise ProjectError(f"{self.manifest_path} must contain a JSON object")
        return manifest

    def write_manifest(self, manifest: dict[str, Any]) -> None:
        """Write the manifest atomically, so a crash can't truncate it."""
        tmp = self.manifest_path.with_suffix(".json.tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            json.dump(manifest, fh, indent=2, sort_keys=True)
            fh.write("\n")
        tmp.replace(self.manifest_path)
