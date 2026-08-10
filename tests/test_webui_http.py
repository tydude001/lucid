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
import re
import shlex
import shutil
import struct
import subprocess
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
from lucid import timeline as tl
from lucid.project import Project

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


def _write_pid_recording_stub(path: Path, pid_file: Path, canned: dict[str, Any]) -> None:
    """Same shape as `_write_agent_stub`, plus its own PID appended to
    `pid_file` on every invocation — proves a respawn is a genuinely new
    process rather than the same one reused.
    """
    script = (
        "#!/usr/bin/env bash\n"
        f'echo "$$" >> {shlex.quote(str(pid_file))}\n'
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


def test_the_picture_lane_reaches_the_page_over_http(project: Path, server: str) -> None:
    """Step 6: what the V2 lane is drawn from has to survive the trip, and it
    is a planned shot list rather than a raw projection — `src_in` is the
    field only `mlt.plan_picture` can produce, and the lane's tooltip is the
    one place a re-used clip's cursor is visible."""
    _, before = _json(f"{server}/api/view")
    assert before["shots"] is None  # no cues, so no picture lane exists to draw

    # Cues are added by the CLI, MCP or the agent panel — the page draws the
    # lane, it does not author it — so this arrives from outside the server,
    # the same way the untranscribed clip above does.
    Project.open(project).cards_dir.joinpath("outro.png").write_bytes(b"\x89PNG")
    ops.cue_add(project, "vo", 2, "card:outro")

    _, payload = _json(f"{server}/api/view")
    assert payload["layered"] is True
    assert payload["shots_rate"] == 30.0
    assert len(payload["shots"]) == 1
    shot = payload["shots"][0]
    assert shot["asset"] == "card:outro"
    assert shot["is_image"] is True
    assert shot["src_in"] == 0
    # The first shot covers from the open, whatever word its cue names.
    assert shot["start"] == pytest.approx(0.0)
    assert shot["word_index"] == 2


def _make_broll(root: Path, *, duration: float) -> Path:
    """A real encoded clip for the picture lane to point at. Real, because
    `_resolve_asset` reads the registered duration off a probe and the pin is
    checked against it."""
    broll = root / "broll.mp4"
    subprocess.run(
        [
            "ffmpeg", "-y", "-loglevel", "error",
            "-f", "lavfi", "-i", f"testsrc=size=160x120:rate=30:duration={duration}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(broll),
        ],
        check=True,
        capture_output=True,
    )  # fmt: skip
    return broll


def test_a_pinned_cue_reaches_the_lane_with_the_moment_it_names(
    project: Path, server: str
) -> None:
    """The b-roll placement, drawn. `src_pin` is what the cue asked for and
    `src_start` is where the planner says the shot reads — the page needs both,
    because the preview layer seeks to `src_start` and a viewer who cannot see
    that the two agree has no way to tell a placement from a re-use.
    """
    broll = _make_broll(project.parent, duration=8.0)
    ops.import_media(project, broll, clip_id="broll")
    Project.open(project).cards_dir.joinpath("outro.png").write_bytes(b"\x89PNG")
    ops.cue_add(project, "vo", 0, "broll", src_start=2.0)
    ops.cue_add(project, "vo", 4, "card:outro")

    status, payload = _json(f"{server}/api/view")

    assert status == 200
    shots = payload["shots"]
    assert shots[0]["asset"] == "broll"
    assert shots[0]["src_pin"] == 2.0
    assert shots[0]["src_start"] == pytest.approx(2.0)
    assert shots[0]["src_in"] == 60  # 2.0s on the 30fps export grid
    # A card takes no pin, and says so rather than reporting a number.
    assert shots[1]["src_pin"] is None


def test_the_frame_reaches_the_page_with_the_render_s_own_placement(
    project: Path, server: str
) -> None:
    """Step 4 of the aspect swap, over the wire. The page draws #frame at
    `canvas` and places media at `reframe[clip].dest`, so both have to survive
    the trip — and `dest` has to be the *whole source frame's* landing rect,
    which is wider than the canvas and starts left of it whenever the render
    crops. A page given only the crop would have to re-derive that itself.
    """
    broll = _make_broll(project.parent, duration=8.0)  # 160x120, so 4:3
    ops.import_media(project, broll, clip_id="broll")
    ops.canvas(project, size="1080x1920")

    status, payload = _json(f"{server}/api/view")

    assert status == 200
    assert payload["canvas"] == [1080, 1920]
    entry = payload["reframe"]["broll"]
    assert entry["source"] == [160, 120]
    assert entry["crops"] is True
    # 9:16 out of 4:3 keeps a 68-wide column of the 160 — centred, and in
    # source pixels, because a rect no edit can invalidate is the whole rule.
    assert entry["crop"] == [46, 0, 68, 120]
    x, y, w, h = entry["dest"]
    assert x < 0 and w > 1080, "the whole frame lands wider than the canvas"
    assert (y, h) == (0, 1920), "filled by height, which is the axis that fits"
    # The audio-only clip has no picture to place, and gets no entry at all.
    assert "vo" not in payload["reframe"]


def test_an_unswapped_project_still_reports_a_frame_to_draw(server: str) -> None:
    """The page has one code path, so the canvas is always answered — here it
    is the audio-only default rather than an absence the front end has to
    guess a shape for."""
    _, payload = _json(f"{server}/api/view")

    assert payload["canvas"] == [1920, 1080]
    assert payload["reframe"] == {}
    assert "reframe_error" not in payload


def test_a_pin_that_runs_off_its_asset_is_drawn_as_a_refusal_not_a_rewind(
    project: Path, server: str
) -> None:
    """The safety property this step adds, over the wire. Unpinned, the same
    shot is drawn from the head of the clip without complaint — so the test
    does both, because the pair is the design: the rewind is right for a
    re-use and would be a lie for a placement.
    """
    broll = _make_broll(project.parent, duration=8.0)
    ops.import_media(project, broll, clip_id="broll")
    Project.open(project).cards_dir.joinpath("outro.png").write_bytes(b"\x89PNG")
    ops.cue_add(project, "vo", 0, "broll", src_start=7.0)  # 4s shot, 1s left in the clip
    ops.cue_add(project, "vo", 4, "card:outro")

    status, payload = _json(f"{server}/api/view")

    assert status == 200
    assert payload["shots"] is None
    assert "a pinned cue shows the moment it names" in payload["shots_error"]
    # Every other lane still answers — the window is how the cue gets fixed.
    assert payload["words"] is not None
    assert payload["segments"]

    ops.cue_rm(project, "vo", 0)
    ops.cue_add(project, "vo", 0, "broll")

    _, redrawn = _json(f"{server}/api/view")
    assert redrawn.get("shots_error") is None
    assert redrawn["shots"][0]["src_in"] == 0


def test_a_cue_the_edit_cuts_away_is_drawn_as_a_refusal_not_a_500(
    project: Path, server: str
) -> None:
    """The safety property, over the wire. A stale cue must not take the view
    down — the window is how a person finds the cue to move, so the picture
    lane comes back empty with the reason attached and every other lane still
    answers."""
    Project.open(project).cards_dir.joinpath("outro.png").write_bytes(b"\x89PNG")
    ops.cue_add(project, "vo", 5, "card:outro")
    _post(f"{server}/api/cut", {"clip_id": "vo", "ranges": [[5, 5]], "mode": "cut"})

    status, payload = _json(f"{server}/api/view")

    assert status == 200
    assert payload["shots"] is None
    assert "was cut from the edit" in payload["shots_error"]
    assert payload["words"] is not None
    assert payload["seams"]


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


def test_restore_undoes_a_cut_over_http(server: str) -> None:
    _, before = _json(f"{server}/api/view")

    status, cut = _post(f"{server}/api/cut", {"clip_id": "vo", "ranges": [[3, 4]], "mode": "cut"})
    assert status == 200
    _, cut_view = _json(f"{server}/api/view")
    assert cut_view["timeline_duration"] < before["timeline_duration"]
    words = {w["index"]: w for w in cut_view["words"]}
    assert words[3]["present"] is False
    assert words[4]["present"] is False

    status, restored = _post(
        f"{server}/api/restore", {"clip_id": "vo", "ranges": [[3, 4]]}
    )
    assert status == 200
    assert restored["applied"][0]["already_present"] is False
    assert restored["restored"] == pytest.approx(cut["removed"], abs=1e-6)

    _, view = _json(f"{server}/api/view")
    assert view["timeline_duration"] == pytest.approx(before["timeline_duration"])
    words = {w["index"]: w for w in view["words"]}
    assert words[3]["present"] is True
    assert words[4]["present"] is True


def test_restore_plan_over_http_does_not_touch_the_timeline(server: str) -> None:
    _post(f"{server}/api/cut", {"clip_id": "vo", "ranges": [[3, 4]], "mode": "cut"})
    _, before_plan = _json(f"{server}/api/view")

    status, planned = _post(
        f"{server}/api/restore", {"clip_id": "vo", "ranges": [[3, 4]], "plan": True}
    )
    assert status == 200
    assert planned["plan"] is True

    _, after_plan = _json(f"{server}/api/view")
    assert after_plan["timeline_duration"] == pytest.approx(before_plan["timeline_duration"])
    assert after_plan["undo_depth"] == before_plan["undo_depth"]


def test_restore_of_a_clip_with_no_material_left_comes_back_as_a_message_not_a_traceback(
    server: str,
) -> None:
    # Cut-at the whole timeline away: no segment of 'vo' survives anywhere.
    _, before = _json(f"{server}/api/view")
    status, _ = _post(f"{server}/api/cut-at", {"spans": [[0.0, before["timeline_duration"]]]})
    assert status == 200
    _, emptied = _json(f"{server}/api/view")
    assert emptied["timeline_duration"] == pytest.approx(0.0)

    status, payload = _post(f"{server}/api/restore", {"clip_id": "vo", "ranges": [[0, 1]]})
    assert status == 400
    assert "error" in payload
    assert "vo" in payload["error"]


def test_api_cut_through_pause_removes_the_trailing_pause(tmp_path: Path) -> None:
    """The shared `project` fixture's words are all 0.1s apart — too tight
    for a marker (CLAUDE.md/DAYDREAM.md's 0.4s threshold) — so this builds
    its own project with one wide gap: words 3 and 4 sit 2.1s apart instead.

    A baseline cut of words 2-3 leaves that 2.1s of dead air playing before
    word 4; `through_pause=True` removes it too, which shows up as word 4
    playing immediately after word 1 instead of 2.1s later.
    """
    root = tmp_path / "proj"
    audio = tmp_path / "vo.wav"
    _make_wav(audio, duration=14.0)

    words = [
        {"word": f"w{n}", "start": n + (2.0 if n >= 4 else 0.0), "end": n + (2.0 if n >= 4 else 0.0) + 0.9}
        for n in range(8)
    ]
    transcript = tmp_path / "vo.json"
    transcript.write_text(json.dumps({"language": "en", "words": words}), encoding="utf-8")

    ops.init(root)
    imported = ops.import_media(root, audio, clip_id="vo")
    ops.attach_transcript(root, imported["clip_id"], transcript)
    ops.seed_timeline(root, "vo", remove_silences=False)

    httpd = webui.make_server(root, port=0)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        server = f"http://127.0.0.1:{httpd.server_address[1]}"

        # Baseline: word 3's own end (3.9s) is where the removed range stops.
        status, baseline = _post(
            f"{server}/api/cut",
            {"clip_id": "vo", "ranges": [[2, 3]], "mode": "cut", "plan": True},
        )
        assert status == 200
        assert baseline["applied"][0]["source_end"] == pytest.approx(3.9)

        # With the flag: the range's trailing edge reaches word 4's own start
        # (6.0s) instead — the pause between them is swallowed by the cut.
        status, flagged = _post(
            f"{server}/api/cut",
            {
                "clip_id": "vo",
                "ranges": [[2, 3]],
                "mode": "cut",
                "through_pause": True,
                "plan": True,
            },
        )
        assert status == 200
        assert flagged["applied"][0]["source_end"] == pytest.approx(6.0)
        assert flagged["applied"][0]["word_end"] == pytest.approx(3.9)

        # Apply it for real and confirm the effect on where word 4 now plays:
        # immediately after word 1's segment (timeline second 2.0), not 2.1s
        # later the way the un-flagged baseline would have left it.
        status, _ = _post(
            f"{server}/api/cut",
            {"clip_id": "vo", "ranges": [[2, 3]], "mode": "cut", "through_pause": True},
        )
        assert status == 200

        _, view = _json(f"{server}/api/view")
        words_by_index = {w["index"]: w for w in view["words"]}
        assert words_by_index[4]["present"] is True
        assert words_by_index[4]["timeline_start"] == pytest.approx(2.0)
    finally:
        httpd.shutdown()
        httpd.server_close()
        httpd.agent.close()
        thread.join(timeout=5)


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


# -- captions ---------------------------------------------------------------
#
# The second read model. It is a separate endpoint from /api/view because it is
# a different derivation of the same edit — placed, grouped and styled — and
# because it moves when the *manifest* moves rather than when the timeline
# does, which is also why `_revision` watches both.


def test_captions_reach_the_page_with_the_style_in_force(server: str) -> None:
    status, payload = _json(f"{server}/api/captions")

    assert status == 200
    assert payload["cues"], "eight words should produce at least one cue"
    assert payload["style"]["resolved"]["preset"] == "clean"
    assert payload["resolution"] == [1920, 1080]
    first = payload["cues"][0]
    assert first["start"] == 0.0
    assert {"start", "end", "text", "words"} <= set(first)


def test_a_caption_word_carries_the_span_its_highlight_runs_over(server: str) -> None:
    """The overlay must not light a word at its own start — a `\\k` duration
    covers the gap before it (captions.Cue.karaoke_spans). The server sends the
    spans so the browser cannot get this rule differently from the burn-in."""
    _, payload = _json(f"{server}/api/captions")
    words = payload["cues"][0]["words"]

    assert words[1]["start"] == 1.0
    assert words[1]["highlight_start"] == pytest.approx(0.9), "when w0 stopped"
    assert words[0]["highlight_start"] == 0.0


def test_the_style_a_restyle_stores_comes_back_on_the_next_fetch(
    project: Path, server: str
) -> None:
    ops.caption_style(project, preset="karaoke", size=80, text="yellow")

    _, payload = _json(f"{server}/api/captions")
    look = payload["style"]["resolved"]

    assert look["size"] == 80
    assert look["karaoke"] is True
    assert look["text"] == "#ffd400ff", "CSS, because the overlay is what draws it"
    assert look["highlight"] != look["text"], "or the word-highlight shows nothing"


def test_captions_follow_a_cut(server: str) -> None:
    """Timeline seconds, not source seconds — the clock the viewer has."""
    _, before = _json(f"{server}/api/captions")
    status, _ = _post(f"{server}/api/cut", {"clip_id": "vo", "ranges": [[0, 0]], "mode": "cut"})
    assert status == 200
    _, after = _json(f"{server}/api/captions")

    assert after["words_cut"] == 1
    assert after["cues"][0]["text"] != before["cues"][0]["text"]
    # w1 was heard at 1.0 and is now heard at 0.1 — the 0.9s w0 occupied is
    # gone from the timeline, so everything after it moved by that much.
    assert after["cues"][0]["start"] == pytest.approx(0.1)


def test_a_restyle_moves_the_revision_so_an_open_window_repaints(
    project: Path, server: str
) -> None:
    """The style lives in the manifest and nothing about it touches
    project.otio, so a revision watching the timeline alone would leave the
    preview overlay drawing the old look until an unrelated edit moved it."""
    host, port = _host_and_port(server)
    conn = http.client.HTTPConnection(host, port, timeout=5)
    try:
        conn.request("GET", "/api/events")
        resp = conn.getresponse()
        events = _sse_events(resp)
        _, first = next(events)

        ops.caption_style(project, size=80)

        for event, data in events:
            if event == "project-changed" and data["revision"] != first["revision"]:
                break
        else:
            pytest.fail("no project-changed event followed the restyle")
    finally:
        conn.close()


# -- the picture layer's assets -------------------------------------------
#
# What the viewer loads to show the shot under the playhead. A card is not a
# clip and is not reachable through `/api/media/`, so these are the routes that
# make V2 a picture rather than a plan of one.


def test_an_asset_route_serves_a_card_the_media_route_cannot_reach(
    project: Path, server: str
) -> None:
    """The reason there are two routes at all: `card:outro` is an asset key, not
    a clip_id, and `/api/media/` resolves clip_ids only."""
    card = Project.open(project).cards_dir / "outro.png"
    card.write_bytes(b"\x89PNG\r\n\x1a\nfake")

    status, headers, body = _get(f"{server}/api/asset/card:outro")

    assert status == 200
    assert body == card.read_bytes()
    assert headers["Accept-Ranges"] == "bytes"
    assert _json(f"{server}/api/media/card:outro")[0] == 400


def test_an_asset_route_also_serves_a_clip(project: Path, server: str) -> None:
    """A picture cue's asset is a clip_id as often as it is a card, so the one
    route answers for both — and answers with the same bytes `/api/media/` does,
    because both go through `media.media_path` rather than guessing at a path."""
    status, _, body = _get(f"{server}/api/asset/vo")

    assert status == 200
    assert body == (project / "media" / "vo.wav").read_bytes()


def test_an_asset_honours_range_the_way_media_does(project: Path, server: str) -> None:
    """The picture layer seeks on every shot change, so Range is load-bearing
    here rather than incidental — and it is the same `_stream_file` either way."""
    whole = (project / "media" / "vo.wav").read_bytes()

    status, headers, body = _get(f"{server}/api/asset/vo", headers={"Range": "bytes=64-127"})

    assert status == 206
    assert headers["Content-Range"] == f"bytes 64-127/{len(whole)}"
    assert body == whole[64:128]


def test_a_card_name_cannot_climb_out_of_the_cards_directory(server: str) -> None:
    """The one place an asset key arrives from outside the project. A traversal
    is refused with a message rather than served, and the check lives in
    `ops.preview_source` so the route cannot have a second, weaker copy of it."""
    assert _get(f"{server}/api/asset/card:..%2F..%2F..%2Fetc%2Fpasswd")[0] == 400

    status, payload = _json(f"{server}/api/preview/card:..%2F..%2F..%2Fetc%2Fpasswd")
    assert status == 400
    assert "does not name a card" in payload["error"]


def test_an_unknown_asset_is_a_message_not_a_crash(server: str) -> None:
    status, payload = _json(f"{server}/api/asset/nope")
    assert status == 400
    assert "nope" in payload["error"]


def test_preview_names_the_kind_the_front_end_has_to_draw_with(
    project: Path, server: str
) -> None:
    """`kind` decides <img> versus <video>, and it is read off the resolved file
    rather than off the cue: `is_image` in a shot is a statement about the key."""
    Project.open(project).cards_dir.joinpath("outro.png").write_bytes(b"\x89PNG\r\n\x1a\nfake")

    _, card = _json(f"{server}/api/preview/card:outro")
    assert card["kind"] == "image"
    assert card["playable"] is True
    assert card["path"].endswith("assets/cards/outro.png")

    _, clip = _json(f"{server}/api/preview/vo")
    assert clip["kind"] == "audio"
    assert clip["playable"] is True
    assert clip["reason"] is None
    assert clip["audio_codec"] == "pcm_s16le"


def test_preview_is_what_turns_a_contentless_media_error_into_a_reason(
    project: Path, server: str
) -> None:
    """The point of the endpoint. A `<video>` that cannot decode its source fires
    one empty `error` event, so the front end asks here and gets words — and the
    file is still served on `/api/asset/`, because the browser is the authority
    and this list is a prediction."""
    # A .mkv registered as a clip: playable streams, container browsers refuse.
    mkv = project.parent / "clip.mkv"
    subprocess.run(
        [
            "ffmpeg", "-y", "-loglevel", "error",
            "-f", "lavfi", "-i", "testsrc=size=160x120:rate=24:duration=1",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(mkv),
        ],
        check=True,
        capture_output=True,
    )  # fmt: skip
    ops.import_media(project, mkv, clip_id="broll")

    status, payload = _json(f"{server}/api/preview/broll")

    assert status == 200
    assert payload["playable"] is False
    assert ".mkv" in payload["reason"]
    assert _get(f"{server}/api/asset/broll")[0] == 200


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
    # theme.js is loaded from <head> as a classic script, not a module: a
    # module is deferred and the page would paint in the wrong theme first.
    assert b'<script src="/static/theme.js"></script>' in body

    for asset, prefix in (
        ("app.js", "text/javascript"),
        ("theme.js", "text/javascript"),
        ("app.css", "text/css"),
    ):
        status, headers, body = _get(f"{server}/static/{asset}")
        assert status == 200, asset
        assert headers["Content-Type"].startswith(prefix)
        assert body


def test_the_vendored_fonts_are_served_and_the_css_asks_for_them(server: str) -> None:
    """The three type voices ship in the package, not from a CDN.

    A CDN would be refused by this server's own `default-src 'self'` CSP, so
    a missing woff2 does not fail loudly — the page just silently falls back
    to a system font and the look pass quietly undoes itself.
    """
    _, _, css = _get(f"{server}/static/app.css")
    wanted = {
        name.decode()
        for name in re.findall(rb'url\("/static/([^"]+\.woff2)"\)', css)
    }
    assert wanted, "app.css declares no vendored fonts"

    for name in sorted(wanted):
        status, headers, body = _get(f"{server}/static/{name}")
        assert status == 200, name
        assert headers["Content-Type"] == "font/woff2", name
        assert body[:4] == b"wOF2", name


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


# -- per-turn thumbs (agent panel cosmetics, item 2) -------------------------


def test_agent_thumbs_rejects_a_bad_host(server: str) -> None:
    request = urllib.request.Request(
        f"{server}/api/agent/thumbs",
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


def test_agent_thumbs_requires_json_content_type(server: str) -> None:
    status, payload = _post(
        f"{server}/api/agent/thumbs",
        {"rating": "up", "session_id": "s", "turn_id": "t"},
        content_type="text/plain",
    )
    assert status == 400
    assert "application/json" in payload["error"]


def test_agent_thumbs_rejects_a_bad_rating(server: str) -> None:
    status, payload = _post(
        f"{server}/api/agent/thumbs",
        {"rating": "sideways", "session_id": "s", "turn_id": "t"},
    )
    assert status == 400
    assert "rating" in payload["error"]


def test_agent_thumbs_requires_session_and_turn_id(server: str) -> None:
    status, payload = _post(f"{server}/api/agent/thumbs", {"rating": "up", "turn_id": "t"})
    assert status == 400
    assert "session_id" in payload["error"]

    status, payload = _post(f"{server}/api/agent/thumbs", {"rating": "up", "session_id": "s"})
    assert status == 400
    assert "turn_id" in payload["error"]


def test_agent_thumbs_appends_a_record_without_touching_the_timeline(
    project: Path, server: str
) -> None:
    _, before = _json(f"{server}/api/view")

    host, port = _host_and_port(server)
    # `getresponse()` on a Connection: close response (this stream has no
    # Content-Length) hands the socket to the response object and nulls
    # `conn.sock` — so the read timeout has to be set on the connection
    # before that happens, not on `conn.sock` afterwards. It applies to the
    # whole socket lifetime, including the earlier reads, which is fine —
    # they arrive immediately.
    conn = http.client.HTTPConnection(host, port, timeout=1.2)
    try:
        conn.request("GET", "/api/events")
        resp = conn.getresponse()
        events = _sse_events(resp)
        next(events)  # the initial project-changed

        status, payload = _post(
            f"{server}/api/agent/thumbs",
            {
                "rating": "up",
                "session_id": "sess-1",
                "turn_id": "turn-1",
                "prompt": "cut the retake",
            },
        )
        assert status == 200
        assert payload["recorded"] is True
        assert payload["rating"] == "up"
        assert payload["session_id"] == "sess-1"
        assert payload["turn_id"] == "turn-1"
        assert payload["prompt"] == "cut the retake"

        # The SSE poll loop only writes when `_revision` moves — a thumbs
        # write touches neither `project.otio`'s mtime nor the snapshot
        # count, so nothing should arrive here within a couple of poll
        # cycles (_REVISION_POLL_SECONDS is 0.5).
        with pytest.raises(TimeoutError):
            next(events)
    finally:
        conn.close()

    lines = Project.open(project).thumbs_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["session_id"] == "sess-1"
    assert record["turn_id"] == "turn-1"
    assert record["rating"] == "up"
    assert record["prompt"] == "cut the retake"
    assert "ts" in record

    _, after = _json(f"{server}/api/view")
    assert after["undo_depth"] == before["undo_depth"]
    assert after["timeline_duration"] == before["timeline_duration"]


def test_agent_thumbs_appends_a_second_line_for_a_second_turn(project: Path, server: str) -> None:
    _post(
        f"{server}/api/agent/thumbs",
        {"rating": "up", "session_id": "sess-1", "turn_id": "turn-1"},
    )
    status, payload = _post(
        f"{server}/api/agent/thumbs",
        {"rating": "down", "session_id": "sess-1", "turn_id": "turn-2"},
    )
    assert status == 200
    assert payload["rating"] == "down"

    lines = Project.open(project).thumbs_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    turn_ids = {json.loads(line)["turn_id"] for line in lines}
    assert turn_ids == {"turn-1", "turn-2"}


# -- Start New Task (agent panel cosmetics, item 4) --------------------------


def test_agent_new_task_rejects_a_bad_host_and_bad_content_type(server: str) -> None:
    request = urllib.request.Request(
        f"{server}/api/agent/new-task",
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

    status, payload = _post(f"{server}/api/agent/new-task", {}, content_type="text/plain")
    assert status == 400
    assert "application/json" in payload["error"]


def test_new_task_with_no_subprocess_running_is_a_no_op(server: str) -> None:
    status, payload = _post(f"{server}/api/agent/new-task", {})
    assert status == 200
    assert payload["reset"] is True


def test_new_task_kills_the_running_subprocess_and_the_next_prompt_spawns_a_fresh_one(
    server: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pid_file = tmp_path / "pids.txt"
    canned = {"type": "assistant", "message": {"content": [{"type": "text", "text": "hi"}]}}
    stub = tmp_path / "agent-stub.sh"
    _write_pid_recording_stub(stub, pid_file, canned)
    monkeypatch.setenv(webui.AGENT_BIN_ENV, str(stub))

    host, port = _host_and_port(server)
    conn = http.client.HTTPConnection(host, port, timeout=5)
    try:
        conn.request("GET", "/api/events")
        resp = conn.getresponse()
        events = _sse_events(resp)
        next(events)  # the initial project-changed

        status, _ = _post(f"{server}/api/agent", {"prompt": "first"})
        assert status == 202
        event, data = next(events)
        assert event == "agent"
        assert data == canned

        pids_after_first = pid_file.read_text(encoding="utf-8").split()
        assert len(pids_after_first) == 1

        status, payload = _post(f"{server}/api/agent/new-task", {})
        assert status == 200
        assert payload["reset"] is True

        status, _ = _post(f"{server}/api/agent", {"prompt": "second"})
        assert status == 202
        event, data = next(events)
        assert event == "agent"
        assert data == canned

        pids_after_second = pid_file.read_text(encoding="utf-8").split()
        assert len(pids_after_second) == 2
        # The second spawn is a genuinely different process, not the killed
        # one reused.
        assert pids_after_second[0] != pids_after_second[1]
    finally:
        conn.close()


def test_new_task_mid_turn_does_not_leak_a_synthetic_error_event(
    server: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Guards `_suppress_next_exit_report` specifically: a reset kills a live
    subprocess before it ever emits a `result` event, which is exactly the
    shape `_pump_stdout`'s silent-exit safety net (written for a genuinely
    broken subprocess) would otherwise report as `error_no_output` — right
    after the deliberate reset that a person clicked New Task to get.
    """
    argv_file = tmp_path / "argv.txt"
    canned = {"type": "assistant", "message": {"content": [{"type": "text", "text": "working…"}]}}
    stub = tmp_path / "agent-stub.sh"
    _write_agent_stub(stub, argv_file, canned)
    monkeypatch.setenv(webui.AGENT_BIN_ENV, str(stub))

    host, port = _host_and_port(server)
    # See the comment in test_agent_thumbs_appends_a_record_without_touching_the_timeline
    # on why the timeout is set on the connection, not on `conn.sock`.
    conn = http.client.HTTPConnection(host, port, timeout=1.2)
    try:
        conn.request("GET", "/api/events")
        resp = conn.getresponse()
        events = _sse_events(resp)
        next(events)  # the initial project-changed

        status, _ = _post(f"{server}/api/agent", {"prompt": "cut the retake"})
        assert status == 202
        event, data = next(events)
        assert event == "agent"
        assert data == canned  # the turn is genuinely live and mid-flight

        status, payload = _post(f"{server}/api/agent/new-task", {})
        assert status == 200
        assert payload["reset"] is True

        # No error_no_output (or any) result event should follow the kill.
        with pytest.raises(TimeoutError):
            next(events)
    finally:
        conn.close()


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


def test_a_layered_project_renders_into_a_container_melt_can_mux(
    server: str, project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The suffix follows the primary clip — except on a layered timeline.

    That one is rendered by melt with `vcodec=libx264`, and the VO it lays
    picture over is a `.wav`: naming the output after it would ask melt to mux
    h264 into a wav. The fact that the timeline is layered comes from
    `ops.timeline_view`, not from a second reading of the manifest here —
    the window never decides (CLAUDE.md).
    """
    second = project.parent / "vo2.wav"
    _make_wav(second)
    ops.import_media(project, second, clip_id="vo2")
    view = ops.timeline_view(str(project))
    tl.write(
        tl.to_otio(
            tl.Edit([tl.Segment("vo", 0.0, 2.0), tl.Segment("vo2", 0.0, 2.0)]),
            {c["clip_id"]: c for c in Project.open(project).read_manifest()["clips"]},
            rate=view["timebase"],
            name="proj",
        ),
        Project.open(project).timeline_path,
    )
    assert ops.timeline_view(str(project))["layered"] is True
    seen: dict[str, str] = {}

    def _stub(path: str, output: str, **kwargs: Any) -> dict[str, Any]:
        seen["output"] = output
        _make_wav(Path(output), duration=0.3)
        return {"output": output, "format": "media", "writer": "melt"}

    monkeypatch.setattr(ops, "export", _stub)
    monkeypatch.setattr(ops, "verify", lambda *a, **k: {"agrees": True, "stub": True})
    host, port = _host_and_port(server)
    conn = http.client.HTTPConnection(host, port, timeout=5)
    try:
        conn.request("GET", "/api/events")
        events = _sse_events(conn.getresponse())
        next(events)  # the initial project-changed

        status, payload = _post(f"{server}/api/render", {})
        assert status == 202
        assert _next_render_event(events, payload["job_id"])["status"] == "done"
    finally:
        conn.close()

    assert Path(seen["output"]).suffix == ".mp4"


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


def _fast_export_stub_with_preset(
    path: str,
    output: str,
    *,
    export_format: str | None = None,
    fps: float | None = None,
    preset: str | None = None,
    resolution: tuple[int, int] | None = None,
) -> dict[str, Any]:
    _make_wav(Path(output), duration=0.3)
    return {
        "output": output,
        "format": "media",
        "timebase": 1000.0,
        "segments": 1,
        "timeline_duration": 0.3,
        "preset": preset,
        "resolution": list(resolution) if resolution else None,
    }


def test_render_accepts_preset_and_resolution_and_echoes_them_on_the_running_event(
    server: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ops, "export", _fast_export_stub_with_preset)
    host, port = _host_and_port(server)
    conn = http.client.HTTPConnection(host, port, timeout=5)
    try:
        conn.request("GET", "/api/events")
        events = _sse_events(conn.getresponse())
        next(events)  # the initial project-changed

        status, payload = _post(f"{server}/api/render", {"preset": "web", "resolution": [608, 1080]})
        assert status == 202

        # the FIRST render event is 'running' — the one that carries the echo.
        for event, data in events:
            if event == "render" and data.get("job_id") == payload["job_id"]:
                assert data["status"] == "running"
                assert data["preset"] == "web"
                assert data["resolution"] == [608, 1080]
                break
        else:
            raise AssertionError("no render event arrived")
    finally:
        conn.close()


def test_render_resolution_must_be_a_two_element_int_list(server: str) -> None:
    for bad in ("1080x1920", [1080], [1080, 1920, 1], [1080.0, 1920.0]):
        status, payload = _post(f"{server}/api/render", {"resolution": bad})
        assert status == 400, bad
        assert "resolution" in payload["error"]


def test_render_with_an_invalid_preset_combination_reports_error_not_400(
    server: str,
) -> None:
    """A syntactically valid body ('custom' with no resolution) is a real
    caller mistake ops.export refuses — but only once the job is running, not
    at the HTTP layer, since this handler only checks shape."""
    host, port = _host_and_port(server)
    conn = http.client.HTTPConnection(host, port, timeout=5)
    try:
        conn.request("GET", "/api/events")
        events = _sse_events(conn.getresponse())
        next(events)  # the initial project-changed

        status, payload = _post(f"{server}/api/render", {"preset": "custom"})
        assert status == 202
        job_id = payload["job_id"]

        found = _next_render_event(events, job_id)
        assert found["status"] == "error"
        assert "custom" in found["error"]
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
