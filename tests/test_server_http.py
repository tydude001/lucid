"""The MCP server's HTTP transport, exercised over a real socket.

Same discipline as `test_server_stdio.py` (a handler called directly proves
nothing about routing) and `test_webui_http.py` (loopback alone does not
guard a server that can rewrite the project): this spawns `lucid mcp
--transport http` as a real subprocess bound to a real ephemeral port and
speaks real HTTP to it, including the plain-socket request that proves the
Host-header guard fires before any MCP framing is even parsed.

`Client` and `_refused` are imported from `test_server_stdio` rather than
copied — same plumbing, same assertions, so a round-trip over HTTP can be
compared byte-for-byte against the same call over stdio.
"""

from __future__ import annotations

import json
import queue
import re
import subprocess
import sys
import threading
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import anyio
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from test_server_stdio import SERVER, Client, _refused, _with_server

from lucid import ops

_URL_RE = re.compile(r"(http://[^\s]+/mcp)")


def _start_http(root: Path | None, *extra: str, timeout: float = 15.0) -> tuple[subprocess.Popen[str], str]:
    """Spawn `lucid [-C root] mcp --transport http --port 0 [extra...]`.

    `--port 0` picks a free port the way `lucid web --port 0` does; the
    server prints the URL it actually bound (`server._serve_http`) as its
    first line, which is how the ephemeral port is discovered here.
    """
    args = [sys.executable, "-m", "lucid.cli"]
    if root is not None:
        args = [*args, "-C", str(root)]
    args = [*args, "mcp", "--transport", "http", "--port", "0", *extra]
    proc = subprocess.Popen(
        args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1
    )
    # A thread rather than `select()`, which takes only sockets on Windows —
    # `[WinError 10038]` for a pipe, the first Windows CI run (2026-09-10).
    first: queue.Queue[str] = queue.Queue()
    threading.Thread(target=lambda: first.put(proc.stdout.readline()), daemon=True).start()
    try:
        line = first.get(timeout=timeout)
    except queue.Empty:
        proc.kill()
        err = proc.stderr.read() if proc.stderr else ""
        raise RuntimeError(
            f"lucid mcp --transport http did not start in {timeout}s: {err}"
        ) from None
    match = _URL_RE.search(line)
    if not match:
        proc.kill()
        err = proc.stderr.read() if proc.stderr else ""
        raise RuntimeError(f"unexpected startup line {line!r}; stderr={err}")
    return proc, match.group(1)


def _stop(proc: subprocess.Popen[str]) -> None:
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)


@pytest.fixture
def http_server(tmp_path: Path) -> Iterator[str]:
    """An unbound HTTP MCP server on a free loopback port."""
    proc, url = _start_http(None)
    try:
        yield url
    finally:
        _stop(proc)


async def _with_http_server(body: Any, url: str) -> Any:
    async with (
        streamable_http_client(url) as (read, write),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        return await body(session)


def test_http_server_starts_and_answers_initialize(http_server: str) -> None:
    async def body(session: ClientSession) -> Any:
        return session

    # `_with_http_server` itself calls `session.initialize()` before handing
    # control to `body`; getting here at all is the assertion that the
    # handshake round-tripped over the real socket. `list_tools` is a second,
    # independent proof the session is live.
    async def list_tools(session: ClientSession) -> Any:
        return await session.list_tools()

    result = anyio.run(_with_http_server, list_tools, http_server)
    names = {tool.name for tool in result.tools}
    assert "cue_ls" in names
    assert "ping" in names


def test_http_tool_call_matches_stdio(tmp_path: Path) -> None:
    """The same call over HTTP and over stdio returns the same JSON."""
    project = tmp_path / "proj"
    ops.init(str(project))

    async def call_it(session: ClientSession) -> Any:
        return await Client(session).call("cue_ls", path=str(project))

    stdio_result = anyio.run(_with_server, call_it, SERVER)

    proc, url = _start_http(None)
    try:
        http_result = anyio.run(_with_http_server, call_it, url)
    finally:
        _stop(proc)

    assert http_result == stdio_result == {"cues": [], "count": 0}


def test_http_host_guard_rejects_non_loopback_host(http_server: str) -> None:
    """A request naming a non-loopback Host is refused before any MCP framing.

    Plain `urllib`, not the MCP client: the guard (`server._LoopbackGuard`)
    sits in front of the SDK's own routing, so this proves it fires on the
    raw socket rather than trusting the client library to send a compliant
    Host header.
    """
    request = urllib.request.Request(
        url=http_server,
        data=b"{}",
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "Host": "evil.example.com",
        },
    )
    try:
        with urllib.request.urlopen(request) as response:
            status, body = response.status, response.read()
    except urllib.error.HTTPError as exc:
        status, body = exc.code, exc.read()
    assert status == 403
    assert b"loopback" in body


