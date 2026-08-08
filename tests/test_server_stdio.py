"""End-to-end checks against the real server process.

This spawns `lucid mcp` as a subprocess and speaks MCP over its stdio, rather
than calling the tool functions directly — the wiring between the CLI, the
transport, and the tool registry is exactly what a unit test would miss
(CLAUDE.md).
"""

from __future__ import annotations

import json
import math
import shutil
import struct
import sys
import wave
from pathlib import Path
from typing import Any

import anyio
import pytest
from mcp import ClientSession, StdioServerParameters, stdio_client

SERVER = StdioServerParameters(command=sys.executable, args=["-m", "lucid.cli", "mcp"])

#: Every tool the MCP surface is expected to expose. Asserted exactly, so a
#: tool that is written but never registered fails the suite instead of
#: silently not existing.
EXPECTED_TOOLS = {
    "ping",
    "init",
    "import_media",
    "attach_transcript",
    "transcribe",
    "get_transcript",
    "seed_timeline",
    "cut_by_transcript",
    "timeline_status",
    "undo",
    "add_captions",
    "verify",
    "export",
}

needs_ffprobe = pytest.mark.skipif(
    shutil.which("ffprobe") is None, reason="ffprobe is not installed"
)


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


@pytest.fixture
def sources(tmp_path: Path) -> tuple[Path, Path]:
    """A four-burst recording and a transcript with two words per burst."""
    audio = tmp_path / "vo.wav"
    _make_wav(audio, tones=[(0.0, 2.0), (3.0, 5.0), (6.0, 8.0), (9.0, 11.0)])

    words = []
    for burst, (start, _) in enumerate([(0.0, 2.0), (3.0, 5.0), (6.0, 8.0), (9.0, 11.0)]):
        for n in range(2):
            at = start + n
            words.append({"word": f"w{burst}{n}", "start": at, "end": at + 0.9})

    transcript = tmp_path / "vo.json"
    transcript.write_text(json.dumps({"language": "en", "words": words}), encoding="utf-8")
    return audio, transcript


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
    "import_media": "import",
    "attach_transcript": "attach-transcript",
    "transcribe": "transcribe",
    "get_transcript": "transcript",
    "seed_timeline": "seed",
    "cut_by_transcript": "cut",
    "timeline_status": "status",
    "undo": "undo",
    "add_captions": "captions",
    "verify": "verify",
    "export": "export",
}

#: CLI-only commands, with the reason each one has no tool behind it.
CLI_ONLY = {
    "mcp",  # starts the server; nothing to call it from
    "ping",  # a tool, but takes no project and needs no mapping
    "info",  # prints the raw manifest, which MCP clients get from other tools
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
def test_cut_plan_resolves_without_touching_the_timeline(
    tmp_path: Path, sources: tuple[Path, Path]
) -> None:
    """Look before you cut, and see the words either side.
    PLAN.md § `cut --plan`, and echoing what a word index resolved to.

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
def test_attach_transcript_flags_adjacent_near_duplicate_phrases(tmp_path: Path) -> None:
    """Over the wire: attach reports a retake `verify` can never catch,
    before any edit exists to diff it against (test_verify.py exercises the
    detector itself; this checks it is actually wired in).
    PLAN.md § Adjacent near-duplicate phrases at `attach-transcript`.
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
    something, usually a swallowed retake (DOGFOOD.md § 2).
    PLAN.md § Suspect word durations at `attach-transcript`.
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
    """The retake case, which is why verify exists at all (DOGFOOD § 1)."""
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
