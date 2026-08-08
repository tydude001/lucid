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
| Local transcription (30+ languages) | whisper (openai / .cpp / faster-whisper) |
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
   Cut and undo from the view too, through the same tools the CLI calls — on
   localhost, out of the same package. **Built** (`lucid web`); because it
   plays the source through the edit rather than a render of it, seeing an
   edit costs no render. [PLAN.md](PLAN.md) § The preview/timeline web UI.
3. **Full editor workspace** — **now the goal, decided 2026-08-08.** Tier 2
   shipped, got used, and came back a correct *instrument* and a poor
   *editor*: the picture is not the centre of the window, the transcript is
   one unbroken wall, 67 segments render as a barcode in a 34px strip, and the
   agent is in a different application entirely. So lucid grows a real
   workspace — three panes over an NLE timeline, with the agent *in* the
   window. [PLAN.md](PLAN.md) § Tier 3 is the goal — the Daydream-shaped
   workspace.

   Finishing moves in with it: **Export renders a watermark-free MP4 from the
   window**, and the OTIO/MLT handoff to Resolve/Premiere/Kdenlive stays as an
   additional way out rather than the only one. That is the sentence that
   crosses the tier line, and it is crossed deliberately.

   Two things that decision did **not** change. It is a workspace, not a
   desktop app: everything that makes Daydream feel like Daydream is inside
   the window, and a native shell buys chrome at the price of a second stack
   — deferred as cheap and reversible, not rejected. And the agent panel is a
   local `claude` subprocess speaking to lucid's own MCP server, restricted to
   lucid's tools and nothing else, so it reaches the timeline only through the
   tools the CLI calls, on your existing auth, with nothing uploaded. The
   non-goals — cloud, accounts, metering — stay dead.

## Try it

Trimming the retakes out of a voiceover, end to end:

```sh
uv sync
uv run lucid init myproject
uv run lucid -C myproject import VO.wav --clip-id vo
uv run lucid -C myproject attach-transcript vo VO.json   # word-timed whisper JSON
uv run lucid -C myproject transcribe vo                  # or: run whisper on vo directly
uv run lucid -C myproject seed vo                        # auto-editor strips silences
uv run lucid -C myproject transcript vo --search "here's the thing"
uv run lucid -C myproject cut vo 111:114 --plan          # what do those indices say?
uv run lucid -C myproject cut vo 111:114 --pad 0.1       # inclusive word range
uv run lucid -C myproject cut-at 40.4+4.4                # or cut by what an export played
uv run lucid -C myproject export cut.kdenlive            # an MLT project to finish in
uv run lucid -C myproject verify final.mp4               # did the render say what you edited?
```

Or watch it instead of reading it — the page plays the source through the
edit, so there is nothing to render first:

```sh
uv run lucid -C myproject web --open      # localhost; select words, preview, cut, undo
uv run lucid -C myproject view            # the same read model as JSON
```

`--render` exports media instead of an NLE project, and `undo` rolls back the
last mutation. Every subcommand is also an MCP tool — that parity is enforced
by the test suite — so an agent drives the same operations:

```sh
uv run lucid mcp                                          # serve MCP over stdio
claude mcp add lucid -- uv run --project /path/to/lucid lucid mcp
```

Word indices address the *original* recording and never renumber, so a range
stays valid however many cuts have accumulated on top of it. The flip side is
that a word index is *not* a render timestamp, and every cut moves the two
further apart — `locate` is the conversion, in the direction `cut-at` does not
go:

```sh
lucid locate vo --words 874:875              # where does that phrase play now?
lucid locate vo --at 360.1                   # or a source instant
lucid locate vo --span 127.0-130.5           # or a source interval
```

It answers in the render's own seconds, reports `present: false` for material
a cut removed rather than sliding the answer onto the neighbouring words, and
distinguishes that from a time the recording never reached. A range a cut
split comes back as one piece per survivor, so "half of it is still in there"
is a readable answer rather than a short one.

Captions are generated from the *timeline*, not the transcript, so they stay
correct after cuts:

