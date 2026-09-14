# lucid

A source-available, local-first AI video editor. A lucid dream is a dream you
control — lucid puts an AI agent on your timeline and keeps the whole thing
on hardware you own: no cloud, no accounts, no metering.

https://github.com/user-attachments/assets/3c3517cd-1113-43f1-bdea-b5c11473ab10

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
| Local transcription (30+ languages) | openai-whisper |
| Silence and bad-take removal | auto-editor |
| Timeline data model + NLE export | OpenTimelineIO (FCPXML, etc.) |
| Layered rendering (b-roll, cards, music) | MLT |
| Title and end cards | SVG templates, rasterised by ImageMagick |

lucid is the orchestration layer on top: an MCP server that exposes those
primitives as editing tools to any agent that speaks MCP (Claude Code, Codex,
your own), so "cut the part where I stumble and caption the rest" becomes a
chat message instead of an afternoon.

It ships as three clients of one engine, all driving the same operations: a
CLI, an MCP server (every tool has a matching subcommand, enforced by the
test suite), and a browser workspace — transcript, preview, a draggable
timeline, framing review and export, with the agent in the window. The
non-goals are permanent: no cloud, no accounts, no metering.

## Help wanted: the first run on a Mac

Nobody has ever run lucid on a Mac. If you have one and half an hour, one
script installs what lucid needs, makes a short test video, has lucid cut,
render and check it, and puts a report on your Desktop:

```sh
git clone https://github.com/tydude001/lucid
bash lucid/scripts/mac_trial.sh
```

