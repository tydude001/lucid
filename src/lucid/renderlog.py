"""The render log — `cache/renders.jsonl`, one line per finished pipeline run.

**Cache artifact only. No manifest key. No schema bump.** Mirrors
`Project.thumbs_path`'s own precedent exactly (`project.py`'s `THUMBS_LOG`):
this is derived telemetry, not part of the edit — nothing here is
authoritative for the timeline or the manifest, `_revision()` in webui.py
never stats it, and a render pipeline run is not a project mutation. It
exists so `ops.finish_report` can answer "did the last render actually burn
captions in" without re-running or re-parsing anything — docs/plans/STUDIO.md § Step 01
is explicit that an absent log is a warning (`captions.burned == "unknown"`),
never an error and never a reason to guess.

One line is one whole `RenderJob` run (`webui.py`): which stages were
attempted, what each one's outcome was, and the output path/preset/expected
duration at the time. `append` is the only writer; `last`/`all_runs` are the
only readers. Nothing here parses the render pipeline's own stage logic —
this module only serializes and deserializes what the caller already decided
happened.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from lucid.project import Project


def append(
    project: Project,
    *,
    output: str,
    preset: str | None,
    expected_duration: float,
    stages: dict[str, dict[str, Any]],
) -> None:
    """Append one run to the log. Stamps its own timestamp — callers never pass one.

    Only stages actually *attempted* belong in `stages`; a run that failed at
    `export` writes a `stages` dict holding only `export`, nothing for the
    stages never reached (`check_frames`/`verify` in particular, since those
    are always the last two attempted).
    """
    project.renders_log_path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "timestamp": datetime.now(UTC).isoformat(),
        "output": output,
        "preset": preset,
        "expected_duration": expected_duration,
        "stages": stages,
    }
    with project.renders_log_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, default=str) + "\n")


def last(project: Project) -> dict[str, Any] | None:
    """The most recent run, or `None` if the log is absent or unreadable.

    Walks the file in reverse so a corrupted trailing line — a crash mid-write
    left a half-written last line — cannot hide every real run before it;
    the first line (from the end) that parses as JSON wins.
    """
    path = project.renders_log_path
    if not path.exists():
        return None
    lines = path.read_text(encoding="utf-8").splitlines()
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            continue
    return None


def all_runs(project: Project) -> list[dict[str, Any]]:
    """Every parseable run, oldest first — a malformed line is skipped, not fatal."""
    path = project.renders_log_path
    if not path.exists():
        return []
    runs: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            runs.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return runs
