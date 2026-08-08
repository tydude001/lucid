"""The preview/timeline web UI — a third client, never a third implementation.

lucid's checks all answer a *machine's* question: `verify` diffs the render's
words, `frames`/`black`/`spots` read counts and pixels. None of them let a
person see an edit before committing to a render. This does — and because it
plays the *source* through the edit rather than a render of it, seeing an edit
costs no render at all.

Two constraints hold it in place, both from ROADMAP.md § Next:

* **No privileged path.** Every mutation here goes through the same `ops`
  functions the CLI and the MCP server call. A window is the most tempting
  thing to break the parity convention with, so nothing below computes an
  edit — it posts to `ops.cut_by_transcript` / `ops.cut_by_time` / `ops.undo`
  and draws whatever comes back.
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
import threading
from collections.abc import Callable
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
}

#: Read size for streaming media. Large enough that a long range is not a
#: million syscalls, small enough that an aborted seek stops promptly.
_CHUNK = 256 * 1024


class WebUIError(Exception):
    """Raised when a request cannot be served for a reason worth reporting."""


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
            elif path.startswith("/api/media/"):
                self._send_media(unquote(path[len("/api/media/") :]), head_only=head_only)
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

        Resolution goes through `media.media_path`, which prefers an
        attenuated copy when one exists (CLAUDE.md). That is right rather than
        incidental: it is the file every downstream op reads, so the preview
        is of the audio that will actually be exported.
        """
        project = Project.open(self.project_root)
        clip = media.get_clip(project, clip_id)
        source = media.media_path(project, clip)
        if not source.is_file():
            raise WebUIError(f"{clip_id}'s media is missing from disk: {source}")

        size = source.stat().st_size
        ctype = mimetypes.guess_type(source.name)[0] or "application/octet-stream"
        header = self.headers.get("Range")
        window = _ranges(header, size) if header else None

        if window is None:
            start, end, status = 0, size - 1, HTTPStatus.OK
        else:
            start, end = window
            status = HTTPStatus.PARTIAL_CONTENT

        length = end - start + 1
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(length))
        self.send_header("Accept-Ranges", "bytes")
        if status == HTTPStatus.PARTIAL_CONTENT:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
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
                    self.wfile.write(chunk)
                except (BrokenPipeError, ConnectionResetError):
                    # A seek aborts the in-flight range. Routine, not an error.
                    return
                remaining -= len(chunk)


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


def _undo(root: str, _payload: dict[str, Any]) -> dict[str, Any]:
    return ops.undo(root)


#: `plan` is a field on the request rather than a separate endpoint, because
#: it is one flag on one op — giving preview its own URL would invite the two
#: paths to drift, which is the whole thing `plan=True` exists to prevent.
_POST_ROUTES: dict[str, Callable[[str, dict[str, Any]], dict[str, Any]]] = {
    "/api/cut": _cut_words,
    "/api/cut-at": _cut_at,
    "/api/undo": _undo,
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

    Threading matters here for one specific reason: media streams for as long
    as playback lasts, and a single-threaded server would leave every API call
    queued behind it.
    """
    project = Project.open(path)

    handler = type(
        "BoundHandler",
        (Handler,),
        {"project_root": project.root, "verbose": verbose},
    )
    server = ThreadingHTTPServer((host, port), handler)
    server.daemon_threads = True
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
