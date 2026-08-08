# lucid — planning

Working document for architecture and scope decisions. Decisions that have
been made move out of "Open questions" into "Decisions" below, with the
reasoning that settled them.

Competitor and dependency research lives in [PRIOR-ART.md](PRIOR-ART.md); this
file cites its conclusions rather than restating the evidence.

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

### How much of the MVP is left once the box is inventoried — 2026-08-07

Measured, not argued. Everything below was verified installed and working on
this machine the same day the fourth trial criterion was added:

| MVP tool | Already covered by | Left for lucid |
|---|---|---|
| `transcribe`, `get_transcript` | openai-whisper + goodsometimes `scripts/clipcut.py` (in use; it verified the Scream reveals) | packaging. **`transcribe` built 2026-08-07** — `asr.py` already existed for `verify`; the tool was a thin wrapper over it |
| `remove_silences` | auto-editor 31.4.2 | nothing — the plan already said shell out |
| `render` | auto-editor v3 / `melt` | mapping layer, per the render decision |
| `export_otio` | `auto-editor --export kdenlive` lands natively in the only NLE here | **near zero** — this was already "lower urgency than it looks"; the Linux NLE ceiling has now collapsed it. **Superseded by the render spike below — see § The handoff clause is not dead** |
| `add_captions` | — | word-timed ASS, genuinely absent. **Built 2026-08-07** — see § Captions came out of the timeline, not the transcript |
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
> free rather than earned. Evidence in § Render spike below.

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
| `cut_by_transcript` | OTIO, hand-rolled | cut/keep ranges as words or times. OTIO's edit algorithms are C++ only — no Python bindings — so this is track surgery over Track/Clip/Gap and `source_range`, not a library call |
| `remove_silences` | auto-editor subprocess | do not reimplement; auto-editor's `--edit` language (`"(or audio:0.03 motion:0.06)"`, labels, `--margin`) is richer than thresholds-as-parameters |
| `add_captions` | ffmpeg + ASS | word-timed, styled via a small preset set; sidecar `.ass` by default, burn-in opt-in. Built 2026-08-07 — § Captions came out of the timeline, not the transcript |
| `render` | OTIO → auto-editor v3 | a mapping layer, not a renderer — see the render decision below |
| `verify` | openai-whisper + difflib + ffmpeg | not in the original surface. Transcribe the finished render and diff it against the words the timeline should play — the only check that catches a retake the transcript never contained. Added after the dogfood found two of them in a shipped render. Built 2026-08-07 — § `verify` checks the render, because the transcript cannot. `--windowed` (a second reading in short overlapping windows, `asr.py`) and `loud_gaps` (the energy envelope, `energy.py` — the only check that answers to no transcript) followed the same day — § `verify --windowed`, and what the Scream exports actually said |
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
  the transcript never recorded. [DOGFOOD.md](DOGFOOD.md) § 2.
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
  waveform), which validates the idea and removes its uniqueness. An MP4 for the human and a web preview
  (tier 2) are separate questions — don't conflate them.
- **Does the OTIO→v3 mapping hold? Partly answered 2026-08-07.** Single-track
  cut-and-concat maps, in both directions, on real material — that is
  milestones 3–5. What the spike did *not* touch is still exactly what it was:
  transitions, speed changes and multi-layer composites are unverified, and
  they are the ones that could force an architecture change. The current model
  cannot even express them (see `timeline.py`: one track, A/V linked, no gaps),
  so the question is now "what does widening the model cost", not "does v3
  work".
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
  including the MLT details that cost the most time. [DOGFOOD.md](DOGFOOD.md) § 3.

  **And it now has a concrete test case.** Beat 3's Billy/Stu line wants VO
  ducked under a clip's own audio, which breaks the assumption underneath the
  split above — that clips are silent and lucid owns the only audio track. Its
  prerequisite is unbuilt whichever way the call goes: an overlap test between a
  clip's speech and the VO's, both mapped through `Edit.timeline_span`.
  Sequence and what gates it: [ROADMAP.md](ROADMAP.md) § Decision gate.

