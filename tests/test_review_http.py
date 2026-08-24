"""`lucid review serve`, exercised over a real socket.

The same discipline `test_webui_http.py` applies to the edit UI: a handler
function called directly proves nothing about routing, Range, or whether the
token guard actually fires. So these start the real `ThreadingHTTPServer` and
speak HTTP to it — including the case webui.py's own suite doesn't have to
cover, since loopback+Host isn't the guard here: a request with no token, or
the wrong one, at all.
"""

from __future__ import annotations

import http.client
import threading
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urlsplit

import pytest

from lucid import finishlog, ops, reviewserver
from lucid.project import Project

TOKEN = "test-token-not-a-secret"


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """A project with one registered render, ready for a review round."""
    root = tmp_path / "proj"
    ops.init(root)
    (root / "renders" / "teaser.mp4").write_bytes(b"0123456789" * 50)
    ops.review_add(root, "teaser", "renders/teaser.mp4", kind="render")
    return root


@pytest.fixture
def server(project: Path) -> Iterator[str]:
    """The real server on a free port, torn down after the test."""
    httpd = reviewserver.make_server(project, port=0, token=TOKEN)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}"
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def _get(url: str, **kwargs: Any) -> tuple[int, dict[str, str], bytes]:
    request = urllib.request.Request(url, **kwargs)
    try:
        with urllib.request.urlopen(request) as response:
            return response.status, dict(response.headers), response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers), exc.read()


def _post_form_no_redirect(server: str, path: str, fields: dict[str, str]) -> tuple[int, dict[str, str]]:
    """POST form-encoded, without following a redirect — so the 302 itself is visible."""
    parts = urlsplit(server)
    assert parts.hostname is not None and parts.port is not None
    conn = http.client.HTTPConnection(parts.hostname, parts.port)
    try:
        body = urlencode(fields)
        conn.request(
            "POST",
            path,
            body=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        response = conn.getresponse()
        response.read()
        return response.status, dict(response.getheaders())
    finally:
        conn.close()


def test_a_request_with_no_token_is_forbidden(server: str) -> None:
    status, _, _ = _get(f"{server}/")
    assert status == 403


def test_a_request_with_the_wrong_token_is_forbidden(server: str) -> None:
    status, _, _ = _get(f"{server}/?t=wrong")
    assert status == 403


def test_the_page_lists_a_registered_item(server: str) -> None:
    status, _, body = _get(f"{server}/?t={TOKEN}")
    assert status == 200
    assert b"teaser" in body


def test_a_range_request_on_a_registered_item_returns_206_and_exactly_those_bytes(
    project: Path, server: str
) -> None:
    whole = (project / "renders" / "teaser.mp4").read_bytes()

    status, headers, body = _get(
        f"{server}/media/teaser?t={TOKEN}", headers={"Range": "bytes=10-19"}
    )
    assert status == 206
    assert headers["Content-Range"] == f"bytes 10-19/{len(whole)}"
    assert body == whole[10:20]


def test_media_with_no_token_is_forbidden(server: str) -> None:
    status, _, _ = _get(f"{server}/media/teaser")
    assert status == 403


def test_a_verdict_posted_with_the_right_token_is_recorded(project: Path, server: str) -> None:
    status, headers = _post_form_no_redirect(
        server, f"/verdict?t={TOKEN}", {"name": "teaser", "verdict": "ship it", "note": "watched twice"}
    )
    assert status == 302
    assert headers["Location"] == f"/?t={TOKEN}"

    verdicts = ops.review_list(project)["verdicts"]
    assert verdicts["teaser"]["verdict"] == "ship it"
    assert verdicts["teaser"]["note"] == "watched twice"


def test_a_verdict_posted_with_the_wrong_token_is_refused_and_not_recorded(
    project: Path, server: str
) -> None:
    status, _ = _post_form_no_redirect(
        server, "/verdict?t=wrong", {"name": "teaser", "verdict": "ship it"}
    )
    assert status == 403
    assert ops.review_list(project)["verdicts"] == {}


def test_a_verdict_for_an_unregistered_name_is_refused(server: str) -> None:
    status, _ = _post_form_no_redirect(
        server, f"/verdict?t={TOKEN}", {"name": "no-such-item", "verdict": "ship it"}
    )
    assert status == 400


# -- finish_check's WARN badge, joined on sha256 -----------------------------


def test_an_item_with_no_finish_check_shows_the_no_check_yet_note(server: str) -> None:
    status, _, body = _get(f"{server}/?t={TOKEN}")
    assert status == 200
    assert b"no finish_check yet" in body


def test_a_failing_finish_check_shows_the_warn_badge(project: Path, server: str) -> None:
    item = ops.review_list(project)["items"][0]
    finishlog.append(
        Project.open(project),
        final=str(project / item["path"]),
        sha256=item["sha256"],
        faults=3,
        ok=False,
        summary={"missing": 3},
    )

    status, _, body = _get(f"{server}/?t={TOKEN}")

    assert status == 200
    assert "⚠ finish_check: 3 fault(s)".encode() in body
    assert b"no finish_check yet" not in body


def test_a_passing_finish_check_shows_no_warn(project: Path, server: str) -> None:
    item = ops.review_list(project)["items"][0]
    finishlog.append(
        Project.open(project),
        final=str(project / item["path"]),
        sha256=item["sha256"],
        faults=0,
        ok=True,
        summary={},
    )

    status, _, body = _get(f"{server}/?t={TOKEN}")

    assert status == 200
    assert b"finish_check" not in body
    assert b"no finish_check yet" not in body


def test_a_finish_check_keyed_to_a_different_sha256_does_not_match(
    project: Path, server: str
) -> None:
    """The join is on bytes, not on name — a stale or unrelated log entry
    must not paint a badge that does not belong to this item."""
    finishlog.append(
        Project.open(project),
        final="/tmp/some-other-file.mp4",
        sha256="0" * 64,
        faults=5,
        ok=False,
        summary={},
    )

    status, _, body = _get(f"{server}/?t={TOKEN}")

    assert status == 200
    assert b"no finish_check yet" in body
    assert b"5 fault" not in body
