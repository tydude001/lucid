"""End-to-end checks against the real server process.

This spawns `lucid mcp` as a subprocess and speaks MCP over its stdio, rather
than calling the tool functions directly — the wiring between the CLI, the
transport, and the tool registry is exactly what a unit test would miss
(CLAUDE.md).
"""

from __future__ import annotations

import inspect
import json
import math
import shutil
import struct
import subprocess
import sys
import tempfile
import wave
import xml.etree.ElementTree as ET
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import anyio
import pytest
from mcp import ClientSession, StdioServerParameters, stdio_client

from lucid import energy, media, ops, picture
from lucid.project import Project

SERVER = StdioServerParameters(command=sys.executable, args=["-m", "lucid.cli", "mcp"])

#: Every tool the MCP surface is expected to expose. Asserted exactly, so a
#: tool that is written but never registered fails the suite instead of
#: silently not existing.
EXPECTED_TOOLS = {
    "ping",
    "init",
    "migrate_project",
    "import_media",
    "attach_transcript",
    "transcribe",
    "get_transcript",
    "describe",
    "describe_ls",
    "card_templates",
    "card_new",
    "card_render",
    "cue_add",
    "cue_rm",
    "cue_ls",
    "build_shots",
    "seed_timeline",
    "cut_by_transcript",
    "cut_by_time",
    "restore",
    "locate",
    "timeline_status",
    "timeline_view",
    "undo",
    "add_captions",
    "caption_view",
    "caption_style",
    "canvas",
    "verify",
    "check_frames",
    "check_black",
    "spot_frames",
    "attenuate_noises",
    "speech_overlap",
    "export",
}

needs_ffprobe = pytest.mark.skipif(
    shutil.which("ffprobe") is None, reason="ffprobe is not installed"
)
needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is not installed")


class Client:
    """A tiny wrapper so tests read as a sequence of tool calls."""

    def __init__(self, session: ClientSession) -> None:
        self._session = session

    async def call(self, tool: str, **arguments: Any) -> Any:
        result = await self._session.call_tool(tool, arguments)
        payload = json.loads(result.content[0].text)
        assert not result.is_error, f"{tool} failed: {payload}"
        return payload


async def _with_server(body: Any, server: StdioServerParameters = SERVER) -> Any:
    async with (
        stdio_client(server) as (read, write),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        return await body(session)


def _make_wav(path: Path, *, tones: list[tuple[float, float]], duration: float = 12.0) -> None:
    """A wav with tone bursts at `tones` and silence elsewhere."""
    rate = 22050
    with wave.open(str(path), "w") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        frames = bytearray()
        for i in range(int(rate * duration)):
            t = i / rate
            loud = any(a <= t < b for a, b in tones)
            value = int(12000 * math.sin(2 * math.pi * 220 * t)) if loud else 0
            frames += struct.pack("<h", value)
        out.writeframes(bytes(frames))


def _make_sources(root: Path) -> tuple[Path, Path]:
    """A four-burst recording and a transcript with two words per burst."""
    audio = root / "vo.wav"
    _make_wav(audio, tones=[(0.0, 2.0), (3.0, 5.0), (6.0, 8.0), (9.0, 11.0)])

    words = []
    for burst, (start, _) in enumerate([(0.0, 2.0), (3.0, 5.0), (6.0, 8.0), (9.0, 11.0)]):
        for n in range(2):
            at = start + n
            words.append({"word": f"w{burst}{n}", "start": at, "end": at + 0.9})

    transcript = root / "vo.json"
    transcript.write_text(json.dumps({"language": "en", "words": words}), encoding="utf-8")
    return audio, transcript


@pytest.fixture
def sources(tmp_path: Path) -> tuple[Path, Path]:
    return _make_sources(tmp_path)


def test_server_serves_ping_over_stdio() -> None:
    async def body(session: ClientSession) -> Any:
        return await Client(session).call("ping")

    payload = anyio.run(_with_server, body)
    assert payload["status"] == "ok"
    assert payload["server"] == "lucid"


def test_every_tool_is_registered() -> None:
    async def body(session: ClientSession) -> Any:
        return await session.list_tools()

    tools = anyio.run(_with_server, body)
    assert {tool.name for tool in tools.tools} == EXPECTED_TOOLS


#: MCP tool -> CLI subcommand. Tool names are spelled for an agent reading a
#: tool list; subcommands are spelled for a human typing them. Where the two
#: differ the mapping is recorded here and asserted in both directions, so a
#: tool added to only one front end fails the suite either way.
TOOL_TO_COMMAND = {
    "init": "init",
    "migrate_project": "migrate",
    "import_media": "import",
    "attach_transcript": "attach-transcript",
    "transcribe": "transcribe",
    "get_transcript": "transcript",
    "describe": "describe",
    "describe_ls": "describe-ls",
    "card_templates": "card",
    "card_new": "card",
    "card_render": "card",
    "cue_add": "cue",
    "cue_rm": "cue",
    "cue_ls": "cue",
    "build_shots": "shots",
    "seed_timeline": "seed",
    "cut_by_transcript": "cut",
    "cut_by_time": "cut-at",
    "restore": "restore",
    "locate": "locate",
    "timeline_status": "status",
    "timeline_view": "view",
    "undo": "undo",
    "add_captions": "captions",
    "caption_view": "caption-view",
    "caption_style": "caption-style",
    "canvas": "canvas",
    "verify": "verify",
    "check_frames": "frames",
    "check_black": "black",
    "spot_frames": "spots",
    "attenuate_noises": "attenuate",
    "speech_overlap": "speech-overlap",
    "export": "export",
}

#: CLI-only commands, with the reason each one has no tool behind it.
CLI_ONLY = {
    "mcp",  # starts the server; nothing to call it from
    "ping",  # a tool, but takes no project and needs no mapping
    "info",  # prints the manifest, which MCP clients get from other tools —
    # and stands its descriptions down to a count, because describe_ls is
    # where the text is meant to be read
    "web",  # serves the UI until Ctrl-C; an agent cannot watch a page
    "waveform",  # 19,000 floats is a picture, not something an agent reasons
    # over — PLAN.md § Read-model additions
    "preview",  # answers "will a *browser* play this", and an agent has no
    # <video> element; no render path consults the verdict either
}


def test_every_mcp_tool_has_a_cli_subcommand() -> None:
    """Parity is a project convention, so it gets asserted rather than trusted."""
    from lucid.cli import _COMMANDS

    assert set(TOOL_TO_COMMAND) == EXPECTED_TOOLS - {"ping"}, (
        "the tool -> command map has drifted from the registered tool list"
    )
    for tool, command in TOOL_TO_COMMAND.items():
        assert command in _COMMANDS, f"MCP tool {tool!r} has no `lucid {command}` subcommand"

    # And the other way, so a CLI command cannot quietly lack a tool.
    unmapped = set(_COMMANDS) - set(TOOL_TO_COMMAND.values()) - CLI_ONLY
    assert not unmapped, f"CLI subcommands with no MCP tool: {sorted(unmapped)}"


@needs_ffprobe
def test_cut_by_transcript_end_to_end(tmp_path: Path, sources: tuple[Path, Path]) -> None:
    """The whole slice over the wire: import, transcript, seed, cut, undo."""
    audio, transcript = sources
    project = tmp_path / "proj"

    async def body(session: ClientSession) -> dict[str, Any]:
        client = Client(session)
        await client.call("init", path=str(project))
        clip = await client.call("import_media", path=str(project), source=str(audio))
        attached = await client.call(
            "attach_transcript",
            path=str(project),
            clip_id=clip["clip_id"],
            transcript_path=str(transcript),
        )
        # Seed without the silence pass so this test does not need auto-editor.
        seeded = await client.call(
            "seed_timeline", path=str(project), clip_id=clip["clip_id"], remove_silences=False
        )
        found = await client.call(
            "get_transcript", path=str(project), clip_id=clip["clip_id"], search="w10 w11"
        )
        cut = await client.call(
            "cut_by_transcript",
            path=str(project),
            clip_id=clip["clip_id"],
            cut=[[2, 3]],
        )
        status = await client.call("timeline_status", path=str(project))
        undone = await client.call("undo", path=str(project))
        return {
            "clip": clip,
            "attached": attached,
            "seeded": seeded,
            "found": found,
            "cut": cut,
            "status": status,
            "undone": undone,
        }

    out = anyio.run(_with_server, body)

    assert out["clip"]["has_audio"] is True and out["clip"]["has_video"] is False
    assert out["attached"]["words"] == 8
    assert out["seeded"]["timeline_duration"] == pytest.approx(12.0, abs=0.05)

    # The phrase is found at the word range that addresses it.
    assert (out["found"]["matches"][0]["first_word"], out["found"]["matches"][0]["last_word"]) == (2, 3)

    # Words 2-3 span source 3.0 -> 4.9, so 1.9s comes out and the segment splits.
    assert out["cut"]["removed"] == pytest.approx(1.9, abs=0.01)
    assert out["cut"]["segments"] == 2
    assert out["status"]["timeline_duration"] == pytest.approx(10.1, abs=0.05)
    assert out["status"]["undo_depth"] == 1

    # Undo puts the timeline back exactly.
    assert out["undone"]["timeline_duration"] == pytest.approx(12.0, abs=0.05)
    assert out["undone"]["undo_depth"] == 0


@needs_ffprobe
@pytest.mark.skipif(shutil.which("magick") is None, reason="ImageMagick is not installed")
def test_card_render_over_the_wire(tmp_path: Path) -> None:
    """A card rendered through the server lands where a `card:` cue looks."""
    project = tmp_path / "proj"

    async def body(session: ClientSession) -> dict[str, Any]:
        client = Client(session)
        await client.call("init", path=str(project))
        cards = Project.open(project).cards_dir
        cards.mkdir(parents=True, exist_ok=True)
        (cards / "receipt.svg").write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" width="1920" height="1080">'
            '<rect width="1920" height="1080" fill="#101418"/></svg>',
            encoding="utf-8",
        )
        return await client.call("card_render", path=str(project), name="receipt")

    out = anyio.run(_with_server, body)

    assert out["asset"] == "card:receipt"
    assert (out["width"], out["height"]) == (1920, 1080)
    assert Path(out["output"]) == Project.open(project).cards_dir / "receipt.png"
    assert Path(out["output"]).is_file()


@pytest.mark.skipif(shutil.which("magick") is None, reason="ImageMagick is not installed")
def test_card_new_from_a_template_over_the_wire(tmp_path: Path) -> None:
    """A card an agent could actually make: list templates, then fill one."""
    project = tmp_path / "proj"

    async def body(session: ClientSession) -> dict[str, Any]:
        client = Client(session)
        await client.call("init", path=str(project))
        listed = await client.call("card_templates")
        made = await client.call(
            "card_new",
            path=str(project),
            name="receipt-scream-1996",
            template="receipt",
            slots={
                "title": "Scream",
                "year": "1996",
                "rating": 4.5,
                "date_line": "watched 20 May 2021",
            },
        )
        return {"listed": listed, "made": made}

    out = anyio.run(_with_server, body)

    assert {t["template"] for t in out["listed"]["templates"]} == {"receipt", "reveal", "rerate"}
    assert out["made"]["asset"] == "card:receipt-scream-1996"
    # No video clip in this project, so the canvas falls back to 1080p.
    assert out["made"]["canvas_from"] == "project"
    assert (out["made"]["width"], out["made"]["height"]) == (1920, 1080)

    cards = Project.open(project).cards_dir
    assert (cards / "receipt-scream-1996.svg").is_file()
    assert (cards / "receipt-scream-1996.png").is_file()


@needs_ffprobe
def test_describe_plans_over_the_wire_without_loading_a_model(tmp_path: Path) -> None:
    """`describe` reachable over stdio, in the mode an agent should reach for
    first: `plan=True` resolves the whole work list, the estimate, and whether
    this box can run the model at all, without 31 GB of weights being what
    answers the question. The describing half needs a GPU and is exercised in
    `test_ops_describe.py` against a stub.
    """
    project = tmp_path / "proj"
    media = tmp_path / "silent.mp4"
    subprocess.run(
        [
            "ffmpeg", "-nostdin", "-v", "error", "-y",
            "-f", "lavfi", "-i", "color=c=black:s=320x240:r=24:d=25",
            str(media),
        ],
        check=True,
    )

    async def body(session: ClientSession) -> dict[str, Any]:
        client = Client(session)
        await client.call("init", path=str(project))
        await client.call("import_media", path=str(project), source=str(media))
        return await client.call("describe", path=str(project), plan=True)

    out = anyio.run(_with_server, body)

    assert out["plan"] is True
    # 25s at 10s windows is three windows, never two of 12.5 — a window is
    # never longer than the one asked for.
    assert out["windows"] == 3
    assert out["clips"] == [{"clip_id": "silent", "windows": 3}]
    assert out["estimated_seconds"] == 26
    assert set(out["runtime"]) == {"available", "python", "tagger", "why"}
    # Nothing was described, so nothing was stored.
    assert Project.open(project).read_manifest()["descriptions"] == []


@needs_ffprobe
def test_describe_ls_searches_over_the_wire(tmp_path: Path) -> None:
    """The read half reachable over stdio — and reachable is the whole point,
    since this is what an agent looking for b-roll actually calls.

    The descriptions are written into the manifest directly rather than
    generated: the model is 31 GB under another interpreter, and what is
    under test here is the transport and the filter, not the vision pass
    (`test_ops_describe.py` covers that against a stub).
    """
    project = tmp_path / "proj"
    source = tmp_path / "silent.mp4"
    subprocess.run(
        [
            "ffmpeg", "-nostdin", "-v", "error", "-y",
            "-f", "lavfi", "-i", "color=c=black:s=320x240:r=24:d=25",
            str(source),
        ],
        check=True,
    )

    async def body(session: ClientSession) -> dict[str, Any]:
        client = Client(session)
        await client.call("init", path=str(project))
        await client.call("import_media", path=str(project), source=str(source))

        opened = Project.open(project)
        manifest = opened.read_manifest()
        manifest["descriptions"] = [
            {
                "clip_id": "silent",
                "src_start": 0.0,
                "src_end": 12.5,
                "text": "A knife on a kitchen counter, beside a white phone.",
                "truncated": False,
                "origin": "qwen2.5-vl:10s/3f",
            },
            {
                "clip_id": "silent",
                "src_start": 12.5,
                "src_end": 25.0,
                "text": "A car parked in a driveway at night, headlights",
                "truncated": True,
                "origin": "qwen2.5-vl:10s/3f",
            },
        ]
        opened.write_manifest(manifest)

        return {
            "all": await client.call("describe_ls", path=str(project)),
            "hit": await client.call("describe_ls", path=str(project), contains="kitchen knife"),
            "miss": await client.call("describe_ls", path=str(project), contains="helicopter"),
        }

    out = anyio.run(_with_server, body)

    assert out["all"]["count"] == 2
    assert out["all"]["clips"] == [
        {
            "clip_id": "silent",
            "windows": 2,
            "described_seconds": 25.0,
            "duration": pytest.approx(25.0, abs=0.05),
            "truncated": 1,
        }
    ]

    # Every term, anywhere — not a phrase match.
    assert out["hit"]["count"] == 1
    assert "knife" in out["hit"]["descriptions"][0]["text"]
    assert out["hit"]["filter"]["terms"] == ["kitchen", "knife"]

    # A miss still says what it filtered out of, so it cannot be mistaken for
    # a project with nothing described in it.
    assert out["miss"]["count"] == 0
    assert out["miss"]["total"] == 2


@needs_ffprobe
def test_describe_refuses_an_audio_only_clip_over_the_wire(
    tmp_path: Path, sources: tuple[Path, Path]
) -> None:
    """The Scream project's VO is exactly this clip, and skipping it quietly
    reads the same as describing it and finding nothing to say."""
    audio, _ = sources
    project = tmp_path / "proj"

    async def body(session: ClientSession) -> Any:
        client = Client(session)
        await client.call("init", path=str(project))
        clip = await client.call("import_media", path=str(project), source=str(audio))
        return await session.call_tool(
            "describe", {"path": str(project), "clip_id": clip["clip_id"], "plan": True}
        )

    result = anyio.run(_with_server, body)

    assert result.is_error
    assert "no video track" in result.content[0].text


def test_cue_table_add_ls_rm_end_to_end(tmp_path: Path, sources: tuple[Path, Path]) -> None:
    """The cue table over the wire — no timeline needed, only a transcript."""
    audio, transcript = sources
    project = tmp_path / "proj"

    async def body(session: ClientSession) -> dict[str, Any]:
        client = Client(session)
        await client.call("init", path=str(project))
        clip = await client.call("import_media", path=str(project), source=str(audio))
        await client.call(
            "attach_transcript",
            path=str(project),
            clip_id=clip["clip_id"],
            transcript_path=str(transcript),
        )
        added = await client.call(
            "cue_add", path=str(project), clip_id=clip["clip_id"], word_index=2, asset="cold-open"
        )
        listed = await client.call("cue_ls", path=str(project))
        removed = await client.call(
            "cue_rm", path=str(project), clip_id=clip["clip_id"], word_index=2
        )
        empty = await client.call("cue_ls", path=str(project))
        return {"clip": clip, "added": added, "listed": listed, "removed": removed, "empty": empty}

    out = anyio.run(_with_server, body)

    assert out["added"]["asset"] == "cold-open"
    assert out["added"]["text"] == "w10"  # word 2 of the 8-word `sources` transcript
    assert out["listed"]["count"] == 1
    assert out["listed"]["cues"][0]["word_index"] == 2
    assert out["removed"]["asset"] == "cold-open"
    assert out["empty"]["count"] == 0


@needs_ffprobe
def test_cue_add_refuses_a_duplicate_word_over_the_wire(
    tmp_path: Path, sources: tuple[Path, Path]
) -> None:
    audio, transcript = sources
    project = tmp_path / "proj"

    async def body(session: ClientSession) -> dict[str, Any]:
        client = Client(session)
        await client.call("init", path=str(project))
        clip = await client.call("import_media", path=str(project), source=str(audio))
        await client.call(
            "attach_transcript",
            path=str(project),
            clip_id=clip["clip_id"],
            transcript_path=str(transcript),
        )
        await client.call(
            "cue_add", path=str(project), clip_id=clip["clip_id"], word_index=0, asset="cold-open"
        )
        result = await session.call_tool(
            "cue_add",
            {"path": str(project), "clip_id": clip["clip_id"], "word_index": 0, "asset": "s4-reveal"},
        )
        return {"is_error": result.is_error, "text": result.content[0].text}

    out = anyio.run(_with_server, body)
    assert out["is_error"]
    assert "already has a cue" in out["text"]


@needs_ffprobe
def test_cut_plan_resolves_without_touching_the_timeline(
    tmp_path: Path, sources: tuple[Path, Path]
) -> None:
    """Look before you cut, and see the words either side.
    HISTORY.md § `cut --plan`, and echoing what a word index resolved to.

    The numbers a plan reports are the real ones — it runs the same code path
    and skips the write — so the assertion that matters is that the plan and
    the cut that follows it agree exactly, while the plan alone leaves no
    snapshot behind.
    """
    audio, transcript = sources
    project = tmp_path / "proj"

    async def body(session: ClientSession) -> dict[str, Any]:
        client = Client(session)
        await client.call("init", path=str(project))
        clip = await client.call("import_media", path=str(project), source=str(audio))
        await client.call(
            "attach_transcript",
            path=str(project),
            clip_id=clip["clip_id"],
            transcript_path=str(transcript),
        )
        await client.call(
            "seed_timeline", path=str(project), clip_id=clip["clip_id"], remove_silences=False
        )
        planned = await client.call(
            "cut_by_transcript",
            path=str(project),
            clip_id=clip["clip_id"],
            cut=[[2, 3]],
            plan=True,
        )
        padded = await client.call(
            "cut_by_transcript",
            path=str(project),
            clip_id=clip["clip_id"],
            cut=[[2, 3]],
            pad=1.2,
            plan=True,
        )
        after_plan = await client.call("timeline_status", path=str(project))
        cut = await client.call(
            "cut_by_transcript", path=str(project), clip_id=clip["clip_id"], cut=[[2, 3]]
        )
        after_cut = await client.call("timeline_status", path=str(project))
        return {
            "planned": planned,
            "padded": padded,
            "after_plan": after_plan,
            "cut": cut,
            "after_cut": after_cut,
        }

    out = anyio.run(_with_server, body)
    planned, applied = out["planned"], out["planned"]["applied"][0]

    assert planned["plan"] is True

    # The indices resolve to their words, and to the words either side of them.
    assert applied["text"] == "w10 w11"
    assert [w["index"] for w in applied["context_before"]] == [0, 1]
    assert [w["index"] for w in applied["context_after"]] == [4, 5, 6]
    assert applied["word_start"] == pytest.approx(3.0) and applied["word_end"] == pytest.approx(4.9)
    assert "pad_reach" not in applied

    # A pad wide enough to reach the neighbouring words says so — the echoed
    # text is the same two words either way, which is the whole problem.
    reach = {w["index"]: w["side"] for w in out["padded"]["applied"][0]["pad_reach"]}
    assert reach == {1: "before", 4: "after"}
    assert out["padded"]["applied"][0]["text"] == "w10 w11"

    # Planning wrote nothing: same duration, and no snapshot to roll back.
    assert out["after_plan"]["timeline_duration"] == pytest.approx(12.0, abs=0.05)
    assert out["after_plan"]["undo_depth"] == 0

    # And the plan was exact — same removal, same resulting segment count.
    assert out["cut"]["removed"] == pytest.approx(planned["removed"], abs=1e-9)
    assert out["cut"]["segments"] == planned["segments"] == 2
    assert out["after_cut"]["undo_depth"] == 1