## Non-goals (write them down so they stay dead)

- Cloud anything. No accounts, no metering, no upload.
- Competing with Resolve/Premiere on finishing. Export to them instead.
- A plugin system before there are two users.

## First milestones

Which of these are done is tracked in the wiki's Open items table, not here.

1. Skeleton: package layout, `lucid mcp` serving a `ping` tool, project
   directory format.
2. **OpenChatCut trial — go/no-go gate.** Install the Linux AppImage, connect
   Claude Code to its MCP endpoint, run the addressable-edit test on a real
   recording (criteria in Open questions). If it passes, archive lucid and
   adopt it; every milestone below exists only if it fails.

   **Ran 2026-08-07 — the gate fails; lucid continues.** Material was the
   Scream essay VO (goodsometimes `ideas/scream.md` § VO), run live against
   v0.1.9 on this box. Verdict per criterion:

   - **1 · Runs on Linux: passes, with friction.** Launches and is stable under
     KDE Wayland. UI defaults to Chinese (`cc.locale` in the app's
     localStorage; a toolbar chip toggles EN). If its port 5199 is held at
     startup it silently falls back to a random port, moving the MCP endpoint.
   - **2 · Addressable edits on a real recording: unanswerable locally —
     transcription is cloud-only.** ASR posts the audio to AssemblyAI and
     without an `ASSEMBLYAI_API_KEY` fails with HTTP 503. The key store has no
     alternative ASR provider (verified in `desktop-dist/main.mjs`; the bundled
     transformers.js whisper models serve other features). The core feature of
     the product does not run without shipping audio to a third-party cloud —
     directly against the local-first premise lucid exists for.
   - **3 · Electron-as-MCP-host in an agent workflow: heavy friction,
     measured.** MCP endpoint is `http://127.0.0.1:5199/api/external-mcp/mcp`
     (streamable HTTP) and works from the CLI, but: the GUI must be running
     with the project open in an editor before the 100+ editor tools even
     register; every project-touching tool's *first call per session* throws a
     manual confirmation card with no "always allow"; and the transport goes
     stale after an import, forcing a full re-init — new session, new edit
     session, and all confirmations again. Three human approval clicks were
     spent before reaching a single edit.
   - **4 · Does the edit get out: fails, verified from the tool itself.**
     `submit_export` emits flattened media (MP4/WebM/MP3/WAV), subtitles, or
     FCPXML "for Premiere / Resolve / FCP" — no MLT, no OTIO. Nothing on this
     box opens FCPXML (Premiere gone, free Resolve decodes no H.264/AAC, no
     Mac), so the timeline is trapped inside the app unless the video is
     finished there.

   The gate required all four to pass; 4 fails outright and 2 cannot pass
   locally. What OpenChatCut is *right* about is worth stealing: draft/review
   edit sessions with explicit approval, transcript-as-address-space tooling,
   and typed structured tool returns. The trial project ("Scream VO trial",
   with the VO uploaded and its media copy in the app's storage) is left in
   place for reference.
3. **Render spike.** Hand-write a two-cut `project.otio`, map it to auto-editor
   v3, render it, verify the output. No transcription involved. This is ahead of
   transcribe deliberately: `transcribe` is a well-trodden path that will work,
   whereas the timeline→pixels path is the one unproven assumption the whole
   architecture rests on, and it is cheaper to falsify now than after three
   tools have been shaped around it.

   **Ran 2026-08-07 — the assumption holds, and it buys more than expected.**
   A hand-written two-cut v3 against a synthetic clip:

   - `auto-editor cut.v3 -o out.mp4` renders 4.000s exactly, and the frame at
     output 2.5s is source 5.5s — offsets are honoured, not just durations.
   - `auto-editor cut.v3 --export kdenlive` writes MLT with `in=0.000
     out=1.967` and `in=5.000 out=6.967` as separate entries on linked
     video *and* audio chains.
   - Audio-only sources work the same way (`"v": []`), which is what the essay
     VO needs.

   Two consequences the plan did not anticipate. First, **the NLE handoff is
   free** — see the correction in § How much of the MVP is left. Second, v3
   accepts a **millisecond timebase** (`1000/1`), so audio cuts are not stuck
   on a 33ms frame grid; auto-editor picks 30/1 for a wav but honours a finer
   one on input.
4. `import_media` + `transcribe` + `get_transcript` on a real clip — which is
   also what answers the word-timestamp and VFR questions with measurements
   instead of guesses.
5. `cut_by_transcript` + `render` — the first end-to-end "cut this sentence out"
   from a Claude Code session. Includes timeline snapshotting.
6. `remove_silences` (shell out), `add_captions` (word-timed ASS), `export_otio`.
7. Dogfood on a real recording; promote pain points to the plan.

   **Ran 2026-08-07 — lucid cut the goodsometimes Scream essay's VO**, eight
   retakes across 5:10.9, and the video was rendered and verified around it.
   The core thesis held under the test that mattered: two retakes found *after*
   the picture was built cost two commands and one re-run, because every cue
   was addressed by source word index. Findings and the four things worth
   building next are in [DOGFOOD.md](DOGFOOD.md).

## What the first vertical slice changed — 2026-08-07

Milestones 4 and 5 were built together against the Scream essay VO rather than
a fixture, and `render` was deliberately skipped: the video needs a `.kdenlive`
to finish in, not an MP4. Three things only the real material exposed.

- **A whisper transcript is an input, not something to regenerate.** The VO was
  transcribed before lucid existed. `attach_transcript` ingests an existing
  word-timed JSON; re-running ASR to obtain an index that already exists is
  wasted GPU time and a second set of timings to disagree with. `transcribe`
  is still wanted for material that has none, but it is no longer on the
  critical path.
- **Importing media cannot assume it can link.** The NAS rejects `symlink()`
  outright (wiki `files.md`), and that is where all the media lives. Copying
  instead would duplicate gigabytes to route around a filesystem limitation, so
  import degrades to referencing the file in place and records which of
  symlink/copy/reference happened. The resulting convention is in CLAUDE.md.
- **The export timebase and the internal timebase are not the same thing, and
  conflating them is a real bug.** The v3 `timebase` becomes MLT's
  `<profile frame_rate_num>`, so exporting an audio project at its millisecond
  rate handed Kdenlive a **1000fps** timeline. Media renders keep milliseconds;
  NLE exports quantise to a frame rate — the picture's, or 30. This is what
  "normalise only when exporting to an NLE" in § Open questions actually means
  in practice.

### The slice, measured on the Scream VO

Project at `Videos/Every Scream Sequel…/Project/lucid-vo/`; the whole run is
eight `lucid` commands.

| Step | Result |
|---|---|
| `import` + `attach-transcript` | 385.8s of VO, 929 words |
| `seed --threshold 0.04` | **62 segments, 5:35 kept from 6:25** |
| `cut … --pad 0.1` (6 retakes) | 19.0s removed → 68 segments, 5:16.9 |
| `export … .kdenlive` | 68 MLT entries at 30fps |

The seed number is the cross-check that matters: goodsometimes `scream.md`
independently records auto-editor at 0.04 producing "62 segments, 5:34 kept
from 6:26" when run natively. lucid's v3 → OTIO import reproduces it exactly,
so the round trip is not lossy.

Verification was **re-transcription of the render**, not inspection of the
timeline — whisper over the rendered result, then 13 assertions about which
phrases survived. All six abandoned takes are absent, all six keepers intact,
and the two retakes deliberately left alone are still present twice. Render
duration matches the timeline to the millisecond (316.901s). `melt` parses the
`.kdenlive` and renders audio from it.

Two of the eight retakes in `scream.md` were **not** applied, because that
file marks them as judgement calls rather than mechanical fixes: the
"Fine, let's test it." / "Fine, test it." pair (recorded as Tyler's call) and
the stray "it" at 5:05 ("micro-trim or leave"). Both are one `lucid cut` away.

The word-index model that fell out of this is worth stating, because every
tool depends on it: **the transcript indexes the source, never the timeline.**
Word 412 means the same audio however many cuts have accumulated, indices never
renumber, and a range that has been cut is reported as absent rather than
silently pointing somewhere else. That is what makes ranges stay addressable
across a session, and it is the whole content of "addressable ranges over an
accumulating edit."

## Captions came out of the timeline, not the transcript — 2026-08-07

`add_captions` is built — the last MVP tool the inventory table above did not
collapse into auto-editor, and the first that had to reconcile the two clocks
lucid keeps.

- **A transcript indexes the source; a caption fires on the timeline.** Every
  other tool so far reads source time and writes source time, so the
  distinction never had to be resolved. A caption cannot dodge it: word 412's
  timings are coordinates in the original recording, and by the time captions
  are wanted the timeline is 68 segments of accumulated cuts. So words are
  mapped through the edit and a cut word is simply not captioned. This is why
  captions are generated from the *project* and not from the whisper JSON — the
  JSON alone cannot know what was removed.
- **The mapping needed one new primitive**, `Edit.timeline_span`, which is
  `timeline_time` over an interval rather than an instant. It reports the part
  of a source interval that survives, so a word straddling a cut is truncated
  rather than stretched over material that is gone.
- **Grouping is measured in timeline time, and that is a decision, not an
  implementation detail.** Two words seconds apart in the recording but adjacent
  after a cut belong to one caption, because that is how they now play.
- **ASS rather than SRT, for a reason that only shows up at word level.** `\k`
  karaoke tags are the only way any subtitle format expresses per-word timing
  *within* a displayed line. Without them "word-timed" degrades to line-timed
  with word-derived boundaries.
- **`PlayResX/Y` is a reference canvas, not an output resolution.** Writing the
  media's real dimensions there — which is the obvious thing to do, and what
  the first version did — makes a 64pt caption fill a 240-line clip and vanish
  on a 4K one. Height is now pinned at 1080 and width follows the aspect ratio,
  because libass scales the axes independently and a 16:9 reference over
  vertical footage stretches the glyphs. Caught by looking at a burned frame;
  the tests were green.

### Measured on the Scream VO

Run against the same `Project/lucid-vo/` the slice built, at 68 segments and
5:16.9:

| | |
|---|---|
| Words in the transcript | 929 |
| Captioned | 864, in 156 cues |
| Dropped as cut | **65** |

65 is the cross-check. `scream.md`'s retake table cuts word ranges 91–98,
111–114, 284–307, 335–345, 390–394 and 545–557 — which is 65 words exactly, so
the caption pass dropped precisely what the edit removed and nothing else. The
phrase-level check agrees: "entire film", "unmask anybody" and "generally
great" are absent, their keepers "entire movie", "unmask somebody" and
"genuinely" are present, "You can't lift it out" appears once, and the retake
left uncut still appears twice. Last cue ends at 316.53s inside a 316.901s
timeline, no cues overlap.

**The Scream video does not need this.** Captions appear nowhere in
goodsometimes `pipeline.md` — the house format is film clips and graphics under
VO. `add_captions` closes the MVP surface; it is not on that video's path.

## `verify` checks the render, because the transcript cannot — 2026-08-07

[DOGFOOD.md](DOGFOOD.md) § 1's top-ranked item. Two retakes reached the first
full render of the Scream video, and *nothing lucid could read would have found
them*: inspecting `project.otio` proves the cuts you made are the cuts you
meant, and those two were never cut at all. `lucid verify <render>` transcribes
the finished render and diffs that word sequence against the one the timeline
should play.

- **It is a check on word *order*, and that is forced, not chosen.** Timings
  cannot detect this defect — whisper hides a whole retake inside the duration
  of the following word (§ 2), so the source transcript agrees with the script
  and reports nothing wrong. What does not lie is that the render's own
  transcript contains the phrase twice while the timeline expects it once.
- **The expected side is `captions.place`, unchanged.** "Which words survive,
  and when do they play" is one question, and captions had already answered it.
  So verify is a diff bolted onto an existing mapping rather than a second
  model of the edit — which also means it inherits the overlap-not-containment
  rule for free, and cannot drift away from what captions believe.
- **Similarity is triage; the diff is the artifact.** Whisper spells its own
  output differently on a second pass, so a clean render scores ~0.97 rather
  than 1.0 and a threshold would be a coin flip. `repeated` and `dropped` are
  heuristics *over* the diff — a heard run of ≥2 words that also appears in the
  expected sequence is a phrase played twice; the mirror case is a cut that
  reached too far. Both are best-effort, and both are named that way in the
  tool docstring so an agent does not treat an empty `repeated` as a pass.
- **The heard transcript is cached and never automatically reused.** It costs
  minutes of GPU to produce, so it is written to `cache/verify/<render>.json`
  and reported back. It is not read on the next run: a re-render under the same
  filename would then verify against the previous render's audio and pass.
  Reuse is explicit, via `--transcript`.
- **ASR became its own module, `asr.py`, with no lucid imports.** Whisper is a
  subprocess, not a library — importing it would pull torch and a GPU context
  into `lucid status`. It is also **not on PATH on this box**; resolution is
  `LUCID_WHISPER` → PATH → the openai-whisper in vaultmedia's `.venv-tag`. That
  leaves the MVP's own `transcribe` tool as a wrapper over a module that
  already exists.

### Measured 2026-08-07 — on synthesised speech, not the Scream VO

Stated plainly because it matters for how much this is worth: the Scream
project is no longer on this box, so the run below is espeak-ng speech, not
human speech. Everything *around* the comparison is real — real whisper
(`small`) on both sides, a real `auto-editor` render of a real lucid edit.

A 24-word read with one line spoken twice. Cutting words 12–15 removes the
second take, leaving a 20-word timeline:

| Render verified | Expected / heard | Similarity | `repeated` |
|---|---|---|---|
| the actual render of the edit | 20 / 20 | **1.0**, empty diff | none |
| the uncut recording | 20 / **24** | 0.909 | `"nobody believes her yet"` @ heard word 12 |

The second row is the Scream defect reproduced and caught. `render_duration`
came back 9.158957s against a 9.159s timeline, which is the same
millisecond-level agreement the first vertical slice measured.

Two honest limits. The 1.0 in row one is *better* than real material will give
— synthesised speech transcribes identically twice, where a human read scores
~0.97 — so do not tighten anything to expect it. And whisper did **not** fold
the doubled line into the previous word here, as it did on the real VO; this
run proves verify catches a surviving retake, not that it reproduces the
transcript infidelity that creates one.

**One thing only the real run found.** Whisper returns an empty `segments` list
rather than failing when it hears no speech, and `transcript.parse_whisper`
then blames missing word timestamps — advice to pass `--word_timestamps True`,
which `asr.transcribe` always passes. `verify` checks for that case first and
says what actually happened: the render has no dialogue on it, so check the
export kept the audio track.

## `verify --windowed`, and what the Scream exports actually said — 2026-08-07

[ROADMAP.md](ROADMAP.md) § 1. Run against the real material this time: the v1
timeline rebuilt in lucid from `VO.json` and the recorded cut list, which lands
on 67 segments and 312.175 s against the 67 and 5:10.9 in goodsometimes, with
the two padded cuts removing exactly the −3.06 s and −1.333 s recorded there.
Then the shipping v1 and v3 exports verified against that one timeline, each
both ways.

| Run | Windows | Heard | Similarity | `repeated` | Suspect durations | `loud_gaps` | Wall |
|---|---|---|---|---|---|---|---|
| v1 single-pass | — | 876 | 0.969 | 2 | **46** | 0 | 19.9 s |
| v1 windowed | 62 | 883 | 0.976 | 3 | **10** | 1 | 39.0 s |
| v3 single-pass | — | 855 | 0.971 | 0 | **50** | 1 | 19.5 s |
| v3 windowed | 60 | 859 | 0.973 | 0 | **10** | 2 | 33.1 s |

**Windowing's benefit is not the one the item claimed, and it is measurable.**
It did not find a retake a single pass had missed. What it did was cut words
with implausible durations from 46 to 10 and 50 to 10 — the collapse mechanism
itself, suppressed about five-fold, because a ten-second segment has nowhere to
put a 3.96-second word. That is the same quantity ROADMAP § 2 wants flagged, so
the two items turn out to be one observation seen from either end.

**What actually surfaced the retakes was the diff, not the transcription.**
Both passes already *contained* both catchable retakes; `repeated` reported one
of them, because it required the extra run to appear in the expected sequence
verbatim. Two takes of a line are never verbatim — that is how you tell them
apart, and the notes call the wrong preposition the tell. Scoring the run
against its best-aligned window instead took v1 from one detection to two on
the *same* transcript. The threshold is 0.5 and that is not slack: the second
take is transcribed worse than the first, and "Scream 4" came back as "screen
4", which alone took the run to 0.556.

**The third retake was never a `verify` miss.** `VO.json` records both takes of
"I don't think that['s / it's] a coincidence" at words 621 and 627. The
timeline expects both because nothing cut them, the render plays both, and
`verify` is right to report no discrepancy — its question is whether the render
says what you edited. Catching that one means comparing the source transcript
against *itself* for adjacent near-duplicate phrases, at attach time. Different
check, now ROADMAP § 3.

### Three failure modes the real material found, none of them theoretical

- **Overlap 3 s loses words in the middle of a file.** The ported method's
  numbers were measured on the VO; a render is harder. At 10 s / 3 s the
  windows only share 3 s in every 7, so 57% of a file sits inside exactly one
  window and a word that window missed is gone — `_reconcile` has no second
  reading to fall back on. On the scored v3 export that dropped 22 words
  mid-sentence ("three different movies, 12 years apart…"); re-admitting
  discarded copies recovered 14, and the remaining 8 were in single-covered
  territory. **The default overlap is now half the window**, which makes
  coverage uniformly two: 859 words against 847, similarity 0.973 against
  0.963, and the hole closed. Pass `--overlap 3` for the original method.
- **Short windows make whisper's repetition loop *more* likely.** One window of
  v1 emitted sixteen words all stamped `229.98 → 229.98` — a verbatim copy of
  an earlier phrase spliced mid-sentence — and `verify` dutifully reported a
  retake that is not in the audio. Zero-length words are the entire signature
  and cost nothing to lose, so a stack of three or more on one instant is
  dropped and counted as `hallucinated_words`.
- **The windowed pass is not reproducible.** Two runs over identical inputs
  gave 883 and 898 heard words. Treat a windowed count as approximate; it is
  the sequence that is being read, not the total.

### The energy envelope is the only part that answers to no transcript

`energy.py`, reported as `loud_gaps` by both passes. Mask the render's audio
with the words that were heard and measure what is left in the holes; the
threshold calibrates off the file, halfway in dB between its quiet tenth and
the median level inside a word, because a VO stem and a scored render sit 20 dB
apart.

Two things make it work rather than merely run:

- **Word durations are not believed when building the mask.** This is the
  whole point and it is easy to get backwards. A collapsed retake does not
  leave a gap in the transcript — it inflates the following word until that
  word's claimed span *covers* the second take. Masking by the claimed span
  therefore masks the evidence. Each span is trimmed to 3x the median word
  duration first, the same multiple ROADMAP § 2 flags at.
- **It caught the windowed pass's own failure.** The 22 missing words on v3
  showed up as 58.98–63.0 s holding 2.64 s of sound at −10.2 dB peak — the same
  shape as the 4.12 s hole holding 2.4 s of speech in the goodsometimes notes,
  and invisible to any transcript-versus-transcript comparison, because both
  sides agreed that stretch was silent.

A music bed raises the quiet end rather than defeating the check, which is what
the self-calibration is for — but the bed is not flat, and a swell in a long
pause can still clear the midpoint. Both v3 runs report one or two gaps around
0.5 s of sound at roughly −19 dB, which is where the seven attenuated noises
live. An entry is somewhere to listen, never a verdict.

## Adjacent near-duplicate phrases at `attach-transcript` — 2026-08-07

ROADMAP item 1, built and run against the real `VO/VO.json` (929 words), not
just synthesised fixtures. `verify.find_adjacent_repeats` scores every 4-word
window against the next 40 words with `_closest_run`, then keeps only the
highest-scoring, non-overlapping candidates — needed because a real repeat
scores well from several neighbouring offsets at once, and without that step
one restart became six near-identical rows.

**929 words in, 30 candidates out, and the target is among them.** Words
621/627 — "I don't think that['s / it's] a coincidence," the retake `verify`
structurally cannot catch — is reported (`614→621`, similarity 0.75). So is
every other self-comparison-shaped retake `ideas/scream.md`'s own trim table
already names by hand: "any one of them" (91), "here's the thing I" (111),
"entire film"/"entire movie" (284–307, the longest, five overlapping windows),
"You can't lift it out." (335–345), "unmask anybody/somebody" (390), "generally
great" → "genuinely great" (545–557), "Fine, let's test it." / "Fine, test it."
(662–668), and the deliberately-kept stray "it" at 725. Roughly a third of the
30 (ratio-0.5 pairs sharing only connector words) are noise, in line with the
item's own "reader's job, not the tool's" design.

**What it correctly does not catch: words 442–445 and 887–889.** Both retakes
survived v1 by a different mechanism — whisper swallowed the second take's
words into the *following* word's duration rather than transcribing them, so
there is no second run of tokens for a token-sequence comparison to find.
That is suspect-duration flagging's defect, not this one's (§ below);
`ideas/scream.md`'s own notes on those two say so directly ("the whisper diff
could not have found the missing two").

## Suspect word durations at `attach-transcript` — 2026-08-07

ROADMAP item 1, built and run against the real `VO/VO.json` (929 words).
`energy.suspect_durations` is `believable`'s existing 3x-median cutoff, given a
second caller — no new measurement, just a name for one that already existed.

**13 of 929 words flagged, and both retakes the near-duplicate check above
cannot catch are among them.** Words 442–445 and 887–889 survived v1 because
whisper swallowed each retake into the *following* word's duration instead of
transcribing it. That following word is exactly what gets flagged: index 446
("wants", 2.22 s) and index 890 ("not", 2.02 s), both against a 0.78 s limit
(3x this transcript's 0.26 s median). `cut_by_transcript` now refuses either as
a cut boundary without `confirm_suspect=True`.

**Corrects an example carried since the `verify --windowed` table above: the
3.96 s "bit" is not a `VO.json` word.** It comes from re-transcribing the
*rendered* v1 export — a different pass over different audio — where it was
one of the single-pass run's 46 suspect durations. In `VO.json` itself "bit" is
an ordinary 0.16 s word; the span actually hiding the "falls apart a bit in the
second half" hole DOGFOOD documents is index 137, "in", at 4.26 s. 446 and 890
are the words this item's own done-when criterion can be checked against.
