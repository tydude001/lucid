# lucid

An open-source, local-first AI video editor. A lucid dream is a dream you
control — lucid is the answer to [Daydream](https://www.daydreamvideo.com):
the same agent-driven editing workflow, but open, unmetered, and running
entirely on your own hardware.

## The idea

Daydream's product is a desktop editor where AI agents (Claude Code, Codex)
do the editing — trim by transcript, remove silences, add captions and motion
graphics — via chat or an MCP server, with metered transcription hours,
processing hours, and MCP calls.

Every hard primitive under that product already exists as mature open source:

| Capability | Open-source primitive |
|---|---|
| Cutting, concat, captions, rendering | ffmpeg |
| Local transcription (30+ languages) | whisper.cpp / faster-whisper |
| Silence and bad-take removal | auto-editor |
| Timeline data model + NLE export | OpenTimelineIO (FCPXML, etc.) |
| Programmatic motion graphics | Motion Canvas |

lucid is the orchestration layer on top: an MCP server that exposes those
primitives as editing tools to any agent, so "cut the part where I stumble
and caption the rest" becomes a chat message instead of an afternoon.

## Scope, in tiers

1. **Headless MCP server + CLI** — import, transcribe, cut by transcript,
   remove silences, caption, render, export MP4/OTIO. ~70% of the value for
   anyone already living in an agent CLI. This is the MVP.
2. **Preview/timeline web UI** — see what the agent did before rendering.
3. **Full desktop editor** — explicitly *not* a goal. OTIO export hands
   finishing work to Resolve/Premiere/Final Cut, same as Daydream does.

## Try it

Trimming the retakes out of a voiceover, end to end:

```sh
uv sync
uv run lucid init myproject
uv run lucid -C myproject import VO.wav --clip-id vo
uv run lucid -C myproject attach-transcript vo VO.json   # word-timed whisper JSON
uv run lucid -C myproject seed vo                        # auto-editor strips silences
uv run lucid -C myproject transcript vo --search "here's the thing"
uv run lucid -C myproject cut vo 111:114 --pad 0.1       # inclusive word range
uv run lucid -C myproject export cut.kdenlive            # an MLT project to finish in
```

`--render` exports media instead of an NLE project, and `undo` rolls back the
last mutation. Every subcommand is also an MCP tool — that parity is enforced
by the test suite — so an agent drives the same operations:

```sh
uv run lucid mcp                                          # serve MCP over stdio
claude mcp add lucid -- uv run --project /path/to/lucid lucid mcp
```

Word indices address the *original* recording and never renumber, so a range
stays valid however many cuts have accumulated on top of it.

Captions are generated from the *timeline*, not the transcript, so they stay
correct after cuts:

```sh
lucid captions subs.ass --preset karaoke     # sidecar ASS, Kdenlive loads it
lucid captions subs.ass --burn render.mp4    # or burn in with ffmpeg
```

`transcribe` and multi-track editing are not built yet — see the milestones in
[PLAN.md](PLAN.md).

## Development

```sh
uv sync
uv run pytest
```

The suite spawns a real `lucid mcp` subprocess and speaks MCP over its stdio,
so expect it to be a little slower than a pure unit suite.

## Planning

See [PLAN.md](PLAN.md) for architecture, stack decisions, and open questions,
and [PRIOR-ART.md](PRIOR-ART.md) for the survey of what else exists in this
space and what lucid does that they don't. Project status is tracked in the
wiki's Open items table, not here.
