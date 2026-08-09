# lucid — planning

The living plan: architecture, standing decisions, open questions, and the
order of work. Decisions that get made move out of "Open questions" into
"Decisions", with the reasoning that settled them.

The other layers are elsewhere and this file cites rather than restates them:
competitor and dependency research in [PRIOR-ART.md](PRIOR-ART.md); the dated
record of what shipped and what the evidence said in [HISTORY.md](HISTORY.md);
the Daydream parity program in [DAYDREAM.md](DAYDREAM.md); status in the
wiki's Open items table.

## Tier 1 MVP — headless MCP server

One binary/package, `lucid`, usable two ways:

- `lucid mcp` — MCP server (stdio) that Claude Code or any MCP client connects to
- `lucid <subcommand>` — same operations as a plain CLI for scripting/debugging

### Project model

A *project* is a directory: source media, a `project.otio` timeline, a
transcript cache, and rendered outputs. Everything on disk, everything
inspectable, nothing uploaded. The OTIO file is the single source of truth
the MCP tools mutate; renders are derived from it.

The concrete layout is implemented in `src/lucid/project.py`, whose docstring
is the reference for it. `lucid.json` carries a `schema_version`; a project
written by a newer lucid is refused rather than silently misread.

### What lucid is, stated narrowly

Most of the MVP tool surface exists elsewhere already — see
[PRIOR-ART.md](PRIOR-ART.md), particularly auto-editor. Three things were
believed not to, and they were the original reason this project exists.
Everything else is plumbing to make them usable:

1. **Addressable ranges.** Every shipping transcript editor treats speech as a
   global declarative *filter* — "keep every section matching this regex."
   lucid addresses a specific range: "cut words 30–45", "keep take 2 of that
   sentence, drop take 1." Filter versus edit. This is what an agent needs to
   work iteratively.
2. **Persistent project state.** The competition is source → output per
   invocation. lucid accumulates an edit across turns, which is what makes
   refinement — and undo — possible.
3. **MCP with a real timeline underneath.** Typed tools with structured returns,
   over OTIO as the native source of truth rather than a one-way export.

Scope discipline follows from this: if a capability is available by shelling out
to an existing tool, shell out. Reimplementation is only justified where one of
the three above requires it.

**The second survey sweep weakened this thesis.** OpenChatCut (see
[PRIOR-ART.md](PRIOR-ART.md)) plausibly covers all three: word-level text-based
cuts, persistent projects with undo, and a real MCP endpoint with a
proposal/review workflow. What it does not cover is the *form factor*: it is an
Electron desktop app whose MCP endpoint requires the GUI process, with a custom
JSON timeline, cuts-only FCPXML as its whole NLE handoff, and no CLI. lucid's surviving thesis, if it
has one, is the narrower combination **headless + CLI parity + OTIO-native NLE
handoff + thin Python stack** — and whether that justifies the project is
decided by the trial gate in the milestones, not by argument.

**The third pass, 2026-08-07, did not weaken it further.** Daydream is the
product the README pitches lucid against and the most prominent competitor by
mindshare, and neither sweep had checked it — it has no GitHub repo, so a
GitHub-shaped search skipped it silently. Checked directly, it clears none of
the narrowed thesis: a closed macOS GUI app fronting a local MCP server (not
headless, no CLI), undocumented per-target XML/FCPXML export with no evidence
of a timeline IR underneath (not OTIO-native), and a product surface —
b-roll search, motion graphics, multi-format export — implying OpenChatCut's
dependency scale rather than a Python package and three subprocesses. It is
also a full desktop NLE that renders in-app, which falsified the README's
claim that it hands finishing work off the way lucid does. Evidence in
[PRIOR-ART.md](PRIOR-ART.md) § Daydream.

What it cannot do is stand in for a trial. There is no Linux build, so unlike
OpenChatCut it cannot be run on this box at all — the differentiators above are
checked against its docs and pricing page, not against the software.

### How much of the MVP is left once the box is inventoried — 2026-08-07

Measured, not argued. Everything below was verified installed and working on
this machine the same day the fourth trial criterion was added:

| MVP tool | Already covered by | Left for lucid |
|---|---|---|
| `transcribe`, `get_transcript` | openai-whisper + goodsometimes `scripts/clipcut.py` (in use; it verified the Scream reveals) | packaging. **`transcribe` built 2026-08-07** — `asr.py` already existed for `verify`; the tool was a thin wrapper over it |
| `remove_silences` | auto-editor 31.4.2 | nothing — the plan already said shell out |
| `render` | auto-editor v3 / `melt` | mapping layer, per the render decision |
| `export_otio` | `auto-editor --export kdenlive` lands natively in the only NLE here | **near zero** — this was already "lower urgency than it looks"; the Linux NLE ceiling has now collapsed it. **Superseded by the render spike — see § The handoff clause is not dead, below** |
| `add_captions` | — | word-timed ASS, genuinely absent. **Built 2026-08-07** — see HISTORY.md § Captions came out of the timeline, not the transcript |
| `cut_by_transcript` | — | **the differentiator, and the only one** |

So the surviving thesis is thinner than "headless + CLI parity + OTIO-native
handoff + thin stack." The handoff clause is dead — auto-editor already does it,
better, to Kdenlive. What is actually left is **addressable ranges over an
accumulating edit**, and nothing else.

> **The handoff clause is not dead — corrected by the render spike, 2026-08-07.**
> The row above reasons that auto-editor already exports Kdenlive, so lucid's
> handoff adds nothing. That is only true of auto-editor's *own* filter-based
> edit. The spike showed the same v3 timeline lucid builds for `render` also
> takes `--export kdenlive`, so an **arbitrary addressable edit** reaches
> Kdenlive through the mapping layer `render` needed anyway. One mapping, two
> exits, no extra work. The handoff clause of the thesis survives, and it is
> free rather than earned. Evidence in HISTORY.md § First milestones, the render spike.

**And for the workload that prompted this, there may be a cheaper shape than
either.** The essay VO is a *scripted* read: 848 known words. The edit is not
"discover the good take interactively" — it is "align the recording against a
script you already have, pick the best rendition of each sentence, assemble in
script order." That is alignment over word timings whisper already emits, not a
filter (auto-editor) and not interactive addressable editing (OpenChatCut).
Neither tool does it; it is also not obviously a whole project. Size it against
a real VO before assuming it needs lucid's architecture underneath.

### MVP tool surface

| Tool | Backed by | Notes |
|---|---|---|
| `import_media` | ffprobe | register clips, probe codecs/fps/duration |
| `transcribe` | openai-whisper subprocess | word-level timestamps, cached per clip. Written as faster-whisper; it is openai-whisper shelled out through `asr.py`, because that is the install that exists on this box and ASR is not worth importing torch into every `lucid status` for. Built 2026-08-07 — `verify` needed the module first, and the tool itself was then a thin wrapper over it |
| `attach_transcript` | cache | ingest a word-timed JSON the recording already has. Not in the original surface; added once the first real subject turned out to have been transcribed before lucid existed |
| `get_transcript` | cache | agent reads text + timings to plan cuts. Takes a `search` phrase as well as a window — locating a retake in 929 words should not mean reading 929 words |
| `cut_by_transcript` | OTIO, hand-rolled | cut/keep ranges as words or times. OTIO's edit algorithms are C++ only — no Python bindings — so this is track surgery over Track/Clip/Gap and `source_range`, not a library call. Echoes the words each index resolved to and takes `plan=True` to resolve without writing — HISTORY.md § `cut --plan` |
| `restore` | OTIO, hand-rolled | un-cut a specific word range. Not in the original surface, and not the mirror it looks like: `Edit` never stored what it removed, so the removed ranges are *derived* — `Edit.gaps` against the clip's registered duration. Bounded by those gaps, so the timeline stays a subset of the source and the subtractive invariant holds; that is what separates it from the still-parked `vo_extend`. Built 2026-08-08 — HISTORY.md § The head of the parity queue |
| `remove_silences` | auto-editor subprocess | do not reimplement; auto-editor's `--edit` language (`"(or audio:0.03 motion:0.06)"`, labels, `--margin`) is richer than thresholds-as-parameters |
| `add_captions` | ffmpeg + ASS | word-timed, styled via a small preset set; sidecar `.ass` by default, burn-in opt-in. Built 2026-08-07 — HISTORY.md § Captions came out of the timeline, not the transcript |
| `render` | OTIO → auto-editor v3 | a mapping layer, not a renderer — see the render decision below |
| `verify` | openai-whisper + difflib + ffmpeg | not in the original surface. Transcribe the finished render and diff it against the words the timeline should play — the only check that catches a retake the transcript never contained. Added after the dogfood found two of them in a shipped render. Built 2026-08-07 — HISTORY.md § `verify` checks the render, because the transcript cannot. `--windowed` (a second reading in short overlapping windows, `asr.py`) and `loud_gaps` (the energy envelope, `energy.py` — the only check that answers to no transcript) followed the same day — HISTORY.md § `verify --windowed`, and what the Scream exports actually said |
| `export_otio` | OTIO adapters | Lower urgency than it looks: auto-editor already exports six NLE formats via subprocess, and on Linux the ones that actually land are MLT (kdenlive/shotcut) — free Resolve decodes no H.264/AAC, so FCPXML only pays off for pre-transcoded footage. See PRIOR-ART.md |

