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
   edit costs no render. [HISTORY.md](HISTORY.md) § The preview/timeline web UI.
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

   **The multi-track question "full editor" implies is answered too, decided
   2026-08-08: lucid edits your video.** Clips and cards lay over the VO from a
   cue table addressed by *word index*, so a recut recomputes shot positions
   instead of invalidating them. The cue table, the shot projection, the MLT
   writer, the `melt` render and the picture lane in the window are all built —
   `export` writes a real two-lane project **and renders it**, measuring the
   finished file rather than trusting a renderer that exits 0 on failure, and
   the timeline draws the shots that render will contain.
   [PLAN.md](PLAN.md) § The layered timeline has the build order.

   **And "the same workflow" became "the same product", decided 2026-08-08:**
   lucid copies Daydream's full feature set and warm-paper look. The whole
   parity plan — the product observed, the design system, the
   feature-by-feature map, the build order — is [DAYDREAM.md](DAYDREAM.md).

   Two things that decision did **not** change. It is a workspace, not a
   desktop app: everything that makes Daydream feel like Daydream is inside
   the window, and a native shell buys chrome at the price of a second stack
   — deferred as cheap and reversible, not rejected. And the agent panel is a
   local `claude` subprocess speaking to lucid's own MCP server, restricted to
   lucid's tools and to the one project it was opened on, so it reaches the
   timeline only through the tools the CLI calls, on your existing auth, with
   nothing uploaded. The
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
uv run lucid -C myproject restore vo 111:114             # changed your mind about one cut
uv run lucid -C myproject export cut.kdenlive            # an MLT project to finish in
uv run lucid -C myproject verify final.mp4               # did the render say what you edited?
```

Or watch it instead of reading it — the page plays the source through the
edit, so there is nothing to render first. On a project with a cue table it
also shows the shot under the playhead, read from the same place the export
will read it:

```sh
uv run lucid -C myproject web --open      # localhost; select words, preview, cut, undo
uv run lucid -C myproject view            # the same read model as JSON
uv run lucid -C myproject preview vo      # will a browser play this asset, and if not why
```

`--render` exports media instead of an NLE project, `--preset youtube|web|custom`
picks a quality bundle for it, and `undo` rolls back the last mutation while
`restore` un-cuts one specific range. A project written by an older lucid is
refused rather than guessed at; `lucid migrate` brings it forward (`--plan`
says what it would do first, and the old manifest is kept under
`cache/history/`). A timeline with a cue table or a second
clip on it is written as MLT by lucid and rendered by `melt` — auto-editor never
sees one, because it degrades a two-source render to 720x576 and exits 0.

Every MCP tool has a matching subcommand, enforced by the test suite — so an
agent drives the same operations. It runs the other way too, minus a short
allowlist of commands there is nothing for an agent to do with (`web`,
`waveform`, `preview`, `info`, `mcp`):

```sh
uv run lucid mcp                                          # serve MCP over stdio
uv run lucid -C myproject mcp                             # ...bound to one project
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
correct after cuts. Their **look is stored on the project** and the captions
are derived from it, which is what makes a restyle survive every later edit —
there is nothing coupling the two, so regenerating just re-reads the style:

```sh
lucid caption-style --preset karaoke --size 80 --highlight yellow
lucid caption-style                          # read it back, resolved
lucid caption-view                           # the cues this timeline produces
lucid captions subs.ass                      # sidecar ASS, Kdenlive loads it
lucid captions subs.ass --burn render.mp4    # or burn in with ffmpeg
```

Colours take `#rrggbb`, a name, or ASS's own `&H…`, and come back resolved in
both — ASS quotes them channel-reversed and alpha-inverted, so a value that
looks right is routinely a different colour. The window draws the same style
over the preview and on the CC lane, so what you see is what burns in.

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
reported rather than corrected, and `export --render` does not have it. HISTORY.md § `check_frames` has the measurements.

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

Clips and cards lay over the VO from the same word-indexed address space:

```sh
lucid -C myproject card templates                   # what each one takes
lucid -C myproject card new reveal-scream2 --template reveal \
  --set 'title=Scream 2' --set "note=Billy's mother" --set year=1997
lucid -C myproject card render reveal-scream2       # re-render after an edit
lucid -C myproject cue add vo 318 s1996-billy-stu   # from this word on, show this
lucid -C myproject cue add vo 503 card:reveal-scream2
lucid -C myproject shots --fps 30                   # what that projects to, in frames
lucid -C myproject export assembly.kdenlive         # both lanes, written as MLT
```