@needs_ffprobe
def test_restore_brings_back_a_cut_range_end_to_end(
    tmp_path: Path, sources: tuple[Path, Path]
) -> None:
    """`restore` is the inverse of `cut_by_transcript`'s `cut=`: cutting a
    range and then restoring the same range round-trips the timeline back to
    its pre-cut state, and the words themselves report `present` again.
    """
    audio, transcript = sources
    project = tmp_path / "proj"

    async def body(session: ClientSession) -> dict[str, Any]:
        client = Client(session)
        await client.call("init", path=str(project))
        clip = await client.call("import_media", path=str(project), source=str(audio))
        await client.call(
            "attach_transcript",
            path=str(project),
            clip_id=clip["clip_id"],
            transcript_path=str(transcript),
        )
        await client.call(
            "seed_timeline", path=str(project), clip_id=clip["clip_id"], remove_silences=False
        )
        cut = await client.call(
            "cut_by_transcript", path=str(project), clip_id=clip["clip_id"], cut=[[3, 4]]
        )
        before_restore = await client.call(
            "timeline_view", path=str(project), clip_id=clip["clip_id"]
        )
        restored = await client.call(
            "restore", path=str(project), clip_id=clip["clip_id"], ranges=[[3, 4]]
        )
        after_restore = await client.call(
            "timeline_view", path=str(project), clip_id=clip["clip_id"]
        )
        return {
            "clip_id": clip["clip_id"],
            "cut": cut,
            "before_restore": before_restore,
            "restored": restored,
            "after_restore": after_restore,
        }

    out = anyio.run(_with_server, body)

    assert out["cut"]["removed"] > 0.0
    assert out["before_restore"]["words"][3]["present"] is False
    assert out["before_restore"]["words"][4]["present"] is False

    assert out["restored"]["restored"] == pytest.approx(out["cut"]["removed"], abs=1e-6)
    assert out["restored"]["applied"][0]["already_present"] is False

    assert out["after_restore"]["timeline_duration"] == pytest.approx(12.0, abs=0.05)
    assert out["after_restore"]["words"][3]["present"] is True
    assert out["after_restore"]["words"][4]["present"] is True


@needs_ffprobe
def test_restore_plan_resolves_without_touching_the_timeline(
    tmp_path: Path, sources: tuple[Path, Path]
) -> None:
    audio, transcript = sources
    project = tmp_path / "proj"

    async def body(session: ClientSession) -> dict[str, Any]:
        client = Client(session)
        await client.call("init", path=str(project))
        clip = await client.call("import_media", path=str(project), source=str(audio))
        await client.call(
            "attach_transcript",
            path=str(project),
            clip_id=clip["clip_id"],
            transcript_path=str(transcript),
        )
        await client.call(
            "seed_timeline", path=str(project), clip_id=clip["clip_id"], remove_silences=False
        )
        await client.call(
            "cut_by_transcript", path=str(project), clip_id=clip["clip_id"], cut=[[3, 4]]
        )
        status_before = await client.call("timeline_status", path=str(project))
        planned = await client.call(
            "restore", path=str(project), clip_id=clip["clip_id"], ranges=[[3, 4]], plan=True
        )
        status_after_plan = await client.call("timeline_status", path=str(project))
        real = await client.call(
            "restore", path=str(project), clip_id=clip["clip_id"], ranges=[[3, 4]]
        )
        return {
            "status_before": status_before,
            "planned": planned,
            "status_after_plan": status_after_plan,
            "real": real,
        }

    out = anyio.run(_with_server, body)

    assert out["planned"]["plan"] is True
    # The plan reports the real numbers — same code path, write skipped.
    assert out["planned"]["restored"] == pytest.approx(out["real"]["restored"], abs=1e-9)

    # Nothing was written: status is unchanged, in particular the undo depth.
    assert out["status_after_plan"] == out["status_before"]


@needs_ffprobe
def test_restore_echoes_words_plus_three_either_side(
    tmp_path: Path, sources: tuple[Path, Path]
) -> None:
    """CLAUDE.md's convention: any op taking a word index echoes the words it
    resolved to, plus the three either side — same shape as
    `cut_by_transcript`'s own echo.
    """
    audio, transcript = sources
    project = tmp_path / "proj"

    async def body(session: ClientSession) -> dict[str, Any]:
        client = Client(session)
        await client.call("init", path=str(project))
        clip = await client.call("import_media", path=str(project), source=str(audio))
        await client.call(
            "attach_transcript",
            path=str(project),
            clip_id=clip["clip_id"],
            transcript_path=str(transcript),
        )
        await client.call(
            "seed_timeline", path=str(project), clip_id=clip["clip_id"], remove_silences=False
        )
        await client.call(
            "cut_by_transcript", path=str(project), clip_id=clip["clip_id"], cut=[[3, 4]]
        )
        return await client.call(
            "restore", path=str(project), clip_id=clip["clip_id"], ranges=[[3, 4]], plan=True
        )

    out = anyio.run(_with_server, body)
    applied = out["applied"][0]

    assert applied["text"] == "w11 w20"
    assert [w["index"] for w in applied["context_before"]] == [0, 1, 2]
    assert [w["index"] for w in applied["context_after"]] == [5, 6, 7]


@needs_ffprobe
def test_restore_of_a_range_still_fully_present_reports_already_present_without_error(
    tmp_path: Path, sources: tuple[Path, Path]
) -> None:
    """A range that was never cut is a no-op, not a refusal — mirroring
    `cut_by_transcript`'s `already_cut`.
    """
    audio, transcript = sources
    project = tmp_path / "proj"

    async def body(session: ClientSession) -> dict[str, Any]:
        client = Client(session)
        await client.call("init", path=str(project))
        clip = await client.call("import_media", path=str(project), source=str(audio))
        await client.call(
            "attach_transcript",
            path=str(project),
            clip_id=clip["clip_id"],
            transcript_path=str(transcript),
        )
        await client.call(
            "seed_timeline", path=str(project), clip_id=clip["clip_id"], remove_silences=False
        )
        return await client.call(
            "restore", path=str(project), clip_id=clip["clip_id"], ranges=[[0, 1]]
        )

    out = anyio.run(_with_server, body)
    applied = out["applied"][0]

    assert applied["already_present"] is True
    assert applied["restored_seconds"] == pytest.approx(0.0)
    assert out["restored"] == pytest.approx(0.0)


@needs_ffprobe
def test_attach_transcript_flags_adjacent_near_duplicate_phrases(tmp_path: Path) -> None:
    """Over the wire: attach reports a retake `verify` can never catch,
    before any edit exists to diff it against (test_verify.py exercises the
    detector itself; this checks it is actually wired in).
    HISTORY.md § Adjacent near-duplicate phrases at `attach-transcript`.
    """
    audio = tmp_path / "vo.wav"
    _make_wav(audio, tones=[(0.0, 8.0)])

    texts = ["so", "much", "going", "on", "here", "it's", "more", "of", "a", "meta", "commentary", "I", "don't", "think", "that", "it's", "a", "coincidence", "I", "don't", "think", "that's", "a", "coincidence", "that", "ghostface"]
    words = [{"word": w, "start": n * 0.3, "end": n * 0.3 + 0.25} for n, w in enumerate(texts)]
    transcript = tmp_path / "vo.json"
    transcript.write_text(json.dumps({"language": "en", "words": words}), encoding="utf-8")
    project = tmp_path / "proj"

    async def body(session: ClientSession) -> dict[str, Any]:
        client = Client(session)
        await client.call("init", path=str(project))
        clip = await client.call("import_media", path=str(project), source=str(audio))
        return await client.call(
            "attach_transcript",
            path=str(project),
            clip_id=clip["clip_id"],
            transcript_path=str(transcript),
        )

    attached = anyio.run(_with_server, body)

    assert len(attached["near_duplicates"]) == 1
    hit = attached["near_duplicates"][0]
    assert hit["similarity"] >= 0.5
    assert hit["first_word"] < hit["second_word"]


def _suspect_duration_sources(tmp_path: Path) -> tuple[Path, Path]:
    """A recording where one word's claimed span hides a swallowed retake."""
    audio = tmp_path / "vo.wav"
    _make_wav(audio, tones=[(0.0, 8.0)])

    words = [
        {"word": "so", "start": 0.0, "end": 0.3},
        {"word": "much", "start": 0.3, "end": 0.6},
        {"word": "going", "start": 0.6, "end": 0.9},
        # claims 3.96s against a 0.3s median — the Scream VO's "bit", in miniature.
        {"word": "bit", "start": 0.9, "end": 4.86},
        {"word": "on", "start": 4.86, "end": 5.16},
    ]
    transcript = tmp_path / "vo.json"
    transcript.write_text(json.dumps({"language": "en", "words": words}), encoding="utf-8")
    return audio, transcript


@needs_ffprobe
def test_attach_transcript_flags_suspect_word_durations(tmp_path: Path) -> None:
    """Over the wire: a word running past 3x the median is a lie about
    something, usually a swallowed retake (HISTORY.md § 2).
    HISTORY.md § Suspect word durations at `attach-transcript`.
    """
    audio, transcript = _suspect_duration_sources(tmp_path)
    project = tmp_path / "proj"

    async def body(session: ClientSession) -> dict[str, Any]:
        client = Client(session)
        await client.call("init", path=str(project))
        clip = await client.call("import_media", path=str(project), source=str(audio))
        return await client.call(
            "attach_transcript",
            path=str(project),
            clip_id=clip["clip_id"],
            transcript_path=str(transcript),
        )

    attached = anyio.run(_with_server, body)

    assert len(attached["suspect_durations"]) == 1
    hit = attached["suspect_durations"][0]
    assert hit["index"] == 3
    assert hit["text"] == "bit"


@needs_ffprobe
def test_cut_refuses_a_suspect_boundary_word_without_confirmation(tmp_path: Path) -> None:
    """A flagged word's end is what the cut boundary resolves to, so using one
    unconfirmed would silently cut wherever the hidden retake actually ends.
    """
    audio, transcript = _suspect_duration_sources(tmp_path)
    project = tmp_path / "proj"

    async def body(session: ClientSession) -> dict[str, Any]:
        client = Client(session)
        await client.call("init", path=str(project))
        clip = await client.call("import_media", path=str(project), source=str(audio))
        await client.call(
            "attach_transcript",
            path=str(project),
            clip_id=clip["clip_id"],
            transcript_path=str(transcript),
        )
        await client.call(
            "seed_timeline", path=str(project), clip_id=clip["clip_id"], remove_silences=False
        )
        blocked = await session.call_tool(
            "cut_by_transcript",
            {"path": str(project), "clip_id": clip["clip_id"], "cut": [[3, 4]]},
        )
        confirmed = await client.call(
            "cut_by_transcript",
            path=str(project),
            clip_id=clip["clip_id"],
            cut=[[3, 4]],
            confirm_suspect=True,
        )
        return {"blocked": blocked, "confirmed": confirmed}

    out = anyio.run(_with_server, body)

    assert out["blocked"].is_error
    assert "hides a retake" in out["blocked"].content[0].text
    assert out["confirmed"]["removed"] > 0


@needs_ffprobe
def test_cut_plan_reports_a_suspect_boundary_instead_of_refusing_it(tmp_path: Path) -> None:
    """Refusing to *look* at a flagged boundary would be backwards — checking
    the word is exactly what the refusal above asks the caller to go and do.
    """
    audio, transcript = _suspect_duration_sources(tmp_path)
    project = tmp_path / "proj"

    async def body(session: ClientSession) -> dict[str, Any]:
        client = Client(session)
        await client.call("init", path=str(project))
        clip = await client.call("import_media", path=str(project), source=str(audio))
        await client.call(
            "attach_transcript",
            path=str(project),
            clip_id=clip["clip_id"],
            transcript_path=str(transcript),
        )
        await client.call(
            "seed_timeline", path=str(project), clip_id=clip["clip_id"], remove_silences=False
        )
        planned = await client.call(
            "cut_by_transcript",
            path=str(project),
            clip_id=clip["clip_id"],
            cut=[[3, 4]],
            plan=True,
        )
        return {"planned": planned, "status": await client.call("timeline_status", path=str(project))}

    out = anyio.run(_with_server, body)

    flagged = out["planned"]["suspect_boundaries"]
    assert [hit["index"] for hit in flagged] == [3]
    assert flagged[0]["text"] == "bit"
    assert flagged[0]["range"] == [3, 4]
    # Reported, not applied — the timeline is still untouched.
    assert out["status"]["undo_depth"] == 0


@needs_ffprobe
def test_cut_and_keep_are_mutually_exclusive(tmp_path: Path, sources: tuple[Path, Path]) -> None:
    """Reading a 'keep' as a 'cut' would produce the exact inverse edit."""
    audio, transcript = sources
    project = tmp_path / "proj"

    async def body(session: ClientSession) -> Any:
        client = Client(session)
        await client.call("init", path=str(project))
        clip = await client.call("import_media", path=str(project), source=str(audio))
        await client.call(
            "attach_transcript",
            path=str(project),
            clip_id=clip["clip_id"],
            transcript_path=str(transcript),
        )
        await client.call(
            "seed_timeline", path=str(project), clip_id=clip["clip_id"], remove_silences=False
        )
        return await session.call_tool(
            "cut_by_transcript",
            {"path": str(project), "clip_id": clip["clip_id"], "cut": [[0, 1]], "keep": [[2, 3]]},
        )

    result = anyio.run(_with_server, body)
    assert result.is_error
    assert "exactly one" in result.content[0].text


@needs_ffprobe
def test_cut_by_time_converts_render_time_to_source_and_cuts(
    tmp_path: Path, sources: tuple[Path, Path]
) -> None:
    """Render time equals source time before any cut has landed, so the
    conversion is checkable directly against the fixture's own word times.
    """
    audio, transcript = sources
    project = tmp_path / "proj"

    async def body(session: ClientSession) -> dict[str, Any]:
        client = Client(session)
        await client.call("init", path=str(project))
        clip = await client.call("import_media", path=str(project), source=str(audio))
        await client.call(
            "attach_transcript",
            path=str(project),
            clip_id=clip["clip_id"],
            transcript_path=str(transcript),
        )
        await client.call(
            "seed_timeline", path=str(project), clip_id=clip["clip_id"], remove_silences=False
        )
        return await client.call("cut_by_time", path=str(project), spans=[[3.0, 3.9]])

    out = anyio.run(_with_server, body)

    assert len(out["applied"]) == 1
    pieces = out["applied"][0]["pieces"]
    assert len(pieces) == 1
    assert [w["text"] for w in pieces[0]["words_overlapped"]] == ["w10"]
    assert pieces[0]["context_after"][0]["text"] == "w11"


@needs_ffprobe
def test_cut_by_time_uses_render_time_not_source_time_once_a_prior_cut_has_landed(
    tmp_path: Path, sources: tuple[Path, Path]
) -> None:
    """The core "this is the inverse of timeline_span" claim, pinned against
    the real server rather than only timeline.py.
    """
    audio, transcript = sources
    project = tmp_path / "proj"

    async def body(session: ClientSession) -> dict[str, Any]:
        client = Client(session)
        await client.call("init", path=str(project))
        clip = await client.call("import_media", path=str(project), source=str(audio))
        await client.call(
            "attach_transcript",
            path=str(project),
            clip_id=clip["clip_id"],
            transcript_path=str(transcript),
        )
        await client.call(
            "seed_timeline", path=str(project), clip_id=clip["clip_id"], remove_silences=False
        )
        # Cut w00/w01 (source 0.0-1.9), which shifts the whole timeline left.
        earlier = await client.call(
            "cut_by_transcript", path=str(project), clip_id=clip["clip_id"], cut=[[0, 1]]
        )
        # w10/w11 now sit at render time 1.1-2.9, not their source time 3.0-4.9.
        cut = await client.call("cut_by_time", path=str(project), spans=[[1.1, 2.0]])
        return {"earlier": earlier, "cut": cut}

    out = anyio.run(_with_server, body)

    removed_earlier = out["earlier"]["removed"]
    assert removed_earlier == pytest.approx(1.9, abs=0.01)

    piece = out["cut"]["applied"][0]["pieces"][0]
    assert piece["source_start"] == pytest.approx(1.1 + removed_earlier, abs=0.01)
    assert piece["source_end"] == pytest.approx(2.0 + removed_earlier, abs=0.01)


@needs_ffprobe
def test_cut_by_time_spanning_a_prior_cut_splits_into_two_source_pieces(
    tmp_path: Path, sources: tuple[Path, Path]
) -> None:
    """The end-to-end version of the roadmap's headline scenario: a render-time
    note straddling a seam a prior cut created resolves into two source pieces
    of the same clip, non-adjacent by exactly the earlier cut's width.
    """
    audio, transcript = sources
    project = tmp_path / "proj"

    async def body(session: ClientSession) -> dict[str, Any]:
        client = Client(session)
        await client.call("init", path=str(project))
        clip = await client.call("import_media", path=str(project), source=str(audio))
        await client.call(
            "attach_transcript",
            path=str(project),
            clip_id=clip["clip_id"],
            transcript_path=str(transcript),
        )
        await client.call(
            "seed_timeline", path=str(project), clip_id=clip["clip_id"], remove_silences=False
        )
        earlier = await client.call(
            "cut_by_transcript", path=str(project), clip_id=clip["clip_id"], cut=[[2, 3]]
        )
        cut = await client.call("cut_by_time", path=str(project), spans=[[2.5, 3.5]])
        return {"earlier": earlier, "cut": cut}

    out = anyio.run(_with_server, body)

    pieces = out["cut"]["applied"][0]["pieces"]
    assert len(pieces) == 2
    assert pieces[0]["clip_id"] == pieces[1]["clip_id"]
    gap = pieces[1]["source_start"] - pieces[0]["source_end"]
    assert gap == pytest.approx(out["earlier"]["removed"], abs=0.01)


@needs_ffprobe
def test_cut_by_time_pad_widens_only_the_outer_edges(
    tmp_path: Path, sources: tuple[Path, Path]
) -> None:
    """The one spot a wrong implementation would silently over-cut a live
    neighbour across the seam: pad must reach only the two true outer edges,
    never the inner seam a multi-piece span crosses.
    """
    audio, transcript = sources
    project = tmp_path / "proj"

    async def body(session: ClientSession) -> dict[str, Any]:
        client = Client(session)
        await client.call("init", path=str(project))
        clip = await client.call("import_media", path=str(project), source=str(audio))
        await client.call(
            "attach_transcript",
            path=str(project),
            clip_id=clip["clip_id"],
            transcript_path=str(transcript),
        )
        await client.call(
            "seed_timeline", path=str(project), clip_id=clip["clip_id"], remove_silences=False
        )
        await client.call(
            "cut_by_transcript", path=str(project), clip_id=clip["clip_id"], cut=[[2, 3]]
        )
        return await client.call(
            "cut_by_time", path=str(project), spans=[[2.5, 3.5]], pad=0.2
        )

    out = anyio.run(_with_server, body)
    pieces = out["applied"][0]["pieces"]
    assert len(pieces) == 2

    # Outer edges padded...
    assert pieces[0]["source_start"] == pytest.approx(2.3, abs=0.01)
    assert pieces[1]["source_end"] == pytest.approx(5.6, abs=0.01)
    # ...but the inner seam is not, so a narrow gap on the far side stays intact.
    assert pieces[0]["source_end"] == pytest.approx(3.0, abs=0.01)
    assert pieces[1]["source_start"] == pytest.approx(4.9, abs=0.01)


