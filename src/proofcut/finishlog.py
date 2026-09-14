"""The finish-check log — `cache/finish_checks.jsonl`, one line per
`ops.finish_check` run.

**Cache artifact only. No manifest key. No schema bump.** `renderlog.py`'s
own shape, cloned rather than reused, because it answers about a different
artifact: a render this project's own `export` produced (`renderlog`)
against a *delivered* file proofcut did not produce, that an external mix pass
built out of one of this project's renders (`finishlog`). Neither watches
the other, and `webui._revision()` must never stat this file either — a
finish_check run is derived telemetry about an artifact outside the edit,
not a project mutation.

`append` is the only writer; `last`/`all_runs`/`for_sha256` are the only
readers. `for_sha256` is the join key `proofcut review serve` needs: every
registered review item already carries its own `sha256` (`ops.review_add`),
so joining on that rather than on a filename is what lets a delivered file
be re-registered under a new name, or the same bytes registered twice, and
still find the finish_check that was run against those exact bytes.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from proofcut.project import Project


def append(
    project: Project,
    *,
    final: str,
    sha256: str,
    faults: int,
    ok: bool,
    summary: dict[str, Any],
) -> None:
    """Append one finish_check run to the log. Stamps its own timestamp —
    callers never pass one, `renderlog.append`'s own discipline.
    """
    project.finish_checks_log_path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "timestamp": datetime.now(UTC).isoformat(),
        "final": final,
        "sha256": sha256,
        "faults": faults,
        "ok": ok,
        "summary": summary,
    }
    with project.finish_checks_log_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, default=str) + "\n")


def last(project: Project) -> dict[str, Any] | None:
    """The most recent finish_check run, or `None` if the log is absent or
    unreadable.

    Walks the file in reverse — `renderlog.last`'s own precaution — so a
    crash mid-write leaving a half-written last line cannot hide every real
    run before it.
    """
    path = project.finish_checks_log_path
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
    """Every parseable finish_check run, oldest first — a malformed line is
    skipped, not fatal."""
    path = project.finish_checks_log_path
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


def for_sha256(project: Project, sha256: str) -> dict[str, Any] | None:
    """The most recent finish_check run whose own `final` file hashed to
    `sha256`, or `None` if none ever did.

    Walked in reverse for the same reason `last` is: the newest matching run
    is the one whose verdict is still current, on the (rare) chance a file's
    bytes were checked more than once.
    """
    path = project.finish_checks_log_path
    if not path.exists():
        return None
    lines = path.read_text(encoding="utf-8").splitlines()
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if record.get("sha256") == sha256:
            return record
    return None