def test_http_confinement_holds(tmp_path: Path) -> None:
    """A server bound with `-C` refuses a call naming a different project,
    over HTTP exactly as it does over stdio (`test_a_bound_server_refuses_another_project`)."""
    project, other = tmp_path / "proj", tmp_path / "other"
    ops.init(str(project))
    ops.init(str(other))

    async def escape(session: ClientSession) -> str:
        return await _refused(session, "cue_ls", path=str(other))

    async def own(session: ClientSession) -> Any:
        return await Client(session).call("cue_ls", path=str(project))

    proc, url = _start_http(project)
    try:
        message = anyio.run(_with_http_server, escape, url)
        assert str(project) in message and str(other) in message

        # And the ordinary case — this project, or a relative path resolved
        # against it — still works over the same bound server.
        result = anyio.run(_with_http_server, own, url)
        assert result == {"cues": [], "count": 0}
    finally:
        _stop(proc)


def test_http_refuses_non_loopback_host_without_allow_remote(tmp_path: Path) -> None:
    """`--host` off loopback is refused at startup unless `--allow-remote`
    is also given — the explicit opt-in CLAUDE.md asks for."""
    args = [
        sys.executable,
        "-m",
        "lucid.cli",
        "mcp",
        "--transport",
        "http",
        "--host",
        "0.0.0.0",
        "--port",
        "0",
    ]
    proc = subprocess.Popen(
        args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )
    try:
        return_code = proc.wait(timeout=15)
        stderr = proc.stderr.read() if proc.stderr else ""
        assert return_code == 1
        assert "allow_remote" in stderr or "allow-remote" in stderr
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)


def test_http_refuses_wildcard_bind_without_allow_remote_hosts(tmp_path: Path) -> None:
    """`--host 0.0.0.0 --allow-remote` alone is refused at startup: the
    wildcard address is never a client-presentable identity, so there is
    nothing honest to widen the Host guard with. `--allow-remote-host` names
    what a real client will actually send."""
    args = [
        sys.executable,
        "-m",
        "lucid.cli",
        "mcp",
        "--transport",
        "http",
        "--host",
        "0.0.0.0",
        "--port",
        "0",
        "--allow-remote",
    ]
    proc = subprocess.Popen(
        args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )
    try:
        return_code = proc.wait(timeout=15)
        stderr = proc.stderr.read() if proc.stderr else ""
        assert return_code == 1
        assert "allow_remote_hosts" in stderr or "allow-remote-host" in stderr
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)


def test_http_allow_remote_host_admits_named_host_not_the_wildcard(tmp_path: Path) -> None:
    """A wildcard bind with `--allow-remote-host NAME` admits a request naming
    that host — the address a real remote client would actually send — while
    still refusing the literal wildcard string itself (what only a spoofed
    `Host:` header, never a real client, would contain) and any other name."""
    proc, url = _start_http(
        None,
        "--host",
        "0.0.0.0",
        "--allow-remote",
        "--allow-remote-host",
        "192.168.1.50",
    )
    try:

        def _status(host_header: str) -> int:
            request = urllib.request.Request(
                url=url,
                data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"}).encode(),
                method="POST",
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json, text/event-stream",
                    "Host": host_header,
                },
            )
            try:
                with urllib.request.urlopen(request) as response:
                    return response.status
            except urllib.error.HTTPError as exc:
                return exc.code

        # the address a real remote client would present is admitted
        assert _status("192.168.1.50") != 403
        # the bind-side wildcard itself is never added — the whole point
        assert _status("0.0.0.0") == 403
        # an unrelated name is still refused
        assert _status("evil.example.com") == 403
    finally:
        _stop(proc)


def test_http_allow_remote_widens_the_guard_to_the_bound_host(tmp_path: Path) -> None:
    """`--allow-remote` does not disable the Host guard — it widens the
    allow-list to the bound host, and only that host."""
    proc, url = _start_http(None, "--host", "127.0.0.1", "--allow-remote")
    try:
        # loopback still works
        request = urllib.request.Request(
            url=url,
            data=json.dumps(
                {"jsonrpc": "2.0", "id": 1, "method": "ping"}
            ).encode(),
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
            },
        )
        try:
            with urllib.request.urlopen(request) as response:
                status = response.status
        except urllib.error.HTTPError as exc:
            status = exc.code
        assert status != 403

        # a name unrelated to loopback OR the bound host is still refused
        request = urllib.request.Request(
            url=url,
            data=b"{}",
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
                "Host": "evil.example.com",
            },
        )
        try:
            with urllib.request.urlopen(request) as response:
                status = response.status
        except urllib.error.HTTPError as exc:
            status = exc.code
        assert status == 403
    finally:
        _stop(proc)
