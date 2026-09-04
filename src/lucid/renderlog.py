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

One line is one whole run: which stages were attempted, what each one's
outcome was, and the output path/preset/expected duration at the time.
Nothing here parses the render pipeline's own stage logic — this module only
serializes and deserializes what the caller already decided happened.

**There are two writers, because there are two shapes of render.** The web
UI's `RenderJob` runs the whole pipeline itself and knows the whole run at
once, so it calls `append`. The CLI and the MCP server have no pipeline —
an agent renders with `export` and then burns with `add_captions`, two
separate calls minutes apart — so those two ops call `amend`, which carries
the earlier stages of the same render forward onto a new line rather than
starting a second run that would hide the first. Until 2026-09-04 neither
wrote anything at all, and `finish_report` answered `captions.burned` with
`"unknown"` for two of lucid's three clients on films whose captions were
demonstrably burned in (TRIAL.md § 2).
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


def amend(
    project: Project,
    *,
    output: str,
    preset: str | None,
    expected_duration: float,
    stages: dict[str, dict[str, Any]],
    continues: str | None = None,
) -> None:
    """Append a run that carries the last one's stages forward, when it is the same render.

    `continues` is the file the new stage consumed — `add_captions(burn=X)`
    passes `X`. When it matches the last run's `output`, this is a later stage
    of *that* render and its stages are merged onto the new line; otherwise
    this is a new render and only `stages` is written.

    The file stays append-only — a merge is a new line, not an edit — because
    `last` reads from the end and a superseding line is what it will find. The
    superseded line is left in place for `all_runs`, which is how a render that
    was burned twice still shows both attempts.

    The stage dicts themselves are never merged: a stage present in `stages`
    replaces the earlier one wholesale, since a second burn onto the same
    export is a new answer to the same question, not an addition to the old
    one.
    """
    carried: dict[str, dict[str, Any]] = {}
    if continues is not None:
        previous = last(project)
        if previous is not None and previous.get("output") == continues:
            carried = dict(previous.get("stages") or {})
            # The preset is the export's property, and a later stage of the
            # same render does not know it — `add_captions` has no preset of
            # its own to pass. Carry the earlier one rather than writing null
            # over it, which would make the burn look like an unpresetted
            # render of its own.
            if preset is None:
                preset = previous.get("preset")
    append(
        project,
        output=output,
        preset=preset,
        expected_duration=expected_duration,
        stages={**carried, **stages},
    )


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
