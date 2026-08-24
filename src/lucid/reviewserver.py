"""`lucid review serve` — the review round as a feature, not a throwaway script.

Every version of the Scream video moved on a served page, and that serving
was hand-rebuilt at least four times (`~/lucid-approvals/`, `~/lucid-watch/`,
`~/lucid-review/`, `~/lucid-flash-review/`), each its own throwaway HTTP
server and its own `decisions.json` living beside the project rather than in
it (PLAN.md § The completion queue, item 6). This is that serving, once:
`lucid review add` registers named renders/sheets/A-B members
(`ops.review_add`), this streams them with Range support so a phone can
scrub, and a plain HTML form posts a verdict straight into the manifest
(`ops.review_verdict`) — no JS, no build step, the `webui.py` stance.

**Different trust model from `webui.py`, deliberately.** `webui.py` binds
loopback and checks the `Host` header, because it can rewrite the whole
project and a page in any other tab on the same machine could reach it under
an attacker-chosen name. This server exists specifically to be reached off
the machine — from a phone on Tailscale — so loopback+Host buys nothing here
and a **token** stands in for it instead: `serve()` mints one
(`secrets.token_urlsafe`) unless the caller supplies one, and every request,
GET or POST, must carry it as `?t=`. The one line printed at startup is the
whole credential — that is what gets copied to the phone. The blast radius
is also smaller than `webui.py`'s: the only mutation this server can cause is
recording a verdict string against an already-registered item, never an edit.

Reuses `webui._stream_file`/`webui._ranges` for the one hand-rolled piece of
HTTP in the package (Range), rather than a second, divergent copy of the
byte math — see `webui.py`'s own module docstring.

**Each item's badge also joins `finishlog` by sha256** — every registered
item already carries its own hash (`ops.review_add`), so a `finish_check`
result follows the delivered *bytes* rather than a name or path that could
be re-registered under something new. `" — no finish_check yet"` or
`" — ⚠ finish_check: N fault(s)"` beside the byte-identical/MISMATCH control
badge — a **report**, never a refusal: nothing here blocks a page from
serving, the same stance `finish_report`'s `burned: "unknown"` and a
`control_ok: False` item (displayed, never refused at *serve* time) take.
"""

from __future__ import annotations

import hmac
import secrets
from html import escape
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urlparse

from lucid import finishlog, ops
from lucid import webui as _webui
from lucid.project import Project, ProjectError

DEFAULT_HOST = "127.0.0.1"
#: Deliberately not 8710 (`webui.DEFAULT_PORT`) or 8000/8080 — a review round
#: and the edit UI are commonly run against the same project at once.
DEFAULT_PORT = 8720

_MEDIA_KIND = {
    ".mp4": "video",
    ".mov": "video",
    ".webm": "video",
    ".mkv": "video",
    ".mp3": "audio",
    ".wav": "audio",
    ".aac": "audio",
    ".m4a": "audio",
    ".png": "image",
    ".jpg": "image",
    ".jpeg": "image",
}


class ReviewServerError(Exception):
    """A malformed request — reported as 400, not a crash."""


