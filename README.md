# lucid

An open-source, local-first AI video editor. A lucid dream is a dream you
control — lucid puts an AI agent on your timeline and keeps the whole thing
on hardware you own: no cloud, no accounts, no metering.

![The lucid workspace on the demo project: the transcript with a retake struck
through, the preview drawing the shot under the playhead with its captions, the
side rail on its agent tab reporting a finished render against the timeline,
and the layered timeline below — picture, waveform and captions as three
projections of one edit](docs/img/edit-mode.png)

## The idea

Most of editing is finding the parts worth keeping, and that work is turning
into a conversation. Trim by transcript, drop the silences, caption the rest,
lay pictures over the voiceover — an agent can do all of it, if something
gives it real tools to do it with. The products built on that idea so far are
desktop apps wrapped around a metered cloud service, billing transcription
hours, processing hours and agent calls.

Every hard primitive under such a product already exists as mature open
source:

| Capability | Open-source primitive |
|---|---|
| Cutting, concat, captions, rendering | ffmpeg |
| Local transcription (30+ languages) | whisper (openai / .cpp / faster-whisper) |
| Silence and bad-take removal | auto-editor |
| Timeline data model + NLE export | OpenTimelineIO (FCPXML, etc.) |
| Programmatic motion graphics | Motion Canvas |

lucid is the orchestration layer on top: an MCP server that exposes those
primitives as editing tools to any agent that speaks MCP (Claude Code, Codex,
your own), so "cut the part where I stumble and caption the rest" becomes a
chat message instead of an afternoon.

It ships as three clients of one engine, all driving the same operations: a
CLI, an MCP server (every tool has a matching subcommand, enforced by the
test suite), and a browser workspace — transcript, preview, a draggable
timeline, framing review and export, with the agent in the window. Those
three non-goals are permanent.

## Requirements