@needs_ffprobe
def test_cut_by_time_plan_matches_the_real_cut(
    tmp_path: Path, sources: tuple[Path, Path]
) -> None:
    """HISTORY.md § `cut --plan`: a plan runs the identical code path and simply
    skips the write, so a plan and the real cut that follows must agree exactly.
    """
    audio, transcript = sources
    project = tmp_path / "proj"

    async def body(session: ClientSession) -> dict[str, Any]:
        client = Client(session)
        await client.call("init", path=str(project))
        clip = await client.call("import_media", path=str(project), source=str(audio))
        await client.call(
            "attach_transcript",
            path=str(project),
            clip_id=clip["clip_id"],
            transcript_path=str(transcript),
        )
        await client.call(
            "seed_timeline", path=str(project), clip_id=clip["clip_id"], remove_silences=False
        )
        planned = await client.call(
            "cut_by_time", path=str(project), spans=[[3.0, 3.9]], plan=True
        )
        status_after_plan = await client.call("timeline_status", path=str(project))
        cut = await client.call("cut_by_time", path=str(project), spans=[[3.0, 3.9]])
        return {"planned": planned, "status_after_plan": status_after_plan, "cut": cut}

    out = anyio.run(_with_server, body)

    assert out["planned"]["plan"] is True
    assert out["status_after_plan"]["undo_depth"] == 0
    assert out["cut"]["duration_after"] == pytest.approx(out["planned"]["duration_after"], abs=1e-9)
    assert out["cut"]["removed"] == pytest.approx(out["planned"]["removed"], abs=1e-9)
    assert out["cut"]["applied"] == out["planned"]["applied"]


@needs_ffprobe
def test_cut_by_time_reports_requested_removed_versus_removed(
    tmp_path: Path, sources: tuple[Path, Path]
) -> None:
    """`removed == requested_removed` is asserted, not just reported, at
    `pad == 0.0` — spans address the current timeline, so every requested
    render-second is live by construction. `pad > 0` legitimately removes more.
    """
    audio, transcript = sources

    async def _flow(project: Path, pad: float) -> dict[str, Any]:
        async def body(session: ClientSession) -> dict[str, Any]:
            client = Client(session)
            await client.call("init", path=str(project))
            clip = await client.call("import_media", path=str(project), source=str(audio))
            await client.call(
                "attach_transcript",
                path=str(project),
                clip_id=clip["clip_id"],
                transcript_path=str(transcript),
            )
            await client.call(
                "seed_timeline",
                path=str(project),
                clip_id=clip["clip_id"],
                remove_silences=False,
            )
            return await client.call(
                "cut_by_time", path=str(project), spans=[[3.0, 3.9]], pad=pad
            )

        return await _with_server(body)

    unpadded = anyio.run(_flow, tmp_path / "unpadded", 0.0)
    padded = anyio.run(_flow, tmp_path / "padded", 0.5)

    assert unpadded["removed"] == pytest.approx(unpadded["requested_removed"], abs=1e-9)
    assert padded["removed"] > padded["requested_removed"]


@needs_ffprobe
def test_cut_by_time_rejects_overlapping_spans_in_one_call(
    tmp_path: Path, sources: tuple[Path, Path]
) -> None:
    """Overlapping spans are refused, not merged or applied twice — an overlap
    between two watch-notes is almost certainly one flub logged twice.
    """
    audio, transcript = sources
    project = tmp_path / "proj"

    async def body(session: ClientSession) -> Any:
        client = Client(session)
        await client.call("init", path=str(project))
        clip = await client.call("import_media", path=str(project), source=str(audio))
        await client.call(
            "attach_transcript",
            path=str(project),
            clip_id=clip["clip_id"],
            transcript_path=str(transcript),
        )
        await client.call(
            "seed_timeline", path=str(project), clip_id=clip["clip_id"], remove_silences=False
        )
        return await session.call_tool(
            "cut_by_time", {"path": str(project), "spans": [[3.0, 4.0], [3.5, 5.0]]}
        )

    result = anyio.run(_with_server, body)
    assert result.is_error
    text = result.content[0].text
    assert "overlap" in text


@needs_ffprobe
def test_cut_by_time_rejects_a_span_past_the_end(
    tmp_path: Path, sources: tuple[Path, Path]
) -> None:
    """Distinguished from the overlap refusal above by message content, not just
    is_error — an over-eager or wrongly-routed boundary check would still leave
    is_error True while refusing for the wrong reason.
    """
    audio, transcript = sources
    project = tmp_path / "proj"

    async def body(session: ClientSession) -> Any:
        client = Client(session)
        await client.call("init", path=str(project))
        clip = await client.call("import_media", path=str(project), source=str(audio))
        await client.call(
            "attach_transcript",
            path=str(project),
            clip_id=clip["clip_id"],
            transcript_path=str(transcript),
        )
        await client.call(
            "seed_timeline", path=str(project), clip_id=clip["clip_id"], remove_silences=False
        )
        return await session.call_tool(
            "cut_by_time", {"path": str(project), "spans": [[11.0, 20.0]]}
        )

    result = anyio.run(_with_server, body)
    assert result.is_error
    text = result.content[0].text
    assert "outside the timeline" in text


@needs_ffprobe
def test_cut_by_time_refuses_a_suspect_boundary_without_confirmation(tmp_path: Path) -> None:
    """A word overlapped by a (padded) span is refused just like
    `cut_by_transcript`'s own boundary word check.
    """
    audio, transcript = _suspect_duration_sources(tmp_path)
    project = tmp_path / "proj"

    async def body(session: ClientSession) -> dict[str, Any]:
        client = Client(session)
        await client.call("init", path=str(project))
        clip = await client.call("import_media", path=str(project), source=str(audio))
        await client.call(
            "attach_transcript",
            path=str(project),
            clip_id=clip["clip_id"],
            transcript_path=str(transcript),
        )
        await client.call(
            "seed_timeline", path=str(project), clip_id=clip["clip_id"], remove_silences=False
        )
        blocked = await session.call_tool(
            "cut_by_time", {"path": str(project), "spans": [[2.0, 2.5]]}
        )
        confirmed = await client.call(
            "cut_by_time", path=str(project), spans=[[2.0, 2.5]], confirm_suspect=True
        )
        return {"blocked": blocked, "confirmed": confirmed}

    out = anyio.run(_with_server, body)

    assert out["blocked"].is_error
    assert "hides a retake" in out["blocked"].content[0].text
    assert out["confirmed"]["removed"] > 0


@needs_ffprobe
def test_cut_by_time_with_plan_reports_a_suspect_boundary_instead_of_refusing(
    tmp_path: Path,
) -> None:
    """Refusing to *look* at a flagged boundary under `plan` would be
    backwards — checking the word is exactly what the refusal above asks for.
    """
    audio, transcript = _suspect_duration_sources(tmp_path)
    project = tmp_path / "proj"

    async def body(session: ClientSession) -> dict[str, Any]:
        client = Client(session)
        await client.call("init", path=str(project))
        clip = await client.call("import_media", path=str(project), source=str(audio))
        await client.call(
            "attach_transcript",
            path=str(project),
            clip_id=clip["clip_id"],
            transcript_path=str(transcript),
        )
        await client.call(
            "seed_timeline", path=str(project), clip_id=clip["clip_id"], remove_silences=False
        )
        planned = await client.call(
            "cut_by_time", path=str(project), spans=[[2.0, 2.5]], plan=True
        )
        status = await client.call("timeline_status", path=str(project))
        return {"planned": planned, "status": status}

    out = anyio.run(_with_server, body)

    flagged = out["planned"]["suspect_boundaries"]
    assert [hit["index"] for hit in flagged] == [3]
    assert flagged[0]["text"] == "bit"
    assert out["status"]["undo_depth"] == 0


@needs_ffprobe
def test_cut_by_time_on_an_untranscribed_clip_still_cuts(tmp_path: Path) -> None:
    """The cut is the load-bearing operation; the echo is the safety net, and
    degrading it beats refusing a valid render-time cut on a picture-only clip.
    """
    audio = tmp_path / "vo.wav"
    _make_wav(audio, tones=[(0.0, 8.0)])
    project = tmp_path / "proj"

    async def body(session: ClientSession) -> dict[str, Any]:
        client = Client(session)
        await client.call("init", path=str(project))
        clip = await client.call("import_media", path=str(project), source=str(audio))
        await client.call(
            "seed_timeline", path=str(project), clip_id=clip["clip_id"], remove_silences=False
        )
        return await client.call("cut_by_time", path=str(project), spans=[[2.0, 3.0]])

    out = anyio.run(_with_server, body)

    piece = out["applied"][0]["pieces"][0]
    assert piece["words_overlapped"] is None
    assert piece["transcript_missing"] is True
    assert out["duration_after"] == pytest.approx(out["duration_before"] - 1.0, abs=0.01)


