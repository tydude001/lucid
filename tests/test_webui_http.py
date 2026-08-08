"""The web UI, exercised over a real socket.

The same discipline `test_server_stdio.py` applies to MCP: a handler function
called directly proves nothing about whether it is routed, whether Range works,
or whether the guards that make a localhost mutating server safe actually fire.
So these start the real `ThreadingHTTPServer` and speak HTTP to it.
"""

from __future__ import annotations

import http.client
import json
import math
import shlex
import shutil
import struct
import threading
import time
import urllib.error
import urllib.request
import wave
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import pytest

from lucid import ops, webui

needs_ffprobe = pytest.mark.skipif(
    shutil.which("ffprobe") is None, reason="ffprobe is not installed"
)

pytestmark = needs_ffprobe


def _make_wav(path: Path, *, duration: float = 12.0) -> None:
    rate = 22050
    with wave.open(str(path), "w") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        frames = bytearray()
        for i in range(int(rate * duration)):
            value = int(12000 * math.sin(2 * math.pi * 220 * (i / rate)))
            frames += struct.pack("<h", value)
        out.writeframes(bytes(frames))


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """A one-clip project: 12s of audio, eight words, no silence pass.

    `remove_silences=False` on purpose — a seeded-with-silences timeline would
    drag auto-editor into a test about HTTP. The cuts these tests make are what
    produce the seams.
    """
    root = tmp_path / "proj"
    audio = tmp_path / "vo.wav"
    _make_wav(audio)

    words = [{"word": f"w{n}", "start": float(n), "end": n + 0.9} for n in range(8)]
    transcript = tmp_path / "vo.json"
    transcript.write_text(json.dumps({"language": "en", "words": words}), encoding="utf-8")

    ops.init(root)
    imported = ops.import_media(root, audio, clip_id="vo")
    ops.attach_transcript(root, imported["clip_id"], transcript)
    ops.seed_timeline(root, "vo", remove_silences=False)
    return root


@pytest.fixture
def server(project: Path) -> Iterator[str]:
    """The real server on a free port, torn down after the test."""
    httpd = webui.make_server(project, port=0)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}"
    finally:
        httpd.shutdown()
        httpd.server_close()
        httpd.agent.close()
        thread.join(timeout=5)


def _get(url: str, **kwargs: Any) -> tuple[int, dict[str, str], bytes]:
    request = urllib.request.Request(url, **kwargs)
    try:
        with urllib.request.urlopen(request) as response:
            return response.status, dict(response.headers), response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers), exc.read()


def _json(url: str, **kwargs: Any) -> tuple[int, Any]:
    status, _, body = _get(url, **kwargs)
    return status, json.loads(body)


def _post(url: str, payload: dict[str, Any], *, content_type: str = "application/json") -> tuple[int, Any]:
    return _json(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": content_type},
        method="POST",
    )


def _host_and_port(server: str) -> tuple[str, int]:
    parts = urlsplit(server)
    assert parts.hostname is not None
    assert parts.port is not None
    return parts.hostname, parts.port


def _sse_events(resp: http.client.HTTPResponse) -> Iterator[tuple[str, Any]]:
    """Yield `(event, data)` pairs off an open `/api/events` connection.

    Reads raw lines off the still-open socket rather than `resp.read()`,
    which would block until the connection closes — exactly what an SSE
    stream never does on its own.
    """
    event = "message"
    while True:
        raw = resp.readline()
        if not raw:
            return
        line = raw.decode("utf-8").rstrip("\n")
        if line == "":
            continue
        if line.startswith("event:"):
            event = line[len("event:") :].strip()
        elif line.startswith("data:"):
            data = json.loads(line[len("data:") :].strip())
            yield event, data
            event = "message"


def _write_agent_stub(path: Path, argv_file: Path, canned: dict[str, Any]) -> None:
    """A fake `claude` binary: records its own argv, echoes one stream-json line.

    Blocks reading stdin afterwards so the process stays alive the way the
    real subprocess would, rather than exiting and racing the reader thread.
    """
    script = (
        "#!/usr/bin/env bash\n"
        f"printf '%s\\n' \"$@\" > {shlex.quote(str(argv_file))}\n"
        f"echo {shlex.quote(json.dumps(canned))}\n"
        "cat > /dev/null\n"
    )
    path.write_text(script, encoding="utf-8")
    path.chmod(0o755)


