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

from lucid import captions, media, ops
from lucid.asr import ASRError
from lucid.autoeditor import AutoEditorError
from lucid.energy import EnergyError
from lucid.media import MediaError
from lucid.mlt import MLTError
from lucid.picture import PictureError
from lucid.project import Project, ProjectError
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
    """One render at a time per server (PLAN.md § Finishing).

    Runs `ops.export` — unchanged, no new render path — in a worker thread and
    publishes progress and completion as `render` events on the bus the SSE
    handler already serves.

    `stop()` deletes whatever the partial output currently is rather than
    leaving it, per PLAN.md's explicit "not left" — but honestly: `ops.export`
    is one blocking call into auto-editor's own subprocess, and nothing here
    holds a handle to kill that subprocess mid-encode. So cancellation deletes
    the *result* on both ends — immediately, on the thread that called
    `stop()`, and again when the background export call eventually returns —
    rather than pretending to halt an encode it cannot reach.

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

    def start(self, preset: str | None, resolution: tuple[int, int] | None = None) -> str:
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
            target=self._run, args=(job_id, output, cancel, preset, resolution), daemon=True
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
            self._run_inner(job_id, output, cancel, preset, resolution)
        finally:
            self._finish()

    def _run_inner(
        self,
        job_id: str,
        output: Path,
        cancel: threading.Event,
        preset: str | None,
        resolution: tuple[int, int] | None,
    ) -> None:
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
                self.bus.publish("render", {"job_id": job_id, "status": "cancelled"})
            else:
                self._report_error(exc, job_id)
            return

        if cancel.is_set():
            self._finish()
            self._delete(output)
            self.bus.publish("render", {"job_id": job_id, "status": "cancelled"})
            return

        try:
            # (a) auto-editor's exit code does not mean success — this probes
            # the actual file that landed on disk, the same way every other
            # check here reads a render rather than trusting a subprocess's
            # own report of itself.
            info = media.probe(output)
        except EXPECTED as exc:
            self._finish()
            self._report_error(exc, job_id)
            return

        # (b) the existing checks, run here rather than left for a person to
        # remember — see `_run_checks`.
        checks = _run_checks(self.project_root, output, info.has_video)
        self._finish()
        self.bus.publish(
            "render",
            {
                "job_id": job_id,
                "status": "done",
                "output": str(output),
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


class Handler(BaseHTTPRequestHandler):
    """One request. `project_root` and `verbose` are set by `make_server`."""

    project_root: Path
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

    def _route(self, *, head_only: bool) -> None:
        if not self._host_is_loopback():
            self._fail(HTTPStatus.FORBIDDEN, "this server answers loopback requests only")
            return
        url = urlparse(self.path)
        path = url.path
        try:
            if path in ("/", "/index.html"):
                self._send_static("index.html")
            elif path.startswith("/static/"):
                self._send_static(path[len("/static/") :])
            elif path == "/api/view":
                query = parse_qs(url.query)
                clip_id = (query.get("clip_id") or [None])[0]
                self._send_json(ops.timeline_view(str(self.project_root), clip_id=clip_id))
            elif path == "/api/captions":
                query = parse_qs(url.query)
                clip_id = (query.get("clip_id") or [None])[0]
                self._send_json(ops.caption_view(str(self.project_root), clip_id=clip_id))
            elif path == "/api/events":
                self._send_events()
            elif path.startswith("/api/waveform/"):
                clip_id = unquote(path[len("/api/waveform/") :])
                if not clip_id:
                    raise WebUIError("clip id is required")
                self._send_json(ops.waveform(str(self.project_root), clip_id))
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
        """`POST /api/render {"preset": optional, "resolution": optional}` —
        202, work happens on the stream.

        Like `/api/agent`, the reply only acknowledges; progress and
        completion arrive as `render` events on `/api/events`. Both fields
        are threaded straight to `ops.export` (`ops.EXPORT_PRESETS`) — this
        handler only checks their *shape* (a string; a 2-element list of
        ints), never whether the combination is valid. An invalid
        combination (an unknown preset name, `resolution` on a layered
        project, `preset`/`resolution` with an NLE `export_format` — this
        endpoint never asks for one, so that specific combination cannot
        happen here) still raises inside `ops.export`, on the render worker
        thread, and surfaces as the existing `error` render event — the
        window draws and plays, it does not decide.
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
        except WebUIError as exc:
            self._fail(HTTPStatus.BAD_REQUEST, str(exc))
            return
        job: RenderJob = self.server.render_job  # type: ignore[attr-defined]
        try:
            job_id = job.start(preset, resolution)
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
    "/api/agent/thumbs": _agent_thumb,
}


# -- lifecycle -----------------------------------------------------------


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
    #: One bus, one agent session, one render job and one proxy job per
    #: server, because one server serves one project (§ Multi-project in
    #: PLAN.md's open questions — unanswered, and this is why: a second
    #: project would need a second everything here). The render and the proxy
    #: hold *separate* slots: they are different work on different files, and
    #: sharing one would make an export refuse while a preview transcoded.
    server.bus = EventBus()  # type: ignore[attr-defined]
    server.agent = AgentSession(project.root, server.bus)  # type: ignore[attr-defined]
    server.render_job = RenderJob(project.root, server.bus)  # type: ignore[attr-defined]
    server.proxy_job = ProxyJob(project.root, server.bus)  # type: ignore[attr-defined]
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
