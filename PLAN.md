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

- **How does a lucid project know it is the film? Opened 2026-08-10.** The
  Scream project sat at the *silence-cut* stage of an edit whose retake pass had
  been done in Kdenlive — 73 segments and 411s against the shipped film's 63 and
  336s — and every check lucid has agreed with itself the whole time: the render
  matched the timeline, `verify` had nothing to report, all 38 shots planned. It
  was not broken, it was the wrong cut, and 72s of retakes reached a review.
  Three gaps, in the order they bite: **no repeat-finder in a transcript**
  (`verify --windowed` finds one in a *render*; `goodsometimes/scripts/vo_windows.py
  --repeats` finds one in audio and lives outside lucid), **no way to bring an
  outside edit in** (63 ranges were parsed from the `.kdenlive` playlist and
  written straight to `Edit`, bypassing `cut`), and **nothing that compares a
  project against what it is meant to be**. HISTORY.md § The VO the project was
  holding.
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

### Recently — what shipped, and what each one corrected

**What is in flight is the wiki's Open items table, never this file** (root
`CLAUDE.md` § Knowledge stores). What follows is the standing record of what
each shipped item turned out to be, which is a different question.

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
project. It is not only a caption question: librsvg substitutes as silently as
libass and at exit 0, so a card template names a fallback *stack* ending in a
generic rather than a face — routing around the call rather than taking it.

**Motion graphics + templates shipped 2026-08-09 — all three steps, stopping
where its costed note said stop** (§ Motion graphics and templates; HISTORY.md
§ The card renderer, § Card templates). The note's finding was that the item
needed no new timeline mechanism — the Scream cards already are motion graphics
minus the motion — so what shipped is the generator it was missing: a renderer,
`card new` over three templates, and a canvas that defaults to the project's
own. That last closes the note's finding 4 for new cards, and only it could
have: `-size` *fits*, so no resize on the way in would have done it.

What the note costed and refused to build is *animation* — an animated card
carries a length, a shot's length is derived from the edit, and a cue carrying
a length is the failure § The property everything below defends exists to
prevent. It gets its own note, after a watch of a card-heavy cut.

**B-roll by description shipped 2026-08-09, all three build steps**
(§ B-roll by description; HISTORY.md § `describe`, § `describe_ls`, § The
pinned cue). The note inverted the item's own framing and was right to: the
indexing half everyone assumed was the cloud-shaped risk is local and resident,
while the *placement* half DAYDREAM.md counted as already-coming did not exist
— a cue could not name a moment inside its asset, because `mlt.plan_picture`
picks that by a consumption cursor. So footage is described, searched by
reading, and now placed by a cue carrying an in-point that refuses rather than
rewinds.

Four things the build corrected or added, each outliving the step that found it:

- **Windows round up, never to nearest** — round-to-nearest silently *widens*,
  and widening is the one direction that fails.
- **~3.5s a window and ~97 words a description**, against the note's 2.6–3.3s
  and ~60, on two independent runs. The read-them-all ceiling is ~600 windows,
  not ~1000.
- **`src_pin` and `src_start` are separate keys** — the cue's ask against the
  planner's answer. One key meaning both reads as correct in every test that
  has a pin in it.
- **A pin advances the per-asset cursor**, so an unpinned re-use after one
  carries on rather than replaying what was just shown.

The pinned refusal was settled by rendering colour-coded b-roll through melt
and sampling the pixels, because the rewind it prevents produces a file and
exit 0. **What is left is not a build**: the note's step 4 is a watch of a real
b-roll cut, before ranking of any kind.

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
   What it left was per-word *animation*, **costed and then declined on a
   watch, both 2026-08-10** (§ Per-word caption animation — the design note;
   HISTORY.md § The caption animation nobody wanted). The costing overturned
   the item's premise — it is not an export cost and not a per-word Dialogue
   event, it is two style fields over the one event `to_ass` already writes —
   and then all four treatments were rendered on the real film and Tyler
   chose the `\k` fill lucid already writes. **This rung is done, and lucid
   diverges from Daydream here by choice** (DAYDREAM.md § What parity does not
   import).
   Then 3. **motion graphics + templates**, then
4. **b-roll by description** — **all three build steps shipped 2026-08-09**
   (§ B-roll by description; HISTORY.md § `describe`, § `describe_ls`, § The
   pinned cue). Footage is indexed, searched, and now *placed*: a cue carries
   an in-point and the shot shows the moment it names or `export` refuses.
   The hour-metering worry resolved against Daydream rather than for it —
   describing locally is minutes, and the part that actually needed building
   was the cue that could name a moment. **The watch that step 4 held for
   happened 2026-08-10, and cost the item its premise**: what chooses a clip
   is not the vision index but a per-clip `synopsis`, and lucid does not
   choose at all (§ B-roll by description step 5; HISTORY.md § Choosing the
   b-roll). The index's remaining use is the in-point, which nothing pins yet.