# -- the read model -------------------------------------------------------


def test_view_reports_segments_and_no_seams_before_a_cut(server: str) -> None:
    status, payload = _json(f"{server}/api/view")
    assert status == 200
    assert payload["clip_id"] == "vo"
    assert len(payload["segments"]) == 1
    assert payload["seams"] == []
    assert payload["segments"][0]["timeline_start"] == pytest.approx(0.0)
    assert len(payload["words"]) == 8
    assert all(word["present"] for word in payload["words"])


def test_a_cut_names_its_seam_by_the_words_either_side(server: str) -> None:
    status, _ = _post(f"{server}/api/cut", {"clip_id": "vo", "ranges": [[3, 4]], "mode": "cut"})
    assert status == 200

    _, payload = _json(f"{server}/api/view")
    assert len(payload["seams"]) == 1
    seam = payload["seams"][0]
    # The property the whole project defends: the boundary is named by words,
    # not by the timeline second it currently happens to sit at.
    assert seam["before"]["index"] == 2
    assert seam["after"]["index"] == 5
    assert seam["removed"] == pytest.approx(1.9)  # words 3 and 4: 3.0 -> 4.9


def test_cut_words_report_present_false_and_no_timeline_position(server: str) -> None:
    _post(f"{server}/api/cut", {"clip_id": "vo", "ranges": [[3, 4]], "mode": "cut"})
    _, payload = _json(f"{server}/api/view")
    words = {w["index"]: w for w in payload["words"]}

    assert words[3]["present"] is False
    assert words[3]["timeline_start"] is None
    assert words[4]["present"] is False
    # And the words after the hole moved earlier, which is what a view drawn
    # off the transcript instead of the edit would get wrong.
    assert words[5]["present"] is True
    assert words[5]["timeline_start"] == pytest.approx(5.0 - 1.9)


def test_a_word_a_cut_only_half_removes_is_reported_partial(server: str) -> None:
    # Cut by time, straight through the middle of word 3 (3.0-3.9).
    status, _ = _post(f"{server}/api/cut-at", {"spans": [[3.5, 4.5]]})
    assert status == 200

    _, payload = _json(f"{server}/api/view")
    word = next(w for w in payload["words"] if w["index"] == 3)
    # Survival is an overlap test, never containment (CLAUDE.md) — half a word
    # left is present, and saying so is the point.
    assert word["present"] is True
    assert word["partial"] is True
    assert word["covered"] == pytest.approx(0.5)


def test_view_of_a_clip_without_a_transcript_still_draws_the_edit(
    project: Path, server: str, tmp_path: Path
) -> None:
    other = tmp_path / "b.wav"
    _make_wav(other, duration=3.0)
    ops.import_media(project, other, clip_id="b")

    _, payload = _json(f"{server}/api/view?clip_id=b")
    assert payload["words"] is None
    assert payload["transcript_missing"] is True
    assert payload["segments"]  # the timeline is still there to look at


# -- plan, apply, undo ----------------------------------------------------


def test_plan_reports_the_real_numbers_and_writes_nothing(server: str) -> None:
    _, before = _json(f"{server}/api/view")

    status, plan = _post(
        f"{server}/api/cut",
        {"clip_id": "vo", "ranges": [[3, 4]], "mode": "cut", "plan": True},
    )
    assert status == 200
    assert plan["plan"] is True
    assert plan["removed"] == pytest.approx(1.9)
    # The echo is what makes an off-by-one visible, so it has to survive the
    # trip through HTTP rather than be a CLI-only nicety.
    assert plan["applied"][0]["text"] == "w3 w4"
    assert [w["index"] for w in plan["applied"][0]["context_before"]] == [0, 1, 2]

    _, after = _json(f"{server}/api/view")
    assert after["timeline_duration"] == pytest.approx(before["timeline_duration"])
    assert after["undo_depth"] == before["undo_depth"]


