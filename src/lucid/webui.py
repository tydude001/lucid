"""The preview/timeline web UI — a third client, never a third implementation.

lucid's checks all answer a *machine's* question: `verify` diffs the render's
words, `frames`/`black`/`spots` read counts and pixels. None of them let a
person see an edit before committing to a render. This does — and because it
plays the *source* through the edit rather than a render of it, seeing an edit
costs no render at all.

Two constraints hold it in place, both from HISTORY.md § The preview/timeline web UI:

* **No privileged path.** Every mutation here goes through the same `ops`
  functions the CLI and the MCP server call. A window is the most tempting
  thing to break the parity convention with, so nothing below computes an
  edit — it posts to `ops.cut_by_transcript` / `ops.cut_by_time` / `ops.undo`
  and draws whatever comes back. The agent panel does not change this: it is
  a *client* of the same MCP tools, reaching the timeline through no path the
  page's own buttons don't already use.
* **Local, in-package.** `http.server` from the standard library, static
  assets shipped beside this file, no build step and no second stack. The one
  thing hand-rolled rather than inherited is HTTP Range, because a browser
  will not seek in a `<video>` without it.

It binds loopback only. Two further guards matter because this server can
mutate a project and read media, and any page you happen to be browsing can
issue requests to `localhost`:

* the `Host` header must name loopback, which is what stops a DNS-rebinding
  page from reaching it under its own name;
* every mutating request must be `application/json`, which an HTML form
  cannot send — so a cross-origin attempt becomes a preflight, and no CORS
  headers are ever served to satisfy one.
"""

from __future__ import annotations

import json
import mimetypes
import os
import queue
import shutil
import subprocess
import tempfile
import threading
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from lucid import captions, media, ops, renderlog
from lucid.asr import ASRError
from lucid.autoeditor import AutoEditorError
from lucid.energy import EnergyError
from lucid.faces import FaceError
from lucid.media import MediaError
from lucid.mlt import MLTError
from lucid.picture import PictureError
from lucid.project import (
    CACHE_DIR,
    MANIFEST_NAME,
    SCHEMA_VERSION,
    Project,
    ProjectError,
)
from lucid.timeline import TimelineError
from lucid.transcript import TranscriptError
from lucid.verify import VerifyError

#: The same family the CLI flattens into a one-line message. Anything outside
#: it is a bug and keeps its traceback rather than being reported as a 400.
EXPECTED = (
    ProjectError,
    MediaError,
    TranscriptError,
    TimelineError,
    AutoEditorError,
    captions.CaptionError,
    ASRError,
    VerifyError,
    PictureError,
    EnergyError,
    # `plan_picture`'s refusals — a shot longer than its asset. `timeline_view`
    # reports that one rather than raising it (the picture lane draws the
    # message), but `export` still raises it, and it is a 400 like the rest.
    MLTError,
    # `reframe_detect`/`reframe_sheet(extremes=True)`'s refusal when no
    # interpreter has a face detector — without this here, a missing
    # `LUCID_FACE` on this box turns into an unhandled exception inside
    # `ReframeDetectJob._run`'s `try/except EXPECTED`: no error event is
    # published, `_finish()` never runs, and the view spins forever waiting
    # on an SSE event that will never arrive (Studio Step 03 contract § A).
    FaceError,
)

STATIC_DIR = Path(__file__).parent / "web"

DEFAULT_HOST = "127.0.0.1"
#: Deliberately not 8000/8080. Those collide with whatever else is being
#: served on a dev box, and a collision here looks like lucid showing someone
#: else's page.
DEFAULT_PORT = 8710

#: Hostnames a request may claim to have reached. A browser sends whatever the
#: user typed, so an attacker-controlled name resolving to 127.0.0.1 arrives
#: here looking local unless the header itself is checked.
_LOOPBACK_NAMES = frozenset({"localhost", "127.0.0.1", "::1", "[::1]"})

_STATIC_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".svg": "image/svg+xml",
    # The three type voices, vendored beside the stylesheet rather than
    # fetched from a CDN — which the `default-src 'self'` CSP would refuse
    # anyway (DAYDREAM.md § Typography). Flat names, because `_send_static`
    # serves a filename and never a path.
    ".woff2": "font/woff2",
}

#: Read size for streaming media. Large enough that a long range is not a
#: million syscalls, small enough that an aborted seek stops promptly.
_CHUNK = 256 * 1024

#: How often the SSE handler checks whether the revision moved (PLAN.md §
#: Tier 3 is the goal, lines 1794-1798). Simple beats exact: this one poll
#: loop is what lets an agent edit, the page's own edit, and a `lucid cut` in
#: a terminal all raise the same event instead of three code paths.
_REVISION_POLL_SECONDS = 0.5

#: `claude` by default; overridable so tests never spawn the real thing.
AGENT_BIN_ENV = "LUCID_AGENT_BIN"

#: The agent's tool allowlist — the security boundary, not a convenience
#: default (PLAN.md § The agent panel, in mechanism). `--permission-mode
#: manual` is the belt to this allowlist's braces: there is no TTY on a
#: subprocess, so anything falling outside the allowlist fails closed rather
#: than prompting. Do not widen this without writing the decision down there.
#:
#: `--allowedTools`/`--disallowedTools`/`--permission-mode manual` alone do
#: **not** bound the built-in tool set — verified against the installed
#: claude 2.1.226: a built-in tool named in neither list (`Glob`, in the
#: reproduction) runs with no permission gate at all, because those flags
#: govern *permission prompts*, and a tool outside the allowlist without a
#: matching disallow entry is simply never asked about. `--tools ""` is the
#: actual boundary for the built-in set — it disables all of it, leaving only
#: the MCP tools `--strict-mcp-config` exposes, which is what makes "the
#: agent gets lucid's MCP tools and nothing else" true. `_AGENT_DISALLOWED_TOOLS`
#: stays as defense in depth, not because it does the job on its own.
_AGENT_ALLOWED_TOOLS = "mcp__lucid__*"
_AGENT_DISALLOWED_TOOLS = ("Bash", "Write", "Edit", "WebFetch", "WebSearch")


class WebUIError(Exception):
    """Raised when a request cannot be served for a reason worth reporting."""


class RenderBusyError(WebUIError):
    """A second render was requested while one was already running.

    Its own type rather than a plain `WebUIError` so the handler can answer
    409 (a real conflict with server state) instead of 400 (a bad request) —
    the identical request would succeed once the first job finishes.
    """


class ProxyBusyError(WebUIError):
    """A second proxy transcode was requested while one was already running.

    Same 409-not-400 reasoning as `RenderBusyError`, and deliberately its own
    type rather than a shared one: a busy proxy must not be reported as a busy
    render, since the two jobs have separate slots and the message is what
    tells a person which to wait for.
    """


class ReframeSheetBusyError(WebUIError):
    """A second sheet generation was requested while one was already running.

    Its own type, same 409-not-400 reasoning as `RenderBusyError`/
    `ProxyBusyError` — a busy sheet job must not be reported as a busy detect
    job or a busy render, since each has its own slot.
    """


class ReframeDetectBusyError(WebUIError):
    """A second detect pass was requested while one was already running."""