```sh
lucid captions subs.ass --preset karaoke     # sidecar ASS, Kdenlive loads it
lucid captions subs.ass --burn render.mp4    # or burn in with ffmpeg
```

`verify` closes the loop the other way: it transcribes a finished render and
diffs it against the words the timeline should play. That catches a class of
defect nothing else does — a retake still in the picture. Whisper collapses an
immediate repeat into one utterance, so a doubled phrase can be missing from
the source transcript, never get cut, and survive into the render with nothing
in the project file to show for it. Reading the timeline can only prove the
cuts you made are the cuts you meant.

```sh
lucid verify final.mp4                       # transcribes with whisper
lucid verify final.mp4 --windowed            # second opinion, in short windows
lucid verify final.mp4 --transcript render.json   # or re-diff without re-running it
```

Similarity around 0.97 is normal on a clean render — whisper spells its own
output differently on a second pass — so the diff is the artifact, and a
`repeated` entry is the retake signal. Whisper is a subprocess, not a
dependency: set `LUCID_WHISPER` if `whisper` is not on your `PATH`.

A clean single-pass result is not proof, because that pass is itself one
whisper transcription and collapses a repeat the same way the source did.
`--windowed` transcribes in 10-second windows with 5 seconds of overlap and a
deliberately *smaller* model — a segment that ends after ten seconds has
nowhere to put an eleventh, and a bigger model tidies away the disfluency being
looked for. It costs one whisper run over twice the audio, which is seconds on
a five-minute render.

Both passes also report `loud_gaps`, which answers to no transcript at all: the
render's own energy envelope, masked by the words that were heard, with any
hole that holds sound anyway reported as somewhere to listen. Word *durations*
are not believed when building that mask — a word claiming several seconds is
hiding a hole rather than filling one, which is exactly how a collapsed retake
escapes a diff.

`verify` covers the audio. `frames` covers the picture, and it is worth running
*before* you render — `melt` will tell you how long the exported project is for
the price of reading it:

```sh
lucid frames                                 # what the timeline will be
lucid frames cut.kdenlive                    # what melt says it would render
lucid frames final.mp4                       # what actually came out
```

`agrees` is the answer and `delta` is how far off. Two things this finds that
nothing else was looking at: a render that is no longer of this timeline, and —
on its first real run — that **auto-editor's kdenlive export is one frame
longer than your edit, and the frame is black**. That one is upstream's, it is
reported rather than corrected, and `export --render` does not have it. PLAN.md
§ `check_frames` has the measurements.

`black` and `spots` read a render that already exists. `black` runs ffmpeg's
blackdetect and only ever explains away a run as that known kdenlive tail
frame when it sits at the end *and* the frame count says so — a real dark
scene, or a dark outro card, is reported, not waved off. `spots` pulls sample
frames out as PNGs, darkest first, with the word and clip they land on when
the render still agrees with the timeline:

```sh
lucid black final.mp4                        # black stretches, explained or not
lucid spots final.mp4                        # sample frames, ranked darkest-first
```

Short loud noises between words get pulled down, not cut — a hole where a
breath was reads as an edit; a quiet breath reads as a person. `attenuate`
only acts automatically on an event short enough, in a gap narrow enough, to
trust the transcript around it; anything riskier is reported and left alone
unless confirmed:

```sh
lucid attenuate vo --plan                    # what would be attenuated, and why not the rest
lucid attenuate vo --confirm-suspect         # write it, including the edge cases
```

Before laying a clip's own audio over the VO, `speech-overlap` checks whether
the two would collide, both mapped through the timeline the same way captions
are:

```sh
lucid speech-overlap clip-id --at 106.4      # does the VO already speak there?
```

Multi-track editing is not built yet — see the milestones in [PLAN.md](PLAN.md).

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
space and what lucid does that they don't. [DOGFOOD.md](DOGFOOD.md) is what
came back from the first real video, and [ROADMAP.md](ROADMAP.md) is the build
order that fell out of it. Project status is tracked in the wiki's Open items
table, not here.