def _fake_whisper(path: Path) -> Path:
    """A whisper stand-in for `LUCID_WHISPER`: writes a fixed transcript.

    Real whisper's CLI shape, minus the GPU — `asr.transcribe` only cares that
    the binary accepts these flags and drops `<stem>.json` in `--output_dir`.
    """
    script = path / "fake-whisper.py"
    script.write_text(
        "#!/usr/bin/env python3\n"
        "import argparse, json\n"
        "from pathlib import Path\n"
        "p = argparse.ArgumentParser()\n"
        "p.add_argument('media')\n"
        "p.add_argument('--model')\n"
        "p.add_argument('--output_format')\n"
        "p.add_argument('--word_timestamps')\n"
        "p.add_argument('--output_dir')\n"
        "p.add_argument('--language', default=None)\n"
        "args = p.parse_args()\n"
        "words = [\n"
        "    {'word': 'hello', 'start': 0.0, 'end': 0.4},\n"
        "    {'word': 'from', 'start': 0.5, 'end': 0.8},\n"
        "    {'word': 'the', 'start': 0.9, 'end': 1.0},\n"
        "    {'word': 'stub', 'start': 1.1, 'end': 1.5},\n"
        "]\n"
        "out = Path(args.output_dir) / f'{Path(args.media).stem}.json'\n"
        "out.write_text(json.dumps({'language': args.language or 'en', 'words': words}))\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    return script


@needs_ffprobe
def test_transcribe_runs_whisper_and_attaches_the_result(tmp_path: Path) -> None:
    """transcribe wires asr.transcribe -> parse_whisper -> the transcript cache.

    No real GPU here — LUCID_WHISPER points the server subprocess at a stand-in
    that writes a fixed transcript, so this checks the wiring, not whisper.
    """
    audio = tmp_path / "vo.wav"
    _make_wav(audio, tones=[(0.0, 2.0)], duration=3.0)
    project = tmp_path / "proj"
    server = StdioServerParameters(
        command=sys.executable,
        args=["-m", "lucid.cli", "mcp"],
        env={"LUCID_WHISPER": str(_fake_whisper(tmp_path))},
    )

    async def body(session: ClientSession) -> dict[str, Any]:
        client = Client(session)
        await client.call("init", path=str(project))
        clip = await client.call("import_media", path=str(project), source=str(audio))
        transcribed = await client.call("transcribe", path=str(project), clip_id=clip["clip_id"])
        found = await client.call("get_transcript", path=str(project), clip_id=clip["clip_id"])
        return {"transcribed": transcribed, "found": found}

    out = anyio.run(lambda: _with_server(body, server))

    assert out["transcribed"]["words"] == 4
    assert out["transcribed"]["language"] == "en"
    assert Path(out["transcribed"]["cached"]).exists()
    assert out["found"]["text"] == "hello from the stub"


@needs_ffprobe
def test_captions_follow_the_timeline_not_the_recording(
    tmp_path: Path, sources: tuple[Path, Path]
) -> None:
    """The whole point of generating captions from the project.

    Words 2-3 are cut, so they must be absent from the .ass, and every word
    after them must have moved earlier by the length of the cut.
    """
    audio, transcript = sources
    project = tmp_path / "proj"
    subtitles = tmp_path / "vo.ass"

    async def body(session: ClientSession) -> dict[str, Any]:
        client = Client(session)
        await client.call("init", path=str(project))
        clip = await client.call("import_media", path=str(project), source=str(audio))
        await client.call(
            "attach_transcript",
            path=str(project),
            clip_id=clip["clip_id"],
            transcript_path=str(transcript),
        )
        await client.call(
            "seed_timeline", path=str(project), clip_id=clip["clip_id"], remove_silences=False
        )
        before = await client.call(
            "add_captions", path=str(project), output=str(tmp_path / "before.ass")
        )
        await client.call(
            "cut_by_transcript", path=str(project), clip_id=clip["clip_id"], cut=[[2, 3]]
        )
        after = await client.call(
            "add_captions", path=str(project), output=str(subtitles), max_words=2
        )
        return {"before": before, "after": after}

    out = anyio.run(_with_server, body)
    written = subtitles.read_text(encoding="utf-8")

    # Eight words in, two cut, six captioned — and the drop is reported.
    assert out["before"]["words"] == 8 and out["before"]["words_cut"] == 0
    assert out["after"]["words"] == 6
    assert out["after"]["words_cut"] == 2

    # The fixture names words w<burst><n>, so indices 2-3 are the second burst.
    assert "w10" not in written and "w11" not in written
    assert "w00" in written and "w20" in written and "w30" in written

    # w20 sat at source 6.0. Cutting 3.0-4.9 removed 1.9s ahead of it, so it is
    # now heard at 4.1 — a caption still quoting 6.0 would be the bug.
    assert "0:00:04.10" in written
    assert "0:00:06.00" not in written


@needs_ffprobe
def test_a_stored_style_reaches_the_ass_file_and_survives_a_cut(
    tmp_path: Path, sources: tuple[Path, Path]
) -> None:
    """Caption styling's whole claim, exercised over the wire.

    The style is project state and the captions are derived, so a restyle
    cannot be lost by a later edit — there is nothing coupling the two. The
    agent sets it once and every regeneration picks it back up.
    """
    audio, transcript = sources
    project = tmp_path / "proj"
    subtitles = tmp_path / "vo.ass"

    async def body(session: ClientSession) -> dict[str, Any]:
        client = Client(session)
        await client.call("init", path=str(project))
        clip = await client.call("import_media", path=str(project), source=str(audio))
        await client.call(
            "attach_transcript",
            path=str(project),
            clip_id=clip["clip_id"],
            transcript_path=str(transcript),
        )
        await client.call(
            "seed_timeline", path=str(project), clip_id=clip["clip_id"], remove_silences=False
        )
        styled = await client.call(
            "caption_style", path=str(project), preset="karaoke", size=80, text="yellow"
        )
        # The cut lands *after* the restyle, which is the case that used to
        # have no answer: regenerate has to come back styled.
        await client.call(
            "cut_by_transcript", path=str(project), clip_id=clip["clip_id"], cut=[[2, 3]]
        )
        view = await client.call("caption_view", path=str(project))
        written = await client.call("add_captions", path=str(project), output=str(subtitles))
        read_back = await client.call("caption_style", path=str(project))
        return {"styled": styled, "view": view, "written": written, "read_back": read_back}

    out = anyio.run(_with_server, body)
    text = subtitles.read_text(encoding="utf-8")

    assert out["styled"]["written"] is True
    assert out["styled"]["changed"] == ["preset", "size", "text"]
    assert out["styled"]["stored"] == {"preset": "karaoke", "size": 80, "text": "&H0000D4FF"}

    # Stored, not flattened: the manifest carries three fields and the rest
    # still come from the preset.
    assert out["read_back"]["stored"] == out["styled"]["stored"]
    assert out["read_back"]["written"] is False, "reading is not a mutation"

    assert "Style: lucid,DejaVu Sans,80," in text
    assert "\\k" in text, "karaoke survived the cut that followed the restyle"
    # SecondaryColour is the *unspoken* colour — the swap this layer exists for.
    assert out["view"]["style"]["ass"]["text"] == "&H0000D4FF"
    assert out["view"]["style"]["resolved"]["text"] == "#ffd400ff"

    # One derivation behind both: what the window would draw and what the file
    # contains are the same cues.
    assert len(out["view"]["cues"]) == out["written"]["cues"]
    assert out["view"]["words"] == out["written"]["words"] == 6
    assert out["view"]["words_cut"] == 2


def test_canvas_over_the_wire(tmp_path: Path) -> None:
    """Registration and the `-C` binding, plus the one field feeding both
    derivations — a project with no footage still has a canvas to report."""
    project = tmp_path / "proj"

    async def body(session: ClientSession) -> dict[str, Any]:
        client = Client(session)
        await client.call("init", path=str(project))
        derived = await client.call("canvas", path=str(project))
        planned = await client.call("canvas", path=str(project), size="1080x1920", plan=True)
        set_ = await client.call("canvas", path=str(project), size="1080x1920")
        after_plan = await client.call("canvas", path=str(project))
        return {"derived": derived, "planned": planned, "set": set_, "after": after_plan}

    out = anyio.run(_with_server, body)

    assert out["derived"]["canvas"] == "1920x1080"
    assert out["derived"]["source"] == "default"
    assert out["planned"]["written"] is False
    assert out["set"]["aspect"] == "9:16"
    assert out["set"]["routes_through"] == "mlt"
    assert out["after"]["canvas"] == "1080x1920", "the plan call left the set one alone"


def test_canvas_refusal_travels_as_an_error(tmp_path: Path) -> None:
    """An odd edge has to come back as a refusal naming the number, not as a
    canvas one pixel different from the one asked for."""
    project = tmp_path / "proj"

    async def body(session: ClientSession) -> dict[str, Any]:
        client = Client(session)
        await client.call("init", path=str(project))
        result = await session.call_tool(
            "canvas", {"path": str(project), "size": "1081x1920"}
        )
        return {"is_error": result.is_error, "text": result.content[0].text}

    out = anyio.run(_with_server, body)

    assert out["is_error"]
    assert "even" in out["text"]


@needs_ffprobe
def test_caption_style_plan_writes_nothing(tmp_path: Path, sources: tuple[Path, Path]) -> None:
    audio, transcript = sources
    project = tmp_path / "proj"

    async def body(session: ClientSession) -> dict[str, Any]:
        client = Client(session)
        await client.call("init", path=str(project))
        clip = await client.call("import_media", path=str(project), source=str(audio))
        await client.call(
            "attach_transcript",
            path=str(project),
            clip_id=clip["clip_id"],
            transcript_path=str(transcript),
        )
        planned = await client.call("caption_style", path=str(project), size=99, plan=True)
        after = await client.call("caption_style", path=str(project))
        return {"planned": planned, "after": after}

    out = anyio.run(_with_server, body)

    assert out["planned"]["resolved"]["size"] == 99
    assert out["planned"]["written"] is False
    assert out["after"]["resolved"]["size"] == 64, "the project never took it"


@needs_ffprobe
def test_caption_view_reports_a_missing_transcript_rather_than_failing(
    tmp_path: Path, sources: tuple[Path, Path]
) -> None:
    """The view a person has open while making exactly this mistake."""
    audio, _ = sources
    project = tmp_path / "proj"

    async def body(session: ClientSession) -> dict[str, Any]:
        client = Client(session)
        await client.call("init", path=str(project))
        clip = await client.call("import_media", path=str(project), source=str(audio))
        await client.call(
            "seed_timeline", path=str(project), clip_id=clip["clip_id"], remove_silences=False
        )
        return await client.call("caption_view", path=str(project))

    out = anyio.run(_with_server, body)

    assert out["cues"] == []
    assert "transcript" in out["cues_error"]
    assert out["style"]["resolved"]["preset"] == "clean", "still says what the look is"


def _heard(path: Path, words: list[str]) -> Path:
    """A transcript of a "render", as whisper would have dumped it.

    Timings are plausible but arbitrary — `verify` compares word *order*, and
    the timings of a render's own transcript are never trusted for anything
    else (CLAUDE.md).
    """
    payload = {
        "language": "en",
        "words": [{"word": w, "start": n * 1.0, "end": n * 1.0 + 0.9} for n, w in enumerate(words)],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


async def _cut_project(client: Client, project: Path, audio: Path, transcript: Path) -> None:
    """init -> import -> attach -> seed -> cut words 2-3, leaving six words."""
    await client.call("init", path=str(project))
    clip = await client.call("import_media", path=str(project), source=str(audio))
    await client.call(
        "attach_transcript",
        path=str(project),
        clip_id=clip["clip_id"],
        transcript_path=str(transcript),
    )
    await client.call(
        "seed_timeline", path=str(project), clip_id=clip["clip_id"], remove_silences=False
    )
    await client.call(
        "cut_by_transcript", path=str(project), clip_id=clip["clip_id"], cut=[[2, 3]]
    )


@needs_ffprobe
def test_verify_matches_a_render_that_says_what_the_timeline_expects(
    tmp_path: Path, sources: tuple[Path, Path]
) -> None:
    """The expected sequence is the timeline's, not the transcript's.

    Words 2-3 were cut, so a render that plays the remaining six is clean —
    against the untrimmed transcript those same six words would look like four
    dropped ones.
    """
    audio, transcript = sources
    project = tmp_path / "proj"
    heard = _heard(tmp_path / "render.json", ["w00", "w01", "w20", "w21", "w30", "w31"])

    async def body(session: ClientSession) -> Any:
        client = Client(session)
        await _cut_project(client, project, audio, transcript)
        # The wav stands in for a render of this timeline; the transcript is
        # supplied, so no whisper is needed anywhere in this suite.
        return await client.call(
            "verify", path=str(project), render=str(audio), transcript_path=str(heard)
        )

    out = anyio.run(_with_server, body)

    assert out["expected_words"] == 6 and out["heard_words"] == 6
    assert out["similarity"] == 1.0
    assert out["repeated"] == [] and out["dropped"] == []
    assert out["diff"] == []
    assert out["words_cut_from_transcript"] == 2
    assert out["timeline_duration"] == pytest.approx(10.1, abs=0.05)
    assert out["render_duration"] == pytest.approx(12.0, abs=0.05)
    # ASR was skipped, so nothing was cached.
    assert "heard_transcript" not in out


@needs_ffprobe
def test_verify_catches_a_phrase_the_render_plays_twice(
    tmp_path: Path, sources: tuple[Path, Path]
) -> None:
    """The retake case, which is why verify exists at all (HISTORY.md § 1)."""
    audio, transcript = sources
    project = tmp_path / "proj"
    heard = _heard(
        tmp_path / "render.json",
        ["w00", "w01", "w20", "w21", "w20", "w21", "w30", "w31"],
    )

    async def body(session: ClientSession) -> Any:
        client = Client(session)
        await _cut_project(client, project, audio, transcript)
        return await client.call(
            "verify", path=str(project), render=str(audio), transcript_path=str(heard)
        )

    out = anyio.run(_with_server, body)

    assert len(out["repeated"]) == 1
    assert out["repeated"][0]["text"] == "w20 w21"
    assert out["repeated"][0]["at_heard_word"] == 4
    assert out["dropped"] == []
    assert out["heard_words"] == 8 and out["expected_words"] == 6
    assert out["similarity"] < 1.0


@needs_ffprobe
def test_verify_reports_which_pass_produced_the_words_it_heard(
    tmp_path: Path, sources: tuple[Path, Path]
) -> None:
    """`windowed` is a request to transcribe, and a supplied transcript is not one.

    Reporting mode "windowed" here because the flag was set would tell a reader
    the render had been through the pass that catches a collapsed retake when it
    had not — and a clean result is exactly what they would act on.
    """
    audio, transcript = sources
    project = tmp_path / "proj"
    heard = _heard(tmp_path / "render.json", ["w00", "w01", "w20", "w21", "w30", "w31"])

    async def body(session: ClientSession) -> Any:
        client = Client(session)
        await _cut_project(client, project, audio, transcript)
        return await client.call(
            "verify",
            path=str(project),
            render=str(audio),
            transcript_path=str(heard),
            windowed=True,
        )

    out = anyio.run(_with_server, body)

    assert out["mode"] == "supplied"
    assert "windows" not in out


@needs_ffprobe
def test_verify_reports_sound_in_a_hole_the_word_map_calls_empty(
    tmp_path: Path, sources: tuple[Path, Path]
) -> None:
    """The energy arbiter, end to end and over the wire.

    The render's word map accounts for the first burst and the last. Two more
    bursts play in between, and no transcript on either side of the diff has a
    word for them — which is the exact shape of the 4.12 s "gap" holding 2.4 s
    of speech on the Scream v1 export.
    """
    audio, transcript = sources
    project = tmp_path / "proj"
    render_words = [
        {"word": "w00", "start": 0.0, "end": 0.9},
        {"word": "w01", "start": 1.0, "end": 1.9},
        {"word": "w30", "start": 9.0, "end": 9.9},
        {"word": "w31", "start": 10.0, "end": 10.9},
    ]
    heard = tmp_path / "render.json"
    heard.write_text(json.dumps({"language": "en", "words": render_words}), encoding="utf-8")

    async def body(session: ClientSession) -> Any:
        client = Client(session)
        await _cut_project(client, project, audio, transcript)
        return await client.call(
            "verify", path=str(project), render=str(audio), transcript_path=str(heard)
        )

    out = anyio.run(_with_server, body)

    gaps = out["loud_gaps"]["gaps"]
    assert len(gaps) == 1
    assert (gaps[0]["start"], gaps[0]["end"]) == (1.9, 9.0)
    # The 3-5 and 6-8 bursts, and nothing else in there. A shade over 4.0s:
    # the fixture is written at 22050 Hz and measured at 8000, and the
    # resampler's ring smears each of the four burst edges into its 20ms frame.
    assert gaps[0]["sound_seconds"] == pytest.approx(4.0, abs=0.3)


needs_auto_editor = pytest.mark.skipif(
    shutil.which("auto-editor") is None and not (Path.home() / ".local/bin/auto-editor").exists(),
    reason="auto-editor is not installed",
)


@needs_ffprobe
@needs_auto_editor
def test_nle_export_uses_a_frame_rate_not_the_audio_timebase(
    tmp_path: Path, sources: tuple[Path, Path]
) -> None:
    """The v3 timebase becomes MLT's <profile frame_rate_num>.

    Audio projects run on a millisecond timebase for cut precision, and letting
    that reach the export hands Kdenlive a 1000fps timeline. Caught on the real
    Scream VO, so it is pinned here.
    """
    audio, transcript = sources
    project = tmp_path / "proj"
    out = tmp_path / "out.kdenlive"

    async def body(session: ClientSession) -> Any:
        client = Client(session)
        await client.call("init", path=str(project))
        clip = await client.call("import_media", path=str(project), source=str(audio))
        await client.call(
            "attach_transcript",
            path=str(project),
            clip_id=clip["clip_id"],
            transcript_path=str(transcript),
        )
        await client.call(
            "seed_timeline", path=str(project), clip_id=clip["clip_id"], remove_silences=False
        )
        return await client.call("export", path=str(project), output=str(out))

    result = anyio.run(_with_server, body)

    assert result["timebase"] == 30.0
    written = Path(result["output"]).read_text(encoding="utf-8")
    assert 'frame_rate_num="30"' in written
    assert 'frame_rate_num="1000"' not in written


@needs_ffprobe
@needs_auto_editor
def test_rendering_keeps_the_millisecond_timebase(
    tmp_path: Path, sources: tuple[Path, Path]
) -> None:
    """Media renders are not frame-bound, so precision is kept there."""
    audio, transcript = sources
    project = tmp_path / "proj"

    async def body(session: ClientSession) -> Any:
        client = Client(session)
        await client.call("init", path=str(project))
        clip = await client.call("import_media", path=str(project), source=str(audio))
        await client.call(
            "attach_transcript",
            path=str(project),
            clip_id=clip["clip_id"],
            transcript_path=str(transcript),
        )
        await client.call(
            "seed_timeline", path=str(project), clip_id=clip["clip_id"], remove_silences=False
        )
        return await client.call(
            "export", path=str(project), output=str(tmp_path / "out.wav"), export_format=None
        )

    assert anyio.run(_with_server, body)["timebase"] == 1000.0


# -- the picture half: frame counts --------------------------------------

def _melt_available() -> bool:
    """Ask lucid's own resolver, so the guard skips exactly when the check would."""
    try:
        picture.melt_command()
    except picture.PictureError:
        return False
    return True


needs_melt = pytest.mark.skipif(
    not _melt_available(),
    reason="melt is installed neither on PATH nor in the Kdenlive flatpak",
)


def _make_video(path: Path, *, duration: float = 12.0, fps: int = 30) -> None:
    """A real encoded video, because the check counts packets in a real one."""
    subprocess.run(
        [
            "ffmpeg", "-y", "-loglevel", "error",
            "-f", "lavfi", "-i", f"testsrc=size=160x120:rate={fps}:duration={duration}",
            "-f", "lavfi", "-i", f"sine=frequency=440:duration={duration}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
            str(path),
        ],
        check=True,
        capture_output=True,
    )  # fmt: skip


def _make_video_with_mid_black(
    path: Path, *, before: float = 4.0, black: float = 2.0, after: float = 6.0, fps: int = 30
) -> None:
    """testsrc/black/testsrc concatenated: a real black region well before the tail."""
    subprocess.run(
        [
            "ffmpeg", "-y", "-loglevel", "error",
            "-f", "lavfi", "-i", f"testsrc=size=160x120:rate={fps}:duration={before}",
            "-f", "lavfi", "-i", f"color=black:size=160x120:rate={fps}:duration={black}",
            "-f", "lavfi", "-i", f"testsrc=size=160x120:rate={fps}:duration={after}",
            "-f", "lavfi", "-i", f"sine=frequency=440:duration={before + black + after}",
            "-filter_complex", "[0:v][1:v][2:v]concat=n=3:v=1:a=0[v]",
            "-map", "[v]", "-map", "3:a",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
            str(path),
        ],
        check=True,
        capture_output=True,
    )  # fmt: skip


def _make_video_with_tail_black_frame(path: Path, *, duration: float = 12.0, fps: int = 30) -> None:
    """`duration` of testsrc plus exactly one appended black frame.

    Constructs `delta == picture.KNOWN_TAIL_FRAME` directly against a plain
    render, without going anywhere near melt or auto-editor's kdenlive
    export — the defect those produce is that a render ends up exactly this
    shape, so building the shape by hand pins the *reporting* the same way
    `test_melt_is_asked_what_it_would_render_before_anything_is_rendered`
    pins melt's, without needing melt installed to run it.
    """
    frame = 1.0 / fps
    subprocess.run(
        [
            "ffmpeg", "-y", "-loglevel", "error",
            "-f", "lavfi", "-i", f"testsrc=size=160x120:rate={fps}:duration={duration}",
            "-f", "lavfi", "-t", f"{frame:.6f}", "-i", f"color=black:size=160x120:rate={fps}",
            "-f", "lavfi", "-i", f"sine=frequency=440:duration={duration + frame}",
            "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0[v]",
            "-map", "[v]", "-map", "2:a",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
            str(path),
        ],
        check=True,
        capture_output=True,
    )  # fmt: skip


async def _seeded(client: Client, project: Path, source: Path, transcript: Path | None) -> str:
    """init -> import -> (transcript) -> seed, the preamble every case below wants."""
    await client.call("init", path=str(project))
    clip = await client.call("import_media", path=str(project), source=str(source))
    if transcript is not None:
        await client.call(
            "attach_transcript",
            path=str(project),
            clip_id=clip["clip_id"],
            transcript_path=str(transcript),
        )
    await client.call(
        "seed_timeline", path=str(project), clip_id=clip["clip_id"], remove_silences=False
    )
    return str(clip["clip_id"])


@needs_ffprobe
def test_check_frames_reports_the_export_grid_with_no_target(
    tmp_path: Path, sources: tuple[Path, Path]
) -> None:
    """The cheap call: what the timeline will be, before anything is exported."""
    audio, transcript = sources
    project = tmp_path / "proj"

    async def body(session: ClientSession) -> Any:
        client = Client(session)
        await _seeded(Client(session), project, audio, transcript)
        return await client.call("check_frames", path=str(project))

    result = anyio.run(_with_server, body)

    # An audio-only project has no picture to take a rate from, so the export
    # default applies — the same 30 the NLE export would write.
    assert result["fps"] == 30.0
    assert result["expected_frames"] == 360
    assert result["expected_duration"] == pytest.approx(12.0, abs=0.001)
    # Nothing was compared, so there is no verdict to read.
    assert "agrees" not in result


@needs_ffprobe
@needs_ffmpeg
@needs_auto_editor
def test_a_render_of_the_current_timeline_agrees_frame_for_frame(tmp_path: Path) -> None:
    """The check passing means exactly this, and it is checked against a real render."""
    source = tmp_path / "pic.mp4"
    _make_video(source)
    project = tmp_path / "proj"
    render = tmp_path / "out.mp4"

    words = [{"word": f"w{i:02d}", "start": i * 0.5, "end": i * 0.5 + 0.4} for i in range(24)]
    transcript = tmp_path / "pic.json"
    transcript.write_text(json.dumps({"language": "en", "words": words}), encoding="utf-8")

    async def body(session: ClientSession) -> Any:
        client = Client(session)
        clip = await _seeded(client, project, source, transcript)
        # Cut, so the count is of an edit rather than of an untouched source.
        await client.call(
            "cut_by_transcript", path=str(project), clip_id=clip, cut=[[4, 6], [14, 16]]
        )
        await client.call(
            "export", path=str(project), output=str(render), export_format=None
        )
        return await client.call("check_frames", path=str(project), target=str(render))

    result = anyio.run(_with_server, body)

    assert result["target_kind"] == "render"
    assert result["expected_frames"] == 276
    assert result["target_frames"] == 276
    assert result["delta"] == 0
    assert result["agrees"] is True


@needs_ffprobe
@needs_ffmpeg
@needs_auto_editor
def test_a_stale_render_is_caught_by_its_frame_count(tmp_path: Path) -> None:
    """The defect the check is for: a render that is no longer of this timeline.

    Rendering and then cutting again is the easy way to ship the previous
    edit — the file on disk still opens, still plays, and is simply the wrong
    one. Its length is the tell, and nothing else in lucid was looking at it.
    """
    source = tmp_path / "pic.mp4"
    _make_video(source)
    project = tmp_path / "proj"
    render = tmp_path / "stale.mp4"

    words = [{"word": f"w{i:02d}", "start": i * 0.5, "end": i * 0.5 + 0.4} for i in range(24)]
    transcript = tmp_path / "pic.json"
    transcript.write_text(json.dumps({"language": "en", "words": words}), encoding="utf-8")

    async def body(session: ClientSession) -> Any:
        client = Client(session)
        clip = await _seeded(client, project, source, transcript)
        await client.call(
            "export", path=str(project), output=str(render), export_format=None
        )
        await client.call(
            "cut_by_transcript", path=str(project), clip_id=clip, cut=[[4, 6], [14, 16]]
        )
        return await client.call("check_frames", path=str(project), target=str(render))

    result = anyio.run(_with_server, body)

    assert result["agrees"] is False
    # 360 frames of the uncut source against a 276-frame timeline.
    assert result["target_frames"] == 360
    assert result["expected_frames"] == 276
    assert result["delta"] == 84


@needs_ffprobe
@needs_auto_editor
def test_an_audio_only_render_has_no_frames_and_says_so(
    tmp_path: Path, sources: tuple[Path, Path]
) -> None:
    """A VO project is the ordinary case, and it is not a failed check.

    `agrees` is null rather than false: nothing disagreed, there was simply
    nothing with frames in it to compare.
    """
    audio, transcript = sources
    project = tmp_path / "proj"
    render = tmp_path / "out.wav"

    async def body(session: ClientSession) -> Any:
        client = Client(session)
        await _seeded(client, project, audio, transcript)
        await client.call(
            "export", path=str(project), output=str(render), export_format=None
        )
        return await client.call("check_frames", path=str(project), target=str(render))

    result = anyio.run(_with_server, body)

    assert result["agrees"] is None
    assert result["target_frames"] is None
    assert result["expected_frames"] == 360
    assert "no video stream" in result["notes"][0]
    # The duration is still there to compare by hand, which is the advice given.
    assert result["target_duration"] == pytest.approx(result["expected_duration"], abs=0.05)


@pytest.fixture
def visible_tmp() -> Iterator[Path]:
    """A working directory melt can actually read.

    pytest's `tmp_path` is under /tmp, and **the Kdenlive flatpak's /tmp is not
    the host's** — `filesystems=host` does not cover it (HISTORY.md § 4). melt
    pointed at one prints "Failed to load" and **exits 0**, so a melt test using
    `tmp_path` would silently stop testing melt and start testing the
    empty-output guard instead.
    """
    root = Path(tempfile.mkdtemp(prefix="lucid-melt-", dir=Path.home()))
    try:
        yield root
    finally:
        shutil.rmtree(root, ignore_errors=True)


@needs_ffprobe
@needs_auto_editor
@needs_melt
def test_melt_is_asked_what_it_would_render_before_anything_is_rendered(
    visible_tmp: Path,
) -> None:
    """The load-bearing case: the NLE project checked without paying for a render.

    On this box the answer is the timeline's count plus one — auto-editor's
    kdenlive export declares the tractors' frame-inclusive `out` as a frame
    count, so melt renders a trailing black frame (picture.KNOWN_TAIL_FRAME).
    That is upstream's bug, not lucid's, so this pins the *reporting* rather
    than the +1: a delta of 0 here would mean auto-editor had fixed it, and the
    thing that must stay true either way is that the note travels with the
    delta it explains.
    """
    audio, transcript = _make_sources(visible_tmp)
    project = visible_tmp / "proj"
    exported = visible_tmp / "out.kdenlive"

    async def body(session: ClientSession) -> Any:
        client = Client(session)
        await _seeded(client, project, audio, transcript)
        written = await client.call("export", path=str(project), output=str(exported))
        return await client.call("check_frames", path=str(project), target=written["output"])

    result = anyio.run(_with_server, body)

    assert result["target_kind"] == "nle-project"
    assert result["expected_frames"] == 360
    assert result["delta"] in (0, picture.KNOWN_TAIL_FRAME)
    assert result["agrees"] is (result["delta"] == 0)
    if result["delta"] == picture.KNOWN_TAIL_FRAME:
        assert any("trailing black frame" in note for note in result["notes"])


# -- the picture half: black runs and spot-checked frames -----------------


@needs_ffprobe
@needs_ffmpeg
def test_check_black_reports_clean_when_nothing_is_black(tmp_path: Path) -> None:
    """A plain render, matching the timeline frame for frame: nothing to explain."""
    source = tmp_path / "pic.mp4"
    _make_video(source)
    project = tmp_path / "proj"

    async def body(session: ClientSession) -> Any:
        client = Client(session)
        await _seeded(client, project, source, None)
        return await client.call("check_black", path=str(project), target=str(source))

    result = anyio.run(_with_server, body)

    assert result["clean"] is True
    assert result["runs"] == []


@needs_ffprobe
@needs_ffmpeg
def test_check_black_catches_a_black_stretch_inside_the_picture(tmp_path: Path) -> None:
    """The actual defect this op exists for, well before the tail."""
    source = tmp_path / "pic.mp4"
    _make_video(source)
    target = tmp_path / "mid-black.mp4"
    _make_video_with_mid_black(target)  # 4s testsrc + 2s black + 6s testsrc = 12s
    project = tmp_path / "proj"

    async def body(session: ClientSession) -> Any:
        client = Client(session)
        await _seeded(client, project, source, None)
        return await client.call("check_black", path=str(project), target=str(target))

    result = anyio.run(_with_server, body)

    assert len(result["runs"]) == 1
    run = result["runs"][0]
    assert run["inside_expected_picture"] is True
    assert run["explained"] is False
    assert result["clean"] is False


@needs_ffprobe
@needs_ffmpeg
def test_check_black_explains_the_known_tail_frame(tmp_path: Path) -> None:
    """Pins the reporting, per the same philosophy as the melt tail-frame test:
    a clean result here would mean the render no longer carries the defect.
    """
    source = tmp_path / "pic.mp4"
    _make_video(source)
    target = tmp_path / "tail-black.mp4"
    _make_video_with_tail_black_frame(target, duration=12.0)  # 360 + 1 black frame
    project = tmp_path / "proj"

    async def body(session: ClientSession) -> Any:
        client = Client(session)
        await _seeded(client, project, source, None)
        return await client.call("check_black", path=str(project), target=str(target))

    result = anyio.run(_with_server, body)

    assert len(result["runs"]) == 1
    run = result["runs"][0]
    assert run["explained"] is True
    assert picture.TAIL_FRAME_NOTE in run["note"]
    assert result["clean"] is True


@needs_ffprobe
def test_check_black_on_audio_only_target_says_so(tmp_path: Path, sources: tuple[Path, Path]) -> None:
    """A VO project is the ordinary case, not a failure: nothing to scan for black."""
    audio, transcript = sources
    project = tmp_path / "proj"

    async def body(session: ClientSession) -> Any:
        client = Client(session)
        await _seeded(client, project, audio, transcript)
        return await client.call("check_black", path=str(project), target=str(audio))

    result = anyio.run(_with_server, body)

    assert result["clean"] is None
    assert result["runs"] == []
    assert "no video stream" in result["notes"][0]


@needs_ffprobe
@needs_ffmpeg
def test_spot_frames_samples_evenly_and_writes_pngs(tmp_path: Path) -> None:
    """The cheap happy path: evenly-spaced samples, each pulled to a real PNG."""
    source = tmp_path / "pic.mp4"
    _make_video(source)
    project = tmp_path / "proj"

    async def body(session: ClientSession) -> Any:
        client = Client(session)
        await _seeded(client, project, source, None)
        return await client.call(
            "spot_frames", path=str(project), target=str(source), count=3
        )

    result = anyio.run(_with_server, body)

    assert len(result["frames"]) == 3
    for i, frame in enumerate(result["frames"]):
        assert Path(frame["png"]).exists()
        assert isinstance(frame["YAVG"], float)
        assert frame["origin"] == "sampled"
        # duration 12.0 / 3 samples: midpoints at 2, 6, 10.
        assert frame["time"] == pytest.approx(4.0 * (i + 0.5), abs=0.05)


@needs_ffprobe
@needs_ffmpeg
def test_spot_frames_merges_explicit_times_with_sampled_ones(tmp_path: Path) -> None:
    source = tmp_path / "pic.mp4"
    _make_video(source)
    project = tmp_path / "proj"

    async def body(session: ClientSession) -> Any:
        client = Client(session)
        await _seeded(client, project, source, None)
        return await client.call(
            "spot_frames", path=str(project), target=str(source), count=2, times=[1.0]
        )

    result = anyio.run(_with_server, body)

    origins = [f["origin"] for f in result["frames"]]
    times = [f["time"] for f in result["frames"]]
    assert sorted(origins) == ["explicit", "sampled", "sampled"]
    assert times == sorted(times)


@needs_ffprobe
@needs_ffmpeg
@needs_auto_editor
def test_spot_frames_echoes_the_word_at_a_sample(tmp_path: Path) -> None:
    """A sample landing inside a known word's span reports that word, in context."""
    source = tmp_path / "pic.mp4"
    _make_video(source)
    project = tmp_path / "proj"
    render = tmp_path / "out.mp4"

    words = [{"word": f"w{i:02d}", "start": i * 0.5, "end": i * 0.5 + 0.4} for i in range(24)]
    transcript = tmp_path / "pic.json"
    transcript.write_text(json.dumps({"language": "en", "words": words}), encoding="utf-8")

    async def body(session: ClientSession) -> Any:
        client = Client(session)
        clip = await _seeded(client, project, source, transcript)
        await client.call(
            "cut_by_transcript", path=str(project), clip_id=clip, cut=[[4, 6], [14, 16]]
        )
        await client.call("export", path=str(project), output=str(render), export_format=None)
        return await client.call(
            "spot_frames", path=str(project), target=str(render), count=0, times=[0.1]
        )

    result = anyio.run(_with_server, body)

    assert result["mapping_trusted"] is True
    frame = result["frames"][0]
    assert frame["clip_id"] is not None
    assert frame["word"]["text"] == "w00"
    assert frame["context_after"][0]["text"] == "w01"


@needs_ffprobe
@needs_ffmpeg
@needs_auto_editor
def test_spot_frames_trusts_a_render_checked_at_a_different_export_rate(
    tmp_path: Path,
) -> None:
    """`edit.duration` is fixed to whatever rate the project's timeline was
    last persisted at (a 24fps source here) and cannot see a *different*
    `fps` a caller asks `spot_frames` to check against — `expected_duration`
    (`frame_total(edit, rate) / rate`), computed at that same `fps`, can.

    Twelve 0.07s keep-ranges against a 24fps source persist to exactly
    1.000s of `edit.duration`. The identical timeline, independently laid
    out at 30fps (a legitimate, supported `spot_frames(..., fps=...)`
    override — e.g. checking a render taken at a different rate than the
    project's own), really runs to 31 frames / 1.0333s, not 1.000s. A render
    built to exactly that 31-frame length is the genuinely correct answer at
    `fps=30`; comparing it against `edit.duration` (1.000s, a different
    rate's number) instead would wrongly call it stale.
    """
    source = tmp_path / "pic.mp4"
    subprocess.run(
        [
            "ffmpeg", "-y", "-loglevel", "error",
            "-f", "lavfi", "-i", "testsrc=size=160x120:rate=24:duration=41.0",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=41.0",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
            str(source),
        ],
        check=True,
        capture_output=True,
    )  # fmt: skip
    project = tmp_path / "proj"
    render = tmp_path / "out.mp4"
    subprocess.run(
        [
            "ffmpeg", "-y", "-loglevel", "error",
            "-f", "lavfi", "-i", "testsrc=size=160x120:rate=30",
            "-frames:v", "31", "-c:v", "libx264", "-pix_fmt", "yuv420p",
            str(render),
        ],
        check=True,
        capture_output=True,
    )  # fmt: skip

    words = [{"word": f"w{i:02d}", "start": i * 0.5, "end": i * 0.5 + 0.07} for i in range(12)]
    transcript = tmp_path / "pic.json"
    transcript.write_text(json.dumps({"language": "en", "words": words}), encoding="utf-8")

    async def body(session: ClientSession) -> Any:
        client = Client(session)
        clip = await _seeded(client, project, source, transcript)
        await client.call(
            "cut_by_transcript",
            path=str(project),
            clip_id=clip,
            keep=[[i, i] for i in range(12)],
        )
        return await client.call(
            "spot_frames", path=str(project), target=str(render), count=1, fps=30.0
        )

    result = anyio.run(_with_server, body)

    assert result["expected_duration"] == pytest.approx(31 / 30, abs=1e-6)
    assert result["mapping_trusted"] is True
    assert "notes" not in result


@needs_ffprobe
@needs_ffmpeg
@needs_auto_editor
def test_spot_frames_refuses_word_mapping_on_a_stale_render(tmp_path: Path) -> None:
    """A render taken before a second cut must not silently map to the wrong words."""
    source = tmp_path / "pic.mp4"
    _make_video(source)
    project = tmp_path / "proj"
    render = tmp_path / "stale.mp4"

    words = [{"word": f"w{i:02d}", "start": i * 0.5, "end": i * 0.5 + 0.4} for i in range(24)]
    transcript = tmp_path / "pic.json"
    transcript.write_text(json.dumps({"language": "en", "words": words}), encoding="utf-8")

    async def body(session: ClientSession) -> Any:
        client = Client(session)
        clip = await _seeded(client, project, source, transcript)
        await client.call("export", path=str(project), output=str(render), export_format=None)
        await client.call(
            "cut_by_transcript", path=str(project), clip_id=clip, cut=[[4, 6], [14, 16]]
        )
        return await client.call(
            "spot_frames", path=str(project), target=str(render), count=2
        )

    result = anyio.run(_with_server, body)

    assert result["mapping_trusted"] is False
    assert result["notes"]
    for frame in result["frames"]:
        assert "clip_id" not in frame
        assert "word" not in frame
        assert Path(frame["png"]).exists()
        assert isinstance(frame["YAVG"], float)


@needs_ffprobe
def test_spot_frames_on_audio_only_target_says_so(
    tmp_path: Path, sources: tuple[Path, Path]
) -> None:
    audio, transcript = sources
    project = tmp_path / "proj"

    async def body(session: ClientSession) -> Any:
        client = Client(session)
        await _seeded(client, project, audio, transcript)
        return await client.call("spot_frames", path=str(project), target=str(audio))

    result = anyio.run(_with_server, body)

    assert result["has_video"] is False
    assert result["frames"] == []


def test_spot_frames_refuses_zero_samples_with_no_explicit_times(tmp_path: Path) -> None:
    """count=0 with no explicit times names nothing to sample — refused up front,
    before any project or media is even touched.
    """
    project = tmp_path / "proj"

    async def body(session: ClientSession) -> Any:
        return await session.call_tool(
            "spot_frames", {"path": str(project), "target": str(tmp_path / "nope.mp4"), "count": 0}
        )

    result = anyio.run(_with_server, body)

    assert result.is_error
    assert "nothing to sample" in result.content[0].text


# -- attenuate_noises -------------------------------------------------------


def _db_at(env: list[float], t: float) -> float:
    return energy._db(env[int(t / energy.FRAME)])


def _write_wav_at_rate(
    path: Path, *, tones: list[tuple[float, float]], duration: float, rate: int
) -> None:
    """Like `_make_wav`, but at an explicit sample rate.

    Written directly at `energy.RATE` for these fixtures so `energy.decode`'s
    resample to that same rate is a no-op — `_make_wav`'s 22050 Hz is fine
    when bursts sit a full second from a word edge, but these fixtures place
    a burst right up against one, and the resampler's ring (documented at
    `test_verify_reports_sound_in_a_hole_the_word_map_calls_empty`) would
    smear a spurious ~20ms run onto the wrong side of the boundary.
    """
    with wave.open(str(path), "w") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        frames = bytearray()
        for i in range(int(rate * duration)):
            t = i / rate
            loud = any(a <= t < b for a, b in tones)
            value = int(12000 * math.sin(2 * math.pi * 220 * t)) if loud else 0
            frames += struct.pack("<h", value)
        out.writeframes(bytes(frames))


def _attenuate_sources(root: Path) -> tuple[Path, Path]:
    """A short loud burst in a 1.3s gap (qualifies) and a longer one in a
    4.7s gap (too wide to prove the map is dense there — disqualified).
    """
    audio = root / "vo.wav"
    _write_wav_at_rate(
        audio,
        tones=[(0.0, 1.0), (1.5, 2.0), (2.3, 3.3), (5.0, 5.7), (8.0, 9.0)],
        duration=10.0,
        rate=energy.RATE,
    )
    words = [
        {"word": "well", "start": 0.0, "end": 1.0},
        {"word": "so", "start": 2.3, "end": 3.3},
        {"word": "quiet", "start": 8.0, "end": 9.0},
    ]
    transcript = root / "vo.json"
    transcript.write_text(json.dumps({"language": "en", "words": words}), encoding="utf-8")
    return audio, transcript


def _scream_hole_sources(root: Path) -> tuple[Path, Path]:
    """Scream v1's own false-positive shape: a 0.6s burst in a 4.12s hole in
    the word map (`ideas/scream.md`) — must stay disqualified on gap width
    alone, never on the event's own (short) duration.
    """
    audio = root / "vo.wav"
    _write_wav_at_rate(
        audio, tones=[(0.0, 1.0), (3.0, 3.6), (5.12, 6.12)], duration=8.0, rate=energy.RATE
    )
    words = [
        {"word": "well", "start": 0.0, "end": 1.0},
        {"word": "so", "start": 5.12, "end": 6.12},
    ]
    transcript = root / "vo.json"
    transcript.write_text(json.dumps({"language": "en", "words": words}), encoding="utf-8")
    return audio, transcript


def _suspect_neighbour_sources(root: Path) -> tuple[Path, Path]:
    """A qualifying event whose *before* neighbour ("loud") claims a
    duration far past 3x the median — suspect by `energy.CAP` — so the
    "gap is narrow" evidence next to it is itself unproven.
    """
    audio = root / "vo.wav"
    _write_wav_at_rate(
        audio,
        tones=[(0.0, 0.3), (0.5, 0.8), (1.0, 1.9), (2.2, 2.7), (3.0, 3.3)],
        duration=6.0,
        rate=energy.RATE,
    )
    words = [
        {"word": "well", "start": 0.0, "end": 0.3},
        {"word": "so", "start": 0.5, "end": 0.8},
        {"word": "loud", "start": 1.0, "end": 4.0},
        {"word": "quiet", "start": 3.0, "end": 3.3},
    ]
    transcript = root / "vo.json"
    transcript.write_text(json.dumps({"language": "en", "words": words}), encoding="utf-8")
    return audio, transcript


def _make_video_with_audio(path: Path, audio: Path, *, duration: float, fps: int = 30) -> None:
    """`_make_video`'s picture, muxed with a real gap-and-burst audio track
    instead of a flat sine tone, so `-c:v copy` has real picture to preserve.
    """
    video_only = path.with_suffix(".video-only.mp4")
    subprocess.run(
        [
            "ffmpeg", "-y", "-loglevel", "error",
            "-f", "lavfi", "-i", f"testsrc=size=160x120:rate={fps}:duration={duration}",
            "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p",
            str(video_only),
        ],
        check=True,
        capture_output=True,
    )  # fmt: skip
    subprocess.run(
        [
            "ffmpeg", "-y", "-loglevel", "error",
            "-i", str(video_only), "-i", str(audio),
            "-map", "0:v", "-map", "1:a",
            "-c:v", "copy", "-c:a", "aac", "-shortest",
            str(path),
        ],
        check=True,
        capture_output=True,
    )  # fmt: skip


async def _attached(client: Client, project: Path, source: Path, transcript: Path) -> str:
    """init -> import -> attach, the preamble `attenuate_noises` wants — it
    needs no timeline, so there is no `seed_timeline` step here.
    """
    await client.call("init", path=str(project))
    clip = await client.call("import_media", path=str(project), source=str(source))
    await client.call(
        "attach_transcript",
        path=str(project),
        clip_id=clip["clip_id"],
        transcript_path=str(transcript),
    )
    return str(clip["clip_id"])


@needs_ffprobe
@needs_ffmpeg
def test_attenuate_noises_pulls_down_a_qualifying_event_and_leaves_the_rest(tmp_path: Path) -> None:
    """The load-bearing shape in one project: a short event in a narrow gap
    is pulled down and written, and a short event in a much wider gap
    (disqualified) is reported but never touched.
    """
    audio, transcript = _attenuate_sources(tmp_path)
    project = tmp_path / "proj"

    async def body(session: ClientSession) -> Any:
        client = Client(session)
        clip_id = await _attached(client, project, audio, transcript)
        return await client.call("attenuate_noises", path=str(project), clip_id=clip_id)

    result = anyio.run(_with_server, body)

    assert result["written"] is True
    assert len(result["attenuated"]) == 1
    assert len(result["disqualified"]) == 1
    assert result["suspect_neighbours"] == []
    assert any("max_gap_seconds" in reason for reason in result["disqualified"][0]["reasons"])

    output = Path(result["output_media"])
    assert output.exists()

    manifest = Project.open(project).read_manifest()
    clip = next(c for c in manifest["clips"] if c.get("attenuated"))
    assert Path(clip["attenuated"]).name == output.name

    before = energy.envelope(energy.decode(audio))
    after = energy.envelope(energy.decode(output))
    assert _db_at(after, 1.75) == pytest.approx(_db_at(before, 1.75) - 12.0, abs=2.0)
    # The disqualified burst, elsewhere in the same file, is left alone.
    assert _db_at(after, 5.35) == pytest.approx(_db_at(before, 5.35), abs=1.0)


@needs_ffprobe
@needs_ffmpeg
def test_attenuate_noises_refuses_to_touch_a_wide_map_hole_even_though_it_is_loud(
    tmp_path: Path,
) -> None:
    """Scream v1's exact false positive: 0.6s of sound in a 4.12s hole in the
    word map read as noise on a first pass. It is not — the hole is too wide
    to prove the map is dense there, so it must be reported, never written.
    """
    audio, transcript = _scream_hole_sources(tmp_path)
    project = tmp_path / "proj"

    async def body(session: ClientSession) -> Any:
        client = Client(session)
        clip_id = await _attached(client, project, audio, transcript)
        return await client.call("attenuate_noises", path=str(project), clip_id=clip_id)

    result = anyio.run(_with_server, body)

    assert result["attenuated"] == []
    assert result["written"] is False
    assert result["output_media"] is None
    assert len(result["disqualified"]) == 1
    disqualified = result["disqualified"][0]
    assert disqualified["gap"]["duration"] == pytest.approx(4.12, abs=0.01)
    assert disqualified["duration"] == pytest.approx(0.6, abs=0.05)
    assert any("max_gap_seconds" in reason for reason in disqualified["reasons"])
    assert not any("max_event_seconds" in reason for reason in disqualified["reasons"])


@needs_ffprobe
@needs_ffmpeg
def test_attenuate_noises_plan_reports_without_writing(tmp_path: Path) -> None:
    """Mirrors `cut --plan`'s "same numbers" contract: a plan and a real run
    against the same project must agree on everything except `written`.

    Run against two fixtures. `_attenuate_sources` has no `suspect_neighbour`
    event, so it cannot see a real bug: `include_suspect = confirm_suspect or
    plan` used to let `plan=True` alone pull a suspect event into
    `to_write`/`output_media`, previewing a write a subsequent real call
    (confirm_suspect defaulting to False) would never actually perform.
    `_suspect_neighbour_sources` has exactly one such event, so it is the one
    that would have caught that divergence — `to_write` must now be gated by
    `confirm_suspect` alone in both the plan and the real path.
    """
    audio, transcript = _attenuate_sources(tmp_path)
    project = tmp_path / "proj"

    async def body(session: ClientSession) -> Any:
        client = Client(session)
        clip_id = await _attached(client, project, audio, transcript)
        planned = await client.call(
            "attenuate_noises", path=str(project), clip_id=clip_id, plan=True
        )
        exists_under_plan = Path(planned["output_media"]).exists()
        real = await client.call("attenuate_noises", path=str(project), clip_id=clip_id)
        return planned, exists_under_plan, real

    planned, exists_under_plan, real = anyio.run(_with_server, body)

    assert planned["plan"] is True
    assert planned["written"] is False
    assert exists_under_plan is False

    assert real["written"] is True
    assert Path(real["output_media"]).exists()

    assert planned["output_media"] == real["output_media"]
    assert planned["attenuated"] == real["attenuated"]
    assert planned["disqualified"] == real["disqualified"]

    suspect_audio, suspect_transcript = _suspect_neighbour_sources(tmp_path)
    suspect_project = tmp_path / "suspect-proj"

    async def suspect_body(session: ClientSession) -> Any:
        client = Client(session)
        clip_id = await _attached(client, suspect_project, suspect_audio, suspect_transcript)
        planned = await client.call(
            "attenuate_noises", path=str(suspect_project), clip_id=clip_id, plan=True
        )
        real = await client.call(
            "attenuate_noises", path=str(suspect_project), clip_id=clip_id
        )
        return planned, real

    suspect_planned, suspect_real = anyio.run(_with_server, suspect_body)

    assert len(suspect_planned["suspect_neighbours"]) == 1
    # Neither call confirmed the suspect neighbour, so a plan's preview and
    # the matching real call must agree it was withheld from both.
    assert suspect_planned["attenuated"] == []
    assert suspect_real["attenuated"] == []
    assert suspect_planned["written"] is False
    assert suspect_real["written"] is False
    assert suspect_planned["output_media"] == suspect_real["output_media"] is None


@needs_ffprobe
@needs_ffmpeg
def test_attenuate_noises_withholds_a_suspect_neighbour_without_confirm_then_writes_it_with_confirm_true(
    tmp_path: Path,
) -> None:
    audio, transcript = _suspect_neighbour_sources(tmp_path)
    project = tmp_path / "proj"

    async def body(session: ClientSession) -> Any:
        client = Client(session)
        clip_id = await _attached(client, project, audio, transcript)
        withheld = await client.call("attenuate_noises", path=str(project), clip_id=clip_id)
        confirmed = await client.call(
            "attenuate_noises", path=str(project), clip_id=clip_id, confirm_suspect=True
        )
        return withheld, confirmed

    withheld, confirmed = anyio.run(_with_server, body)

    assert withheld["attenuated"] == []
    assert withheld["written"] is False
    assert len(withheld["suspect_neighbours"]) == 1
    assert withheld["suspect_neighbours"][0]["neighbour_before"]["text"] == "loud"

    assert len(confirmed["attenuated"]) == 1
    assert confirmed["written"] is True


@needs_ffprobe
@needs_ffmpeg
def test_attenuate_noises_re_run_does_not_compound_gain(tmp_path: Path) -> None:
    """A second call must read the *original* media, not the first call's
    output — otherwise the same span would be attenuated twice.
    """
    audio, transcript = _attenuate_sources(tmp_path)
    project = tmp_path / "proj"

    async def body(session: ClientSession) -> Any:
        client = Client(session)
        clip_id = await _attached(client, project, audio, transcript)
        first = await client.call("attenuate_noises", path=str(project), clip_id=clip_id)
        second = await client.call("attenuate_noises", path=str(project), clip_id=clip_id)
        return first, second

    first, second = anyio.run(_with_server, body)

    assert second["source_media"] == first["source_media"]

    after_first = energy.envelope(energy.decode(Path(first["output_media"])))
    after_second = energy.envelope(energy.decode(Path(second["output_media"])))
    assert _db_at(after_second, 1.75) == pytest.approx(_db_at(after_first, 1.75), abs=1.0)


def _overlapping_runs_sources(root: Path) -> tuple[Path, Path]:
    """Two loud runs ~0.02s apart (after envelope quantisation) in one 1.3s
    gap — closer than `2*pad` (default `pad=0.05s`), so their padded spans
    overlap. Both independently qualify as `"attenuated"`; the write side
    must merge them before building the filtergraph, or ffmpeg's
    comma-chained `volume` filters double-attenuate the overlap.
    """
    audio = root / "vo.wav"
    _write_wav_at_rate(
        audio,
        tones=[(0.0, 1.0), (1.5, 1.75), (1.79, 2.05), (2.3, 3.3)],
        duration=5.0,
        rate=energy.RATE,
    )
    words = [
        {"word": "well", "start": 0.0, "end": 1.0},
        {"word": "so", "start": 2.3, "end": 3.3},
    ]
    transcript = root / "vo.json"
    transcript.write_text(json.dumps({"language": "en", "words": words}), encoding="utf-8")
    return audio, transcript


@needs_ffprobe
@needs_ffmpeg
def test_attenuate_noises_merges_overlapping_padded_runs_before_writing(tmp_path: Path) -> None:
    """Two loud runs in one gap, padded closer together than they are apart,
    must not stack. `energy.attenuate` comma-chains one `volume` filter per
    span, so an unmerged overlap gets attenuated twice — roughly double the
    requested `db` there, with no error and no warning, while `result["gain"]`
    keeps reporting the single-pass value that does not describe what
    actually happened in the overlap.
    """
    audio, transcript = _overlapping_runs_sources(tmp_path)
    project = tmp_path / "proj"

    async def body(session: ClientSession) -> Any:
        client = Client(session)
        clip_id = await _attached(client, project, audio, transcript)
        return await client.call("attenuate_noises", path=str(project), clip_id=clip_id)

    result = anyio.run(_with_server, body)

    assert result["written"] is True
    # Per-event detail survives the write-side merge: two distinct runs are
    # still two distinct reported events.
    assert len(result["attenuated"]) == 2
    assert all(e["status"] == "attenuated" for e in result["attenuated"])

    before = energy.envelope(energy.decode(audio))
    after = energy.envelope(energy.decode(Path(result["output_media"])))

    # A point inside only the first run's padded span, a point inside the
    # overlap of both padded spans, and a point inside only the second run's.
    for t in (1.55, 1.82, 2.00):
        assert _db_at(after, t) == pytest.approx(_db_at(before, t) - 12.0, abs=2.0)


@needs_ffprobe
@needs_ffmpeg
@needs_auto_editor
def test_export_renders_the_attenuated_copy_not_the_original(tmp_path: Path) -> None:
    """`media_path()` prefers `clip["attenuated"]`, but `autoeditor.to_v3`
    used to build each segment's `"src"` from `record["source"]` directly,
    bypassing `media_path()` entirely — so a render taken after
    `attenuate_noises` still carried the original noise burst at full
    volume, with `written: true` giving no sign anything had been bypassed.
    Doubles as the regression test for that bypass: without routing
    `to_v3`'s `"src"` through `media.media_path()`, this render measures the
    *pre*-attenuation level, not the post-attenuation one.
    """
    audio, transcript = _attenuate_sources(tmp_path)
    project = tmp_path / "proj"
    render = tmp_path / "out.wav"

    async def body(session: ClientSession) -> Any:
        client = Client(session)
        clip_id = await _attached(client, project, audio, transcript)
        await client.call("attenuate_noises", path=str(project), clip_id=clip_id)
        await client.call(
            "seed_timeline", path=str(project), clip_id=clip_id, remove_silences=False
        )
        await client.call("export", path=str(project), output=str(render), export_format=None)

    anyio.run(_with_server, body)

    before = energy.envelope(energy.decode(audio))
    after = energy.envelope(energy.decode(render))
    assert _db_at(after, 1.75) == pytest.approx(_db_at(before, 1.75) - 12.0, abs=2.0)


@needs_ffprobe
@needs_ffmpeg
def test_attenuate_noises_video_clip_copies_picture_and_only_touches_audio(tmp_path: Path) -> None:
    """`-c:v copy`, proven by frame count parity rather than trusted by name."""
    audio = tmp_path / "vo.wav"
    _make_wav(audio, tones=[(0.0, 1.0), (1.5, 2.0), (2.3, 3.3)], duration=8.0)
    source = tmp_path / "pic.mp4"
    _make_video_with_audio(source, audio, duration=8.0)
    project = tmp_path / "proj"
    words = [
        {"word": "well", "start": 0.0, "end": 1.0},
        {"word": "so", "start": 2.3, "end": 3.3},
    ]
    transcript = tmp_path / "pic.json"
    transcript.write_text(json.dumps({"language": "en", "words": words}), encoding="utf-8")

    async def body(session: ClientSession) -> Any:
        client = Client(session)
        clip_id = await _attached(client, project, source, transcript)
        return await client.call("attenuate_noises", path=str(project), clip_id=clip_id)

    result = anyio.run(_with_server, body)

    assert result["written"] is True
    before = media.count_frames(source)
    after = media.count_frames(result["output_media"])
    assert after["frames"] == before["frames"]
    assert after["frames"] is not None


async def _clip_b(client: Client, project: Path, source: Path, transcript: Path) -> str:
    """import -> attach for a clip that is never placed on the timeline —
    `speech_overlap` tests a *proposed* placement of it against the VO's
    already-seeded one, so unlike `_seeded` there is no `seed_timeline` step.
    """
    clip = await client.call("import_media", path=str(project), source=str(source))
    await client.call(
        "attach_transcript",
        path=str(project),
        clip_id=clip["clip_id"],
        transcript_path=str(transcript),
    )
    return str(clip["clip_id"])


def _write_words(path: Path, words: list[dict[str, Any]]) -> None:
    path.write_text(json.dumps({"language": "en", "words": words}), encoding="utf-8")


@needs_ffprobe
def test_speech_overlap_reports_a_clean_seam_when_clip_speech_sits_in_a_vo_gap(
    tmp_path: Path, sources: tuple[Path, Path]
) -> None:
    """The cheapest case: a proposed clip placement lands in a VO silence
    gap (between the w01 and w10 bursts of the `sources` fixture), so there
    is nothing to duck around.
    """
    audio, transcript = sources
    project = tmp_path / "proj"
    b_audio = tmp_path / "clipb.wav"
    _make_wav(b_audio, tones=[(2.2, 2.8)], duration=4.0)
    b_transcript = tmp_path / "clipb.json"
    _write_words(b_transcript, [{"word": "bspeak", "start": 2.2, "end": 2.8}])

    async def body(session: ClientSession) -> Any:
        client = Client(session)
        await _seeded(client, project, audio, transcript)
        clip_b = await _clip_b(client, project, b_audio, b_transcript)
        return await client.call("speech_overlap", path=str(project), clip_id=clip_b)

    result = anyio.run(_with_server, body)

    assert result["overlaps"] == []
    assert result["summary"]["overlap_count"] == 0
    assert len(result["clean_seams"]) == 1
    seam = result["clean_seams"][0]
    assert seam["timeline_start"] == pytest.approx(2.2)
    assert seam["timeline_end"] == pytest.approx(2.8)


@needs_ffprobe
def test_speech_overlap_catches_the_billy_stu_case(
    tmp_path: Path, sources: tuple[Path, Path]
) -> None:
    """Named for the incident it exists to catch: a word-level pass on a
    real clip found its speech (105.35-109.15s) landing almost entirely on
    top of a VO thesis line (105.97-109.85s) — near-total overlap, no seam
    to duck into. Here the proposed clip placement lands squarely inside a
    VO run (the merged w00/w01 burst of the `sources` fixture).
    """
    audio, transcript = sources
    project = tmp_path / "proj"
    b_audio = tmp_path / "clipb.wav"
    _make_wav(b_audio, tones=[(1.0, 1.5)], duration=3.0)
    b_transcript = tmp_path / "clipb.json"
    _write_words(b_transcript, [{"word": "over", "start": 1.0, "end": 1.5}])

    async def body(session: ClientSession) -> Any:
        client = Client(session)
        await _seeded(client, project, audio, transcript)
        clip_b = await _clip_b(client, project, b_audio, b_transcript)
        return await client.call("speech_overlap", path=str(project), clip_id=clip_b)

    result = anyio.run(_with_server, body)

    assert len(result["overlaps"]) == 1
    overlap = result["overlaps"][0]
    assert [w["text"] for w in overlap["clip_words"]] == ["over"]
    assert [w["text"] for w in overlap["vo_words"]] == ["w01"]
    assert result["clean_seams"] == []


@needs_ffprobe
def test_speech_overlap_merges_a_narrow_gap_into_one_run(
    tmp_path: Path, sources: tuple[Path, Path]
) -> None:
    """Pins `max_gap` end-to-end, not just at the `speech.merge_runs` unit
    level: two clip words 0.05s apart read as one run at the default
    tolerance and two runs at `max_gap=0.0`.
    """
    audio, transcript = sources
    project = tmp_path / "proj"
    b_audio = tmp_path / "clipb.wav"
    _make_wav(b_audio, tones=[(0.5, 1.4)], duration=3.0)
    b_transcript = tmp_path / "clipb.json"
    _write_words(
        b_transcript,
        [
            {"word": "p1", "start": 0.5, "end": 0.9},
            {"word": "p2", "start": 0.95, "end": 1.4},
        ],
    )

    async def body(session: ClientSession) -> Any:
        client = Client(session)
        await _seeded(client, project, audio, transcript)
        clip_b = await _clip_b(client, project, b_audio, b_transcript)
        default = await client.call("speech_overlap", path=str(project), clip_id=clip_b)
        strict = await client.call(
            "speech_overlap", path=str(project), clip_id=clip_b, max_gap=0.0
        )
        return {"default": default, "strict": strict}

    out = anyio.run(_with_server, body)

    assert len(out["default"]["clip_runs"]) == 1
    assert len(out["strict"]["clip_runs"]) == 2


@needs_ffprobe
def test_speech_overlap_trims_a_suspect_vo_word_before_testing_overlap(
    tmp_path: Path,
) -> None:
    """Mirrors HISTORY.md § 2's swallowed-retake trap: a VO word claiming 6.0s
    (15x the 0.4s median of its neighbours) is capped by `energy.believable`
    before mapping, so a clip placed just past the claimed-but-unbelieved
    tail is correctly read as a clean seam, not an overlap.
    """
    project = tmp_path / "proj"
    vo_audio = tmp_path / "vo.wav"
    _make_wav(vo_audio, tones=[(0.0, 8.1)], duration=9.0)
    vo_transcript = tmp_path / "vo.json"
    _write_words(
        vo_transcript,
        [
            {"word": "so", "start": 0.0, "end": 0.5},
            {"word": "we", "start": 0.6, "end": 1.0},
            {"word": "bit", "start": 1.1, "end": 1.5},
            {"word": "on", "start": 1.6, "end": 7.6},
            {"word": "it", "start": 7.7, "end": 8.1},
        ],
    )
    b_audio = tmp_path / "clipb.wav"
    _make_wav(b_audio, tones=[(3.0, 3.5)], duration=4.0)
    b_transcript = tmp_path / "clipb.json"
    _write_words(b_transcript, [{"word": "later", "start": 3.0, "end": 3.5}])

    async def body(session: ClientSession) -> Any:
        client = Client(session)
        await _seeded(client, project, vo_audio, vo_transcript)
        clip_b = await _clip_b(client, project, b_audio, b_transcript)
        return await client.call("speech_overlap", path=str(project), clip_id=clip_b)

    result = anyio.run(_with_server, body)

    trimmed = next(w for w in result["vo_words"] if w["text"] == "on")
    assert trimmed["source_end"] == pytest.approx(7.6)
    assert trimmed["believable_end"] == pytest.approx(2.8)
    assert trimmed["believable_end"] != trimmed["source_end"]

    assert result["overlaps"] == []
    assert len(result["clean_seams"]) == 1
    seam = result["clean_seams"][0]
    assert seam["timeline_start"] == pytest.approx(3.0)
    assert seam["timeline_end"] == pytest.approx(3.5)


@needs_ffprobe
def test_speech_overlap_trims_a_suspect_clip_b_word_using_the_whole_clip_not_the_window(
    tmp_path: Path,
) -> None:
    """Clip B's own words are not in the edit, so they map by direct offset
    against the proposed `[clip_in, clip_out)` window — and the window here
    is narrow enough (one word) that the old bug's local median was set by
    the very outlier it was supposed to catch: with only the inflated word
    in `clip_hits`, `_median_limit` took *its own* duration as the median,
    so `believable` trimmed nothing. The fix computes the cap from clip_b's
    whole transcript (mirroring the VO side, `_suspect_durations`, and
    `attenuate_noises`), so the same 6.0s outlier is still caught even
    though the proposed window only ever sees it alone.
    """
    project = tmp_path / "proj"
    vo_audio = tmp_path / "vo.wav"
    _make_wav(vo_audio, tones=[], duration=12.0)
    vo_transcript = tmp_path / "vo.json"
    _write_words(vo_transcript, [{"word": "hush", "start": 0.0, "end": 0.4}])

    b_audio = tmp_path / "clipb.wav"
    _make_wav(b_audio, tones=[], duration=10.0)
    b_transcript = tmp_path / "clipb.json"
    _write_words(
        b_transcript,
        [
            {"word": "so", "start": 0.0, "end": 0.5},
            {"word": "we", "start": 0.6, "end": 1.0},
            {"word": "bit", "start": 1.1, "end": 1.5},
            {"word": "later", "start": 3.0, "end": 9.0},
            {"word": "it", "start": 9.6, "end": 10.0},
        ],
    )

    async def body(session: ClientSession) -> Any:
        client = Client(session)
        await _seeded(client, project, vo_audio, vo_transcript)
        clip_b = await _clip_b(client, project, b_audio, b_transcript)
        # Narrow enough that only "later" falls in clip_hits — "bit" ends at
        # 1.5 (<= clip_in), "it" starts at 9.6 (>= clip_out).
        return await client.call(
            "speech_overlap",
            path=str(project),
            clip_id=clip_b,
            clip_in=2.0,
            clip_out=9.5,
        )

    result = anyio.run(_with_server, body)

    assert [w["text"] for w in result["clip_words"]] == ["later"]
    trimmed = result["clip_words"][0]
    assert trimmed["source_end"] == pytest.approx(9.0)
    # Full-population median of [0.4, 0.4, 0.4, 0.5, 6.0] is 0.4, cap=3.0 ->
    # limit=1.2, so believable_end = 3.0 + 1.2 = 4.2. Under the bug, the
    # single-word window's own median was the 6.0s outlier itself, so
    # believable_end stayed 9.0 (untrimmed).
    assert trimmed["believable_end"] == pytest.approx(4.2)
    assert trimmed["believable_end"] != trimmed["source_end"]


@needs_ffprobe
def test_speech_overlap_refuses_when_clip_has_no_transcript(tmp_path: Path) -> None:
    project = tmp_path / "proj"
    audio, transcript = _make_sources(tmp_path)
    b_audio = tmp_path / "clipb.wav"
    _make_wav(b_audio, tones=[(0.5, 1.0)], duration=2.0)

    async def body(session: ClientSession) -> Any:
        client = Client(session)
        await _seeded(client, project, audio, transcript)
        clip_b = await client.call("import_media", path=str(project), source=str(b_audio))
        return await session.call_tool(
            "speech_overlap", {"path": str(project), "clip_id": clip_b["clip_id"]}
        )

    result = anyio.run(_with_server, body)

    assert result.is_error
    assert "attach" in result.content[0].text


@needs_ffprobe
def test_speech_overlap_refuses_when_vo_timeline_is_empty(tmp_path: Path) -> None:
    """No `seed_timeline` call at all — a project with clips but no timeline
    is the same refusal `_load_edit` gives every other timeline-reading op.
    """
    project = tmp_path / "proj"
    b_audio = tmp_path / "clipb.wav"
    _make_wav(b_audio, tones=[(0.5, 1.0)], duration=2.0)
    b_transcript = tmp_path / "clipb.json"
    _write_words(b_transcript, [{"word": "hi", "start": 0.5, "end": 1.0}])

    async def body(session: ClientSession) -> Any:
        client = Client(session)
        await client.call("init", path=str(project))
        clip_b = await _clip_b(client, project, b_audio, b_transcript)
        return await session.call_tool(
            "speech_overlap", {"path": str(project), "clip_id": clip_b}
        )

    result = anyio.run(_with_server, body)

    assert result.is_error
    assert "timeline" in result.content[0].text


@needs_ffprobe
def test_speech_overlap_refuses_for_an_unregistered_clip(tmp_path: Path) -> None:
    project = tmp_path / "proj"

    async def body(session: ClientSession) -> Any:
        await Client(session).call("init", path=str(project))
        return await session.call_tool(
            "speech_overlap", {"path": str(project), "clip_id": "nope"}
        )

    result = anyio.run(_with_server, body)

    assert result.is_error
    assert "nope" in result.content[0].text


@needs_ffprobe
def test_speech_overlap_default_placement_covers_the_clips_whole_duration(
    tmp_path: Path, sources: tuple[Path, Path]
) -> None:
    """`at`/`clip_in`/`clip_out` are silent defaults otherwise — pin them
    explicitly rather than trust the docstring.
    """
    audio, transcript = sources
    project = tmp_path / "proj"
    b_audio = tmp_path / "clipb.wav"
    _make_wav(b_audio, tones=[(0.5, 1.0)], duration=2.0)
    b_transcript = tmp_path / "clipb.json"
    _write_words(b_transcript, [{"word": "hi", "start": 0.5, "end": 1.0}])

    async def body(session: ClientSession) -> Any:
        client = Client(session)
        await _seeded(client, project, audio, transcript)
        b_clip = await client.call("import_media", path=str(project), source=str(b_audio))
        await client.call(
            "attach_transcript",
            path=str(project),
            clip_id=b_clip["clip_id"],
            transcript_path=str(b_transcript),
        )
        result = await client.call(
            "speech_overlap", path=str(project), clip_id=b_clip["clip_id"]
        )
        return {"clip": b_clip, "result": result}

    out = anyio.run(_with_server, body)

    assert out["result"]["at"] == pytest.approx(0.0)
    assert out["result"]["clip_in"] == pytest.approx(0.0)
    assert out["result"]["clip_out"] == pytest.approx(out["clip"]["duration"])


# -- locate: source -> timeline ------------------------------------------
#
# The `sources` fixture seeded with `remove_silences=False` is one 0-12s
# segment, and its words are w00 0.0-0.9, w01 1.0-1.9, w10 3.0-3.9,
# w11 4.0-4.9, w20 6.0-6.9, w21 7.0-7.9, w30 9.0-9.9, w31 10.0-10.9. Every
# case below cuts something and then asks where a word *downstream of the cut*
# now plays, because an uncut timeline makes source and timeline coordinates
# identical and would pass no matter what the mapping did.


@needs_ffprobe
def test_locate_maps_a_word_forward_through_an_earlier_cut(
    tmp_path: Path, sources: tuple[Path, Path]
) -> None:
    """The whole point of the tool: the index does not move, the answer does.

    w30 is asked for twice with the same index, either side of a 2s cut that
    happens entirely before it.
    """
    audio, transcript = sources
    project = tmp_path / "proj"

    async def body(session: ClientSession) -> Any:
        client = Client(session)
        clip_id = await _seeded(client, project, audio, transcript)
        before = await client.call("locate", path=str(project), clip_id=clip_id, first=6)
        await client.call(
            "cut_by_transcript", path=str(project), clip_id=clip_id, cut=[[2, 3]]
        )
        after = await client.call("locate", path=str(project), clip_id=clip_id, first=6)
        return {"before": before, "after": after}

    out = anyio.run(_with_server, body)

    # Uncut, source and timeline agree; that is the control, not the result.
    assert out["before"]["timeline_start"] == pytest.approx(9.0)
    assert out["before"]["source_start"] == pytest.approx(9.0)

    # The cut removed words 2..3, i.e. source 3.0-4.9 = 1.9s of material.
    assert out["after"]["source_start"] == pytest.approx(9.0), "the index must not renumber"
    assert out["after"]["timeline_start"] == pytest.approx(9.0 - 1.9)
    assert out["after"]["timeline_end"] == pytest.approx(9.9 - 1.9)
    assert out["after"]["present"] is True
    assert out["after"]["fully_present"] is True
    assert out["after"]["timeline_duration"] == pytest.approx(12.0 - 1.9)


@needs_ffprobe
def test_locate_echoes_the_words_and_their_neighbours(
    tmp_path: Path, sources: tuple[Path, Path]
) -> None:
    """The project-wide echo convention (CLAUDE.md) applies to a read too —
    an index one past the intended phrase reads fine on its own.
    """
    audio, transcript = sources
    project = tmp_path / "proj"

    async def body(session: ClientSession) -> Any:
        client = Client(session)
        clip_id = await _seeded(client, project, audio, transcript)
        return await client.call(
            "locate", path=str(project), clip_id=clip_id, first=3, last=4
        )

    result = anyio.run(_with_server, body)

    assert result["text"] == "w11 w20"
    assert [w["text"] for w in result["words"]] == ["w11", "w20"]
    assert [w["text"] for w in result["context_before"]] == ["w00", "w01", "w10"]
    assert [w["text"] for w in result["context_after"]] == ["w21", "w30", "w31"]


@needs_ffprobe
def test_locate_reports_a_cut_word_as_absent_rather_than_moving_it(
    tmp_path: Path, sources: tuple[Path, Path]
) -> None:
    """`present: false` is the honest answer, and the reason word indices can
    stay stable across cuts at all — nothing silently slides onto neighbouring
    material.
    """
    audio, transcript = sources
    project = tmp_path / "proj"

    async def body(session: ClientSession) -> Any:
        client = Client(session)
        clip_id = await _seeded(client, project, audio, transcript)
        await client.call(
            "cut_by_transcript", path=str(project), clip_id=clip_id, cut=[[2, 3]]
        )
        return await client.call("locate", path=str(project), clip_id=clip_id, first=2)

    result = anyio.run(_with_server, body)

    assert result["present"] is False
    assert result["placements"] == []
    assert result["timeline_start"] is None
    assert result["covered"] == pytest.approx(0.0)
    assert "beyond_source" not in result, "it was recorded, it was cut — different things"
    assert result["text"] == "w10"


@needs_ffprobe
def test_locate_reports_each_surviving_piece_of_a_half_cut_range(
    tmp_path: Path, sources: tuple[Path, Path]
) -> None:
    """A range a cut split is the normal case, not an error. `timeline_span`
    would report only the first survivor (it is shaped for captions); the
    aggregate `timeline_spans` behind `locate` reports both, and the pieces
    still play back-to-back because a cut closes its hole.
    """
    audio, transcript = sources
    project = tmp_path / "proj"

    async def body(session: ClientSession) -> Any:
        client = Client(session)
        clip_id = await _seeded(client, project, audio, transcript)
        # Cut 5.0-6.0, a silence gap sitting inside the 4.0-7.0 range below.
        await client.call("cut_by_time", path=str(project), spans=[[5.0, 6.0]])
        return await client.call(
            "locate",
            path=str(project),
            clip_id=clip_id,
            source_start=4.0,
            source_end=7.0,
        )

    result = anyio.run(_with_server, body)

    assert result["present"] is True
    assert result["fully_present"] is False
    assert result["requested"] == pytest.approx(3.0)
    assert result["covered"] == pytest.approx(2.0)
    assert len(result["placements"]) == 2

    first, second = result["placements"]
    assert (first["source_start"], first["source_end"]) == pytest.approx((4.0, 5.0))
    assert (second["source_start"], second["source_end"]) == pytest.approx((6.0, 7.0))
    # The hole closed, so the two survivors are adjacent in timeline time even
    # though they are a second apart in source time.
    assert first["timeline_end"] == pytest.approx(second["timeline_start"])
    assert result["contiguous"] is True

    # Time mode echoes by overlap, never containment: w11 (4.0-4.9) and
    # w20 (6.0-6.9) both fall inside, and the request's own edges touch neither
    # neighbour.
    assert [w["text"] for w in result["words"]] == ["w11", "w20"]


@needs_ffprobe
def test_locate_finds_the_word_playing_at_a_source_instant(
    tmp_path: Path, sources: tuple[Path, Path]
) -> None:
    audio, transcript = sources
    project = tmp_path / "proj"

    async def body(session: ClientSession) -> Any:
        client = Client(session)
        clip_id = await _seeded(client, project, audio, transcript)
        await client.call("cut_by_time", path=str(project), spans=[[0.0, 1.0]])
        return await client.call(
            "locate", path=str(project), clip_id=clip_id, source_start=7.5
        )

    result = anyio.run(_with_server, body)

    assert result["mode"] == "instant"
    assert result["timeline_start"] == pytest.approx(6.5)
    assert result["timeline_end"] == pytest.approx(6.5)
    assert [w["text"] for w in result["words"]] == ["w21"]


@needs_ffprobe
def test_locate_names_the_nearest_words_for_an_instant_in_silence(
    tmp_path: Path, sources: tuple[Path, Path]
) -> None:
    """5.5s is in the gap between w11 (ends 4.9) and w20 (starts 6.0). An empty
    word list with no neighbours would leave nothing to check the timestamp
    against.
    """
    audio, transcript = sources
    project = tmp_path / "proj"

    async def body(session: ClientSession) -> Any:
        client = Client(session)
        clip_id = await _seeded(client, project, audio, transcript)
        return await client.call(
            "locate", path=str(project), clip_id=clip_id, source_start=5.5
        )

    result = anyio.run(_with_server, body)

    assert result["words"] == []
    assert [w["text"] for w in result["context_before"]] == ["w01", "w10", "w11"]
    assert [w["text"] for w in result["context_after"]] == ["w20", "w21", "w30"]


@needs_ffprobe
def test_locate_distinguishes_never_recorded_from_cut(
    tmp_path: Path, sources: tuple[Path, Path]
) -> None:
    """Both come back with no placements, and only the clip's own duration
    tells them apart — so `locate` says which it is rather than letting the
    empty list read as an edit decision.
    """
    audio, transcript = sources
    project = tmp_path / "proj"

    async def body(session: ClientSession) -> Any:
        client = Client(session)
        clip_id = await _seeded(client, project, audio, transcript)
        return await client.call(
            "locate", path=str(project), clip_id=clip_id, source_start=20.0
        )

    result = anyio.run(_with_server, body)

    assert result["present"] is False
    assert result["beyond_source"] is True
    assert result["source_duration"] == pytest.approx(12.0, abs=0.05)


@needs_ffprobe
def test_locate_refuses_both_addressing_modes_at_once(
    tmp_path: Path, sources: tuple[Path, Path]
) -> None:
    """Word indices and source seconds name the same thing two ways; a call
    giving both cannot say which it meant, and picking one would be a guess.
    """
    audio, transcript = sources
    project = tmp_path / "proj"

    async def body(session: ClientSession) -> Any:
        client = Client(session)
        clip_id = await _seeded(client, project, audio, transcript)
        return await session.call_tool(
            "locate", {"path": str(project), "clip_id": clip_id, "first": 3, "source_start": 4.0}
        )

    result = anyio.run(_with_server, body)

    assert result.is_error
    assert "not both" in result.content[0].text


@needs_ffprobe
def test_locate_works_on_a_clip_with_no_transcript(tmp_path: Path) -> None:
    """A picture-only clip is a valid thing to ask about by time, so the
    missing transcript is reported rather than made a refusal — the same
    choice `cut_by_time` makes.
    """
    project = tmp_path / "proj"
    audio = tmp_path / "vo.wav"
    _make_wav(audio, tones=[(0.0, 2.0)], duration=4.0)

    async def body(session: ClientSession) -> Any:
        client = Client(session)
        clip_id = await _seeded(client, project, audio, None)
        return await client.call(
            "locate", path=str(project), clip_id=clip_id, source_start=1.0, source_end=2.0
        )

    result = anyio.run(_with_server, body)

    assert result["present"] is True
    assert result["words"] is None
    assert result["transcript_missing"] is True


# -- timeline_view: the whole edit in one payload -------------------------
#
# `locate` asked once per range; this asks once for the clip. The cases that
# matter are the ones a view drawn off the transcript instead of the edit
# would get wrong.


@needs_ffprobe
def test_timeline_view_names_each_seam_by_the_surviving_words_either_side(
    tmp_path: Path, sources: tuple[Path, Path]
) -> None:
    """The seam is a word boundary, not a timeline second.

    Asking the transcript what sits at the seam's *source* time answers with
    the word that was removed — a cut begins exactly where the outgoing
    segment ends — so the lookup has to happen among the survivors, in
    timeline coordinates.
    """
    audio, transcript = sources
    project = tmp_path / "proj"

    async def body(session: ClientSession) -> Any:
        client = Client(session)
        clip_id = await _seeded(client, project, audio, transcript)
        await client.call("cut_by_transcript", path=str(project), clip_id=clip_id, cut=[[2, 3]])
        return await client.call("timeline_view", path=str(project))

    view = anyio.run(_with_server, body)

    assert len(view["seams"]) == 1
    seam = view["seams"][0]
    assert (seam["before"]["index"], seam["after"]["index"]) == (1, 4)
    assert seam["removed"] == pytest.approx(1.9)
    assert seam["timeline_time"] == pytest.approx(3.0)


@needs_ffprobe
def test_timeline_view_reports_cut_words_absent_and_later_words_moved(
    tmp_path: Path, sources: tuple[Path, Path]
) -> None:
    audio, transcript = sources
    project = tmp_path / "proj"

    async def body(session: ClientSession) -> Any:
        client = Client(session)
        clip_id = await _seeded(client, project, audio, transcript)
        await client.call("cut_by_transcript", path=str(project), clip_id=clip_id, cut=[[2, 3]])
        return await client.call("timeline_view", path=str(project))

    words = {w["index"]: w for w in anyio.run(_with_server, body)["words"]}

    assert words[2]["present"] is False and words[2]["timeline_start"] is None
    assert words[3]["present"] is False
    # The index never renumbers; only the answer moves.
    assert words[6]["start"] == pytest.approx(9.0), "the index must not renumber"
    assert words[6]["timeline_start"] == pytest.approx(9.0 - 1.9)


@needs_ffprobe
def test_timeline_view_marks_a_word_a_cut_only_half_removed(
    tmp_path: Path, sources: tuple[Path, Path]
) -> None:
    """Partial survival is normal on whisper timings, so it is reported.

    w10 runs 3.0-3.9; cutting render time 3.5-4.5 takes half of it. A
    containment test would call the word gone (HISTORY.md § 2).
    """
    audio, transcript = sources
    project = tmp_path / "proj"

    async def body(session: ClientSession) -> Any:
        client = Client(session)
        await _seeded(client, project, audio, transcript)
        await client.call("cut_by_time", path=str(project), spans=[[3.5, 4.5]])
        return await client.call("timeline_view", path=str(project))

    words = {w["index"]: w for w in anyio.run(_with_server, body)["words"]}

    assert words[2]["present"] is True
    assert words[2]["partial"] is True
    assert words[2]["covered"] == pytest.approx(0.5)


@needs_ffprobe
def test_timeline_view_carries_both_coordinate_systems_per_segment(
    tmp_path: Path, sources: tuple[Path, Path]
) -> None:
    audio, transcript = sources
    project = tmp_path / "proj"

    async def body(session: ClientSession) -> Any:
        client = Client(session)
        clip_id = await _seeded(client, project, audio, transcript)
        await client.call("cut_by_transcript", path=str(project), clip_id=clip_id, cut=[[2, 3]])
        return await client.call("timeline_view", path=str(project))

    view = anyio.run(_with_server, body)
    first, second = view["segments"]

    assert (first["start"], first["timeline_start"]) == (pytest.approx(0.0), pytest.approx(0.0))
    assert first["end"] == pytest.approx(3.0)
    # Source 4.9 onward, but it plays from 3.0 — the pair a caller otherwise
    # recomputes by summing durations.
    assert second["start"] == pytest.approx(4.9)
    assert second["timeline_start"] == pytest.approx(3.0)
    assert view["undo_depth"] == 1


@needs_ffprobe
def test_timeline_view_words_carry_a_paragraph_field(
    tmp_path: Path, sources: tuple[Path, Path]
) -> None:
    """The read model over the wire: every word — cut or not — is placed in a
    paragraph. test_ops_paragraphs.py covers the break rule itself in
    isolation; this only checks the field rides through the real call, since
    `sources`' 8 plain words never earn a break.
    """
    audio, transcript = sources
    project = tmp_path / "proj"

    async def body(session: ClientSession) -> Any:
        client = Client(session)
        clip_id = await _seeded(client, project, audio, transcript)
        await client.call("cut_by_transcript", path=str(project), clip_id=clip_id, cut=[[2, 3]])
        return await client.call("timeline_view", path=str(project))

    words = {w["index"]: w for w in anyio.run(_with_server, body)["words"]}

    assert all(w["paragraph"] == 0 for w in words.values())
    # A cut word still gets a paragraph — it is a document property, not an
    # edit one.
    assert words[2]["present"] is False
    assert words[2]["paragraph"] == 0


@needs_ffprobe
def test_timeline_view_words_carries_a_pause_after_field_above_threshold(
    tmp_path: Path, sources: tuple[Path, Path]
) -> None:
    """The read model over the wire: `sources`' 8 words sit two-per-burst,
    0.1s apart within a burst and 1.1s apart across a burst boundary — so
    only the second word of each burst (except the last) should carry
    `pause_after`. ops._gap_after/_word_placements are unit-tested directly
    in test_ops_pause_markers.py; this only checks the field rides through
    the real `timeline_view` call unmodified.
    """
    audio, transcript = sources
    project = tmp_path / "proj"

    async def body(session: ClientSession) -> Any:
        client = Client(session)
        await _seeded(client, project, audio, transcript)
        return await client.call("timeline_view", path=str(project))

    words = {w["index"]: w for w in anyio.run(_with_server, body)["words"]}

    for i in (1, 3, 5):
        assert words[i]["pause_after"]["duration"] == pytest.approx(1.1)
        assert words[i]["pause_after"]["present"] is True
    for i in (0, 2, 4, 6, 7):
        assert "pause_after" not in words[i]


@needs_ffprobe
def test_cut_by_transcript_through_pause_extends_the_removed_range_to_the_next_word(
    tmp_path: Path, sources: tuple[Path, Path]
) -> None:
    """Cutting the phrase ending at word 3 (w11, end 4.9s) sits right before
    the 1.1s gap to word 4 (w20, start 6.0s) — wide enough to have drawn a
    `[1.1s]` marker. `through_pause=True` should extend the removed range's
    trailing edge onto that gap; without the flag the pinned boundary
    (test_cut_plan_resolves_without_touching_the_timeline, `word_end ==
    4.9`) holds unmodified.
    """
    audio, transcript = sources

    async def with_flag(project: Path) -> dict[str, Any]:
        async def body(session: ClientSession) -> Any:
            client = Client(session)
            clip_id = await _seeded(client, project, audio, transcript)
            return await client.call(
                "cut_by_transcript",
                path=str(project),
                clip_id=clip_id,
                cut=[[2, 3]],
                through_pause=True,
            )

        return await _with_server(body)

    async def without_flag(project: Path) -> dict[str, Any]:
        async def body(session: ClientSession) -> Any:
            client = Client(session)
            clip_id = await _seeded(client, project, audio, transcript)
            return await client.call(
                "cut_by_transcript", path=str(project), clip_id=clip_id, cut=[[2, 3]]
            )

        return await _with_server(body)

    extended = anyio.run(with_flag, tmp_path / "proj-flagged")
    plain = anyio.run(without_flag, tmp_path / "proj-plain")

    # Regression guard: the no-flag boundary is exactly the last word's own
    # `end`, matching the pinned assertion elsewhere in this file.
    assert plain["applied"][0]["source_end"] == pytest.approx(4.9)
    assert plain["applied"][0]["word_end"] == pytest.approx(4.9)

    # With the flag, the removed range's trailing edge reaches the next
    # word's own start (6.0s) — the pause between them is gone too — while
    # the echoed `word_end` (the words themselves) is unaffected, exactly
    # the way `pad` already diverges `source_end` from `word_end`.
    assert extended["applied"][0]["source_end"] == pytest.approx(6.0)
    assert extended["applied"][0]["word_end"] == pytest.approx(4.9)
    assert extended["removed"] == pytest.approx(plain["removed"] + 1.1, abs=1e-6)


@needs_ffprobe
def test_cut_by_transcript_through_pause_has_no_effect_under_the_marker_threshold(
    tmp_path: Path, sources: tuple[Path, Path]
) -> None:
    """Word 0 (w00, end 0.9s) sits only 0.1s from word 1 (w01, start 1.0s) —
    under PAUSE_MARKER_MIN, so no marker would have drawn there. The shared
    predicate makes `through_pause=True` a safe no-op on that boundary.
    """
    audio, transcript = sources
    project = tmp_path / "proj"

    async def body(session: ClientSession) -> Any:
        client = Client(session)
        clip_id = await _seeded(client, project, audio, transcript)
        return await client.call(
            "cut_by_transcript",
            path=str(project),
            clip_id=clip_id,
            cut=[[0, 0]],
            through_pause=True,
        )

    out = anyio.run(_with_server, body)
    applied = out["applied"][0]
    assert applied["source_end"] == pytest.approx(0.9)
    assert applied["word_end"] == pytest.approx(0.9)


# -- the layered timeline over the wire ----------------------------------
#
# `export` grew a second writer (PLAN.md § The layered timeline, step 4): a
# project with a cue table is written as MLT by lucid itself, because
# auto-editor refuses a second source on export and renders one at 720x576
# while exiting 0. Which writer ran is a property of the project, never of an
# argument, so these go through the real tool calls that build that project.


@needs_ffprobe
@needs_ffmpeg
def test_a_cue_table_makes_export_write_mlt_itself(tmp_path: Path) -> None:
    audio, transcript = _make_sources(tmp_path)
    film = tmp_path / "film.mp4"
    _make_video(film, duration=12.0)
    project = tmp_path / "proj"
    out = tmp_path / "out.kdenlive"

    async def body(session: ClientSession) -> Any:
        client = Client(session)
        clip_id = await _seeded(client, project, audio, transcript)
        asset = await client.call("import_media", path=str(project), source=str(film))
        await client.call(
            "cue_add", path=str(project), clip_id=clip_id, word_index=0, asset=asset["clip_id"]
        )
        await client.call(
            "cue_add", path=str(project), clip_id=clip_id, word_index=4, asset=asset["clip_id"]
        )
        shots = await client.call("build_shots", path=str(project), fps=30)
        return {
            "shots": shots,
            "export": await client.call("export", path=str(project), output=str(out)),
        }

    result = anyio.run(_with_server, body)

    assert result["export"]["writer"] == "mlt"
    assert result["export"]["shots"] == 2
    # The lane is quantised on the export's grid, not on the project's
    # millisecond timebase — asking for shots on 30 gives the same total.
    assert result["shots"]["total_frames"] == result["export"]["frames"]
    assert 'frame_rate_num="30"' in out.read_text(encoding="utf-8")


@needs_ffprobe
@needs_ffmpeg
def test_a_pinned_cue_puts_its_in_point_into_the_document(tmp_path: Path) -> None:
    """`cue_add`'s `src_start` is reachable over the wire and lands in the XML.

    The end of the b-roll chain: `describe` finds a moment, `describe_ls`
    reports its `src_start`, and this is where that number becomes the `in`
    on an entry melt reads. Asserted off the written document rather than off
    `build_shots`, because the projection deliberately does not decide the
    in-point — only the writer does, and a number that was right in the plan
    and absent from the XML is exactly the bug this file exists to catch.
    """
    audio, transcript = _make_sources(tmp_path)
    film = tmp_path / "film.mp4"
    _make_video(film, duration=20.0)
    project = tmp_path / "proj"
    out = tmp_path / "out.kdenlive"

    async def body(session: ClientSession) -> Any:
        client = Client(session)
        clip_id = await _seeded(client, project, audio, transcript)
        asset = await client.call("import_media", path=str(project), source=str(film))
        await client.call(
            "cue_add", path=str(project), clip_id=clip_id, word_index=0, asset=asset["clip_id"]
        )
        pinned = await client.call(
            "cue_add",
            path=str(project),
            clip_id=clip_id,
            word_index=4,
            asset=asset["clip_id"],
            src_start=7.0,
        )
        return {
            "pinned": pinned,
            "listed": await client.call("cue_ls", path=str(project)),
            "export": await client.call("export", path=str(project), output=str(out)),
        }

    result = anyio.run(_with_server, body)

    assert result["pinned"]["src_start"] == 7.0
    assert [c["src_start"] for c in result["listed"]["cues"]] == [None, 7.0]
    assert result["export"]["writer"] == "mlt"

    document = ET.fromstring(out.read_text(encoding="utf-8"))
    film_nodes = {
        node.get("id")
        for node in document.iter()
        if node.tag in {"chain", "producer"}
        and any(
            p.get("name") == "resource" and str(p.text).endswith("film.mp4")
            for p in node.findall("property")
        )
    }
    assert film_nodes, "the film never made it into the document at all"
    # Track playlists only — `main_bin` lists the same film again as a bin
    # entry, always at 0, and that one says nothing about the timeline.
    picture_ins = [
        int(entry.get("in"))
        for playlist in document.iter("playlist")
        if playlist.get("id") != "main_bin"
        for entry in playlist.findall("entry")
        if entry.get("producer") in film_nodes
    ]
    # Two shots off the film: the unpinned one from its head, and the pinned
    # one at 7.0s * 30fps. Nothing rewound and nothing was clamped.
    assert picture_ins == [0, 210], f"expected the pin at frame 210, got {picture_ins}"


@needs_ffprobe
@needs_ffmpeg
def test_a_pinned_cue_that_outruns_its_asset_refuses_over_the_wire(tmp_path: Path) -> None:
    """The safety property, at the transport. Unpinned this same shot rewinds
    to the head of the clip and exports happily; pinned it must refuse, or the
    film quietly shows the asset's opening seconds under a cue that says it
    shows the moment at 19.0s.
    """
    audio, transcript = _make_sources(tmp_path)
    film = tmp_path / "film.mp4"
    _make_video(film, duration=20.0)
    project = tmp_path / "proj"
    out = tmp_path / "out.kdenlive"

    async def body(session: ClientSession) -> Any:
        client = Client(session)
        clip_id = await _seeded(client, project, audio, transcript)
        asset = await client.call("import_media", path=str(project), source=str(film))
        await client.call(
            "cue_add",
            path=str(project),
            clip_id=clip_id,
            word_index=0,
            asset=asset["clip_id"],
            src_start=19.0,
        )
        await client.call(
            "cue_add", path=str(project), clip_id=clip_id, word_index=4, asset=asset["clip_id"]
        )
        refused = await session.call_tool(
            "export", {"path": str(project), "output": str(out)}
        )
        return {"is_error": refused.is_error, "text": refused.content[0].text}

    result = anyio.run(_with_server, body)

    assert result["is_error"]
    assert "a pinned cue shows the moment it names" in result["text"]
    assert not out.exists(), "a refused export must leave no half-written document"


@needs_ffprobe
def test_cue_add_refuses_a_pin_on_a_card_over_the_wire(
    tmp_path: Path, sources: tuple[Path, Path]
) -> None:
    """A held frame has no playhead, so this is refused where it is cheapest —
    before any media is resolved. Over the wire because a refusal that only
    exists in `ops` is one the agent never meets."""
    audio, transcript = sources
    project = tmp_path / "proj"

    async def body(session: ClientSession) -> dict[str, Any]:
        client = Client(session)
        await client.call("init", path=str(project))
        clip = await client.call("import_media", path=str(project), source=str(audio))
        await client.call(
            "attach_transcript",
            path=str(project),
            clip_id=clip["clip_id"],
            transcript_path=str(transcript),
        )
        result = await session.call_tool(
            "cue_add",
            {
                "path": str(project),
                "clip_id": clip["clip_id"],
                "word_index": 0,
                "asset": "card:outro",
                "src_start": 3.0,
            },
        )
        return {"is_error": result.is_error, "text": result.content[0].text}

    out = anyio.run(_with_server, body)
    assert out["is_error"]
    assert "no playhead to move" in out["text"]


@needs_ffprobe
@needs_ffmpeg
@needs_melt
def test_rendering_a_cued_project_goes_through_melt_and_is_measured(
    visible_tmp: Path,
) -> None:
    """Step 5, end to end and against a real melt: a cued project renders.

    Everything here is the thing itself — a real film clip, a real cue, a real
    encode — because every failure this path routes around produces a file and
    exit 0 rather than an error. auto-editor would render this at 720x576;
    melt has no source-count gate, and what proves which one ran is the
    resolution ffprobe reads back off the finished file.

    Under `$HOME` (`visible_tmp`), not `tmp_path`: the flatpak cannot see the
    host's /tmp, and a project it cannot read renders nothing while exiting 0.
    """
    audio, transcript = _make_sources(visible_tmp)
    film = visible_tmp / "film.mp4"
    _make_video(film, duration=12.0)
    project = visible_tmp / "proj"
    output = visible_tmp / "out.mp4"

    async def body(session: ClientSession) -> Any:
        client = Client(session)
        clip_id = await _seeded(client, project, audio, transcript)
        asset = await client.call("import_media", path=str(project), source=str(film))
        await client.call(
            "cue_add", path=str(project), clip_id=clip_id, word_index=0, asset=asset["clip_id"]
        )
        rendered = await client.call(
            "export", path=str(project), output=str(output), export_format=None
        )
        return rendered, await client.call(
            "check_frames", path=str(project), target=str(output)
        )

    rendered, frames = anyio.run(_with_server, body)

    assert rendered["writer"] == "melt"
    assert rendered["format"] == "media"
    # melt's own answer before the encode, and the file's after it.
    assert rendered["melt_frames"] == rendered["frames"] == 360
    assert rendered["rendered"]["frames"] == 360
    assert (rendered["rendered"]["width"], rendered["rendered"]["height"]) == (160, 120)
    assert rendered["rendered"]["has_video"] and rendered["rendered"]["has_audio"]
    assert Path(rendered["output"]).is_file()
    # And the picture-side check agrees with it, with no tail frame to explain:
    # that defect is auto-editor's kdenlive export, and this document is lucid's.
    assert frames["delta"] == 0
    assert frames["agrees"] is True


# -- export presets --------------------------------------------------------
#
# DAYDREAM.md § Export presets maps YouTube/Web/Custom onto ops.export as
# named bundles. There is deliberately no TikTok-Reels: 9:16 is only
# producible here as a pillarbox of the 16:9 frame (verified live against the
# installed auto-editor binary while surveying this item), never a real
# reframe — that is DAYDREAM.md § Aspect swap, a separately deferred item.


@needs_ffprobe
@needs_ffmpeg
@needs_melt
def test_export_preset_youtube_reproduces_todays_default_melt_consumer(
    visible_tmp: Path,
) -> None:
    """Naming today's hardcoded melt consumer as 'youtube' changes nothing
    about what melt actually does — the encode is byte-identical."""
    audio, transcript = _make_sources(visible_tmp)
    film = visible_tmp / "film.mp4"
    _make_video(film, duration=12.0)
    project = visible_tmp / "proj"
    output = visible_tmp / "out.mp4"

    async def body(session: ClientSession) -> Any:
        client = Client(session)
        clip_id = await _seeded(client, project, audio, transcript)
        asset = await client.call("import_media", path=str(project), source=str(film))
        await client.call(
            "cue_add", path=str(project), clip_id=clip_id, word_index=0, asset=asset["clip_id"]
        )
        return await client.call(
            "export",
            path=str(project),
            output=str(output),
            export_format=None,
            preset="youtube",
        )

    rendered = anyio.run(_with_server, body)

    assert rendered["preset"] == "youtube"
    assert rendered["rendered"]["consumer"] == [
        "vcodec=libx264",
        "crf=18",
        "preset=medium",
        "acodec=aac",
    ]


@needs_ffprobe
@needs_ffmpeg
@needs_melt
def test_export_preset_web_only_varies_the_four_known_keys(visible_tmp: Path) -> None:
    """'web' varies values within melt's already-measured-safe {vcodec, crf,
    preset, acodec} — never a new key (HISTORY.md § 4's `ab`/`width`/`height`
    growth is exactly what this guards against ever being silently reopened).
    """
    audio, transcript = _make_sources(visible_tmp)
    film = visible_tmp / "film.mp4"
    _make_video(film, duration=12.0)
    project = visible_tmp / "proj"
    output = visible_tmp / "out.mp4"

    async def body(session: ClientSession) -> Any:
        client = Client(session)
        clip_id = await _seeded(client, project, audio, transcript)
        asset = await client.call("import_media", path=str(project), source=str(film))
        await client.call(
            "cue_add", path=str(project), clip_id=clip_id, word_index=0, asset=asset["clip_id"]
        )
        return await client.call(
            "export", path=str(project), output=str(output), export_format=None, preset="web"
        )

    rendered = anyio.run(_with_server, body)

    consumer = rendered["rendered"]["consumer"]
    assert "crf=23" in consumer
    assert "preset=faster" in consumer
    assert len(consumer) == 4
    assert not any(entry.startswith(("width=", "height=", "ab=")) for entry in consumer)


@needs_ffprobe
@needs_ffmpeg
def test_export_resolution_on_a_layered_project_is_refused(tmp_path: Path) -> None:
    """melt's consumer is deliberately hardcoded shut against width/height —
    HISTORY.md § 4's growth to 14.6 GB was never isolated to a safe subset —
    so a layered project refuses `resolution` outright, before any subprocess
    runs."""
    audio, transcript = _make_sources(tmp_path)
    film = tmp_path / "film.mp4"
    _make_video(film, duration=12.0)
    project = tmp_path / "proj"

    async def body(session: ClientSession) -> Any:
        client = Client(session)
        clip_id = await _seeded(client, project, audio, transcript)
        asset = await client.call("import_media", path=str(project), source=str(film))
        await client.call(
            "cue_add", path=str(project), clip_id=clip_id, word_index=0, asset=asset["clip_id"]
        )
        result = await session.call_tool(
            "export",
            {
                "path": str(project),
                "output": str(tmp_path / "out.mp4"),
                "export_format": None,
                "resolution": [608, 1080],
            },
        )
        return result

    result = anyio.run(_with_server, body)
    assert result.is_error
    text = result.content[0].text
    assert "14.6" in text or "HISTORY" in text
    assert "single-source" in text


def test_unknown_export_preset_lists_available_names_and_names_why_tiktok_reels_is_absent(
    tmp_path: Path, sources: tuple[Path, Path]
) -> None:
    audio, transcript = sources
    project = tmp_path / "proj"

    async def body(session: ClientSession) -> Any:
        client = Client(session)
        await _seeded(client, project, audio, transcript)
        return await session.call_tool(
            "export",
            {
                "path": str(project),
                "output": str(tmp_path / "out.wav"),
                "export_format": None,
                "preset": "tiktok-reels",
            },
        )

    result = anyio.run(_with_server, body)
    assert result.is_error
    text = result.content[0].text
    assert "youtube" in text and "web" in text and "custom" in text
    assert "tiktok" in text.lower() or "aspect" in text.lower()


def test_preset_or_resolution_with_an_nle_export_format_is_refused(
    tmp_path: Path, sources: tuple[Path, Path]
) -> None:
    audio, transcript = sources
    project = tmp_path / "proj"

    async def body(session: ClientSession) -> Any:
        client = Client(session)
        await _seeded(client, project, audio, transcript)
        return await session.call_tool(
            "export",
            {
                "path": str(project),
                "output": str(tmp_path / "out.kdenlive"),
                "export_format": "kdenlive",
                "preset": "youtube",
            },
        )

    result = anyio.run(_with_server, body)
    assert result.is_error
    assert "bitrate" in result.content[0].text


def test_custom_preset_without_resolution_is_refused(
    tmp_path: Path, sources: tuple[Path, Path]
) -> None:
    audio, transcript = sources
    project = tmp_path / "proj"

    async def body(session: ClientSession) -> Any:
        client = Client(session)
        await _seeded(client, project, audio, transcript)
        return await session.call_tool(
            "export",
            {
                "path": str(project),
                "output": str(tmp_path / "out.wav"),
                "export_format": None,
                "preset": "custom",
            },
        )

    result = anyio.run(_with_server, body)
    assert result.is_error
    assert "custom" in result.content[0].text


@needs_ffprobe
@needs_ffmpeg
@needs_auto_editor
def test_export_resolution_letterboxes_a_single_source_render_and_reports_the_measured_size(
    tmp_path: Path,
) -> None:
    source = tmp_path / "pic.mp4"
    _make_video(source, duration=2.0)
    project = tmp_path / "proj"
    render = tmp_path / "out.mp4"

    words = [{"word": f"w{i:02d}", "start": i * 0.5, "end": i * 0.5 + 0.4} for i in range(4)]
    transcript = tmp_path / "pic.json"
    transcript.write_text(json.dumps({"language": "en", "words": words}), encoding="utf-8")

    async def body(session: ClientSession) -> Any:
        client = Client(session)
        await _seeded(client, project, source, transcript)
        return await client.call(
            "export",
            path=str(project),
            output=str(render),
            export_format=None,
            preset="custom",
            resolution=[608, 1080],
        )

    result = anyio.run(_with_server, body)

    assert result["resolution"] == [608, 1080]
    assert result["notes"] == []
    assert Path(result["output"]).is_file()
    info = media.probe(render)
    assert (info.width, info.height) == (608, 1080)


@needs_ffprobe
@needs_ffmpeg
@needs_auto_editor
def test_export_resolution_is_a_documented_noop_on_an_audio_only_project(
    tmp_path: Path, sources: tuple[Path, Path]
) -> None:
    audio, transcript = sources
    project = tmp_path / "proj"
    render = tmp_path / "out.wav"

    async def body(session: ClientSession) -> Any:
        client = Client(session)
        await _seeded(client, project, audio, transcript)
        return await client.call(
            "export",
            path=str(project),
            output=str(render),
            export_format=None,
            preset="custom",
            resolution=[608, 1080],
        )

    result = anyio.run(_with_server, body)

    assert result["resolution"] is None
    assert any("no video stream" in note for note in result["notes"])
    assert Path(result["output"]).is_file()


# -- the bound server ---------------------------------------------------------
#
# `lucid -C <project> mcp` binds the server to one project. The web UI's agent
# panel spawns exactly this (`webui.py`'s generated MCP config), and it is the
# half of that panel's confinement that `--strict-mcp-config` and `--tools ""`
# do not cover: those keep the agent inside lucid's ops, this keeps it inside
# *this project's*. Every check below goes over the wire for the usual reason
# — the binding lives in the CLI-to-server wiring, which is exactly what a
# direct call to a tool function cannot see.


def _bound(root: Path) -> StdioServerParameters:
    return StdioServerParameters(
        command=sys.executable, args=["-m", "lucid.cli", "-C", str(root), "mcp"]
    )


async def _refused(session: ClientSession, tool: str, **arguments: Any) -> str:
    """Call a tool expecting a refusal, and return the message it refused with."""
    result = await session.call_tool(tool, arguments)
    text = result.content[0].text
    assert result.is_error, f"{tool} was expected to be refused, but returned: {text}"
    return text


def _two_projects(tmp_path: Path) -> tuple[Path, Path]:
    project, other = tmp_path / "proj", tmp_path / "other"
    ops.init(str(project))
    ops.init(str(other))
    return project, other


def test_a_bound_server_serves_its_own_project(tmp_path: Path) -> None:
    project, _ = _two_projects(tmp_path)

    async def body(session: ClientSession) -> Any:
        return await Client(session).call("cue_ls", path=str(project))

    assert anyio.run(_with_server, body, _bound(project))["count"] == 0


def test_a_bound_server_refuses_another_project(tmp_path: Path) -> None:
    """The hole this binding closes: every tool takes an explicit `path`."""
    project, other = _two_projects(tmp_path)

    async def body(session: ClientSession) -> Any:
        return await _refused(session, "cue_ls", path=str(other))

    message = anyio.run(_with_server, body, _bound(project))
    assert str(project) in message and str(other) in message


def test_a_bound_server_resolves_a_relative_path_against_its_project(tmp_path: Path) -> None:
    """A bound server means "this project", not "wherever the client stands".

    The proof is that this succeeds at all: the test process runs from the
    repo, which is not a lucid project, so a "." resolved against the cwd
    could only fail.
    """
    project, _ = _two_projects(tmp_path)

    async def body(session: ClientSession) -> Any:
        return await Client(session).call("cue_ls", path=".")

    assert anyio.run(_with_server, body, _bound(project))["count"] == 0


def test_a_bound_server_refuses_an_escape_by_parent_or_symlink(tmp_path: Path) -> None:
    """Both sides resolve, so `..` and a symlink out are refused, not followed."""
    project, other = _two_projects(tmp_path)
    (project / "elsewhere").symlink_to(other, target_is_directory=True)

    async def body(session: ClientSession) -> Any:
        return [
            await _refused(session, "cue_ls", path="../other"),
            await _refused(session, "cue_ls", path=str(project / "elsewhere")),
        ]

    for message in anyio.run(_with_server, body, _bound(project)):
        assert str(other) in message


def test_an_unbound_server_still_reaches_any_project(tmp_path: Path) -> None:
    """`lucid mcp` with no `-C` is the general-client case and is unconfined.

    `main()` defaults `-C` to ".", so this is what would break if the binding
    were applied whenever the default was present rather than when the flag
    was typed.
    """
    _, other = _two_projects(tmp_path)

    async def body(session: ClientSession) -> Any:
        return await Client(session).call("cue_ls", path=str(other))

    assert anyio.run(_with_server, body)["count"] == 0


def test_binding_does_not_change_the_advertised_tool_schema(tmp_path: Path) -> None:
    """The confinement is a wrapper, and a wrapper that reshaped the schema
    would change the tool surface for every client. `functools.wraps` sets
    `__wrapped__` and the SDK's `inspect.signature(fn, eval_str=True)`
    follows it; this is that claim, asserted rather than trusted."""
    project, _ = _two_projects(tmp_path)

    async def body(session: ClientSession) -> Any:
        return await session.list_tools()

    unbound = {t.name: t.input_schema for t in anyio.run(_with_server, body).tools}
    bound = {t.name: t.input_schema for t in anyio.run(_with_server, body, _bound(project)).tools}

    assert set(bound) == EXPECTED_TOOLS
    assert bound == unbound


def test_binding_to_a_directory_that_is_not_there_fails_at_startup() -> None:
    """A bad root is caught when the server starts rather than on every call,
    which would blame the client's argument for the server's own start-up."""
    result = subprocess.run(
        [sys.executable, "-m", "lucid.cli", "-C", "/nonexistent-project", "mcp"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    assert "not a directory" in result.stderr


def test_every_tool_taking_a_path_goes_through_the_binding() -> None:
    """A tool registered with `@mcp.tool()` instead of `@_tool()` would work,
    advertise an identical schema, and quietly not be confined — so the
    invariant is asserted rather than left to review. `@_tool()` returns the
    wrapper for anything taking a `path`, and `functools.wraps` is what puts
    `__wrapped__` on it; `mcp.tool()` returns the function untouched.
    """
    import lucid.server as server_module

    for name in sorted(EXPECTED_TOOLS):
        fn = getattr(server_module, name)
        takes_path = "path" in inspect.signature(fn).parameters
        confined = hasattr(fn, "__wrapped__")
        assert takes_path == confined, (
            f"{name} takes path={takes_path} but is confined={confined} — "
            "a tool with a `path` argument must be registered with `@_tool()`, "
            "not `@mcp.tool()`, or it escapes the -C binding"
        )