- **Python 3.13** and [uv](https://docs.astral.sh/uv/) — `uv sync` installs
  the Python side (the only runtime dependencies are `mcp` and
  OpenTimelineIO).
- **ffmpeg / ffprobe** on `PATH` — every media operation goes through them.
- **[auto-editor](https://github.com/WyattBlue/auto-editor) 31+** — silence
  removal and single-source rendering. Install the upstream binary; the PyPI
  package is a stale 29.x.
- **whisper** — transcription and render verification. A subprocess, never an
  import: any `openai-whisper` install works, resolved via `LUCID_WHISPER`,
  then `PATH`, then a sibling venv.
- **MLT (`melt`)** — renders layered timelines (b-roll, cards, music). A
  Kdenlive install provides it.
- **ImageMagick (`magick`)** — rasterises title and end cards.

Run `lucid doctor` to check all of this at once — it probes every binary,
reports what it found and where, and names the fix for anything missing.

Optional, feature-gated: a torch-capable interpreter named by `LUCID_VLM`
powers `describe` (b-roll search by what's on screen), and one named by
`LUCID_FACE` powers `reframe-detect` (face-aware crop proposals).
`describe --plan` reports whether this machine can run it. Everything else
works without them.

## Try it

**No footage handy?** [docs/DEMO.md](docs/DEMO.md) is the whole loop in two
minutes on media the repo generates rather than ships — cut a retake by naming
the words, hang b-roll off a phrase, render, and have lucid check the render
against the timeline:

```sh
uv sync
uv run python scripts/make_demo.py ~/lucid-demo   # a voiceover with a real retake
```

With your own voiceover, end to end:

```sh
uv sync
uv run lucid init myproject
uv run lucid -C myproject import VO.wav --clip-id vo
uv run lucid -C myproject transcribe vo                  # whisper, word-timed
uv run lucid -C myproject seed vo                        # auto-editor strips silences
uv run lucid -C myproject transcript vo --search "here's the thing"
uv run lucid -C myproject cut vo 111:114 --plan          # what do those indices say?
uv run lucid -C myproject cut vo 111:114 --pad 0.1       # inclusive word range
uv run lucid -C myproject export final.mp4 --render      # or a .kdenlive to finish in an NLE
uv run lucid -C myproject verify final.mp4               # did the render say what you edited?
```

Or watch it instead of reading it — the workspace plays the source through
the edit, so seeing a cut costs no render:

```sh
uv run lucid -C myproject open       # server + an app window, reopens where you left off
uv run lucid -C myproject web --open # the same page in an ordinary tab
```

To let an agent drive the same project over MCP:

```sh
claude mcp add lucid -- uv run --project /path/to/lucid lucid mcp
```

## What's in the box

One line each here; the [manual](docs/MANUAL.md) walks every one of these
with the reasoning behind each behaviour.

- **Cut by transcript** — word indices address the *original* recording and
  never renumber, so a range stays valid however many cuts pile up; `--plan`
  echoes the words an index resolves to before anything is written, and
  `restore`/`undo` walk it back.
- **The workspace** — Edit (transcript, preview, drag-trim and razor), Frame
  (every crop window reviewable in place), Finish (presets, verify, the
  finished file playable in the page), with a truth strip that says while you
  edit whether the film would ship wrong.
- **Captions from the timeline, not the transcript** — they stay correct
  after cuts, and the look is project state, so a restyle survives every
  later edit. Karaoke highlight, sidecar ASS, or ffmpeg burn-in.
- **Transcript self-checks** — retake seams, invented words, swallowed
  repeats and suspect durations are reported at attach; `unspoken` lets the
  render itself testify to words nobody said.
- **Multi-mic recordings** — a container with two mics is refused until you
  say what it is (`--mix` sums, `--audio-stream k` keeps one), and
  `attribute-speakers` labels each word with who said it.
- **Render verification** — `verify` transcribes the finished file and diffs
  it against what the timeline should play, which catches the one defect
  nothing else can: a retake still in the picture. `frames`, `film-check`,
  `black` and `spots` cover the picture side.

  ![Finish mode: the per-stage report — export, caption burn, frame count
  agrees, audio verify at 0.971 similarity — beside the finished file playing
  in the page with its burnt captions, and the truth strip down to no
  flags](docs/img/finish-mode.png)
- **B-roll by description** — `describe` writes what is visible in each
  ~10-second window of footage; reading it back *is* the search, and a cue
  table addressed by word index lays clips and cards over the voiceover.
- **An agent that can look at the cut** — `shot-sheet` draws the whole picture
  track as one labelled grid, and over MCP it returns the *image*, so an agent
  can see what it edited rather than reason about a path it cannot open. What
  it shows is a hypothesis; the checks above are what settle one.
- **Cards** — five SVG templates rasterised at the project's own canvas,
  recorded so a canvas change re-authors them instead of stretching them.
- **Reframing** — per-shot source-pixel crop windows for aspect changes,
  face-aware proposals (`reframe-detect`), a review sheet that draws every
  window on its own frames, and stacked splits for two-handers.

  ![Frame mode: a shot list beside the selected shot's windows — each crop
  drawn as a rect on three of the source's own frames, over a filmstrip of the
  whole shot with the sampled instants ticked on it, the window's rect quoted
  in source pixels, Approve/Re-frame beside it, and coverage chips for stale
  framing and unexplained steps](docs/img/frame-mode.png)
- **Derived reels** — `reel` cuts a span of the film into a new project for a
  vertical teaser, reporting every picture it dropped and pinning every one
  it kept, so the reel shows what the film showed.
- **NLE round-trip** — export a `.kdenlive`/OTIO project, finish in
  Resolve/Premiere/Kdenlive, or `import-edit` the trim you made there back.
- **Layered rendering** — a timeline with a cue table or a second clip is
  written as MLT and rendered by `melt`, and the finished file is measured
  rather than trusted, because both upstream renderers exit 0 on failure.

## Status

All three planned tiers are built and in daily use: the headless MCP server +
CLI, the preview/timeline web page, and the full workspace with the agent in
the window. Multi-track — clips and cards laid over the voiceover from a
word-indexed cue table — is built end to end, and `export --render` measures
the finished file rather than trusting a renderer that exits 0 on failure.
It is still 0.x software: an old project is refused rather than guessed at,
and `lucid migrate` brings it forward.

## Development

```sh
uv sync
uv run pytest
```

The suite spawns a real `lucid mcp` subprocess and speaks MCP over its stdio,
so expect it to be a little slower than a pure unit suite. The five tests
that render through `melt` need a desktop session; on a headless box they
fail with "no display for MLT's Qt module to open", which is the environment,
not a regression.

## Documentation

- [docs/MANUAL.md](docs/MANUAL.md) — every command, with the rationale.
- [PLAN.md](PLAN.md) — architecture, stack decisions, open questions.
- [PRIOR-ART.md](PRIOR-ART.md) — the survey of what else exists in this space
  and what lucid does that they don't.
- [HISTORY.md](HISTORY.md) — the dated record of what shipped and what the
  evidence said, first real video included.
- [DAYDREAM.md](DAYDREAM.md) — the feature map drawn from
  [Daydream](https://www.daydreamvideo.com), the closest commercial product;
  [STUDIO.md](STUDIO.md) — the workspace design.

## License

[PolyForm Shield 1.0.0](LICENSE) — that covers the code. The vendored typefaces
are not covered by it and are not lucid's to relicense: the caption face under `src/lucid/fonts/` and the
three browser faces under `src/lucid/web/` are OFL-1.1, each shipping its
licence text beside it and its provenance in that directory's `FONTS.md`.