It installs `uv`, `ffmpeg-full`, `espeak-ng` and `auto-editor` with Homebrew (and
Homebrew, if you have none), the Shotcut app for its renderer, and whisper,
and it asks before starting. It keeps a list of what it added, and `bash
lucid/scripts/mac_trial.sh --uninstall` removes exactly that and nothing you
already had. Then [file the report](https://github.com/tydude001/lucid/issues/new?template=mac-test.yml)
— a run that stops at the first step is just as useful, because where it
stops is the finding.

## Help wanted: the first run on Windows

Nobody has run lucid on a Windows PC either. GitHub's Windows runner takes
the same demo to a checked render, but a runner never reads the
instructions. If you have a PC and half an hour, from PowerShell:

```powershell
git clone https://github.com/tydude001/lucid
powershell -ExecutionPolicy Bypass -File lucid\scripts\windows_trial.ps1
```

It downloads `uv`, `ffmpeg`, `auto-editor`, `espeak-ng`, Shotcut's renderer
and whisper into one folder under `%LOCALAPPDATA%`, with nothing installed
system-wide and no administrator rights, and it asks before starting. The
same command with `-Uninstall` removes that folder. It puts
`lucid-windows-report.zip` on your Desktop with your home folder's name taken
out; [file the report](https://github.com/tydude001/lucid/issues/new?template=windows-test.yml)
— a run that stops at the first step is just as useful.

## Requirements

lucid is developed on Linux (a Fedora-based desktop). On macOS the test
suite passes on CI and GitHub's macOS runner takes the demo to a checked
render, but no person has run it on a Mac yet. Windows is the same: the
suite passes on CI and GitHub's Windows runner takes the demo to a checked
render, and no person has run it on Windows yet. What a port takes, and where
each OS stands, is [docs/plans/PORTABILITY.md](docs/plans/PORTABILITY.md).

- **Python 3.13** and [uv](https://docs.astral.sh/uv/) — `uv sync` installs
  the Python side (the only runtime dependencies are `mcp` and
  OpenTimelineIO).
- **ffmpeg / ffprobe** on `PATH`, built with `libx264`, freetype and libass —
  every media operation goes through them, the demo labels its footage with
  `drawtext`, and captions burn through libass. Fedora's default `ffmpeg-free`
  has no `libx264`; swap in RPM Fusion's `ffmpeg`. Homebrew's `ffmpeg` has
  neither freetype nor libass; install `ffmpeg-full` and put
  `$(brew --prefix ffmpeg-full)/bin` first on `PATH`, since it is keg-only.
- **[auto-editor](https://github.com/WyattBlue/auto-editor) 31+** — silence
  removal and single-source rendering. Install the upstream binary; the PyPI
  package is a stale 29.x.
- **whisper** — transcription and render verification. A subprocess, never an
  import: any `openai-whisper` install works (`uv tool install
  openai-whisper` is the short route), resolved via `LUCID_WHISPER`, then
  `PATH`. Without an NVIDIA GPU, add `--torch-backend cpu`. The default pulls
  CUDA torch, 5.5 GB against 1.9 GB. The CPU build transcribed the demo's
  19-second voiceover in 33 seconds.
- **MLT (`melt`)** — renders layered timelines (b-roll, cards, music). Your
  distribution's `melt` package (`mlt` on Fedora, whose `melt` package is an
  unrelated compression tool), or a Kdenlive install (the flatpak's own is
  found automatically); `LUCID_MELT` overrides both.

Run `lucid doctor` to check all of this at once — it probes every binary,
reports what it found and where, and names the fix for anything missing.

Optional, feature-gated — `lucid doctor` reports each as available or not,
and everything else works without them:

- **ImageMagick 7 (`magick`)** — rasterises title and end cards. Distributions
  that still package ImageMagick 6 (Ubuntu 24.04 does) need
  ImageMagick's own build; IM6's `convert` is not used.
- **[Claude Code](https://docs.claude.com/en/docs/claude-code)** (`claude`,
  logged in) — the agent pane in the workspace. `lucid mcp` works with any
  MCP client; only the pane spawns `claude` itself.
- **`LUCID_VLM`** — the python of a venv with torch, transformers,
  bitsandbytes and Pillow, on a CUDA GPU. Powers `describe` (b-roll search by
  what's on screen); the Qwen2.5-VL model downloads on first use.
- **`LUCID_FACE`** — the python of a venv with insightface, onnxruntime and
  opencv-python. Powers `reframe-detect` (face-aware crop proposals).
- **`LUCID_TTS`, `LUCID_TTS_MODEL` and `LUCID_TTS_VOICE`** — a python with
  qwen-tts and a CUDA torch, a local Qwen3-TTS snapshot, and a directory
  holding a reference clip of the voice. Powers `vo-synth`. There is no
  default voice, on purpose.

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

In Claude Code, the plugin is the shorter route — it registers the same MCP
server, so the 90 editing tools are there without an `mcp add` of your own:

```
/plugin marketplace add tydude001/lucid
/plugin install lucid@lucid
```

The plugin's first start downloads lucid's Python and its dependencies, about
175 MB, and Claude Code gives a server 30 seconds to connect. On a slower
line, start that first session as `MCP_TIMEOUT=300000 claude`; if `/mcp`
already shows lucid as failed, reconnect it there — the download keeps what
it fetched.

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
- **B-roll by description** — `describe` writes what is visible in each
  ~10-second window of footage; reading it back *is* the search, and a cue
  table addressed by word index lays clips and cards over the voiceover.
- **An agent that can look** — `shot-sheet` draws the whole picture track as one
  labelled grid and `footage-sheet` browses a clip you have not cut yet, both
  returning the *image* over MCP rather than a path an agent cannot open. The
  second needs no edit and no transcript, which is the point: it is for footage
  with no dialogue to search. What they show is a hypothesis; the checks above
  are what settle one.
- **Cards** — six SVG templates rasterised at the project's own canvas,
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
so expect it to be a little slower than a pure unit suite. Tests that need
whisper, auto-editor, melt or ImageMagick skip where the binary is absent. The
seven tests that render through `melt` also need a desktop session, or on a
headless box `QT_QPA_PLATFORM=offscreen` where your MLT honours it and
`xvfb-run -a` where it does not (`lucid doctor` renders a probe frame to tell
you which). Without one they fail with "no display for MLT's Qt module to
open", which is the environment, not a regression.

[CONTRIBUTING.md](CONTRIBUTING.md) has the rules a pull request is checked
against, and [SECURITY.md](SECURITY.md) how to report a vulnerability.

## Documentation

Start with the manual; the rest is here because lucid's reasoning is part of
what it ships.

- [docs/MANUAL.md](docs/MANUAL.md) — every command, with the rationale.
- [docs/DEMO.md](docs/DEMO.md) — the whole loop in two minutes, on footage
  the repo generates.

**Live — what lucid is and what it learned.**

- [PLAN.md](docs/PLAN.md) — architecture, stack decisions, open questions.
- [HISTORY.md](docs/HISTORY.md) — the dated record of what shipped and what the
  evidence said, first real video included.
- [PRIOR-ART.md](docs/PRIOR-ART.md) — the survey of what else exists in this space
  and what lucid does that they don't.
- [NEXT.md](docs/NEXT.md) — the three directions after the queues closed, ranked.
- [TRIAL.md](docs/TRIAL.md) — an agent cutting a video end to end, unattended and
  scored, plus the queue its failures became.

**Shipped plans — [docs/plans/](docs/plans).** Each was built to completion; they
are kept because the design reasoning and the measurements behind it are cited
throughout the code, not because any work is outstanding.

- [DAYDREAM.md](docs/plans/DAYDREAM.md) — the feature map drawn from
  [Daydream](https://www.daydreamvideo.com), the closest commercial product.
- [STUDIO.md](docs/plans/STUDIO.md) — the Home/Edit/Frame/Finish workspace,
  which supersedes the Daydream build order where the two conflict.
- [POLISH.md](docs/plans/POLISH.md) — the works-for-anyone pass: doctor, the
  demo project, manifest-aware undo.

## License

[PolyForm Shield 1.0.0](LICENSE) — that covers the code. It is
source-available rather than open source: you can read it, run it, change it
and redistribute it for any purpose except one, which is providing a product
that competes with lucid. Cutting your own videos with it, building on it,
running it for clients, forking it to fix a bug — all fine. Shipping it, or a
derivative, as a rival editor is the one reserved use. Anyone who wants that
can ask for a commercial licence.

The vendored typefaces are not lucid's to relicense: the caption face under
`src/lucid/fonts/` and the three browser faces under `src/lucid/web/` are
OFL-1.1, each shipping its licence text beside it and its provenance in that
directory's `FONTS.md`.