class Handler(BaseHTTPRequestHandler):
    """One request. `project_root` and `token` are set by `make_server`."""

    project_root: Path
    token: str
    verbose: bool = False
    server_version = "lucid-review"
    sys_version = ""
    #: Keep-alive, so scrubbing a video does not reopen a connection per range.
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args: Any) -> None:
        if self.verbose:
            super().log_message(fmt, *args)

    # -- auth --------------------------------------------------------------

    def _token_ok(self, query: dict[str, list[str]]) -> bool:
        supplied = (query.get("t") or [""])[0]
        # Constant-time: this token is the only thing standing between the
        # LAN and a project's verdicts, so it gets the same comparison a
        # password would.
        return hmac.compare_digest(supplied, self.token)

    # -- plumbing ------------------------------------------------------------

    def _send(self, status: HTTPStatus, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Content-Security-Policy", "default-src 'self'; media-src 'self'")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _send_html(self, status: HTTPStatus, html: str) -> None:
        self._send(status, html.encode("utf-8"), "text/html; charset=utf-8")

    def _fail(self, status: HTTPStatus, message: str) -> None:
        self._send_html(status, f"<!doctype html><p>{escape(message)}</p>")

    # -- routing -------------------------------------------------------------

    def do_GET(self) -> None:
        self._route(head_only=False)

    def do_HEAD(self) -> None:
        self._route(head_only=True)

    def _route(self, *, head_only: bool) -> None:
        url = urlparse(self.path)
        if not self._token_ok(parse_qs(url.query)):
            self._fail(HTTPStatus.FORBIDDEN, "missing or wrong token")
            return
        try:
            if url.path == "/":
                self._send_page(head_only=head_only)
            elif url.path.startswith("/media/"):
                self._send_media(unquote(url.path[len("/media/") :]), head_only=head_only)
            else:
                self._fail(HTTPStatus.NOT_FOUND, f"no such endpoint: {url.path}")
        except (ReviewServerError, ProjectError) as exc:
            self._fail(HTTPStatus.BAD_REQUEST, str(exc))

    def do_POST(self) -> None:
        url = urlparse(self.path)
        if not self._token_ok(parse_qs(url.query)):
            self._fail(HTTPStatus.FORBIDDEN, "missing or wrong token")
            return
        if url.path != "/verdict":
            self._fail(HTTPStatus.NOT_FOUND, f"no such endpoint: {url.path}")
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length > 0 else b""
            form = parse_qs(raw.decode("utf-8"))
            name = (form.get("name") or [""])[0]
            verdict = (form.get("verdict") or [""])[0]
            note = (form.get("note") or [""])[0] or None
            if not name or not verdict:
                raise ReviewServerError("both 'name' and 'verdict' are required")
            ops.review_verdict(str(self.project_root), name, verdict, note=note)
        except (ReviewServerError, ProjectError) as exc:
            self._fail(HTTPStatus.BAD_REQUEST, str(exc))
            return
        self.send_response(HTTPStatus.FOUND)
        self.send_header("Location", f"/?t={quote(self.token)}")
        self.send_header("Content-Length", "0")
        self.end_headers()

    # -- handlers --------------------------------------------------------

    def _send_media(self, name: str, *, head_only: bool) -> None:
        listing = ops.review_list(str(self.project_root))
        item = next((it for it in listing["items"] if it["name"] == name), None)
        if item is None:
            raise ReviewServerError(f"no registered review item named {name!r}")
        source = self.project_root / item["path"]
        if not source.is_file():
            raise ReviewServerError(f"{name}'s file is missing from disk: {source}")
        # The shared Range/streaming mechanism (`webui.py`'s module docstring:
        # "the one thing hand-rolled rather than inherited"), not a second copy.
        _webui._stream_file(self, source, head_only=head_only)

    def _send_page(self, *, head_only: bool) -> None:
        listing = ops.review_list(str(self.project_root))
        html = _render_page(listing, self.token, Project.open(self.project_root))
        if head_only:
            self._send(HTTPStatus.OK, b"", "text/html; charset=utf-8")
            return
        self._send_html(HTTPStatus.OK, html)


def _render_page(listing: dict[str, Any], token: str, project: Project) -> str:
    items = sorted(listing["items"], key=lambda it: it["added_at"])
    verdicts = listing["verdicts"]
    sections = []
    for item in items:
        name = item["name"]
        suffix = Path(item["path"]).suffix.lower()
        media_kind = _MEDIA_KIND.get(suffix)
        src = f"/media/{quote(name)}?t={quote(token)}"
        if media_kind == "video":
            media_html = f'<video controls preload="metadata" src="{src}"></video>'
        elif media_kind == "audio":
            media_html = f'<audio controls preload="metadata" src="{src}"></audio>'
        elif media_kind == "image":
            media_html = f'<img src="{src}" alt="{escape(name)}">'
        else:
            media_html = f'<a href="{src}">{escape(item["path"])}</a>'

        badge = ""
        if item["kind"] == "control":
            badge = " — byte-identical" if item.get("control_ok") else " — MISMATCH"

        # `finish_check`'s own WARN, joined on sha256 rather than name or
        # path — a review item can be re-registered under a new name, or the
        # same delivered bytes registered twice, and the finish_check
        # result should follow the *bytes*. **Report, never refuse**: this
        # is a badge beside an item that already serves, the same stance
        # `finish_report`'s `burned: "unknown"` and a `control_ok: False`
        # item (displayed, never refused at *serve* time) both take.
        fc = finishlog.for_sha256(project, item["sha256"])
        if fc is None:
            badge += " — no finish_check yet"
        elif not fc["ok"]:
            badge += f" — ⚠ finish_check: {fc['faults']} fault(s)"

        existing = verdicts.get(name)
        current = ""
        if existing:
            note = f" — {escape(existing['note'])}" if existing.get("note") else ""
            current = f'<p>current verdict: <strong>{escape(existing["verdict"])}</strong>{note}</p>'

        sections.append(
            f"""
        <section>
          <h2>{escape(name)} <small>({escape(item["kind"])}{badge})</small></h2>
          {media_html}
          {current}
          <form method="post" action="/verdict?t={quote(token)}">
            <input type="hidden" name="name" value="{escape(name)}">
            <input type="text" name="verdict" placeholder="verdict" required>
            <input type="text" name="note" placeholder="note (optional)">
            <button type="submit">Save</button>
          </form>
        </section>
        """
        )

    body = "\n".join(sections) if sections else "<p>Nothing registered yet — `lucid review add`.</p>"
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>lucid review</title>
<style>
  body {{ font-family: system-ui, sans-serif; max-width: 640px; margin: 0 auto; padding: 1rem; }}
  video, audio, img {{ width: 100%; border-radius: 4px; }}
  section {{ margin-bottom: 2rem; border-bottom: 1px solid #ccc; padding-bottom: 1rem; }}
  form {{ display: flex; gap: 0.5rem; flex-wrap: wrap; margin-top: 0.5rem; }}
  input[type=text] {{ flex: 1; min-width: 8rem; }}
</style>
</head>
<body>
<h1>lucid review</h1>
{body}
</body>
</html>"""


def make_server(
    path: Path | str,
    *,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    token: str | None = None,
    verbose: bool = False,
) -> ThreadingHTTPServer:
    """Build a server for one project's review round. Opens it first, so a
    bad path fails now rather than on the first request.
    """
    project = Project.open(path)
    resolved_token = token or secrets.token_urlsafe(24)

    handler = type(
        "BoundReviewHandler",
        (Handler,),
        {"project_root": project.root, "token": resolved_token, "verbose": verbose},
    )
    server = ThreadingHTTPServer((host, port), handler)
    server.daemon_threads = True
    server.token = resolved_token  # type: ignore[attr-defined]
    return server


def serve(
    path: Path | str,
    *,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    token: str | None = None,
    verbose: bool = False,
) -> None:
    """Run a review round until interrupted. `port=0` picks a free one."""
    server = make_server(path, host=host, port=port, token=token, verbose=verbose)
    bound = server.server_address[1]
    url = f"http://{host}:{bound}/?t={server.token}"  # type: ignore[attr-defined]
    # Flushed, the `webui.serve` reason: this is the one line to copy to a
    # phone, and a piped stdout would otherwise hold it in the buffer.
    print(f"lucid review: {url}  (project: {Project.open(path).root})", flush=True)
    print("Ctrl-C to stop.", flush=True)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print()
    finally:
        server.shutdown()
        server.server_close()


__all__ = ["DEFAULT_HOST", "DEFAULT_PORT", "Handler", "ReviewServerError", "make_server", "serve"]