Deliberately absent from MVP: motion graphics (tier 1.5, Motion Canvas),
b-roll generation, any GUI.

### Stack decision

**Python.** OpenTimelineIO and faster-whisper are both Python, and OTIO is the
load-bearing one — it is the source of truth every tool mutates, and rewriting
or FFI-wrapping it is the cost that would dominate any other choice. The MCP SDK
is solid. ffmpeg and auto-editor are subprocesses either way — auto-editor is
Nim, so it was never a Python dependency to weigh.

This rests on OTIO alone, which is narrower than it looks. Revisit if
performance actually hurts, or if OTIO stops being the source of truth.

**And it now rests on OTIO literally alone.** auto-editor turned out to be Nim
(PRIOR-ART.md), and ASR turned out to be a subprocess too once it was built —
so of the three Python dependencies the paragraph above reasons from, one is
left. The conclusion survives because it was always the load-bearing one, but
"the stack is Python" is no longer a reason for anything.

## Decisions

- **Timeline addressing: both transcript ranges and clip/segment IDs.**
  Transcript-only is simpler, but it has no way to name footage with no
  speech — b-roll, music beds, screen recordings with no narration — and
  those are ordinary material, not edge cases. OTIO already gives every
  segment an identity, so IDs are nearly free now and expensive later:
  retrofitting them means changing the signature of every tool that was
  shaped around transcript ranges. Word ranges stay the ergonomic path for
  dialogue; IDs are the fallback that always works.
- **Python 3.13, not 3.14.** OpenTimelineIO is the sole holdout: 0.18.1 ships
  cp39–cp313 wheels and no cp314. Every other dependency already covers 3.14
  (ctranslate2 4.8.1 through cp314 including free-threaded, onnxruntime 1.28.0
  through cp314, PyAV and tokenizers via abi3 wheels). Pinned in
  `pyproject.toml`; `uv` fetches 3.13. Wheel matrix in
  [PRIOR-ART.md](PRIOR-ART.md). Revisit when OTIO publishes cp314 — and check
  the matrix rather than assuming, since this pin was stale against its own
  revisit condition once already.
- **`render` is a mapping layer, not a renderer.** There is no first-party
  OTIO→ffmpeg renderer in the ecosystem, and nobody has demonstrated one inside
  an agent loop. Rather than write one, map OTIO onto auto-editor's `v3`
  timeline JSON and shell out to `auto-editor timeline.v3 -o out.mp4`. v3 is a
  flattened OTIO track under different field names, so the mapping is small, and
  it buys auto-editor's renderer and its `--preview` dry run for free.
  auto-editor is public domain, so porting its render logic later is
  unencumbered if the mapping leaks. Hand-rolled OTIO→ffmpeg stays the fallback.
  **Verified 2026-08-07** (milestone 3), with one addition the decision did not
  anticipate: the same mapping also exports to Kdenlive, so it is the NLE
  handoff too. Its header fields are templated out of `auto-editor --edit none`
  rather than reconstructed from ffprobe — `layout` and friends are not worth
  guessing, and templating costs a probe instead of an audio analysis.
- **Captions are word-timed ASS.** SRT + ffmpeg `force_style` structurally
  cannot do word-level highlighting, which is the thing burned-in captions are
  actually for. ASS is miserable to generate by hand; generate it from the
  cached word timings instead, which is where they already live. kinocut reached
  the same conclusion independently.
- **Snapshot the timeline on every mutation.** `project.otio` is a single source
  of truth being mutated in place by a non-deterministic agent, so undo is not a
  tier-2 feature. Copy to `cache/history/<n>.otio` before each write. Ten lines
  now, a schema migration later.

## Open questions

- **Does OpenChatCut make lucid redundant? Answered 2026-08-07: no.** The gate
  required all four criteria — runs acceptably on Linux **and** MCP handles
  iterative addressable edits on a real recording **and** Electron-as-MCP-host
  is tolerable in an agent-CLI workflow **and** the output reaches the
  finishing NLE. Criterion 4 failed outright (FCPXML-only handoff) and 2 is
  cloud-locked (AssemblyAI-only ASR); per-criterion evidence in milestone 2.
  lucid continues with the narrowed thesis above.
- **Fourth trial criterion, added 2026-08-07: does the edit get *out*?** The
  first three criteria were written assuming finishing happened elsewhere. It
  can't. Premiere does not run on Linux and the goodsometimes back catalog's
  last `.prproj` is 2025-10-30 — **the only NLE on this box is Kdenlive, and
  Kdenlive cannot import FCPXML.** OpenChatCut's sole handoff is FCPXML, so it
  is all-or-nothing: either the video is finished inside a v0.1.9 Electron app
  using Remotion, or nothing leaves. For a video essay that needs quote cards,
  chapter titles and lower-thirds, that is a real bet and it belongs in the gate.
  Contrast measured the same day: `auto-editor --export kdenlive` writes a native
  MLT project that Kdenlive opens and `melt` renders. See goodsometimes
  `pipeline.md` § The NLE changed for the verified path.
- **Word-timestamp accuracy.** whisper word timings drift on long recordings.
  Forced alignment (WhisperX-style) is the obvious fix, but probably the wrong
  one: cut points want to land in the *silence between* words, so snapping the
  cut to the nearest audio-energy minimum within a window is cheaper and more
  robust than better ASR. Evidence that alignment alone is insufficient:
  rescript, a shipping transcript editor, added drag-to-adjust word edges.
  Decide after measuring on real footage.

  **First measurement, 2026-08-07 — cheaper than feared on this material.** At
  the six retake boundaries in the Scream VO the silence between the abandoned
  take and the restart ran 0.34s–2.48s, so a flat `pad` of 0.1s put every cut
  well inside the gap, and re-transcribing the render confirmed no word was
  clipped at either edge. That is *not* a general answer: restart pauses are
  the easiest case there is, and a cut mid-sentence has no such margin. Energy
  minimum snapping stays the plan for tight cuts; it is just not urgent.

  **Narrowed once that video was rendered: this covers drift, not infidelity.**
  It sampled the retakes lucid knew about. Two it did not know about were
  missing from the transcript altogether — whisper had folded them into the
  duration of the following word — and no amount of edge-snapping finds a take
  the transcript never recorded. HISTORY.md § 2.