A card is an SVG under `assets/cards/` and the PNG `card:<name>` resolves to;
both are kept, so a card is re-edited rather than redrawn. `card new` fills one
of three templates — `receipt`, `reveal`, `rerate` — and `card render`
re-rasterises after a hand edit. **Cards generate at the project's own canvas**,
so a card in a 1920x816 cut is 1920x816 rather than a 16:9 still with a
quarter of its width in black bar.

Change the canvas later and the cards are the one thing that cannot follow on
their own — the aspect is baked into the SVG's viewBox, and rasterising a 16:9
document into a 9:16 frame *fits* it rather than reflowing it. So lucid records
what each card was made from and draws it again:

```sh
lucid -C myproject canvas 1080x1920                 # names the cards left behind
lucid -C myproject card reauthor --plan             # what would be redrawn
lucid -C myproject card reauthor                    # every stale card, at the canvas
```

A card whose files predate the record — drawn elsewhere and copied in — is
reported by name rather than guessed at, because nothing on disk says what
made it.

Every render reports the fonts the document names and what fontconfig will
actually draw — **a card naming a font this machine lacks renders
pixel-identically to one naming a font it has**, so `font_warnings` is the only
place that substitution is visible.

To find the b-roll to cue in the first place, describe it:

```sh
lucid -C myproject describe --plan          # what it would cost, no model loaded
lucid -C myproject describe                 # every video clip not yet described
lucid -C myproject describe cold-open       # or just one
```

Each clip is split into fixed ~10-second windows and each window gets a couple
of sentences of what is visible in it, stored against the clip in **source**
seconds — so cutting the edit can never invalidate one. It is a job rather
than a request: about three and a half seconds per window, so a project's
footage is minutes of GPU time, which is what `--plan` is for. **The windows
are never widened to save time** — one pass over a whole clip described six
frames as six people, fluently, with nothing on screen saying it was wrong.

The model runs under a separate interpreter (`LUCID_VLM`), so nothing here
puts torch in lucid's own environment. `--plan` reports whether this machine
can run it at all.

Then read them back, which **is** the search — no ranking, no embeddings, no
similarity score to tune:

```sh
lucid -C myproject describe-ls                        # the whole table
lucid -C myproject describe-ls --contains "kitchen knife"
lucid -C myproject describe-ls cold-open              # or one clip's
```

`--contains` takes terms rather than a phrase: every term has to appear
somewhere in a description, so `kitchen knife` finds "a knife on the kitchen
counter". A filtered result reports what it filtered *out of*, so a narrow
answer cannot be mistaken for an empty project, and `words` says how much text
came back — at roughly 600 windows, reading them all stops being reasonable.

A window's `src_start` is what places it. `cue add --src-start` pins where
inside the asset the shot reads, so the cut shows the moment you searched for
rather than wherever that clip's re-use cursor had got to:

```sh
lucid -C myproject cue add vo 318 cold-open --src-start 92.4
```

In-point only — the out-point stays derived from the next cue, so a later
recut still moves the shot. A pinned shot that would run past the end of its
asset is **refused** by `shots` and `export` rather than rewinding to the
clip's opening seconds, which would be plausible footage and the wrong film.

Descriptions live in the manifest, so `lucid info` reports a count and points
here rather than printing them; `lucid info --raw` still prints the manifest
verbatim.

A cue names a *word*, so a later recut recomputes every shot position rather
than invalidating it — and a cue whose word the recut removed is refused
rather than silently snapped forward. Once a project has a cue table (or a
second clip on the timeline) `export` writes the MLT itself instead of going
through auto-editor, which refuses a second source on export and quietly
renders one at 720x576.

Multi-track editing is **decided and built** — all six steps, 2026-08-08: the
cue table, the shot projection, the refusal that guards it, the MLT writer, the
`melt` render, and the picture lane in the window. `export --render` produces
the file; the timeline's V2 lane draws the shots that file will contain, and
draws them from the *planned* projection, so the window can never show a shot
`export` would refuse. [PLAN.md](PLAN.md) § The layered timeline has the design
and the build order.

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
space and what lucid does that they don't. [HISTORY.md](HISTORY.md) is the dated
record of what shipped and what the evidence said, first real video included;
the build order that fell out of it is [PLAN.md](PLAN.md) § Direction and
order, and the Daydream parity plan is [DAYDREAM.md](DAYDREAM.md). Project status is tracked in the wiki's Open items
table, not here.