def _json_body(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
    """Read and parse a JSON request body, enforcing the content type.

    The content type is a guard, not a formality: `application/json` is not a
    type an HTML form can produce, so requiring it is what makes a
    cross-origin POST take the preflight path this server never answers.
    """
    ctype = (handler.headers.get("Content-Type") or "").split(";")[0].strip().lower()
    if ctype != "application/json":
        raise WebUIError("request body must be application/json")
    try:
        length = int(handler.headers.get("Content-Length") or 0)
    except ValueError:
        raise WebUIError("bad Content-Length") from None
    if length <= 0:
        return {}
    raw = handler.rfile.read(length)
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise WebUIError(f"body is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise WebUIError("body must be a JSON object")
    return payload


#: How far beneath `--root` the scan looks for a project. Real dogfood
#: layouts put one at depth 1 (`~/lucid-dogfood/scream-vo` is itself the
#: project, two path segments under a `~/` root) and at depth 2
#: (`~/lucid-teaser/proj`, an explicit `proj` subdirectory) — this covers
#: both without wandering into an unrelated deep tree. A directory a scan
#: finds a project in is never descended into further: its own `history/`
#: backups are named `lucid-vN.json`, never `lucid.json` (`Project.migrate`),
#: so there is no false positive to worry about, but stopping there also
#: keeps a big `--root` cheap to scan on every picker load.
_SCAN_MAX_DEPTH = 3

#: Directories a scan never opens, whether or not they hold a project one
#: level down — dev-tooling trees that can be enormous and are never where a
#: project lives.
_SCAN_SKIP_NAMES = frozenset({".git", ".venv", "venv", "node_modules", "__pycache__"})


def scan_projects(root: Path) -> list[dict[str, Any]]:
    """Find lucid projects under `root` (DAYDREAM.md § Multi-project).

    A project is a directory holding `lucid.json` (`Project.MANIFEST_NAME`)
    directly — not a directory containing one somewhere inside it, which
    would also match every project's own `history/` backups' *parent*.
    Never opens a manifest at the wrong schema and never migrates one
    (CLAUDE.md: `Project.open` refuses an old manifest and a read must never
    rewrite a project someone only looked at) — each entry says what was
    found instead:

    * `status: "ok"` — opened cleanly; `name`, `timeline_duration`,
      `segments` and `clips` are `ops.status`'s own cheap read, the same one
      the workspace's top bar uses.
    * `status: "needs_migration"` — a manifest at a schema `Project.open`
      refuses; `schema_version` names what was found. Listed, not skipped
      and not opened — `lucid migrate -C <path>` is the way forward, and the
      picker says so without taking it.
    * `status: "unreadable"` — any other `ProjectError` (bad JSON, a
      manifest that is not a JSON object, or a read that raced the
      directory listing) — `error` carries `Project.open`'s own message.
    * `status: "error"` — the manifest itself read fine at the current
      schema, but `ops.status` (the same cheap read the `ok` case uses)
      raised one of `EXPECTED` — an un-seeded project (`lucid init` with no
      `lucid seed` yet) is the ordinary way to hit this, not a corrupt
      project. Listed with `error` carrying the message, same as
      `unreadable` — one bad project must never take the whole `/api/projects`
      listing down with it.

    A directory with no `lucid.json` at all is not a project and is not in
    the returned list — that is the "skip a non-project directory" case, and
    it produces no entry rather than a fifth kind of failure.
    """
    root = Path(root)
    found: list[dict[str, Any]] = []

    def walk(directory: Path, depth: int) -> None:
        if depth > _SCAN_MAX_DEPTH:
            return
        try:
            # `is_symlink()` excludes a symlinked directory, not just a
            # symlinked file — a symlink placed under `--root` can point
            # anywhere on disk, and `is_dir()` alone follows it. `/api/open`
            # confines by `.resolve()` at bind time regardless, but the scan
            # must not *report* metadata (name, segment/clip counts) for a
            # directory `--root` was never scanned to include.
            children = sorted(p for p in directory.iterdir() if p.is_dir() and not p.is_symlink())
        except OSError:
            return
        for child in children:
            if child.name.startswith(".") or child.name in _SCAN_SKIP_NAMES:
                continue
            if (child / MANIFEST_NAME).is_file():
                found.append(_scan_one(child))
                continue  # never descend into a project's own subdirectories
            walk(child, depth + 1)

    walk(root, 1)
    found.sort(key=lambda entry: entry["path"])
    return found


def _scan_one(path: Path) -> dict[str, Any]:
    """Classify one directory already known to hold `lucid.json`."""
    entry: dict[str, Any] = {"path": str(path), "name": path.name}
    # Resume line (Studio Step 04 § D): a plain, best-effort file read that
    # rides this scan rather than adding a second one — no `Project.open`,
    # no binding. Works for every status below, `needs_migration` included,
    # because `session.json` carries no schema version of its own.
    session_file = path / CACHE_DIR / "session.json"
    if session_file.is_file():
        try:
            with session_file.open(encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, dict):
                entry["session"] = data
        except (json.JSONDecodeError, OSError):
            pass  # no resume line for this project; the rest of the entry stands
    project = Project(path)
    try:
        manifest = project.read_manifest()
    except (ProjectError, OSError) as exc:
        entry["status"] = "unreadable"
        entry["error"] = str(exc)
        return entry
    found_version = manifest.get("schema_version")
    if found_version != SCHEMA_VERSION:
        entry["status"] = "needs_migration"
        entry["schema_version"] = found_version
        return entry
    try:
        info = ops.status(path)
    except EXPECTED as exc:
        # A current-schema project whose manifest reads fine can still fail
        # here — no timeline seeded yet is the ordinary case. One bad
        # project must not take the whole listing down (webui.py's own
        # `_route_picker` would otherwise turn this into a 400 for
        # everyone under `--root`, not just the broken one).
        entry["status"] = "error"
        entry["error"] = str(exc)
        return entry
    entry["status"] = "ok"
    entry["timeline_duration"] = info["timeline_duration"]
    entry["segments"] = info["segments"]
    entry["clips"] = len(info["clips"])
    return entry


def _ranges(spec: str, size: int) -> tuple[int, int] | None:
    """Parse a single-range `Range: bytes=` header against a known size.

    Only the first range of a multi-range request is honoured — serving
    `multipart/byteranges` would be real work and no browser needs it for
    media playback. Returns None when the header is unusable, which means
    "serve the whole thing" rather than an error.
    """
    if not spec.lower().startswith("bytes="):
        return None
    first, sep, last = spec[6:].split(",")[0].strip().partition("-")
    if not sep:
        return None
    try:
        if first:
            start = int(first)
            end = int(last) if last else size - 1
        elif last:
            # Suffix form, `bytes=-500`: the final N bytes.
            start = max(0, size - int(last))
            end = size - 1
        else:
            return None
    except ValueError:
        return None
    if start < 0 or start >= size or end < start:
        raise WebUIError(f"range {spec!r} does not fit a {size}-byte file")
    return start, min(end, size - 1)


def _stream_file(handler: BaseHTTPRequestHandler, source: Path, *, head_only: bool) -> None:
    """Byte-range streaming, shared by every route that hands over a file.

    Takes `handler` rather than being a method, the `_json_body` shape —
    `reviewserver.py` streams renders and sheets over LAN under a different
    guard (a token, not loopback+Host) and reuses this rather than
    reimplementing Range parsing a second time, which is the one piece of
    HTTP this package hand-rolls in the first place (module docstring).
    """
    size = source.stat().st_size
    ctype = mimetypes.guess_type(source.name)[0] or "application/octet-stream"
    header = handler.headers.get("Range")
    window = _ranges(header, size) if header else None

    if window is None:
        start, end, status = 0, size - 1, HTTPStatus.OK
    else:
        start, end = window
        status = HTTPStatus.PARTIAL_CONTENT

    length = end - start + 1
    handler.send_response(status)
    handler.send_header("Content-Type", ctype)
    handler.send_header("Content-Length", str(length))
    handler.send_header("Accept-Ranges", "bytes")
    if status == HTTPStatus.PARTIAL_CONTENT:
        handler.send_header("Content-Range", f"bytes {start}-{end}/{size}")
    handler.send_header("X-Content-Type-Options", "nosniff")
    handler.end_headers()
    if head_only:
        return

    with source.open("rb") as fh:
        fh.seek(start)
        remaining = length
        while remaining > 0:
            chunk = fh.read(min(_CHUNK, remaining))
            if not chunk:
                break
            try:
                handler.wfile.write(chunk)
            except (BrokenPipeError, ConnectionResetError):
                # A seek aborts the in-flight range. Routine, not an error.
                return
            remaining -= len(chunk)


def _revision(project_root: Path) -> list[float | int]:
    """`project.otio` mtime, the manifest's, and undo depth (PLAN.md § View
    invalidation).

    Not a single counter: a mutation changes the otio mtime, an undo changes
    the depth without necessarily changing that mtime to something
    new-looking (a restore overwrites the file, but a second undo back to a
    state that was never re-saved can otherwise look unchanged). Comparing
    the tuple catches both.

    **The manifest is in here because two things the view draws live in it and
    not in the timeline at all** — the cue table behind the V2 lane, and the
    caption style the preview overlay draws. `cue_add` and `caption_style`
    write the manifest and never touch `project.otio`, so a revision that
    watched the timeline alone left an open window showing the old picture
    lane until something unrelated moved the edit.
    """
    project = Project.open(project_root)
    timeline = project.timeline_path
    mtime = timeline.stat().st_mtime if timeline.exists() else 0.0
    manifest = project.manifest_path
    return [mtime, manifest.stat().st_mtime if manifest.exists() else 0.0, len(project.snapshots())]


def _session_get(root: str) -> dict[str, Any]:
    """`GET /api/session` — read back `cache/session.json`, or `{}`.

    Best-effort by design (Studio Step 04 contract § B): a missing or
    corrupt session file restores nothing rather than failing the page
    load, since it holds nothing but UI convenience state — playhead, zoom,
    scroll, pane-expand, mode, selection — and every key is optional on
    both read and write.
    """
    project = Project.open(root)
    path = project.session_path
    if not path.is_file():
        return {}
    try:
        with path.open(encoding="utf-8") as fh:
            data = json.load(fh)
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def _session_set(root: str, payload: dict[str, Any]) -> dict[str, Any]:
    """`POST /api/session` — replace `cache/session.json` wholesale.

    Deliberately does not touch `project.otio` or the manifest: `_revision()`
    (above) only stats `project.timeline_path`, `project.manifest_path`, and
    counts `project.snapshots()`, and this writes to none of the three — so
    no `project-changed` event fires from this call, the same fact
    `_agent_thumb`'s own docstring states about `Project.thumbs_path`.

    Full-object replace, last-write-wins: the client always POSTs its whole
    current snapshot, never a partial patch, so there is nothing to merge
    here. Atomic write, `Project.write_manifest`'s own tmp+`.replace()`
    pattern (project.py:439-445), aimed at `session_path` instead of
    `manifest_path` — cache, no schema version, disposable by design.
    """
    project = Project.open(root)
    path = project.session_path
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, sort_keys=True)
        fh.write("\n")
    tmp.replace(path)
    return {"saved": True}


def _ensure_poster(project: Project, view: dict[str, Any]) -> None:
    """Best-effort — a poster failure must never break `/api/view`.

    Written once, on the workspace's first real data fetch (whether reached
    via `-C` or via `/api/open`) — no auto-refresh. `view["shots"]` is
    `timeline_view`'s own picture-lane projection (already through
    `mlt.plan_picture`), and its first shot's `asset` is the footage
    actually on screen — CLAUDE.md: a shot's *addressing* clip (`clip_id`)
    is not its footage, and reaching in by `clip_id` is the exact bug the
    first filmstrip draft had.

    `ops.thumbnail` is used unmodified: it resolves the source through
    `media.media_path()`, never `media.preview_path()`, and caches its own
    frame under `cache/thumbs/<clip_id>/<ms>.jpg`. This function does a
    plain byte copy of that cached frame into the stable `cache/poster.jpg`
    name the picker's `_send_poster` serves — not a symlink, not a reused
    path — so the thumbnail cache can be pruned independently later without
    breaking the poster.
    """
    if project.poster_path.is_file():
        return  # written once; no auto-refresh
    shots = view.get("shots") or []
    if not shots:
        return  # audio-only or unedited project: no poster, acceptable
    first = shots[0]
    asset_clip_id = first.get("asset")
    if not asset_clip_id:
        return
    at = first.get("src_start") or 0.0
    resolved = ops.thumbnail(str(project.root), asset_clip_id, at)
    project.poster_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(Path(resolved["path"]), project.poster_path)


class EventBus:
    """A lock and a set of per-subscriber queues — nothing cleverer than that.

    `project-changed` is polled straight off `_revision` inside the SSE
    handler; `agent` and `render` events are *pushed* here by other server
    code (the agent subprocess reader and the render job, respectively) and
    fan out to every open `/api/events` connection. One bus per server,
    because one server serves one project.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._subscribers: set[queue.Queue[tuple[str, dict[str, Any]]]] = set()

    def subscribe(self) -> queue.Queue[tuple[str, dict[str, Any]]]:
        q: queue.Queue[tuple[str, dict[str, Any]]] = queue.Queue()
        with self._lock:
            self._subscribers.add(q)
        return q

    def unsubscribe(self, q: queue.Queue[tuple[str, dict[str, Any]]]) -> None:
        with self._lock:
            self._subscribers.discard(q)

    def publish(self, event: str, data: dict[str, Any]) -> None:
        with self._lock:
            subscribers = list(self._subscribers)
        for q in subscribers:
            q.put((event, data))


def _agent_bin() -> str:
    return os.environ.get(AGENT_BIN_ENV, "claude")


class AgentSession:
    """One `claude -p` subprocess per server, spawned lazily on first prompt.

    PLAN.md § The agent panel, in mechanism: `--strict-mcp-config` confines it
    to a generated config holding *only* lucid's MCP server (never the user's
    own Gmail/Drive/Calendar servers), the allowlist above is the sole path it
    has into the project, and `--permission-mode manual` fails anything
    outside that allowlist closed rather than prompting a TTY that isn't
    there. There is no `--cwd` flag — the working directory is set on the
    Popen instead.
    """

    def __init__(self, project_root: Path, bus: EventBus) -> None:
        self.project_root = project_root
        self.bus = bus
        self._lock = threading.Lock()
        self._proc: subprocess.Popen[str] | None = None
        self._mcp_config_path: Path | None = None
        #: Set only by `close()`'s kill branch, and only when it actually
        #: kills a live proc — never unconditionally, or it would wrongly
        #: swallow a *genuine* future crash report after an earlier no-op
        #: reset. Consumed once, by `_pump_stdout`'s silent-exit branch, so a
        #: deliberate `reset()` (item 4, DAYDREAM.md § Agent panel) does not
        #: also surface as a synthetic `error_no_output` result event.
        self._suppress_next_exit_report = False

    def _mcp_config(self) -> Path:
        """Write the generated one-server MCP config lazily, once.

        `lucid -C <project> mcp` is the invocation that actually binds the
        server to this project — `-C` is a global flag that argparse only
        accepts *before* the subcommand (`lucid mcp -C <project>` does not
        parse), so it is spelled out here as `command`/`args` rather than as
        a single shell string.
        """
        if self._mcp_config_path is None:
            config = {
                "mcpServers": {
                    "lucid": {
                        "command": "lucid",
                        "args": ["-C", str(self.project_root), "mcp"],
                    }
                }
            }
            fd, name = tempfile.mkstemp(prefix="lucid-mcp-", suffix=".json")
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(config, fh)
            self._mcp_config_path = Path(name)
        return self._mcp_config_path

    def _spawn(self) -> subprocess.Popen[str]:
        argv = [
            _agent_bin(),
            "-p",
            "--verbose",
            "--input-format",
            "stream-json",
            "--output-format",
            "stream-json",
            "--mcp-config",
            str(self._mcp_config()),
            "--strict-mcp-config",
            "--tools",
            "",
            "--allowedTools",
            _AGENT_ALLOWED_TOOLS,
            "--disallowedTools",
            *_AGENT_DISALLOWED_TOOLS,
            "--permission-mode",
            "manual",
        ]
        proc = subprocess.Popen(
            argv,
            cwd=str(self.project_root),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        stderr_tail: list[str] = []
        stderr_thread = threading.Thread(
            target=self._pump_stderr, args=(proc, stderr_tail), daemon=True
        )
        stderr_thread.start()
        threading.Thread(
            target=self._pump_stdout,
            args=(proc, stderr_tail, stderr_thread),
            daemon=True,
        ).start()
        return proc

    @staticmethod
    def _pump_stderr(proc: subprocess.Popen[str], tail: list[str]) -> None:
        """Keep the last ~200 lines of stderr, for `_pump_stdout`'s silent-exit report.

        Read continuously rather than at the end: `claude` writing enough to
        fill the pipe buffer while nobody drains it would otherwise deadlock
        the subprocess against its own stderr.
        """
        assert proc.stderr is not None
        for line in proc.stderr:
            tail.append(line)
            del tail[:-200]

    def _pump_stdout(
        self,
        proc: subprocess.Popen[str],
        stderr_tail: list[str],
        stderr_thread: threading.Thread,
    ) -> None:
        """Parse one `stream-json` line at a time and publish it as-is.

        The page styles the event; this only has to pass the parsed JSON
        through, unchanged, the same way `ops.timeline_view` hands the page
        numbers rather than a rendering of them.

        If the process exits without ever emitting a `result` event — a CLI
        flag mismatch that errors and exits 0 before printing anything is the
        reproduction that found this — the page's composer has nothing to
        clear `busy` on and hangs forever with no visible failure. A
        synthetic `result` event with a non-"success" subtype covers that:
        `agent.js`'s `handleResult` already renders any such subtype and
        clears `busy` regardless of what it says.
        """
        assert proc.stdout is not None
        saw_result = False
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict) and payload.get("type") == "result":
                saw_result = True
            self.bus.publish("agent", payload)
        if saw_result:
            return
        proc.wait()
        # stderr is drained by its own thread; without this join a fast exit
        # can report a truncated tail while that thread is still mid-read.
        stderr_thread.join(timeout=2)
        with self._lock:
            suppressed, self._suppress_next_exit_report = self._suppress_next_exit_report, False
        if suppressed:
            # A deliberate `reset()` (item 4) killed this proc on purpose —
            # the exit is expected, not a silent failure, so it gets no
            # synthetic result event. The client clears `busy` itself instead
            # of waiting on this stream (see `_handle_agent_new_task`).
            return
        detail = "".join(stderr_tail).strip()[-2000:] or (
            f"the agent process exited (code {proc.returncode}) without producing a response"
        )
        self.bus.publish(
            "agent",
            {"type": "result", "subtype": "error_no_output", "result": detail},
        )

    def send(self, prompt: str) -> None:
        with self._lock:
            if self._proc is None or self._proc.poll() is not None:
                self._proc = self._spawn()
            proc = self._proc
        message = {
            "type": "user",
            "message": {"role": "user", "content": [{"type": "text", "text": prompt}]},
        }
        assert proc.stdin is not None
        proc.stdin.write(json.dumps(message) + "\n")
        proc.stdin.flush()

    def stop(self) -> None:
        """Interrupt the running turn.

        `claude`'s `stream-json` input protocol takes a `control_request` of
        subtype `interrupt` on stdin (verified against the installed 2.1.226
        binary's own control-plane strings, not recalled). That is tried
        first; if the pipe is already gone the process is killed instead and
        the next prompt lazily respawns it — the documented fallback this
        stage was asked to fall back to.
        """
        with self._lock:
            proc = self._proc
        if proc is None or proc.poll() is not None:
            return
        control = {
            "type": "control_request",
            "request_id": str(uuid.uuid4()),
            "request": {"subtype": "interrupt"},
        }
        try:
            assert proc.stdin is not None
            proc.stdin.write(json.dumps(control) + "\n")
            proc.stdin.flush()
        except (BrokenPipeError, OSError):
            proc.kill()
            with self._lock:
                if self._proc is proc:
                    self._proc = None

    def close(self) -> None:
        """Server shutdown: kill the subprocess and remove the generated config.

        Nothing else reaps either one — the subprocess otherwise outlives the
        server it belonged to, and every session that prompted the agent
        would leave one `lucid-mcp-*.json` behind in `$TMPDIR`.

        Also the mechanism `reset()` (item 4) reuses for a live mid-session
        "Start New Task": when a proc is actually killed here, the
        `_suppress_next_exit_report` flag is set first so `_pump_stdout`'s
        silent-exit safety net — written for a genuinely broken subprocess —
        does not also fire for this deliberate kill.
        """
        with self._lock:
            proc, self._proc = self._proc, None
            config, self._mcp_config_path = self._mcp_config_path, None
        if proc is not None and proc.poll() is None:
            with self._lock:
                self._suppress_next_exit_report = True
            proc.kill()
            proc.wait(timeout=5)
        if config is not None:
            try:
                config.unlink(missing_ok=True)
            except OSError:
                pass

    def reset(self) -> None:
        """`POST /api/agent/new-task`: kill the running subprocess so the next
        prompt spawns fresh with no conversation history.

        Same mechanics as `close()` — the alias exists so a live per-request
        reset does not read as server shutdown, which is `close()`'s only
        caller today. `send()` already respawns lazily
        (`if self._proc is None or self._proc.poll() is not None`), so "fresh
        subprocess turn" needs nothing beyond making the current one gone.
        """
        self.close()


def _run_checks(project_root: Path, output: Path, has_video: bool) -> dict[str, Any]:
    """What the checks that already exist say about this render.

    PLAN.md § Finishing — the render happens in the window: `verify`,
    `check_frames`, `check_black` and `spot_frames` already answer whether a
    render says what the timeline says, and the completion card is where they
    belong rather than a separate command a person has to remember to run.

    `verify` is the audio-side check (its own docstring: "deliberately covers
    only audio") and always applies. The picture-side three are *skipped*
    outright for an audio-only render, not called to report null fields —
    cheaper than a wasted ffprobe/ffmpeg pass, and the payload says why rather
    than silently omitting them.

    Any one check failing to run (no whisper on `PATH`, no video stream to
    probe, a render too odd to scan) is caught and reported `skipped` next to
    its reason, so one check's absence never costs the render its completion
    event or the checks that did run.
    """
    checks: dict[str, Any] = {}
    try:
        checks["verify"] = ops.verify(str(project_root), str(output))
    except EXPECTED as exc:
        checks["verify"] = {"skipped": True, "reason": str(exc)}

    picture_checks: tuple[tuple[str, Callable[[], dict[str, Any]]], ...] = (
        ("check_frames", lambda: ops.check_frames(str(project_root), str(output))),
        ("check_black", lambda: ops.check_black(str(project_root), str(output))),
        ("spot_frames", lambda: ops.spot_frames(str(project_root), str(output))),
    )
    for name, call in picture_checks:
        if not has_video:
            checks[name] = {
                "skipped": True,
                "reason": "this render has no video stream — the picture-side checks do not apply",
            }
            continue
        try:
            checks[name] = call()
        except EXPECTED as exc:
            checks[name] = {"skipped": True, "reason": str(exc)}
    return checks


class RenderJob:
    """One render at a time per server (PLAN.md § Finishing, STUDIO.md § Step 01).

    Runs the finishing pipeline — `export` → optional `burn` (add_captions)
    → `check_frames` → `verify`, the last two derived from `_run_checks`
    rather than called a second time — in a worker thread, publishing a
    `"stage"` event on the same `render` bus topic after each stage attempt,
    and appending the whole run to `renderlog` exactly once, on every exit
    path (success, error, or cancelled).

    `stop()` deletes whatever the partial output currently is rather than
    leaving it, per PLAN.md's explicit "not left" — but honestly: `ops.export`
    and `ops.add_captions` are blocking calls into a subprocess, and nothing
    here holds a handle to kill that subprocess mid-encode. So cancellation
    deletes the *result* on both ends — immediately, on the thread that
    called `stop()`, and again when the background call eventually returns —
    rather than pretending to halt an encode it cannot reach.

    Only `export` and `burn` can fail or be cancelled — `check_frames` and
    `verify` are read off `_run_checks`'s own return value, which already
    turns a per-check `EXPECTED` failure into `{"skipped": True, "reason":
    ...}` rather than raising, so those two stages are always `"done"` or
    `"skipped"`, never `"error"`/`"cancelled"`.

    `_running` is a plain flag guarded by the lock, not `Thread.is_alive()`:
    a `Thread` object is not alive until `.start()` actually runs, so gating
    "busy" on liveness would let a second `/api/render` slip through in the
    window between constructing the thread and starting it.
    """

    def __init__(self, project_root: Path, bus: EventBus) -> None:
        self.project_root = project_root
        self.bus = bus
        self._lock = threading.Lock()
        self._running = False
        self._cancel: threading.Event | None = None
        self._output: Path | None = None

    def _output_path(self, job_id: str) -> Path:
        """`renders/web-<job_id><suffix>`.

        The suffix follows the primary clip's own media — the same clip
        `ops.export` treats as primary (`edit.segments[0]`) — so the
        container this picks matches the one auto-editor is about to write.
        **Except on a layered timeline**, which melt renders as picture over
        the VO: a `.wav` primary would then name a container that cannot hold
        the video the render is for. `layered` is `ops.timeline_view`'s answer,
        not a second reading of the manifest here — the UI never decides
        (CLAUDE.md).

        Everything here can raise before any job state is touched, which is
        what makes an empty timeline a 400 rather than a job that starts only
        to immediately error.
        """
        project = Project.open(self.project_root)
        view = ops.timeline_view(str(self.project_root))
        segments = view.get("segments") or []
        if not segments:
            raise WebUIError("the timeline is empty — nothing to render")
        clip = media.get_clip(project, segments[0]["clip_id"])
        suffix = ".mp4" if view.get("layered") else (media.media_path(project, clip).suffix or ".mp4")
        return project.render_dir / f"web-{job_id}{suffix}"

    def start(
        self,
        preset: str | None,
        resolution: tuple[int, int] | None = None,
        burn: bool | None = None,
    ) -> str:
        job_id = uuid.uuid4().hex
        output = self._output_path(job_id)
        cancel = threading.Event()
        with self._lock:
            if self._running:
                raise RenderBusyError("a render is already running")
            self._running = True
            self._cancel = cancel
            self._output = output
        threading.Thread(
            target=self._run,
            args=(job_id, output, cancel, preset, resolution, burn),
            daemon=True,
        ).start()
        return job_id

    def stop(self) -> None:
        with self._lock:
            if not self._running:
                return
            cancel = self._cancel
            output = self._output
        assert cancel is not None
        cancel.set()
        self._delete(output)

    def _finish(self) -> None:
        with self._lock:
            self._running = False

    @staticmethod
    def _delete(output: Path | None) -> None:
        if output is None:
            return
        try:
            if output.exists():
                output.unlink()
        except OSError:
            pass

    def _report_error(self, exc: Exception, job_id: str) -> None:
        # Reached only for EXPECTED exceptions (CLAUDE.md's family) — anything
        # outside it is a bug and is left to propagate and keep its traceback
        # (the same rule the HTTP handlers follow), rather than being caught
        # here and flattened into a fake completion event.
        self.bus.publish("render", {"job_id": job_id, "status": "error", "error": str(exc)})

    def _run(
        self,
        job_id: str,
        output: Path,
        cancel: threading.Event,
        preset: str | None,
        resolution: tuple[int, int] | None,
        burn: bool | None,
    ) -> None:
        self.bus.publish(
            "render",
            {
                "job_id": job_id,
                "status": "running",
                "preset": preset,
                "resolution": list(resolution) if resolution else None,
            },
        )
        # The finally is a backstop for non-EXPECTED exceptions only: a bug
        # still propagates with its traceback (the HTTP handlers' rule), but
        # it must not leave `_running` latched — that would turn one bug into
        # a permanent 409 for every render until the server restarts.
        try:
            self._run_inner(job_id, output, cancel, preset, resolution, burn)
        finally:
            self._finish()

    def _run_inner(
        self,
        job_id: str,
        output: Path,
        cancel: threading.Event,
        preset: str | None,
        resolution: tuple[int, int] | None,
        burn: bool | None,
    ) -> None:
        project = Project.open(self.project_root)
        # Read once, before `export` runs — this is "what the project claims
        # its own finished length is" at the moment the render was asked for,
        # the same number `check_frames`/`verify` measure a render against.
        expected_duration = ops.status(str(self.project_root))["expected_duration"]
        stages_log: dict[str, dict[str, Any]] = {}

        def publish_stage(stage: str, outcome: str, detail: dict[str, Any] | None = None) -> None:
            stages_log[stage] = {"outcome": outcome, "detail": detail}
            self.bus.publish(
                "render",
                {
                    "job_id": job_id,
                    "status": "stage",
                    "stage": stage,
                    "outcome": outcome,
                    "detail": detail,
                },
            )

        def append_run(final_output: Path) -> None:
            renderlog.append(
                project,
                output=str(final_output),
                preset=preset,
                expected_duration=expected_duration,
                stages=stages_log,
            )

        # -- export ------------------------------------------------------
        # Only passed on when actually set, so a plain `/api/render {}` call
        # still hits `ops.export(path, output, export_format=None)` exactly
        # as it did before preset/resolution existed — the shape a stubbed
        # `ops.export` in the test suite still expects.
        export_kwargs: dict[str, Any] = {}
        if preset is not None:
            export_kwargs["preset"] = preset
        if resolution is not None:
            export_kwargs["resolution"] = resolution
        try:
            ops.export(str(self.project_root), str(output), export_format=None, **export_kwargs)
        except EXPECTED as exc:
            self._finish()
            if cancel.is_set():
                self._delete(output)
                publish_stage("export", "cancelled")
                append_run(output)
                self.bus.publish("render", {"job_id": job_id, "status": "cancelled"})
            else:
                publish_stage("export", "error", {"error": str(exc)})
                append_run(output)
                self._report_error(exc, job_id)
            return

        if cancel.is_set():
            self._finish()
            self._delete(output)
            publish_stage("export", "cancelled")
            append_run(output)
            self.bus.publish("render", {"job_id": job_id, "status": "cancelled"})
            return

        publish_stage("export", "done")

        # -- burn ----------------------------------------------------------
        # `burn is None` means "apply the project's own default": on when a
        # caption style is configured, off otherwise — STUDIO.md's rule.
        # `burn is True`/`burn is False` overrides it explicitly either way.
        should_burn = (
            ops.CAPTION_STYLE_KEY in project.read_manifest() if burn is None else burn
        )
        final_output = output
        if should_burn:
            try:
                # `burn` names the video to burn onto — the file `export` just
                # wrote — never the untrimmed source (CLAUDE.md: burning onto
                # the source lines captions up against audio that has moved).
                result = ops.add_captions(
                    str(self.project_root), str(output.with_suffix(".ass")), burn=str(output)
                )
            except EXPECTED as exc:
                self._finish()
                if cancel.is_set():
                    publish_stage("burn", "cancelled")
                    append_run(output)
                    self.bus.publish("render", {"job_id": job_id, "status": "cancelled"})
                else:
                    publish_stage("burn", "error", {"error": str(exc)})
                    append_run(output)
                    self._report_error(exc, job_id)
                return
            final_output = Path(result["burned"])
            if cancel.is_set():
                self._finish()
                self._delete(final_output)
                publish_stage("burn", "cancelled")
                append_run(final_output)
                self.bus.publish("render", {"job_id": job_id, "status": "cancelled"})
                return
            publish_stage("burn", "done")
        else:
            publish_stage("burn", "skipped", {"reason": "burn not requested"})

        try:
            # (a) auto-editor's/melt's exit code does not mean success — this
            # probes the actual file that landed on disk, the same way every
            # other check here reads a render rather than trusting a
            # subprocess's own report of itself.
            info = media.probe(final_output)
        except EXPECTED as exc:
            self._finish()
            append_run(final_output)
            self._report_error(exc, job_id)
            return

        # -- check_frames / verify, derived from `_run_checks` --------------
        # (b) the existing checks, run here rather than left for a person to
        # remember — see `_run_checks`. Neither can fail this pipeline:
        # `_run_checks` already turns a per-check `EXPECTED` failure into a
        # `skipped` entry rather than raising.
        checks = _run_checks(self.project_root, final_output, info.has_video)

        check_frames_result = checks.get("check_frames", {})
        if check_frames_result.get("skipped"):
            publish_stage(
                "check_frames", "skipped", {"reason": check_frames_result.get("reason")}
            )
        else:
            publish_stage("check_frames", "done", {"agrees": check_frames_result.get("agrees")})

        verify_result = checks.get("verify", {})
        if verify_result.get("skipped"):
            publish_stage("verify", "skipped", {"reason": verify_result.get("reason")})
        else:
            publish_stage("verify", "done", {"similarity": verify_result.get("similarity")})

        self._finish()
        append_run(final_output)
        self.bus.publish(
            "render",
            {
                "job_id": job_id,
                "status": "done",
                "output": str(final_output),
                "width": info.width,
                "height": info.height,
                "duration": info.duration,
                "has_video": info.has_video,
                "has_audio": info.has_audio,
                "checks": checks,
            },
        )


class ProxyJob:
    """One proxy transcode at a time per server (PLAN.md § The preview proxy).

    `RenderJob`'s pattern, deliberately: the lock, the plain `_running` flag
    rather than `Thread.is_alive()`, everything that can raise computed
    *before* any job state is touched so a bad asset is a 400 rather than a
    job that starts only to immediately fail, `_finish()` in a `finally` so a
    bug cannot latch the slot into a permanent 409, and completion published
    on the same bus the SSE handler already serves. There is no GET-by-job-id
    route in this codebase and this adds none.

    **The single slot is a decision the design note left open, taken here and
    worth stating.** A proxy is keyed by *asset*, not by project, so unlike a
    render there is a real case for concurrency: a timeline can show several
    unplayable shots, and one slot means the second one clicked gets a 409
    while the first encodes. It is taken anyway because nothing measures the
    alternative — settling it needs a project carrying more than one
    unplayable asset, which this box does not have — and because a wrong
    single slot costs a retry while a wrong parallel one costs N concurrent
    x264 encodes on a box that is also running melt. Revisit with real
    footage, not with reasoning.

    There is no `/api/proxy/stop`. Cancelling is safe by construction rather
    than by handling: `ops.proxy_transcode` writes the sidecar key only after
    ffmpeg returns, so an interrupted job leaves an unkeyed file that
    `proxy_is_current` reads as no proxy at all.
    """

    def __init__(self, project_root: Path, bus: EventBus) -> None:
        self.project_root = project_root
        self.bus = bus
        self._lock = threading.Lock()
        self._running = False

    def start(self, clip_id: str, *, force: bool = False) -> str:
        job_id = uuid.uuid4().hex
        # Resolve before claiming the slot: an unknown clip_id, missing media,
        # an already-playable file and a streamless one all raise here, on the
        # request thread, where they become a 400.
        project = Project.open(self.project_root)
        media.get_clip(project, clip_id)
        with self._lock:
            if self._running:
                raise ProxyBusyError("a proxy transcode is already running")
            self._running = True
        threading.Thread(target=self._run, args=(job_id, clip_id, force), daemon=True).start()
        return job_id

    def _finish(self) -> None:
        with self._lock:
            self._running = False

    def _run(self, job_id: str, clip_id: str, force: bool) -> None:
        self.bus.publish("proxy", {"job_id": job_id, "status": "running", "clip_id": clip_id})
        try:
            try:
                result = ops.proxy_transcode(str(self.project_root), clip_id, force=force)
            except EXPECTED as exc:
                # Same rule as `RenderJob._report_error`: only lucid's own
                # refusals are flattened into an event. Anything else is a bug
                # and keeps its traceback.
                self.bus.publish(
                    "proxy",
                    {"job_id": job_id, "status": "error", "clip_id": clip_id, "error": str(exc)},
                )
                return
            self.bus.publish("proxy", {"job_id": job_id, "status": "done", **result})
        finally:
            self._finish()


class ReframeSheetJob:
    """One sheet generation at a time per server (STUDIO.md § Step 03, Frame mode).

    `ProxyJob`'s exact shape: the lock, the plain `_running` flag, everything
    that can raise (`Project.open`) resolved on the request thread before the
    slot is claimed, a dedicated `*BusyError` for a distinct 409, `_finish()`
    in a `finally`, and completion published on the same bus the SSE handler
    already serves.

    `extremes` is accepted for parity with `ops.reframe_sheet`'s own
    signature, but `frame.js` never sends `extremes: true` in this step — a
    later step's draggable/extreme-probe review can turn it on without this
    job changing shape.
    """

    def __init__(self, project_root: Path, bus: EventBus) -> None:
        self.project_root = project_root
        self.bus = bus
        self._lock = threading.Lock()
        self._running = False

    def start(
        self,
        *,
        moments: list[float] | None = None,
        extremes: bool = False,
        out: str | None = None,
    ) -> str:
        job_id = uuid.uuid4().hex
        # A bad/unopenable project is caught here, on the request thread,
        # before the slot is touched — the `ProxyJob` precedent.
        Project.open(self.project_root)
        with self._lock:
            if self._running:
                raise ReframeSheetBusyError("a reframe sheet is already generating")
            self._running = True
        threading.Thread(
            target=self._run, args=(job_id, moments, extremes, out), daemon=True
        ).start()
        return job_id

    def _finish(self) -> None:
        with self._lock:
            self._running = False

    def _run(
        self, job_id: str, moments: list[float] | None, extremes: bool, out: str | None
    ) -> None:
        self.bus.publish("reframe-sheet", {"job_id": job_id, "status": "running"})
        try:
            try:
                result = ops.reframe_sheet(
                    str(self.project_root), out=out, moments=moments, extremes=extremes
                )
            except EXPECTED as exc:
                self.bus.publish(
                    "reframe-sheet", {"job_id": job_id, "status": "error", "error": str(exc)}
                )
                return
            self.bus.publish("reframe-sheet", {"job_id": job_id, "status": "done", **result})
        finally:
            self._finish()


class ReframeDetectJob:
    """One detect pass at a time per server (STUDIO.md § Step 03, Frame mode).

    `ProxyJob`'s exact shape. **`apply` is not a parameter of `.start()` at
    all** — it is hard-coded `False` in the call to `ops.reframe_detect`,
    enforced here at the job layer (and again at the HTTP layer, in
    `_handle_reframe_detect_start`, which refuses even a hand-crafted
    request naming the key) — the one flag STUDIO.md is explicit about:
    "`apply` stays off — it proposes, the sheet judges."

    This job always needs `LUCID_FACE` — `ops.reframe_detect` raises
    `FaceError` unconditionally, before the scene scan, when no interpreter
    is available — which is why `FaceError` is in `EXPECTED` above: without
    it, a missing detector would propagate out of `_run`'s worker thread
    with no handler, `_finish()` would never run, and the slot would latch
    busy forever while the view spins on an SSE event that never arrives.
    """

    def __init__(self, project_root: Path, bus: EventBus) -> None:
        self.project_root = project_root
        self.bus = bus
        self._lock = threading.Lock()
        self._running = False

    def start(
        self,
        *,
        clip_id: str | None = None,
        threshold: float | None = None,
        frames: int | None = None,
        split: bool = True,
    ) -> str:
        job_id = uuid.uuid4().hex
        Project.open(self.project_root)
        with self._lock:
            if self._running:
                raise ReframeDetectBusyError("a reframe detect pass is already running")
            self._running = True
        threading.Thread(
            target=self._run,
            args=(job_id, clip_id, threshold, frames, split),
            daemon=True,
        ).start()
        return job_id

    def _finish(self) -> None:
        with self._lock:
            self._running = False

    def _run(
        self,
        job_id: str,
        clip_id: str | None,
        threshold: float | None,
        frames: int | None,
        split: bool,
    ) -> None:
        self.bus.publish("reframe-detect", {"job_id": job_id, "status": "running"})
        try:
            try:
                result = ops.reframe_detect(
                    str(self.project_root),
                    clip_id=clip_id,
                    threshold=ops.SCENE_THRESHOLD if threshold is None else threshold,
                    frames=ops.DETECT_FRAMES if frames is None else frames,
                    apply=False,
                    split=split,
                )
            except EXPECTED as exc:
                self.bus.publish(
                    "reframe-detect", {"job_id": job_id, "status": "error", "error": str(exc)}
                )
                return
            self.bus.publish("reframe-detect", {"job_id": job_id, "status": "done", **result})
        finally:
            self._finish()


class Handler(BaseHTTPRequestHandler):
    """One request. `project_root` and `verbose` are set by `make_server`.

    `root_dir` is the picker's own flag: `None` (its default, unchanged for
    every `-C` server `make_server` builds) means this class has a fixed
    `project_root` and behaves exactly as it always has. Set (by
    `make_picker_server`) it means `project_root` does not exist *yet* —
    `self.server.bound_root` is `None` until `POST /api/open` picks one, and
    every route below is reachable only after that (`_route_picker`,
    `_handle_open`). Once open, `project_root` is set the same way `-C`
    always set it and this instance is, for the rest of the process, an
    ordinary single-project handler."""

    project_root: Path
    root_dir: Path | None = None
    verbose: bool = False
    server_version = "lucid"
    sys_version = ""
    #: Keep-alive, so seeking a video does not reopen a connection per range.
    protocol_version = "HTTP/1.1"

    # -- plumbing --------------------------------------------------------

    def log_message(self, fmt: str, *args: Any) -> None:
        # Media playback issues a request per range; logging every one buries
        # the startup line the user actually needs. Off unless asked for.
        if self.verbose:
            super().log_message(fmt, *args)

    def _host_is_loopback(self) -> bool:
        host = (self.headers.get("Host") or "").strip()
        name = host.rsplit(":", 1)[0] if host.count(":") == 1 else host
        if name.startswith("[") and "]" in name:
            name = name[: name.index("]") + 1]
        return name.lower() in _LOOPBACK_NAMES

    def _send(
        self,
        status: HTTPStatus,
        body: bytes,
        content_type: str,
        *,
        extra: dict[str, str] | None = None,
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        # This page is only ever served to a person sitting at this machine,
        # and it embeds no third-party anything. Say so, so a stray injection
        # has nowhere to phone home to.
        self.send_header("Content-Security-Policy", "default-src 'self'; media-src 'self'")
        self.send_header("X-Content-Type-Options", "nosniff")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _send_json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")
        self._send(status, body, "application/json; charset=utf-8")

    def _fail(self, status: HTTPStatus, message: str) -> None:
        self._send_json({"error": message}, status)

    # -- routing ---------------------------------------------------------

    def do_GET(self) -> None:
        self._route(head_only=False)

    def do_HEAD(self) -> None:
        # Browsers probe media with HEAD before ranging into it.
        self._route(head_only=True)

    def do_POST(self) -> None:
        if not self._host_is_loopback():
            self._fail(HTTPStatus.FORBIDDEN, "this server answers loopback requests only")
            return
        url = urlparse(self.path)
        if self.root_dir is not None:
            # Picker mode. `/api/open` is reachable whether or not a project
            # is bound yet — `_handle_open` is what makes a second call on
            # the same project a no-op and a call naming a *different* one a
            # 409, rather than either being "no such endpoint". Every other
            # route below needs `self.server.agent`/`render_job`/`proxy_job`
            # or a fixed `project_root`, none of which exist before the
            # first successful open.
            if url.path == "/api/open":
                self._handle_open()
                return
            if not self._project_bound():
                self._fail(HTTPStatus.NOT_FOUND, "no project open yet — pick one at /")
                return
        if url.path == "/api/agent":
            self._handle_agent_prompt()
            return
        if url.path == "/api/agent/stop":
            self._handle_agent_stop()
            return
        if url.path == "/api/agent/new-task":
            self._handle_agent_new_task()
            return
        if url.path == "/api/render":
            self._handle_render_start()
            return
        if url.path == "/api/render/stop":
            self._handle_render_stop()
            return
        if url.path == "/api/proxy":
            self._handle_proxy_start()
            return
        if url.path == "/api/reframe/sheet":
            self._handle_reframe_sheet_start()
            return
        if url.path == "/api/reframe/detect":
            self._handle_reframe_detect_start()
            return
        route = _POST_ROUTES.get(url.path)
        if route is None:
            self._fail(HTTPStatus.NOT_FOUND, f"no such endpoint: {url.path}")
            return
        try:
            payload = _json_body(self)
            self._send_json(route(str(self.project_root), payload))
        except WebUIError as exc:
            self._fail(HTTPStatus.BAD_REQUEST, str(exc))
        except EXPECTED as exc:
            # A refused cut is the normal case here, not a server fault: the
            # suspect-duration guard rejects a boundary precisely so a person
            # reads the message and picks a different word.
            self._fail(HTTPStatus.BAD_REQUEST, str(exc))

    def _project_bound(self) -> bool:
        """Picker mode only: has `POST /api/open` picked a project yet?

        Always `False` on a plain `-C` server, but never checked there —
        `root_dir is None` short-circuits every caller before this runs, so
        a single-project server never even looks at `self.server.bound_root`
        (which does not exist on it).
        """
        return getattr(self.server, "bound_root", None) is not None

    def _route(self, *, head_only: bool) -> None:
        if not self._host_is_loopback():
            self._fail(HTTPStatus.FORBIDDEN, "this server answers loopback requests only")
            return
        url = urlparse(self.path)
        path = url.path
        if self.root_dir is not None and not self._project_bound():
            self._route_picker(path, url.query, head_only=head_only)
            return
        try:
            if path in ("/", "/index.html"):
                self._send_static("index.html")
            elif path.startswith("/static/"):
                self._send_static(path[len("/static/") :])
            elif path == "/api/view":
                query = parse_qs(url.query)
                clip_id = (query.get("clip_id") or [None])[0]
                view = ops.timeline_view(str(self.project_root), clip_id=clip_id)
                # Best-effort, on the workspace's first real data fetch —
                # never lets a poster failure turn a page load into a 400
                # (Studio Step 04 contract § C).
                try:
                    _ensure_poster(Project.open(self.project_root), view)
                except Exception:  # noqa: BLE001, S110 — a poster is best-effort, never fatal
                    pass
                self._send_json(view)
            elif path == "/api/session":
                self._send_json(_session_get(str(self.project_root)))
            elif path == "/api/captions":
                query = parse_qs(url.query)
                clip_id = (query.get("clip_id") or [None])[0]
                self._send_json(ops.caption_view(str(self.project_root), clip_id=clip_id))
            elif path == "/api/assets":
                self._send_json(ops.assets(str(self.project_root)))
            elif path == "/api/properties":
                query = parse_qs(url.query)
                clip_id = (query.get("clip_id") or [None])[0]
                raw_word = (query.get("word_index") or [None])[0]
                word_index = self._int_query(raw_word, "word_index")
                self._send_json(
                    ops.properties(str(self.project_root), clip_id=clip_id, word_index=word_index)
                )
            elif path == "/api/finish":
                # `?framing=1` opts into the scene-cut scan. Off by default
                # and deliberately so: the truth strip re-reads this route on
                # every `project-changed` event, and the framing section
                # costs 5.7s wall / 46s CPU on the film, uncached — every cut
                # would have paid it for a number nothing on screen asked to
                # change. Frame mode asks for it when it opens.
                query = parse_qs(url.query)
                want_framing = (query.get("framing") or ["0"])[0] not in ("", "0", "false")
                self._send_json(
                    ops.finish_report(str(self.project_root), framing=want_framing)
                )
            elif path == "/api/reframe/coverage":
                query = parse_qs(url.query)
                clip_id = (query.get("clip_id") or [None])[0]
                raw_threshold = (query.get("threshold") or [None])[0]
                threshold = self._float_query(raw_threshold, "threshold")
                self._send_json(
                    ops.reframe_coverage(
                        str(self.project_root),
                        clip_id=clip_id,
                        threshold=ops.SCENE_THRESHOLD if threshold is None else threshold,
                    )
                )
            elif path.startswith("/api/reframe/tile/"):
                name = unquote(path[len("/api/reframe/tile/") :])
                self._send_reframe_tile(name, head_only=head_only)
            elif path == "/api/events":
                self._send_events()
            elif path.startswith("/api/waveform/"):
                clip_id = unquote(path[len("/api/waveform/") :])
                if not clip_id:
                    raise WebUIError("clip id is required")
                self._send_json(ops.waveform(str(self.project_root), clip_id))
            elif path.startswith("/api/thumb/"):
                clip_id = unquote(path[len("/api/thumb/") :])
                if not clip_id:
                    raise WebUIError("clip id is required")
                self._send_thumb(clip_id, url.query, head_only=head_only)
            elif path.startswith("/api/media/"):
                self._send_media(unquote(path[len("/api/media/") :]), head_only=head_only)
            elif path.startswith("/api/asset/"):
                self._send_asset(unquote(path[len("/api/asset/") :]), head_only=head_only)
            elif path.startswith("/api/preview/"):
                asset = unquote(path[len("/api/preview/") :])
                if not asset:
                    raise WebUIError("asset key is required")
                self._send_json(ops.preview_source(str(self.project_root), asset))
            else:
                self._fail(HTTPStatus.NOT_FOUND, f"no such endpoint: {path}")
        except WebUIError as exc:
            self._fail(HTTPStatus.BAD_REQUEST, str(exc))
        except EXPECTED as exc:
            self._fail(HTTPStatus.BAD_REQUEST, str(exc))

    # -- handlers --------------------------------------------------------

    def _send_static(self, name: str) -> None:
        # No traversal: a static name is one flat filename out of a directory
        # shipped inside the package, never a path.
        if "/" in name or "\\" in name or name.startswith("."):
            self._fail(HTTPStatus.NOT_FOUND, f"no such asset: {name}")
            return
        target = STATIC_DIR / name
        if not target.is_file() or target.suffix not in _STATIC_TYPES:
            self._fail(HTTPStatus.NOT_FOUND, f"no such asset: {name}")
            return
        self._send(HTTPStatus.OK, target.read_bytes(), _STATIC_TYPES[target.suffix])

    def _route_picker(self, path: str, query: str, *, head_only: bool) -> None:
        """GET routing while `root_dir` is set and no project is open yet.

        Four routes — the picker page, its own static assets, the scan
        itself, and a project's poster image — because everything else on a
        normal server needs a bound `project_root` or the singletons
        `/api/open` has not built yet. `POST /api/open` is handled in
        `do_POST`, not here; this method only ever answers GET/HEAD.
        """
        try:
            if path in ("/", "/index.html"):
                self._send_static("picker.html")
            elif path.startswith("/static/"):
                self._send_static(path[len("/static/") :])
            elif path == "/api/projects":
                assert self.root_dir is not None
                self._send_json({"root": str(self.root_dir), "projects": scan_projects(self.root_dir)})
            elif path == "/api/poster":
                params = parse_qs(query)
                raw_path = (params.get("path") or [None])[0]
                if not raw_path:
                    raise WebUIError("'path' is required")
                self._send_poster(raw_path, head_only=head_only)
            else:
                self._fail(HTTPStatus.NOT_FOUND, "no project open yet — pick one at /")
        except WebUIError as exc:
            self._fail(HTTPStatus.BAD_REQUEST, str(exc))
        except EXPECTED as exc:
            self._fail(HTTPStatus.BAD_REQUEST, str(exc))

    def _send_poster(self, raw_path: str, *, head_only: bool) -> None:
        """`GET /api/poster?path=<project>` — the Home gallery's still image.

        Picker-only, modeled directly on `_send_reframe_tile` (Studio Step
        03's own confinement precedent — CLAUDE.md names it as the model to
        copy). The picker never binds and never thumbnails: this only ever
        reads a file a *bound* session already wrote via `_ensure_poster`.

        The symlink refusal is inherited, not re-implemented: `raw_path` is
        matched against `scan_projects`'s own output, and `scan_projects`'s
        `is_symlink()` filter (webui.py, `walk()`) already excludes a
        symlinked directory from that list — a poster request naming a path
        outside the scan, symlinked or not, simply has no matching entry and
        404s here rather than needing a second symlink check. The
        resolved-parent check below is belt-and-suspenders on top of that,
        catching a symlink placed *inside* a scanned project's own `cache/`
        pointing elsewhere on disk — the one thing matching against the scan
        alone would not catch, same reasoning as `_send_reframe_tile`'s own
        third layer.
        """
        assert self.root_dir is not None
        entries = scan_projects(self.root_dir)
        match = next((e for e in entries if e["path"] == raw_path), None)
        if match is None:
            raise WebUIError(f"{raw_path!r} is not a project under {self.root_dir}")
        project = Project(Path(match["path"]))
        poster = project.poster_path
        if poster.resolve().parent != (project.root / CACHE_DIR).resolve():
            raise WebUIError(f"{raw_path!r} has no poster")
        if not poster.is_file():
            raise WebUIError(f"no poster for {raw_path!r} yet")
        self._stream_file(poster, head_only=head_only)

    def _send_media(self, clip_id: str, *, head_only: bool) -> None:
        """Stream a clip's media, honouring Range so the browser can seek.

        Resolution goes through `media.preview_path`, which is `media_path`
        — the attenuated copy when one exists, so the preview is of the audio
        that will actually be exported (CLAUDE.md) — *unless* a current proxy
        exists, in which case it is that. This is one of the two preview-side
        callers allowed to resolve that way; nothing that renders is among
        them (PLAN.md § The preview proxy transcode).
        """
        project = Project.open(self.project_root)
        clip = media.get_clip(project, clip_id)
        source = media.preview_path(project, clip)
        if not source.is_file():
            raise WebUIError(f"{clip_id}'s media is missing from disk: {source}")
        self._stream_file(source, head_only=head_only)

    def _send_asset(self, asset: str, *, head_only: bool) -> None:
        """Stream one picture asset — a cue's `card:name` or clip_id — to the viewer.

        Separate from `_send_media` because the two resolve differently and only
        one of them is addressed by clip_id: a card is not a clip and never will
        be. Both end in the same `_stream_file`, so Range behaves identically —
        which matters more here than for the transport, since the picture layer
        seeks constantly and every seek aborts an in-flight range.

        Resolution and the traversal check are `ops.preview_source`'s, not a
        second copy: the untrusted-string case is exactly the one that must have
        one implementation.
        """
        if not asset:
            raise WebUIError("asset key is required")
        resolved = ops.preview_source(str(self.project_root), asset)
        self._stream_file(Path(resolved["path"]), head_only=head_only)

    def _send_thumb(self, clip_id: str, query: str, *, head_only: bool) -> None:
        """`GET /api/thumb/<clip_id>?at=<seconds>` — one filmstrip frame.

        `ops.thumbnail` does the caching and the containment (it writes
        under `cache/thumbs/`, never the manifest, and is never resolved by
        `media.media_path`/`preview_path` — CLAUDE.md's split); this is only
        the fourth caller into `_stream_file`, so a thumbnail seeks and
        Ranges exactly like every other picture asset the viewer draws.
        """
        params = parse_qs(query)
        at = self._float_query((params.get("at") or [None])[0], "at", required=True)
        interval_raw = (params.get("interval") or [None])[0]
        parsed_interval = self._float_query(interval_raw, "interval")
        interval = ops.THUMB_INTERVAL if parsed_interval is None else parsed_interval
        resolved = ops.thumbnail(str(self.project_root), clip_id, at, interval=interval)
        self._stream_file(Path(resolved["path"]), head_only=head_only)

    def _send_reframe_tile(self, name: str, *, head_only: bool) -> None:
        """`GET /api/reframe/tile/<name>` — one PNG frame out of `cache/sheets`.

        The security-relevant route in Studio Step 03 (contract § B). `name`
        is confined to `project.sheet_dir` exactly the way `ops.thumbnail`'s
        cache convention is confined (CLAUDE.md's named precedent) — never
        through `media.preview_path()`, which gains no new caller here.

        Three layers, each catching something the others do not:

        1. `Path(name).name` strips any directory component — this alone
           refuses `../../etc/passwd` (becomes `passwd`, which then simply
           fails the `is_file()` check below) and an absolute path
           (`Path("/etc/passwd").name == "passwd"`, same outcome).
        2. A belt-and-suspenders character blacklist, `_send_asset`'s
           `card:` style, catching anything step 1's silent stripping might
           otherwise let through unnoticed.
        3. A resolved-parent check — the symlink defence: a symlink *placed
           inside* `cache/sheets` pointing outside it has a bare name with
           no `/` or `..` in it at all, so steps 1-2 alone would pass it.
        """
        if not name:
            raise WebUIError("tile name is required")
        if ".." in name or "\\" in name:
            raise WebUIError(f"{name!r} does not name a sheet tile")
        if name != Path(name).name:
            raise WebUIError(f"{name!r} does not name a sheet tile")
        project = Project.open(self.project_root)
        target = project.sheet_dir / name
        if target.resolve().parent != project.sheet_dir.resolve():
            raise WebUIError(f"{name!r} does not name a sheet tile")
        if not target.is_file():
            raise WebUIError(f"no such tile: {name}")
        self._stream_file(target, head_only=head_only)

    @staticmethod
    def _int_query(raw: str | None, name: str) -> int | None:
        if raw is None:
            return None
        try:
            return int(raw)
        except ValueError:
            raise WebUIError(f"{name!r} must be an integer, not {raw!r}") from None

    @staticmethod
    def _float_query(raw: str | None, name: str, *, required: bool = False) -> float | None:
        if raw is None:
            if required:
                raise WebUIError(f"{name!r} is required")
            return None
        try:
            return float(raw)
        except ValueError:
            raise WebUIError(f"{name!r} must be a number, not {raw!r}") from None

    def _stream_file(self, source: Path, *, head_only: bool) -> None:
        """Byte-range streaming, shared by every route that hands over a file."""
        _stream_file(self, source, head_only=head_only)

    def _send_events(self) -> None:
        """`GET /api/events` — a long-lived `text/event-stream`.

        One event type is polled (`project-changed`, off `_revision`); two
        are pushed (`agent`, `render`) through `self.server.bus`, which other
        server code publishes onto — the agent's stdout reader and the render
        job. No `Content-Length`: the response ends only when the client
        disconnects, which is also the only way this method returns.
        """
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True

        bus: EventBus = self.server.bus  # type: ignore[attr-defined]
        subscription = bus.subscribe()
        try:
            last = _revision(self.project_root)
            self._write_sse("project-changed", {"revision": last})
            while True:
                try:
                    event, data = subscription.get(timeout=_REVISION_POLL_SECONDS)
                    self._write_sse(event, data)
                except queue.Empty:
                    pass
                current = _revision(self.project_root)
                if current != last:
                    last = current
                    self._write_sse("project-changed", {"revision": last})
        except (BrokenPipeError, ConnectionResetError, OSError):
            # The browser navigated away or closed the tab. Routine, not an
            # error — the same treatment `_send_media` gives an aborted seek.
            return
        finally:
            bus.unsubscribe(subscription)

    def _write_sse(self, event: str, data: dict[str, Any]) -> None:
        chunk = f"event: {event}\ndata: {json.dumps(data)}\n\n"
        self.wfile.write(chunk.encode("utf-8"))
        self.wfile.flush()

    def _handle_agent_prompt(self) -> None:
        """`POST /api/agent {"prompt": ...}` — 202, the work happens on the stream.

        The reply is an acknowledgement, not a result: what the agent does
        arrives as `agent` events on `/api/events`, the same feed a person's
        own cut lands in (PLAN.md § Where the cut controls go).
        """
        try:
            payload = _json_body(self)
            prompt = payload.get("prompt")
            if not isinstance(prompt, str) or not prompt.strip():
                raise WebUIError("'prompt' is required")
        except WebUIError as exc:
            self._fail(HTTPStatus.BAD_REQUEST, str(exc))
            return
        agent: AgentSession = self.server.agent  # type: ignore[attr-defined]
        try:
            agent.send(prompt)
        except OSError as exc:
            # A spawn that never happened (`claude` not on PATH, a dead
            # LUCID_AGENT_BIN) puts nothing on `/api/events` to clear the
            # composer — so the failure has to come back on this request,
            # as JSON, not as a connection reset with a server-side traceback.
            self._fail(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                f"could not start the agent process: {exc}",
            )
            return
        self._send_json({"accepted": True}, HTTPStatus.ACCEPTED)

    def _handle_agent_stop(self) -> None:
        try:
            _json_body(self)
        except WebUIError as exc:
            self._fail(HTTPStatus.BAD_REQUEST, str(exc))
            return
        agent: AgentSession = self.server.agent  # type: ignore[attr-defined]
        agent.stop()
        self._send_json({"stopped": True})

    def _handle_agent_new_task(self) -> None:
        """`POST /api/agent/new-task {}` — kill the live subprocess so the
        next prompt starts a fresh conversation (DAYDREAM.md § Agent panel,
        item 4: "needs only the affordance" — `AgentSession.reset()` and
        `send()`'s existing lazy respawn already do the rest).

        Same shape as `_handle_agent_stop`: a plain 200 acknowledgement, no
        `self.server`-free `_POST_ROUTES` entry because this needs the live
        `AgentSession` off `self.server`.
        """
        try:
            _json_body(self)
        except WebUIError as exc:
            self._fail(HTTPStatus.BAD_REQUEST, str(exc))
            return
        agent: AgentSession = self.server.agent  # type: ignore[attr-defined]
        agent.reset()
        self._send_json({"reset": True})

    def _handle_render_start(self) -> None:
        """`POST /api/render {"preset": optional, "resolution": optional,
        "burn": optional}` — 202, work happens on the stream.

        Like `/api/agent`, the reply only acknowledges; progress arrives as
        `render` events on `/api/events` — `"running"`, one `"stage"` event
        per pipeline stage attempted (`export`/`burn`/`check_frames`/
        `verify`), then `"done"`/`"error"`/`"cancelled"`. All three fields
        are threaded straight through to the render pipeline — this handler
        only checks their *shape* (a string; a 2-element list of ints; a
        bool or null), never whether the combination is valid. An invalid
        combination (an unknown preset name, `resolution` on a layered
        project, `preset`/`resolution` with an NLE `export_format` — this
        endpoint never asks for one, so that specific combination cannot
        happen here) still raises inside the pipeline, on the render worker
        thread, and surfaces as the existing `error` render event — the
        window draws and plays, it does not decide.

        `burn`: `null` applies the project's own default (on when a caption
        style is configured, off otherwise); `true`/`false` overrides it.
        """
        try:
            payload = _json_body(self)
            preset = payload.get("preset")
            if preset is not None and not isinstance(preset, str):
                raise WebUIError("'preset' must be a string")
            resolution = payload.get("resolution")
            if resolution is not None:
                if (
                    not isinstance(resolution, list)
                    or len(resolution) != 2
                    or not all(isinstance(n, int) and not isinstance(n, bool) for n in resolution)
                ):
                    raise WebUIError("'resolution' must be a two-element list of integers")
                resolution = (resolution[0], resolution[1])
            burn = payload.get("burn")
            if burn is not None and not isinstance(burn, bool):
                raise WebUIError("'burn' must be true, false, or null")
        except WebUIError as exc:
            self._fail(HTTPStatus.BAD_REQUEST, str(exc))
            return
        job: RenderJob = self.server.render_job  # type: ignore[attr-defined]
        try:
            job_id = job.start(preset, resolution, burn)
        except RenderBusyError as exc:
            self._fail(HTTPStatus.CONFLICT, str(exc))
            return
        except WebUIError as exc:
            self._fail(HTTPStatus.BAD_REQUEST, str(exc))
            return
        except EXPECTED as exc:
            self._fail(HTTPStatus.BAD_REQUEST, str(exc))
            return
        self._send_json({"job_id": job_id}, HTTPStatus.ACCEPTED)

    def _handle_render_stop(self) -> None:
        """`POST /api/render/stop {}` — cancel; the partial output is deleted.

        A no-op 200 when nothing is running, the same shape `/api/agent/stop`
        already answers with — the client does not have to know whether a
        render was in flight to ask it to stop.
        """
        try:
            _json_body(self)
        except WebUIError as exc:
            self._fail(HTTPStatus.BAD_REQUEST, str(exc))
            return
        job: RenderJob = self.server.render_job  # type: ignore[attr-defined]
        job.stop()
        self._send_json({"stopped": True})

    def _handle_proxy_start(self) -> None:
        """`POST /api/proxy {"clip_id": ..., "force": optional}` — 202.

        Like `/api/render`, the reply only acknowledges; `running` → `done`/
        `error` arrive as `proxy` events on `/api/events`. The transcode is a
        job rather than a request because it is minutes of ffmpeg on a long
        clip, and a request that long is a dead window.

        This handler checks shape only. Whether the clip is *worth* proxying —
        already playable, or streamless and so unfixable — is
        `ops.proxy_transcode`'s judgement, reached through `ProxyJob.start`
        before the slot is claimed, so it still surfaces as a 400 here rather
        than as an event nobody asked for. The window draws and plays, it does
        not decide (CLAUDE.md).
        """
        try:
            payload = _json_body(self)
            clip_id = payload.get("clip_id")
            if not isinstance(clip_id, str) or not clip_id:
                raise WebUIError("'clip_id' is required")
            force = payload.get("force", False)
            if not isinstance(force, bool):
                raise WebUIError("'force' must be a boolean")
        except WebUIError as exc:
            self._fail(HTTPStatus.BAD_REQUEST, str(exc))
            return
        job: ProxyJob = self.server.proxy_job  # type: ignore[attr-defined]
        try:
            job_id = job.start(clip_id, force=force)
        except ProxyBusyError as exc:
            self._fail(HTTPStatus.CONFLICT, str(exc))
            return
        except WebUIError as exc:
            self._fail(HTTPStatus.BAD_REQUEST, str(exc))
            return
        except EXPECTED as exc:
            self._fail(HTTPStatus.BAD_REQUEST, str(exc))
            return
        self._send_json({"job_id": job_id}, HTTPStatus.ACCEPTED)

    def _handle_reframe_sheet_start(self) -> None:
        """`POST /api/reframe/sheet {"moments": [...] | null, "extremes": bool
        | null, "out": str | null}` — 202, work happens on the stream.

        Shape check only, `_handle_proxy_start`'s pattern. `frame.js` never
        sends `extremes: true` in this step, but the endpoint honours it if
        a body ever does — `extremes` is only cost/availability-gated, not
        the "never write" rail `apply` is on the detect endpoint.
        """
        try:
            payload = _json_body(self)
            moments = payload.get("moments")
            if moments is not None:
                if not isinstance(moments, list) or not all(
                    isinstance(n, int | float) and not isinstance(n, bool) for n in moments
                ):
                    raise WebUIError("'moments' must be a list of numbers")
                moments = [float(n) for n in moments]
            extremes = payload.get("extremes", False)
            if not isinstance(extremes, bool):
                raise WebUIError("'extremes' must be a boolean")
            out = payload.get("out")
            if out is not None and not isinstance(out, str):
                raise WebUIError("'out' must be a string")
        except WebUIError as exc:
            self._fail(HTTPStatus.BAD_REQUEST, str(exc))
            return
        job: ReframeSheetJob = self.server.reframe_sheet_job  # type: ignore[attr-defined]
        try:
            job_id = job.start(moments=moments, extremes=extremes, out=out)
        except ReframeSheetBusyError as exc:
            self._fail(HTTPStatus.CONFLICT, str(exc))
            return
        except WebUIError as exc:
            self._fail(HTTPStatus.BAD_REQUEST, str(exc))
            return
        except EXPECTED as exc:
            self._fail(HTTPStatus.BAD_REQUEST, str(exc))
            return
        self._send_json({"job_id": job_id}, HTTPStatus.ACCEPTED)

    def _handle_reframe_detect_start(self) -> None:
        """`POST /api/reframe/detect {"clip_id": str | null, "threshold":
        number | null, "frames": int | null, "split": bool | null}` — 202.

        **`apply` is not read from the body at all.** If the body includes
        `"apply": true` this refuses with a 400 before the job even starts —
        the frontend has no control that could set it, and this refuses even
        a hand-crafted request that tries, the second of the two independent
        places (`ReframeDetectJob.start` hard-codes `apply=False`) enforcing
        "reframe-detect never writes; approve a proposal through
        /api/reframe instead."
        """
        try:
            payload = _json_body(self)
            if "apply" in payload:
                raise WebUIError(
                    "'apply' is not accepted here — reframe-detect never writes; "
                    "approve a proposal through /api/reframe instead"
                )
            clip_id = payload.get("clip_id")
            if clip_id is not None and not isinstance(clip_id, str):
                raise WebUIError("'clip_id' must be a string")
            threshold = payload.get("threshold")
            if threshold is not None and not isinstance(threshold, int | float):
                raise WebUIError("'threshold' must be a number")
            frames = payload.get("frames")
            if frames is not None and (
                not isinstance(frames, int) or isinstance(frames, bool)
            ):
                raise WebUIError("'frames' must be an integer")
            split = payload.get("split", True)
            if not isinstance(split, bool):
                raise WebUIError("'split' must be a boolean")
        except WebUIError as exc:
            self._fail(HTTPStatus.BAD_REQUEST, str(exc))
            return
        job: ReframeDetectJob = self.server.reframe_detect_job  # type: ignore[attr-defined]
        try:
            job_id = job.start(
                clip_id=clip_id,
                threshold=None if threshold is None else float(threshold),
                frames=frames,
                split=split,
            )
        except ReframeDetectBusyError as exc:
            self._fail(HTTPStatus.CONFLICT, str(exc))
            return
        except WebUIError as exc:
            self._fail(HTTPStatus.BAD_REQUEST, str(exc))
            return
        except EXPECTED as exc:
            self._fail(HTTPStatus.BAD_REQUEST, str(exc))
            return
        self._send_json({"job_id": job_id}, HTTPStatus.ACCEPTED)

    def _handle_open(self) -> None:
        """`POST /api/open {"path": "..."}` — the picker's one mutation.

        Binds this process to one project, permanently: the same work
        `make_server` already does for `-C` at process start
        (`_bind_singletons`), just deferred to the moment a person picks one
        instead of decided in advance. There is no unbind and no switch —
        once this returns 200, `project_root` is set on the handler class
        and `self.server.bus`/`agent`/`render_job`/`proxy_job` exist, and
        every request after this one (from any tab, any connection) is an
        ordinary single-project request against that project for the rest
        of the process's life. Wanting a second project open at the same
        time still means a second process, exactly as `-C` always required
        — that is what keeps two projects from ever sharing one
        `AgentSession` or `RenderJob` (CLAUDE.md: cross-wiring those is a
        data-corruption bug, not a UI bug).

        The path is confined to `root_dir` the same way `server.py`'s
        `_confine` confines an MCP tool's project selector — resolved, and
        refused if it lands outside the scanned root rather than followed —
        because a `--root` a user passed must not become a way to open a
        directory it never scanned. And it goes through `Project.open`
        itself, so an old-schema or unreadable project (already visible to
        `/api/projects` as `needs_migration`/`unreadable`) is refused here
        exactly as it always refuses `-C`, not skipped and not migrated.
        """
        try:
            payload = _json_body(self)
            raw = payload.get("path")
            if not isinstance(raw, str) or not raw:
                raise WebUIError("'path' is required")
        except WebUIError as exc:
            self._fail(HTTPStatus.BAD_REQUEST, str(exc))
            return

        assert self.root_dir is not None  # only reachable in picker mode
        root_dir = self.root_dir
        candidate = Path(raw).expanduser()
        if not candidate.is_absolute():
            candidate = root_dir / candidate
        resolved = candidate.resolve()
        if resolved != root_dir and root_dir not in resolved.parents:
            self._fail(
                HTTPStatus.FORBIDDEN,
                f"this server was started with --root {root_dir} and {raw!r} resolves "
                f"outside it ({resolved}); pass a path at or under the scanned root",
            )
            return

        try:
            project = Project.open(resolved)
        except ProjectError as exc:
            self._fail(HTTPStatus.BAD_REQUEST, str(exc))
            return

        lock: threading.Lock = self.server.open_lock  # type: ignore[attr-defined]
        with lock:
            bound = getattr(self.server, "bound_root", None)
            if bound is not None:
                if bound != project.root:
                    self._fail(HTTPStatus.CONFLICT, f"this server already opened {bound}")
                    return
                # Idempotent: a second click on the same project (or a second
                # tab that raced the first) is not an error.
                self._send_json({"opened": True, "root": str(project.root)})
                return
            type(self).project_root = project.root
            _bind_singletons(self.server, project.root)  # type: ignore[arg-type]
            self.server.bound_root = project.root  # type: ignore[attr-defined]
        self._send_json({"opened": True, "root": str(project.root)})


# -- the mutating endpoints ----------------------------------------------
#
# Each one is a shape check and a call. No endpoint computes an edit; the
# payload the browser draws is the op's own return value, which is what keeps
# the view honest about `plan` in particular — the panel shows the numbers the
# real call produced, because it *is* the real call with the write skipped.


def _ranges_arg(payload: dict[str, Any], key: str) -> list[list[int]]:
    raw = payload.get(key)
    if not isinstance(raw, list) or not raw:
        raise WebUIError(f"{key!r} must be a non-empty list of [first, last] word ranges")
    out = []
    for item in raw:
        if not isinstance(item, list | tuple) or len(item) != 2:
            raise WebUIError(f"{item!r} is not a [first, last] word range")
        try:
            out.append([int(item[0]), int(item[1])])
        except (TypeError, ValueError):
            raise WebUIError(f"{item!r} is not a [first, last] word range") from None
    return out


def _spans_arg(payload: dict[str, Any]) -> list[list[float]]:
    raw = payload.get("spans")
    if not isinstance(raw, list) or not raw:
        raise WebUIError("'spans' must be a non-empty list of [start, end] timeline spans")
    out = []
    for item in raw:
        if not isinstance(item, list | tuple) or len(item) != 2:
            raise WebUIError(f"{item!r} is not a [start, end] span")
        try:
            out.append([float(item[0]), float(item[1])])
        except (TypeError, ValueError):
            raise WebUIError(f"{item!r} is not a [start, end] span") from None
    return out


def _clip_arg(payload: dict[str, Any]) -> str:
    clip_id = payload.get("clip_id")
    if not isinstance(clip_id, str) or not clip_id:
        raise WebUIError("'clip_id' is required")
    return clip_id


def _float_arg(payload: dict[str, Any], key: str, default: float = 0.0) -> float:
    try:
        return float(payload.get(key, default))
    except (TypeError, ValueError):
        raise WebUIError(f"{key!r} must be a number") from None


def _cut_words(root: str, payload: dict[str, Any]) -> dict[str, Any]:
    mode = payload.get("mode", "cut")
    if mode not in ("cut", "keep"):
        raise WebUIError("'mode' must be 'cut' or 'keep'")
    ranges = _ranges_arg(payload, "ranges")
    return ops.cut_by_transcript(
        root,
        _clip_arg(payload),
        cut=ranges if mode == "cut" else None,
        keep=ranges if mode == "keep" else None,
        pad=_float_arg(payload, "pad"),
        confirm_suspect=bool(payload.get("confirm_suspect")),
        through_pause=bool(payload.get("through_pause")),
        plan=bool(payload.get("plan")),
    )


def _cut_at(root: str, payload: dict[str, Any]) -> dict[str, Any]:
    return ops.cut_by_time(
        root,
        spans=_spans_arg(payload),
        pad=_float_arg(payload, "pad"),
        confirm_suspect=bool(payload.get("confirm_suspect")),
        plan=bool(payload.get("plan")),
    )


def _restore(root: str, payload: dict[str, Any]) -> dict[str, Any]:
    ranges = _ranges_arg(payload, "ranges")
    return ops.restore(
        root,
        _clip_arg(payload),
        ranges,
        pad=_float_arg(payload, "pad"),
        plan=bool(payload.get("plan")),
    )


def _undo(root: str, _payload: dict[str, Any]) -> dict[str, Any]:
    return ops.undo(root)


def _cue_add(root: str, payload: dict[str, Any]) -> dict[str, Any]:
    """`POST /api/cue` — the timeline drag gesture's landing point.

    A fourth caller into `ops.cue_add`, alongside the CLI and MCP tool,
    matching every other route in this table (CLAUDE.md: the web UI draws
    and plays, it never decides — every mutation posts to the same `ops`
    function the CLI and MCP call).
    """
    asset = payload.get("asset")
    if not isinstance(asset, str) or not asset:
        raise WebUIError("'asset' is required")
    word_index = payload.get("word_index")
    try:
        word_index = int(word_index)
    except (TypeError, ValueError):
        raise WebUIError("'word_index' must be an integer") from None
    src_start = payload.get("src_start")
    return ops.cue_add(
        root,
        _clip_arg(payload),
        word_index,
        asset,
        src_start=None if src_start is None else _float_arg(payload, "src_start"),
    )


def _clip_role(root: str, payload: dict[str, Any]) -> dict[str, Any]:
    """`POST /api/clip-role` — the assets pane's role toggle.

    A fourth caller into `ops.clip_role`, alongside the CLI and MCP tool,
    matching every other route in this table (CLAUDE.md: the web UI draws
    and plays, it never decides).
    """
    clip_id = payload.get("clip_id")
    if not isinstance(clip_id, str) or not clip_id:
        raise WebUIError("'clip_id' is required")
    role = payload.get("role")
    if role is not None and not isinstance(role, str):
        raise WebUIError("'role' must be a string")
    return ops.clip_role(root, clip_id, role, reset=bool(payload.get("reset")))


def _agent_thumb(root: str, payload: dict[str, Any]) -> dict[str, Any]:
    """`POST /api/agent/thumbs` — append one rating to `Project.thumbs_path`.

    DAYDREAM.md § Agent panel, item 2: "useful only if something reads it;
    build the log, defer any use." So this is telemetry, not an `ops`
    mutation — no CLI subcommand, matching the existing precedent that
    `/api/agent`, `/api/agent/stop`, `/api/render` and `/api/render/stop`
    also have no CLI equivalents (CLAUDE.md's parity rule is scoped to MCP
    tools, and this route touches no MCP tool either).

    `session_id` + `turn_id` are the pair that let a later reader tell WHICH
    turn was rated: `session_id` is constant across every turn of one
    subprocess (the stream-json `result` event's own field, verified live
    against the installed `claude` binary), `turn_id` — that event's `uuid`
    — is unique per turn. `prompt` is optional, echoed for convenience; it is
    not part of the identifying pair.

    Deliberately does not touch `project.otio`: `_revision()` only stats
    `project.timeline_path` and counts `project.snapshots()`, and this writes
    to neither, so no `project-changed` event fires from this call.
    """
    rating = payload.get("rating")
    if rating not in ("up", "down"):
        raise WebUIError("'rating' must be 'up' or 'down'")
    session_id = payload.get("session_id")
    if not isinstance(session_id, str) or not session_id:
        raise WebUIError("'session_id' is required")
    turn_id = payload.get("turn_id")
    if not isinstance(turn_id, str) or not turn_id:
        raise WebUIError("'turn_id' is required")
    prompt = payload.get("prompt")
    if prompt is not None and not isinstance(prompt, str):
        raise WebUIError("'prompt' must be a string")

    project = Project.open(root)
    record = {
        "ts": datetime.now(UTC).isoformat(),
        "session_id": session_id,
        "turn_id": turn_id,
        "rating": rating,
        "prompt": prompt,
    }
    with project.thumbs_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, sort_keys=True) + "\n")
    return {"recorded": True, **record}


def _reframe(root: str, payload: dict[str, Any]) -> dict[str, Any]:
    """`POST /api/reframe` — the Re-frame panel's landing point.

    A fifth caller into `ops.reframe`, alongside the CLI, the MCP tool, and
    (read-only) `timeline_view`/`reframe_sheet`, matching every other route
    in this table (CLAUDE.md: the web UI draws and plays, it never decides).

    `clip_id` is always required on this route — the read-only "report on
    every clip" use of `ops.reframe(clip_id=None)` has no caller from the
    Frame view; `frame.js` always targets one row's asset. `pane` without
    `rect` is not re-checked here — `ops.reframe` refuses that combination
    itself, and the refusal surfaces as this route's 400, the same
    "don't re-implement the op's own validation" discipline `_cue_add`
    already follows for its own args. `interp`, `reset` and `plan` are not
    read from the payload at all in this step (Studio Step 03 contract § B) —
    nudge and direct-rect-entry produce only `rect`/`pane`/`src_start`.
    """
    clip_id = _clip_arg(payload)
    rect = payload.get("rect")
    if rect is not None and not isinstance(rect, str):
        raise WebUIError("'rect' must be a string")
    pane = payload.get("pane")
    if pane is not None and not isinstance(pane, str):
        raise WebUIError("'pane' must be a string")
    src_start = payload.get("src_start")
    return ops.reframe(
        root,
        clip_id,
        rect=rect,
        pane=pane,
        src_start=None if src_start is None else _float_arg(payload, "src_start"),
        interp=False,
        reset=False,
        plan=False,
    )


#: `plan` is a field on the request rather than a separate endpoint, because
#: it is one flag on one op — giving preview its own URL would invite the two
#: paths to drift, which is the whole thing `plan=True` exists to prevent.
#: `/api/agent`, `/api/agent/stop`, `/api/agent/new-task`, `/api/render` and
#: `/api/render/stop` are handled directly in `do_POST` instead of living
#: here, because they need `self.server` (the bus, the agent session, the
#: render job) rather than just the project root a plain `ops` call takes.
#: `/api/agent/thumbs` is the one `/api/agent*` route that lives here rather
#: than in `do_POST`: it only ever needs the project root, the same as every
#: other route in this table.
_POST_ROUTES: dict[str, Callable[[str, dict[str, Any]], dict[str, Any]]] = {
    "/api/cut": _cut_words,
    "/api/cut-at": _cut_at,
    "/api/restore": _restore,
    "/api/undo": _undo,
    "/api/cue": _cue_add,
    "/api/clip-role": _clip_role,
    "/api/agent/thumbs": _agent_thumb,
    "/api/reframe": _reframe,
    "/api/session": _session_set,
}


# -- lifecycle -----------------------------------------------------------


def _bind_singletons(server: ThreadingHTTPServer, project_root: Path) -> None:
    """One bus, one agent session, one render job and one proxy job — the
    per-project state a `Handler` reaches through `self.server`.

    Called exactly once per server: at construction for a plain `-C` server
    (`make_server`), or once from `Handler._handle_open` on a picker
    server's first successful `POST /api/open`. Never both, and never twice
    — a picker server starts with none of these attributes set at all
    (`make_picker_server`), so a route reached before `/api/open` fails
    loudly (`AttributeError` in tests, refused by `do_POST`/`_route` in
    production) rather than reading a stale project's job.

    This is the whole answer to DAYDREAM.md § Multi-project's "a second
    project would need a second everything here": it does not get one.
    `--root` lets a process defer *which* project these four belong to, but
    only ever binds one — a second project open at once still means a
    second process. The render and the proxy hold *separate* slots for the
    reason they always have: different work on different files, and sharing
    one would make an export refuse while a preview transcoded.
    """
    server.bus = EventBus()  # type: ignore[attr-defined]
    server.agent = AgentSession(project_root, server.bus)  # type: ignore[attr-defined]
    server.render_job = RenderJob(project_root, server.bus)  # type: ignore[attr-defined]
    server.proxy_job = ProxyJob(project_root, server.bus)  # type: ignore[attr-defined]
    server.reframe_sheet_job = ReframeSheetJob(project_root, server.bus)  # type: ignore[attr-defined]
    server.reframe_detect_job = ReframeDetectJob(project_root, server.bus)  # type: ignore[attr-defined]


def make_server(
    path: Path | str,
    *,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    verbose: bool = False,
) -> ThreadingHTTPServer:
    """Build a server for one project. Opens it first, so a bad path fails now.

    Threading matters for two reasons now, not one: media streams for as long
    as playback lasts, and `/api/events` holds a connection open for as long
    as the tab is — either one would leave every other request queued behind
    it on a single-threaded server.
    """
    project = Project.open(path)

    handler = type(
        "BoundHandler",
        (Handler,),
        {"project_root": project.root, "verbose": verbose},
    )
    server = ThreadingHTTPServer((host, port), handler)
    server.daemon_threads = True
    _bind_singletons(server, project.root)
    return server


def make_picker_server(
    root: Path | str,
    *,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    verbose: bool = False,
) -> ThreadingHTTPServer:
    """Build a server over a `--root` scan (DAYDREAM.md § Multi-project).

    Opens nothing: a scan can find a project at an old schema or with a
    broken manifest (`scan_projects`), and `Project.open` must never migrate
    one on a read (CLAUDE.md), so nothing here may call it before a person
    picks. The server starts with `bound_root = None` and no `bus`/`agent`/
    `render_job`/`proxy_job` at all; `Handler._route_picker` and
    `Handler._handle_open` are the only routes reachable until `POST
    /api/open` succeeds, at which point `_bind_singletons` runs (the same
    call `make_server` makes at construction, just later) and this server is
    an ordinary single-project server for the rest of its life — see
    `_bind_singletons`'s docstring for why that is the whole design.
    """
    root_dir = Path(root).expanduser().resolve()
    handler = type(
        "RootHandler",
        (Handler,),
        {"root_dir": root_dir, "verbose": verbose},
    )
    server = ThreadingHTTPServer((host, port), handler)
    server.daemon_threads = True
    server.bound_root = None  # type: ignore[attr-defined]
    #: Guards the check-then-bind in `Handler._handle_open` — two requests
    #: racing to open two *different* projects on the same fresh server must
    #: not both win, or the second `_bind_singletons` call would silently
    #: replace the first project's agent/render/proxy jobs out from under
    #: whoever was about to use them.
    server.open_lock = threading.Lock()  # type: ignore[attr-defined]
    return server


def serve(
    path: Path | str,
    *,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    verbose: bool = False,
    open_browser: bool = False,
) -> None:
    """Run the UI until interrupted. `port=0` picks a free one."""
    server = make_server(path, host=host, port=port, verbose=verbose)
    bound = server.server_address[1]
    url = f"http://{host}:{bound}/"
    # Flushed: this is the one line the user needs, and a piped stdout would
    # otherwise hold it in the buffer until the server exits.
    print(f"lucid web: {url}  (project: {Project.open(path).root})", flush=True)
    print("Ctrl-C to stop.", flush=True)

    if open_browser:
        import webbrowser

        threading.Timer(0.3, webbrowser.open, args=(url,)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print()
    finally:
        server.shutdown()
        server.server_close()
        server.agent.close()  # type: ignore[attr-defined]


def serve_root(
    root: Path | str,
    *,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    verbose: bool = False,
    open_browser: bool = False,
) -> None:
    """Run the picker until interrupted. `port=0` picks a free one.

    Once `POST /api/open` binds a project, this is functionally `serve`
    running on a server that happened to start life unbound — same loop,
    same shutdown. `open_browser` opens the picker, not a project: nothing
    is open yet at startup by construction.
    """
    server = make_picker_server(root, host=host, port=port, verbose=verbose)
    bound = server.server_address[1]
    url = f"http://{host}:{bound}/"
    root_dir = server.RequestHandlerClass.root_dir  # type: ignore[attr-defined]
    print(f"lucid web: {url}  (projects under: {root_dir})", flush=True)
    print("Ctrl-C to stop.", flush=True)

    if open_browser:
        import webbrowser

        threading.Timer(0.3, webbrowser.open, args=(url,)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print()
    finally:
        server.shutdown()
        server.server_close()
        agent = getattr(server, "agent", None)
        if agent is not None:
            agent.close()


#: Checked in order by `_resolve_app_browser`; a chromium-family browser is
#: required because `--app=<url>` (a chromeless window, no tabs/toolbar) is
#: a Chromium flag with no Firefox/Safari equivalent — the whole reason
#: `lucid open` prefers one over the default browser. Verified live on this
#: box: nothing here is on PATH (only reachable through the flatpak tier
#: below), but the tuple is what should be probed, portably.
_APP_BROWSER_BINS = (
    "chromium",
    "chromium-browser",
    "google-chrome",
    "google-chrome-stable",
    "google-chrome-unstable",
    "chrome",
    "brave-browser",
    "brave",
    "vivaldi",
    "microsoft-edge",
    "microsoft-edge-stable",
)

#: Same chromium-family constraint, one flatpak app ID per vendor.
#: `com.google.Chrome` is confirmed installed on this box (flathub, system)
#: and is what actually fires `lucid open` here today, since nothing above
#: is on PATH.
_APP_BROWSER_FLATPAKS = (
    "com.google.Chrome",
    "com.brave.Browser",
    "com.microsoft.Edge",
    "org.chromium.Chromium",
    "com.vivaldi.Vivaldi",
)

#: Env var naming an exact browser command to launch `lucid open`'s window
#: with. Checked first and taken literally — no existence check — because an
#: operator who set it wrong would rather see the failure than have it
#: silently ignored.
LUCID_BROWSER_ENV = "LUCID_BROWSER"


def _resolve_app_browser() -> list[str] | None:
    """The command to launch a chromeless `--app=<url>` window with, or None.

    Checked in order, stopping at the first hit: `$LUCID_BROWSER` (taken
    literally, unconditionally); a chromium-family binary on PATH
    (`_APP_BROWSER_BINS`); a chromium-family flatpak, only if `flatpak`
    itself is on PATH (`_APP_BROWSER_FLATPAKS`, probed with `flatpak info`).

    Deliberately does not add a fourth tier for Playwright's cached
    Chromium under `~/.cache/ms-playwright/` — it exists on this box only as
    a test fixture, and `chrome-headless-shell` specifically cannot open a
    window at all, so launching either as the user's app surface would be
    silently wrong (Studio Step 04 contract § A).
    """
    override = os.environ.get(LUCID_BROWSER_ENV)
    if override:
        return [override]

    for name in _APP_BROWSER_BINS:
        resolved = shutil.which(name)
        if resolved:
            return [resolved]

    if shutil.which("flatpak"):
        for app_id in _APP_BROWSER_FLATPAKS:
            try:
                probe = subprocess.run(
                    ["flatpak", "info", app_id], capture_output=True, check=False
                )
            except OSError:
                continue
            if probe.returncode == 0:
                return ["flatpak", "run", app_id]

    return None


def _launch_app(url: str) -> None:
    """Open `url` in a chromeless app window, falling back to `xdg-open`.

    Best-effort only: a vanished binary, a permission error, or nothing
    found at all must never crash `lucid open` — the URL was already
    printed by the caller before this runs, which is what satisfies "print
    the URL either way."
    """
    cmd = _resolve_app_browser()
    if cmd is not None:
        try:
            subprocess.Popen(
                [*cmd, f"--app={url}"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except OSError:
            pass
        return

    xdg_open = shutil.which("xdg-open")
    if xdg_open:
        try:
            subprocess.Popen(
                [xdg_open, url],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except OSError:
            pass


def open_studio(path: Path | str | None = None, *, root: Path | str | None = None) -> None:
    """`lucid open` — an ephemeral-port server plus a chromeless browser window.

    Studio Step 04 contract § A. Composes the existing `make_server`/
    `make_picker_server` rather than adding a mode to `serve`/`serve_root`,
    so neither function's signature or existing callers/tests are touched.
    Port is hardcoded `0` — always ephemeral, never configurable, per
    STUDIO.md's own wording; there is no `--host`/`--port` here the way
    `lucid web` has them.

    `-C` (`path`) opens straight into that project; `--root` opens Home.
    Mutual refusal between the two lives in `cli._cmd_open`, matching where
    `_cmd_web` already refuses `-C`+`--root` together.
    """
    if root is not None:
        server = make_picker_server(root, host=DEFAULT_HOST, port=0)
        bound = server.server_address[1]
        url = f"http://{DEFAULT_HOST}:{bound}/"
        root_dir = server.RequestHandlerClass.root_dir  # type: ignore[attr-defined]
        print(f"lucid open: {url}  (projects under: {root_dir})", flush=True)
    else:
        server = make_server(path if path is not None else ".", host=DEFAULT_HOST, port=0)
        bound = server.server_address[1]
        url = f"http://{DEFAULT_HOST}:{bound}/"
        print(f"lucid open: {url}  (project: {Project.open(path if path is not None else '.').root})", flush=True)
    print("Ctrl-C to stop.", flush=True)

    # 0.3s, same delay `serve`'s own `open_browser` path already uses — the
    # socket is listening (bound above) before anything dials it, and the
    # print above already happened, so the URL is on screen even if
    # `_launch_app` finds nothing.
    threading.Timer(0.3, _launch_app, args=(url,)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print()
    finally:
        server.shutdown()
        server.server_close()
        agent = getattr(server, "agent", None)
        if agent is not None:
            agent.close()