- **Variable frame rate footage.** Phone/screen recordings are often VFR and
  break naive cut math. Current lean: do *not* transcode on import — it is slow
  and lossy, and cut-and-concat operates in the time domain where VFR is mostly
  fine. Probe it, record `vfr: true` in the manifest, normalize only when
  exporting to an NLE, where frame-exactness actually matters. Verify against
  real screen recordings.
- **Preview delivery in tier 1.** The consumer here is an agent, and an agent
  cannot watch an MP4. Leading option: a contact sheet of frames at ±0.5s around
  each cut boundary, which a vision model can actually check. Cheap to render;
  video-use independently ships decision-point composites (filmstrip +
  waveform), which validates the idea and removes its uniqueness. An MP4 for
  the human and a web preview (tier 2, built — HISTORY.md § The preview/timeline web UI)
  are separate questions — don't conflate them, and building the second did
  not answer this one: the page is for a person, and an agent still cannot
  watch it.
- **Does the OTIO→v3 mapping hold? Answered 2026-08-08: yes, wider than lucid
  uses.** Single-track cut-and-concat maps in both directions on real material
  (milestones 3–5), and v3 turns out to express the three things this bullet
  used to list as unverified: multi-layer composites (`v`/`a` are lists of
  tracks), speed (`effects: ["speed:2.0"]`) and transitions (a top-level
  `transitions` key). So none of them can force an architecture change at the
  v3 boundary. `timeline.py` still cannot express them — one track, A/V linked,
  no gaps — but that is now lucid's choice rather than the format's limit, and
  the cost of changing it is measured in HISTORY.md § The multi-track costing spike. What
  v3 has no field for is per-entry gain.
- **Laying clips and graphics over the VO is unmodelled, and that is the next
  real decision.** The Scream video needs five film clips and nine cards on top
  of the trimmed VO. Right now that is Kdenlive's job and lucid's output is an
  audio bed to build on, which is a defensible split. But it is the difference
  between "lucid trims your VO" and "lucid edits your video", and multi-track is
  the whole cost. Decide against the *next* video, not this one — this one has a
  working path.

  **The decision is cheaper now.** `goodsometimes/scripts/assemble_scream.py`
  shipped that video: a cue table of `(source_word_index, asset)` mapped through
  the surviving ranges. It is a worked reference for what lucid would absorb,
  including the MLT details that cost the most time. HISTORY.md § 3.

  **And it has a concrete test case, whose prerequisite now exists.** Beat 3's
  Billy/Stu line wants VO ducked under a clip's own audio, which breaks the
  assumption underneath the split above — that clips are silent and lucid owns
  the only audio track. `speech_overlap` is the overlap test that call needed
  either way. What is left is not the model — HISTORY.md § The multi-track costing spike
  prices that, and it is cheap — but getting a multi-*source* timeline out of
  auto-editor at all. Sequence: § Direction and order.

  **Decided 2026-08-08: lucid edits your video.** This bullet is answered and
  is kept for the reasoning, not as an open question. The multi-source timeline
  does not come out of auto-editor at all — it comes out of `melt`, which has
  no source-count gate and was already this repo's stated multi-track renderer
  (HISTORY.md § 4). Design, build order and what stays blocked:
  § The layered timeline — the gate is decided, and `melt` renders it.

## Non-goals (write them down so they stay dead)

- Cloud anything. No accounts, no metering, no upload.
- Competing with Resolve/Premiere on finishing. Export to them instead.
- A plugin system before there are two users.

## Direction and order

Sequence and rationale — formerly ROADMAP.md, folded in 2026-08-08. Status
lives in the wiki's Open items table; the account of what shipped is
[HISTORY.md](HISTORY.md). **Cite items by name, never by number**: numbers
renumber on every ship, and four things once cited "item 1" meaning four
different items. Anything built gets a named HISTORY.md section; cite that.

**Ordering answers to measured defects, not to competitors** — with one
deliberate exception on the record: Daydream parity, a goal by owner's
decision (Tyler, 2026-08-08) rather than by measurement. What survives of the
rule is the order *inside* the queue — it still ranks by what the layered
timeline unblocks — and the constraints that keep the window honest bind
every parity item.

### The property everything below defends

**Word indices address the source and never renumber.** When two late retakes
shifted every downstream cut by 4.4 s, the whole 37-shot plan recomputed from
two `lucid cut` commands, because no cue was written in timeline seconds
(HISTORY.md § The core thesis held, and it paid off late). The music bed
proved the converse: cues carrying explicit lengths tuned to the old runtime
were invalidated wholesale by a ~12 s append — **the property is about every
cue in a project, not just the shot plan.** Any item below that would trade
it away is wrong regardless of what it buys. The corollaries are conventions
in [CLAUDE.md](CLAUDE.md): trust word *order*, never word *durations*;
survival is an *overlap* test; anything emitting times for playback maps
through `Edit.timeline_span`.

### Now — nothing in flight

The tier-3 workspace shipped 2026-08-08 (§ Tier 3 is the goal). Of its two
remainders one is closed — the agent's MCP server binds to its `-C` project
as of 2026-08-09 (HISTORY.md § Binding the agent's MCP server to its
project) — leaving the video preview proxy, whose showing-the-shot half
shipped the same day (HISTORY.md § The preview picture layer), so what is
open there is the transcode. The verified
bar for any UI item: run against the real Scream VO, in a real browser (wiki
`tooling.md` § Headless browser) — and for anything showing *video*, not by
screenshot, for the reason that page now records.

The look/feel pass — the parity queue's head — shipped 2026-08-08 too
(HISTORY.md § The look pass), and the six small items it left behind shipped
the same day: model label, per-turn thumbs, `@`-mentions, inline pause
markers, `restore`, export presets. HISTORY.md § The head of the parity queue.

**Caption styling, the next ranked item, shipped 2026-08-09** — the style is
project state and the captions are derived from it, so a restyle survives
every later edit (HISTORY.md § Caption styling). Two measurements out of it
carry past captions. ASS `\k` is a left-to-right *fill*, not a per-word step,
and the preview was corrected to match the file rather than the other way
round. And **`DejaVu Sans` is not installed on this box** — `fc-match`
answers `Noto Sans`, so every caption lucid has burned here was drawn in a
substitute, silently, and the preset comment claiming otherwise was wrong.
The substitution is now reported on every call; **whether lucid's default
should name a font this machine actually has is an open call**, deliberately
not taken, because changing the table would silently restyle every existing
project.

The next ranked item is motion graphics + templates, and **its costed design
note is written** — § Motion graphics and templates, 2026-08-09. Its finding
is that the item needs no new timeline mechanism: the Scream cards already are
motion graphics minus the motion, so what is missing is a generator for the
asset. What the note does cost, and where it stops the build, is *animation* —
an animated card carries a length, a shot's length is derived from the edit,
and a cue carrying a length is the failure § The property everything below
defends exists to prevent.

**Step 1 of that build shipped 2026-08-09** — the renderer, `lucid card
render`, and the font report (HISTORY.md § The card renderer). Its second
measurement carries forward into step 3: `-size` *fits*, so a card authored at
a different aspect from its film pillarboxes and no resize could ever close
it — authoring at the canvas size is the only fix, which is what step 3 does.
Its fourth is the one that carries past this item: **a card naming a font this
box lacks renders pixel-identically to one naming a font it has, at exit 0**,
so the open call on lucid's default font is no longer only about captions.

One named thing did not ship and is blocked rather than unfinished: a
**`tiktok-reels` preset**, because 9:16 is only producible here as a pillarbox
of the 16:9 frame and a real reframe is § Next's own deferred aspect-swap
item. Shipping a platform's name over a quiet letterbox is the
correct-pixels-wrong-video failure the trap below exists to prevent, so it
waits for the item that does it properly.

### Done — the layered timeline

The gate was decided — **lucid edits your video** — and all six steps shipped
2026-08-08. Design, evidence, and what stays blocked: § The layered timeline —
the gate is decided, and `melt` renders it; the account of each step, and of
the three constraints the ordering owned, is HISTORY.md.

