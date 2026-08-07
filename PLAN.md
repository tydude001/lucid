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
| `transcribe`, `get_transcript` | openai-whisper + goodsometimes `scripts/clipcut.py` (in use; it verified the Scream reveals) | packaging |
| `remove_silences` | auto-editor 31.4.2 | nothing — the plan already said shell out |
| `render` | auto-editor v3 / `melt` | mapping layer, per the render decision |
| `export_otio` | `auto-editor --export kdenlive` lands natively in the only NLE here | **near zero** — this was already "lower urgency than it looks"; the Linux NLE ceiling has now collapsed it. **Superseded by the render spike below — see § The handoff clause is not dead** |
| `add_captions` | — | word-timed ASS, genuinely absent |
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
| `transcribe` | faster-whisper | word-level timestamps, cached per clip |
| `attach_transcript` | cache | ingest a word-timed JSON the recording already has. Not in the original surface; added once the first real subject turned out to have been transcribed before lucid existed |
| `get_transcript` | cache | agent reads text + timings to plan cuts. Takes a `search` phrase as well as a window — locating a retake in 929 words should not mean reading 929 words |
| `cut_by_transcript` | OTIO, hand-rolled | cut/keep ranges as words or times. OTIO's edit algorithms are C++ only — no Python bindings — so this is track surgery over Track/Clip/Gap and `source_range`, not a library call |
| `remove_silences` | auto-editor subprocess | do not reimplement; auto-editor's `--edit` language (`"(or audio:0.03 motion:0.06)"`, labels, `--margin`) is richer than thresholds-as-parameters |
| `add_captions` | ffmpeg + ASS | burn-in, word-timed; styled via a small preset set |
| `render` | OTIO → auto-editor v3 | a mapping layer, not a renderer — see the render decision below |
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