def test_apply_then_undo_returns_the_timeline_and_the_words(server: str) -> None:
    _, before = _json(f"{server}/api/view")

    _post(f"{server}/api/cut", {"clip_id": "vo", "ranges": [[3, 4]], "mode": "cut"})
    _, cut = _json(f"{server}/api/view")
    assert cut["undo_depth"] == 1
    assert cut["timeline_duration"] < before["timeline_duration"]

    status, undone = _post(f"{server}/api/undo", {})
    assert status == 200
    assert undone["undo_depth"] == 0

    _, restored = _json(f"{server}/api/view")
    assert restored["timeline_duration"] == pytest.approx(before["timeline_duration"])
    assert all(word["present"] for word in restored["words"])


def test_keep_only_goes_through_the_same_endpoint(server: str) -> None:
    status, payload = _post(
        f"{server}/api/cut", {"clip_id": "vo", "ranges": [[2, 3]], "mode": "keep"}
    )
    assert status == 200
    assert payload["mode"] == "keep"

    _, view = _json(f"{server}/api/view")
    kept = [w["index"] for w in view["words"] if w["present"]]
    assert kept == [2, 3]


def test_a_refused_cut_comes_back_as_a_message_not_a_traceback(server: str) -> None:
    status, payload = _post(
        f"{server}/api/cut", {"clip_id": "vo", "ranges": [[99, 99]], "mode": "cut"}
    )
    assert status == 400
    assert "error" in payload
    assert "99" in payload["error"]


def test_bad_request_shapes_are_refused_before_reaching_ops(server: str) -> None:
    for body in (
        {"clip_id": "vo", "mode": "cut"},
        {"clip_id": "vo", "ranges": [], "mode": "cut"},
        {"clip_id": "vo", "ranges": [[1]], "mode": "cut"},
        {"ranges": [[1, 2]], "mode": "cut"},
        {"clip_id": "vo", "ranges": [[1, 2]], "mode": "sideways"},
    ):
        status, payload = _post(f"{server}/api/cut", body)
        assert status == 400, body
        assert "error" in payload


# -- media, and the Range support a browser needs to seek -----------------


def test_media_serves_the_whole_file_and_advertises_ranges(project: Path, server: str) -> None:
    status, headers, body = _get(f"{server}/api/media/vo")
    assert status == 200
    assert headers["Accept-Ranges"] == "bytes"
    assert len(body) == (project / "media" / "vo.wav").stat().st_size


def test_a_range_request_returns_206_and_exactly_those_bytes(project: Path, server: str) -> None:
    whole = (project / "media" / "vo.wav").read_bytes()

    status, headers, body = _get(f"{server}/api/media/vo", headers={"Range": "bytes=100-199"})
    assert status == 206
    assert headers["Content-Range"] == f"bytes 100-199/{len(whole)}"
    assert body == whole[100:200]


def test_an_open_ended_range_runs_to_the_end_of_the_file(project: Path, server: str) -> None:
    whole = (project / "media" / "vo.wav").read_bytes()
    size = len(whole)

    status, headers, body = _get(f"{server}/api/media/vo", headers={"Range": f"bytes={size - 50}-"})
    assert status == 206
    assert headers["Content-Range"] == f"bytes {size - 50}-{size - 1}/{size}"
    assert body == whole[-50:]


def test_a_suffix_range_returns_the_tail(project: Path, server: str) -> None:
    whole = (project / "media" / "vo.wav").read_bytes()
    status, _, body = _get(f"{server}/api/media/vo", headers={"Range": "bytes=-50"})
    assert status == 206
    assert body == whole[-50:]


def test_an_unsatisfiable_range_is_refused_rather_than_served_wrong(server: str) -> None:
    status, payload = _json(f"{server}/api/media/vo", headers={"Range": "bytes=999999999-"})
    assert status == 400
    assert "error" in payload


def test_head_on_media_answers_without_a_body(server: str) -> None:
    status, headers, body = _get(f"{server}/api/media/vo", method="HEAD")
    assert status == 200
    assert int(headers["Content-Length"]) > 0
    assert body == b""


def test_an_unknown_clip_is_a_message_not_a_crash(server: str) -> None:
    status, payload = _json(f"{server}/api/media/nope")
    assert status == 400
    assert "nope" in payload["error"]


# -- waveform ---------------------------------------------------------------


def test_waveform_matches_the_ops_contract(project: Path, server: str) -> None:
    status, payload = _json(f"{server}/api/waveform/vo")
    assert status == 200
    assert payload["clip_id"] == "vo"
    assert payload["frame_ms"] == 20
    assert isinstance(payload["rms"], list)
    assert payload["rms"]
    assert all(isinstance(v, int) and 0 <= v <= 255 for v in payload["rms"])
    assert payload["duration_s"] == pytest.approx(12.0, abs=0.1)