The outside date is real: the **October Horror Bracket, part 1 due Oct 1**,
format decisions wanted mid-September. The Billy/Stu duck stays blocked by
the recording, not the model — 74–85% overlap, no seam to duck into
(HISTORY.md § `speech_overlap`) — and the layered timeline ships without it.

### Next — the Daydream parity queue

The whole parity plan — observed product, design system, per-feature notes,
non-imports — is [DAYDREAM.md](DAYDREAM.md). Ranking, governed by the layered
timeline being the enabler and the look pass being gated on nothing:

1. **The look/feel pass** — shipped 2026-08-08 (HISTORY.md § The look pass),
   and so are the six small items that were to ride it and didn't
   (HISTORY.md § The head of the parity queue). This rung is done.
2. **Caption styling** — shipped 2026-08-09 (HISTORY.md § Caption styling).
   What it left is per-word *animation*, which shares a construction question
   with a single-word highlight and is an export cost, not a styling one.
   Then 3. **motion graphics + templates**, then
4. **b-roll by description** — both get costed design notes before
   any build; b-roll must not copy Daydream blind, whose hour-metering
   implies cloud inference where lucid is local-only.
5. **The long tail** — aspect swap, import roles + assets pane,
   multi-project picker, HTTP MCP transport, properties pane. **Aspect swap
   is no longer only a parity nicety** — it is what a `tiktok-reels` export
   preset is waiting on, and the preset is the first thing anyone reaching
   for a vertical export will ask for. It still costs what it always did:
   the project model, both render paths, and the preview letterbox.

**What step 6 left is closed, and it was two items rather than one.** The
picture lane is previewed as of 2026-08-09: clicking a shot shows it, from the
position inside its asset `mlt.plan_picture` assigned, so a clip used three
times previews from three different places (HISTORY.md § The preview picture
layer). What that needed was a second element in `#viewer`, not a transcode —
every piece of the Scream footage is already `avc1`/`yuv420p`.

The wiki row's other half, **a playable proxy for footage a browser cannot
decode**, is still open and is now the smaller thing: an unplayable asset
explains itself in the viewer (`hev1`, 10-bit, an unopenable container, an
undecodable audio track — each named), it just does not play. Building the
transcode wants a design note first for the same reason everything else here
does: it is a *job*, not a request — `cold-open` is 730s — so it needs the
`/api/render` background pattern, a cache key, and an eviction rule.

### Parked — deliberately, with the reasoning

- **`vo_extend`, the mirror of `cut_by_time`** — unparked by the gate
  decision, not yet queued: it is the one item touching `Edit`'s subtractive
  invariant, it is the same operation as inserting a hold to unblock
  Billy/Stu without a re-record, and the case for it is editorial — decide on
  a watch, after the six steps land. Constraints it inherits: HISTORY.md
  HISTORY.md § `cut_by_time`, at *the `vo_extend` mirror*.
- **Energy-snapping cut edges** — measured non-urgent on Scream-like
  material; the failures that looked like drift were transcript infidelity,
  addressed instead by the near-duplicate and suspect-duration checks
  (HISTORY.md § 2, revising the Word-timestamp accuracy finding). Revisit if
  a video demands mid-sentence cuts.
- **Everything one video couldn't establish** — one speaker, audio-only, no
  camera footage, no VFR, no speed changes (HISTORY.md § What this does not
  establish). The October bracket is where several get their first real test;
  expect this section to reshuffle then.

**What separates tier 2 from tier 3 is finishing, not mutation** — the
definition stands, and lucid crossed it 2026-08-08: Export renders a
watermark-free MP4 in the window, with the render checks reported on the
completion card. Non-goals stay dead in § Non-goals.

## Tier 3 is the goal — the Daydream-shaped workspace — 2026-08-08

**The decision: lucid grows a workspace, not a shell.** HISTORY.md § The preview/timeline
web UI shipped and was used, and the verdict on use was that it is a correct
*instrument* and a poor *editor*. the roadmap had already left tier 3
"revisitable — a question behind the web UI"; this is the answer, taken
deliberately rather than arrived at by drift.

What reopened it was not the handoff argument the closing note anticipated. It
was simpler: the page is unpleasant to work in, and every reason it is
unpleasant is a reason inside the window.

### What using it actually exposed

Measured against the real Scream VO at 67 segments, not against a mock:

* **The picture is not the centre.** `#viewer` is capped at 34vh above two
  strips, and on an audio-only clip it is `display:none` outright — so the
  largest thing on screen is a transcript and the smallest is the thing being
  edited.
* **The transcript is one 929-word paragraph.** No breaks, no timestamps, no
  scroll to the playing word. It is addressable and unreadable at once.
* **67 segments in a 34px strip is a barcode.** No ruler, no zoom, no track
  header, no clip name, no waveform. The strip proves the edit exists; it does
  not let you work on it.
* **The inspector is empty almost always.** "Nothing selected · Nothing run
  yet" is the resting state of 380px of a 1440px window.
* **There is no agent in the window at all** — which is the category
  difference, not a craft one. lucid's agent lives in another application.

### The line that moves, and the one that does not

§ Direction and order's line — "what separates tier 2 from tier 3 is finishing, not mutation" —
stays true and stays the definition. **What changes is that lucid now intends
to cross it**, in this order: the workspace first, finishing second. A window
good enough to edit in is worth building before the render path can finish a
video inside it, because the window is what makes the render path's gaps
visible.

**Non-goals do not move.** No cloud, no accounts, no metering, no upload. The
agent panel below is what makes that non-trivial to keep, and it is why the
panel is shaped the way it is.

### The agent panel, and why it does not become a fourth implementation

CLAUDE.md's convention — *the web UI draws and it plays, it never decides* —
survives this intact, and it constrains the design rather than yielding to it.

The panel hosts a **local `claude` subprocess** (2.1.226 on this box) run as
`claude -p --input-format stream-json --output-format stream-json
--mcp-config`, with lucid's own `lucid mcp` attached. So:

* the agent reaches the timeline **only** through the MCP tools, which are the
  same `ops` functions the CLI and the page's own buttons call. There is no
  privileged path, and the panel adds no new one — it adds a *client of the
  existing one*;
* it rides Claude Code's existing auth. No API key, no key storage, no request
  leaving for an endpoint lucid chose. § Non-goals holds;
* `stream-json` is already the progress list the panel needs to draw. Daydream
  renders "Reading transcript → Editing transcript → Done!"; that is a tool-use
  stream with a stylesheet on it.

The page still never computes an edit. It now hosts something that asks for
one, and draws the answer — which is the same relationship it already has to
its own Preview button.

### The trap this section exists to write down

**Do not draw tracks the export cannot produce.** The UI can grow a V2 lane and
a ducked A2 in an afternoon; `export` cannot follow it. HISTORY.md § The multi-track
costing spike measured the wall: auto-editor 31.x gates multi-*source*
timelines behind a paid key and **degrades the render to 720x576 with a warning
and exit 0** rather than failing. A workspace that draws a b-roll lane over
that produces a beautiful window and a silently wrong file.

So the timeline is built as a real NLE timeline **over the single-track `Edit`
that exists** — ruler, zoom, lanes, named clip blocks, waveform — and widens
when the September decision gate widens the model, not before. Lanes drawn
today are *projections of one track*, and the code says so where it draws
them.

### Not a desktop app, and the reasoning is on file

Tier 3 named "a full desktop editor". What is being built is the editor, not
the packaging, and those were never the same decision.

Everything that makes Daydream feel like Daydream is inside the window. The
native shell buys a title bar and costs a second stack — which § Non-goals
already refuses — and this repo has *measured* the specific friction: the
OpenChatCut trial (HISTORY.md § First milestones) found an Electron GUI that must be
running before its MCP tools register, a confirmation card per tool per
session, and a transport that goes stale after an import. Adopting that shape
to gain chrome would be paying the trial's own findings forward.

