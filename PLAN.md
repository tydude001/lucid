# lucid — planning

Working document for architecture and scope decisions. Nothing here is built
yet; edits to this file are the project until the first line of code.

## Tier 1 MVP — headless MCP server

One binary/package, `lucid`, usable two ways:

- `lucid mcp` — MCP server (stdio) that Claude Code or any MCP client connects to
- `lucid <subcommand>` — same operations as a plain CLI for scripting/debugging

### Project model

A *project* is a directory: source media, a `project.otio` timeline, a
transcript cache, and rendered outputs. Everything on disk, everything
inspectable, nothing uploaded. The OTIO file is the single source of truth
the MCP tools mutate; renders are derived from it.

### MVP tool surface

| Tool | Backed by | Notes |
|---|---|---|
| `import_media` | ffprobe | register clips, probe codecs/fps/duration |
| `transcribe` | faster-whisper | word-level timestamps, cached per clip |
| `get_transcript` | cache | agent reads text + timings to plan cuts |
| `cut_by_transcript` | OTIO | cut/keep ranges expressed as words or times |
| `remove_silences` | auto-editor | thresholds as parameters |
| `add_captions` | ffmpeg subtitles | burn-in; styled via a small preset set |
| `render` | ffmpeg | preview (low-res, fast) and final quality |
| `export_otio` | OTIO adapters | FCPXML etc. for finishing in a real NLE |

Deliberately absent from MVP: motion graphics (tier 1.5, Motion Canvas),
b-roll generation, any GUI.

### Stack decision

**Python.** faster-whisper, OpenTimelineIO, and auto-editor are all Python;
the MCP SDK is solid; ffmpeg is subprocess either way. A Rust core would be
nicer to ship but would mean reimplementing or FFI-wrapping all three
primitives. Revisit only if performance actually hurts.

## Open questions

- **Timeline semantics for the agent.** Does the agent address the timeline
  by transcript ranges only, or also by clip/segment IDs? Transcript-only is
  simpler but breaks down for footage with no speech (b-roll, music).
- **Word-timestamp accuracy.** whisper word timings drift on long recordings;
  may need forced alignment (e.g. WhisperX-style) for frame-accurate cuts.
  Decide after testing on real footage.
- **Variable frame rate footage.** Phone/screen recordings are often VFR and
  break naive cut math. Probably normalize to CFR on import; costs a
  transcode. Verify against real screen recordings.
- **Caption styling.** ASS subtitles give full styling control but the format
  is miserable to generate; SRT + ffmpeg `force_style` is limited. Pick after
  the first caption prototype.
- **Preview delivery in tier 1.** Even headless, the user wants to *see* a
  cut. Cheapest option: render low-res MP4 and open it locally. A web preview
  belongs to tier 2 — don't drag it forward.

## Non-goals (write them down so they stay dead)

- Cloud anything. No accounts, no metering, no upload.
- Competing with Resolve/Premiere on finishing. Export to them instead.
- A plugin system before there are two users.

## First milestones

1. Skeleton: package layout, `lucid mcp` serving a `ping` tool, project
   directory format.
2. `import_media` + `transcribe` + `get_transcript` working on a real clip.
3. `cut_by_transcript` + `render` — the first end-to-end "cut this sentence
   out" from a Claude Code session.
4. `remove_silences`, `add_captions`, `export_otio`.
5. Dogfood on a real recording; promote pain points to the plan.