def test_waveform_on_an_unknown_clip_is_a_message_not_a_crash(server: str) -> None:
    status, payload = _json(f"{server}/api/waveform/nope")
    assert status == 400
    assert "nope" in payload["error"]


# -- the guards -----------------------------------------------------------


def test_a_non_loopback_host_header_is_refused(server: str) -> None:
    # What a DNS-rebinding page looks like from here: the socket is loopback,
    # but the name the browser thinks it reached is not.
    status, payload = _json(f"{server}/api/view", headers={"Host": "evil.example.com"})
    assert status == 403
    assert "loopback" in payload["error"]


def test_a_mutating_request_must_be_json(server: str) -> None:
    # An HTML form can only send these three, which is exactly why requiring
    # application/json is what stops a cross-origin POST.
    for ctype in ("application/x-www-form-urlencoded", "text/plain", "multipart/form-data"):
        status, payload = _post(
            f"{server}/api/cut",
            {"clip_id": "vo", "ranges": [[0, 1]], "mode": "cut"},
            content_type=ctype,
        )
        assert status == 400, ctype
        assert "application/json" in payload["error"]

    _, view = _json(f"{server}/api/view")
    assert view["undo_depth"] == 0  # nothing got through


def test_a_non_loopback_host_cannot_mutate_either(server: str) -> None:
    status, _ = _post(f"{server}/api/undo", {})  # nothing to undo, but routed
    assert status == 400

    request = urllib.request.Request(
        f"{server}/api/cut",
        data=b"{}",
        headers={"Content-Type": "application/json", "Host": "evil.example.com"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request) as response:
            code = response.status
    except urllib.error.HTTPError as exc:
        code = exc.code
    assert code == 403


# -- static assets --------------------------------------------------------


def test_the_page_and_its_assets_are_served_from_the_package(server: str) -> None:
    status, headers, body = _get(f"{server}/")
    assert status == 200
    assert headers["Content-Type"].startswith("text/html")
    assert b'src="/static/app.js"' in body

    for asset, prefix in (("app.js", "text/javascript"), ("app.css", "text/css")):
        status, headers, body = _get(f"{server}/static/{asset}")
        assert status == 200, asset
        assert headers["Content-Type"].startswith(prefix)
        assert body


def test_static_serving_refuses_a_path_rather_than_a_name(server: str) -> None:
    for name in ("..%2f..%2fpyproject.toml", "%2eenv", "nope.js", "index.html%00"):
        status, _ = _json(f"{server}/static/{name}")
        assert status == 404, name


def test_an_unknown_endpoint_is_a_404_with_a_message(server: str) -> None:
    status, payload = _json(f"{server}/api/nothing")
    assert status == 404
    assert "error" in payload


# -- /api/events, the SSE stream -------------------------------------------


def test_events_stream_is_text_event_stream_and_starts_with_the_revision(server: str) -> None:
    host, port = _host_and_port(server)
    conn = http.client.HTTPConnection(host, port, timeout=5)
    try:
        conn.request("GET", "/api/events")
        resp = conn.getresponse()
        assert resp.status == 200
        assert (resp.getheader("Content-Type") or "").startswith("text/event-stream")

        event, data = next(_sse_events(resp))
        assert event == "project-changed"
        assert "revision" in data
    finally:
        conn.close()


def test_events_stream_reports_project_changed_after_a_mutation(server: str) -> None:
    host, port = _host_and_port(server)
    conn = http.client.HTTPConnection(host, port, timeout=5)
    try:
        conn.request("GET", "/api/events")
        resp = conn.getresponse()
        events = _sse_events(resp)
        _, first = next(events)
        first_revision = first["revision"]

        status, _ = _post(
            f"{server}/api/cut", {"clip_id": "vo", "ranges": [[3, 4]], "mode": "cut"}
        )
        assert status == 200

        for event, data in events:
            if event == "project-changed" and data["revision"] != first_revision:
                break
        else:
            pytest.fail("no project-changed event followed the mutation")
    finally:
        conn.close()


def test_events_endpoint_rejects_a_bad_host(server: str) -> None:
    status, payload = _json(f"{server}/api/events", headers={"Host": "evil.example.com"})
    assert status == 403
    assert "loopback" in payload["error"]


# -- the agent subprocess ---------------------------------------------------


def test_agent_endpoints_reject_a_bad_host(server: str) -> None:
    for path in ("/api/agent", "/api/agent/stop"):
        request = urllib.request.Request(
            f"{server}{path}",
            data=b"{}",
            headers={"Content-Type": "application/json", "Host": "evil.example.com"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request) as response:
                code = response.status
        except urllib.error.HTTPError as exc:
            code = exc.code
        assert code == 403, path


def test_agent_endpoints_require_json_content_type(server: str) -> None:
    for path in ("/api/agent", "/api/agent/stop"):
        status, payload = _post(f"{server}{path}", {"prompt": "hi"}, content_type="text/plain")
        assert status == 400, path
        assert "application/json" in payload["error"]

    # Missing entirely, not just wrong, is refused the same way.
    request = urllib.request.Request(
        f"{server}/api/agent", data=b"{}", method="POST"
    )
    try:
        with urllib.request.urlopen(request) as response:
            code = response.status
    except urllib.error.HTTPError as exc:
        code = exc.code
    assert code == 400


def test_agent_prompt_requires_a_prompt(server: str) -> None:
    status, payload = _post(f"{server}/api/agent", {})
    assert status == 400
    assert "prompt" in payload["error"]


def test_agent_prompt_spawns_with_the_allowlist_and_streams_the_canned_event(
    server: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The one end-to-end check: a stubbed `claude` records its own argv and
    echoes a canned `stream-json` line, which must come back out as an
    `agent` event on `/api/events` — proving the spawn, the allowlist, and
    the bus all actually connect rather than merely existing side by side.
    """
    argv_file = tmp_path / "argv.txt"
    canned = {"type": "assistant", "message": {"content": [{"type": "text", "text": "hi"}]}}
    stub = tmp_path / "agent-stub.sh"
    _write_agent_stub(stub, argv_file, canned)
    monkeypatch.setenv(webui.AGENT_BIN_ENV, str(stub))

    host, port = _host_and_port(server)
    conn = http.client.HTTPConnection(host, port, timeout=5)
    try:
        conn.request("GET", "/api/events")
        resp = conn.getresponse()
        events = _sse_events(resp)
        next(events)  # the initial project-changed

        status, payload = _post(f"{server}/api/agent", {"prompt": "cut the retake"})
        assert status == 202
        assert payload["accepted"] is True

        found = None
        for event, data in events:
            if event == "agent":
                found = data
                break
        assert found == canned
    finally:
        conn.close()

    argv = argv_file.read_text(encoding="utf-8").splitlines()
    assert "--strict-mcp-config" in argv
    assert "mcp__lucid__*" in argv
    assert "--permission-mode" in argv
    assert argv[argv.index("--permission-mode") + 1] == "manual"
    for tool in ("Bash", "Write", "Edit", "WebFetch", "WebSearch"):
        assert tool in argv
    # --verbose: claude 2.1.226 refuses --print --output-format=stream-json
    # without it (errors and exits 0 with nothing on stdout) — see
    # PLAN.md § The agent panel, in mechanism.
    assert "--verbose" in argv
    # --tools '': the allow/disallow lists alone do not gate built-in tools
    # absent from both — this is what actually confines the agent to lucid's
    # MCP tools and nothing else. Same PLAN.md section.
    assert "--tools" in argv
    assert argv[argv.index("--tools") + 1] == ""


def _write_silent_agent_stub(path: Path) -> None:
    """A fake `claude` that reproduces the real bug this test guards against:
    it errors to stderr and exits 0 without ever writing a `stream-json` line
    to stdout — exactly what claude 2.1.226 does when `--verbose` is missing
    from a `--print --output-format=stream-json` invocation.
    """
    script = "#!/usr/bin/env bash\necho 'Error: boom, no --verbose' >&2\nexit 0\n"
    path.write_text(script, encoding="utf-8")
    path.chmod(0o755)


def test_a_silent_agent_exit_still_surfaces_as_a_result_event(
    server: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A subprocess that exits without ever printing a `stream-json` line
    must not leave the page's composer hung on `busy` forever with nothing on
    `/api/events` to clear it — the failure mode a real `claude` upgrade
    silently produced. A synthetic `result` event with a non-"success"
    subtype is what `agent.js`'s `handleResult` needs to show an error and
    clear `busy`.
    """
    stub = tmp_path / "silent-agent-stub.sh"
    _write_silent_agent_stub(stub)
    monkeypatch.setenv(webui.AGENT_BIN_ENV, str(stub))

    host, port = _host_and_port(server)
    conn = http.client.HTTPConnection(host, port, timeout=5)
    try:
        conn.request("GET", "/api/events")
        resp = conn.getresponse()
        events = _sse_events(resp)
        next(events)  # the initial project-changed

        status, payload = _post(f"{server}/api/agent", {"prompt": "cut the retake"})
        assert status == 202
        assert payload["accepted"] is True

        found = None
        for event, data in events:
            if event == "agent":
                found = data
                break
        assert found is not None
        assert found["type"] == "result"
        assert found["subtype"] != "success"
        assert "boom" in found["result"]
    finally:
        conn.close()


def test_a_failed_agent_spawn_is_a_json_error_not_a_reset(
    server: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A binary that cannot spawn at all (`claude` missing from PATH, a dead
    LUCID_AGENT_BIN) puts nothing on `/api/events` — so the composer's only
    way to hear about it is this request failing as JSON rather than the
    connection resetting on an uncaught server-side traceback.
    """
    monkeypatch.setenv(webui.AGENT_BIN_ENV, str(tmp_path / "no-such-binary"))
    status, payload = _post(f"{server}/api/agent", {"prompt": "cut the retake"})
    assert status == 500
    assert "could not start the agent" in payload["error"]


def test_agent_stop_with_no_subprocess_running_is_a_no_op(server: str) -> None:
    status, payload = _post(f"{server}/api/agent/stop", {})
    assert status == 200
    assert payload["stopped"] is True


# -- render jobs -------------------------------------------------------------
#
# `ops.export` is monkeypatched to a stub that writes a tiny real WAV instead
# of shelling out to auto-editor (PLAN.md § Finishing; the task's own
# guidance for this test style) — these exercise the job model's plumbing,
# not a real render. `ops.verify` is separately stubbed where a completion
# payload's shape is asserted, so the test does not depend on whisper being
# on this machine's PATH; where it is *not* stubbed, the real absence of
# whisper (CLAUDE.md) drives the honest `verify: skipped` path for free.


def _fast_export_stub(
    path: str, output: str, *, export_format: str | None = None, fps: float | None = None
) -> dict[str, Any]:
    _make_wav(Path(output), duration=0.3)
    return {
        "output": output,
        "format": "media",
        "timebase": 1000.0,
        "segments": 1,
        "timeline_duration": 0.3,
    }


def _render_output_path(project: Path, job_id: str) -> Path:
    # RenderJob._output_path: `web-<job_id><suffix>` under renders/, where the
    # suffix follows the fixture's one clip, vo.wav.
    return project / "renders" / f"web-{job_id}.wav"


def _next_render_event(events: Iterator[tuple[str, Any]], job_id: str) -> dict[str, Any]:
    """The first non-`running` `render` event for `job_id` off an open stream."""
    for event, data in events:
        if event == "render" and data.get("job_id") == job_id and data.get("status") != "running":
            return data
    raise AssertionError(f"no completion event arrived for render {job_id}")


def test_render_accepted_returns_a_job_id(server: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ops, "export", _fast_export_stub)
    status, payload = _post(f"{server}/api/render", {})
    assert status == 202
    assert isinstance(payload["job_id"], str) and payload["job_id"]


def test_a_second_render_while_one_is_running_is_refused(
    server: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    gate = threading.Event()

    def _stub(
        path: str, output: str, *, export_format: str | None = None, fps: float | None = None
    ) -> dict[str, Any]:
        _make_wav(Path(output), duration=0.2)
        gate.wait(timeout=5)
        return {"output": output, "format": "media", "timebase": 1000.0}

    monkeypatch.setattr(ops, "export", _stub)
    try:
        status, _ = _post(f"{server}/api/render", {})
        assert status == 202

        status, payload = _post(f"{server}/api/render", {})
        assert status == 409
        assert "error" in payload
    finally:
        gate.set()


def test_render_stop_deletes_the_partial_output_and_reports_cancelled(
    server: str, project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    gate = threading.Event()

    def _stub(
        path: str, output: str, *, export_format: str | None = None, fps: float | None = None
    ) -> dict[str, Any]:
        _make_wav(Path(output), duration=0.2)
        gate.wait(timeout=5)
        return {"output": output, "format": "media", "timebase": 1000.0}

    monkeypatch.setattr(ops, "export", _stub)

    host, port = _host_and_port(server)
    conn = http.client.HTTPConnection(host, port, timeout=5)
    try:
        conn.request("GET", "/api/events")
        resp = conn.getresponse()
        events = _sse_events(resp)
        next(events)  # the initial project-changed

        status, payload = _post(f"{server}/api/render", {})
        assert status == 202
        job_id = payload["job_id"]
        output = _render_output_path(project, job_id)

        deadline = time.monotonic() + 5
        while not output.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert output.exists(), "the stub never wrote its partial output"

        status, _ = _post(f"{server}/api/render/stop", {})
        assert status == 200

        # Deleted the instant `stop` answers, not merely once the background
        # export call eventually notices the cancellation (PLAN.md line 1832:
        # the partial output is deleted, not left).
        assert not output.exists()

        gate.set()
        found = _next_render_event(events, job_id)
        assert found["status"] == "cancelled"
        assert not output.exists()
    finally:
        gate.set()
        conn.close()


def test_render_completion_event_carries_dimensions_and_check_results(
    server: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ops, "export", _fast_export_stub)
    monkeypatch.setattr(ops, "verify", lambda *a, **k: {"agrees": True, "stub": True})

    host, port = _host_and_port(server)
    conn = http.client.HTTPConnection(host, port, timeout=5)
    try:
        conn.request("GET", "/api/events")
        resp = conn.getresponse()
        events = _sse_events(resp)
        next(events)  # the initial project-changed

        status, payload = _post(f"{server}/api/render", {})
        assert status == 202
        job_id = payload["job_id"]

        found = _next_render_event(events, job_id)
        assert found["status"] == "done"
        assert Path(found["output"]).exists()
        # (a) honesty: these are ffprobe's own read of the file that landed on
        # disk, not auto-editor's exit code.
        assert found["has_video"] is False
        assert found["has_audio"] is True
        assert found["duration"] == pytest.approx(0.3, abs=0.05)

        # (b) the completion card is where the existing checks land.
        checks = found["checks"]
        assert checks["verify"] == {"agrees": True, "stub": True}
        for name in ("check_frames", "check_black", "spot_frames"):
            assert checks[name]["skipped"] is True
            assert "video" in checks[name]["reason"]
    finally:
        conn.close()


def test_render_endpoints_reject_a_bad_host(server: str) -> None:
    for path in ("/api/render", "/api/render/stop"):
        request = urllib.request.Request(
            f"{server}{path}",
            data=b"{}",
            headers={"Content-Type": "application/json", "Host": "evil.example.com"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request) as response:
                code = response.status
        except urllib.error.HTTPError as exc:
            code = exc.code
        assert code == 403, path


def test_render_endpoints_require_json_content_type(server: str) -> None:
    for path in ("/api/render", "/api/render/stop"):
        status, payload = _post(f"{server}{path}", {}, content_type="text/plain")
        assert status == 400, path
        assert "application/json" in payload["error"]


def test_render_stop_with_no_job_running_is_a_no_op(server: str) -> None:
    status, payload = _post(f"{server}/api/render/stop", {})
    assert status == 200
    assert payload["stopped"] is True


def test_render_on_an_empty_timeline_is_refused_before_a_job_starts(
    project: Path, server: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # `ops.undo` empties the seeded timeline back to nothing to import; simpler
    # to point the render at a project whose timeline was never seeded.
    empty = project.parent / "empty-proj"
    ops.init(empty)
    httpd = webui.make_server(empty, port=0)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        status, payload = _post(f"http://127.0.0.1:{httpd.server_address[1]}/api/render", {})
        assert status == 400
        assert "error" in payload
    finally:
        httpd.shutdown()
        httpd.server_close()
        httpd.agent.close()
        thread.join(timeout=5)