If the finished page still reads as a browser tab, wrapping *that same page* in
a Chrome `--app` window or Tauri is a day's work against a week's. The shell is
deferred because it is cheap and reversible, not because it is unwanted.

**And the asymmetry that makes any of this worth doing: Daydream has no Linux
build.** PRIOR-ART.md § Daydream — no Windows or Linux build on the download
page, docs or FAQ. On this box the competitor cannot run at all.

### The design — panes, endpoints, and what each one is not allowed to do

Written before building, because three of the decisions below are expensive to
reverse once the page exists.

#### Layout

One CSS grid, three columns over a full-width timeline. No framework, no build
step — that constraint is inherited from § Non-goals and is not revisited.

```
┌──────────────────────────────────────────────────────────┐
│ lucid / <project>                    [Export] [Undo (n)] │  top bar
├────────────┬─────────────────────────┬───────────────────┤
│ transcript │        preview          │      agent        │
│  ~26rem    │        flex: 1          │      ~24rem       │
│            │   transport under it    │  feed + composer  │
├────────────┴─────────────────────────┴───────────────────┤
│ ruler · zoom                                             │  timeline
│ V1 ▓▓▓▓│▓▓▓▓▓▓│▓▓▓▓▓▓▓▓                                  │  ~22vh
│ A1 ╫╫╫╫│╫╫╫╫╫╫│╫╫╫╫╫╫╫╫                                  │
│ CC ──────────────────────────                            │
└──────────────────────────────────────────────────────────┘
```

The one thing this fixes that is not cosmetic: **the picture becomes the
largest element on screen**, and an audio-only clip gets a drawn level display
rather than `display:none`. The current page's worst behaviour is that on the
only real project in the repo it renders no viewer at all.

#### Files, and why they split

`app.js` is 744 lines today and this roughly triples it. ES modules, served
flat out of `/static/` — which the existing static handler already permits
(flat names, `.js` allowed) and which the existing CSP (`default-src 'self'`)
already satisfies. No bundler is introduced.

| module | holds |
|---|---|
| `app.js` | entry, the one `view` state, wiring |
| `api.js` | fetch + SSE, the JSON content-type header |
| `transcript.js` | the document pane and selection |
| `timeline.js` | ruler, lanes, clip blocks, waveform canvas, zoom |
| `player.js` | the seam-jumping playback loop, transport |
| `agent.js` | the feed, the composer, the tool-progress list |
| `dom.js` | `el`/`$`, time formatting |

`player.js` inherits the existing seam loop unchanged. It is the one piece of
the current page that is genuinely good and it is not being rewritten for
tidiness — it is the thing that makes seeing an edit cost no render.

#### Read-model additions

Two, and both are ops rather than server-side computation, for the reason
`timeline_view` already is one: a view that computed its own answers would be
a second implementation.

**`paragraph`, a new field on each word in `timeline_view`.** The transcript is
one 929-word block today because nothing tells the page where to break. The
rule is deliberately **word-order-driven, not duration-driven**: break after a
sentence-ending word once the paragraph holds ≥40 words. A silence of ≥0.75 s
after a sentence end may break earlier, once the paragraph holds ≥15 words —
but that arm is opportunistic and the word count is the guarantee. This is the
CLAUDE.md rule about durations applied to a cosmetic feature: whisper inflates
a duration to swallow a retake, which can only ever *suppress* a gap break,
never invent one. A suppressed break is an ugly paragraph; an invented one
would be a lie about where a sentence ended.

**`ops.waveform(path, clip_id)` — CLI `lucid waveform`, no MCP tool.** RMS per
20 ms frame from `energy.decode` + `energy.envelope`, normalised to bytes,
cached under a new `cache/waveform/` keyed by the media's size and mtime. The
cost is why it is cached and not computed per request: `envelope` is a Python
loop, and 385 s at 8 kHz is ~3 M multiply-adds — roughly a second here, and
linear, so an hour of footage is ~15 s. It is deliberately **not** an MCP
tool: the convention binds MCP tools to have CLI subcommands, not the reverse,
and 19 000 floats is a picture, not something an agent should reason over —
`loud_gaps` and `unaccounted_sound` already answer the numeric questions.

The waveform is drawn **through the edit**: each timeline segment maps to a
source range, and the lane draws that slice of the source envelope. So no
timeline-space envelope is ever computed, and a cut needs no recompute.

#### The timeline

* **Zoom is pixels-per-second**, one number, fit-to-window by default. The
  current strip has no zoom, which is why 67 segments render as a barcode.
* **Track headers are a sticky left column**; lanes scroll horizontally
  together in one container.
* **Clip blocks are DOM, the waveform is `<canvas>`.** Blocks need hover, title
  and hit-testing and there are tens of them; the envelope is thousands of
  points and needs none of that. 67 blocks does not warrant virtualisation —
  the threshold to revisit is ~2000.
* **Lanes are projections of one `Edit`.** V1 only when the clip
  `has_video`, A1 always, CC only when captions exist. **No lane that `export`
  cannot produce** — § The trap this section exists to write down, above.
  Written when that also ruled out V2; V2 became producible at step 5 and was
  drawn at step 6, which is the rule working rather than an exception to it.
  There is still no A2.

#### The agent panel, in mechanism

```
POST /api/agent      {prompt}     → 202, work happens on the stream
POST /api/agent/stop              → interrupt the running turn
GET  /api/events                  → SSE: agent deltas, tool calls, project-changed
```

One subprocess per server, spawned lazily:

Flags below verified against the installed `claude` 2.1.226 rather than
recalled — `--allowedTools`, `--disallowedTools` and `--strict-mcp-config` all
exist, and `--permission-mode` takes `manual` among others. There is **no
`--cwd` flag**; the working directory is set on the spawn.

```
claude -p --verbose --input-format stream-json --output-format stream-json
       --mcp-config <generated: one server, lucid -C <project> mcp>
       --strict-mcp-config
       --tools ''
       --allowedTools 'mcp__lucid__*'
       --disallowedTools Bash Write Edit WebFetch WebSearch
       --permission-mode manual
# cwd=<project root>, set on the Popen, not by a flag
```

`--verbose` is not optional either, and not for logging: 2.1.226 refuses
`--print --output-format=stream-json` without it — errors and **exits 0**
with nothing on stdout, which the SSE-consuming page has no way to see as
failure (a submitted prompt just sits "busy" forever). Verified by direct
reproduction, not recalled.

**The tool allowlist is the security boundary, and it is the whole design —
but `--allowedTools`/`--disallowedTools`/`--permission-mode manual` alone do
not enforce it against built-in tools.** Verified against 2.1.226: those three
flags govern *permission prompts*; a built-in tool named in neither list (the
reproduction used `Glob`) simply never triggers one and runs. `--tools ''`
is what actually disables the built-in set, leaving only the MCP tools
`--strict-mcp-config` exposes — that is the flag that makes "the agent gets
lucid's MCP tools and nothing else" true, not the allow/disallow lists on
their own. Today a bypass of the `Host`/content-type guards costs you a
mangled edit that `Undo` reverses. An agent panel without this bound would
make the same bypass cost arbitrary code execution as the user, because
Claude Code has Bash. So the agent gets lucid's MCP tools **and nothing
else**, which bounds a fully hijacked agent to operations the undo stack
already reverses. `--permission-mode manual` remains the belt to the
allowlist's braces for the MCP tools themselves: there is no TTY on a
subprocess, so an MCP tool call outside `--allowedTools` cannot be approved
and fails closed rather than running.

**This was chosen against the two looser options, not defaulted into**
(2026-08-08). Read-only project file access via `--add-dir` was rejected
because it widens what an injected transcript can pull into a tool result for
no capability lucid's own tools do not already expose; Bash was rejected
because it converts a guard bypass into arbitrary code execution, which is the
single thing the allowlist exists to prevent. If a future need argues for
widening this, it is a decision that gets written here, not a flag someone
adds to make a debugging session easier.

