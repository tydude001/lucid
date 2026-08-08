"""The lucid project directory.

A project is a directory on disk. Nothing is uploaded, and every artifact is
inspectable with ordinary tools::

    myproject/
      lucid.json            manifest — schema version, clip registry, settings
      media/                imported source media (copies or symlinks)
      project.otio          the timeline; the source of truth tools mutate
      cache/
        transcripts/        <clip_id>.json — word-level timings, per clip
        verify/             <render>.json — what a finished render was heard to say
        frames/             <render-stem>/*.png — spot-check frames pulled from a render
      renders/              preview.mp4, final.mp4, …

The OTIO file is authoritative for the edit; renders are derived from it and
are safe to delete. The manifest is authoritative for *identity* — which clip
a `clip_id` refers to, and where its media lives.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

#: Bumped when the on-disk layout changes incompatibly.
SCHEMA_VERSION = 1

MANIFEST_NAME = "lucid.json"
TIMELINE_NAME = "project.otio"

MEDIA_DIR = "media"
CACHE_DIR = "cache"
TRANSCRIPT_DIR = "cache/transcripts"
HISTORY_DIR = "cache/history"
VERIFY_DIR = "cache/verify"
FRAMES_DIR = "cache/frames"
RENDER_DIR = "renders"

_SUBDIRS = (MEDIA_DIR, CACHE_DIR, TRANSCRIPT_DIR, HISTORY_DIR, VERIFY_DIR, FRAMES_DIR, RENDER_DIR)


class ProjectError(Exception):
    """Raised when a path is not a usable lucid project."""


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

    def transcript_path(self, clip_id: str) -> Path:
        return self.transcript_dir / f"{clip_id}.json"

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
            raise ProjectError(
                f"{project.manifest_path} has schema_version {found!r}, "
                f"but this lucid understands {SCHEMA_VERSION}"
            )
        return project

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
