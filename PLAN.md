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
| `cut_by_transcript` | OTIO, hand-rolled | cut/keep ranges as words or times. OTIO's edit algorithms are C++ only — no Python bindings — so this is track surgery over Track/Clip/Gap and `source_range`, not a library call. Echoes the words each index resolved to and takes `plan=True` to resolve without writing — § `cut --plan` |
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
  waveform), which validates the idea and removes its uniqueness. An MP4 for
  the human and a web preview (tier 2, built — § The preview/timeline web UI)
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
  the cost of changing it is measured in § The multi-track costing spike. What
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
  including the MLT details that cost the most time. [DOGFOOD.md](DOGFOOD.md) § 3.

  **And it has a concrete test case, whose prerequisite now exists.** Beat 3's
  Billy/Stu line wants VO ducked under a clip's own audio, which breaks the
  assumption underneath the split above — that clips are silent and lucid owns
  the only audio track. `speech_overlap` is the overlap test that call needed
  either way. What is left is not the model — § The multi-track costing spike
  prices that, and it is cheap — but getting a multi-*source* timeline out of
  auto-editor at all. Sequence and what gates it:
  [ROADMAP.md](ROADMAP.md) § Decision gate.

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

## `cut --plan`, and echoing what a word index resolved to — 2026-08-07

ROADMAP item 1, built and run against the real `VO/VO.json`. Three parts, and
the smallest of them turned out to carry the item.

**`plan=True` runs the same code path and skips the write.** The edit is loaded,
mutated in memory, and simply never saved — no snapshot, no `project.otio`
write. So `duration_after`, `removed`, `segments` and `segments_touched` are the
real numbers rather than a second implementation's prediction of them; the
stdio test asserts a plan and the cut that follows it agree exactly. This
replaces the cut-read-undo loop, which for an agent costs a full turn per undo
and leaves snapshots behind for an edit that was never wanted.

**Every range echoes the words either side of it, and that is the part that
works.** Resolved text alone cannot show an off-by-one — "the words I meant,
plus one" reads perfectly well on its own, which is why six Scream cues shipped
with it. Live, planning `cut vo 111:114 --pad 0.1`:

| field | value |
|---|---|
| `text` | `Here's the thing I,` |
| `context_before` | 108 `a`, 109 `3`, 110 `.5.` |
| `context_after` | 115 `here's`, 116 `the`, 117 `thing` |

The restart is sitting in `context_after`. The range is correct — it takes the
abandoned "Here's the thing I," and leaves the real one — but *nothing in the
resolved text says so*, and a range ending at 117 instead of 114 would read
just as well. Three words of context is what makes the two distinguishable.

**`pad` is in seconds and the echoed text is not**, so a padded cut can eat a
neighbour the words never mention. `pad_reach` names any word the padded span
overlaps from outside the range, `side`-labelled. Overlap, never containment
(CLAUDE.md) — a neighbour half-swallowed by the padding is precisely the case
worth reporting, and containment would report neither of the two the unit test
covers. `word_start`/`word_end` now ship alongside `source_start`/`source_end`
so the padding's effect is readable rather than inferred.

**Planning reports suspect boundaries instead of refusing them.** The refusal
added above tells the caller to go and check the word; refusing to let them
look would be circular. Under `plan=True` the same hits come back as
`suspect_boundaries` with the range that triggered each. Verified live on word
446: `cut vo 446:450` still refuses with the full message, `--plan` on the same
range returns the finding and touches nothing.

One thing this did *not* change, and it is correct: the suspect check reads
only a range's first and last word. Planning `444:448` reports no suspect
boundary even though interior word 446 is flagged, because 446 is not what the
cut edge resolves to. Interior words are removed wholesale; only the edges
carry the risk.

## `check_frames`, the picture half of checking a render — 2026-08-07

[ROADMAP.md](ROADMAP.md) § Picture-side render checks, of whose three parts
this is the one it names load-bearing. `verify` covers the audio and says so;
this counts frames. `blackdetect` and spot frames are still owed.

`lucid frames [TARGET]` / `check_frames`. With no target it reports
`expected_frames`, the total the timeline lays down. With one it compares:

- an NLE project (`.kdenlive`/`.mlt`/`.xml`) goes to `melt -consumer xml`,
  which resolves the document and prints what it *would* render without
  encoding anything;
- anything else is a render, counted with ffprobe.

**The check runs before the render, and that is the whole point.** Exact
agreement with `melt`'s count is what made 68 cut positions on the Scream essay
trustworthy before pixels existed (DOGFOOD.md § 3), and reading a document
costs seconds where rendering costs minutes.

**`expected_frames` comes from the export's own arithmetic, not from the
duration.** `autoeditor.frame_layout` was factored out of `to_v3` rather than
restated beside it, so the number a check reports and the number an export
writes cannot become two. It matters because each segment edge is quantised on
its own: two 0.017s segments at 30fps are half a frame each, become one frame
each, and make a 2-frame timeline that `round(0.034 * 30)` calls 1. The
exported timeline is the honest answer and only the per-segment path has it.

### auto-editor's kdenlive export is one frame long, and the frame is black

Measured here, not reasoned about. auto-editor 31.x, MLT 7.40, Kdenlive
26.04.3:

| Timeline | lucid | `melt` `length` | rendered |
|---|---|---|---|
| 12.0s uncut, 30fps | 360 | **361** | **361** |
| the same, cut to 9.2s | 276 | **277** | — |
| 10.0s audio-only | 300 | **301** | — |
| 12.0s via `export --render` | 360 | — | **360** |

The extra frame is real: frame 360 of the melt render measured YAVG 16 against
~123 for the three before it. The cause is the shape goodsometimes
`pipeline.md` § Rendering documents from the other side — MLT's `out` is
frame-*inclusive*, and auto-editor writes the tractors' `out` as the frame
*count*. The clip entries are right (`out="00:00:11.967"` is frame 359,
correct for 360 frames); the three tractors declaring `00:00:12.000` are not,
and melt renders to the longest declared length.