**`--strict-mcp-config` is not optional, and it is the trap worth writing
down.** Without it the spawned agent inherits *the user's own* MCP servers —
on this box that is Gmail, Google Drive and Calendar. A video editor's agent
panel silently holding a mail client is exactly the kind of privilege nobody
audits later. The flag confines it to the one generated config.

The subprocess runs with the project as its working directory and its MCP
server is spawned as `lucid -C <project> mcp` (`-C` is a global flag and
must precede the subcommand — `lucid mcp -C` does not parse), **and as of
2026-08-09 that binding is real.** It was not for a day: `_cmd_mcp` ignored
`-C` entirely while every tool took its own explicit `path`, so confinement
to lucid's ops held and confinement to *this project's* ops did not.
`serve(root=)` now pins the server, and each tool's `path` resolves against
that root or is refused. The account, and the boundary the fix deliberately
stops at — `path` is confined because it is the project *selector*, while
`import_media`'s `source` and `export`'s `output` are not — is HISTORY.md
§ Binding the agent's MCP server to its project.

**Prompt injection is in scope and is bounded the same way.** The transcript is
attacker-influenced content whenever the footage is not yours, and the agent
reads it. An injected instruction cannot reach outside the allowlist; that is
the property the allowlist exists to buy, and it is the reason not to relax it
for convenience later.

**View invalidation is uniform.** The server tracks a revision — `project.otio`
mtime plus undo depth — and the SSE stream emits `project-changed` when it
moves. The page reloads `/api/view` on that event, which covers an agent edit,
the page's own edit, and a `lucid cut` run in a terminal beside it, without
three code paths.

#### Where the cut controls go

The right pane is the agent now, so the inspector cannot stay there. Selecting
words raises a **floating toolbar anchored to the selection** — Preview, Cut,
Keep only, and a small popover for pad and the suspect-boundary confirmation.

The op's *result* renders into the agent feed as a system entry. That is the
substantive choice: **one feed for everything that happened to the edit**,
whether a person or the agent caused it, in order. The alternative — a separate
result panel — reproduces the current page's emptiest region and splits the
history of an editing session across two places.

The echo rules do not move. A word range still shows the three words either
side (CLAUDE.md), and Preview is still `plan=True` on the same op rather than
its own endpoint.

#### Finishing — the render happens in the window

**Decided 2026-08-08: Export renders a watermark-free MP4 in the window**, and
the MLT/Kdenlive handoff stays as an additional way out rather than the only
one. This is the sentence that actually crosses the tier line. § Direction and order's
"what separates tier 2 from tier 3 is finishing, not mutation" has been the
definition since the tiers were written; this is lucid choosing to cross it,
with the definition left standing so the crossing stays legible.

`ops.export` already does both — `export_format=None` renders, `"kdenlive"`
writes MLT — so no new render path is written. What is new is that a render is
long enough that a blocking HTTP request is the wrong shape:

```
POST /api/render   {preset}   → 202 {job_id}
GET  /api/events              → job progress and completion on the same stream
POST /api/render/stop         → cancel; the partial output is deleted, not left
```

One job at a time per server, output under `renders/`. Three things the job
model has to get right, all of them already-measured traps rather than
guesses:

* **auto-editor's exit code does not mean success** (HISTORY.md § The multi-track costing
  spike). The job reads the output's actual dimensions before reporting
  success, and says what it got rather than that it finished.
* **A finished render is checkable, and the checks exist.** `verify`,
  `check_frames`, `check_black` and `spot_frames` already answer whether the
  render says what the timeline says. The window is the first place those have
  somewhere useful to appear — the completion card is where they belong, not a
  separate command a person has to remember.
* **The proxy must not be what gets rendered.** The preview proxy below and
  the attenuated copy both resolve through `media.media_path()`; export reads
  through the same function. That ordering is load-bearing and gets a test,
  because the failure is a finished, delivered file at preview quality.

#### What this design still does not answer

* **Multi-project.** `lucid web` serves one project per process. Daydream's
  breadcrumb implies a project list; nothing here builds one.
* **Video, and the codec wall under it.** *Answered in part, 2026-08-09 — the
  picture is verified against real footage now (HISTORY.md § The preview
  picture layer), and the wall turned out not to stand in front of this
  project.* All ten Scream clips are H.264 High / `avc1` / `yuv420p`, so the
  browser plays them from `/api/asset/` byte-for-byte and the letterbox is
  `object-fit: contain`. What survives of this bullet is everything below it:
  the wall is real for *other* footage, and lucid now names which wall it hit
  rather than showing black.

  The wall found while planning, and it is a *container and profile* problem
  rather than a Linux one. ffprobe on a representative NAS source reports
  `codec_name=hevc`, `codec_tag_string=hev1`, `profile=Main 10`,
  `pix_fmt=yuv420p10le` — which is precisely the combination wiki `home.md`
  already records as un-playable in a browser (H.264, or H.265 tagged `hvc1`;
  `hev1` does not play). That rule was written for the Vault browser and holds
  here for the same reason.

  So `/api/media/` streaming the source byte-for-byte — what makes the current
  page's "no render" claim true for audio — **does not carry over to picture**.
  The preview would show nothing and blame the file.

  This does not break the design; it adds a step the design must not skip. The
  fix is a cached **proxy transcode** into a new `cache/proxy/`, resolved the
  way `media.media_path()` already prefers an attenuated copy. Note before
  building it that homebase already runs an encoder service for exactly this
  conversion (wiki `homebase.md`, port 8765) — worth checking whether lucid
  should call it rather than grow its own ffmpeg path. Two consequences to
  keep honest either way: seeing a *video* edit costs one proxy pass, not
  zero, and the proxy must never reach `export`, which reads through
  `media_path()` — so the resolution order is load-bearing and gets a test.

## The layered timeline — the gate is decided, and `melt` renders it — 2026-08-08

The decision gate (§ Direction and order) asked whether lucid trims your VO or
edits your video. **It edits your video.** This section is the decision, the
measurement that forced it, and the build order — written to be picked up cold
in a later session.

### The gate was mis-framed, and the correction is one measurement

HISTORY.md § The multi-track costing spike priced the model as cheap and the export as the
wall: auto-editor 31.x gates any timeline naming two distinct `src` files down
to 720x576 with **exit 0**. Every number in that section is correct and stands.

What it did not do is connect back to HISTORY.md § 4, which had
already concluded — from the video that shipped — that **rendering a multi-track
project needs `melt`, not auto-editor**. So the gate's "four options, none free"
framing quietly assumed auto-editor was the only renderer, when this repo's own
dogfood notes had already said it was the wrong one.

Measured today, closing that loop, against the real assembly rather than a
fixture:

```sh
melt "…/Every Scream Sequel Falls Apart At The REVEAL - assembly v3.kdenlive" \
     in=0 out=90 -consumer avformat:spike.mp4 vcodec=libx264 acodec=aac
```

| | result |
|---|---|
| distinct source files in that project | **23** — `VO.wav`, 9 film clips, 13 cards |
| structure | 4 tractors, 5 playlists |
| render | **1920x1080**, 91 frames, h264 + aac stereo |
| licence gate encountered | **none** |

`melt` has no source-count gate, is already installed (inside the Kdenlive
flatpak, `filesystems=host` already granted), and is already resolved by
`picture.melt_command()`. Two of the spike's own choices were the documented
traps being obeyed rather than luck: it passed `WAYLAND_DISPLAY`, and it passed
**the codec and nothing else** on the consumer. Both are HISTORY.md § 4; do not
re-derive them, and read `goodsometimes/scripts/render.py` before writing the
render call — it handles all three traps plus a `systemd-run` memory cap.

**So the wall is auto-editor's, not this box's.** Options 1 (buy a key) and 2
(fork the Nim source, re-patch every release, and assert un-gatedness forever by
probing render *resolution* because the exit code lies) both existed to buy back
something `melt` does for free. They are dropped.