5. **The long tail** — aspect swap, import roles + assets pane,
   multi-project picker, HTTP MCP transport, properties pane. **Aspect swap
   is no longer only a parity nicety** — it is what a `tiktok-reels` export
   preset is waiting on, and the preset is the first thing anyone reaching
   for a vertical export will ask for. **Costed 2026-08-09** (§ Aspect swap —
   the design note), and the cost moved: not both render paths but one, since
   an override routes through the MLT writer that already reframes — plus the
   cards, which are the only project state a swap cannot re-derive. **Steps 1
   and 2 shipped 2026-08-10** — the canvas field with its routing, and the
   card record that makes a card re-derivable (HISTORY.md § The canvas field,
   § The card record). Both corrected the note: the bump the first refused
   landed on the second, and the cards the second was meant to rescue turned
   out never to have been lucid's. **Step 3, the MLT reframe, shipped
   2026-08-10**: a swapped canvas now crops to fill, per-clip and overridable,
   verified against a real melt render (HISTORY.md § The MLT reframe).
   **Step 4, the viewer's frame, shipped 2026-08-10** — the preview is shaped
   like the render and crops where it crops, which closes both the
   disagreement step 3 opened and the older finding 6 (HISTORY.md § The
   viewer's frame). It corrected the note too: the note said "contain" there
   and contain would have drawn black bars the render does not have.
   **Next is `tiktok-reels`**, now one preset entry plus the canvas, and then
   the stop-and-watch that ends this item.

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
   files. CLI and MCP parity again. **Shipped 2026-08-09** — `lucid card new`
   and `card templates`, the three templates read off the real Scream cards,
   and the escaping split that a string template lives or dies on.
   HISTORY.md § Card templates.
3. Canvas-size defaulting, closing finding 4 for new cards. **Shipped
   2026-08-09**, in the same change — and the stdio suite is what caught the
   MCP tool still defaulting to 1920x1080 while the op defaulted to the
   project.
4. **Stop.** Animation gets its own note, after a watch of a real card-heavy
   cut — the same discipline the layered timeline used.

No properties pane and no styling UI: the agent authors and the window
renders, which is the parity target DAYDREAM.md states. Two things stay
deliberately unanswered — whether the existing Scream cards get regenerated at
1920x816 (Tyler's call on a watch, and the wiki row already carries it), and
per-word caption animation, which shares "one Dialogue event per word" with
nothing here and neither blocks this nor is blocked by it.

## B-roll by description — the design note — 2026-08-09

The costed note DAYDREAM.md § B-roll by description and § Next ask for before
any build. **The finding that shapes it inverts the item's own framing.**
DAYDREAM.md says lucid "has the placement substrate coming (cues) and one
primitive (`spot_frames`)" and lacks indexing and search, with the indexing
half being the part that must not be copied blind because Daydream's metering
implies cloud inference.

Measured, both halves come out the other way round. **The indexing half is
nearly free and entirely local** — the model is already on this box, the
pipeline that drives it is already written in a sibling repo, and a project's
whole footage library describes in about six minutes. **The placement
substrate is the part that does not exist.** A cue addresses
`(clip_id, word_index, asset)`; where inside the asset a shot reads is decided
by `mlt.plan_picture`'s per-asset cursor, in consumption order. Search's whole
output is *a moment* — "cold-open at 312s" — and there is no way to say it.
The missing piece is not an index. It is an in-point on a cue, and it is small.

### Measured on this box, 2026-08-09

Six measurements, on the real Scream footage (`~/lucid-scream-v2/proj/media`,
nine clips, 14s to 730s), because the last two notes both found the toolchain
was not what it was assumed to be.

1. **The describe model is resident and the loader is already written.**
   `Qwen2.5-VL-7B-Instruct` is 31 GB in the HF cache; `vaultmedia`'s
   `tagger_core.load_qwen` loads it 4-bit (nf4, bf16 compute) in **14.9s**, and
   `run_vlm` is a generic frames+prompt pass. Nothing needs downloading and no
   inference code needs writing. What lucid must **not** reuse is that repo's
   prompt and vocabulary — both are specific to that repo's own library — only the loader
   and the generation pass. That the model is cached and that the tagging venv
   exists are box/cross-repo facts and belong in the wiki, not here; this note
   cites them.

2. **Cost is per window, not per second of footage.** Sampling plus one
   description is **~2.6–3.3s per window**, near enough constant regardless of
   how much footage the window spans:

   | clip | span | windows | total | per minute of footage |
   |---|---|---|---|---|
   | `s1996-billy-stu` | 30s | 3 × 10s | 7.9s | 15.7s |
   | `s3-reveal` | 55s | 5 × 10s | 16.5s | 18.0s |
   | `s2022-reveal` | 160s | 8 × 20s | 22.9s | 8.6s |

   So window *length* is the only cost knob, and the Scream project's ~1300s of
   video is **~6 minutes at 10s windows, ~3 at 20s**. That makes `describe` a
   *job*, not a request — the same shape as the still-open preview transcode,
   and it should reuse `/api/render`'s background pattern rather than invent a
   second one.

3. **VRAM is the ceiling, and this box's always-on MoE server sets it.** The
   RTX 5070 has 11.5 GiB usable and `llama-server` holds **3.5 GiB
   permanently**. Six frames at 420x360 peaks at **6024 MiB and fits**; twelve
   frames **OOMs** — which is what vaultmedia's own `num_frames_for` rule asks
   for on a 730s clip, so the 730s cold open is exactly the clip that failed.
   lucid therefore **cannot scale frames with clip length**; it holds
   frames-per-call fixed and scales window *count*. Finding 2 reaches the same
   place from the cost side.

4. **A whole-clip description is not merely vague, it is wrong — and windows
   fix it.** One 6-frame pass over the 30s Billy/Stu clip described **six men**
   where there are two: it read six frames as six people, in fluent prose, with
   no signal that anything was off. The same clip in 10s windows of 3 frames
   reads correctly and concretely — kitchen, white cabinets, blood, a knife.
   The whole-clip pass on `s3-reveal` did the softer version of the same thing,
   collapsing three distinct locations into "a person… another person… a third
   person" and discarding *when* each was. Windowed output is specific enough to
   search on: "a kitchen with blue tiled walls and a white range hood featuring
   circular vents".
   - **Two residual error classes, recorded so they are not rediscovered as
     bugs.** The model still narrates *across* a cut inside a window as though
     it were one take ("the camera remains stationary as the figure turns to
     face away"), so a window is not evidence of a continuous shot. And at
     `max_new_tokens=120` two windows **truncated mid-sentence** — an index
     entry that ends mid-fact, which reads as a complete description. Whatever
     limit ships has to be checked against, not assumed.

5. **Scene detection cannot choose the windows, and it fails by producing
   output.** `select='gt(scene,T)'` is cheap — 730s scanned in 11.1s, ~66×
   realtime — but `T` is not portable across footage. At the *same* threshold
   0.3, the 160s clip yields **23** cuts and the 730s cold open yields **5**.
   Five windows over 730s is a 2.4-minute window described from three frames:
   precisely the blur finding 4 rejects, arrived at silently and looking like
   success. Sweeping the cold open confirms the knob is a cliff rather than a
   dial — **0.1 → 118 cuts, 0.2 → 50, 0.3 → 5**. So **fixed windows are the
   default**, and scene detection is only ever allowed to *subdivide* one.

6. **The homebase encoder service is not relevant compute.** DAYDREAM.md put
   port 8765 on the checklist as possibly-relevant. It is vaultmedia's ffmpeg
   transcoder — zero inference, no model of any kind. Struck from this item;
   it is, however, relevant to a *different* open one, the preview proxy
   transcode.

### The design

**A description indexes the source, which is why an edit cannot invalidate
it.** The unit is `(clip_id, src_start, src_end, text)` in **source** seconds.
The b-roll asset is not the thing being cut, so its own times never renumber —
the same reason word indices are safe, and not in tension with § The property
everything below defends, which is about cues carrying *timeline* lengths.

**They live in the manifest, and that is a schema bump.** v2 → v3, with a
`_MIGRATIONS[2]` entry keyed by the version it migrates *from*, exactly as the
caption/cue work established — the migration mechanism exists so a bump is a
step rather than a widening of `Project.open`. Rejected alternatives: a sidecar
directory on the `assets/cards/` precedent (a card is a file a cue names by
convention; a description has no natural filename and is per-clip metadata
`info` should report), and `cache/` (disposable, and these cost GPU minutes).

**The runtime is a subprocess, resolved the way whisper is.** `asr.transcribe()`
shells the binary via `LUCID_WHISPER` → PATH → a sibling venv specifically so
lucid never imports a heavy model runtime; `describe.py` gets the same shape —
`LUCID_VLM` → the sibling tagging venv → a refusal that names what is missing.
lucid's own venv gains no torch. It also keeps the sibling repo's prompts out of
lucid: lucid passes its own.

**Search is the agent reading the descriptions, and that is right up to a
measured ceiling.** ~130 windows for this project at ~60 words each is roughly
**10k tokens** — the agent is already in the window and can simply read them.
No embedding runtime, no vector store, no similarity threshold to tune. The
ceiling is real and worth writing down: at ~1000 windows (≈5.5 hours of footage
at 20s) it is ~80k tokens and stops being reasonable. Embeddings become the
right answer only when a **cross-project** library exists, which lucid does not
have — multi-project is late and small in § Next. So `describe_ls` returns the
table, optionally filtered by clip, and the agent picks. Keyword filtering is a
convenience on top, not a subsystem.

**The one thing that must be built rather than reused: a cue that can name a
moment.** `cue_add` gains an optional `src_start`, and four constraints come
with it:

- **In-point only.** The out-point stays derived from the next cue, through the
  edit. A cue carrying both ends is the music-bed failure § The property
  everything below defends records.
- **A pinned cue refuses rather than rewinds.** `plan_picture` today rewinds a
  cursor that would overrun its asset, which is right for an unpinned re-use —
  clamping would read as a frozen frame, a render bug. For a *pinned* cue,
  rewinding silently shows footage the search did not find: correct pixels,
  wrong video. It refuses, and the refusal arrives as `shots_error` for the
  lane to draw, never as an exception — the picture lane's existing contract.
- **Same schema bump as the descriptions**, one migration for both.
- **No new plumbing for the window.** `timeline_view`'s shots already carry
  `src_start` (`ops.py:632`), and both `player.js` and `timeline.js` already
  read it, because the preview picture layer needed exactly this field.

### What this note refuses to build

- **No embeddings, no vector store, no CLIP.** Measured unnecessary at project
  scale; the trigger to revisit is a cross-project library, not a hunch.
- **No "watch on import".** It would make every import a six-minute job and
  describe footage nobody uses. `describe` is explicit, like `transcribe`.
- **No automatic placement.** The agent places, through `cue_add`, after a human
  or the agent has read the description. A pass that picks *and* places puts a
  wrong shot into a finished film with nothing on screen saying so.
- **No re-describe hook on edit.** Descriptions index the source; cutting the VO
  cannot invalidate them. Stated explicitly so nobody adds the invalidation.

### Build order — step 1 shipped 2026-08-09

1. `describe` — the subprocess, fixed windows, manifest storage, the schema
   bump, and skip-if-already-described. **Shipped**, with the corrections
   measured on the way in: HISTORY.md § `describe`.
2. `describe_ls` — the table. **Shipped 2026-08-09**, CLI and MCP, and it took
   `info` with it. The web half of the parity this line asked for was *not*
   built, deliberately: nothing in the window places a cue, so a descriptions
   pane would be a view of a decision the UI cannot take. HISTORY.md
   § `describe_ls`.
3. `cue_add --src-start`, `plan_picture`'s pinned-entry refusal, and the stdio
   and HTTP suites that prove both are reachable rather than merely written.
   **Shipped 2026-08-09**, verified by a real melt render rather than by the
   suites alone: HISTORY.md § The pinned cue. What it added is a second field
   name — the cue's ask is `src_pin` and the planner's answer is `src_start`,
   because carrying both under one key would have read correctly in every test
   that had a pin in it.
4. **Stop.** Watch a cut that actually uses b-roll before adding ranking of any
   kind — the same discipline the layered timeline and the card note used.
   **The cut got made on 2026-08-10, and the stop earned itself.** Ranking was
   the wrong next question: the index it would rank has no separation in it —
   0.201 word overlap between two windows of the same clip against 0.161
   between two *different films*, and `killer`, `unmask`, `stab` and `costume`
   appear in none of the 139 descriptions. The placement half held on real
   footage; the describing half returns rooms and clothing because
   `describe.PROMPT` asks for rooms and clothing. HISTORY.md § The b-roll cut,
   on real footage.
5. **The prompt was the wrong suspect too, and the answer is `synopsis` —
   shipped 2026-08-10.** Rewriting `describe.PROMPT` to ask for events was next
   until it was costed against the alternative it was competing with: the clips'
   own *filenames* already name the event (`scream3-reveal-roman-brother`) and
   score 3 of 25. The information is not missing from the index; the connection
   is not lexical. So the corpus moved up a level — one sentence per clip saying
   what the footage *is*, allowed to carry what no camera can see — and the
   choosing moved out of lucid, to whatever is reading the brief. 2/25 → 14/25,
   with the whole loop driven off `broll_brief`'s own output. **A second
   reviewing pass was tried and scored worse (13 → 10), so there is not one.**
   HISTORY.md § Choosing the b-roll.

## Aspect swap — the design note — 2026-08-09

The small note DAYDREAM.md § Aspect swap and § Next ask for before any build.
**The finding that shapes it inverts which half is hard.** DAYDREAM.md records
the multi-source side as the blocker — "the melt path cannot take a resolution
at all until HISTORY.md § 4's memory-growth combination is isolated — so a real
9:16 needs an answer on the multi-source side, not just a flag on the other
one" — and `ops.export` and `picture.render` both carry the same reading.

Measured, it comes out the other way round. **The melt path renders a 9:16
frame today, with its consumer untouched, and reframes with one filter.** The
resolution on that path is a `<profile>` attribute, and `mlt.document` has
taken a `resolution=` argument since the MLT writer shipped; the consumer was
never the knob. **The single-source path is the one with no answer** — `-res`
letterboxes and auto-editor has no reframe flag to teach. So the item is not
"add a resolution to both writers". It is: give the project a canvas, route
anything that overrides it through the writer that can already do the work,
and decide what part of the frame survives the crop.

### Measured on this box, 2026-08-09

Rendered against the real Scream footage (`~/lucid-scream-v2/proj/media`,
`cold-open.mp4`, 1920x816), through `picture.render` — not through a
hand-run melt, so the display env, the `$HOME` staging and the memory cap are
the ones lucid actually uses.

1. **A 9:16 profile renders, and `RENDER_ARGS` is untouched.** `mlt.document(
   resolution=(1080, 1920))` over a 1920x816 source produced a **1080x1920**
   file, memory cap 6G, no growth, against a 1920x816 baseline from the same
   script. The consumer stayed the four measured-safe keys throughout.
   HISTORY.md § 4's finding is about *restating the profile on the consumer*;
   declaring it in the `<profile>` is a different mechanism and always was.
   `ops.export`'s refusal of a caller-supplied `resolution` on the melt path
   is still correct — widening the consumer remains unmeasured — but the
   inference DAYDREAM.md drew from it, that 9:16 is therefore unreachable
   there, is not.

2. **A swapped profile pillarboxes, and the geometry is exact.** Sampled
   pixels rather than exit codes: the content band is **459 of 1920 rows**,
   x 236..845 — the source scaled by 1080/1920 = 0.5625 (419→236, 1503→845),
   to the pixel. **76% of the frame is black bar.** So melt at a swapped
   profile produces precisely what auto-editor's `-res` produces (DAYDREAM.md
   § Export presets, measured 320x240 → 608x1080). **Both paths can already
   make 9:16 pixels and neither reframes** — resolution was never the missing
   piece on either one.
   - **The first sample said 104 rows**, which reads as something worse than a
     pillarbox. It was a dark scene, not geometry. A brightness-thresholded
     bounding box across five frames is what settled it — the same reason the
     picture layer is verified by canvas readback rather than by eye
     (HISTORY.md § The preview picture layer).

3. **A real crop-to-fill reframe renders today, and it is one filter.** A
   `qtblend` filter carrying `rect="-1719 0 4518 1920 1"` (fill by height,
   centre the overflow) hung on the source producer fills the frame: content
   spans y **0..1919** and x **83..1079**, against the pillarbox's 459-row
   band. No new mechanism, no new dependency, no consumer change — `mlt.py`
   already writes `qtblend` for compositing. DAYDREAM.md's "mechanically
   modest after the MLT writer exists" is right, about the path it called hard.
   - **The filter has to go on every node, not every resource.** The probe
     matched **two** nodes for one file, because `mlt.py` writes one node per
     distinct resource *per role* — a file used by both the edit and the
     picture lane would otherwise be reframed on one track and letterboxed on
     the other, in the same frame.

4. **The project holds two independent derivations of its canvas, and no place
   to override either.** `ops._mlt_resolution` (first video clip, else 1080p)
   and `ops._caption_canvas` (first video clip → `captions.canvas`) walk
   `clips` separately for the same fact. An override must reach both: quoting
   captions against a 16:9 reference over a 9:16 render stretches the glyphs,
   which is what `captions.canvas`'s own docstring exists to prevent.

5. **An aspect swap orphans every card already made, and nothing on disk can
   re-author one.** `card_new` writes `assets/cards/<name>.svg` at the canvas
   and rasterises it; the template name and slot values come back in the reply
   and are **persisted nowhere**. The SVG on disk has the old aspect baked into
   its viewBox, and `-size` *fits* rather than distorts, so re-rendering it at
   a new canvas pillarboxes the card inside the frame. It is not a one-off — it
   recurs on every aspect change. **Cards are the only project state that is
   rasterised rather than derived**; captions survive a swap because they come
   off `caption_style` every time.
   - **The half of this finding about the *existing* cards was wrong, and step
     2 found out by building it.** It read `card_new`'s reply and inferred the
     cards in the Scream project came from it. They did not — they are twelve
     PNGs with no SVG, drawn by a `goodsometimes` script before `card_new`
     existed — the thirteenth of the assembly's set is the outro card, which is
     a tail in that script and not in lucid's cue table at all. So the record
     cannot recover them, and this is not the wiki's "regenerate the 13 cards"
     item after all. HISTORY.md § The card record.

6. **The preview holds two ideas of the frame, and they agree today only by
   accident.** `player.js`'s `captionBox()` contain-fits the *project's*
   caption canvas into `#viewer`, while `#viewer video` is `max-width`/
   `max-height: 100%` in a flex-centred black box — so the picture's letterbox
   is the *media's* own aspect. The two match today because the canvas is
   derived from the media. An aspect override is exactly what separates them:
   a 16:9 source in a 9:16 project would draw full-width video with the
   captions boxed to a 9:16 sub-rectangle inside it.
   - **Closed by step 4**, and it turned out to be the smaller half of what
     the preview owed: there is one rectangle now, and it is #frame.

### The design

**A reframe indexes the source, so no edit can invalidate one.** The unit is
`(clip_id, rect)` in **source pixels** — geometry, never a length — the same
rule as a footage description, and for the same reason. Nothing here carries a
timeline duration, so it is not in tension with § The property everything below
defends.

**The project canvas is one field, and it feeds both derivations.** A `canvas`
in the manifest (`WIDTHxHEIGHT`, absent meaning "derive as today"), read by
`_mlt_resolution` and `_caption_canvas` before either walks `clips`.

**It takes no schema bump, and the first draft of this note was wrong to say it
did.** The precedent is written at `CAPTION_STYLE_KEY`: an additive optional
key whose absence means what every older manifest already meant needs no
version, and bumping for one "would make `Project.open` refuse every existing
project to gain nothing". v2 and v3 both bumped for *list* keys that other ops
`setdefault` — there the number is what makes the key true rather than
incidentally survivable. A canvas is the `caption_style` shape, not the
`descriptions` shape. **Where the bump does land is step 2**: persisted card
records are a list, and old cards on disk lack them.

**An aspect override routes through the MLT writer, whatever the source
count.** `export` picks its writer from the project and never from an argument,
precisely so a project that would render wrong cannot be argued onto the wrong
road; "this project overrides its canvas" is another way of asking
`_is_layered`'s question, and it gets folded in there rather than given a flag.
The single-source path is not taught to reframe — it cannot be.

**The default crop is centre, and it is reported rather than assumed.** A
centre crop of a 16:9 frame is wrong whenever the subject is not centred, which
in this footage is often. So the reply names the crop it used per clip and a
clip can override it. What `export` must never do is choose a crop by analysis
and say nothing: that is correct-pixels-wrong-video with a plausible file to
back it up.

**Cards become re-derivable, which `card_new` owes anyway.** Persist
`(template, slots, canvas)` alongside the card — the v4 bump — so a swap
can re-author every card at the new canvas, and so the 13 existing Scream cards
regenerate by command rather than by hand.

**The viewer's frame becomes the project canvas**, with the media contained
inside *that* — one more `contain`, in the layer that currently has none, so
the picture and the caption layer letterbox against the same rectangle.

> **Corrected by step 4, which built it.** `contain` was written before step 3
> decided the render *crops to fill*, and it only answers finding 6. Contained
> media in a canvas frame draws the whole 16:9 clip pillarboxed inside a 9:16
> box — still showing footage the export drops, now with black bars the render
> does not have. The build places media at the writer's own `dest_rect`
> instead, so the preview crops exactly where the render crops. A still keeps
> the `contain`, because that is what MLT does to one. HISTORY.md § The
> viewer's frame.

### What this note refuses to build

- **No consumer widening.** Whether `width`/`height` on the melt consumer is
  memory-safe stays unanswered *and stays unnecessary* — finding 1 makes it
  irrelevant to this item rather than a prerequisite for it. The refusal in
  `ops.export` stays exactly as it is.
- **No smart reframe** — no face tracking, no saliency crop. That is a model,
  and a wrong one reframes a film with nothing on screen saying so.
- **No animated crop.** A pan/scale over time is a crop carrying a length, and
  a cue carrying a length is the failure § The property everything below
  defends exists to prevent. It belongs with animation, after its own watch.
- **No in-place swap that leaves old cards behind.** A vertical render with 13
  pillarboxed 16:9 cards in it is the failure this item is meant to close, not
  a partial win. Step 2 gates step 3 for that reason.

### Build order — nothing built yet

1. **The canvas field** — **shipped 2026-08-10.** Manifest key, both
   derivations reading it, `status` reporting it, `canvas` op with CLI and MCP
   parity. **The routing came with it rather than waiting for step 3**, which
   the note originally had backwards: an override that `_is_layered` did not
   know about would send a single-source project to auto-editor, which takes
   the export and ignores the canvas — a 16:9 file at exit 0, the exact
   silent-wrong-output this item exists to close. So an overridden project
   routes through the MLT writer from the day the field exists, and the reply
   says so (`routes_through`). Until step 3 a swapped aspect pillarboxes, and
   the reply says that too (`fills_frame`).
2. **Card re-derivation** — **shipped 2026-08-10.** `card_new` records
   `(template, slots, canvas)`, `card_reauthor` fills the template again at
   the project canvas, and `canvas` names the cards a swap has left behind.
   The v4 bump lands here, as step 1 said it would. **What it does not do is
   close the wiki's 13-card item, and this step's premise was wrong about
   that**: the twelve cards in the real project are PNGs with no SVG, drawn by
   a `goodsometimes` script before `card_new` existed, so there is nothing to
   persist and nothing to re-render — and their receipts carry three ink
   levels that lucid's one-fill `quote` slot cannot express. Closing that item
   needs an emphasis-capable quote slot first, **costed 2026-08-10 in § The
   emphasis-capable quote slot**, which found a second loss this step missed:
   the script wraps by measurement, so the slot needs a flow as well as an
   ink. HISTORY.md § The card record.
3. **The MLT reframe** — **shipped 2026-08-10.** Per-clip crop rects
   (`reframe`, with CLI and MCP parity) and the `qtblend` filter applied per
   node *per role*; the routing landed in step 1. Verified the way the pinned
   cue was, and the method mattered: the render fills the frame *and* matches
   ffmpeg's own crop of the source to 0.34/255, while the bbox check that
   settled finding 2 is uninformative on a dark frame and nearly reproduced
   its own trap. **The note under-specified one decision and the build had to
   make it**: an override is a rect of arbitrary shape, and growing it to the
   canvas rather than shrinking it into the canvas is what keeps the subject
   whole. HISTORY.md § The MLT reframe.
4. **The viewer's project-canvas frame** — **shipped 2026-08-10.** `#frame`
   is the canvas, every layer draws inside it, and media is *placed* at
   `timeline_view`'s new `reframe[clip].dest` — the writer's own rect — rather
   than fitted to its own aspect, so the preview crops where the render crops.
   `captionBox()` collapsed to the frame, which closes finding 6 as well.
   **The note said "contain" here and the build had to correct it**: contain
   would have closed finding 6 and left step 3's disagreement open, drawing
   black bars the render does not have. Verified in a real browser on two
   copies of the Scream project, geometry from `getBoundingClientRect()` and
   pixels against both hypotheses; it also turned up a shipped bug the picture
   layer's own readback could not see. HISTORY.md § The viewer's frame.
5. **`tiktok-reels`** — **shipped 2026-08-10.** One `EXPORT_PRESETS` entry
   carrying `youtube`'s four encode values, plus `PRESET_ASPECT`; the refusal
   text in `_resolve_preset` came out with it, and CLI, MCP and the window's
   preset menu all carry the name. **The note said "plus the canvas" and left
   open how the two halves meet, so the build decided it: the preset
   *checks* the project's canvas and refuses, and never sets it.** A preset
   that reshaped a project would be an export argument rewriting project
   state — the same class of failure as picking the writer from an argument.
   Verified by a real melt render measured at 90x160 and by the refusal
   against the real Scream project, which wrote nothing. HISTORY.md
   § `tiktok-reels`.
6. **Stop.** Watch a vertical cut before ranking anything further — the same
   discipline the layered timeline, the card note and the b-roll note all
   used. **This is where the item now sits, and it is the only thing left in
   it.** Three of the five steps above corrected their own premise by being
   built; nothing here has yet been looked at as a film.

## The emphasis-capable quote slot — the design note — 2026-08-10

The note § Aspect swap step 2 said it was not writing, and the one thing
standing between the twelve unrecorded Scream cards and being re-authored
through lucid at all (HISTORY.md § The card record). It is nominally a
template change. **It is not, and the finding that shapes it is that the
costing named one loss where there are two — and the second one is a rule
this repo already wrote down.**

HISTORY.md § The card record costs it as emphasis alone: the script's receipts
"carry three ink levels inside one paragraph — `dim`, `key`, and an amber `em`
on the fragment the VO quotes — and lucid's `receipt` has one `quote` slot of
kind `lines`, drawn in a single fill." True. But `make_scream_cards.py:63` is
`wrap_runs`, a greedy word-wrap that **measures** each word against a body
width, and the emphasis runs cross the line breaks it produces. lucid's
`_lines_markup` refuses to wrap on principle — "a wrap computed from a
character count is a wrap that overflows the frame silently on the first line
of wide glyphs" (`graphics.py:456`). So the slot needs emphasis *and* a wrap,
and the wrap is the half that argues with a standing rule.

**The rule survives the measurement, and its reasoning is what tells you how
to build the wrap.** It indicts character counts, which deserve it; it does
not indict measurement, and this box can measure through the exact renderer
that draws the card.

### Measured on this box, 2026-08-10

Through `magick`'s RSVG coder — librsvg 2.62.0, ImageMagick 7.1.2-13 — which
is the path `graphics.render_svg` already uses, at Zilla Slab 40px, the
script's own body size.

1. **Per-run emphasis renders through librsvg exactly, and reproduces all
   three of the script's ink levels to the byte.** One `<text>` carrying three
   `<tspan>`s with their own `font-weight`, `fill` and `fill-opacity`, sampled
   off the raster rather than eyeballed: `dim` → `155,151,145` (ink `#1a1714`
   at 0.42 over paper `#faf5ec` predicts 156), `em` → `232,161,60` (amber
   `#e8a13c`, exact), `key` → `26,23,20` (ink, exact). **There is no
   mechanism to invent here** — the emphasis half is a markup shape and a
   vocabulary, nothing more.

2. **A wrap measured through RSVG is accurate to ±0.8%; a character count is
   wrong by −34.6% to +83.4%.** Against the ink width of the whole line
   rendered, on three real Scream quote lines and two adversaries:

   | line | measured | character count |
   |------|----------|-----------------|
   | "might be the perfect horror slasher." | +0.8% | +16.3% |
   | "The satire is great. I know I am late…" | +0.3% | +19.8% |
   | "Falls apart a bit in the second half." | +0.7% | +25.0% |
   | `WWW MMM WWW MMM WWW MMM` | +0.7% | **−34.6%** |
   | `illillillill iiii llll iiii llll` | −0.3% | +83.4% |

   **The `WWW MMM` row is the rule's own case, and it confirms it**: the
   character count *underestimates* by a third on wide glyphs, which is the
   silent overflow `_lines_markup`'s docstring exists to prevent. Note the
   direction — a character count is not merely imprecise, it is unsafe in the
   one direction that produces a wrong card at exit 0.

3. **Measure candidate lines, not words — it is exact, and it costs the same
   number of renders.** The obvious cheap build measures each word once and
   sums with a space advance; that is the +0.3%/+0.8% column above, and it
   drifts to −0.3% on `illill…` because side bearings accumulate. But greedy
   wrap tests one *prefix* per word either way, so rendering the actual
   candidate line is O(words) too — and it is ground truth rather than a sum,
   it captures kerning, and it can see the mixed faces a styled line actually
   contains, which the per-word shortcut cannot without tracking run styles
   itself. The shortcut is more code and less accurate.

4. **100ms a render, so ~1.5s for a 15-word quote and ~48s for all twelve
   cards.** That is fine for `card_new` and it is a fact about *where* this
   lives: measurement belongs at authoring time and must never sit in a
   request path. `card_reauthor` at a new canvas re-flows, so a canvas swap
   over a card-heavy project pays it too — worth reporting, not worth
   avoiding.

5. **librsvg resolves CSS weights correctly, and `fc-match` disagrees with
   it.** `font-family="Zilla Slab" font-weight="600"` renders SemiBold (918px
   ink on a reference string) and `700` renders Bold (931px), which is right.
   `fc-match 'Zilla Slab:weight=600'` answers `ZillaSlab-Bold.ttf` — because
   fontconfig's weight scale is not CSS's. This nearly became a finding about
   losing SemiBold in the re-author; it is instead a finding about the
   reporter, and a live one rather than a future one. **`font_report` reports
   per `font-family` declaration and never reads `font-weight`, so its `drawn`
   field is already wrong on a shipped template**: `receipt.svg`'s title is
   `font-weight="700"`, librsvg draws Bold, and `fc-match 'Zilla Slab'` — the
   family alone, which is what the reporter asks — answers SemiBold. It is a
   wrong *report*, not a wrong render, and it only bites a family with more
   than one weight installed. Emphasis makes weight load-bearing for the first
   time, so the reporter needs the declaration's weight before step 1 lands;
   filed as its own remainder rather than folded into this note's steps.

6. **The typeface is not a loss, which the costing did not say either way.**
   lucid's `FONTS` defaults are Noto Serif / Lato, not Zilla Slab — but they
   are ordinary overridable slots, so a re-author passes the script's own
   stack and gets the script's own faces, both of which this box has
   (`~/.local/share/fonts/ZillaSlab-{SemiBold,Bold}.ttf`). Nothing needs
   building for it; it needs writing down, because the twelve will look wrong
   in a way that has nothing to do with this item if nobody passes it.

### The two decisions the measurements do not make

- **The run vocabulary.** Three named levels (`key` as the default, `dim`,
  `em`) is what the source data has, and semantic names beat inline style
  because the `em` fragment is *the bit the VO quotes* — that is meaning, not
  ink. What the note recommends and does not consider settled is spelling it
  as lightweight inline markers rather than JSON runs, because the value
  arrives from a CLI argument and an MCP string, where JSON is hostile. A
  marker syntax owes an escape for a literal marker, and templates escaping
  every user value while inserting only lucid's own markup raw is the rule
  that syntax has to survive.
- **What a quote that does not fit does.** The script's `wrap_runs` returns a
  final baseline and `receipt()` throws it away, so the original could overrun
  its own footer and nothing would say so. A flowed slot has a box; the slot
  **refuses** when the flow exceeds it, and names the width and the overflow.
  Growing the card instead is the tempting build and it is wrong for the same
  reason a cue cannot carry a length: the canvas is the project's.

### Build order

0. **The font report's weight** — finding 5's remainder, **shipped
   2026-08-10** ahead of step 1 as it asked to be. It was owed for a
   stronger reason than the finding states: `em` is a *weight* change, not
   only a colour, so emphasis is exactly what a family-only reporter cannot
   see. Three faults, all unsafe-direction, and the mapping is validated
   against renders rather than against `fc-match`. HISTORY.md § The
   emphasis-capable quote slot.
1. **The `runs` slot kind** — **shipped 2026-08-10.** Markers, three levels,
   the `[[` escape, per-run `<tspan>`s; all three inks reproduce finding 1's
   sampled values at L1 0. **The note under-specified one thing and it was a
   silent one**: per-run `<tspan>`s collapse the whitespace between them, so
   `the [em]perfect[/em] horror` draws as `theperfecthorror` at exit 0.
   `xml:space="preserve"`, once per line.
2. **Measured flow** — **shipped 2026-08-10**, with the character-count
   control built and run rather than cited: `WWW MMM` overflows a 1640 box
   by 1054 units where the measurement fits. Two decisions the note left
   open: the scratch canvas is the whole cost of a measurement *and* clips
   silently when it is too small (a clipped line measures narrower, which
   overflows the card), and the box is derived from the canvas rather than
   declared, because the bottom margin moves with the aspect.
3. **Re-author the twelve** — **ten of twelve, 2026-08-10, and the two
   refusals are the finding.** The receipt's header is fixed in template
   units while the canvas is 264 units shorter, so the quote box is 3 lines
   at 2.35:1 against 7 at 16:9, and the two longest reviews flow to 4 and 6.
   Correct rather than broken — before step 2 they overran the card in
   silence — but **it does not close the wiki's card row**, and what to do
   instead is editorial: shorten the verbatim reviews, split them across two
   cards, scale the receipt's header with the canvas, or keep those two at
   16:9 and accept the pillarbox. Done on a copy; the real project's twelve
   are untouched.
4. **Stop.** The cards exist so that the aspect swap's own step 6 — the watch
   of a vertical cut — has graphics in it. Card *animation* is still parked
   behind that watch and this note does not touch it. **This is where the
   item now sits**, alongside the editorial call step 3 raised.

## Per-word caption animation — the design note — 2026-08-10

The last named gap on DAYDREAM.md § Captions: lucid generates and styles
timeline-mapped captions, but the highlight is `\k`'s left-to-right fill and
nothing moves a glyph. The row costs it as two things sharing one construction
question — *"both want one Dialogue event per word rather than one per line,
and both are export questions to cost before building"* — and
`captions.py`'s `Preset` docstring says the same in code: *"a genuine
one-word-at-a-time highlight is a different construction (one Dialogue event
per word) and is not what `to_ass` writes."*

**That construction claim is wrong, and it is wrong in the expensive
direction.** One Dialogue event per word is the build that would force lucid
to own text layout — libass decides where a word sits, and an event carrying
one word has no way to be told where the *other* words put it. Measured
instead: both the single-word highlight and the per-word animation are
per-word `\t` blocks **inside one Dialogue event per line**, which is the
shape `to_ass` already writes. The real cost is somewhere else entirely, and
it is a metrics question.

### Measured on this box, 2026-08-10

libass through ffmpeg 8.1.2 (`--enable-libass`), burned over a flat frame at
1920×1080 and read back per pixel, then reproduced on the real film
(`~/lucid-final-cut/out.mp4`, 1920×816, the caption canvas being the 2541×1080
PlayRes `to_ass` writes). Probes kept at `~/lucid-caption-anim/`.

1. **A single-word highlight is one event, and it is exact.** Per word, a
   block of `{\c<base>\t(on,on+1,\c<hi>)\t(off,off+1,\c<base>)}`. Sampled at
   seven times across a seven-word line, **exactly one word is in the
   highlight colour at every sample and it advances**, against the `\k`
   control on the same words accumulating 1 → 2 → 3 → 4 → 5 → 6 → 7. On the
   real film's first cue the same two constructions read 1,1,1,1,1 and
   2,3,4,6,7. The `\k` finding of HISTORY.md § Caption styling is reproduced
   exactly; what is new is that stepping out of it costs one tag, not a
   rebuild.

2. **Per-word animation is also one event.** `\t` inside a mid-line override
   block animates only the run that follows it, so each word carries its own
   pop. A 130% scale over 120ms on word 3 of 7 rendered at 42px→50px of ink
   height and returned. **No event splitting, no `\pos`, no layout of our
   own.**

3. **What one event per word actually gives you is a different feature.**
   Built to check: with no `\pos` — which lucid cannot compute — every event
   centres itself, so the seven words drew as a single blob at x≈890–1030 at
   every sample. That is **one word alone in the middle of the frame**, which
   is a real caption style and is not "a line with the current word lit". The
   claim on file did not name a harder build of this feature; it named a
   different feature.

4. **The cost is metrics: a scale pop reflows the whole line.** The animatable
   tags split cleanly, measured as the drift of the line's outermost ink
   columns — which belong to the first and last words, neither of them the
   animated one:

   | tag | animates | line drift | |
   |-----|----------|-----------|---|
   | `\fscx`+`\fscy` | yes | **20 px** | reflows |
   | `\fs` | yes | **20 px** | reflows |
   | `\fsp` | yes | **18 px** | reflows |
   | `\fscy` alone | yes | 0 px | metric-neutral |
   | `\frz` | yes | 0 px | metric-neutral |
   | `\bord` · `\shad` · `\blur` · `\be` | yes | 0 px | metric-neutral |
   | `\alpha` · `\c` | yes | 0 px | metric-neutral |

   On the real film the same pop moves both edges of the line 13 px, seven
   times a line, while `\fscy` alone moves them **0 px across every frame of
   the pop**. So a *proper* scale pop and a line that holds still are
   mutually exclusive, and no amount of building changes that — it is what
   text layout is. `\fsp` compensation was tried and is not a way out: at the
   compensation that holds the width, neighbouring words merge.

5. **The trap, and it is the `\k` disagreement again.** The preview overlay
   must draw what libass will, and **CSS's natural pop is metric-neutral
   where ASS's is not** — `transform: scale()` does not affect layout, so the
   obvious browser implementation shows a still line with one word growing
   while the render shows the whole line breathing. Right in the window,
   wrong in the file, no error on either side. Whatever ships, the browser
   half animates the property that *reflows* (`font-size`) if the ASS half
   reflows, and the agreement is settled by reading back a burned frame
   against the page, never by looking at the page.

6. **An artifact worth writing down, because this repo has had it twice
   before.** The first pass of finding 4 reported `\bord`, `\shad` and
   `\blur` as *not animating at all* — zero pixels changed. They animate
   fine; the outline and shadow colours were black and the probe background
   was black. Same shape as the brightness-bbox misreads in CLAUDE.md: a
   black subject reads exactly like an absent one. The fix was a coloured
   outline, and the lesson is that "no effect" and "no contrast" need
   separating before either is believed.

7. **It is not an export cost.** No new dependency, no filter, no second
   pass — the same `-vf ass=` burn. The `.ass` grows about 4× (1.7 KB → 6.6 KB
   over eight cues; ~150 KB for the film's 178), which is nothing, and the
   sidecar stays a plain ASS file Kdenlive opens.

### The design

Two fields on the existing `caption_style` object, both additive and optional,
so **no `SCHEMA_VERSION` bump** — the standing rule in CLAUDE.md, and neither
is a list key another op would `setdefault`.

- **`emphasis`**: `none` | `fill` | `word`. This absorbs the `karaoke`
  boolean rather than sitting beside it, because two knobs for one thing is
  two answers — `karaoke: true` resolves to `fill` and `false` to `none`, the
  alias stays accepted and stays readable in every manifest already on disk,
  and `describe()` reports `emphasis` resolved. `fill` remains what `\k`
  writes, so no existing project changes appearance.
- **`animate`**: `none` | `pop`, plus `animate_ms` and `animate_amount`. Only
  meaningful with `emphasis` set, and refused with `emphasis: none` rather
  than silently ignored, per the standing rule on style fields.

**One derivation, as before.** `Cue.karaoke_spans()` already owns the rule
that a word's highlight begins where the previous one ended, and `as_dict`
already exports `highlight_start`/`highlight_end` — so the `word` mode needs
no new server field at all, and the pop needs only the two style numbers the
overlay already receives resolved. `_dialogue_text` grows a branch per mode
and stays the only place a cue becomes ASS. `\t` times are milliseconds
**relative to the Dialogue line's own start**, i.e. `cue.start`, which is the
one arithmetic detail that is easy to get wrong and silent when wrong.

### The build

1. **`emphasis`, with `word` writing per-word `\t` colour steps.** Style
   field, alias, echo, CLI and MCP parity. The test burns and counts
   highlighted blobs, because a test that asserts on the `.ass` text proves
   the string and not the picture.
2. **The overlay draws `word`**, calibrated against a burned frame the way
   HISTORY.md § Caption styling calibrated the `\k` fill — readback, not
   screenshot.
3. **`animate`**, whichever pop the watch picks, with finding 5's constraint
   binding the browser half.

### The watch happened, and the answer was `fill` — 2026-08-10

**Tyler watched the four treatments and picked 1, the `\k` fill lucid already
writes. So the item closes having built nothing, and the design above is a
record of a road not taken rather than a plan.** The four are kept at
`~/lucid-caption-anim/` (`fill`, `word`, `word` + reflowing scale pop, `word`
+ metric-neutral vertical pop), served by `serve.py` on :8791.

**This is a deliberate divergence from Daydream, not an unbuilt row**, and
DAYDREAM.md § Captions now says so. Daydream lights one word at a time and
moves it; lucid sweeps and does not. The measurement is what makes that a
choice rather than a limitation — findings 1 and 2 say either could ship for
about a day's work, so nobody needs to re-derive the cost to reopen it.

**What would reopen it, stated so the next reader does not re-run the
probes:** a watch that wants the *current word* legible late in a line. That
is the fill's one real cost — by the last word of a seven-word cue every word
is in the highlight colour, so the signal is "how far through the line are
you", not "which word is this". Nothing else about the fill is in question,
and no measurement here is stale: the tag table in finding 4 is a fact about
libass, not about this project.

**What did survive the item.** Finding 5's trap is now on record before
anything could trip it, and it applies to any future caption motion whatever
its shape. Finding 6 is a third instance of a failure this repo keeps having
and is cited from CLAUDE.md's brightness-bbox rule. And `captions.py`'s
comment no longer claims a single-word highlight needs one Dialogue event per
word — the claim was false whether or not lucid ever ships one.