It is **reported, not corrected**. `agrees` stays False and nothing is
subtracted, because the frame is genuinely in the render; a `notes` entry names
the cause so it reads as upstream's defect rather than a wrong cut. The last
row is why that is the right call: auto-editor's own renderer does not have it,
so this is the NLE handoff specifically. `picture.KNOWN_TAIL_FRAME` holds the
measurement.

The stdio test pins the *reporting* rather than the +1 — a delta of 0 there
would mean auto-editor had fixed it, and what must stay true either way is that
the note travels with the delta it explains.

### Two things the real run found that a fixture would not have

**`melt` is not a host package and its flatpak cannot see `/tmp`.** It lives
inside `org.kde.kdenlive`, so `picture.melt_command()` resolves `LUCID_MELT` →
PATH → flatpak, the same ladder `asr.py` and `autoeditor.py` use. Then, pointed
at a project under `/tmp`, it printed `Failed to load` and **exited 0** — the
third of DOGFOOD.md § 4's traps, met from a new direction. The empty-output
guard caught it, and the error now names the trap when the path is under `/tmp`
and melt is the flatpak. The melt test needs its own fixture under `$HOME` for
the same reason: on `tmp_path` it would have quietly stopped testing melt and
started testing the guard.

**An audio-only render has no frames, and that is not a failed check.** It is
the ordinary case for a VO project. `agrees` comes back null rather than false —
nothing disagreed, there was simply nothing with frames in it — with a note
pointing at the NLE project as the thing to count instead.

`media.count_frames` counts packets (`-count_packets`) rather than trusting the
container's `nb_frames`, which is a header a muxer can write wrong, and returns
both so a disagreement between two ffprobe readings of one file is reported
rather than resolved silently.

## `cut_by_time`, cuts addressed by what an export played — 2026-08-08

[ROADMAP.md](ROADMAP.md) § Accept cuts in render time — and its mirror,
added time. Closes the first half of that item: a human watching an export
reports a flub at the timestamp they saw, not a source word index, and
`cut_by_time` (CLI `cut-at`) takes it exactly that way. The mirror — added
time — is not built; see below for why.

- **`Edit.source_spans` is the timeline→source inverse `timeline_span` was
  missing.** `timeline_span` walks source time to timeline time for one clip;
  `source_spans` walks the other direction, across however many segments (and,
  once the model is multi-clip, clips) a `[start, end)` render-time span
  touches, in playback order. Past-the-end is refused rather than clamped —
  unlike `pad`'s deliberate overreach, a timestamp naming material that was
  never on the timeline at all is almost certainly a mistake worth stopping
  on, not silently trimming to fit.
- **All spans in one call resolve against the timeline as it stood before any
  of them was applied.** A list of notes taken against one watch stays valid
  together even though a real cut would shift every later timestamp by the
  time it removed. Overlapping spans in the same call are refused rather than
  silently double-applied.
- **`pad` widens only the two true outer edges of a span**, never an inner
  seam a multi-piece span happened to cross. Padding an inner seam would reach
  toward whatever now sits on the far side of a prior cut — material the
  caller never named.
- **`requested_removed == removed` is asserted, not just reported, when
  `pad == 0.0`.** `source_spans` and `Edit.remove` are two independent walks
  over the same segments; a mismatch between what was asked for and what
  actually shrank means the two disagree with each other, which the code
  calls "unreachable" and raises on rather than returning a wrong number.
  `pad` widens the request on purpose, so the invariant only holds where
  nothing was added.
- **The word echo reuses `cut_by_transcript`'s own convention rather than
  inventing a second one.** Every piece a span produced echoes the words it
  overlaps — overlap, never containment — plus `context_before`/
  `context_after` either side, and a span landing entirely in silence still
  gets its nearest flanking words so there is always something to check the
  timestamp against. Suspect boundaries (PLAN.md § Suspect word durations)
  are refused the same way, with the same `confirm_suspect`/`plan` escape
  hatches `cut --plan` established.
- **A clip with no transcript still gets cut.** `words_overlapped` comes back
  null and `transcript_missing` is set instead of refusing a valid
  render-time cut just because a picture-only clip was never transcribed.

### Measured on the Scream VO