### What this does to "lucid never writes MLT"

That rule (HISTORY.md § `cut_by_time`, at *the `vo_extend` mirror*) is narrower than its
summary. It says lucid **regenerates** a timeline through `auto-editor --export
kdenlive` rather than **mutating** MLT in place, so it never owns MLT's two
sharp edges: `<blank>` silently adding runtime every downstream cue is blind to,
and four declared-length spots (both tractors' `out`, the sequence track's
`out`, `producer0`'s length) that must be swept in step.

The rule pays for itself only while auto-editor writes the XML. On the
multi-source path it writes nothing — the kdenlive exporter **refuses, exit 2**.
So the XML is not being re-adopted from something that would otherwise produce
it; it is being written because nothing else will.

**The rule is therefore narrowed, not abandoned:**

- **Single-source `export` is unchanged.** It still shells out to auto-editor,
  render and `--export kdenlive` both. Nothing about today's behaviour moves.
- **The multi-source path generates MLT from the `Edit` plus the cue table**,
  every time, from scratch. It **still never mutates** an existing project — the
  distinction the original rule actually cared about survives intact.
- Generating means lucid now owns both sharp edges above. They are already
  written down in this file precisely so this day would not be a surprise, and
  the declared-length sweep gets an assertion rather than a comment.

Built as `src/lucid/mlt.py` (step 4, below): the sweep is `declared_frames()`,
read back off the finished document rather than tracked while building it.

### The design: Design B, unchanged

HISTORY.md § The multi-track costing spike costed two designs, recommended B, and
validated it against the real 37-cue table. Nothing found since argues against
it; that section keeps the numbers.

`Edit` stays **single-track and subtractive**. The picture is a *derived
projection* recomputed on every build, so there is nothing positioned to go
stale, and § The property everything below defends is preserved by
construction rather than by care. Untouched: all five addressing methods
(`timeline_time`, `timeline_span`, `timeline_spans`, `source_at`,
`source_spans`), `remove`, `keep_only`, `from_otio`, `to_otio`, captions,
verify, cut, locate.

Design A — widening `Edit` to N positioned tracks — stays rejected. Rippling the
VO would invalidate every stored position on the picture track, which is the
property traded away for the thing it was defending against.

### Build order

Each step is shippable and verifiable on its own. Parity is not optional:
every op gets an MCP tool **and** a `lucid` subcommand (CLAUDE.md § Conventions).

1. **The cue table.** `(clip_id, word_index, asset)` in the manifest,
   source-addressed, nothing in timeline coordinates. Ops `cue_add`, `cue_rm`,
   `cue_ls`; CLI `lucid cue add|rm|ls`; MCP to match. Bump `schema_version` and
   keep the reader tolerant of manifests without the key. **Built
   2026-08-08** — HISTORY.md § The cue table, step 1 of the layered timeline.
2. **The shot projection.** `build_shots` minus all XML — map each cue's word
   through the surviving ranges, each shot running to the next cue. ~150–200
   lines. `assemble_scream.py` is the worked reference; take its arithmetic,
   not its structure. **Built 2026-08-08** — HISTORY.md § The shot
   projection, step 2 of the layered timeline. Also resolves `asset` to a
   checked path (`card:name` under a new `assets/cards/`, else a registered
   video clip_id), per the division `cue_add`'s own docstring already
   committed to at step 1.
3. **Refuse to build when a cue lands in a cut range.** This fired correctly
   twice on Scream, both times catching a stale cue after a recut. It is the
   safety property of the whole feature and it is not optional. Test it
   first. **Shipped inside step 2, not after it** — the frame arithmetic has
   nothing to return for a cut word, so the refusal could not be deferred.
   What step 2 got wrong on the first pass and step 3's own tests exist to
   guard: it used `Edit.timeline_time` (containment of the word's *start*
   instant) rather than `Edit.timeline_span` (overlap across the whole
   word), and disagreed with `assemble_scream.py`'s own arithmetic on the
   real Scream VO at word 115 — a swallowed false start whose survival
   depends on its tail, not its start. Fixed before shipping; HISTORY.md
   § The shot projection has the numbers.
4. **The MLT writer**, multi-source path only. Owns the `<blank>` and
   declared-length constraints named above. Every emitted length asserted
   against the `Edit`'s own frame total from `autoeditor.frame_layout` — never
   from a duration (CLAUDE.md). **Built 2026-08-08** — HISTORY.md § The MLT
   writer, step 4 of the layered timeline. It also took the per-clip playback
   cursor step 2 deferred to it, and made `export` refuse to *render* a
   multi-source timeline rather than let auto-editor degrade it — the refusal
   step 5 then replaced with the render itself.
5. **Render through `melt`**, HISTORY.md § 4's three traps handled, exit code
   trusted for nothing. Assert the output's **resolution and frame count**, not
   its status. The measurements to beat are already on file: the step-4 spike
   rendered its own document at 1920x1080 and exactly the declared frame
   count, by hand. **Built 2026-08-08** — HISTORY.md § Rendering through
   `melt`, step 5 of the layered timeline. It also found the fourth trap the
   first three imply and none of them states: `WAYLAND_DISPLAY` without
   `XDG_RUNTIME_DIR` is not a display, and that is the pair a scrubbed
   environment — the MCP stdio transport's — hands the renderer.
6. **The picture lane in the web UI.** This becomes legal for the first time
   here and not before: the timeline may not draw a lane `export` cannot
   produce, so V2 lands in the same change that makes `export` able to produce
   it — never earlier. CLAUDE.md § Conventions, and § Tier 3 is the goal.
   **Built 2026-08-08** — HISTORY.md § The picture lane. What the rule turned
   out to demand: **not a lane drawn from `build_shots`.** The projection
   accepts a shot longer than its asset and the MLT writer refuses it, so the
   lane draws `timeline_view`'s `shots` — the projection already through
   `mlt.plan_picture` — and a refusal from either arrives as a message rather
   than an exception.

Seed the cue table from `assemble_scream.py`'s existing 37 cues, so the first
layered timeline lucid builds is **this video**, checkable against a file that
has already been watched — rather than an empty project that can only be
checked against itself. **Done at step 5, and it moved which project that
means.** The 37 cues address `VO/VO2-windowed.json` — the re-recorded VO,
re-found by phrase — while `Project/lucid-vo` holds the *v1* VO and a
929-word transcript, so pasting the table onto that project would have put
every cue on the wrong word. The seeded project is a new one on VO2.wav plus
the windowed transcript, where all 37 land and the render is real:
HISTORY.md § Rendering through `melt` has the numbers, and § The shot
projection and § The MLT writer have the two before it.

### What stays blocked, and it is not lucid

**The Billy/Stu duck.** It was rejected on measurement, not taste: the clip's
line sits at 105.35–109.15 s against the VO's own thesis sentence at
105.97–109.85 s, and `speech_overlap` re-measured 74–85% overlap with only
sub-second clean seams (HISTORY.md § `speech_overlap`). There is no seam to duck into. That
is a property of **the v1 recording**, and no amount of multi-track fixes it.

Two ways out, and the choice is editorial rather than technical:

- **The re-record**, which was always the plan and opens a real pause.
- **Insert a hold** — open a gap in the VO and let the film's line play in it.
  lucid cannot do this today: `Edit` only ever removes, so a non-subtractive
  operation is new work, and it is the same work as HISTORY.md § The `vo_extend` mirror is
  a deliberate non-goal, for now. That section's stated reason for parking —
  that it only matters the day lucid owns MLT generation — **expires with this
  decision.** Re-cost it against a watch, not in the abstract, and note it is
  the one item here that touches `Edit`'s subtractive invariant.

Neither blocks steps 1–6. The layered timeline ships without the duck.

## The Daydream parity map — copy the features and the look — 2026-08-08

The parity direction (Tyler, 2026-08-08: lucid copies Daydream's full feature
set and look/feel), the observed product, the design-system spec, the
feature-by-feature map against shipped code, and the build order are one
document: [DAYDREAM.md](DAYDREAM.md). The constraints that bind every parity
item are lucid's own and live where they always did: § Non-goals, the web-UI
conventions (no lane `export` cannot produce — CLAUDE.md), and § The
property everything below defends.

## Motion graphics and templates — the design note — 2026-08-09

The costed note DAYDREAM.md § Motion graphics + templates and § Next ask for
before any build. **The finding that shapes it: motion graphics need no new
timeline mechanism at all.** The Scream assembly's 13 cards already are motion
graphics minus the motion — PNGs in `assets/cards/`, cued by `(clip_id,
word_index, asset)`, resolved by `ops._resolve_asset`, projected by
`build_shots`, held by `mlt.plan_picture` as an `is_image` `Entry`, composited
by melt as a `qimage` producer. What is missing is a *generator* for the
asset, and one decision about animation that turns out to be about § The
property everything below defends rather than about rendering.

### Measured on this box, 2026-08-09

Five measurements, because a design note that guesses at the toolchain is how
the caption default came to name a font this machine does not have.

1. **There is a real SVG rasteriser here, and the obvious probes miss it** —
   `magick` links librsvg, so `magick in.svg out.png` renders text faithfully.
   Which binaries are absent, which delegate row to look for, and the numbers
   behind "faithfully" are a box fact, not a lucid one: wiki `tooling.md`
   § Rasterising SVG. **What it means for this note is only that the generator
   has a renderer to shell out to and needs no new dependency.**

2. **That renderer substitutes a missing font silently — the caption trap, on a
   second renderer.** Same card, one naming an installed font and one naming a
   missing one: pixel-identical output, both exit 0 (measurement in the wiki
   section above). The consequence here is that `captions.font_match` is
   already the right answer and gets reused rather than reinvented — report the
   substitution, do not prevent it. Without that, cards join captions in being
   drawn in a typeface nobody picked.

3. **The production render preserves a card's colour, and the alarm that says
   otherwise is a testing artifact.** A one-frame `melt … -consumer avformat`
   probe with default args lifted blacks — `(16,20,24)` → `(30,34,37)`, the
   signature of a limited/full-range mismatch — and that is the probe's fault,
   not melt's. Against the real render: `receipt-scream-1996.png`'s paper is
   `(250,245,236)` in the source and `(250,243,236)` in `~/lucid-scream-v2/out.mp4`.
   Two levels on one channel is h.264 chroma rounding. **No colour management
   is needed**; the false alarm is recorded because a one-frame probe is the
   obvious way to check and it will be rediscovered.

4. **Cards pillarbox, and it costs a quarter of the frame.** Now a measurement
   rather than the wiki row's prediction. `ops._mlt_resolution` takes the
   canvas from the first video clip — the film's **1920x816** crop — and the
   1920x1080 cards fit to it by height. In `out.mp4` the card occupies
   x ∈ [232, 1686]: **465 px of 1920, 24% of the width, is black bar.**

5. **melt will read an SVG directly, and taking that shortcut would split the
   rasteriser in two** — it goes through Qt, not librsvg (wiki `tooling.md`
   § Rasterising SVG). A card previewed through one renderer and rendered
   through another can disagree with no error on either side, which is this
   repo's recurring failure shape. So lucid rasterises to PNG itself and never
   hands melt an SVG — which the current code already does by accident, since
   `_resolve_asset` and `preview_source` both hardcode `<name>.png`.

### The design

**Asset format: SVG in, PNG out, both kept.** `assets/cards/<name>.svg` is the
source the agent authors and re-edits; `assets/cards/<name>.png` is the
rasterisation the cue resolves to. Both, because the cue table and the
preview `<img>` want a raster (and finding 5 says keep it that way), while a
card you cannot re-edit is a card you have to redraw from scratch to change a
year. No schema bump — `assets/cards/` is a directory, not a manifest field,
the precedent `CARDS_DIR` set at step 2 of the layered timeline.

**The generator is a new `graphics.py`**, shelling `magick` the way `asr`
shells whisper and `picture` shells melt — same reasoning, an external
renderer with a resolution order and no Python API worth binding. It returns
the font-substitution report for every `font-family` in the document, reusing
`captions.font_match` rather than growing a second one.

**Templates are SVG files with `{{slot}}` placeholders and a slot manifest**,
filled by XML-escaped string substitution — not a template engine. The starter
set is the three the Scream assembly actually used, not a speculative library:
`receipt` (title/year/stars/date/quote), `reveal` (title/year), `rerate`
(before/after). Their docs' "iterate one graphic at a time" is prompt guidance
and free to adopt.

**Cards generate at the project's canvas size, not at 1920x1080.** This is
what finding 4 actually says: the question was never "should cards
pillarbox", it is that a card was authored at a different aspect from the film
it sits in. `_mlt_resolution` already computes the canvas; `graphics` takes it
and the templates are authored in relative units. Existing cards keep working
— they still scale to fit — and new ones stop discarding 24% of the frame.

### Animation is a length problem, not a rendering one

This is the part that costs, and the cost is not where it looks.

`mlt.plan_picture` refuses a shot longer than its asset. A still has no length
to run out of: `IMAGE_LENGTH_SECONDS` claims four hours and `eof=continue`
holds the last frame, so a card fits any shot. **An animated card is a video
clip, and a video clip has a length.** But a shot's length is *derived* — it
runs from its cue to the next cue, through the current edit. An animated asset
baked to N seconds is a cue carrying an explicit length, which is precisely the
music-bed failure § The property everything below defends records as the
converse proof: cues carrying lengths tuned to the old runtime were
invalidated wholesale by a ~12 s append, while the 37-shot plan recomputed for
free from two `lucid cut` commands.

So the ordering is forced, and it is not a preference:

- **Static cards are the whole of the first build.** They inherit the property.
- **Animation, when costed, must be length-agnostic.** Intro-then-hold
  (animate in, then hold the last frame indefinitely) and loop are the two
  shapes that are; `eof=continue` already gives the hold for free on a
  `qimage` producer and would need it stated explicitly on an `avformat` one.
  **A fixed-length animation is the one to refuse**, and the refusal belongs at
  *authoring* time — `plan_picture`'s existing refusal fires at export, which
  is far too late to be told the graphic is the wrong length.
- Two mechanisms, when it comes: a melt `<filter>` on the entry (affine
  keyframes), which **`mlt.py` cannot express at all today** — `_playlist`
  writes bare entries and there is no filter support anywhere in the module —
  or an ffmpeg-rendered clip from an SVG frame sequence, which needs **zero**
  `mlt.py` change and reuses the existing non-image path. The second is
  cheaper and gets tried first.

### Build order, and where it stops

1. `graphics.py` — `render_svg`, with the font-substitution report. CLI
   `lucid card render`, MCP parity, per CLAUDE.md § Conventions.
   **Shipped 2026-08-09** — HISTORY.md § The card renderer, which records what
   the four measurements behind it decided and one they changed: `-size` fits
   rather than distorts, so step 3 below is the only thing that can close
   finding 4.
2. Templates and card creation: fill a template's slots, rasterise, land both
   files. CLI and MCP parity again.
3. Canvas-size defaulting, closing finding 4 for new cards.
4. **Stop.** Animation gets its own note, after a watch of a real card-heavy
   cut — the same discipline the layered timeline used.

No properties pane and no styling UI: the agent authors and the window
renders, which is the parity target DAYDREAM.md states. Two things stay
deliberately unanswered — whether the existing Scream cards get regenerated at
1920x816 (Tyler's call on a watch, and the wiki row already carries it), and
per-word caption animation, which shares "one Dialogue event per word" with
nothing here and neither blocks this nor is blocked by it.