Timeline segment 33.500–36.933s ("I have never given one of them more than a
3.5.") cut by watch-note timestamp, not word index:

| `cut-at 33.9+2.9 --plan` | value |
|---|---|
| requested (timeline time) | 33.9 → 36.8 |
| resolved | 1 piece, source 38.433–41.333 |
| `words_overlapped` | idx 100–110, "have never given one of them more than a 3 .5." |
| `context_before` / `context_after` | idx 97–99 "of them, I" / idx 111–113 "Here's the thing" |
| `requested_removed` vs `removed` | 2.8999999999999986 vs 2.8999999999999773 — float precision only |
| `duration_before` → `duration_after` | 335.901 → 333.001, segments 62 → 63 |
| determinism | two identical `--plan` calls, byte-identical output |
| past-the-end | `cut-at 500+10 --plan` → exit 1, "interval 500.000-510.000 is outside the timeline (0.000-335.901) — it names material that is not on the timeline at all" |

The only word lost against the intended phrase is the leading "I" — the
requested span started 0.013s after its onset, a clean boundary trim rather
than a wrong range. All runs used `--plan`; `lucid status` afterward still
showed the live timeline untouched.

### The `vo_extend` mirror is a deliberate non-goal, for now

`vo_extend.py` in goodsometimes appends real tail time the same way
`vo_trim.py` removes it. Two constraints any lucid timeline mutation inherits
once it does the same:

- the added time must be a real MLT `silence` producer entry, **not** a
  `<blank>` — a cue table addressed by word index cannot see a blank, so a
  `<blank>` silently adds runtime every downstream cue is blind to;
- four declared-length spots have to be swept in step — both tractors' `out`,
  the sequence track's `out`, `producer0`'s length.

Neither is coded here, and the reason is structural rather than an oversight:
**lucid never writes MLT.** It shells out to `auto-editor --export kdenlive`
and auto-editor owns the XML, so `export` regenerates a timeline rather than
mutating one in place. The day lucid mutates an MLT project directly instead
of regenerating it, it owns both constraints above — until then they are
documented so they are not rediscovered as a surprise, not implemented.

## `check_black` and `spot_frames`, the rest of the picture-side checks — 2026-08-08

[ROADMAP.md](ROADMAP.md) § Picture-side render checks — the rest of them.
`check_frames` (PLAN.md § `check_frames`) is the load-bearing third of this
item, run before a render exists; these two read a render that already does.

- **`KNOWN_TAIL_FRAME` reasoning is broadened from NLE projects to bare
  renders, deliberately.** `check_frames` only ever compares the constant
  against an NLE-project target, because a `melt -consumer xml` read is the
  only place the tail frame shows up before anything renders. `check_black`
  extends the same reasoning to a finished file: the trailing frame that
  defect produces is actually encoded, not just declared in the project XML,
  so it can equally turn up after rendering. A run is `explained` only when
  it sits at the tail *and* the frame delta between the target and the
  timeline equals `picture.KNOWN_TAIL_FRAME` exactly — position has to match
  the known defect, not just the count, so a run sitting inside the declared
  picture is never waved away regardless of delta.
- **blackdetect's EOF runs report `duration: 0`, measured against the
  installed ffmpeg (8.1.2), not assumed.** `blackdetect` derives a run's
  reported duration from the *next* frame's timestamp; a black run that
  reaches end of stream has no next frame, so it reports zero regardless of
  how many black frames it actually holds. That is exactly the trailing
  kdenlive-export frame this tool exists to explain, so `min_duration`
  defaults to **0**, not the half-frame grid the rest of this module
  measures against — a positive default would read as "half a frame of
  slack" and silently drop the one event the check is for. Every other run's
  duration is a real multiple of the frame interval, never a fraction of
  one, so nothing spurious gets in at 0 that would not already pass at
  half a frame.
- **`signalstats` is parsed from ffmpeg's stderr, not stdout — measured, not
  assumed.** `extract_frame`'s `-vf signalstats,metadata=print` writes
  through the ordinary log, which ffmpeg sends to stderr; `parse_signalstats`
  is written against that, and the function's own parameter is named
  `output`, not `stdout`, because of it.
- **PNGs land in `cache/frames/<render-stem>/`.** `spot_frames` samples
  `count` evenly-spaced frames (midpoint-sampled, so a sample never lands
  exactly on frame 0 or the last one) plus any explicit `--at` times, each
  extracted with `picture.extract_frame` and ranked darkest-first by `YAVG`.
- **Word/clip mapping only fires when the render's probed duration agrees
  with the current timeline within a frame (`mapping_trusted`).** A stale
  render silently mapping to the wrong words would be worse than no mapping
  at all; when it is not trusted, every frame still gets its PNG and stats,
  only `clip_id`/`source_time`/`word` are withheld. The adversarial review
  caught this comparing against `edit.duration` — the unquantised sum of
  segment durations — instead of `expected_duration`, the same
  `frame_layout` quantisation gap CLAUDE.md already warns about for
  `check_frames`. A multi-dozen-cut export could disagree with `edit.duration`
  by more than a frame while matching `expected_duration` exactly, marking a
  perfectly fresh render as untrustworthy. Fixed to compare against
  `expected_duration`, already computed one line above for the frame-count
  gate, so the two checks cannot drift apart on this point either.

### Measured on the Scream VO

`Exports/Video Final v5.mp4`, 314.112s, 9423 frames, `check_frames` agreeing
exactly (`delta: 0`) — so nothing here is explainable by the known tail-frame
defect, and the tool has to get that right rather than wave the finding away.

| `lucid black`, `pix_th` | `clean` | run |
|---|---|---|
| 0.10 (default) | false | 302.300–314.067s, duration 11.767s, inside picture, `explained: false` |
| 0.05 | false | 314.067–314.067s, duration 0.0s, inside picture, `explained: false` |

Both runs are correctly *not* auto-explained: `delta` is 0 and the run sits
inside the declared picture, not past it, so the tool refuses to file a real
11.8-second static outro card under the auto-editor tail-frame defect. Reading
the frame confirms it by eye — `cache/frames/…/00_305.000s.png` is a dark
"movies are good sometimes" subscribe card, held static to the end.

| `lucid spots` (default 6) | time | YAVG |
|---|---|---|
| darkest | 235.584s | 24.887 (real dark movie still, low-key horror lighting) |
| brightest | 26.176s | 223.748 (a Letterboxd-style review card) |

Five explicit outro samples (305, 308, 310, 313, 313.9s) all read
**YAVG 38.1592 to four decimals** — the same static card, confirmed identical
rather than merely similar. With no transcript attached to this project,
`clip_id`/`source_time` still populate (`mapping_trusted: true`); only `word`
is silently withheld rather than raising, because `_transcript()`'s
`TranscriptError` is caught here specifically.

### What this does not cover

Neither tool corrects anything — `check_black`'s `explained` is a label, not
a subtraction, same as `check_frames`'s `agrees`. Multi-track compositing is
still unmodelled, so both read a single flattened render; a project with
picture on more than one track has no representative export for either to
scan yet.

## `attenuate_noises`, pulling noise down instead of cutting it — 2026-08-08

[ROADMAP.md](ROADMAP.md) § Attenuate noises; don't cut them.

- **Two independent gates, tagged separately.** `_classify_noise_events`
  marks every loud run in every gap `"attenuated"`, `"suspect_neighbour"`, or
  `"disqualified"`, with a `reasons` list — length and gap-width failures are
  never collapsed into one reason, so a caller can tell which side of the
  filter actually caught a given event.
- **An event qualifies only when it is short (`max_event_seconds`, default
  1.5s) *and* sits in a gap narrow enough to prove the map is dense around it
  (`max_gap_seconds`, default 2.0s).** A wide gap disqualifies even a very
  short, very loud event, because a narrow event duration is not evidence the
  *map* is trustworthy there — the Scream v1 false positive was exactly this,
  0.4–0.9s "events" that turned out to be speech inside a 4.12s hole the
  transcript never wrote down (DOGFOOD.md § 2).
- **Disqualified events have no override; suspect-neighbour ones do.** An
  event whose bounding word carries a suspect duration (PLAN.md § Suspect
  word durations) is withheld from writing unless `--confirm-suspect` — the
  neighbour might itself be hiding a swallowed retake, which would make the
  "gap is narrow" evidence unsound. An event that is simply too long or in
  too wide a gap is never written, no confirmation overrides it. Both tiers
  are reported in full regardless of `confirm_suspect`/`plan` — a deliberate
  divergence from `cut_by_transcript`'s `suspect_boundaries`, which only
  surfaces under `plan`, because this is an automatic scan that can turn up
  many independent candidates and refusing the whole pass over one distant
  ambiguous candidate would defeat the point.
- **Padded spans (±`pad`, default 0.05s) are merged before writing.** The
  adversarial review found that two loud runs in the same gap closer together
  than `2*pad` produce overlapping padded spans, and ffmpeg's comma-chained
  `volume=...:enable=between(...)` filters attenuate the overlap twice,
  multiplicatively — reproduced live at roughly double the requested dB drop
  in the shared window. Fixed by merging `(padded_start, padded_end)` pairs
  with `speech.merge_runs(max_gap=0.0)` before building the filtergraph.
  Write-side only: `events`/`attenuated` still report one entry per detected
  run.
- **Always reads the original media, never a previous attenuated copy.**
  `media.original_media_path` is the source for every run, so re-running with
  different parameters fully overwrites `cache/attenuated/<clip_id>.<ext>`
  rather than compounding gain on top of an earlier pass.
- **`media_path()` now prefers `clip["attenuated"]`, and `export` was the one
  caller that didn't go through it.** The docstring promise — that
  `media_path()` "picks the attenuated copy up automatically everywhere
  downstream" — was false for exports: `autoeditor.to_v3` built each v3
  entry's `"src"` from the manifest's raw, immutable `"source"` field, so a
  render or kdenlive export taken after `attenuate_noises` silently used the
  original, un-quieted file while still reporting success. Fixed: `export`
  now resolves every clip through `media.media_path()` before handing records
  to `to_v3`.
- **`plan` and a real write now agree on what gets written.** `include_suspect`
  used to be `confirm_suspect or plan`, so a `plan=True` preview always
  included `suspect_neighbour` events regardless of `confirm_suspect` — a plan
  could report an `output_media` path and an event count that the matching
  real call, at the default `confirm_suspect=False`, would never actually
  write. `to_write` is now gated by `confirm_suspect` alone on both paths, so
  the plan's `attenuated`/`output_media` genuinely mirrors what the identical
  non-plan call produces.

### Measured on the Scream VO

`lucid attenuate vo --plan` at every default: **`attenuated: []`.** Zero
events attenuated on real material — this is the safety filter working, not
attenuation failing to fire:

| status | count | reason |
|---|---|---|
| `disqualified` | 13 | gap wider than `max_gap_seconds=2.0` — every one, e.g. 4 events at 55.72–58.10s in a 3.48s gap between suspect word 137 "in" (4.26s claimed) and word 138 "the", peak up to -5.7 dB |
| `suspect_neighbour` | 5 | gap narrow enough (1.24s, 1.44s) but the bounding word (446/447 "wants"/"to", or 890/891 "not"/"making") itself carries a suspect duration |
| `attenuated` | 0 | — |

`lucid attenuate vo --confirm-suspect` promotes the 5 `suspect_neighbour`
events and writes them (`written: true`). Measured against
`cache/attenuated/vo.wav` with `ffmpeg -af volumedetect`:

| span | original | attenuated | drop |
|---|---|---|---|
| 367.83–368.58s (1 event) | mean -16.4 dB / max -0.0 dB | mean -28.4 dB / max -12.0 dB | exactly -12.0 dB, both readings |
| 189.87–190.78s (4 sub-events, merged) | mean -19.6 dB / max -2.1 dB | mean -28.4 dB / max -6.1 dB | -8.8 / -4.0 dB — less than -12 because the padded window mixes attenuated and untouched audio, which is correct |
| 10–15s (untouched) | mean -19.1 / max 0.0 | identical | 0 |

A second `--confirm-suspect` run wrote the same 5 events to the same path with
identical dB readings on both spans — no compounding, because the source read
is always the original file.

### What this does not cover

Default `attenuate` (no flags) is a **complete no-op on the real Scream VO**:
every candidate loud event was disqualified by gap width or withheld as a
suspect neighbour, and that is stated here rather than implied away — the
filter is doing exactly what DOGFOOD.md § 2 asked for, not failing to attenuate
anything. Nothing here snaps a cut edge or fixes a transcript; it only ever
changes gain on an already-qualified span.

## `speech_overlap`, the ducking prerequisite Billy/Stu never had — 2026-08-08

[ROADMAP.md](ROADMAP.md) § Decision gate. Closes the paragraph that used to
read "its prerequisite is a check lucid does not have" — the check now
exists. The mid-September multi-track DECISION itself is unchanged and still
open; this only answers "can this clip speak here?", which the gate said had
to exist whichever way the call falls.

- **Clip words map by offset against the proposal; VO words map through
  `Edit.timeline_span`.** `clip_id` is not on the timeline yet — the current
  model is single-track, and usually the clip being asked about isn't placed
  — so its words map directly against the proposed `[at, at + (clip_out -
  clip_in))` window. The VO's words map through the existing edit exactly as
  captions do, so a VO word already cut is never counted as spoken. This is a
  third use of a clip's own transcript, alongside `attach_transcript`/
  `transcribe` and `cut_by_transcript`.
- **Both sides are trimmed through `energy.believable` before anything else
  happens** (CLAUDE.md; DOGFOOD.md § 2) — an inflated word duration hides a
  real seam behind it. The review found the clip side trimmed only against
  the words inside the proposed window (`clip_hits`), which for a short
  window can be dominated by the very outlier it exists to catch — a 2-word
  window whose median *is* the swallowed-retake word trims nothing at all.
  Fixed: the clip's full transcript is trimmed first
  (`clip_full_trimmed = energy.believable([...full clip words...])`) and then
  filtered down to the window, matching how the VO side and every other
  `believable()` caller in the codebase already derives its median from the
  whole population being reasoned about.
- **Merged into runs with `max_gap` tolerance** (default 0.3s) — a 0.05s gap
  between two words is not a usable seam to duck into.
- **Overlap, never containment, and in timeline coordinates.** `overlaps`
  (`speech.intersect_runs`) means the placement steps on VO speech, not empty
  air. `clean_seams` (`speech.subtract_runs`, at least `min_seam` wide,
  default 0.5s) are the windows where `clip_id` could speak without touching
  it.
- **Read-only.** Nothing is written and there is no `plan=` — there is
  nothing to preview a write of; this is the decision aid asked for before any
  ducking mechanism is designed, not a mutation.

### Measured on the Scream VO — the Billy/Stu clip

This VO take does **not** contain the literal "movies make psychos more
creative" line the gate names — searched and confirmed empty. The measurement
below uses the VO's actual nearest thesis region instead (words ~280–334,
source ~120.8–140.56s, "Billy and Stu spend the entire movie explaining the
rules of a horror movie to you... The killer is the movie's argument"),
mapped to timeline time 106.266–120.566s.

| placement | `clip_speech_s` | `overlap_s` | overlap % | `clean_seam_s` | seam % | `clip_runs` |
|---|---|---|---|---|---|---|
| thesis region, `--at 106.4` | 18.1 | 15.401 | ~85% | 1.74 | ~9.6% | 7 |
| start of timeline, `--at 0.0` (comparison) | 18.4 | 13.62 | ~74% | 3.14 | ~17% | 6 |

Clean seams at the thesis placement: 110.566–111.186 (0.620s),
122.659–123.279 (0.620s), 130.380–130.880 (0.500s) — every one narrower than a
single word, none of them a real insertion point. At an arbitrary placement
against dense VO speech the story is the same shape, just slightly less
overlap. Either way the clip's own speech overlaps VO speech 74–85% of its
own runtime with only sub-second clean seams — the same "no seam" conclusion
that shelved the duck for v4, now measured by the tool rather than by hand.

### What this does not cover

The duck itself — splitting a shot into muted/unmuted producers plus a `mix`
transition — is unbuilt; this answers "can it speak here", not "how to duck
it". `vo_clip_id` assumes one VO clip on the timeline unless named explicitly,
and `clip_id`'s placement is hypothetical throughout — nothing here puts the
clip on a timeline that cannot yet hold it.

## `locate`, the source→timeline direction `cut-at` does not go — 2026-08-08

Wiki Open items, "two CLI gaps surfaced by the 2026-08-08 dogfood run" (b).
`cut_by_time` resolves a render timestamp back to source; nothing resolved
source forward to render. Both coordinate systems are load-bearing — the whole
project rests on word indices addressing the source and never renumbering —
and the arithmetic between them (walk the segments, accumulate durations) was
being done by hand against `project.otio`. It is exactly the arithmetic every
cut invalidates.

- **`Edit.timeline_spans` is a new primitive, not a rename of
  `timeline_span`.** The singular one stops at the first segment overlapping
  the interval, because captions want one span per word and a half-cut word
  should show for the half still audible. That is the wrong shape for "where
  does this play": a range a cut split has *two* answers and the singular form
  silently reports one. The plural walks every segment and returns a
  `Placement` per survivor, carrying both coordinate systems — the source
  coordinates are what make a partial answer readable rather than merely
  short. `source_spans` remains the timeline→source aggregate; the four
  mappings now pair up.
- **Pieces are not merged even when their timeline coordinates touch.** Across
  a cut seam they do touch — the hole closed — but "continuous to a listener"
  and "no cut inside it" are different facts, and merging would report the
  second one falsely. `Placement.contiguous_with` re-joins them for a caller
  that only cares about playback, and `contiguous` in the payload says whether
  anything else got between them (which single-track cannot produce, so
  `test_pieces_split_by_another_clip_are_not_contiguous` builds it directly).
- **Cut and never-recorded are told apart.** Both produce zero placements, and
  the empty list alone reads as an edit decision. `beyond_source` plus
  `source_duration` name the other case. It is a bool with the seconds beside
  it in `beyond_source_seconds`, because an instant past the end overruns by
  exactly 0.0 and a caller testing that number's truthiness would miss it.
- **One addressing mode per call, enforced twice.** Word indices and source
  seconds name the same thing two ways, so a call giving both cannot say which
  it meant. `ops.locate` refuses it; the CLI refuses it earlier through a
  mutually exclusive group, which is the same answer with usage text.
- **Echoes follow the existing conventions.** Word mode echoes the resolved
  words plus three either side (CLAUDE.md); time mode echoes the words the
  interval overlaps — overlap, never containment — and falls back to
  `_nearest_context` when the interval landed in silence, reusing
  `cut_by_time`'s own helpers rather than a parallel set. A clip with no
  transcript still locates by time, with `transcript_missing`, matching
  `cut_by_time`'s choice not to refuse a valid question about picture.
- **Read-only.** No snapshot, no `plan=`, same as `speech_overlap`.

### Measured on the Scream VO

67 segments, timeline 312.175s against a 385.792s recording.

| asked | source | timeline | note |
|---|---|---|---|
| `--words 874:875` ("the reveal") | 360.100–360.580 | 293.542–294.022 | 66.558s of cuts sit in front of it |
| `--words 298:302` ("to you. And then the") | 127.040–128.920 | — | `present: false`, `covered: 0` |
| `--span 127.0-130.5` | 127.000–130.500 | 103.466–103.746 | 0.280s of 3.500s survives, one piece |
| `--at 9999` | — | — | `beyond_source`, `source_duration: 385.792` |

The round trip is the check that matters: `cut-at --plan 293.542-294.022`
resolves back to source 360.100–360.580 and echoes words 874/875, against 67
real segments rather than a fixture. Word 873 ("making", 359.78–360.10) also
appears in that echo — its end sits exactly on the boundary, and the overlap
test is doing what it is supposed to at a float edge.

The middle row is the one worth keeping. A 5-word phrase reported wholly
absent looked like a bug until the segments were read directly: nothing
between 124s and 130.22s survives at all, so `present: false` is the correct
answer and the tool is refusing to slide the phrase onto the material that
replaced it.

## `init` stops silently ignoring `-C` — 2026-08-08

Wiki Open items, same row, (a). Every other subcommand *finds* a project
through the global `-C`, which is the habit the CLI teaches; `init` alone read
only its positional. So `lucid -C myproj init` created a project in the
current directory and printed a success payload naming it — the wrong
directory, with no error.

Both spellings now work, and giving two different answers is refused rather
than resolved. That needed `-C`'s default to move out of argparse (`default=
"."` cannot be told from an explicit `-C .`) and into `main`, which sets
`args.project_given` before defaulting; `init` is the only reader, because it
is the only subcommand whose directory is an argument rather than a lookup.

## The multi-track costing spike — 2026-08-08

[ROADMAP.md](ROADMAP.md) § Decision gate asked what widening the model costs,
so the mid-September call could be made against a number. Nothing was built
here; everything below is measured, on this box, against auto-editor 31.4.2 and
the real Scream VO.

**The headline is that the question splits in two, and they were being priced
as one.** Widening the *model* is cheap and the cheap design is already
validated. Getting a multi-source timeline *out* is the expensive half, the
cost is not code, and it lands the same way whichever way the model question is
answered.

### auto-editor's v3 is already multi-track — track count is free

`to_v3` writes `payload["v"] = [list(entries)]`: `v` and `a` are lists **of
tracks**, and lucid has only ever written one. auto-editor honours more. A
hand-built two-video-plus-two-audio-track v3 renders and exports:

| timeline | render | `--export kdenlive` |
|---|---|---|
| 1 track, 1 source (what lucid writes today) | full res | ok |
| **2 tracks, 1 source** | **full 1920x800** | **ok — 4 tractors, `melt` reads it** |
| 1 track, 2 sources | 720x300, warning, **exit 0** | refused, exit 2 |
| 2 tracks, 2 sources | 720x300, warning, **exit 0** | refused, exit 2 |

So multi-track per se costs nothing at the export boundary, and auto-editor's
own exporter writes the whole MLT structure — producers, playlists, tractors,
`mix` and `qtblend` transitions — that `assemble_scream.py` hand-rolls in 534
lines. Verified end to end: `picture.project_frames()` on the two-track export
returns 121 frames for a 120-frame timeline, which is the *known* trailing
black frame (CLAUDE.md) and confirms it is not single-track-specific.

### The wall is source count, and it is a paid key

`src/license.nim` in auto-editor's own source:

```nim
FREE_RENDER_LONG_SIDE* = 3200'i32     # unlicensed single-source render cap
FREE_RENDER_SHORT_SIDE* = 1800'i32
FREE_MULTI_SOURCE_LONG_SIDE* = 720'i32   # unlicensed multi-source render cap
FREE_MULTI_SOURCE_SHORT_SIDE* = 576'i32
```

Any timeline naming two distinct `src` files — **on one track or several** — is
gated. The key is ed25519-signed, supplied by `-k/--license-key` or the
`AE_PRIVATE_LK` env var, issued from `app.auto-editor.com`, and time-limited
(`LICENSE_PERIOD_YEARS = 3`, `LICENSE_EXPIRY_YEARS = 4`, checked against the
binary's *compile* date, so an old build keeps working). The 3200x1800
single-source cap is well above anything this project renders and is not
binding; the 720x576 multi-source cap is.

Two things about how it fails are worth writing down:

- **The render side degrades silently.** It prints a warning, writes a
  720x300 file, and **exits 0** — the same shape of trap as `melt` printing
  `Failed to load` and exiting 0 (CLAUDE.md). An exit code proves nothing here
  either. The kdenlive export at least refuses loudly, exit 2.
- **lucid cannot currently reach the wall, and every overlay design reaches it
  immediately.** `seed_timeline` *replaces* the whole `Edit` and nothing
  appends to it, so a timeline can only ever hold one `clip_id` —
  `to_v3`'s per-segment `clips.get(seg.clip_id)` lookup has never had a second
  answer to give. Note this is not a multi-track problem: a plain two-take
  concat on one track hits the same wall.

auto-editor's source is **the Unlicense** (public domain), master active as of
2026-08-05, gate included in that source — so compiling it without the check is
permitted by the stated licence rather than a circumvention of it. Re-read that
licence at the commit actually forked rather than trusting this line: a project
that has just added a paid tier is the kind that relicenses, and only the
binary is on this box (`~/.local/bin/auto-editor`, 31.4.2) — the source is not
checked out here, so nothing local re-verifies it. That is one option; it costs
a Nim toolchain and a fork to keep current. Buying a key is
the other, and it collides with § Non-goals' first line — "Cloud anything. No
accounts, no metering" — because a key *is* an account. Neither is free, and
the price of a key could not be established: `auto-editor.com/pricing` 404s and
checkout is behind a login.

### What v3 expresses, and the one thing it does not

The syntax behind § Open questions' answer, measured on 31.4.2:

- **Speed:** `{"src": …, "effects": ["speed:2.0"]}` on the entry.
- **Transitions:** a top-level `"transitions"` key, `{v: [per-track], a: […]}`,
  each `{kind, at, dur, alignment}`, `at` in timeline frames, alignment
  `start`/`center`/`end`.
- **Composites:** the track list above.

No field carries **per-entry gain**, which is exactly the ducking case — but
`attenuate_noises` already writes derived gain-reduced media into
`cache/attenuated/` and `media.media_path()` resolves it, so "duck the VO across
this span" extends a subsystem that exists rather than needing a new one. An
unrelated trap from the same measurement: a two-audio-track render writes **two
separate audio streams**, not a mixdown, and without `--mix-audio-streams` most
players hear only the first.

### The cheap design needs no new addressing code — measured

`assemble_scream.py`'s real 37-cue table, run through lucid's existing
`Edit.timeline_span` against the real Scream VO lucid project
(`Project/lucid-vo/`, 67 segments, 310.875s) and compared to that script's own
frame-inclusive MLT arithmetic:

| | result |
|---|---|
| survival verdicts disagreeing | **0 of 37** |
| position delta | **-0.013s to +0.027s** (sub-frame at 30fps) |
| frame-inclusive accumulation, had it drifted | 2.233s |

The delta is not the accumulation, so the two independently-derived answers
agree. **The picture track is derivable from the API that already ships.**

### The two designs, and what each costs

**Design A — widen `Edit` to N positioned tracks.** All five addressing methods
(`timeline_time`, `timeline_span`, `timeline_spans`, `source_at`,
`source_spans`) are built on `offset += seg.duration`: that running sum *is* the
single-track assumption, so a positioned model rewrites all five. `from_otio`
loses its `break`, `to_otio` its single track, `frame_layout`/`to_v3` their
single cursor. Worse, `remove`/`keep_only` ripple semantics break — rippling the
VO invalidates every stored position on the picture track, which is
ROADMAP.md § The property everything defends traded away for the thing it was
defending against. This is timeline.py rewritten plus every `ops.py` caller
audited.

**Design B — `Edit` stays single-track; the overlay is a derived projection.**
This is what the worked reference actually does: it stores
`(source_word_index, asset)` and *recomputes* positions every run, so there is
nothing positioned to go stale. Unchanged: all five addressing methods,
`remove`, `keep_only`, `from_otio`, `to_otio`, captions, verify, cut, locate.
New work, roughly:

- a cue table in the manifest, `(clip_id, word_index, asset)` — source-addressed
- a projection to contiguous shots, i.e. `build_shots` minus all the MLT XML
  (~150–200 lines; the XML is what auto-editor now writes for us)
- multi-track emit: `to_v3` gains a track list, `frame_layout` a positioned
  variant (~40 lines)
- **refuse to build when a cue points into a cut range** — this fired correctly
  twice on Scream and must survive into whatever shape lucid adopts
- MCP + CLI parity per new op, and tests

A few hundred lines against a rewrite, and the property holds by construction.
Design B is the recommendation for the model half.

### What this does to the gate

**The model question is answered and it is cheap. The gate now turns entirely
on the export wall**, and the gate's own named test edit is what forces it: a
duck needs the film clip's audio *and* the VO, which is two sources, so
**Billy/Stu cannot be exported by an unlicensed auto-editor whichever way the
model question is decided.** The choice is between four options, and the first
three each collide with something already written down:

1. **Pay for a key** — collides with § Non-goals, "no accounts, no metering".
2. **Build auto-editor from source without the gate** — permitted by the
   Unlicense; costs a Nim toolchain and a fork. Note it is a fork, not a build:
   the gate is *in* the source, so compiling unmodified reproduces it, and the
   recurring cost is re-applying the patch per upstream release. Its trap is
   that a fresh install, a second machine or a `pip install` shadowing the fork
   silently restores the gate — and the restored failure is a warning, a
   720x576 file and **exit 0**, so the render is the only thing that reports
   it. Resolve the binary the way `asr.py` resolves whisper (env → PATH →
   sibling venv) and assert un-gatedness by rendering a throwaway two-source
   frame and checking its *resolution*, never its exit code.
3. **Write MLT directly** — reverses ROADMAP.md's "lucid never writes MLT
   itself", and re-adopts the 534 lines auto-editor would otherwise write.
4. **Keep exports single-source and formalise the handoff** — lucid *computes*
   the overlay (design B's projection, refuse-to-build included) and hands
   Kdenlive a cue sheet instead of a rendered multi-track timeline. This is
   what happens today with a human in the loop, made machine-readable. It is
   the only option that collides with nothing, and it delivers the cue-table
   value — positions recomputed after a recut, stale cues refused — without
   needing multi-source export at all. What it does *not* deliver is the duck.

Option 4 is the honest default and option 2 is the cheapest way to get the
duck. The DECISION stays open at mid-September as scheduled; what changed is
that it is now a question about auto-editor's business model rather than about
lucid's data model.

Housekeeping, noticed in passing: the "68 cuts" figure repeated across these
docs is approximate, and no VO timeline has exactly that count — measured,
`Scream VO - final.kdenlive` is 67 entries, `… final v2` 69, `… final v2 +
outro` 70. The comparison above pairs the 67-entry `final` with
`Project/lucid-vo/`, which matches it; `assemble_scream.py`'s production run
used a later one. Nothing above depends on the figure, but it is not a constant.

## The preview/timeline web UI — 2026-08-08

README's tier 2, built the day [ROADMAP.md](ROADMAP.md) queued it. `lucid web`
serves a page on localhost that draws the current `Edit`, plays it, and cuts
it. Every check that existed before answers a *machine's* question — `verify`
diffs the render's words, `frames`/`black`/`spots` read counts and pixels —
and none of them let a person see an edit before committing to a render.

**The claim worth stating plainly: seeing an edit now costs no render.** The
page plays the *source file* and jumps the seams, so the thing being previewed
is the timeline rather than an export of it. Measured on the real Scream VO:
seeded at 62 segments, playback at timeline 33.1s sat at source 36.234s, and
1.8s later it was at source 39.284s — it had crossed the seam at source
36.634→38.033 without playing the 1.399s the silence pass removed. The words
either side of that seam are 98 `them,` and 99 `I`, which is the
"I have never given" retake DOGFOOD.md § 2 describes.

### It is a third client, not a third implementation

The constraint it was queued under, and the one a window is most likely to
break. Nothing in the page computes an edit. Selecting words and pressing Preview
posts to `ops.cut_by_transcript(plan=True)`; pressing Cut posts the identical
body with `plan` false; dragging the timeline strip posts to `ops.cut_by_time`;
Undo posts to `ops.undo`. What the panel draws **is** the op's return value,
which is what makes the preview trustworthy — it is the real call with the
write skipped, not a second guess at the numbers.

The one thing the browser necessarily computes for itself is timeline→source
mapping, because that is what playing an edit without rendering it *is*. It
draws and it plays; it never decides.

`plan` is a field on the request rather than its own endpoint, for the same
reason: two URLs would be two paths to drift apart, which is the thing
`plan=True` exists to prevent.

### `timeline_view`, the read model

The page needed one payload for "the whole edit", and computing it in the
server would have put the overlap test in a front end. So it is an op —
`ops.timeline_view`, MCP tool `timeline_view`, CLI `lucid view` — and it is
`locate` asked once for a clip instead of once per range:

* **segments** carry both coordinate systems. `Edit.segments` holds source
  time only; where a segment *plays* is the running sum of everything before
  it, which is the arithmetic every cut invalidates.
* **seams** are named by the surviving words either side. This is the part
  that was wrong first: asking the transcript what sits at a seam's *source*
  time answers with the word that was **removed**, because a cut begins
  exactly where the outgoing segment ends. The lookup has to happen among the
  survivors, in timeline coordinates. Caught by the test, not by reading.
* **words** report `present`, `covered` and `partial`. Survival is an overlap
  test, never containment (CLAUDE.md), so a word a cut split reports present
  and says how much is left. On the real VO that is 24 of 929 words — routine,
  not a defect, and the view marks them rather than rounding them to kept.
  Suspect durations carry the flag `attach_transcript` already reported; 13 of
  929 there.

A clip with no transcript still returns segments and seams, with `words` null
and `transcript_missing` set — `locate`'s policy, for the same reason.

### Stack: `http.server`, and the one thing hand-rolled

Standard library only, no build step, static assets shipped in the package
(`src/lucid/web/`, confirmed present in the built wheel). starlette and uvicorn
are already in the tree under `mcp`, and were still not used: two direct
dependencies is the whole point of § Non-goals' "no second stack".

HTTP Range is hand-rolled because a browser will not seek in a `<video>`
without it, and `SimpleHTTPRequestHandler` does not speak it. Single-range
only; `multipart/byteranges` is real work no media element needs. Verified
byte-exact against the real 70 MB VO through its symlink, including a
mid-file seek and the `bytes=-N` suffix form.

Media resolves through `media.media_path`, so the preview is of the
*attenuated* copy when one exists — the file every downstream op reads, which
makes the preview the audio that will actually be exported.

### Two guards, because localhost is not private

This server mutates a project and reads media, and any page you happen to be
browsing can issue requests to `localhost`.

* The `Host` header must name loopback. A name an attacker controls that
  resolves to 127.0.0.1 arrives looking local otherwise; the socket cannot
  tell you apart from the rebinding, only the header can.
* Every mutating request must be `application/json` — the one content type an
  HTML form cannot produce. That turns a cross-origin attempt into a
  preflight, and no CORS headers are ever served to satisfy one.

Both are asserted in `tests/test_webui_http.py`, live over a socket, including
that a refused POST leaves `undo_depth` at zero.

### What it does not do

Single-track, because `Edit` is (§ The multi-track costing spike). No
waveform: the strips are drawn from segment durations, and an envelope would
be a second read of the media for a picture `energy.py` already answers
numerically. Seams click on playback — each one is a seek, and the page says
so rather than implying a clean join. Nothing here renders, exports or
finishes; that is still ROADMAP.md's tier-2/tier-3 line.

## Tier 3 is the goal — the Daydream-shaped workspace — 2026-08-08

**The decision: lucid grows a workspace, not a shell.** § The preview/timeline
web UI shipped and was used, and the verdict on use was that it is a correct
*instrument* and a poor *editor*. ROADMAP.md had already left tier 3
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

ROADMAP.md § "What separates tier 2 from tier 3 is finishing, not mutation"
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
a ducked A2 in an afternoon; `export` cannot follow it. § The multi-track
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
OpenChatCut trial (§ First milestones) found an Electron GUI that must be
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
  `has_video`, A1 always, CC only when captions exist. **No V2, no A2, no lane
  that `export` cannot produce** — § The trap this section exists to write
  down, above.

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
must precede the subcommand — `lucid mcp -C` does not parse). **But the
project binding is weaker than this section originally claimed**, found
while building: `_cmd_mcp` ignores `-C` entirely, and every MCP tool takes
its own explicit `path` argument — so nothing yet stops the agent pointing
a tool it *is* allowed at a different project directory. Confinement to
lucid's ops holds; confinement to *this project's* ops does not. The fix is
binding `path` server-side to the `-C` value; open item in the wiki.

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
one. This is the sentence that actually crosses the tier line. ROADMAP.md's
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

* **auto-editor's exit code does not mean success** (§ The multi-track costing
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
* **Video, and the codec wall under it.** Every claim above about the picture
  is unverified against real footage, because the only project in the repo is
  an audio-only VO. Frame stepping and letterboxing get checked against a real
  clip before they are believed.

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
