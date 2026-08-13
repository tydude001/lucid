# lucid — history

The dated record of what shipped and what the evidence said, moved out of
PLAN.md so the plan stays a plan. Three rules:

- **Sections are cited by name** — from CLAUDE.md, PLAN.md, the wiki, code
  comments and tests — so **headers here are never renamed**.
- **Append, don't rewrite.** A section that turns out to be wrong gets a
  correction note, the way PLAN.md § How much of the MVP is left carries one; the
  original stays on the record.
- References to "the roadmap" and its numbered items cite the roadmap as it
  stood on that date; the roadmap now lives at PLAN.md § Direction and order.
- The living layer is elsewhere: design and order in [PLAN.md](PLAN.md), the
  parity program in [DAYDREAM.md](DAYDREAM.md), guardrails in
  [CLAUDE.md](CLAUDE.md), status in the wiki's Open items table.

## First milestones — all seven ran — 2026-08-07

All seven ran; the trial and spike verdicts below are why several later
sections exist. Moved verbatim from PLAN.md.

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
   free** — see the correction in PLAN.md § How much of the MVP is left. Second, v3
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
   building next are in § Dogfood — what the first real video taught us, below.


## Dogfood — what the first real video taught us — 2026-08-07

Milestone 7's output. lucid cut the voiceover for the goodsometimes Scream
essay on **2026-08-07** — its first job on material somebody actually intends
to publish — and the video was assembled, rendered and verified around it.

This is the pain-point list that milestone says to promote into the plan. It is
written for whoever picks lucid up next; the evidence lives in goodsometimes
`ideas/scream.md` § Retakes trimmed and `pipeline.md`.

### What the video was

5:10.9 of VO across 67 segments, under 37 shots of film clips and title cards.
lucid's part: strip silences, then cut eight retakes by word range. Everything
above the audio bed was done by a one-off script, `goodsometimes/scripts/
assemble_scream.py`, because lucid has no multi-track model.

### The core thesis held, and it paid off late

**Word indices addressing the source and never renumbering is the thing that
made this work.** It is easy to read that as an implementation detail. It isn't:

Two retakes were discovered *after* the picture was built — 37 shots, 9 cards,
all positioned. Removing them shifted every downstream cut by 4.4 seconds. The
repair was two `lucid cut` commands and one re-run of the assembly script, and
the whole shot plan recomputed correctly, because every cue was addressed by a
word index into the source rather than by a timeline position.

Had the cue table been written against timeline seconds, that correction would
have meant re-timing 37 shots by hand, and the realistic outcome is that the
defect ships instead. **Keep this property. It is the product.**

### 1. Build `verify` — transcribe the render, diff against the timeline

The highest-value thing lucid is missing, and it is small.

> **Built 2026-08-07**, close to as specified below — including surfacing the
> repeated phrase explicitly rather than leaving it in the diff. What it cost
> and what a real run measured: [PLAN.md](PLAN.md) § `verify` checks the
> render, because the transcript cannot.

lucid knows what words the timeline *should* play: the transcript, filtered by
the surviving ranges. Transcribing the finished render and diffing the two
catches a class of defect nothing else does.

On this video it caught two retakes the trim list had missed. Both survived
into the first full render. Reading the project file could never have found
them — that only proves the cuts you made are the cuts you meant, and these
were never cut at all.

```
lucid verify <render.mp4> [--clip vo]
  → expected 854 words from the timeline, heard 858 in the render
    similarity: 0.975
    <unified diff of the word sequences>
```

Notes for whoever writes it:

- Expect ~0.97, not 1.0, on a clean render. Whisper spells things its own way
  ("whodunit" / "who done it", "4" / "four"), so the score is a triage signal
  and the diff is the artifact. Normalise to lowercase word tokens.
- A repeated phrase in the render that appears once in the transcript is the
  signal that matters. Surface it explicitly rather than leaving it in a diff.
- Frame count, `blackdetect` and spot frames cover the picture. Only the
  re-transcription covers the audio. Both are needed. `verify` deliberately
  covers only the audio half — the picture checks belong with rendering, not
  with this.

### 2. Word durations are not addresses — only word *order* is

lucid's entire model rests on a whisper transcript. The word **sequence** is
reliable. The **durations** are not, and this bit twice in one video.

**Whisper collapses immediate repeats.** It writes the abandoned take down as
ordinary words, then hands the *following* word a duration long enough to
swallow the pause and the entire restart. On this material word 446 was given
2.2s and word 890 2.0s, each with a complete restarted clause hidden inside. A
script-vs-transcript diff therefore sees each line exactly once and reports
nothing wrong — which is precisely why the two retakes above went unnoticed
until the render.

**A long word breaks containment tests.** The same defect made one word appear
to have been cut when it hadn't: its inflated duration spanned a silence, so
auto-editor's pass split it across two surviving segments, and a "is this word
inside a kept range?" test answered no. **Asking whether a word survived is an
overlap test, never a containment test** — partial survival is normal.

Three proposals, cheapest first:

1. **Flag suspect durations at `attach-transcript`.** Any word running beyond
   ~3× the median is a lie about something. Report the list; refuse to use one
   as a cut boundary without confirmation.
2. **Fix the overlap test wherever lucid asks "did this word survive".**
3. **Snap cut edges to an energy minimum.** This is already PLAN.md § Word-
   timestamp accuracy's plan, and this video is new evidence for it — but see
   below, because it also revises that section's conclusion.

### This revises the "not urgent" finding in PLAN.md § Word-timestamp accuracy

That section records a 2026-08-07 measurement: at the six retake boundaries the
silence ran 0.34s–2.48s, a flat `pad` of 0.1s landed well inside every gap, and
nothing was clipped. That measurement is still correct — but it was taken
across the retakes lucid *knew about*, which is a biased sample. The two it did
not know about are the ones where the transcript was not merely imprecise but
**wrong**: it did not contain the words at all.

So the conclusion splits. *Drift* remains non-urgent on this kind of material.
*Transcript infidelity* is a different failure with a different fix — energy
snapping doesn't help you cut a take the transcript never recorded. That is
what `verify` (§1) is for, and it is why §1 ranks above §3.

### 3. Multi-track: the shape is known now, so the decision is cheaper

PLAN.md § Open questions calls laying clips and graphics over the VO "the next
real decision", to be made against the next video rather than this one. That
still stands — but `assemble_scream.py` is now a worked reference (534 lines,
stdlib only), so the decision can be made against a real implementation.

**The model it validates:**

- A cue table of `(source_word_index, asset)`. Each cue runs until the next
  one. Nothing is positioned in timeline coordinates — see the thesis above.
- A `timeline_time()` that maps source seconds through the surviving ranges,
  honouring MLT's frame-inclusive `out`: an entry lasts `(out - in) + 1/fps`.
  Ignoring this drifted a 68-cut timeline ~2.3s late by the end.
- Validation by frame count: the computed total must equal what `melt
  -consumer xml` reports. It did, exactly, which is what made the positions
  trustworthy before anything was rendered.

**MLT specifics that cost real time, so nobody re-derives them:**

- Video clips are `<chain>` with `audio_index=-1` and `set.test_audio=1`, or
  they fight the VO. Still images are `<producer mlt_service="qimage">`.
- **A tractor renders only its first track unless you add transitions.** Two
  are required: `mix` (`a_track=0 b_track=1`) for audio and `qtblend`
  (`a_track=0 b_track=2`) to composite picture over black. Without them the
  render succeeds and shows one track.

**And one ergonomic finding worth generalising:** the assembly script's
`--plan` prints, for every cue, the actual word text that index resolves to.
That immediately exposed six cues pointing one word past the intended phrase —
an error invisible in the index itself. **Any lucid command that accepts a word
index should echo back the words it resolved to.**

### 4. Rendering a multi-track project needs `melt`, not auto-editor

> **This section decided the multi-track gate, once it was noticed** — the gate
> had been costed as though auto-editor were the only renderer. Measured
> 2026-08-08: `melt` renders the real 23-source Scream assembly at 1920x1080,
> ungated. PLAN.md § The layered timeline.

`export --render` shells out to auto-editor, which is right for a single-track
cut. A multi-track MLT project needs `melt`, and it has three traps that all
produce output rather than an error:

- **Pass the codec and nothing else.** Restating the project profile on the
  consumer correlates with unbounded memory growth — 2167 MB peak with
  `vcodec crf preset acodec` alone, still climbing past 6873 MB with `ab`,
  `width`, `height` and `progressive` added, on the way to the 14.6 GB that
  froze the machine. No single one of the four reproduces it in isolation.
- **MLT's Qt module needs a display.** Without `WAYLAND_DISPLAY` or `DISPLAY`,
  every `qimage` producer and the `qtblend` transition refuse to load — the
  card track silently vanishes and the render still exits 0.
- **A flatpak's `/tmp` is not the host's.** `filesystems=host` does not cover
  it, so scratch must live under `$HOME`.

`goodsometimes/scripts/render.py` handles all three plus a `systemd-run`
memory cap; details in that repo's `pipeline.md` § Rendering.

### What this does not establish

One video, one speaker, one voice. The source was **audio-only** — no VFR
question was touched, no camera footage, no speed changes or transitions. Every
cut landed at a restart pause, the most generous case there is; a mid-sentence
cut has no such margin.

The multi-track findings come from a script written for one project and are
descriptive of MLT, not of a design lucid has committed to.

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
  "normalise only when exporting to an NLE" in PLAN.md § Open questions actually means
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

§ 1's top-ranked item. Two retakes reached the first
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

The roadmap's § 1. Run against the real material this time: the v1
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
put a 3.96-second word. That is the same quantity the roadmap's § 2 wants flagged, so
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
check, now the roadmap's § 3.

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
  duration first, the same multiple the roadmap's § 2 flags at.
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

roadmap item 1, built and run against the real `VO/VO.json` (929 words), not
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

roadmap item 1, built and run against the real `VO/VO.json` (929 words).
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
second half" hole § 2 documents is index 137, "in", at 4.26 s. 446 and 890
are the words this item's own done-when criterion can be checked against.

## `cut --plan`, and echoing what a word index resolved to — 2026-08-07

roadmap item 1, built and run against the real `VO/VO.json`. Three parts, and
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

The roadmap's § Picture-side render checks, of whose three parts
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
trustworthy before pixels existed (§ 3), and reading a document
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
third of § 4's traps, met from a new direction. The empty-output
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

The roadmap's § Accept cuts in render time — and its mirror,
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
  timestamp against. Suspect boundaries (§ Suspect word durations)
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

> **Narrowed 2026-08-08** by PLAN.md § The layered timeline — the gate is decided, and
> `melt` renders it. Single-source `export` still goes through auto-editor,
> exactly as described above. The **multi-source** path generates MLT itself,
> because auto-editor's kdenlive exporter refuses it outright (exit 2) — so
> lucid now owns both constraints above on that path, and the declared-length
> sweep gets an assertion rather than a comment. It still only ever
> *generates*, never *mutates*, which is the distinction this paragraph was
> actually defending.

## `check_black` and `spot_frames`, the rest of the picture-side checks — 2026-08-08

The roadmap's § Picture-side render checks — the rest of them.
`check_frames` (§ `check_frames`) is the load-bearing third of this
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

The roadmap's § Attenuate noises; don't cut them.

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
  transcript never wrote down (§ 2).
- **Disqualified events have no override; suspect-neighbour ones do.** An
  event whose bounding word carries a suspect duration (§ Suspect
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
filter is doing exactly what § 2 asked for, not failing to attenuate
anything. Nothing here snaps a cut edge or fixes a transcript; it only ever
changes gain on an already-qualified span.

## `speech_overlap`, the ducking prerequisite Billy/Stu never had — 2026-08-08

The roadmap's § Decision gate. Closes the paragraph that used to
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
  happens** (CLAUDE.md; § 2) — an inflated word duration hides a
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

The roadmap's § Decision gate asked what widening the model costs,
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
the other, and it collides with PLAN.md § Non-goals' first line — "Cloud anything. No
accounts, no metering" — because a key *is* an account. Neither is free, and
the price of a key could not be established: `auto-editor.com/pricing` 404s and
checkout is behind a login.

### What v3 expresses, and the one thing it does not

The syntax behind PLAN.md § Open questions' answer, measured on 31.4.2:

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
PLAN.md § The property everything below defends traded away for the thing it was
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

> **Superseded 2026-08-08 by PLAN.md § The layered timeline — the gate is decided, and
> `melt` renders it.** Every measurement in this section stands; the conclusion
> below does not. It prices the gate as if auto-editor were the only renderer,
> which contradicts § 4 — `melt` has no source-count
> gate and renders the real 23-source Scream assembly at 1920x1080. Options 1
> and 2 are dropped and option 3 is the path. Read the four options below as
> the reasoning that was corrected, not as open choices.

**The model question is answered and it is cheap. The gate now turns entirely
on the export wall**, and the gate's own named test edit is what forces it: a
duck needs the film clip's audio *and* the VO, which is two sources, so
**Billy/Stu cannot be exported by an unlicensed auto-editor whichever way the
model question is decided.** The choice is between four options, and the first
three each collide with something already written down:

1. **Pay for a key** — collides with PLAN.md § Non-goals, "no accounts, no metering".
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
3. **Write MLT directly** — reverses the roadmap's "lucid never writes MLT
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

> **End of the superseded conclusion.** The gate closed the same day instead of
> in September: the question was never auto-editor's business model, because
> auto-editor was never the renderer. Option 3 — write MLT, render via `melt` — is the
> path, and it collides with nothing once the "never writes MLT" rule is read
> as what it says (never *mutates*) rather than what it is usually summarised
> as. PLAN.md § The layered timeline — the gate is decided, and `melt` renders it.

Housekeeping, noticed in passing: the "68 cuts" figure repeated across these
docs is approximate, and no VO timeline has exactly that count — measured,
`Scream VO - final.kdenlive` is 67 entries, `… final v2` 69, `… final v2 +
outro` 70. The comparison above pairs the 67-entry `final` with
`Project/lucid-vo/`, which matches it; `assemble_scream.py`'s production run
used a later one. Nothing above depends on the figure, but it is not a constant.

## The preview/timeline web UI — 2026-08-08

README's tier 2, built the day the roadmap queued it. `lucid web`
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
"I have never given" retake § 2 describes.

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
dependencies is the whole point of PLAN.md § Non-goals' "no second stack".

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
finishes; that is still the tier-2/tier-3 line (PLAN.md § Direction and order).

## What the roadmap's reshuffles recorded — 2026-08-08

Kept from the retired ROADMAP.md, because both were deliberately left on the
record. **The 2026-08-08 clear of "Next"** (render-time cuts, the remaining
picture checks, `attenuate_noises`, `speech_overlap`) ended with an
adversarial review that found and fixed seven correctness bugs — notably
`export` silently skipping attenuated audio, and a `plan=True` preview of
`attenuate_noises` promising a write the real call would not perform. **And
the tier-3 note predicted the wrong wall:** it expected tier 3 to reopen on
evidence that the *handoff* was trapping timelines (the OpenChatCut failure);
what actually reopened it was the *window* — every complaint from working in
`lucid web` sat inside it, and the handoff was never reached. The
Electron-as-MCP-host friction it held up as tier 3's cost stayed true and
argued for a workspace rather than a desktop app.

## The cue table, step 1 of the layered timeline — 2026-08-08

PLAN.md § The layered timeline, build order step 1. `lucid.json` gets a
`cues` list — `{clip_id, word_index, asset}`, source-addressed and nothing
in timeline coordinates, matching `assemble_scream.py`'s `(word_index,
media_key)` table it is meant to eventually replace. Ops `cue_add`/`cue_rm`/
`cue_ls`, CLI `lucid cue add|rm|ls`, matching MCP tools — parity asserted the
usual way in `test_server_stdio.py`'s tool-registry and CLI-mapping checks.

- **`SCHEMA_VERSION` bumped 1 → 2**, the first bump since the field existed.
  `Project.open`'s exact-match check (CLAUDE.md: "a project written by a
  newer lucid is refused rather than silently misread") means this is a hard
  break for any project directory created before today — there are none in
  this repo, only `tmp_path` fixtures, so nothing needed migrating.
  **Correction, 2026-08-09:** true of the repo, false of the box — the three
  `~/lucid-dogfood` projects were v1 and had been unopenable since. § The
  schema migration.
- **`cue_add` reuses the word-index machinery `cut_by_transcript` already
  has** — `Transcript.span` for bounds-checking, `_context` for the "three
  words either side" echo (CLAUDE.md) — rather than growing a second
  validator. A cue at a word that does not exist raises the same
  `TranscriptError` a bad cut range would.
- **A second cue at the same word is refused, not overwritten.** The table
  has no ordering of its own beyond `(clip_id, word_index)`, so two assets
  claiming one word would need a silent tie-break; refusing forces an
  explicit `cue_rm` first instead.
- **`asset` is opaque.** Neither `cue_add` nor `cue_ls` resolves it against
  disk or a `card:`-key namespace — that is the shot projection's job (step
  2), the same division `assemble_scream.py`'s `CUES` table and
  `resolve_media()` already had.
- Nothing here touches `project.otio`; the cue table is manifest metadata
  until the shot projection reads it, so no snapshot/undo applies to it.

Verified against a synthetic fixture (unit tests) and the real stdio server
process end to end, plus a manual `lucid cue add|rm|ls` run over a real
ffprobe-imported clip. Not yet verified against the Scream VO itself — that
happens when step 2 seeds the table from `assemble_scream.py`'s 37 cues, per
the build order.

## The shot projection, step 2 of the layered timeline — 2026-08-08

PLAN.md § The layered timeline, build order step 2. `ops.build_shots` (CLI
`lucid shots`, MCP `build_shots`): reads the cue table, maps each cue's word
through the edit to a timeline frame, resolves `asset` to a checked path, and
runs each shot to the next cue — `assemble_scream.py`'s `build_shots` minus
the XML, per the plan's own instruction to take its arithmetic and not its
structure. Step 3 (refuse a cut cue) shipped inside this one rather than
after it: the frame arithmetic has nothing to return for a cut word, so the
refusal could not be deferred to a later step.

- **`asset` resolution is real, not deferred.** `cue_add`'s docstring
  committed to this at step 1 ("the shot projection resolves it, the same
  way `assemble_scream.py`'s CUES table did by hand"), so `_resolve_asset`
  does it here: `card:name` resolves under a new `assets/cards/` project
  directory (`project.py` gained `CARDS_DIR`, no schema bump needed — it is
  a directory, not a manifest field), anything else resolves as a
  registered video clip_id through `media.get_clip`/`media.media_path`.
  Both are checked against disk before `build_shots` returns, refusing a
  typo'd clip_id, an audio-only clip used as a picture asset, or a missing
  card rather than handing the MLT writer (step 4) a path that does not
  exist.
- **What step 2 deliberately does not do: per-clip playback cursors.**
  `assemble_scream.py`'s `build_shots` also decides *where in the source
  clip* each shot reads from, so three uses of one clip show three
  different stretches rather than repeating. That decision is about what
  the MLT writer actually shows for a duration this step already computed,
  so it stays with the XML that consumes it (step 4) — this step only
  answers *when* and *for how long*.
- **The first pass used the wrong addressing method, and real data caught
  it before a unit test could.** `Edit.timeline_time(clip_id, word.start)`
  — containment of the word's *start instant* — looked right (HISTORY.md §
  The multi-track costing spike had already validated `timeline_span`
  against `assemble_scream.py`'s own arithmetic, but `timeline_time` reads
  as the more direct method for a single point) and passed all nine unit
  tests, because every hand-built fixture word sat entirely inside one
  segment. Verified against the real Scream VO — a scratch copy of the real
  `Project/lucid-vo` project (67 segments, 310.875s) fed the real 37 cues
  from `assemble_scream.py`'s `CUES` table, the real clips from `Source/`,
  and the real cards from `Assets/Cards/` — word 115 ("here's", the
  surviving half of a false start: "Here's the thing I, here's the thing I
  want...") raised as cut. It is not cut: `is_cut`/`timeline_span` are an
  *overlap* test across the whole word, and word 115's own start (45.04s)
  sits in a 0.267s gap while its tail (to 46.44s) spills into the next
  surviving segment (from 45.2s) — exactly the CLAUDE.md rule ("survival is
  an overlap test against the kept ranges, never containment") stated for
  masking audio, now confirmed to bind shot projection too. Switched to
  `Edit.timeline_span(clip_id, word.start, word.end)`, which truncates to
  the surviving portion the same way `_word_placements` already does for
  `timeline_view`. A regression test
  (`test_build_shots_survives_a_word_whose_start_is_cut_but_whose_tail_overlaps`)
  locks in the shape: a word starting in a gap whose tail overlaps the next
  segment must resolve to that segment's start, not refuse.
- **Re-verified after the fix: 35 of 37 real cues agree with
  `assemble_scream.py`'s own arithmetic to sub-frame precision** (matching
  HISTORY.md § The multi-track costing spike's earlier -0.013s to +0.027s
  band), zero cut/survive disagreements. The remaining two (words 430, 433)
  sit ~0.02–0.034s apart — about one frame at 30fps, and both land entirely
  inside the same surviving segment in both computations, so the gap is
  accumulated floating-point drift between OTIO's rational-time storage and
  the reference script's direct timecode parsing, not a disagreement about
  what survived or where a cut falls. Verification was against a disposable
  scratch copy — the real `Project/lucid-vo` manifest on the NAS was read,
  never written; seeding a persistent cue table there is still open, noted
  in PLAN.md.
- Ten unit tests (`tests/test_ops_shots.py`) cover the arithmetic, the
  overlap-vs-containment regression above, the monotonic-tie refusal (two
  cues resolving to the same instant), and every asset-resolution failure
  mode; parity asserted the usual way in `test_server_stdio.py`.

## The MLT writer, step 4 of the layered timeline — 2026-08-08

PLAN.md § The layered timeline, build order step 4. New module
`src/lucid/mlt.py`: `Entry`, `plan_picture`, `document`, `declared_frames`,
`write`. `ops.export` grew a second road — a multi-source timeline is now
written by lucid as MLT instead of being handed to auto-editor, which refuses
to export a second `src` (exit 2) and renders one at 720x576 while exiting 0.

- **Which writer runs is a property of the project, never of an argument.**
  `_is_layered` says yes to a cue table *or* to an edit naming two clip_ids —
  both are two `src` files, and the failure they route around is silent, so a
  flag that can be left off is not a safe way to choose. The reply now carries
  `"writer": "mlt"` or `"writer": "auto-editor"` so the road taken is visible
  without inspecting the file. Single-source export is untouched: same
  auto-editor call, same output, and `test_ops_export_mlt.py` asserts that
  from the other side.
- **Rendering a multi-source timeline refuses rather than falling back.**
  That is step 5, and until it lands the honest answer is an error naming
  720x576 — an auto-editor fallback would write a file that looks like a
  success.
- **Positions are frame integers, not `HH:MM:SS.mmm`.** Kdenlive and
  auto-editor both write clock time; millisecond text cannot name a 1/29.97 s
  edge, and it is the form that cost auto-editor its tail frame. MLT parses a
  bare integer as a frame position — verified by rendering, not assumed.
- **`declared_frames()` is the assertion PLAN.md asked for instead of a
  comment.** melt renders to the longest declared length in the document, so
  every one of them (the two track tractors' `out`, the sequence tractor's,
  the outer project tractor's and its track's, and the black background
  producer's `length`) is written from one number, then **read back off the
  built tree** and checked before the document is returned. A value that was
  right in a variable and wrong in an attribute is the exact bug this exists
  for. A still image's four-hour `qimage` length is deliberately not swept —
  it is not a statement about the timeline.
- **No `<blank>`, ever.** Both playlists are contiguous by construction, and a
  picture lane whose frames do not sum to exactly the edit's total is refused
  in both directions: short pads with blank (runtime every downstream cue is
  blind to), long runs the render past the audio.
- **`build_shots` grew `fps`.** It answered on the project's timebase, which
  for an audio-only project is 1000 — milliseconds, not frames. The export
  passes its own rate straight through rather than converting the answer
  afterwards, so the two halves of the document are quantised on one grid by
  construction. CLI `lucid shots --fps`, MCP `build_shots(fps=)`.
- **The per-clip playback cursor landed here, as step 2 said it would.**
  `plan_picture` carries a cursor per asset so a clip used three times shows
  three different stretches; a shot that would overrun rewinds to the start
  rather than clamping (a clamp holds a frozen frame, which reads as a render
  bug rather than a re-use), and a shot longer than its whole asset refuses.
  `_resolve_asset` now returns `asset_duration` for exactly this — the cursor
  cannot tell a re-use from an overrun without it.
- **`set.test_video` is per source, not per document.** The first pass took a
  single `audio_has_video` flag; a wav and an mp4 on the same track cannot
  answer that question once, and answering it wrong tells MLT to render black
  frames off the wav. It is a field on `Entry` now.
- **The sequence uuid is derived from the project name, not random**, so the
  same project exported twice is byte-identical and a diff shows what changed
  in the edit.

### Verified against melt, not just against the tests

Both spikes under `$HOME` (the flatpak cannot see `/tmp`, and exits 0 having
read nothing — CLAUDE.md). The second one went through the real `ops.export`
on a real project with two VO segments, three cues, and a card:

| | result |
|---|---|
| `melt -consumer xml` frame count | **150**, against 150 declared |
| render | **1920x1080**, **150 frames**, h264 + aac |
| picture at each cue | film / card / film — the card measured YAVG 62, UAVG 103, VAVG 238, i.e. the actual red card, so `qtblend` loaded and composited |
| the second film shot | read from source frame 45, not 0 — the cursor advanced |
| `check_frames` vs the project **and** vs the render | `delta: 0`, `agrees: true`, no tail-frame note |

That last row is the one worth keeping: **auto-editor's `--export kdenlive`
output reports one frame more than the timeline holds and renders a black
frame for it (`picture.KNOWN_TAIL_FRAME`); lucid's own MLT does not.** The
existing picture-side check validates the new writer with no special-casing.

**A measured red herring, recorded so it is not re-investigated.** The first
render came back 3 dB below its source and that looked exactly like a 50/50
`mix` transition where an additive one was wanted. It is not: sweeping the
transition through `sum=1`, `start/end=1`, `level=1` and no `sum` at all gave
`-24.1 dB` every time, and re-measuring showed the *source* wav was mono while
the render was stereo — ffmpeg's own mono→stereo conversion applies the same
-3 dB. Rendering from a stereo source of the same tone: -24.1 dB in, -24.1 dB
out. The mix is at unity and always was.

### What this does not cover

- **The render (step 5) and the picture lane in the web UI (step 6)** are
  still ahead. The UI lane stays illegal until `export` can *render* what it
  would draw, not merely describe it (CLAUDE.md). *Step 5 landed the same
  day — the next section.*
- **Kdenlive opening the file is unverified.** The document carries the bin,
  the `kdenlive:id` linkage and the two-playlists-per-track shape Kdenlive
  writes itself, but nothing here has opened it in the GUI. melt is the
  consumer this step was built for.
- **Seeding the real Scream cue table is still open** — same note as step 2:
  the NAS project's manifest has been read, never written. *Closed at step 5,
  and it turned out to name a different project — see below.*

## Rendering through `melt`, step 5 of the layered timeline — 2026-08-08

PLAN.md § The layered timeline, build order step 5. `export(export_format=None)`
on a multi-source timeline **renders it** now, where step 4 refused: lucid
writes the MLT, hands it to `melt`, and then measures the file that came out.
New in `picture.py`: `scratch()`, `render()`, `render_problems()`. `ops` grew
`_build_mlt`/`_render_mlt` — one document builder, so the thing rendered is the
same document `export` would have written rather than a second construction of
it — and `timeline_view` grew `layered`.

- **The exit code is trusted for nothing, in both directions.** melt exits 0
  having rendered nothing, and exits 0 having rendered the wrong length, so the
  render is bracketed by two checks that read numbers instead. *Before* the
  encode: `project_frames` (`-consumer xml`) resolves the document without
  encoding a frame, and a disagreement there refuses rather than spending the
  encode to discover it. *After*: ffprobe's resolution and packet count against
  what the timeline promised. A render that disagrees **is not copied to the
  destination** — it stays in its scratch directory and the error names it,
  because the evidence for what melt did is the file it wrote.
- **The three traps are handled, not hoped past** (HISTORY.md § 4): the
  consumer gets `vcodec crf preset acodec` and nothing else, a missing display
  is a refusal rather than a warning, and everything melt has to read or write
  lives under `$HOME`. The `systemd-run --user --scope` memory cap from
  `goodsometimes/scripts/render.py` came across too, and says so in the reply
  (`memory_cap`) rather than being assumed.
- **The fourth trap, which the first three imply and none of them states:
  `WAYLAND_DISPLAY` is not a display.** It is a socket *name*, resolved under
  `XDG_RUNTIME_DIR`, and the two have to travel together. `display_env()` found
  the socket and exported only the name, which is fine from a shell and fatal
  from a **scrubbed environment** — and scrubbed is what the MCP stdio
  transport hands its server: the SDK's `DEFAULT_INHERITED_ENV_VARS` is exactly
  `HOME, LOGNAME, PATH, SHELL, TERM, USER` on POSIX — read off the installed
  package, not remembered — and `XDG_RUNTIME_DIR` is not in it.
  Measured: `Failed to create wl_display`, then no Qt platform plugin at all,
  then melt **aborts printing nothing** — which the empty-output guard reads as
  "the project could not be loaded", pointing at the wrong thing entirely. The
  fix is one line and the finding is worth more than the fix: the first stdio
  test to render for real is what surfaced it, and nothing that ran melt from a
  shell ever could have.
- **Staged, then copied.** The render is written into `~/lucid-render/<run>/`
  and copied to the destination only once it agrees. A render that dies halfway
  would otherwise leave a half-muxed file at the destination that looks
  finished — and the destination may be on the NAS, which the flatpak's writes
  should not be aimed at mid-encode either.
  - **Nothing ever removes a staging directory, and that is deliberate for the
    failures and untidy for the successes.** A disagreeing render is *meant* to
    stay put — the bullet above is the reason, the file being the evidence — but
    a successful one leaves its directory behind too. Measured 2026-08-10 after
    two days of heavy rendering: **51 directories, 408 KB total**, each holding
    one ~4.7 KB `timeline.mlt` and no media, because the output was copied out
    and the scratch encode removed with it. So this is tidiness, not disk, and
    it is recorded here rather than opened as work — the number is the point,
    since "renders leave scratch behind" sounds like a space problem and is off
    by about four orders of magnitude. The kept `.mlt` files are also the only
    on-disk record of what document each render was given.
- **The window picks a container that can hold picture.** `RenderJob` named its
  output after the primary clip's media, which on a layered timeline is the VO's
  `.wav` — melt would have been asked to mux h264 into a wav. It asks
  `ops.timeline_view` whether the timeline is layered rather than reading the
  manifest itself; the UI never decides (CLAUDE.md).

### Seeded and rendered against the real material, which moved which project that means

**The 37 cues do not address `Project/lucid-vo`.** `assemble_scream.py` says so
in a comment that had not been read against lucid's own project: the indices are
into `VO/VO2-windowed.json`, the **re-recorded** VO, re-found by phrase after
the re-record moved every index. `lucid-vo` holds the v1 VO and a 929-word
transcript, and the table runs to word 1118 — so seeding it there would not have
failed loudly, it would have put 37 cues on 37 wrong words. The seeded project
is a new one on `VO2.wav` + the windowed transcript (1150 words, word 18 =
"The", word 83 = "might" — the phrases the table's own comments name).

| | result |
|---|---|
| timeline | 73 segments, 410.963s — a plain silence cut, so the retakes the finished VO trimmed are still in |
| the real 37 cues | **all 37 added, none refused**; 9 film clips from `Source/`, 12 cards from `Assets/Cards/` |
| distinct sources in the document | **22** |
| `melt -consumer xml`, before the encode | **9856** frames, against 9856 declared |
| the render | **1920x816**, **9856 frames**, h264 + aac, `agrees: true` |
| wall clock | **102s** for 411s of video, inside the 6G `systemd-run` cap |
| `check_frames` against the render | `delta: 0`, `agrees: true` |
| the picture at a card cue (190.9s) | the actual "Scream* — two fans of the movies" card, pillarboxed into the canvas — so `qimage` and `qtblend` both loaded |
| the picture at a film cue (405.0s) | the Scream 4 car, full frame |

**The one refusal was real, and it was `plan_picture`'s**: word 318's shot ran
34.6s against a 30.1s clip, because this timeline keeps retakes the shot plan
was written against a trimmed VO for. Split with one extra cue on the same
asset — mechanical, not editorial, since the cursor rewinds and each half fits.
That is the refusal working: the alternative is a frozen frame for four seconds
and exit 0.

**`check_black` found one 3.29s run and it is the card, not a hole.** The
reveal-scream2022 card is near-black by design, so a luma scan reads it as
black; the frame pulled at 190.9s has the type on it. Worth stating because the
run reports `explained: false` and the honest reading of that is "a dark card",
not "a missing shot" — the check cannot tell them apart and does not pretend to.

### What this does not cover

- **Kdenlive opening the file is still unverified** — unchanged from step 4.
- **The canvas comes from the first picture clip**, and on this material that
  is a cropped 1920x816 film scope frame rather than the 1920x1080 the
  hand-built assembly used. The render agrees with the profile it declared, so
  every check passes — but the consequence is visible: the film fills the frame
  and the 16:9 cards are pillarboxed into it, where the assembly put the film
  in a letterbox and gave the cards the full frame. Which is right is editorial
  (`_mlt_resolution`'s rule that cards never size the canvas is doing exactly
  what it says), and real material has now raised it. Left as a question rather
  than answered by a renderer.
- **The picture lane in the web UI (step 6)** is what this makes legal. It was
  illegal until `export` could render what the lane would draw, and now it can.

## The picture lane, step 6 of the layered timeline — 2026-08-08

PLAN.md § The layered timeline, build order step 6, and the last of the six.
The web UI draws **V2**, the cue table's picture, over the edit's own lanes.
It was illegal until step 5 — the timeline may not draw a lane `export` cannot
produce — and became legal the moment `export` started rendering a layered
timeline through MLT and `melt`. New: `ops._picture_plan`, `timeline_view`'s
`shots`/`shots_rate`/`shots_error`, and `buildPictureRow` in `timeline.js`.

- **The lane is drawn from the *planned* shots, not the projection, and that
  turned out to be what the rule actually demanded.** `build_shots` (step 2)
  is perfectly happy with a shot longer than the asset it points at;
  `mlt.plan_picture` (step 4) refuses it. A lane drawn from `build_shots`
  would therefore have put a block on screen for a shot `export` refuses to
  render — the same class of lie as drawing a track the renderer degrades,
  arrived at from the opposite direction. So `_picture_plan` runs both steps
  at `export`'s own rate and `timeline_view` reports its answer, which also
  makes `_build_mlt` and the view share one construction rather than two.
  This is not hypothetical: the real refusal on the Scream assembly was
  `plan_picture`'s, at word 318 (§ Rendering through `melt`).
- **A refusal is reported, not raised.** `timeline_view` catches the picture
  plan's five deliberate failures and answers `shots: null` plus a
  `shots_error` string; the lane draws the message across itself in red and
  every other lane keeps working. The reasoning is that the window is *how a
  person finds the cue to fix* — a view that raised would take down the one
  tool for repairing the thing that broke it. Verified live: cutting word 83
  out from under its cue drew `picture refused — cue at 'vo' word 83
  ('might') was cut from the edit — remove or move the cue (cue_rm/cue_add)
  before projecting shots`, with the transcript, waveform and captions intact
  beside it.
- **`MLTError` was in neither `_EXPECTED` tuple**, so `lucid export` on that
  real word-318 refusal printed a traceback rather than the sentence it had
  gone to the trouble of writing. Added to the CLI's and the web UI's, found
  only because the view now catches the same family.
- **The tooltip carries the two facts only the planner knows**: where inside
  an asset the shot reads from, and which cue put it there. The first is the
  re-use fact — a clip cued three times shows three different stretches of
  itself, and a row of identical blocks cannot say so. The second is the word
  index, which is the thing a person edits to move the shot, and which never
  renumbers. The first shot also says out loud that it does not start at its
  own cue: the picture track is contiguous by construction, so whichever cue
  resolves first covers from the open.
- **The picture runs on `export`'s frame grid and the ruler on the edit's
  seconds, so V2 is legitimately a hair longer than every other lane** —
  411.077s against 410.963s on the Scream assembly, which is `frame_total`
  versus a summed duration (CLAUDE.md). The lane is sized to whichever is
  longer rather than clipped to hide it. At zoom 4 that is a visible 1.7px of
  overhang and it is telling the truth.

### Verified in a real browser, against the real 38-cue project

`~/lucid-scream-v2/proj` — the VO2 project step 5 seeded — driven over CDP
(wiki `tooling.md` § Headless browser; the one-shot `--screenshot` route still
hangs on the page's open `EventSource`).

| | result |
|---|---|
| lanes drawn | **V2, A1, CC** — no V1, because the VO clip is audio-only |
| V2 blocks | **38**, contiguous, **13** tinted as held cards and 25 as film |
| tooltip, shot 1 | `cold-open · 0:00.0–0:28.9 · 692 frames @ 23.976fps` / `reads the asset from 0:00.0` / `cue: vo word 18 — The` |
| tooltip, shot 3 | `reads the asset from 0:28.9` — the re-use cursor, visible |
| click-to-seek on V2 | seeks the transport like every other lane (246.601s) |
| zoom to 4× | 38 blocks preserved, lane 6065.7px against A1's 6064.0px |
| the refusal path | full-width red strip naming cue, word, text and the fix |

**Two measurements that look like defects and are not, both checked against
the lanes that predate this one.** A 10px minimum block width makes one pair
of V2 blocks overlap by 2px — but `.clip-block`'s padding has always floored
the width there, and A1's own segment blocks overlap in 13 places for the same
reason. And the body scrolls 128px horizontally at 1600px wide — identical
with V2 removed from the DOM, and the overflowing nodes are the top bar's.
Neither is step 6's, and both are recorded here so the next person measuring
them does not attribute them to it.

### What this does not cover

- **The lane is a map, not a viewer.** Clicking a shot seeks the transport,
  which plays the VO through the edit; the preview pane stays black, because
  it still plays one clip's media. Showing the shot under the playhead is the
  video preview proxy (a wiki row), and it is what would make V2 a picture
  rather than a plan of one.
- **Nothing here authors a cue.** The page draws the lane; cues are still
  added by CLI, MCP or the agent panel. Cue editing in the window belongs to
  the parity queue's assets pane, not to this step.

## The look pass, head of the Daydream parity queue — 2026-08-08

The item DAYDREAM.md § Build order named first and gated on nothing: warm
tokens in light **and** dark, vendored fonts, the three type voices, the
pastel timeline, top-bar parity. The palette is Daydream's own HSL triplets,
copied verbatim from DAYDREAM.md § Tokens — the system, not the assets; the
name, logo and copy are not taken and every typeface involved is OFL.

### The theme mechanism, and why there is no second palette

`light-dark()` on every token, declared once in `:root`, with `color-scheme`
as the entire switch. No `@media (prefers-color-scheme: dark)` block
redefining the palette and no `[data-theme]` block either — the usual shape
for this stores the colours twice, and two copies is how a token gets edited
in one theme and not the other. `color-scheme` also repaints the browser's own
scrollbars and form widgets, which a hand-rolled swap does not.

`theme.js` is therefore tiny and holds no colours: it sets `data-theme` and
raises an event. It is a **classic script in `<head>`, not a module** —
a module is deferred, so it would run after the first paint and the toggle
would announce itself with a flash on every load. Three states, not two:
`auto` is a real answer, and a two-state toggle makes the first click a
permanent opt-out of the OS preference with no way back.

Fonts are vendored as woff2 beside `app.css` (`FONTS.md` has provenance and
licences). Not a preference — this server sends `default-src 'self'`, so a CDN
`<link>` would be refused and the page would silently fall back to a system
font. Flat filenames, because `_send_static` serves a name and never a path.

### Three defects the browser found and no test could

Each produced a page that *looked* fine from the outside, which is the
recurring shape of this repo's UI bugs.

- **A canvas fill cannot read a colour token.**
  `getPropertyValue('--waveform-ink')` returns the literal text
  `light-dark(…)`; `fillStyle` cannot parse it, and **an unparseable
  `fillStyle` is silently ignored**, so the canvas keeps the colour it already
  had — black. Invisible in the light theme, black-on-black in the dark one.
  The fix is to put the colour on the canvas element as a real `color` and
  read `getComputedStyle(canvas).color`, which is resolved to `rgba(…)` before
  JS sees it. Measured after: light `rgba(20, 19, 15, 0.5)`, dark
  `rgba(249, 249, 245, 0.35)`, mean painted pixel `(13,13,9)` and
  `(249,249,247)` respectively.
- **A canvas does not repaint itself on a theme change.** CSS does; a canvas
  holds whatever ink it was drawn with. Hence `theme.js`'s `lucid:theme`
  event — timeline.js re-renders on it and player.js drops its cached bar
  colour. It fires for an OS preference change too, because in `auto` that is
  a theme change with no click behind it.
- **The 128px horizontal overflow was a grid track, and it predated this.**
  Step 6 recorded it as "the overflowing nodes are the top bar's" and left it;
  measured at HEAD it is 1728px of page in a 1600px window, unchanged by the
  look pass. The cause is `body`'s implicit `auto` grid column, which never
  shrinks below its items' min-content — so the timeline's content width
  propagated up and pushed Export off the right edge. `minmax(0, 1fr)` on the
  body grid plus `min-width: 0` on `.track-lanes` fixes it; `overflow: hidden`
  on `body` is why it never showed a scrollbar to give itself away.

A fourth, smaller: the favicon was `data:,` — added to avoid a `/favicon.ico`
404, but CSP counts a data: URI as a foreign image, so **every load logged a
security error**. Now a real `/static/favicon.svg`. The page's console is
clean.

### Verified in a real browser, against the real Scream VO

`~/lucid-scream-v2/proj` over CDP, 1600×1000 (wiki `tooling.md` § Headless
browser), read back from computed style rather than from the stylesheet.

| | light | dark |
|---|---|---|
| page background | `rgb(251, 251, 249)` | `rgb(19, 18, 17)` |
| V2 / A1 / CC clip fills | `219,210,238` · `201,232,218` · `235,228,214` | `74,64,100` · `52,81,67` · `67,63,55` |
| waveform ink | `rgba(20, 19, 15, 0.5)` | `rgba(249, 249, 245, 0.35)` |
| level-display bars | `rgb(36, 97, 188)` | `rgb(115, 168, 231)` |
| horizontal overflow | none | none |
| console entries | none | none |

Body in Geist Sans, the brand in italic Source Serif 4, every timecode and
word index in JetBrains Mono — all three families reported `loaded` by
`document.fonts`. The toggle cycles auto → light → dark → auto with the
background following it, and `Export` is the one filled button, near-black on
paper and inverting to near-white on the dark theme.

### What the look pass did not include

The small items DAYDREAM.md § Build order lists as riding it are **not** done:
model label, per-turn thumbs, `@`-mentions, inline pause markers, `restore`,
export presets. Two are more than cosmetic and want their own step —
`restore` is a real op needing CLI + MCP parity and a `plan` echo, and pause
markers have the duration-inflation rule to respect (a gap computed from word
boundaries under-reports, never over-reports, so a suppressed marker is
cosmetic and an invented one would be a lie).

They shipped later the same day, which is why this paragraph needs a pointer
rather than a correction: § The head of the parity queue.

Filmstrip thumbnails and clip *filename* labels are also still open. The
blocks label by `clip_id`, which is deliberate for now: it is the name every
other surface in lucid addresses a clip by, and a filename would make the lane
disagree with the CLI.

## The head of the parity queue, six items — 2026-08-08

The six § The look pass did not include, built as one pass: model label,
per-turn thumbs, `@`-mentions, inline pause markers, `restore`, export presets.
DAYDREAM.md § Build order had them as the queue's head "gated on nothing", and
four of them were exactly that. The two it had already flagged as more than
cosmetic each cost a design decision, and a third — export presets, filed as
"cheap, anytime" — turned out to be the one with a wall behind it.

### `restore` — the removed ranges were never stored

DAYDREAM.md specified this as "`Edit` stores its removed ranges, so un-removing
a *specific* range is a real op". **It does not store them.** `Edit` is an
ordered list of surviving `Segment`s and nothing else, so the first job was
deriving what is missing rather than reading it. `Edit.gaps(clip_id, duration)`
walks that clip's merged segments against its registered length and returns the
complement — head, interior and tail fall out of one pass, so a `keep_only`
that dropped the opening needs no special case, which is the half a stored
range table would have missed anyway.

**It does not touch the subtractive invariant, and the argument matters more
than the code.** `restore` is bounded by `gaps()`: only source time the
recording actually has, and does not currently play, can come back. The
timeline stays a subset of the source at every step, which is the property
`remove` and `keep_only` already uphold — `restore` walks it backward rather
than widening it. That is what separates it from `vo_extend` (PLAN.md § Parked),
which splices in material the source never had and remains parked.

Two things the derivation forced:

- **A closed gap must not leave two segments behind.** Restoring an interior
  gap in full makes its neighbours source-adjacent *and* timeline-adjacent, and
  `_seams` reads that pair as a cut with zero material removed — a phantom seam
  drawn across a join that no longer exists. `_insert_piece` merges into either
  neighbour it now touches exactly.
- **It refuses rather than guesses.** A clip with no surviving segment has
  nowhere well-defined to be spliced back next to, and a clip whose segments are
  not contiguous in the edit is an interleaved multi-source timeline nothing
  ships yet. Both raise. Every operation in the codebase today produces one
  contiguous run per clip; the refusal exists so the day that stops being true
  is loud.

Word-addressed, with the standard echo and `plan` for free — it resolves ranges
through `_echo`/`_context`/`_pad_reach` exactly as `cut_by_transcript` does, so
the three-words-either-side rule (CLAUDE.md) cost nothing. There is no
suspect-duration gate: restoring across a suspect boundary is the *fix*, not the
mistake the gate exists to catch. `--pad` mirrors the pad the original cut used,
so the sliver comes back too.

### Pause markers, and the one gap computation

`[N.Ns]` between word spans, from `ops._gap_after` — which `_paragraphs`'
opportunistic silence arm now calls too, because DAYDREAM.md asked for both to
be derived from the same place and two gap computations is how they drift. The
duration rule (CLAUDE.md) is the whole reason the field is safe: whisper
inflates the *end* of the word following a swallowed retake, and a later `end`
can only shrink a gap measured to the next word's `start`. A bad transcript
suppresses a marker; it cannot invent one.

The marker carries `{duration, present}` and `present` is an overlap test
against the kept ranges like everything else — a pause can be cut while both
flanking words survive, which is what `cut_by_time` on a silence does.

Selecting through a marker is the part Daydream's own docs show and the part
with state in it. A `.pause` node resolves to the index of the word it trails
and never becomes an addressable bound of its own; when it is the selection's
*trailing* edge, the cut extends through the pause (`--through-pause`,
`through_pause`). The bug in the first cut of that, found in review: the flag
was recomputed from whichever node the gesture moved, so shift-clicking
leftward to add context — a gesture that does not move `last` at all — silently
cancelled a trailing pause the user had already chosen. `trailingPause()` now
asks which *bound* sits at `last` instead of which node moved, which is what
the flag always meant.

### Export presets, and the preset that is not there

Filed as "an afternoon". The afternoon was real; the costing was not. DAYDREAM.md
says presets "map onto `ops.export`'s existing arguments as named bundles", and
`export` had no resolution or quality arguments to bundle — it took `output`,
`export_format` and `fps`.

`youtube` and `web` ship. Both are bundles over the same four consumer keys
`picture.RENDER_ARGS` already hardcodes (`vcodec`/`crf`/`preset`/`acodec`), and
`youtube` reproduces `RENDER_ARGS` byte for byte, so naming it changes nothing
about what melt already does. That narrowness is not tidiness: § 4 measured a
melt consumer reaching 14.6 GB and freezing the machine, `width`/`height`/`ab`
were in the combination, and nobody has since isolated which addition caused it.
A preset that widens the consumer is a memory-growth experiment wearing a
feature's clothes. `custom` means "apply this resolution, quality at the
`youtube` default", and refuses with no resolution, because customising nothing
is a caller mistake rather than a legitimate no-op.

**There is no `tiktok-reels`, and that is the finding rather than an omission.**
9:16 is mechanically producible on the single-source path — `-res` was run and
a real 320x240 clip came back as 608x1080, confirmed with ffprobe — but only as
the 16:9 frame pillarboxed, never a filled or reframed vertical video. The
latter is DAYDREAM.md § Aspect swap, deferred on purpose because it touches the
project model, both render paths and the preview letterbox. On the melt path a
resolution override is refused outright for the memory reason above, so a 9:16
preset could not have been offered consistently across the two writers even as a
pillarbox. Shipping a platform's name over a quiet letterbox is the
correct-pixels-wrong-video failure this repo keeps writing rules against.

Three refusals guard the rest, all before any subprocess runs: a preset with an
NLE `export_format` (an MLT handoff has no bitrate), a resolution on a layered
project, and an unknown name — which answers with the available list *and* the
aspect reasoning, so the next person to reach for `tiktok-reels` gets told why.

**The exit code still proves nothing**, so a resolution request is staged: the
single-source path renders into a temp dir, probes the result, and runs it
through `picture.render_problems` before copying to the destination — the same
stage/probe/copy-only-if-it-agrees shape `picture.render` already uses on the
melt side. And one thing only the real plumbing could have said: those four
flags are fatal, not merely useless, on a project with no picture —
`Could not open encoder 'aac'` against a `.wav` destination — so an audio-only
project skips them and says so in `notes`.

### The panel cosmetics, and the one that was not

Model label, thumbs, `@`-mentions, plus `Start New Task`, which DAYDREAM.md said
"needs only the affordance" and nearly did. None added a tool, widened the
allowlist, or gave the subprocess a new path to the project — PLAN.md § The
agent panel, in mechanism did not move.

- **The model label rides the stream that was already there.** `stream-json`'s
  `init` message carries the model; the panel was dropping it. No endpoint.
- **Thumbs append one JSON line** to `cache/agent_thumbs.jsonl`, carrying the
  session and turn ids so a later reader can tell *which* turn was rated. It is
  a mutation and obeys the `Host` and content-type guards like every other POST,
  but it must not bump the revision or fire `project-changed` — it does not
  touch `project.otio`, and a test asserts the SSE stream stays silent by
  waiting for an event that never comes.
- **`@`-mentions read `view.clips`**, which the view already ships. No endpoint,
  no capability: the agent already reaches media through the tools.
- **`Start New Task` was the one with a real edge.** Killing the subprocess mid
  turn trips the stdout pump's silent-exit branch, which publishes a synthetic
  `error_no_output` result — so a deliberate reset announced itself as a crash.
  A suppress-once flag, set only when a live process is actually being killed,
  keeps a genuine later crash reportable.

### What the review found, and where

Three reviewers over the finished tree — correctness, conventions, and a real
browser. Two blockers, two real, two nits; the conventions pass also caught a
builder having run a non-plan `restore` against `~/lucid-scream-v2/proj` itself
rather than the scratch copy its own report described, which is why that project
briefly read 74 segments. Reverted; it is back at 73 and md5
`705540da92323bee24ef6565740b6a24`.

The two that were defects in the shipped code, both invisible to every test:

- **The preview pane disappeared at 800px, and 800px is half a 1600px display.**
  `#workspace` was `26rem 1fr 24rem` — 416 + 384 is exactly 800 — and a bare
  `1fr` between two fixed tracks resolves to **zero** rather than squeezing
  either neighbour. So the player, transport and clock vanished with no
  scrollbar, no collapsed affordance and nothing in the console, and stayed gone
  below that width. This is the second time a grid track has silently eaten this
  page (§ The look pass found `body`'s `auto` column pushing Export off the
  right edge) and the same thing hid it both times: `overflow: hidden` on `body`
  means the page never grows a scrollbar to give itself away. Three `minmax()`es
  now, with the side panes giving way first — the picture is the last thing to
  shrink, which is the priority § Layout is arguing for at every other width.

  Measured over CDP after the fix, transcript / preview / agent:

  | window | 1600 | 1400 | 1100 | 900 | 800 | 700 |
  |---|---|---|---|---|---|---|
  | transcript | 416 | 416 | 412 | 298 | 248 | 208 |
  | **preview** | **800** | **600** | **304** | **304** | **304** | **304** |
  | agent | 384 | 384 | 384 | 298 | 248 | 208 |

  1600 and 1400 are byte-identical to what shipped, which was the constraint —
  the fix is not allowed to restyle the widths anyone actually uses. At 700 the
  floors are reached and the page scrolls by 32px, which is at least visible.

- **A zero-width word on a segment's closing boundary read as cut.** Whisper
  emits `start == end` often enough, and the last word of a transcript lands on
  the last segment's end, where the half-open `[start, end)` test says "gone"
  about material plainly still there. Pre-existing, and `restore` is what made
  it legible: restoring words 1148–1149 of the real VO reported the full 1.4s
  back and `lucid status` agreed, while the transcript kept drawing 1149 struck.
  `Edit.timeline_time` gained `closed_end=`, default off so every range caller
  keeps the convention it was written against, and `_word_placements`' zero-width
  branch is its one caller — for an *instant* the boundary belongs to the
  material ending there; for a range it would double-count the join.

### Verified

`uv run ruff check src tests` clean, and the full suite at **463 passed**, up
from 406 — 57 new tests, and `git diff --numstat tests/` reports **zero deleted
lines** across all four modified files, which is the number that matters
(CLAUDE.md: a test rewritten to agree with the code guards nothing).

Against the real projects rather than fixtures: `~/lucid-scream-v2/proj`, the
seeded VO2 project — 1150 words, 73 segments — carries 101 pause markers, and
`lucid cut vo 15:17 --plan` versus `--plan --through-pause` moves `source_end`
from 11.08 to 13.62, exactly the 2.54s pause after word 17, while `word_end`
does not move at all. Restore round-trips on a copy: 73 → 74 segments, +1.4s,
words 1148 *and* 1149 both present afterwards.

In a real browser over CDP (wiki `tooling.md` § Headless browser): the pause
markers read in both themes, the Restore affordance appears over struck text and
the change survives a shell-side `lucid status`, the model label degrades
honestly before any turn and shows a real id after one, `@` completes over the
project's own clips, thumbs persist to disk, the preset dropdown reveals its
resolution field for `custom`, and playback ran ~212s across dozens of cut seams
with no console errors. The trailing-pause fix was re-checked the same way, as a
real gesture: click the `[2.5s]` marker after word 17, shift-click word 14, and
the marker keeps its selection with four words selected.

### What this leaves

The parity queue's head is clear. `tiktok-reels` is the one named thing that did
not ship and it is blocked on DAYDREAM.md § Aspect swap, not on effort.
Filmstrip thumbnails, clip filename labels, and snap/link/lock toggles are still
open on their own gates (§ The look pass). The next ranked item is caption
styling.

## The preview picture layer — V2 stops being a plan of one — 2026-08-09

Step 6 drew the picture lane and said so plainly in its own § What this does not
cover: "clicking a shot seeks the transport, which plays the VO through the
edit; the preview pane stays black, because it still plays one clip's media."
That sentence is now false. The viewer shows the shot under the playhead.

### The wiki row was two items, and only one of them was blocked

The open row read "the video preview proxy (`hev1`/Main 10 is browser-unplayable
…), which waits on a project with real footage", and the two halves of that turn
out to be independent:

- **Showing the shot** needed no transcode at all. Every piece of the Scream
  footage is H.264 High, `avc1`, `yuv420p` — measured, all ten clips — so the
  browser plays the assets as they sit on the NAS. What was missing was a second
  element in `#viewer` and something to drive it.
- **Making an unplayable asset playable** is a transcode, and it is deferred
  with its reasons written down below rather than built blind.

So the row's gate — "waits on a project with real footage" — was satisfied all
along by `~/lucid-scream-v2/proj`, and what it was actually waiting on was
somebody separating the two.

### The layer reads `shots`, and that is the whole honesty argument

`#picture` holds a `<video>` and an `<img>`, stacked over `#media` because that
is the order `melt` composites V2 over the edit's own track. Every frame,
`paintPicture(t)` finds the shot containing `now()` and shows it: an `<img>` for
a card, a `<video>` seeked to `src_start + (t - shot.start)` for a clip.

`src_start` is the field that makes this more than a slideshow. It is
`mlt.plan_picture`'s per-asset cursor, already in `timeline_view`'s projection
(CLAUDE.md: the lane draws the plan, never `build_shots`), so **a clip used three
times previews from three different places inside it** — exactly where the writer
will read on export. A layer that reloaded each asset from its head would look
fine and be a different film.

The audio is never this element's. `muted` at the source and the transport is
the only clock: `now()` derives from `#media`'s `currentTime` through the edit,
and the picture is corrected back to it whenever it drifts past 0.15s (0.04s when
paused, where nothing is jittering). Two media elements cannot be frame-locked;
one of them being authoritative is what keeps that from mattering.

### A contentless error, turned into a sentence

A `<video>` that cannot decode its source fires one `error` event carrying
nothing, and shows black — **indistinguishable from a black frame the edit
meant.** That is the failure mode the codec half of the row was really about, and
it is closed even though the transcode is not: `media.playability()` probes the
file and `GET /api/preview/<asset>` reports the reason, which the layer draws
over the viewer. The front end asks only after an error, once per asset.

Verified by encoding each case rather than by reasoning about codec strings:

| file | verdict |
|---|---|
| H.264 High / `avc1` / `yuv420p` in `.mp4` | playable |
| PCM `.wav` (the VO case) | playable |
| HEVC tagged `hev1` | `video codec hevc (tagged hev1) is not decodable in a browser here` |
| H.264 **High 10** / `yuv420p10le` | `High 10 at yuv420p10le is beyond a browser's 8-bit 4:2:0 decoder` |
| H.264 in `.mkv` | `.mkv is not a container browsers open` |
| `ac3` audio in `.mp4` | `audio codec ac3 is not decodable in a browser here` |

Three of those pass a naive check. `High 10` is `codec_name: h264`, so the pixel
format has to be a separate gate; the `.mkv` has a perfectly good H.264 stream
and the container refuses it anyway; the `ac3` file's video is fine and the
browser still plays nothing, because there is no partial state where the picture
shows and the sound is missing. The verdict is **reported, not enforced** —
`/api/asset/` streams a refused file anyway, since the browser is the authority
and this list is a prediction.

`preview_source` is deliberately wider than `_resolve_asset`, which refuses a
clip with no video because a picture *cue* pointing at a VO is a mistake. The
viewer's other caller is the transport, and on a VO project the clip it needs is
exactly the audio-only one. Same resolution, opposite idea of a valid answer.

### Verified

`ruff check src tests` clean; suite **477 passed**, up from 463 — 14 new tests,
seven in the new `test_media_playability.py` and seven in `test_webui_http.py`,
with `git diff --numstat tests/` reporting `110 0` and `2 0`: **zero deleted
lines** (CLAUDE.md — a test rewritten to agree with the code guards nothing).
The two added lines are `preview` joining the `CLI_ONLY` allowlist with its
reason, which is what that allowlist is for: the verdict is about a *browser*,
and the agent panel has no `<video>` element to spend it on.

**The screenshot is not the evidence, and finding that out cost an hour.** Both
headless routes drew a black viewer while the element reported `readyState 4`,
`videoWidth 1920`, no error and `canPlayType` "probably", against a frame ffmpeg
put at `YAVG 78.6` — the browser is not compositing `<video>` into the capture at
all. The measurement and the rule it produced are filed where the recipe lives,
wiki `tooling.md` § Headless browser, since it is a fact about the tool rather
than about this pane.

What was measured instead: `drawImage` the element into a canvas, reduce to an
8x4 mean-RGB grid, and compare against the same grid off the frame ffmpeg
extracts at the source timestamp the page claims. Seven shots across five
assets, clicked in the V2 lane:

| shot | reads at | distance / 255 |
|---|---|---|
| `cold-open` 0:00.0–0:28.9 | 14.50s | 3.9 |
| `cold-open` 0:41.3–0:48.0 | 32.28s | 3.9 |
| `vi-richie` 1:08.3–1:18.7 | 5.22s | 4.3 |
| `s4-reveal` 1:18.7–1:22.5 | 1.75s | 6.9 |
| `vi-richie` 1:22.5–1:38.0 | 18.26s | 2.8 |
| `s2022-reveal` 1:38.0–1:49.2 | 5.74s | 3.7 |
| `s1996-billy-stu` 1:49.2–2:06.2 | 8.52s | 4.2 |

The two `cold-open` rows are the point: the second one reads at **32.28s**, not
from the head — `plan_picture`'s cursor, confirmed from the browser. `vi-richie`
does the same, 5.22s then 18.26s. Playback held the lock too: 3.9s of transport
advanced the picture 3.91s.

Cards were checked as an `<img>` — `receipt-scream-1996` drew at its natural
1920x1080 against the film's 1920x816 canvas, letterboxed by `object-fit:
contain`, which is the pillarbox the wiki row predicted and the reason `cover`
is not used: a preview that crops to fill hides the framing problem it was
opened to show. And the refusal note was driven end to end on a scratch project
carrying a real `hev1` clip — the viewer draws *"broll — video codec hevc (tagged
hev1) is not decodable in a browser here"* where it used to draw black.

### What this does not cover

- **No transcode.** An unplayable asset now explains itself; it still does not
  play. Building the proxy needs three answers this change did not need: where it
  goes and how it is keyed (the waveform cache is the obvious model), what
  happens while it runs — `cold-open` is 730s, so it is a job with progress, not
  a request that blocks — and when it is evicted. The `/api/render` background-job
  pattern is the shape to copy. Deferring it is the same call every other
  subsystem here got: no design note, no build.
- **The transport still plays one clip.** V2 previews over V1; V1 itself is
  whatever `#media` holds, and on a VO project that is silence-and-black under
  the picture. Multi-clip V1 playback is not this change.
- **Nothing here authors a cue**, same as step 6. The layer draws what the
  projection says.

## Caption styling, second in the Daydream parity queue — 2026-08-09

The gap DAYDREAM.md § Captions named: lucid generated timeline-mapped captions
but the look was an *argument*, so nothing persisted it, nothing previewed it,
and "restyle, then keep editing" had no answer. The fix is the separation that
section specified — **a caption-style object in the project, and caption
content derived** — which makes regenerate-preserving-style true by
construction rather than by care. There is nothing to preserve, because
nothing was ever coupled to a particular generation.

`caption_style` reads or writes it, `caption_view` shows what the timeline
would produce, `add_captions` takes its look from the project, and the window
draws the same thing in the viewer and on the CC lane. Both new ops have their
`lucid` subcommand and their MCP tool, per the parity convention.

### What is stored, and what is not

The manifest key is `caption_style`, additive and read with `.get()` — **not a
`SCHEMA_VERSION` bump**, which would make `Project.open` refuse every existing
project to gain nothing. What it holds is the base preset name plus *only the
fields overridden on top of it*, never a flattened copy: the manifest stays
readable, and a later improvement to a preset still reaches a project that
only changed its size.

Line grouping (`max_words`, `max_gap`, `max_duration`, `hold`) is in there with
the font and the colours, and that is not tidiness. How a line breaks is as
much of the look as the typeface, and had it stayed a call-site default, the
preview would have grouped one way and the burn-in another — a window showing
captions the `.ass` file does not contain. For the same reason `group()`'s
defaults now come from `DEFAULT_GROUPING` rather than from literals in its
signature: two sets of defaults is two answers.

`add_captions` still takes `preset` and the four grouping numbers, but they
override *for that file only* and are not written back. One writer for the
style, and it is not the thing that generates files.

### ASS speaks a different language, and three of its words are traps

The stored style says `text`/`highlight`/`box`/`position`; `captions.resolve`
is the only place that becomes ASS, because ASS's own vocabulary is actively
misleading:

- **`PrimaryColour` is the colour a word turns as it is *spoken*** and
  `SecondaryColour` is how it sits before then. So with karaoke on, the base
  text colour is the secondary one. Set "primary" to yellow expecting yellow
  captions and you get white captions that flash yellow.
- **The alpha byte is transparency, not opacity.** `&H00…` is fully opaque
  where CSS's `#rrggbbaa` reads a trailing `00` as fully transparent. The two
  are exact inverses, so a value copied across without the inversion is not
  slightly wrong, it is invisible.
- **`BorderStyle` is a two-value enum, not a width** — the width is `Outline`,
  a different field with a similar name.

Hence every echo quotes colours twice, resolved: CSS for a reader and the
preview, ASS for the file. An unknown style field is refused rather than
ignored, because a silently dropped typo looks exactly like a setting that had
no effect.

One behaviour worth naming: switching karaoke on over a non-karaoke preset used
to inherit that preset's two identical colour slots, emitting `\k` tags that
changed nothing visible — the flag looking broken. It now falls back to the
karaoke preset's own highlight.

### Two things the browser and ffmpeg disagreed about, and both were real

Verified against `~/lucid-scream-v2/proj` over CDP (wiki `tooling.md` §
Headless browser) at 1600×1000, then against libass by burning the project's
own `.ass` over a flat 2541×1080 frame and reading the pixels back. The window
alone would have passed both times.

- **`\k` is a fill, not a step.** The overlay lit one word at a time; the
  burned frame at t=4.70 had *four* words in the highlight colour (ink from
  x=822 to x=1390) and three in the base colour (x=1408 to x=1720). A `\k`
  tag switches its word to `PrimaryColour` when its turn comes and the word
  **stays** that colour for the rest of the line — karaoke sweeps left to
  right. The preview was corrected to match the file, not the other way round;
  a genuine one-word-at-a-time highlight is a different construction (one
  Dialogue event per word) and is not what `to_ass` writes.
- **`DejaVu Sans` is not installed on this box.** The preset comment justified
  it as shipping "with essentially every Linux distribution" — Bazzite ships
  Noto, and `fc-match "DejaVu Sans"` answers `Noto Sans`. So every caption
  lucid has burned here was drawn in a font nobody chose, silently: libass
  substitutes without a warning and ffmpeg exits 0. `captions.font_match` now
  asks fontconfig the same question libass will and reports the answer on
  every `caption_style` and `caption_view` call. `available` is null rather
  than false when `fc-match` is missing, because "cannot tell" and "not here"
  are different answers.

  The preset table was **not** changed. The substitution can happen to any font
  on any other machine, so the fix is reporting it, not picking a different
  default — and picking one would silently change the look of every existing
  project. Whether lucid's default should name a font this box actually has is
  a call left open.

A third defect, found the same way and of the recurring shape: a renamed
function with a stale call site threw `ReferenceError` **once per animation
frame** inside `paintCaption`. The overlay simply never appeared, the page
looked idle rather than broken, and the Python suite cannot see it.

### The overlay, and why its geometry comes from the canvas

`#caption-layer` is placed over the *caption canvas* — `caption_view`'s
`resolution`, which is the PlayRes `to_ass` writes — `contain`-fitted into
`#viewer`, and **not** over whichever element currently holds picture.
Measured off the DOM instead, the box changed size whenever a shot started or
ended, and it is unavailable at all on an audio-only project, where every
element in the viewer reports `videoWidth 0`. Sizes scale by
`frame.height / 1080`, since a style's numbers are quoted against
`REFERENCE_HEIGHT` whatever the footage is.

Every visible property arrives from the server already resolved. That rule is
stronger here than the palette rule elsewhere in the window: these pixels are a
claim about pixels ffmpeg will burn, so a caption borrowing lucid's theme would
be a preview of the window rather than of the render.

Read back at t=4.70 with the karaoke preset at size 80, `#ff3b30` highlight,
bottom, margin 96: layer 800×340 in an 800×687 viewer (2541:1080, exact),
font-size 25.19px (`80 × 340/1080`), padding-bottom 30.22px (`96 × 340/1080`),
stroke 0.944px (`3 × 340/1080`), `flex-end`/`center`, and the fill boundary
falling between "are" and "still" — the same four words libass filled. Console
clean.

### The CC lane stopped lying, and `_revision` grew a field

The lane drew one block per *timeline segment*. A segment is a piece of the
edit and a cue is a line of subtitle, and they are not the same shape — cues
break on sentence ends, silences and a word count. So it was drawing caption
blocks the `.ass` will never contain: the picture lane's rule (never draw a
lane the export cannot produce) failing in a quieter register, because nothing
looks wrong. It now draws `/api/captions`, refusals included: 215 cue blocks on
the Scream assembly, the first reading *"The first 12"*.

And `_revision` now watches the **manifest's** mtime as well as the timeline's.
Both the caption style and the cue table live in the manifest and neither
touches `project.otio`, so an open window kept drawing the old style — and, it
turns out, the old picture lane after a `cue_add` — until some unrelated edit
moved the timeline. That second half was a pre-existing bug in the V2 lane's
invalidation, fixed here by accident of needing the same thing.

### What this does not cover

- **Per-word animation** — the pop/scale/slide Daydream applies to a
  highlighted word. Karaoke is a colour fill and nothing here moves a glyph;
  DAYDREAM.md § Captions always parked this as an export question, and it is
  the same construction question the one-word-at-a-time highlight raises.
- **No styling UI.** The agent restyles and the window renders it — which is
  the parity target, but it does mean there is no colour picker. `/api/captions`
  is GET-only for that reason; a POST route with nothing calling it would be
  dead code.
- **Burn-in is still opt-in on `add_captions`.** `export` does not take a
  captions flag, and the sidecar `.ass` remains the default exit because
  Kdenlive loads it and it stays restylable.

## The schema migration, and why `open` still refuses — 2026-08-09

`SCHEMA_VERSION` went 1 → 2 on 2026-08-08 for the cue table, and § The cue
table, step 1 recorded that nothing needed migrating: "there are none in this
repo, only `tmp_path` fixtures". That was true of the repo and false of the
box. The three `~/lucid-dogfood` projects — `scream-vo`, `scream-picture`,
`scream-reveal` — were all `schema_version 1`, so `Project.open` refused every
one of them, and the fixture that every UI-verification instruction in this
repo names had been unusable since the bump. `~/lucid-scream-v2/proj` stood in
on 2026-08-08 without anyone writing down why.

**The delta was one key.** v2 is v1 plus `cues`, and `cue_add` already
`setdefault`s it — so a v1 manifest would have *worked* had anything been
allowed to open it. The refusal was the whole of the breakage, which is worth
stating plainly: the exact-match check in `open` is not a safety net that
happened to fire, it is the only thing that fired.

### Migration is explicit, because opening is a read

The obvious shape — migrate inside `Project.open` — is the one deliberately
not built. `open` is called by every op including `info` and `status`, so
folding the migration in means `lucid info` rewrites the manifest of a
project the reader only meant to look at, and silently retires a directory
that an older lucid installed elsewhere could still open until the moment it
was inspected. A read that rewrites what it validated is the same class of
failure as the silent degradations this repo keeps cataloguing, so:

- `Project.open` still refuses, and the refusal now **names the way out** —
  `run \`lucid migrate\` to bring it forward` when a path exists, `there is no
  migration path from it` when one does not. The old message stated the two
  version numbers and stopped, which is a dead end dressed as an error.
- `Project.migrate` does the writing, as `ops.migrate` → `lucid migrate` →
  the `migrate_project` tool, per the parity convention. It takes `--plan`
  (CLAUDE.md: mutating tools resolve without writing), which doubles as the
  only way to ask "what version is this, and can it come forward?" without
  committing to the answer.

### Stepwise, forward-only, and it keeps the old manifest

`_MIGRATIONS` is keyed by the version each step migrates *from* and returns
the manifest at key+1; `migrate` stamps the number itself, so a step cannot
disagree with the version it claims to have produced. Stepwise rather than one
function per (from, to) pair means the next bump is one entry and every older
project reaches the present along the path the one before it took.

Two guards that look like pedantry and are not:

- **`bool` is excluded explicitly.** It is an `int` subclass, so a manifest
  reading `"schema_version": true` passes `found < SCHEMA_VERSION` and would
  have been migrated as v1 — writing a v2 header onto a file whose shape
  nobody has established. It is refused instead.
- **The pre-migration manifest is copied to `cache/history/lucid-v<n>.json`**
  before anything is written. This step is additive and loses nothing; the
  next one may not be, and the backup is cheaper to build once than to add
  after the migration that needed it. It lands beside the timeline snapshots
  because it is the same kind of thing — state before a mutation — and
  `snapshots()` globs `*.otio`, so it is invisible to `undo`. That matters in
  the right direction: rolling the timeline back one edit must not roll the
  schema back with it. Asserted, because the glob also `int()`s the stem and a
  stray `.json` in there would be a crash rather than a wrong answer.

### Verified on the projects it was built for

All three migrated, and were then checked as *fixtures* rather than as files:
`status` opens each (scream-vo: 62 segments, 5:35.9, undo depth still 0 —
the backup is not an undo step), all four clips resolve through
`media.media_path`, and `lucid web` on scream-vo serves `/api/view` (929
words, 61 seams) and `/api/captions`, draws in headless Chrome with no console
errors, and its `<video>` reaches `readyState: 4` on `/api/media/vo`. The one
`net::ERR_ABORTED` in the network log is the media element cancelling a
speculative range fetch, not a decode failure — the distinction CLAUDE.md
warns about, checked rather than assumed.

`melt-spike` in the same directory is not a project and has no manifest; it
was left alone.

## Binding the agent's MCP server to its project — 2026-08-09

PLAN.md § The agent panel, in mechanism had been carrying its own correction
since 2026-08-08: the panel spawns `lucid -C <project> mcp`, and `_cmd_mcp`
took its `argparse.Namespace` as `_args` and dropped it. `serve()` took no
arguments. So the generated MCP config spelled out `["-C", str(project_root),
"mcp"]`, the server read none of it, and every tool took its own explicit
`path`. The two confinements the panel's flags buy are separable, and only
one of them held: `--strict-mcp-config` and `--tools ''` kept the agent
inside lucid's ops, and nothing kept it inside *this project's*. An agent
panel opened on `scream-vo` could cut `scream-picture`.

Worth being precise about the size of it, because the flags around it are
load-bearing and this was not a hole in them. Nothing here escalated beyond
lucid's own operations — every one of them is snapshotted and `undo` reverses
it. What it defeated was the assumption a user makes from the window they are
looking at: that the panel in *this* project edits *this* project.

### The binding is on `path`, and that is a boundary, not an oversight

`path` is confined because it is the **project selector** — the argument that
decides which project's state a call reads and writes. The file arguments are
left alone, and the reasoning is worth writing down so nobody later "finishes
the job" and breaks the workflow:

- `import_media`'s `source` reads footage that lives on the NAS, outside every
  project by design (CLAUDE.md: a `media/` entry is optional because the NAS
  rejects symlinks).
- `export` and `add_captions` write their `output` where the user asked, which
  is routinely `~/Videos/…`.

Neither can touch a second project's state, so confining either would cost the
ordinary workflow and buy nothing. The selector is the whole of the leak.

### Where the check lives, and why it is a decorator

One decorator, `_tool()`, wraps `mcp.tool()` and routes `path` through
`_confine` before the body runs. Not a line in each of the 28 bodies that take
one: a body that forgot it would be the entire hole again, and tool bodies
stay trivial by this repo's own convention. The wrapper is transparent to the
tool surface — `functools.wraps` sets `__wrapped__`, and the SDK's
`func_metadata` builds its schema from `inspect.signature(fn, eval_str=True)`,
which follows it. Checked in the installed package before relying on it, and
then asserted over the wire: the bound server's advertised schemas are
compared to the unbound server's for equality, so a future wrapper that
reshaped them fails the suite rather than changing what clients see.

Three properties the tests pin, each because the obvious implementation gets
it wrong:

- **A relative path resolves against the bound root, not the process cwd.**
  For the panel these are the same directory — `webui.py` sets `cwd` on the
  Popen — but "bound to this project" should not depend on where the client
  happened to be standing. The test proves it the cheap way: it runs from the
  repo, which is not a lucid project, so `path="."` succeeding at all can only
  mean it resolved against the root.
- **Both sides `resolve()`, so `..` and a symlink out are refused rather than
  followed.** A containment check on unresolved paths is string-deep and a
  symlink planted inside the project walks straight through it. It also cuts
  the other way on this box, which the live check ran into: `/home` is a
  symlink to `/var/home`, so a root given as `/home/<user>/lucid-dogfood/…`
  and a `path` spelled the same way both normalise to `/var/home/…` and
  match. A string-prefix check would have refused a project **its own path**.
- **`-C` binds only when it was typed.** `main()` defaults `args.project` to
  `"."`, so binding on the value rather than on `args.project_given` would pin
  a globally-configured `lucid mcp` to whatever directory its client launched
  from — breaking every general MCP client to fix the panel. `lucid mcp` with
  no `-C` stays unconfined, and that too is asserted.

A root that is not a directory fails at **startup** (`lucid: cannot bind the
MCP server to '/nonexistent-project': not a directory`, exit 1) rather than
per call, because a per-call refusal blames the argument the client sent for
the directory the server was started with. Existence is all that is checked —
`init` under a bound root is legitimate, so demanding the root already be a
lucid project would refuse a real workflow.

### Verified on the real projects, not only on `tmp_path`

The suite builds empty projects; the check that matters is a bound server
against one with state. `lucid -C ~/lucid-dogfood/scream-vo mcp`, driven over
stdio from a working directory that is neither project: `timeline_status`
returns the same project by absolute path and by `"."` (335.901 s, 62
segments, undo depth 0 — the figures § The schema migration recorded), and
the same call against `~/lucid-dogfood/scream-picture` is refused naming both
directories. `lucid -C /nonexistent-project mcp` exits 1 with the one-line
message and no traceback.

## The card renderer, step 1 of motion graphics — 2026-08-09

PLAN.md § Motion graphics and templates costed the item and found it needs no
new timeline mechanism: the Scream assembly's cards already ride the cue table
as stills, so what was missing is a generator for the asset. This is its
renderer — `graphics.py`, `ops.card_render`, `lucid card render`, MCP
`card_render`. SVG in, PNG out, both kept: the cue table and the preview
`<img>` want a raster, and a card you cannot re-edit is one you redraw from
scratch to change a year.

`magick` is shelled the way `asr` shells whisper and `picture` shells melt.
IM6's `convert` is deliberately not in the resolution order — it is a
different SVG renderer with different defaults, and every measurement below
was taken on IM7's librsvg coder, so falling back to it would render through
something the numbers do not describe.

### Four measurements, and what each one decided

1. **`-size WxH` before the input is a vector render; `-resize` after it is a
   resample.** Same 1920x1080 card: `-size` gave an 8-bit, 256-colour raster,
   `-resize` a 16-bit one an order of magnitude larger — it rasterises at the
   document's native size and then scales the *pixels*, which is the one thing
   not to do to text. So the size knob goes before the input, and `render_svg`
   has no resize path at all.

2. **`-size` fits, it does not distort.** 1920x816 asked of a 16:9 document
   gives **1450x816**, not a squashed 1920. This is § Motion graphics and
   templates' finding 4 restated as a mechanism rather than an observation:
   cards pillarbox not because fitting is wrong but because a card authored at
   a different aspect from its film has nowhere else to go. It is also why
   step 3 has to author templates *at* the canvas size — resizing here could
   never have closed it. `RENDER_FIT` names the policy and a test asserts the
   1450.

3. **A missing font renders pixel-identical at exit 0.** The caption trap
   (CLAUDE.md), reproduced on a second renderer: the same card naming
   `Noto Sans` and naming a face that does not exist compared at
   `magick compare -metric AE` **0**. Nothing in the PNG records that a
   substitution happened, so the report is the only guard there is — and like
   `captions.font_match`, which it reuses rather than duplicating, it reports
   and does not prevent.

4. **Unlike melt, magick's exit code can be trusted here.** A truncated SVG
   and a file that is not SVG at all both exit 1 naming `RenderRSVGImage`.
   Worth writing down only because so much else in this repo exits 0 on
   failure — it means this module does not have to prove its output exists by
   other means. It reads the finished raster's dimensions back off the file
   anyway (`mlt.declared_frames`' discipline), because after measurement 2 the
   size asked for and the size that landed are different numbers.

### The font report is per declaration, not per face

A `font-family` value is a fallback stack, and the stack is what decides the
outcome. Reporting each face separately would warn about `'Card Face',
sans-serif` with the first one installed — a warning about working output,
the false-alarm shape finding 3 of the design note exists to not repeat. So
one entry per declaration: `available` is true when *some* named face in the
stack is installed, `drawn` is what fontconfig will actually use, and generic
families are excluded from the installed question because `sans-serif` is not
an uninstalled font, it is a request with no face. The tri-state from
`font_match` survives — null still means `fc-match` could not be reached,
which sends someone somewhere different from "the font is not here".

Families are read by walking the parsed tree, not by pattern-matching the
markup: the three places a family can be named — the presentation attribute,
an inline `style=`, and CSS in a `<style>` element — share no syntax, and a
regex loose enough to catch all three swallows the rest of the tag.

### Verified on a real project, not only on `tmp_path`

`lucid -C proj card render receipt` on a card authored at the film's 1920x816:
renders 1920x816, and the paper reads back **exactly `(250,245,236)`** against
the source's `#faf5ec` — the design note's finding 3 (no colour management
needed) holding at the near end of the pipeline too. The missing-card path
exits 1 naming the cards that do have a source.

It also caught the live thing: the card named `DejaVu Sans` and came back
`available: false, drawn: Noto Sans`. That is the same substitution caption
styling hit, which means **the open call about lucid's default font is no
longer only about captions** — a template shipping a face this box lacks would
put every generated card in a typeface nobody picked, invisibly.

## Card templates, steps 2 and 3 of motion graphics — 2026-08-09

`card new` fills a template's slots, writes the SVG, and renders it — and
takes its canvas from the project rather than from a constant, which is what
closes § Motion graphics and templates' finding 4. With step 1's renderer
under them, the item's build order is done to where the note said stop.

### The templates reproduce the real cards rather than inventing a look

The starter set is the three the Scream assembly used — `receipt`, `reveal`,
`rerate` — and their design was read off `receipt-scream-1996.png` and its
siblings, not designed fresh. The palette is **sampled**: paper `(250,245,236)`,
ink `(26,23,20)`, amber `(232,161,60)`, muted `(110,99,87)`, faint
`(156,152,145)`. Every one is an ordinary slot with that as its default, so a
project restyles a card without authoring SVG.

Two things the shipped templates deliberately do not carry. There is no brand
mark baked in — `mark` is an empty slot — because lucid is not the channel
that happens to be dogfooding it. And **no template names a single font**: each
declares a fallback stack ending in a generic (`'Noto Serif', 'Liberation
Serif', serif`). That is the shape step 1's per-declaration font report was
built for, and it scores correctly on this box: `Noto Serif` and `Lato` are
present, so a real render reports `available: true` with no warning, rather
than the false alarm a per-face check would raise about the tail of the stack.

### Escaping is the whole security story of a string template

Slots are filled by substitution, not by a template engine — the vocabulary is
"put this text there", and a dependency that can branch and loop is one that
can put logic in a card. What that leaves is escaping, and it is split by
origin: **every user value is escaped, and the only raw markup is what lucid
generates itself** for a derived slot. `"` escapes along with `&<>`, because a
slot lands inside a double-quoted attribute — `font-family="{{title_font}}"`
does — and a value that closed the attribute early would rewrite the document
rather than fail. Both directions are asserted: a title of
`</text><script>…` comes out escaped and still parses, and a font stack of
`x" onload="boom` cannot reach the tag.

### Stars are generated, and a half is the same star clipped

A rating is parsed as a number and drawn, never pasted through as text. Halves
are the full star polygon under a clip rectangle rather than a second
hand-drawn path, so the two halves cannot drift apart — and each row's clip id
is prefixed, because `rerate` puts two rows in one document and a shared id
would collapse them into one. The re-rate row lays its arrow out from the
*measured* width of the first row: a fixed offset collides the moment someone
re-rates from four stars rather than from two.

**Nothing wraps.** SVG has no automatic wrapping, and a wrap computed from a
character count overflows the frame silently on the first line of wide glyphs
— the failure shape this repo keeps finding. So a newline in a slot is a line
break and nothing else breaks it, and the caller owns the lines. A test feeds
200 words and asserts that not one line break appears.

### The manifest and the SVG are checked against each other

What a template accepts is read from the placeholders in the file, not from
the manifest alone, and the two are compared in both directions: a placeholder
nothing fills and a declared slot the SVG never places are each an error. The
failure that guards against is a card shipping with `{{year}}` printed on its
face, which renders perfectly and is unmistakably wrong. It runs per template
in the suite.

### Canvas defaulting, and what the stdio test caught

Step 3 is one decision: `card_new`'s canvas defaults to `_mlt_resolution` —
the same number the MLT profile declares. Templates can honour it because
their geometry is in 1920-wide units and the viewBox is written to the aspect
asked for, so a 1920x816 project gets a card rendered at exactly 1920x816
rather than the 1450x816 that fitting a 16:9 document into that frame gives.
Finding 4's 465 px of black bar is gone for new cards, and it could only ever
have been closed here: step 1 measured that `-size` *fits*, so no resize on
the way in would have done it.

**The MCP tool did not get this until a test over the wire said so.** Its
signature still read `width: int = 1920, height: int = 1080`, so every call
through the server passed an explicit canvas and `canvas_from` came back
`requested` — step 3 present in the op, bypassed by one of the two front ends.
Nothing in the unit tests could see it, which is the argument for
`test_server_stdio.py` restated: the tool function was right and the tool was
not.

### Verified on a real project

`lucid -C proj card new` against a manifest whose only video clip is 1920x816:
`canvas: 1920x816`, `canvas_from: project`, and the PNG reads back 1920x816
with the layout adapted — full-bleed background, footer still off the bottom
edge, no pillarbox. Rendered at 1920x1080 against the real cards, all three
templates are recognisably the same design as the originals they were read
from.

## `describe`, step 1 of b-roll by description — 2026-08-09

The costed note is PLAN.md § B-roll by description, and this is its first
three-quarters: the subprocess, the windows, the manifest storage, the schema
bump, and skip-if-already-described. `describe_ls` and the pinned cue are
steps 2 and 3 and are not built.

The note's design survived contact — nothing here contradicts it — so what
follows is only what building it *added*.

### The window count rounds up, and that was not in the note

The note fixed the window length and said nothing about how a clip that is
not a whole number of windows gets split. The obvious answer, nearest, is
wrong, and a test caught it before any footage did: **25s at 10s windows
became two windows of 12.5s.** Round-to-nearest silently *widens*, and
widening is the one direction that fails — the whole-clip pass that described
six frames as six people is just a window widened far enough. 14s at 10s
windows would have been a single 14s window, 40% over what was asked for,
arrived at silently.

So the count is `ceil`, and the invariant is stated as **a window is never
longer than the one asked for**. It trades cost for fidelity, and cost is the
knob the caller already has. The windows are still divided evenly rather than
`window`-then-a-remainder, for the note's reason: a 0.4s tail samples three
frames from one instant and is then described as though it were ten seconds.

### One process for the whole run, and why the worker is a separate file

Loading the model is ~15s; describing a window is ~3s. So the unit of work
handed to the subprocess is **every window of every clip at once**, not a
window and not a clip — a process per clip would spend most of the run
loading the same 31 GB of weights again. `ops.describe` builds the whole work
list, `describe.describe_windows` runs it in one process, and results come
back keyed by window index so nothing depends on the order they finish in.

`_vlm_worker.py` lives inside the package but is **never imported by lucid**.
It is executed by whichever interpreter `LUCID_VLM` resolves — the sibling
tagging venv here — which is the same trade `asr.py` makes for whisper and
for the same reason: `lucid status` should not pay for a torch import. What
crosses the boundary is a JSON job file in and a JSON result file out.

**A file rather than stdout**, and that is not fastidiousness: torch,
transformers and bitsandbytes each write to whichever stream they feel like,
and a progress bar landing in the middle of a JSON document is a parse error
that reads exactly like a model failure. Whisper is read back from a file for
the same reason.

Reused from `tagger_core`: `load_qwen` and `run_vlm`, the measured-working
4-bit config. Not reused: its prompt and its vocabulary, both
specific to that repo's own library. lucid passes its own prompt, which asks for the
concrete nouns a later search has to match on — a description reading "a
person does something" indexes nothing.

### A failed window is reported, not fatal, and truncation is computed

Two error classes the note measured are surfaced on every result rather than
smoothed over:

- **`errors`** — a window the model could not describe. One unseekable moment
  in a 133-window run is not a reason to throw away 132 good descriptions, so
  the failure is recorded against that window and the run continues. The
  *worker* failing to start at all is still an exception: nothing was
  described.
- **`truncated`** — text that stops mid-sentence. The note measured two
  windows truncating at `max_new_tokens=120` and warned that whatever limit
  ships "has to be checked against, not assumed". So the limit is 220 *and*
  every entry is checked: a description ending anywhere but sentence-final
  punctuation is flagged. It is still stored — it indexes what it did say —
  because the failure being guarded against is that it reads as complete.

The third error class is not detectable and is written down instead: the
model narrates *across* a cut inside a window as though it were one take. A
window is evidence of what is visible in a span, never of a continuous shot.

### The schema bump, and what `describe` refuses

v2 -> v3, one `_MIGRATIONS[2]` entry keyed by the version it migrates *from*,
additive like v2 before it. It covers the optional in-point a cue gains in
step 3 as well — one bump for both, because a v2 cue without one means in v3
exactly what it meant in v2, so no cue needs rewriting.

Descriptions live in the manifest rather than a sidecar directory or
`cache/`: they are per-clip metadata `info` should report, they have no
natural filename the way a card does, and they cost GPU minutes, which is not
what `cache/` is for.

Two refusals, both naming what they refused:

- **An audio-only clip.** Descriptions index pictures; its words are what
  `transcribe` indexes. Skipping it quietly reads the same as describing it
  and finding nothing worth saying — and the Scream project's VO is exactly
  this clip, so the quiet version would have shipped.
- **No interpreter with a vision model.** `LUCID_VLM`, then the sibling venv,
  then a refusal naming both. There is no PATH step, unlike
  `asr.whisper_binary`: `python` is always on PATH and is almost never the one
  with torch in it, so searching it would resolve to an interpreter that fails
  several minutes later with an ImportError instead of refusing now.

`plan=True` resolves the whole work list, the estimate, and whether this box
can run the model at all — without loading anything. **The estimate includes
the model load**, which matters more than it sounds: three windows is 9s of
describing and 25s of waiting, and an estimate wrong by 3x on the small run
someone checks it against is not a useful estimate.

### Verified on the real footage, and two numbers the note had wrong

The whole Scream project — nine video clips, 14s to 730s — described end to
end: **139 windows, 0 errors, 0 truncations, 498.6s** against an estimate of
502. The 730s cold open is 74 windows and did not OOM, which is finding 3
holding: frames per call are fixed at 3 and length is absorbed by the window
count, so the clip that failed vaultmedia's length-scaled rule is unremarkable
here. GPU sat at 11.5 of 12.2 GiB throughout, alongside the always-on
`llama-server`.

Finding 4 reproduced exactly on the clip it was measured on. The whole-clip
pass had described the 30s Billy/Stu window as six men; in windows it reads
*"a kitchen... a person wearing a white shirt with red stains resembling
blood, holding a knife"* — two people, correctly. The cold open gives the kind
of noun a search actually needs: *"a hand reaching towards a corded telephone
on a wooden table"*, *"a wooden entertainment center that houses a television
displaying a blue screen"*.

Two of the note's numbers were off, both measured rather than argued:

- **~3.5s per window, not 2.6-3.3.** The note's spike ran on smaller frames;
  the real mix at 1920x816 is slower. The estimate carries 3.5 and now lands
  within 1% on a 139-window run.
- **~97 words per description, not ~60.** That moves the ceiling on "search is
  the agent reading the descriptions": this project is **~18k tokens, not
  10k**, and the point where reading them stops being reasonable arrives at
  roughly 600 windows rather than 1000. The design is unchanged — 18k is
  readable, and the trigger for embeddings is still a *cross-project* library
  — but the number to revisit it at is 600.

**One thing this leaves for step 2**: the manifest is now 103 KB, and
`lucid info` prints the manifest. That is a CLI-only surface, so no agent is
flooded by it, but it is a debugging command that just got much harder to
read. `describe_ls` is the table that answers this, and it is next.

## `describe_ls`, step 2 of b-roll by description — 2026-08-09

The table that reads the descriptions back, and it **is** the search: no
ranking, no embeddings, no similarity threshold, for the note's measured
reason. What follows is what building it added or answered.

### It took `info` with it, and that needed an escape hatch

Step 1 left the problem stated: descriptions live in the manifest, `lucid info`
prints the manifest, and a described project's manifest is 103 KB. So `info`
now stands that one block down to a count and a pointer, and everything else
stays verbatim.

The part worth writing down is that **substituting a summary is a lie unless
there is a way to see the bytes**, and nothing else in lucid can show you what
is on disk — `describe_ls` returns the descriptions, not the manifest. Hence
`lucid info --raw`, and a test asserting it prints the stored entries. The
summary is also *only* a substitution: on an undescribed project the empty list
`describe` wrote stays an empty list, because a summary appearing where there is
nothing to summarise is a second thing to explain.

Measured on the real six-window project below: 6050 bytes of manifest to 1456.

### `contains` matches terms, not a phrase, and real footage settled it

The note called keyword filtering "a convenience on top, not a subsystem" and
said nothing about what a match is. Substring-of-the-whole-string is the
obvious reading and is the wrong one: on the real Scream footage the window
that matters describes *"a knife on the kitchen counter"*, and nobody searching
for it types that. `--contains "kitchen knife"` finds it because every term has
to appear **somewhere**, not in that order.

The terms it split into come back in `filter`, on the same principle that makes
a word-indexed tool echo the words it resolved to: a search that quietly
tokenised differently than you assumed returns a plausible wrong answer.

### Two shapes that exist so an empty answer cannot mislead

- **`total` rides along with `count`.** A filter matching 1 of 6 and a project
  with 1 description in it print the same `descriptions` array. One of those
  means "narrow your terms" and the other means "go and run `describe`", and
  the caller cannot tell them apart without the denominator.
- **`clips` covers every video clip, described or not.** A clip with
  `windows: 0` has not been indexed; without the zero row, an undescribed clip
  and a mistyped `clip_id` are the same empty result. `described_seconds`
  against `duration` is the coverage check, and `duration` is rounded to match
  it — 14.013 against 14.013292 reads as a shortfall that is not there.

`words` is reported for the ceiling the note set: ~600 windows is where reading
them all stops being reasonable, and a number after the fact beats a guess.

### The web half of step 2's parity was not built, on purpose

The build order asked for "CLI/MCP/web parity". CLI and MCP shipped; the web
pane did not, and the reason is the same one that governs the timeline lanes:
**nothing in the window places a cue.** Cue placement is a CLI and agent-panel
operation, so a descriptions pane would draw the input to a decision the UI
cannot take — a view widening ahead of the model. `cue_add --src-start` (step
3) is what would give it a user. Noted rather than silently skipped, because a
build order with an unexplained gap reads as an oversight.

Worth recording that this is not the precedent breaking: `cue_ls` has no web
endpoint either. The convention that is actually asserted, by
`test_every_mcp_tool_has_a_cli_subcommand`, is CLI/MCP.

### Verified on the GPU, and two of step 1's numbers held

Six windows across two real Scream source clips, described for real rather than
against the stub, then read back through the CLI and over a live MCP stdio
session:

- **34.6s against a 36s estimate** — the 3.5s-a-window constant plus the load,
  on an independent run from the one that set it.
- **593 words over 6 descriptions, ~99 each** — step 1 corrected the note's ~60
  to ~97, and this lands on it. The ~600-window ceiling stands.

## The pinned cue, step 3 of b-roll by description — 2026-08-09

The last thing the note said to build: `cue_add --src-start`, and
`plan_picture` refusing rather than rewinding for a cue that carries one. It
closes the gap the note found — `describe` indexes footage and `describe_ls`
searches it, but what search returns is *a moment inside an asset*, and until
now nothing could place one.

The design survived contact. What follows is what building it added, and the
one measurement that settles whether it works.

### Two names, because they are two different claims

The note said "no new plumbing for the window: `timeline_view`'s shots already
carry `src_start`". True, and it is exactly why the cue's field could not be
called `src_start` in the shot dict.

`_picture_plan` annotates every shot with `src_start` — *where the planner says
it reads*. Carrying the cue's in-point under the same key would have made one
name mean two things depending on whether the dict had been through the
planner: the ask before, the answer after. For a pinned shot they are the same
number, which is the worst version of the bug — it would have looked correct
in every test that had a pin in it.

So the projection carries **`src_pin`** (what the cue asked for, or None) and
the plan adds **`src_start`** (where it actually reads). That they agree for a
pinned shot is the whole guarantee, and it is only a guarantee because the
planner refuses when they cannot.

### A pin still advances the cursor

Not in the note, and it has to be decided somewhere. A pinned shot consumes its
stretch like any other, so the per-asset cursor moves to the end of it — an
unpinned re-use afterwards carries on rather than replaying footage the viewer
has just seen. Measured on the live server: a pin at 10.0s of a 20s clip under
a 4s shot gives `src_in` 300, and the unpinned cue after it 420, not 0.

### The refusal, and where each half of it lives

`cue_add` checks only what it can check without touching disk — a negative
in-point, and a pin on a `card:`, where a held frame has no playhead and the
number could only ever be ignored. It deliberately does **not** check the pin
against the asset's length: resolving the asset needs media, and that is the
projection's job. A pin 90s into a 5s clip is accepted and refused later.

`plan_picture` owns the real one, and refuses a pin on a still too rather than
ignoring it — unreachable through `cue_add`, but a silent no-op is the failure
class this module is written against. The refusal arrives as `shots_error` for
the lane to draw, never as an exception, because `mlt.MLTError` was already in
`_PICTURE_REFUSALS`.

### Verified against a real melt render, by colour

Twenty seconds of b-roll built as ten distinct two-second colour blocks, so a
rendered pixel names its own source second and a wrong in-point cannot look
right. One cue, pinned to 10.0s, over an 8s VO; rendered through melt at 30fps.

| Rendered at | Sampled RGB | Source second the pin implies | Source's own RGB there |
|-------------|-------------|-------------------------------|------------------------|
| 0.5s        | 0 255 253   | 10.5s (cyan)                  | 1 255 255              |
| 3.5s        | 255 255 255 | 13.5s (white)                 | 255 255 255            |

What a rewind would have produced at 0.5s is `254 0 0` — the clip's own opening
red. That is the whole failure this step exists to prevent, and the render says
it did not happen.

The refusals were run live too: a pin at 14.0s under an 8s shot exits 1 with
the message and writes no file; `cue add … card:outro --src-start 3.0` is
refused at the cue table.

### One line of front end, and why it earns its place

The note's "no new plumbing" held for the data — the payload already carried
`src_start`, and the preview layer already seeks to it. What was added is a
tooltip clause: *"— pinned there by the cue"*.

It is not cosmetic. Two shots reading from the same second are identical in the
lane, and the difference between them is what happens next: an unpinned shot's
content slides when an upstream cue moves, and a pinned one's does not — it
shows the moment its cue names or `export` refuses. Read back off the real page
over CDP, both shots and the refusal:

```
broll · 0:00.0–0:04.0 · 120 frames @ 30.000fps
reads the asset from 0:10.0 — pinned there by the cue
cue: vo word 0 — w0
```

```
picture refused — the cue at 'vo' word 0 pins 'broll' to 18.0s and the shot
runs 4.0s, which ends past the asset's 20.0s — …
```

### The schema bump that was already paid

None was needed. Step 1's `_v2_to_v3` was written saying it covered the
optional `src_start` a picture cue would gain, and that claim only holds if an
unpinned cue is still written with exactly three keys — a `"src_start": None`
in the table would be a fourth key v2 manifests do not have, and the migration
would have had to rewrite every cue. `cue_add` omits the key rather than
writing null, and a test asserts the byte-level shape.

## The canvas field, step 1 of aspect swap — 2026-08-10

The project gained a `canvas` — one manifest key, `WIDTHxHEIGHT`, absent
meaning "derive from the footage" — and the two derivations that used to walk
`clips` independently (`_mlt_resolution` for the MLT profile, `_caption_canvas`
for the reference caption sizes are quoted against) now read it before either
walks anything. It is reachable as `lucid canvas`, as the `canvas` tool, and it
shows up in `status`.

Two things the design note (PLAN.md § Aspect swap) had wrong, both found by
building it.

### The schema bump it did not need

The note costed a v3 → v4 bump with a `_MIGRATIONS[3]` step. The precedent
against it was already written in this repo, at `CAPTION_STYLE_KEY`: an
additive *optional* key whose absence means what every older manifest already
meant needs no version, and bumping for one "would make `Project.open` refuse
every existing project to gain nothing". Both bumps so far were for *list* keys
another op would `setdefault` anyway — `cues` in v2, `descriptions` in v3 —
where the number is what makes the key true rather than incidentally
survivable. A canvas is the `caption_style` shape. The bump comes back at step
2, where persisted card records are a list and the cards on disk lack them.

### The routing could not wait for step 3

The note put the `_is_layered` widening in step 3, with the reframe. That is
one step too late, and the failure is this repo's usual one. `export` picks its
writer from the project; a single-source project whose canvas `_is_layered` did
not know about would go to auto-editor, which takes the export and renders the
footage's own shape at exit 0. A 16:9 file where 9:16 was asked for, no error
anywhere. So the routing shipped with the field: an overridden project reaches
the MLT writer whatever its source count, and the reply says so rather than
leaving it to be discovered at export.

Verified end to end rather than by unit test, on five real seconds of the
Scream cold open (1920x816) through the actual CLI:

```
lucid canvas 1080x1920   →  routes_through: mlt, fills_frame: false
lucid export --render    →  writer: melt, 1080x1920, 63 of 63 frames, exit 0
```

and then sampled, because exit 0 proves nothing here: the content band is 461
of 1920 rows, **76% black bar**, matching the 459 rows the costing spike
measured. That is the honest state until step 3 — the field makes the frame
the right shape and nothing yet makes the picture fill it, which is why both
`fills_frame` and `routes_through` are in every reply rather than in a doc.

`card_new` already defaulted its canvas to `_mlt_resolution`, so a card
authored after a swap comes out at the new shape for free. The 13 that exist
were authored before it, and remain step 2's problem.

## The b-roll cut, on real footage — 2026-08-10

The first cut b-roll-by-description has ever made from real material, and the
first thing it says is that the *indexing* half does not work. Built on a copy
of the Scream project (`~/lucid-final-broll`, migrated v2 → v3 so nothing of
Tyler's was touched), holding his edit and his 13 card cues fixed and replacing
only the 25 video cues, so the one variable is which footage got chosen. The
edit under it is the finished VO — the first pass was not, § The VO the project
was holding.

`describe` ran over all nine clips: **139 windows, 502s estimated, no window
errors**. Then each cue position was matched against the index by idf-weighted
overlap with the narration around it — boilerplate scores zero by construction,
so this flatters the index rather than the reverse.

**It agreed with the human choice on 2 of 25.** The two agreements were
`cold-open`, the asset that covers half the film anyway.

### The index cannot separate the films

Every window of Billy and Stu's unmasking — the franchise's most famous reveal —
came back as some phrasing of "indoors, likely in a kitchen". Every Scream 6
window is "a dimly lit room". Measured rather than eyeballed:

- **17 words appear in more than half of all 139 descriptions**: appears,
  background, colored, given, hair, indoors, light, lighting, likely, person,
  place, possibly, room, scene, setting, wearing, with.
- **Jaccard overlap between two windows of the same clip is 0.201; between two
  windows of different films it is 0.161.** Four points of separation is the
  entire signal a ranker would have to work with.
- The terms an editor would actually search: `killer` 0 windows, `unmask` 0,
  `stab` 0, `costume` 0, `ghostface` 1, `mask` 6.

So the matches land on the *narration's* abstract vocabulary instead — shots
chosen because a description shared the words "sentence", "ceiling", "third" or
"way" with the sentence being spoken over it. One position scored 0.00 and took
the first description in the corpus.

**The cause is lucid's own prompt, not the model.** `describe.PROMPT` asks for
"where it takes place, who or what is present, what they are doing, and how the
shot is framed … colours, objects, clothing, location, time of day, lighting" —
and it is obeyed exactly. Rooms and jackets are what was requested. Nothing in
it asks for the event, which is the only thing a cutaway is ever chosen for.

That is a prompt change and another 502-second pass, and it wants the same
treatment as any other claim here: two or three wordings, and the same-clip vs
different-clip overlap measured again, rather than one rewrite declared better.
PLAN.md § B-roll by description said ranking was the next question. It is not —
ranking a corpus with no separation in it is ranking noise.

### What worked, first time, on real material

Worth recording because the failure above is loud enough to bury it. The
placement half held: 25 cues placed by pin, `mlt.plan_picture` refused the two
whose shot would have run past the end of its asset and named the second and the
asset in the refusal, and the corrected render came back frame-exact — 8064 of
8064 frames at 1920x816, `agrees: true`, exit 0.

It also caught the `build_shots` / `plan_picture` disagreement CLAUDE.md
documents, the honest way: `lucid shots` reported 38 shots and no error, and the
render then refused. The raw projection is not the plan, and a check that wants
to know whether `export` will run has to ask `timeline_view`.

## The VO the project was holding — 2026-08-10

The b-roll cut above went out for review and came back with a complaint that had
nothing to do with b-roll: *"it seems like you're working with a worse version of
the voiceover — there are lots of retakes in there that aren't cut out."* He was
right, and no check in lucid was in a position to say so.

The recording was current — `VO2.wav`, the same file the shipped film uses. What
was stale was the *edit*. `~/lucid-scream-v2`'s timeline is **73 segments,
410.96s**, and `Project/Scream VO v2 - silence cut.kdenlive` is **73 entries,
408.53s**. Same stage. The retake pass after it — `Scream VO v2 - retakes
trimmed.kdenlive`, **63 entries, 336.27s** — was done in Kdenlive and never
carried across. What sat in lucid's timeline and not in the film:

- **15 stretches, 71.6s, 178 words** (1148 surviving words against 970).
- All of them audibly retakes: "the best 12 minutes of horror **whore. in the
  90s.**", "a secret half-brother where nobody… **blah.**", "the problem was
  **problem** purely structural".

**It also moved the picture, which is the part that made it a b-roll complaint.**
Those 72 seconds sit *between* cue positions, so every shot spanning one held
longer than written: **13 of 38 shots changed length by more than a second**, the
worst 24.5s where the finished VO gives it 11.2s. A clip held for twenty-four
seconds reads as unrelated to the narration regardless of who chose it — so the
review conflated a stale edit with a bad choice, and both were present.

### What lucid could and could not have caught

`verify --windowed` finds a retake **in a render**, and it is the reason two got
caught in August. It answers a question nobody asked here, because the render was
faithful — the timeline really did contain those words. There is no op that finds
a repeated take *in a transcript*; `vo_windows.py --repeats` in `goodsometimes`
does, and lives outside lucid. `speech-overlap` and `spots` are unrelated.

Nor is there any way to bring a Kdenlive trim in. The fix was 63 ranges parsed
out of the `.kdenlive` playlist and written straight to `Edit`, which is not a
supported path — it bypasses `cut` and its history entirely.

The cross-check that the transplant was right: **970 surviving words against the
983 that whisper reads off his own v6 render** (`VO/v6-render-windowed.json`),
the difference being the 12.8s outro lucid does not have. And the cue tables
already agreed — lucid's 38 cues match `assemble_scream.py`'s `CUES` on 37 of 38
by word index *and* asset, so with the finished VO underneath, lucid renders his
film: 63 segments, 8064 of 8064 frames, `agrees: true`.

### The rule this earns

**A lucid project seeded from one stage of an outside edit stays at that stage,
silently, and every downstream number stays self-consistent while it does.** The
render agreed with the timeline, `verify` had nothing to report, the cue table
resolved, 38 shots planned without error. Nothing was broken; it was the wrong
film. The only signal available was duration against the thing it is supposed to
be — 411s against 351s — and nothing compares those.

And it was *not* undetected. § Rendering through `melt`, step 5 of the layered
timeline wrote "73 segments, 410.963s — a plain silence cut, so the retakes the finished
VO trimmed are still in" on 2026-08-08, and correctly attributed the one
`plan_picture` refusal that day to them. Two days later that project was the
substrate for a cut sent out for review. **A caveat recorded in a results table
is not a guard**; the 38th cue still in the manifest is the split that refusal
forced, and on the finished VO it is no longer needed.

## Choosing the b-roll — 2026-08-10

The cut from § The b-roll cut, on real footage went out for review and came
back with the b-roll called out by name: *"the clips are less related to the
voiceover than before — even though Claude selected those clips previously."*
Two things in that sentence, and the second one is the finding. The index does
not work, which was already known. And **the thing it was built to replace —
an agent reading the transcript and knowing the films — already did.**

### The prompt was the wrong suspect

The plan of record was to rewrite `describe.PROMPT` to ask for events rather
than rooms, and re-index. That would have been a 502-second pass to test a
premise nobody had costed, and the cheap control killed it: **the clips' own
filenames already name the event.** `scream3-reveal-roman-brother` is exactly
what the rewritten prompt was supposed to produce, it is free, and matching on
it scores **3 of 25** — statistically the same as the 139-window index's 2.

So the information was never missing from the index. Six mechanisms against
the same 25 human choices, and the shape of the table is the argument:

| picking by | agrees |
|---|---|
| the `describe` index | 2 / 25 |
| the clips' filenames | 3 / 25 |
| a film named in the narration | 4 / 25 |
| the `describe` index, shortlist of 3 | 8 / 25 |
| a `synopsis` catalogue, shortlist of 3 | 15 / 25 |
| a `synopsis` catalogue read by a model that knows the films | **13 / 25** |
| the same, driven off `broll_brief`'s own output | **14 / 25** |

Two readings, both load-bearing. A better corpus **narrows** — nine candidates
to a correct three, 8 → 15 — and barely picks: the same corpus scored by the
same lexical method still only takes the right one 5 times. And **nothing that
scores text against text gets past single digits**, because the connection is
not lexical at all. "Every one of those is further outside the film than the
one before it" earns the Scream VI reveal because its killers are a family
avenging someone from the previous movie. No word of that sentence appears in
any description of those pixels, and none ever would.

### What shipped

**`synopsis`** — one sentence per clip saying what the footage *is*, an
additive optional key on the clip record, no `SCHEMA_VERSION` bump for the
reason `CANVAS_KEY` gave. Read/write/clear on one entry point, `canvas`'s
shape. Nothing generates one: a VLM cannot, and guessing a title from a
filename would produce confident wrong placements instead of an obviously
empty catalogue somebody notices.

**`broll_brief`** — the whole question as one read-only call: the catalogue
with synopses and durations, then every shot position with the narration that
plays over it and how long it is held. It goes through `_picture_plan`, not
`build_shots`, for the reason the picture lane does — a brief offering a slot
`export` will not produce invites a pick for a shot that cannot exist.

**It does not choose, and that is the measurement rather than a preference.**
The loop is: read the brief, decide, write back through `cue_add`, where
`plan_picture` checks each one like any other cue. Driven end to end that way
on the real project it rewrote 11 of 25 cues, planned clean, and rendered
8064 of 8064 frames.

### Two negative results worth the same space

**A second reviewing pass makes it worse.** Handing the positions back with
the picks in them and asking for exactly the three failures the first pass
shows — the same clip twice across a card, a clip one beat off its own
sentence, a clip spent before the narration reaches its subject — changed 6
answers and scored **13 → 10**. It is not implemented for that reason, not
because nobody thought of it. The failures are real; asking for them back is
not how they get fixed.

**Context the brief carries because it is cheap, not because it was shown to
help.** Shot durations and the `card:` positions moved 12 correct to 13, which
is noise. They stay in — a long hold plausibly wants footage that sustains —
but nothing here should be defended on their behalf.

### What this does to `describe`

It is not the answer to *which clip*, and the 139 windows earned nothing on
this video. Its remaining honest use is *which second inside a clip* — the
in-point a `src_start` pin sets, which is genuinely visual. Worth stating
plainly: **the Scream cue table pins nothing at all.** All 25 video cues run
off `plan_picture`'s cursor, so on the one real project there is, the visual
index currently has no consumer. Kept rather than removed because the pinning
case is real and untested, not because it is carrying anything today.

## The card record, step 2 of aspect swap — 2026-08-10

A card now carries what it was made from. `card_new` writes
`(card, template, slots, canvas)` into a `cards` list in the manifest — the
v3 → v4 bump step 1's write-up deferred to here — and `card_reauthor` fills
the template again at the project's current canvas, rewriting both the SVG
and the PNG. `lucid card reauthor` with no name sweeps every recorded card the
canvas has left behind; named, it redraws that one whatever its canvas.
`canvas` gained `cards_stale` and `cards_unrecorded`, because the moment the
shape moves is the moment to say which cards no longer agree with it.

**It re-authors rather than resizes, and that distinction is the whole
feature.** Measured on the real project rather than asserted: the same receipt
card, authored at 1920x816 and then handed to the new canvas both ways.

```
render the old SVG at 1080x1920   →  1080x459   (a 459-row band, 76% bar)
card reauthor                     →  1080x1920, cream to all four corners
```

The 459 is the same number the costing spike and step 1 both measured, from a
third direction. `-size` fits, so no rasterisation of a 16:9 document will ever
fill a 9:16 frame; only `fill_template` can move the geometry, and only the
record can feed it. The re-authored source carries `viewBox="0 0 1920 3413"` —
the aspect in the template's own 1920-wide units — which is what a resize
cannot produce.

### The thing the note got wrong: the Scream cards are not lucid's

The design note (PLAN.md § Aspect swap, finding 5) says step 2 "closes the
wiki's 13-card item ... which is open regardless of whether anything ever goes
9:16". It does not, and the reason is one `ls`:

```
assets/cards/  →  12 PNGs, 1920x1080, no SVG beside any of them
```

They were drawn by `goodsometimes/scripts/make_scream_cards.py` before
`card_new` existed and copied in. So they have no record to persist and no
source to re-render — `card_reauthor` names all twelve under `unrecorded`
rather than pretending, and `card_render` could not touch them either. The
note's finding 5 read `card_new`'s reply and inferred that the cards on disk
came from it. **Every card in the one real project predates the generator.**

Two consequences, both real:

- **The 1920x1080-in-a-1920x816-frame defect is still live in the shipped
  film** — a 4:3-shaped card fits by height into a 40:17 frame and gives up
  roughly a quarter of its width to bar, which is finding 4 of the motion
  graphics note measured on the cards that provoked it. Step 2 does not fix
  it; it makes every card made *after* it immune.
- **Regenerating those twelve through lucid is not lossless, and now it is
  costed.** The script's receipts carry three ink levels inside one
  paragraph — `dim`, `key`, and an amber `em` on the fragment the VO quotes —
  and lucid's `receipt` has one `quote` slot of kind `lines`, drawn in a
  single fill. Re-authoring them today would flatten the emphasis. Closing the
  wiki item through lucid therefore needs an emphasis-capable quote slot
  first; that is a template change, and it is not in this note.

### The guard that was looking at the wrong file

Finding the PNG-only cards found a hole in `card_new`. Its
already-exists refusal checked the SVG source alone, so a name with a PNG and
no SVG — every one of the twelve — was waved straight through and the raster a
cue resolves to was overwritten without the guard ever tripping. Either file
now counts as existing. This is the same shape as every other trap in this
repo: the failure produced a file and exit 0.

### What it deliberately does not take

`card_reauthor` has no width or height. A card authored at anything but the
project canvas is the motion graphics note's finding 4 all over again, and the
knob for rendering at another shape is `canvas`, one level up. A test asserts
the signature, because the argument is the kind that gets added back by
someone being helpful.

A record holds content and a geometry and never a length, so it sits under the
same rule as a footage description and is not in tension with PLAN.md § The
property everything below defends.

## The MLT reframe, step 3 of the aspect swap — 2026-08-10

A swapped canvas now crops to fill instead of pillarboxing. The design note
(PLAN.md § Aspect swap) had already measured the mechanism — a `qtblend`
filter on the source producer, no new dependency, no consumer change — so
this step was mostly building what finding 3 described. What it added was the
part the note left open, and the verification.

### The unit, and why it is stored as asked

A reframe is `(clip_id, rect)` in **source pixels** — geometry, never a
length, the same rule a footage description follows, so no cut can invalidate
one. The build extended that one step: the rect is stored **as asked** and
refit to whatever canvas is in force, so a canvas change cannot invalidate one
either. Storing the fitted rect would have baked one canvas's shape into a
record that outlives it.

`reframe` is a manifest key and takes **no schema bump**, which is the
`canvas`/`caption_style` shape rather than the `cards` one. Absent means
"centre-crop every clip", a complete answer rather than a gap: the migration a
bump would carry is `setdefault([])`, and CLAUDE.md's bar is that the number
has to be what makes the key true.

### Grow, don't shrink — the decision the note did not make

The note said the default crop is centre and reported rather than assumed, and
that a clip can override it. It did not say what happens when the override is
not already the canvas's shape, which is the normal case: someone drawing a
box round a subject types a box round the subject, not a 9:16-exact rect.

Two readings, and they fail differently:

- **Grow** (the ask ⊆ what is used) pulls in surroundings, and can be
  impossible — "show me all of a 16:9 frame in 9:16" has no answer.
- **Shrink** (what is used ⊆ the ask) never refuses, and cuts the subject in
  half.

Growing won on the asymmetry: the ask is a *floor*, everything named stays on
screen, and the impossible case is refused with the largest rect that would
have worked rather than quietly clipped. The reply names both `asked` and the
`crop` it became. A grown rect that leaves the source is shifted whole back
inside it — past the edge is MLT's idea of the footage, not the footage's.

### The trap, and the guard for it

Finding 3 had already named it: `mlt.py` writes one node per distinct resource
**per role**, so a file used by both the edit and the picture lane has two, and
a reframe applied per resource crops it on one track and letterboxes it on the
other in the same frame — at exit 0. The filter is applied per node, and
`document()` reads the finished tree back and refuses if the set of
filter-bearing nodes is not the set that should have them. Same discipline as
`declared_frames`, and for the same reason: every failure on this path is a
file rather than an error.

Two things deliberately never get one. **A still is never cropped** — a card
is authored at the canvas and re-authored when it moves (`card_reauthor`), so
cropping one would be lucid losing a corner of a title it drew itself. **The
bin keeps the raw media** — it is `xml_retain`-ed out of the render, and a
crop is a timeline placement rather than a property of the file.

And no filter is emitted at all when it would say nothing: a source already at
the canvas's aspect, uncropped, lands on exactly the rect MLT would have used
unaided. That is what keeps every project without a canvas override writing a
byte-identical document to the one it wrote before this existed, and a test
asserts the two strings are equal.

### Verified against a real render, and the bbox check nearly repeated its own trap

Two melt renders of the real Scream cold-open (1920x816) at 1080x1920, plus a
third on the layered project, all sampled for pixel geometry.

1. **It fills the frame.** Five frames of the single-source render, brightness
   bbox: content spans x 0..1079, y 0..1919 in every one — against the
   measured pillarbox's 459 rows of 1920.
2. **It is the right pixels, not merely the right count.** Compared frame for
   frame against ffmpeg's own `crop=459:816:730:0,scale=1080:1920` of the
   source at the matching source timestamp: **mean absolute difference
   0.33–0.37 of 255**, which is encoder noise.
3. **An override moves the picture to where it says.** Re-rendered at
   `1400,0,459,816`: 0.43–0.61 against ffmpeg's crop at x=1400, and 18–39
   against both the centre crop and the centre render. The number that matters
   is the pair, not either alone.
4. **The picture lane reframes through the compositing transition too** —
   0.86–0.91 against the reference, on a layered project cut down to one cue.

**The bbox check nearly reproduced finding 2's own mistake.** On the layered
render it reported 370–423 lit rows — close enough to the pillarbox's 459 to
read as a failure — and the rows outside were *exactly zero*, which is what a
black bar looks like and not what a dark scene looks like. Both readings were
wrong. The frames sampled were the film's opening credits: white text on
black, content confined to source rows 302..482, which scale to render rows
718..1140. The render was right and the probe was measuring the source's own
black. What settled it was the comparison against both hypotheses as pixels —
0.86 against crop-to-fill, 20.79 against a synthesised pillarbox. **A bbox
answers "where is the bright part", never "where is the frame", and finding 2
already paid for that lesson once.**

### What it leaves the preview owing

Finding 6 recorded that the preview holds two ideas of the frame and they
"agree today only by accident" — `captionBox()` contain-fits the project's
caption canvas while the `<video>` letterboxes by the media's own aspect. They
now disagree on purpose: a 16:9 clip in a 9:16 project previews at full width
while the render keeps a 459-pixel band of it, so the page draws footage the
export drops. That is the viewer's version of drawing a lane `export` cannot
produce, and it is step 4 — which this step moved from tidiness to a real
disagreement.

## The viewer's frame, step 4 of the aspect swap — 2026-08-10

The preview stops being shaped like its media and starts being shaped like the
render. `#frame` is the project canvas, every layer draws inside it, and media
is *placed* at the rect the MLT writer places it at rather than fitted to its
own aspect. What step 3 left owing — "the page draws footage the export drops"
— is closed, and so is finding 6, which is the older half of the same bug.

### One rectangle, and the payload that carries it

`timeline_view` gained two fields. `canvas` is `_mlt_resolution`, the number
the MLT profile declares. `reframe` maps a clip to `dest` — `mlt.Reframe.
dest_rect`, where the *whole* source frame lands on that canvas so its crop
fills the frame, in canvas pixels. The page scales that by the frame's own
size and lets `overflow: hidden` do the rest, so it **reproduces** the crop
rather than re-deriving one. It is the same rect the writer turns into a
`qtblend` property, and a test asserts the string the document carries is the
one the view reported.

Three consequences worth writing down, because each was a choice:

- **A clip the render does not crop still gets an entry**, and its `dest` is
  `fit_rect` — the contain placement MLT uses when no filter is emitted. One
  code path draws both, so the page never chooses between two ways of putting
  an element somewhere. It is also why a project with no canvas override looks
  exactly as it did: the placement it computes is the placement it had.
- **A still is never placed**, matching the writer, which emits no filter for
  an image. So a card authored at the old canvas pillarboxes in the preview
  and pillarboxes in the render, which is what `card_reauthor` is for and what
  a `cover` in the stylesheet would have hidden in both places.
- **A rect the canvas outgrew comes back as `reframe_error`**, not an
  exception — `shots_error`'s policy, for its reason: the view is how a person
  finds the rect to fix. The frame is still drawn at the canvas's shape, and
  the pane draws the sentence.

`captionBox()` went from twelve lines to one. It used to contain-fit the
caption canvas into `#viewer`, which was a second construction of the same
rectangle the picture was drawn against — finding 6's whole complaint. The
layer is now `inset: 0` in the frame and the only thing computed is the
*scale*, still against `captions.REFERENCE_HEIGHT` rather than the canvas,
because a caption size is quoted at 1080 tall whatever the footage is.

### `aspect-ratio` cannot do this, and the reason is worth one line

The frame's size is measured in JS off a `ResizeObserver`. CSS was tried
first: a flex item with no in-flow content has no size for `aspect-ratio` to
keep the ratio of, and every child of `#frame` is absolutely positioned, so
the box collapsed. Adding `width: 100%; height: 100%` over-constrains it and
`aspect-ratio` is then ignored outright.

### Verified in a real browser, twice, on real footage

`chrome-headless-shell` over CDP against `lucid web`, on two copies of the
Scream project — one swapped to 1080x1920, one left at its derived 1920x816 —
with shots reached by clicking the V2 lane the way a person reaches them.

**Geometry, which is layout and not arithmetic.** The frame measured
386.44x687 in an 800x687 pane: aspect 0.5625 against the canvas's 0.5625, and
centred. `#caption-layer`'s box equalled `#frame`'s to the hundredth of a
pixel. Then the strong claim: for each shot, the visible region was derived
from `getBoundingClientRect()` alone — the element's box intersected with the
frame's, converted to source pixels by its own `videoWidth` — and compared
against the server's `crop`. Five of six agreed **to the pixel**
(`[730, 0, 459, 816]`, which is finding 3's own number), the sixth within one
(451 vs 450, a half-pixel centring).

**Pixels, against the wrong hypothesis too.** `drawImage` of the visible
region into an 8x4 mean-RGB grid, against ffmpeg's frame at the source
timestamp the page claimed, cropped the same way — and against the *uncropped*
frame, which is the hypothesis this step exists to refute. Every read: 19.5 vs
33.7, 11.9 vs 37.5, 4.4 vs 33.2, 11.8 vs 30.9, 11.2 vs 32.1, 10.0 vs 27.8, out
of 255. One number alone would have said nothing; CLAUDE.md's rule about the
brightness bbox is the same rule.

**The first run had one row where the wrong hypothesis won**, 46.4 against
36.0, and the calibration is what caught it rather than a judgement call. Each
read also grids the *whole* decoded frame against ffmpeg's whole frame, which
asks "are these two even the same moment?" — every good row answered 4.6–5.4,
that one answered 28.1. A follow-up probe named it exactly: `seeking: true`,
`readyState: 1`. **`drawImage` on a mid-seek `<video>` hands back the frame
that was there before**, which reads exactly like a wrong rectangle; the same
element read after settling scored 4.8. The harness now waits for
`!seeking && readyState >= 2` rather than for a guess at how long a seek
takes. This is the third distinct way this repo has found to measure a black
or stale frame and believe it.

**And the unswapped copy is unchanged**, which is the regression half: the
frame took the footage's own 40:17 and filled the pane's width, uncropped
clips showed their whole source, and the one clip that does crop at that
canvas (`s4-reveal`, 1920x800 in 1920x816) cropped by the 19 px the server
said. That crop is invisible at an 8x4 grid — 5.1 against 5.3 — which is worth
saying plainly: the pixel discriminator only bites when the crop is large, and
the geometry check is what covers the small ones.

### A shipped bug the readback could not see

`#viewer.audio video` — the audio-only rule — matched **every** `video`
descendant, including `#picture-video`. `audio` is about the clip the
*transport* holds, and on a VO project that is the audio-only one, while the
picture lane over it is the entire assembly. So every shot in the Scream
project was `visibility: hidden` behind the level display.

It survived because of how the picture layer was verified: `drawImage` reads a
`visibility: hidden` element back perfectly happily, and screenshots were
already known to be useless for `<video>`. The measurement that proved the
layer correct could not see that nobody could see it. The selector is now
`#viewer.audio #media`, and the browser run reports `#picture-video` computed
`visible` while `#media` stays `hidden`.

### What this does not cover

- **`tiktok-reels` is not in it.** That is step 5, and it is now honest to
  build: one `EXPORT_PRESETS` entry plus the canvas.
- **The caption style is not re-tuned for vertical.** The preview now shows a
  64pt caption wrapping to five lines in a 608-wide reference, which is what
  the render would do. Showing it is this step's job; deciding about it is a
  watch, which is step 6.
- **Nothing here places a card.** A still is contained, deliberately, and the
  twelve unrecorded Scream cards still need an emphasis-capable `quote` slot
  before they can be re-authored at all.

## `tiktok-reels`, step 5 of the aspect swap — 2026-08-10

The preset the item was named after, and the smallest step in it: one
`EXPORT_PRESETS` entry, its four encode values copied from `youtube`, plus a
precondition. What took five steps to earn was not the encode — it was the
render behind it, and the honesty of the name.

### The decision the build had to make, because the note left it open

PLAN.md § Aspect swap called step 5 "one entry in `EXPORT_PRESETS` plus the
canvas". Those two halves live in different places and the note did not say
how they meet. A preset in that dict is four consumer keys and nothing else —
`vcodec`/`crf`/`preset`/`acodec`, the combination HISTORY.md § 4 measured as
memory-safe — and the canvas is manifest state that routes the export and
reports what its crop costs. So there were two shapes available:

1. **The preset checks the canvas and refuses**, naming the `canvas` command
   that fixes it.
2. **The preset sets the canvas**, and a vertical render falls out of one
   flag.

**It checks.** (2) is an export argument rewriting project state on the way
past, which is the same class of failure as picking the writer from an
argument — the thing `export` picks its writer *from the project* to prevent.
A flag that reshapes the project also silently invalidates nothing visible: it
would leave a swapped manifest behind after a render the caller may have
cancelled, and the next unflagged export would be vertical for no stated
reason. So `PRESET_ASPECT` is a claim a preset's *name* makes about geometry,
checked against `_mlt_resolution` and never applied.

**Exact 9:16, not "portrait enough".** Both platforms specify 9:16, and a
preset named after that spec that quietly accepted 19.5:9 would be guessing on
the caller's behalf about a shape the caller can simply state. A vertical
canvas that is not 9:16 is a legitimate export; it goes out under `youtube` or
`web`, and the refusal says so rather than leaving it to be discovered.

The comparison is cross-multiplied (`w * 16 == h * 9`) rather than a ratio:
1080/1920 is not exactly representable, and a float test refuses the one shape
that is exactly right.

### The audio-only project is refused separately, and that is not fussiness

`_mlt_resolution` falls back to 1080p when nothing in the manifest has
picture. Routed through the geometry check, an audio-only project under
`tiktok-reels` would have been refused for being **1920x1080** — a true
refusal quoting a frame that project has not got, which is the shape of every
plausible-and-wrong message this repo has had to unpick. It is caught first,
and says the real thing: there is no picture to shape.

Asked of the manifest rather than of the rendered payload, deliberately —
every other canvas derivation in `ops.py` walks `clips`, and § Aspect swap's
finding 4 is about what happens when two of them stop agreeing.

### What was verified, and where

- **A real melt render, not an exit code.** `canvas 90x160` (exactly 9:16,
  even on both edges, cheap to encode) plus `--preset tiktok-reels` renders
  through melt and ffprobe reads **90x160** back off the file, with the
  consumer still the four measured-safe keys. The preset name in a reply
  proves nothing — a degraded render would carry it too.
- **The refusal against the real 23-source Scream project, through the CLI.**
  1920x816 (40:17) refuses with `lucid canvas 1080x1920` in the message, and
  writes nothing: no output file, and no `canvas` key added to a manifest that
  did not have one. That last check is the point of choosing (1).
- 739 tests pass.

### What this does not close

**Step 6 — the watch.** Nothing here has been looked at as a film. The build
order says stop before ranking anything further, and it means it: every prior
step in this item corrected its own premise, and three of them were corrected
by building rather than by reasoning. A vertical cut of real footage is what
says whether centre-crop defaults are usable, whether a 64pt caption in a
608-wide reference reads, and whether the twelve unrecorded cards make the
whole thing moot until they can be re-authored.

## The emphasis-capable quote slot — 2026-08-10

Steps 1–3 of PLAN.md § The emphasis-capable quote slot, built in one pass
with the remainder finding 5 filed ahead of them. What the note costed is
what landed; what it did not cost is three traps, each of which produces a
wrong card at exit 0, and one refusal that ends the item short of closing
the wiki's card row.

### The remainder first: the font report could not see a weight

Finding 5 filed this as owed *before* step 1, and it was right for a reason
the finding only half states. `em` is not a colour — `make_scream_cards.py`'s
own `STYLES` is `key: (zb600, INK, None)`, `dim: (zb600, INK, 0.42)`,
`em: (zb700, AMBER, None)` — so emphasis is a **weight** change, and a
reporter blind to weight would have gone on being wrong about the exact
thing this item added.

Three faults, each in the unsafe direction:

1. **`font_report` answered per family.** `receipt.svg`'s title is
   `font-weight="700"` wrapped around a `<tspan font-weight="400">`, which is
   two faces of one family — and the tspan names no family at all, because
   both properties inherit. One entry described neither. The fix is a tree
   walk carrying `(family, weight)` rather than a collection pass, which is
   also what makes the report right about the `<tspan>`s step 1 then went on
   to emit.
2. **CSS weights are not fontconfig weights.** fontconfig's Bold is 200, so
   every CSS value is above every real one. Measured here: unmapped, CSS
   **400 and 700 both answer Lato Black** — not merely wrong, identical, so
   the report could not have distinguished any two weights of anything.
3. **A family name went into a fontconfig pattern unescaped.** A pattern is
   `family-size:key=value`, so `fc-match 'Zilla Slab-24'` reads the tail as a
   point size and answers about `Zilla Slab` — reporting a face nobody has as
   installed.

Settled the way CLAUDE.md requires — **by measuring a render, never by
`fc-match`**. Ink widths through `render_svg`'s own coder, across Lato, Noto
Serif and Zilla Slab: the mapped query names the same face the render draws
on every row where a distinct face exists, and the ladder is monotonic
(Lato 400/500/600/700/900 → 1235/1238/1244/1251/1266 units). The test
renders two weights and compares; without the mapping both report one style
while the renders differ, so it is not vacuous.

Captions are untouched on purpose. libass takes a bold *flag*, not a CSS
weight, and how that resolves through fontconfig has not been measured here
— so `font_match` gained an optional weight rather than a guessed 700.

### Step 1 — the `runs` slot, and the whitespace trap

The vocabulary is read off the real cards rather than invented, which is
what makes step 1 checkable: rendered and sampled back off the raster, all
three levels land on finding 1's measured values **exactly**, L1 distance 0.
`dim` is ink at 0.42 rather than a flat grey, so it stays right when the
paper is not cream.

Markers rather than JSON runs, per the note — `[em]…[/em]`, `[dim]…[/dim]`,
unmarked text is `key`, and `[[` is the escape a marker syntax owes. A `[`
that begins no known marker is left alone, so `[sic]` is prose. Runs nest
innermost-wins and span line breaks. A close with nothing open and a run
left open are both refused, because either draws and looks deliberate.

**The trap is that splitting a line into per-run `<tspan>`s silently eats
the spaces between them.** SVG collapses whitespace at every chunk boundary,
so `the [em]perfect[/em] horror` renders as `theperfecthorror` — 25px
narrower at 48px, at exit 0, reading as a deliberate ligature rather than a
bug. `xml:space="preserve"` restores it to the byte and *inherits*, so it is
set once per line rather than per run. Its test uses `[key]` as the control:
same weight, fill and opacity as unmarked text, so the tspan split is the
only variable.

### Step 2 — the flow, and the two things the note did not specify

Greedy wrap over candidate lines, rendered rather than summed, against a
body width the template declares. `fill_template` grew `flow`, defaulting
on: the failure it closes is silent, because the script throws away
`wrap_runs`'s final baseline and a long enough quote overran its own footer
with nothing saying so.

**The control is a test rather than a claim.** A character count is built
alongside and run on finding 2's own adversary: `WWW MMM` wraps to **2694
units in a 1640 box — over by 1054** — where the measured wrap fits at 1491.
On the real Scream review lines the two agree, which is exactly why the
adversary is the row that decides anything.

Two decisions the note left open and the build had to make:

- **The scratch canvas is the entire cost of a measurement, and clipping it
  is silent.** The same line measures 1622 units on a 20000x400 scratch and
  1622 on 3000x120 — at 413ms and 38ms, because a measurement is
  rasterisation, not layout. But a canvas that is too small does not error:
  it **clips**, and a clipped line measures *narrower*, which ends the greedy
  wrap early and overflows the card. So the canvas is sized from the box and
  grows when the ink reaches its edge. A real quote went 11s → 1.5s.
  Batching many candidates into one `magick` call was tried first and is
  worth nothing (6.39s vs 6.5s) — the cost is per-image, not per-process.
- **The box is derived from the canvas, not declared.** It is the space
  between the slot's first baseline and the template's own bottom margin,
  and that margin moves with the aspect. Hard-coding it would refuse at 9:16
  a quote that plainly fits there; the same quote is tested both ways.

The refusal names the flow, the width and the overflow, and does **not**
grow the card. A template that got taller to fit its text would be a slot
value deciding the frame, which is the failure § The property everything
below defends exists to prevent.

### Step 3 — ten of twelve, and the two refusals are the finding

The twelve were re-authored on a **copy** of the Scream project
(`~/lucid-cards-reauthor/proj`), values transcribed from the script's own
`CARDS` table, with the Zilla Slab and Outfit stacks passed per finding 6.
The real project was not touched: `card_new` needs `overwrite` to replace a
card, and spending the twelve originals to see whether the replacements
were any good is not a trade worth making before anyone has looked.

**Ten came through at 1920x816, filling the frame, with emphasis and a
measured wrap. Two are refused, and the refusal is correct.** The receipt's
header is fixed in template units — title at 232, stars at 330, date at 452,
quote's first baseline at 572 — while the canvas is 264 units shorter than
the one it was drawn for. So the quote box is **3 lines at 2.35:1 where it
is 7 at 16:9**, and the two longest Letterboxd reviews flow to 4 and 6.

That is not a bug in the flow; it is the aspect swap surfacing a template
that does not adapt. Before step 2 the same two cards would have overrun the
bottom of the card in silence. **The item does not close here**, and the
choice between shortening verbatim reviews, splitting them across two cards,
scaling the receipt's header with the canvas, or keeping those two at 16:9
and accepting the pillarbox is editorial, not mechanical.

One real bug fell out of the attempt: the gap that keeps a quote clear of
the wordmark was being reserved whether or not a wordmark was drawn, costing
a line exactly where lines are scarcest (2 lines at 2.35:1 rather than 3).
Nothing at 16:9 could have noticed — the box is 7 either way.

### What this does not cover

- **Nobody has watched these in a cut.** Step 4 of the note is Stop, and it
  still is. The ten are on a copy, and a served comparison page is the only
  place they have been looked at.
- **Paragraph gaps.** The script draws paragraphs with 26 units of extra
  lead; a `runs` slot's blank line is one line height. Two of the receipts
  have more than one paragraph.
- **`card_reauthor` re-flows but has not been run at a second canvas** on
  real cards, because the twelve had no records to re-author from until now.

## The caption animation nobody wanted — 2026-08-10

DAYDREAM.md § Captions had one gap left: Daydream lights one word at a time
and pops it, lucid sweeps a `\k` fill and moves no glyph. It was costed, the
costing found the recorded blocker wrong, the four candidate looks were
rendered on the real film, and **Tyler watched them and picked the fill lucid
already writes.** Nothing was built. The design and every measurement are in
PLAN.md § Per-word caption animation; what belongs here is the dated verdict
and the two things the exercise is worth keeping for.

**The blocker was a category error, which is a shape this repo had not seen.**
PLAN.md, DAYDREAM.md and `captions.py`'s own `Preset` docstring all said the
feature — and the single-word highlight it shares a construction with — needed
one Dialogue event per word. That build makes lucid own text layout, because
an event holding one word cannot know where libass put the others. Measured:
both are per-word `\t` blocks inside the one event *per line* that `to_ass`
already writes. Built to check, the per-word-event version drew a single word
centred in the frame — **not a harder version of this feature, a different
feature.** Three documents agreed with each other and all three were wrong;
the phrasings differed enough to read as corroboration.

**The decision was gated on something no amount of building resolves.** A
scale pop reflows the line — every other word moves 13 px on the real film,
20 px on a flat 1080 frame, twice per word, seven times a line — because a
wider glyph run pushes its neighbours. `\fscy` alone, `\frz`, `\bord`,
`\shad`, `\blur`, `\be`, `\alpha` and `\c` move nothing. So "a real pop" and
"a line that holds still" are exclusive, and the choice was editorial from
the start rather than after a build.

**Two findings outlive the decision.**

- **The preview would have disagreed with the render, again.** CSS's natural
  pop is `transform: scale()`, which does not affect layout; ASS's `\fscx`
  does. The obvious browser half would have shown a still line with one word
  growing over a file where the whole line breathes — the same shape as the
  `\k` fill disagreement in § Caption styling, caught this time before any
  code existed to trip it. It binds any future caption motion whatever its
  form.
- **"No effect" and "no contrast" are different answers.** The first pass
  reported `\bord`, `\shad` and `\blur` as not animating at all, zero pixels
  changed. They animate; the outline and shadow were black and the probe
  background was black. Third instance of this failure here, after the two
  brightness-bbox misreads CLAUDE.md already carries. A probe that can only
  report absence has to be shown a positive control first.

**What would reopen it**, so the next reader does not re-run the probes: a
watch that wants the current word legible late in a line. That is the fill's
one real cost — by the seventh word of a seven-word cue every word is in the
highlight colour, so it signals progress through the line rather than which
word is being said. Reopening costs about a day, not a layout engine, and the
tag measurements stay valid because they are facts about libass rather than
about this project. The four renders are kept at `~/lucid-caption-anim/`.

## The film had no captions in it — 2026-08-10

The layered-timeline row said the finished cut's captions were "the `clean`
default — white, no fill", so applying the look picked earlier that day read as
one `caption_style` call and a re-render. It was not. **`~/lucid-final-cut/out.mp4`
had no captions burned into it at all**, and had never had any.

The check that found it was a pixel readback of the film itself, at 17 points
across its 336 seconds: **zero caption ink at twelve of them**. The other five
were not captions either — they were ~289000 saturated pixels, the *whole*
bottom band, which is a full-frame review card. A sentence in a status table was
the only thing that had ever asserted the captions existed.

**This is § The VO the project was holding again, one layer out.** That entry's
rule is that a project seeded from one stage of an outside edit stays at that
stage while every downstream number agrees. Here nothing was even stale: the
manifest's `caption_style` was genuinely `clean`, `caption-view` genuinely
resolved it, and both were true statements about *project state*. Neither is a
statement about the file, and no op connects the two — `export --render` does not
burn captions and never claimed to, `captions --burn` is a separate opt-in step,
and nothing reports that a render was made without it.

So the rule this earns is narrower than the VO one and shares its shape:
**`caption_style` is a claim about what a burn would draw, never evidence that a
burn happened.** The only thing that settles it is reading the render.

### What the burn then found, which the row could not have

`verify` and `check_frames` were clean, because they answer whether the render
says what the timeline says, and it did. What they do not answer is whether
anyone can read the result. White captions over the seven light "receipt" cards
measure a **1.10:1** contrast ratio against the card's own `(250, 243, 236)`;
amber over the same card is 1.41:1. Both are invisible, and what keeps the words
legible at all is the 3px black outline. Over footage the same captions measure
21:1.

Measured against the shot plan rather than eyeballed, because the fraction is
what decides whether it matters: **13 of 38 shots are cards, 90.6s of 336.3s**,
and of the twelve distinct cards **seven are light and five are dark**. Only the
light ones are affected, and against them **49 of 178 caption lines — 67.3
caption-seconds** draw at that ratio.

The candidate fix measures well and is not free. `caption_style --box` (ASS
`BorderStyle: 3`, the one field that differs) takes the same words from 1.95:1
to **20.87:1** — but libass draws one box per override block, so a `\k` line
gets one box per karaoke chunk and the top and bottom edges come out ragged
where they meet. **Fill and clean box edges are in tension the same way a scale
pop and a still line are** (§ The caption animation nobody wanted), which makes
this an editorial call and not a build. It is Tyler's, on a watch, and the 13
seconds either way are rendered and served for it.

### The smaller correction, on the record because it changed what he watched

The four caption treatments of § The caption animation nobody wanted were
rendered with a **red** highlight (`&H003B30FF`) that the probes hardcoded, and
option 1 was labelled "what lucid writes today". lucid's `karaoke` preset is
**amber** (`&H0000C8FF`). The label was wrong; the decision was not, because the
colour was constant across all four options and the variable was the motion. But
the film he approved from and the film the preset produces differ in a way he can
see, so it is said plainly rather than left to be noticed.

The generated ASS is otherwise identical to the probe's `fill.ass` — same `\k`
values, same line breaks, same PlayRes and margins — which is what makes the
comparison exact.

## The cut and v7 are different shapes — 2026-08-10

The layered-timeline row's first watch asked whether *anything but the music
and the outro card* still separates `out-karaoke.mp4` from Video Final v7. It
was written as a question only a watch could answer. It was not: **the two
films are different shapes, and it is measurable in one ffprobe.**

- **Video Final v7 is 1920x1080.** lucid's cut is **1920x816**.
- lucid derived its canvas from the *footage* (`_footage_resolution` — the
  Scream clips are 1920x816 scope), and the hand edit derived its from a
  1080p timeline.

That single difference inverts how both kinds of material sit:

| | v7 | lucid |
|---|---|---|
| movie footage | letterboxed, 132px bars top/bottom | fills the frame |
| review cards | **fill the frame** | **234px bars each side** |

The cards are 1920x1080 stills in a 1920x816 project, and **a still is
contained, never cropped** — so every card renders as a 1451px island. That
is 1451 measured against 1451 predicted (`1920 * 816/1080`) and bars of 234
against 234.5 predicted, i.e. the geometry to the pixel, not a brightness
bbox reading a dark scene as a bar. v7's letterbox was measured the same way:
content rows 130..947, 818 tall, against 816 predicted for the same contain in
the other direction.

**Confirmed to be the same card, not merely a similar one**: lucid's card
content, cropped out of its bars and downscaled, differs from v7's frame at
the matching timestamp by a mean of **0.03 of 255**. lucid's cards *are* v7's
cards, shrunk.

**Scale: 13 of 38 shots, 90.6s of 336.3s — 27% of the film.** This is the
strongest available candidate for the 2026-08-10 log entry's standing open
question, *"the hand-assembled cut is still the better one, and why is now the
open question."* A quarter of the film displayed at 75% width in black would
read as cheap without being easy to name.

### It is not a one-command fix, and that is the useful half

The obvious repair — `canvas 1920x1080` to match v7 — was run on a copy.
`fills_frame: true`, and **all nine footage clips move to `cropped`**. lucid
crops footage to fill and contains a still; it has no letterbox mode for
footage at all, by design (CLAUDE.md: media is *placed*, never fitted). So:

1. Keep the scope frame and **re-author the cards at 1920x816** — which lucid
   can now do (below).
2. Match v7 at 1080p, which needs a footage-letterbox mode lucid does not
   have. That is a build, and it argues against the current "always fill" rule.
3. Leave it. Nothing is broken — `verify` and `check_frames` agree, because
   the render does match the timeline. Legibility was never their question,
   the same gap § The film had no captions in it opened.

**This is § The film had no captions in it one layer out again.** Every check
lucid has was green, and the thing that separated the two films was a property
no check asks about. Served for the call at `vertical.html`.

## Step 6 of the aspect swap, watched — and its blocker dissolved — 2026-08-10

The last open piece of § Aspect swap: *"A vertical cut of real footage is what
says whether centre-crop defaults are usable, whether a 64pt caption in a
608-wide reference reads, and whether the twelve unrecorded cards make the
whole thing moot."* Rendered, at `~/lucid-vertical/`, and served.

### The card blocker dissolved, and it was never twelve

§ The card record said the twelve Scream cards have files and no record, so
`card_reauthor` can only report them. True of `~/lucid-final-cut/proj`, whose
`cards` key is `[]`. **But the ten records exist** — in
`~/lucid-cards-reauthor/proj`, complete with `(template, slots, canvas)`, and
the slot table for **all twelve** is in that directory's `reauthor.py`.

So the records were never lost; they were written against a *different working
copy*. And that copy is the 411s silence cut (73 segments), not the 336s film
— **§ The VO the project was holding, a third instance.** A second project
copy at the wrong edit stage, holding the only copy of state the real one
needs. The rule earns a corollary: **derived project state written on a
scratch copy has to be carried back, or the next reader finds the film missing
it and concludes the feature does not work.**

**All twelve author at 1080x1920, zero refusals**, through `card_new` at the
project canvas. Including the two that refused at 2.35:1 — a receipt holding
three quote lines wide holds four and six tall, because the frame got taller.
**The editorial call the parity row describes is a 16:9-only problem and does
not gate the vertical cut at all.**

The render: 1080x1920, **8064 frames, `agrees: true`**, 336.34s, `writer:
melt`, `preset: tiktok-reels`. Four sampled frames fill the frame edge to
edge — no bars anywhere, which is what the twelve re-authored cards buy.

### The centre crop is not usable, and that is the answer

Six frames across the film, read back from the render:

- the title card's **"SCREAM" crops to "REA"**
- one face survives; one is cut in half
- a staircase shot where the subject sits below the crop
- a wall with no subject in it at all
- and a card

**One of six is composed correctly.** A centre crop cannot be the default for
this footage. lucid already has `reframe` per clip, so the fix is nine
decisions, not a feature — but the *default* is now measured rather than
assumed, which is what step 6 existed for.

### The receipt template does not compose tall

The five dark `reveal` cards read well at 9:16 — centred, generous air. The
seven cream `receipt` cards stack from the top, so at 1080x1920 the content
occupies the top quarter and two-thirds is empty cream. Not a refusal and not
a bar: `fill_template` measured every line and fit them. **A template that
fits is not a template that composes**, and only the wrap was ever measured.

## kdenlive's trailing black frame, filed closed — 2026-08-10

Carried as **Unfiled** on the layered-timeline row. Reproduced live against
the installed versions (auto-editor 31.4.2, melt 7.40.0): a 360-frame
single-source project exports with its clip entry correct (`out` = frame 359)
and all three tractors declaring `out` = frame 360 — a count where MLT wants
the last index. `lucid frames` reports `delta: 1, agrees: false`, and
rendering that project through the real flatpak `melt` encodes **361 frames,
the last measuring YAVG 16 against ~122** for real picture. Pixel-identical to
the 2026-08-07 measurement in § `check_frames`.

**It files closed, not open.** It is a real upstream defect and it is already
named (`picture.KNOWN_TAIL_FRAME`/`TAIL_FRAME_NOTE`), detected
(`check_frames`/`check_black`), pinned by a real non-mocked test
(`test_server_stdio.py:2375`), and structurally walled off: lucid's own
`mlt.py` writes every `out` as `total_frames - 1` and `declared_frames()`
reads all four lengths back before returning, and **nothing in lucid pipes an
auto-editor kdenlive export into a delivered render** — `picture.render()`
only ever renders lucid's own MLT document, and single-source `export
--render` uses auto-editor's own renderer, which does not carry the +1.

The film confirms it end to end: `render-nocaps.mp4` and `out-karaoke.mp4`
both count exactly **8064 frames**, `agrees: true, delta: 0`, with no luma
drop on the tail — because that project is layered and never touched the
affected path. There is no action item; the row should stop carrying one.

## The vertical cut, refused on a watch — 2026-08-10

The 9:16 render was served and rejected on look: the cards "really small and
awkward", the footage "not formatted in a way that makes them easy to watch".
Both are real, both were measurable, and they are two unrelated faults. The
watch also settled captions for the 16:9 cut — **not burned in** — so the
caption-contrast A/B closes undecided-by-choice rather than unanswered. It read
as "this cut or any" at the time and is not: the vertical teaser asked for them
back the same day, § The hand-framed teaser, watched.

**The cards are drawn at 0.5625 and nothing said so.** `fill_template` sets
`view_height = round(TEMPLATE_WIDTH * height / width)` with `TEMPLATE_WIDTH`
pinned at 1920, so every template is authored on a 1920-wide grid and a
1080-wide canvas simply scales it down while the frame grows 1.78x taller.
Against the frame, type shrinks ~3.2x:

| Text | 16:9 | 9:16 |
|------|------|------|
| receipt title (122u) | 11.30% of height | 3.57% |
| receipt body (46u) | 4.26% | **1.35% — 26px in a 1920 frame** |
| reveal title (196u) | 18.15% | 5.74% |

Every earlier check passed because none of them looks at this: the cards
rasterise at the right pixel dimensions, `card_reauthor` reports twelve
successes, and the fit measurement (§ The emphasis-capable quote slot) asks
whether a quote *overruns*, which a too-small quote never does. **A card that
fits and a card that reads are different questions, and only fit was ever
instrumented.** The palette and both faces are correct and installed — Zilla
Slab and Outfit both resolve, checked because a missing face substitutes
silently — so the cards are on-brand and mis-scaled, not off-brand.

**The recorded footage fix was wrong.** The row said the centre crop needed
"nine per-clip `reframe` picks". Drawing the 9:16 window on all 25 footage
shots kills that in one image: `s2022-reveal` wants frame-left at 92s and
centre-right at 180s, and **5 of the 9 clips contradict themselves** across
their own shots. `reframe` stores one rect per clip, so the fix as recorded
cannot express the answer — this is a build, not an editorial afternoon. Note
the shape of the error: the blocker was named at the right layer and the wrong
*granularity*, which reads as a settings question right up until two shots of
one clip are put side by side.

The scope source is what forces it. At 1920x816 a 9:16 crop **keeps 23.9% of
the width**, so ~15 of 25 shots (the close-ups) survive and ~10 (two-handers,
the party scene, most reveals) cannot — no rect fits two people at a quarter
width. Three treatments were built and served: crop-to-fill, blurred backdrop,
and the whole picture on brand near-black. **Neither pole wins outright** — the
crop is the *best* option on a close-up and deletes an actor on a two-hander —
so the answer is a per-shot mode rather than a global one.

`goodsometimes/branding.md` turns out to specify the target and nothing had
been built to it: **1080x1920, title in the top third, bottom clear because
platform UI covers it.** Its palette and faces are what the cards already use.
Worth weighing against `analytics.md` § 2 before building: Shorts convert ~6x
worse than essays there, and `pipeline.md` already files a vertical cut as a
reach play.

## The vertical cut, made native: tracked framing — 2026-08-10

The three treatments above were served and **all three were refused, on the
axis rather than on the pick**: "B looks like a better version of C… I don't
even understand the purpose of C", and then the point that matters — landscape
parked inside a tall frame "isn't very enticing to people who regularly consume
vertical content." Tyler's own counter-proposal was the fix: crop to fill, but
"track the stuff in frame that is primary focus."

**C was right and pointless at once.** It reserved `branding.md`'s top-third
title zone by pushing the picture down — but with no title built to put in the
zone, it is B with a flat backdrop instead of a blurred one, so it could only
ever measure worse. A treatment that exists to hold a slot for absent content
does not belong in an A/B; it reads as a design when it is a placeholder.

**The option set was the error, not the option.** Three treatments spanned
crop-vs-letterbox and none of them spanned *does a framing decision get made at
all*. The answer sat outside the set, so no amount of picking within it could
reach it — and the previous note's own recommendation ("crop the close-ups,
brand-ground the two-handers") was a compromise between two options that were
both wrong.

**Auto-reframe, built to check.** Face detection per sampled frame, cuts found
first so the decision is per *shot*, detections chained into per-person tracks,
and the framing panned only when the tracked subject actually moves. The
measurements against the shipped centre crop, over all 25 footage placements —
**64 distinct camera shots, 245.6s**:

| What the shot needs | shots | seconds | share |
|---|---|---|---|
| one tracked window | 40 | 152.7 | 62.2% |
| a stacked two-pane split | 14 | 61.0 | 24.8% |
| crowd — one window, rest lost | 2 | 3.4 | 1.4% |
| no detectable face | 8 | 28.5 | 11.6% |

And of the 217.1s that hold a detectable subject, the centre crop leaves a
subject **outside the frame entirely in 59.8%** (129.9s) and clips one at the
edge in a further 23.2%. **The prior estimate of "~10 of 25 shots fail" was too
kind by a wide margin** — it counted clips where the unit is the shot, the same
granularity error one layer down.

**A single 9:16 window cannot hold a two-hander at all, so tracking alone tops
out.** Where the subjects' spread exceeds the window, the frame splits into two
stacked 1080x960 panes, one per cluster; each pane crops 918 source pixels
against the solo window's 459, so both faces survive at 2x the width and the
result still fills the phone. A **crowd is not a wide two-hander**: above three
subjects the split frames nobody, so it reverts to one window on the primary.

Five traps, all of which produce output rather than an error:

1. **`cv2.CascadeClassifier` is gone in OpenCV 5** and `cv2.data.haarcascades`
   points at an empty directory — the training prior is 4.x. YuNet
   (`cv2.FaceDetectorYN`) replaces it and is far better on film footage, but
   its ONNX ships via git-lfs: `raw.githubusercontent.com` returns a **131-byte
   pointer file**, and only `media.githubusercontent.com/media/…` returns the
   model.
2. **The largest face flips between people mid-shot.** An extra passing camera
   outranks the subject for a frame and the crop lurches. Score *tracks*, not
   detections — area summed over persistence — and a background walker lands at
   0.019 of the primary where a real second subject lands at 0.295.
3. **`blend`'s expression evaluator has neither `between()` nor `t`**, so
   switching treatments per shot inside `blend` fails with `Undefined constant`
   pointing at the middle of the call. `overlay`'s `enable=` takes the timeline
   eval, which has both.
4. **`color=` is an infinite source, and overlaying onto it emits the first
   frame before the pane arrives** — a single-frame render comes out flat ink
   at exit 0. Build the frame by `pad`ding the top pane down to full height
   instead; no infinite source, works for stills and video alike.
5. **A lone face can fail a "does everyone fit" span test**, because a span of
   zero plus a 420px face plus margin exceeds the 459px window. One subject
   always fits — the window is placed on it — so the span test needs two.

Nothing here entered lucid: the spike is `autoframe.py` under the job's tmp
dir, and the samples are throwaways. What a build would need is a detector
(subprocess with its own interpreter, the `describe`/`LUCID_VLM` shape — lucid's
venv has no opencv), per-shot framing on the cue, and a stacked render path in
`mlt.py`. Served for the decision at `/vertical-native.html`.

## The hand-framed teaser, watched — 2026-08-10

The tracked-framing spike asked "build it at all?" and the answer arrived as a
counter-example rather than a decision: a 44s vertical teaser, framed by hand,
watched and approved. Fifteen shots, one crop-x number each, one eased move —
no detector, no framing on the cue, no stacked render path. It is ffmpeg
scripts in the job's tmp dir and samples under `~/lucid-final-cut/`; nothing
entered lucid.

The load-bearing part is not the teaser, it is that **a teaser is the only
vertical output that can reach the feed at all** — the film is 5:36 and Shorts
and Reels both cap at 3:00. So the auto-reframe build was justified by a cut
that could not be distributed, and 62%-of-shots-served was answering the wrong
question.

**Captions come back for vertical.** § The vertical cut, refused on a watch
settled them off, and the teaser reopened them on the same day, asked for by
name. The two are not in conflict once the reason is stated: a Short is watched
sound-off. The 16:9 essay still ships clean.

### The tell for an invented word is overlap, never grammar

Burning the transcript over 44 seconds surfaced **nine words Whisper invented**,
all at retake seams. The mechanism is that it transcribes straight *across* a
splice and emits words from both takes interleaved, so the invention **starts
before the word ahead of it ends** — `Stu` 102.72–102.98 against `do`
102.74–103.06.

Eight were removed by eye in one pass and the ninth survived it, because
"Billy and Stu **do** spend the entire film" is a grammatical English sentence
where "Billy **Billions** and Stu" is not. Tyler caught it on a watch. **Reading
for sense finds the nonsense ones and is blind to the rest**; the overlap scan
finds all nine and needs no judgement. It is the same shape as § 2's rule about
durations and a different consequence: there, an inflated duration hides a
retake from an audio mask; here, the seam *adds* a word that gets drawn on
screen.

Nine in 44 seconds of a 5:36 film is a rate. They are in the transcript, not in
any render — so anything downstream of it (an SRT, a platform subtitle track)
carries them, and wants the scan first.

### A mis-framed shot looks like a shot the editor chose

Two of the fifteen crop numbers were wrong and neither was visible in motion —
they read as framing, because there is no reference in the frame to say
otherwise. What surfaced them was a contact sheet: every shot at three moments,
the 9:16 window drawn in red **on the source frame**. 45 images, two bad.

The wrong instinct is worth recording. Having just built the keyframed move for
shot 9, the fix for shot 8 looked like another one — and measuring the mask
centre at seven timestamps said no: it drifts 235px, but the window is 459 wide
and the subject about 130, so a single x holds it end to end. **The window was
not moving too little, it was parked in the wrong place.** Same for shot 3.

If the detector is ever built, the contact sheet is the thing to build beside
it — the detector's output is unreviewable without one.

### Measure the overlay against every shot, not the opening one

The teaser's title header is persistent, so it sits over all fifteen shots. Type
against background measured 14–16:1 on thirteen of them and **4.2:1 on the one
blown-out frame** — under the floor, and the same failure as the 1.10:1
captions over the light cards in § The film had no captions in it. Deepening the
scrim 62% → 75% took it to 5.2:1 and cost nothing elsewhere, because over dark
footage the scrim was already invisible. Sampling the opener would have reported
14:1 and been useless.

## The overlap scan, and what it found in the whole film — 2026-08-10

§ The hand-framed teaser, watched left a rule with nothing enforcing it —
*"overlap-scan anything derived from a transcript before it is drawn"* — on the
strength of nine invented words in 44 seconds. This is the scan, and the first
thing it did was answer whether nine-in-44s was a teaser-sized accident.

It is not. **Run over the whole Scream VO: 56 overlapping pairs in 1150 words,
which group into 40 seams.** Both hand-found cases are in it at the indices the
teaser reported — `Billy Billions and` at 349, `Stu do - spend` at 352.

### It catches what the two sibling checks structurally cannot

`attach_transcript` already returned `near_duplicates` and `suspect_durations`,
so the honest question was whether a third finding is a third *finding*.
Measured rather than argued: **39 of the 56 pairs fall outside every
near-duplicate window.** The reason is mechanical — `find_adjacent_repeats`
matches *phrases*, and a splice that invents one word repeats no phrase for it
to match. `coincidence incidents`, `guy's guys`, `is genu genuinely`, `Scream
screen` are invisible to it. `suspect_durations` is blind for a different
reason: a seam's words are ordinary-length, they are merely in two places at
once.

### Seams, not pairs — and no threshold

One splice overlaps several words in a row, so the raw pair list reports one
event five times: 350, 351, 353, 354, 355 are all `Billy Billions and Stu do -
spend`. Grouping consecutive pairs into a seam is the same collapse
`find_adjacent_repeats` already does to its candidates, and it takes 56 down to
40.

**The threshold was the real design question, and the answer was not to have
one.** Whisper quantises its timestamps — every distinct step in the VO is a
multiple of 0.02s — so two ordinary consecutive words can overlap by exactly
one quantum through rounding alone. Eight of the 56 sit at exactly 0.02. The
tempting move is a floor, and it is wrong twice: it is lucid deciding, on a
finding whose whole value is that it needs no judgement, and it would discard
a real seam it happened to mis-size. Grouping makes the noise self-identifying
instead — a one-pair seam whose `worst` *is* one quantum — so `pairs` and
`worst` ride along and whoever reads the result decides. Three of the 40 are
that shape.

Of the eight at one quantum, four (`- spend`, `3 out`, `of 10.`, `and...
while`) sit immediately beside a seam with real overlap, so a floor would also
have been trimming the edges off events it kept.

### The finding had nowhere to be asked for

The three checks are computed at attach and handed back in that call's result,
which means a project attached before a check existed can never see it. That is
not hypothetical — it is exactly where the Scream VO stood, and re-attaching to
surface a finding means re-running ASR or hunting down the original whisper
JSON. So `transcript_checks` (op, CLI `transcript-checks`, MCP tool) re-runs all
three over what is already on disk, reads only, and is how the 40 above were
counted.

The detector is `transcript.find_overlaps`, and it went there rather than
beside its siblings because both of their homes refuse it by their own
docstrings: `energy.py` is the audio envelope, "the one arbiter a transcript
cannot outvote", and this needs no audio; `verify.py` is "pure sequence work…
over *word order*, not timings", and this is nothing but timings. What it
actually asserts is that the index is self-consistent, which is `transcript.py`'s
subject.

Two details worth keeping. A seam's `end` is the widest end in its range, not
its last word's — an invented word routinely ends *before* the word it follows,
and that inversion is the finding, so the extent cannot be read off the final
member. And the comparison carries an epsilon: two words sharing a boundary come
back from JSON and a subtraction as 0.9 against 0.8999999999999999, which is
arithmetic rather than a splice. A zero-width word (`start == end`, which
whisper emits often) landing exactly on the previous word's end is correctly
silent for the same reason, and one landing before it is correctly a seam.

## `lucid reel`, the project-derivation op — 2026-08-10

PLAN.md § Three uncosted parity items costed reel selection and found there was
nothing to build for the *choosing*: `cut_by_time` already takes spans in the
seconds an export plays at, converts them through `Edit.source_spans` and cuts
through the same `Edit.remove` path everything else uses. What was missing sat
one level up — **the canvas is project state and the cuts are destructive, so
the copy is mandatory, and it was a `cp -a` done by hand.** That is this op:
copy, two cuts, canvas, re-author cards, one command.

The reason deriving is the safe shape rather than a convenience is the failure
`tiktok-reels` already refuses one level down. Setting a vertical canvas on the
film to take one render leaves the film swapped afterwards, and nothing reports
it. A reel names what to **keep**, which is the only thing in lucid that reads
that way round; the head and the tail are what get cut.

Media is linked, never copied — a reel of a five-minute film would duplicate
every gigabyte that went into making one. The `media/` entry and the
`cache/attenuated/` entry both, and the second is the one that matters:
`media_path()` prefers `attenuated`, which is what makes attenuation
transparent downstream, so carrying `media/` alone would give the reel a render
at full noise with nothing in the manifest saying so.

### Both real bugs were invisible to the tests and to reasoning

Twenty-one tests passed, including one asserting the film is left byte-identical
and one asserting the reel resolves the film's own bytes. Deriving a 44s reel of
the actual 5:36 Scream cut found two things neither the suite nor the design
note saw, and the second made the artifact unusable.

**The suspect-duration guard was firing on everything being removed.**
`cut_by_time` flags every suspect word a removed span *overlaps*, which is right
for an ordinary cut — the span and its boundary are nearly the same thing — and
useless for a reel, which removes most of the film. The first real run flagged
**fifteen, none within a hundred seconds of either edge**, so `--confirm-suspect`
would have been mandatory on every reel of every film, which is a guard that
guards nothing. The edges that can actually hide a retake are the two the reel
*keeps*: an inflated duration there means the reel opens or closes on material
from the wrong take. `_reel_suspect_edges` asks that question instead, and the
same film goes 15 → 0 while the guard still fires on a planted edge case.

**The cue table orphaned, and `build_shots` refuses a whole projection on one
orphan.** A cue is word-indexed, so a cut cannot *invalidate* one — that much
was reasoned correctly and is why the design note said cues survive by
construction. What a cut can do is take the word away, and a reel takes 87% of
them: 34 of the film's 38 cues pointed at words the reel no longer had. The
derived project opened, read as a film, passed `status`, and `shots` refused
with `cue at 'vo' word 18 ('The') was cut from the edit`. **It was correct in
every check and unrenderable.** So the derived cue table is the surviving cues,
and `cues_dropped` names the rest — one entry per picture the reel will not
have, because dropping them quietly is dropping pictures quietly.

Both are the same lesson in different clothes, and it is the standing one:
neither was reachable by inspection, and both took one run against real data.

### It renders

The 44s reel at 1080x1920 through `melt`: 1056 frames against the timeline's
1056, `check_frames` `agrees: true` with `delta: 0`, `check_black` `clean:
true`. The reel directory is 1.3 MB — its manifest, its transcripts and the
twelve card PNGs — against a film whose footage it shares by symlink.

The frames are also **mis-framed exactly as § The vertical cut, made native
measured**: the centre crop puts a head half out of frame. That is not this op's
problem and it is worth stating plainly, because it is the whole argument for
what comes next — a reel is a *derivation*, and per-shot framing is a separate
address space that does not exist yet. Read the other way: the derivation makes
the framing question the only one left, which is what a control is for.

### Two smaller things

**`cards_unrecorded` came back twelve long, as CLAUDE.md says it would.** The
reel is correct in every other respect while its cards are still 16:9. Nothing
here changes that; it is reported at the moment it starts mattering.

**`dest` is the first second project-selector in the tool surface**, and an
unconfined one would let an agent panel bound to one project write a whole
project anywhere on disk — `path` being confined is no help, because the escape
is on the way out. `_tool()` now takes the selector names (`@_tool("path",
"dest")`), defaulting to `("path",)` so every other registration is unchanged.
Named at the registration site rather than checked in the body, for the reason
the decorator exists at all.

## Per-shot framing — the window is a source address — 2026-08-10

Built as costed: PLAN.md § Per-shot framing, steps 1–4 (store, writer, contact
sheet, preview). The item the vertical line was waiting on — `tiktok-reels`
renders, and the centre crop it renders with was refused on a watch — so the
whole aspect-swap rung has been sitting on an address space that did not exist.
It exists now: **`(clip_id, src_start, rect)` in source seconds**, the same
shape a footage description uses, for the same reason.

The design note's three findings all held on the build, which is worth saying
because the note is the one that moved the answer *off* the two obvious places
(the cue, and a new render node) before any code was written.

### What shipped

- **The store.** A `reframe` record grows an optional `src_start`. Absent means
  the window from the head of the file, which is what every rect on disk
  already meant, so nothing migrates and there is **no schema bump** — and the
  head record is written back byte-for-byte as it was, so an unwindowed
  project's manifest is untouched by any of this. One entry per
  `(clip_id, src_start)`.
- **The op.** `reframe --at SECONDS` sets a window, `--reset --at` drops one,
  `--reset` on a clip drops the series. A window past the clip's own duration
  is refused rather than stored: it would never come into force and would read
  in the manifest as framing that had been dealt with. Every window is still a
  *floor* — grown to the canvas's aspect, never shrunk.
- **The writer.** `Reframe` widened from one rect to a head rect plus a series,
  and `rect_property` writes MLT's animation when there is more than one:
  discrete (`|=`, a framing window steps at a camera cut, it does not slide),
  numbered in the producer's **source** frames. One window still writes the
  bare string it always wrote.
- **The contact sheet.** `reframe_sheet` (CLI `lucid reframe-sheet`), a build
  of `~/lucid-final-cut/audit.py`: every placement at three moments, the window
  in force drawn on the source frame in red and labelled with its rect, tiled
  into one montage. Rows are *placements*, not clips — a clip used seven times
  is seven rows — and stills come back under `skipped`, since a card is
  authored at the canvas and never cropped.
- **The preview.** Each shot in `timeline_view` carries its own `dest`, and
  `player.js`'s picture layer places from that rather than from
  `reframe[clip].dest`. The per-clip entry is the *head* window, which is the
  edit track's answer and only accidentally the picture lane's.

### It renders, and the clock is the source's

The failure this guards produces a file and exit 0, so it was settled on
pixels, end to end through a real `melt` render rather than the isolated probe
the note used (`~/lucid-pershot-check/check.py`). The edit is **cut** on
purpose — it keeps source [5s, 20s), so source time and timeline time differ by
five seconds throughout — and a window stored at source 14s has to appear at
output 9s. A timeline clock would put it at 14s; a rect applied per resource
rather than per window would never move at all.

| output | source | window | rmse | against |
|---|---|---|---|---|
| 0.50s | 5.50s | x=0 | 592.58 | 17710.60 for x=1461 |
| 8.50s | 13.50s | x=0 | 471.17 | 9769.85 for x=1461 |
| 9.50s | 14.50s | x=1461 | 1058.61 | 10419.40 for x=0 |
| 14.50s | 19.50s | x=1461 | 749.65 | 11122.50 for x=0 |

Scored against ffmpeg's own crop of the source at the source timestamp the
document claims, and against the wrong window too — an order of magnitude
apart, so it is an answer rather than a number.

**And the node count did not move.** One `qtblend` filter per node per role,
carrying every window for that file, which is what keeps the `reframed_nodes`
readback — the check that catches a reframe cropping one track and letterboxing
the other — meaning exactly what it meant before.

### The preview was checked on the served page, not reasoned about

Seven placements of `cold-open` in the real film, from **two stored numbers**:
the placement at source 0.0s draws at `dest` x=0 and the six from 20.4s onward
at x=-3438. Then the page itself, driven over CDP (geometry, not a capture —
what changed is which rect the element is put at, so `getBoundingClientRect` is
the right instrument and the `<video>`-capture trap does not apply): clicking
the two shots put `#picture-video` at x=0 and x=-1212.8 of a 1593.8px frame,
each matching its own shot's `dest` scaled by `frame.clientWidth`. Reading the
clip entry — the old path — would have put both at the first.

The one measurement that disagreed with itself first time was mine: scaling by
`getBoundingClientRect().width` instead of `clientWidth` moved the expectation
1.6px and read as a mismatch. The code scales by `clientWidth`; measure with
what the thing under test uses.

### What the sheet said the moment it existed

Run on the film with two hand-picked windows on `cold-open`, it answers the
question it was built for immediately and in the wrong direction: **both
windows are wrong**, and obviously so — the subject is centred and both rects
sit at an edge. In motion neither would have looked like anything but framing.
That is the 2-of-15 finding reproduced on the first run of the tool built to
catch it, and it is the argument for the sheet being a build item beside the
framing rather than after it.

**Twenty-five rows, thirteen skipped.** The skipped are the cards, and the 25
are what a framing pass has to decide — against 38 cues. The design note's
finding 1 said the film needs more windows than it has placements at every
scene threshold measured; the sheet is where that stops being a table and
becomes work.

### Not built, and why

The detector stays step 5 and stays after this, unchanged: it is judged against
the 15 hand numbers, which is a control that already passed a watch. Keyframed
*moves* remain refused — the mechanism is paid for by the writer now, but the
authoring waits for evidence, and the evidence so far is one eased move in
fifteen shots with a 2-in-15 false-positive rate against it.

One limitation worth stating rather than discovering: **the preview places a
shot by the window at its `src_start`**, so a window boundary *inside* a
placement previews as the first of the two. The render steps mid-shot correctly
— that is what the keyframes are — and `reframe_sheet`'s `windows` count is how
a placement that crosses one announces itself.

## The framing control, ported off the render and into the source — 2026-08-10

PLAN.md § Per-shot framing, step 5 gates the detector on *"whether it beats the
15 hand numbers, which is the control that already exists and was watched and
approved"*, and § Three uncosted parity items' standing rule is that the dumb
control is **built as a test** rather than remembered. Neither was true yet:
the numbers were a `CROP` dict in `~/lucid-final-cut/render.py`, addressed in
*timeline* seconds against a scratch render, which is precisely the address
space per-shot framing exists to replace. This is the port, and it is now
`tests/test_framing_control.py`.

### The two address spaces were joined by measurement, not by arithmetic

The obvious move — assume the teaser is the reel `lucid reel` already derives —
is wrong, and the check that caught it was cheap. A 2fps grayscale fingerprint
of the approved render against the film's own render put **81 of 88 frames at
+96.0s**; two of the hand shot boundaries then land on the film's own placement
boundaries at 95.930 and 95.929, which pins the offset to a third of a frame.
The approved teaser is film **[95.93, 139.85]**.

**Each ported window was then checked on pixels**, because a wrong offset
produces a plausible file: the source frame cropped at the ported window
against the approved render's own frame, scored also against a deliberately
wrong x. All 16 reproduce — RMSE 0.8–1.2 on the 816-tall clips against 29–68
for the wrong window.

**Sixteen, for fifteen shots.** Shot 9 is the one hand-eased move and the
series is discrete by design, so the ramp is carried as one step at its middle.

### The reel is not the film's picture, and unpinned cues are why

The finding that made the port a port rather than a copy. `~/lucid-reel/teaser`
keeps film [92, 136] — a 4s overlap short of the approved teaser's span — but
the deeper difference is that **its picture is not the film's picture over the
same seconds.** A reel drops the cues whose words it cut (34 of 38), and
`plan_picture`'s per-asset cursor therefore starts fresh: every surviving cue is
unpinned, so each asset replays from its own head. Aligned against the film the
reel reads +95.5 for its first 20s and +92 after — the tell that picture and
narration have slid apart by the 3.5s the cursor did not consume.

CLAUDE.md already says a pin is what separates a re-use from a placement. What
this adds is that **a derivation is where that bites hardest**, because
derivation is exactly the operation that empties the cursor. Pinning the four
cues to the film's own in-points reproduces the film's picture exactly, and that
is what the verification render was built on.

### It renders, and it is the approved framing

`lucid export --render --preset tiktok-reels` over the pinned derivation: 1067
frames against the timeline's 1067, `agrees: true`, all three control clips in
`reframed`. Sampled one frame per hand shot, 30% in, and scored against both
the approved render and the centre crop — **14 of 14 shots are closer to the
approved framing**, most at RMSE 1.4–2.2 against 18–81 for the centre crop.

Two properties showed up unasked, both of them the design note's own claims
arriving on real data rather than in a test:

- **Three placements outside the teaser were framed for free.** The same three
  clips are re-used later in the film, and each picked up the window covering
  the source range it reads. They are extrapolations rather than approved
  decisions, and the contact sheet is where they get judged.
- **The framing survived the derivation intact** — all 16 windows carried into
  a reel that dropped 34 of 38 cues. Source-addressed state is the half of a
  project a cut cannot reach, which is the whole argument for the address.

### Shot 9 puts a number on the refused mechanism

The one place the port is an approximation, measured across the move rather
than asserted: the discrete step holds correctly at both ends (RMSE 3.6–9.5)
and **for about 0.75s of the 1.3s ramp it is no better than the centre crop** —
47.3 against 47.3 at the midpoint, and at one sample the crop is nearer.

That is the evidence PLAN.md § Per-shot framing said the *authoring* of
keyframed moves was waiting for, and it is deliberately not treated as
settling it: one shot in fifteen, under a second of it, against a 2-in-15
false-positive rate for wanting a move at all. The mechanism is cheap — MLT's
default `=` interpolates and the writer already emits keyframes, so what is
missing is a way to say a window slides. **The call is Tyler's and it does not
block the framing pass.**

### What is left is the framing

**18 of the film's 25 footage placements are still on the centre crop.** The
control covers 4 and lends its numbers to 3 more; the rest is choosing windows
and reviewing them on `reframe_sheet`, which is work rather than a build.

## The auto-framing detector, built — 2026-08-11

PLAN.md § The auto-framing detector costed this the day before and § Per-shot
framing, step 5 gated it on one thing: beat the fifteen hand numbers. This is
the build. `faces.py` and `_face_worker.py` (the detector, behind an
interpreter), `media.scene_cuts` (the boundaries), `ops.reframe_detect` (the
pass), a CLI subcommand and an MCP tool, and two test files. All five of the
note's build items landed as written, which is not the interesting part — the
interesting part is the two numbers that moved.

### The gate is scored at the sampling that ships, and it is not 0.755

The design note's 0.755 / 111.6 came off the costing probe, which sampled every
0.5s up to sixteen frames a window. `reframe_detect` samples **three**, through
`describe.frame_times`, for that module's own reason: a window boundary is where
a cut is most likely to be, so the samples sit off both edges. Rescoring the
shipped rule on three frames:

| | overlap | displacement | lost | worst |
|---|---|---|---|---|
| centre crop — the bar | 0.568 | 199.4 | **1** | 0.000 |
| luma centroid, 3 frames | 0.545 | 207.6 | **1** | 0.000 |
| faces, 16 frames (the costing) | 0.755 | 111.6 | 0 | 0.480 |
| **faces, 3 frames (what ships)** | **0.750** | **114.0** | **0** | **0.480** |

Five thousandths and 2.4px. **The sampling is not a lever either** — which is
the same shape as finding 2's result about the aggregation rule, arriving in a
second place: the signal is doing all the work. The luma centroid was
re-measured on the same three frames so the comparison is the signal rather than
the density, and it is *still* below the centre crop, and at this density it
loses a subject too. There is no column on which it is the better answer.

The gate is `tests/test_framing_control.py`, extended, and it scores
`faces.window_centre` and `faces.window_x` themselves rather than a
re-derivation — a test that re-implements the rule it checks passes whatever the
code does. The detections are checked in at `tests/data/framing_detections.json`
so the gate runs with no insightface, no ONNX session and no footage.

**A refusal is scored as the centre crop**, because that is what the film gets
there: the pass declines and the default stands. Scoring it as a miss would
flatter the rule; scoring it as a hit would invent one.

### The film found the bug the tests could not

The one thing the note did not anticipate. Run against `~/lucid-vertical/proj`,
the pass reported **fifteen of the sixteen hand-approved windows as unframed**,
which would have made `--apply` write a duplicate beside each one.

ffmpeg reports the cut at **0.834167**. The manifest holds **0.8342** — the
control was ported by hand through a timeline offset, the scan reads raw
presentation times, and the two disagree by 33 microseconds about the same cut.
Three more windows disagreed by 0.7ms. An exact-match test (`< 1e-6`) called all
of them different windows, and *the display rounded both to four places*, so the
plan printed `0.8342` beside `0.8342` and labelled it `centre`.

The fix is that **two boundaries inside one source frame are one window**. Not a
tolerance for slop: it is the resolution the render has, since a reframe is
emitted as keyframes numbered in the producer's own source frames (CLAUDE.md
§ The MLT reframe). `same_window_within` is reported rather than assumed,
because it is the number deciding whether `apply` leaves a hand-framed shot
alone.

With the frame in place, **14 of 16 are recognised**, and the two that are not
are exactly the two the costing predicted: `s1996-billy-stu` 0.5012, where the
human began the window twelve frames into a placement with no visual event at
all, and `s4-reveal` 7.3428, the midpoint of the eased move, where by
construction there is no cut. Neither is a miss — both are addresses no detector
was ever going to find.

Worth naming as a pattern: **the stubs could not have caught this**, because a
stub agrees with whatever address the code asks for. What caught it was running
the pass against a project whose windows came from somewhere else.

### What it produces on the film

59 windows against 25 placements — **2.4×**, against the costing's forecast of
1.9× over the 18 unframed placements, and § Per-shot framing's threshold-robust
claim that the film needs more windows than it has placements holds on real data
at a third measurement. 34 of the 59 boundaries are camera cuts and 25 are
placement heads, which the edit supplies for free.

**A face is found in 51 of 59 (86%)**, better than the forecast's 80%. The other
eight come back refused and named — `cold-open` [0, 6.631] and [52.260, 65.815],
`s1996-randy` [0.834, 1.960] (the CRT, the case finding 4 looked at), `s3-reveal`
[0, 2.211] and [16.058, 18.060], `s4-reveal` [18.727, 21.730]. None of them is
centre-cropped quietly; each says so.

Applied to a copy, 39 windows were written and **all 16 hand windows survive
byte-identical** — the other 12 proposals landed on windows already framed and
were declined with a reason, which is the rule that `apply` never writes over
someone's decision. The project reads back with no `reframe` errors on any of
its nine clips.

### On the sheet, the two-hander is the visible failure

`~/lucid-framing-detect/sheet-detected.png`, 25 rows. Spot-checking the tiles
rather than the table, because that is the whole point of the sheet:

`cold-open` @36.77s frames Casey on the phone correctly — the window lands on
her, and the half of frame it drops is a dark doorway. `s4-overexposed` @1.75s
is the interesting one. Two women in a car, driver left and passenger right, and
the area-weighted rule lands **between** them at 1068 — far enough right to be
obviously the passenger's shot, and close enough to the middle that it **clips
the right side of her head**. That is finding 3's ceiling arriving as a picture:
every face is a true positive, only one of them is the shot, and no property of
the boxes says which. An oracle picking the passenger alone would frame it.

The refused windows draw the centre crop, as they should: `cold-open`'s head
window is labelled 730, which is exactly `(1920-459)//2`, and the *next* window
along is 732. Nothing about the refusal is hidden in the picture — it just looks
like the default, which is why it has to be named in the output.

### And a second wrong claim, caught by building the review page

Reviewing is where the *last* mistake surfaced, which is the whole argument for
`reframe_sheet` existing. The refusal message read *"this window is unframed,
not centre-cropped"*, and that is false. **Nothing is written for a refused
window, so whatever window is already in force simply carries over.** At the
head of a clip that is the centre crop. Everywhere else it is the previous
shot's framing:

| refused window | what actually renders there |
|---|---|
| `cold-open` [0, 6.631] | the centre crop |
| `cold-open` [52.260, 65.815] — three windows | **the window from 44.461s** |
| `s1996-randy` [0.834, 1.960] | the hand override already at that in-point |
| `s3-reveal` [0, 2.211] | the centre crop |
| `s3-reveal` [16.058, 18.060] | **the window from 9.051s** |
| `s4-reveal` [18.727, 21.730] | the hand override already at that in-point |

**Four of the eight inherit a different shot's window**, and that is worse than
the centre crop rather than equal to it: a default reads as a default, while a
stale window reads as a decision. Exactly the failure this item exists to
prevent, arriving through the one path nobody was watching.

So `falls_back_to` names what will actually cover each refusal, resolved as if
the proposals were applied — which is the question a plan is read to answer. The
message no longer claims anything about the centre crop, and the test that
asserted the old wording was corrected with the code and gained an assertion
rather than losing one.

Both bugs in this build have the same shape, worth naming: **a stub agrees with
whatever the code asks it for.** The frame-tolerance bug needed a project whose
windows were addressed by someone else; this one needed the pictures drawn and
looked at. Neither was reachable from the test suite that covers them now.

### Refused, unchanged

Everything the design note refused stays refused: no look-room rule fitted to
sixteen samples, no second signal for the screen-within-a-frame, no auto-apply,
and keyframed moves still a call for Tyler. `apply` being off by default is the
opposite of `cut --plan` and deliberately so — the pass is 114px out on a 459px
window, and 2 of the 15 hand numbers were wrong in a way no watch showed.

## The stacked split, built — 2026-08-11

PLAN.md § The stacked split has the mechanism and the numbers. This is what
went in, and the two things the build found that the probes had not.

Shipped: `mlt.Reframe.panes` and `mlt.pane_boxes`, a second node per split lane
in `mlt.document`, `pane` on a stored reframe record, `reframe --pane`,
`reframe_detect`'s split proposal behind `faces.split_centres`, both rects on
`reframe_sheet`'s tiles, and both halves in `timeline_view` and the preview.
Review page: `~/lucid-split-review/`, served on 8797.

### The number was a quarter of the one about to be inherited

The spike's 24.8%-of-shot-seconds came from a different pass on differently
found shots. Re-measured over the 59 windows `reframe_detect` actually proposes
— same footage, same sampled timestamps, boxes kept — a split fires on **4
windows, 15.1s, 6.2%** of the picture-seconds. The full table is in PLAN.md;
what matters here is that the rule moves the answer by 2.4x within the same
data, from 14.8% (median frame) to 6.3% (every frame), so *"how often does this
fire"* has no answer until the rule is fixed.

It also found that **`reframe_detect`'s `faces` field cannot be read as a
subject count** and was about to be: it sums detections over the three sampled
frames, so one face reads as 3 and `s1996-randy`'s 33 is eleven people watching
a television. `subjects` — the per-frame median — is now reported beside it.

### The pane's aspect is not enough; it needs the full source height

Found by a test rather than by reasoning, and it would have rendered rather
than raised. `_fit_rect_to_canvas` grows a rect to the target *aspect*, so
fitting a pane against a 1080x960 box turned a `400,300,200,200` ask into
`225x200` — correctly 9:8, and a 4.8x zoom. Nothing masks a pane: `_dest`
places the **whole** source frame so the rect fills the pane and the profile
clips it, so a crop that is a fraction of the source's height scales the frame
up until it overruns its own pane and draws into the other one. Two halves
bleeding into each other, at exit 0.

`_fit_pane_rect` forces the full source height and derives the width from it,
which makes the scaled frame exactly one pane tall for any source shape — the
disjointness PLAN.md § finding 2 claims, now enforced where it is claimed. The
ask moves the window sideways and nothing else, which is what a framing
decision is here. A source too tall to carry a pane refuses at the keyboard,
and a canvas swap that makes an existing split impossible is *reported* rather
than raised, for the reason every other outgrown rect is.

### `-strokedasharray` is ImageMagick 6's spelling

The sheet draws the lower pane dashed. `magick` rejects the option outright —
the dash array is an MVG primitive inside `-draw`. Noted only because it is the
rare graphics failure in this repo that is loud.

### Verified by two renders, not by the suite

melt cannot see the `/tmp` a `tmp_path` hands out, so the evidence is here.
Both documents came out of `mlt.document` itself, not hand-written like the
probes':

- **Geometry.** The car scene at the canvas, diffed against ffmpeg's own
  two-pane composite of the same source frame: mean |diff| **1.59**, max 19 —
  against **66.55** for the solo centre crop it replaces. The seam rows either
  side of the join are 1.48, so the panes do not bleed.
- **The off switch.** One clip with three windows, solo → split → solo, on the
  picture lane (so the `pvchain` node and the blank-padded overlay playlist are
  what is under test). Each of the three matches its own reference — 1.81,
  1.14, 2.12 — and the two solo frames are **61 and 70** away from what a pane
  left switched on would have drawn. That is the failure the keyframe at every
  window boundary exists to close: a step that is not written is a value that
  carries on, and melt exits 0.

The detector then found the car scene unprompted and proposed `323` and `1006`
where the hand-built probe had used `322` and `1006`.

### What it is still waiting on

Tyler's judgement on the four, which is what the review page is for. The
three-face window at `s4-overexposed` 7.632s is the doubtful one: with three
faces the panes are two *groups* rather than two people, and they overlap
enough that both draw much the same wide view. Legal, correct, and probably
worse than one window — but that is a watch, not a rule, which is the same
place § Choosing the b-roll ended up.

## The preview proxy — 2026-08-11

PLAN.md § The preview proxy transcode has the design and the corrections. This
is what shipped, and the two things measuring found that the note had reasoned
its way past.

Shipped: `project.PROXY_DIR`/`proxy_path`/`proxy_key_path`, `media.make_proxy`,
`media.preview_path` and `media.proxy_is_current`, `ops.proxy_transcode`,
`webui.ProxyJob` behind `POST /api/proxy`, `lucid proxy`, and a
`proxy_transcode` MCP tool. The tier-3 workspace's last open piece.

### The eviction rule dissolved, because its premise was assumed

The note asked for an eviction policy on the grounds that *"a proxy is a
full-resolution H.264 re-encode, so a project with many unplayable clips grows
`cache/proxy/` without bound."* Both halves of that are a decision wearing a
premise's clothes: a proxy plays in a `<video>` in a window, and nothing said
it had to be full resolution.

Measured on `~/lucid-vertical/vertical.mp4` — real film footage, 1080x1920 at
5.28 Mbps — one minute costs **24.2 MB at full resolution and 3.2 MB at 720
tall**, 7.6x, and encodes 2.9x faster. The film's whole 1324s of footage is
then ~70 MB rather than ~530 MB, which is under what `cache/frames/` already
holds, and one-entry-per-clip is the *existing* cache convention rather than
new ground. There is no eviction rule and nothing to hand-clean.

The check that made the downscale safe rather than merely cheap is a negative
one: `player.js`'s `place()` positions by `timeline_view`'s `dest` rect in
canvas coordinates with `objectFit: fill` and **never reads
`videoWidth`/`videoHeight`**, so a uniform downscale draws in exactly the same
place. Had it read intrinsic size, the whole lever would have been unavailable
and the eviction rule would have been real.

**The size ratio is a fact about real footage and not about any fixture.** In
the live run the 4s `testsrc` proxy came out *larger* than its hevc source —
112,748 against 95,699 bytes — because libx265 compresses a test pattern
pathologically well. Nothing asserts a size reduction anywhere in the suite,
deliberately: a test that did would be pinning ffmpeg's opinion of a colour
bar.

### `media_path()` changed by zero lines, and that is the whole design

The rule the note set is that the proxy never enters the manifest and
`media_path()` gains no branch, so `export`, `verify` and `check_frames`
cannot reach a proxy *because they never call the function that resolves one*
— not because a resolution order was written carefully. It held: `preview_path`
is a second function with two callers (`ops.preview_source`,
`webui._send_media`), and `media_path` is untouched.

The load-bearing test is not the transcode. `test_export_never_names_the_proxy`
builds a proxy, exports, and reads the handoff for the path it referenced,
because every other test in the file would still pass if the proxy leaked into
the render path. `attenuate_noises` had the mirror-image bug pointing the other
way (§ `attenuate_noises`), and a leak in this direction is worse: silently
delivering a downscaled preview encode as the finished film.

### Verified live, because a passing suite has missed this class before

The suite stubs `ops.proxy_transcode` for the HTTP routing tests, so the real
service was driven end to end: a 1920x1080 `hev1`/`ac3` clip — two refusal
classes at once — imported into a scratch project under `lucid web`.
`/api/preview/scene` reported `playable: false` and named the codec;
`POST /api/proxy` returned 202; the SSE stream carried `running` then `done`
with `playable: true`; `/api/preview/scene` then resolved to
`cache/proxy/scene.mp4` and `/api/media/scene` streamed its 112,748 bytes. A
`lucid export` taken afterwards named `media/scene.mp4` and nothing under
`cache/proxy`, and the manifest clip carried no `proxy` key. A second POST
while one ran returned 409.

### Two refusals, and only one of them is about codecs

`playability()` refuses in four classes and a transcode closes three. The
fourth — no decodable streams — is a broken file, and it stays a refusal rather
than becoming a failed job. The other refusal is the one worth writing down
because it is a judgement rather than a limit: **a clip that already plays is
refused**, since a proxy of a file the browser opens directly is a second,
lower-quality copy of footage nothing needed a copy of. `force` overrides the
cache, not that.

## Variant resolution — the vertical card layout, step 1 — 2026-08-11

PLAN.md § The vertical card layout — the design note has the four findings and
the build order. This is step 1: `fill_template` picks *which file* it fills
from the canvas, and the geometry that goes with it. No variant files yet — the
step exists so the mechanism is under the twelve recorded cards before any of
them move.

Shipped: `graphics.VARIANTS`, `graphics.BASE_GEOMETRY`, `graphics.template_layout`,
`graphics._declared_slots`, a `variant` argument on `template_path` and
`template_slots`, and an optional `variants` key on a `TEMPLATES` entry.
`_flow_box` and `_check_fits` take the resolved geometry instead of a
hard-coded 110.

### The gate was byte-identity, measured against the code it replaced

A step whose whole claim is "nothing changes yet" is worth exactly the check
behind it. Every one of the twelve real slot tables in `~/lucid-vertical/proj`
plus each shipped template filled with placeholder values, at four canvases —
1920x1080, 1920x816, 1080x1920, 1080x1080 — hashed, then `git stash` and hashed
again on the pre-change tree. **60 pairs, all identical.** The two that refuse
(`receipt-scream-1996`, `receipt-scream4-2011` at 16:9, the pair the wiki's
Open items row names) refuse with the same text, so the identity is not the
vacuous kind where everything errored.

That compare is a one-off and does not survive as a test; what survives is the
property it proved. `test_a_template_with_no_variant_draws_its_own_file_at_every_canvas`
asserts, per template per canvas, that the resolved layout is the base file,
`BASE_GEOMETRY`, and the base slot table — which is the invariant that would
have to break for a later step to redraw a card it only meant to add a branch
beside.

### A variant is a file chosen from the canvas, never a second template name

This is the one design decision in the step, and it is forced by the card
record rather than by taste. `card_new` records `(template, slots, canvas)` and
`card_reauthor` fills that template again at the project's canvas — the
record's entire job is to survive an aspect swap. Had portrait been a template
name, re-authoring after a swap would have to rewrite the recorded template,
and the record would stop saying what the card *is*. Resolved from the shape of
the frame instead, every record already on disk keeps meaning what it meant,
and `card_new`/`card_reauthor`/`ops` needed no change at all.

The grid stays 1920 units wide across variants. x-coordinates, margins and body
widths keep one language, `render_svg` learns nothing, and the portrait file is
the same coordinate system with a 3413u-tall viewBox it actually uses.

### Both directions of the declaration are guards

A *declared* variant with no file refuses rather than falling back to the base.
Falling back is the tempting build and it draws the landscape card into the
tall frame — the pillarboxed card the whole item exists to remove — at exit 0.

The mirror is the one worth writing down: a variant **file** the manifest does
not declare is also refused. Without it, authoring `receipt.portrait.svg` and
forgetting the declaration leaves every portrait canvas quietly filling the
landscape file, with a correct-looking file sitting right beside it. That is
the same shape as the drift guard `template_slots` already runs between a
manifest and its placeholders, pointed the other way, and step 3 is exactly the
step that would have hit it.

### The geometry table is per-variant because finding 3 arrives twice

`TEMPLATES[name]["slots"][slot]` carries `x`/`y`/`width`/`size`/`line_height`/
`footer_slot` for the wrap measurement, and those numbers are the landscape
file's. A portrait file measured against landscape declarations wraps to a box
the card has not got and overruns it at `magick` exit 0 — which is finding 3's
silent-overflow failure reached by a second route, without anyone setting a
bigger title. So `_declared_slots` is one merge shared by the drift guard and
the fill; a variant that declared its geometry to one and not the other is the
bug the shared helper exists to make impossible.

The derived numbers move with it. `mid_y`, `note_y` and `foot_y` come from
`BASE_GEOMETRY` (`mid_ratio` 0.44, `note_gap` 130, `foot_margin` 110 — the
landscape file's), overridable per variant, and `_flow_box` reads the same
`foot_margin` rather than its own literal. Finding 4 is why: at 1080x1920,
`view_height - 110` puts the wordmark 62px from the bottom edge, inside the
band `goodsometimes/branding.md`'s Shorts row reserves for platform UI.

## The measured line — the vertical card layout, step 2 — 2026-08-11

`title` and `note` fit-checked, refusing rather than overrunning. The step
closes a hole that was live at exit 0 and it is prerequisite rather than
preparation: the portrait variant wants a bigger title, and a bigger title in
an unmeasured slot is the failure `flow=True` was built to prevent, shipped a
second time.

It went wider than the two slots the note named. `date_line`, `year` and
`mark` are the same kind of plain substitution with the same silent failure,
and once the mechanism exists the marginal cost of each is a table entry. So
the rule is the class rather than the instances: **a placed text slot declares
`kind: "line"` and is measured, or it is named in another slot's `parts` and
measured as part of that line.** There is no third state, and a test holds
every shipped template to it — dropping `year` from `receipt`'s title parts
fails with `receipt.year is a placed text slot that nothing measures`.

### The box belongs to the `<text>` element, and finding 3's numbers were the slot's

The unit that overruns is not the slot. `receipt` draws the year inside the
title's own element, smaller and after a 36-unit `dx`; `reveal` gives its title
a raised asterisk and its note a leading one. A title measured by itself is
measured against a box something else is already standing in.

Measured, the companion is not a rounding error. The year is a flat **229
units** of a 1640-unit box — 14% of it, gap included — and the reveal
asterisk is ~183. So the design note's own table, which measured the title
alone, understates every row:

| reveal title | as the note measured it | as the line is drawn |
|---|---|---|
| `Scream VI` at 196u | 861 | **1052** |
| `Scream 2022` at 196u | 1096 | **1279** |
| `Scream 2022` at 300u | 1677 | **1957** |

The overflow finding 3 costed at 37 units past the box is **317**. Nothing
about the conclusion changes — it was already "the title has to become
measured first" — but the margin the portrait variant has to spend is smaller
than the note thought, and it is smaller in the direction that fails silently.

`measure_line` therefore draws the whole element on the scratch canvas, `dx`
included, rather than measuring pieces and adding them: the same **rendered,
not summed** rule `measure_runs` records, applied to a line whose pieces are
different sizes. `_measure` is the shared growth-and-clipping loop under both,
because a clipped measurement is narrow, and narrow means a wrap that ends
early *and* a fit check that passes the one value that does not fit.

### The hole, watched rather than reasoned about

`reveal` at 1920x1080 with `The Texas Chain Saw Massacre`, filled the way it
filled yesterday: `magick` exits 0 and the render's ink measures **1920x653 at
x=0** — the full width of the frame, both 140-unit margins gone, letters cut
off at each end. The same fill now refuses at 3100 units against a 1640 box,
and writes nothing: `lucid card new` names the numbers and leaves the assets
directory alone.

### Nothing on disk moves, and the slot with least room is not the title

The same 60 card/canvas pairs step 1 hashed — the twelve real slot tables plus
each template, at four canvases — hash identical again, the two known 16:9
quote refusals included and refusing with the same text. The check is inert on
everything that exists.

Why it is inert is the more useful number. Measured across the twelve records,
the tightest drawn line is **`rerate-scream4`'s date line at 72% of its box**
(1176 of 1640); the widest title is `reveal-screamVI` at 56%, and the notes
run 16–33%. So the constraint step 3 hits first is not the slot the note is
about — a date line enlarged the way finding 2 enlarges the quote is refused
before any title is. It is worth knowing before the portrait files get
authored rather than after, as a refusal nobody predicted.

### What the box is, and what it still is not

A line runs from one margin to its mirror, so the box is derived from the
anchor rather than believed: `start` gives `1920 - 2x`, `end` gives
`2x - 1920`, `middle` fixes `x` at 960 and takes `1920 - 2·BODY_MARGIN`. The
drift guard checks the pair, so a mis-stated box and a size the file does not
draw both fail — the same duplication `quote`'s `x`/`y`/`size` has always had,
now with the arithmetic tying the two ends together.

What it does not check: **two independently anchored elements on one row.**
`reveal`'s footer draws the year at x=140 and the wordmark ending at 1780, each
measured against the full 1640, so in principle they could meet without either
overrunning. On real cards the year is 133 units against a mark of a few
hundred, so this has never been close, and a row concept would be a fourth
idea to hold. Named rather than built.

A blank slot is not measured. Five line slots on a card and typically two
filled, so measuring the empties would roughly triple the renders a fill costs
in order to ask about text nobody wrote.

## The portrait cards — the vertical card layout, steps 3 and 4 — 2026-08-11

`receipt.portrait.svg`, `reveal.portrait.svg` and `rerate.portrait.svg`, the
twelve re-authored through them in `~/lucid-vertical/proj`, and a sheet on
**`:8798`** — not `:8797`, which is still holding the stacked splits Tyler owes
a verdict on.

The mechanism needed nothing new. The grid stays 1920 units wide, so the files
are the same coordinate system with a taller viewBox; each scales its derived
markup in its own `<g transform>` (`stars` at 1.6, `comparison` at 1.2), which
works because `stars_markup` draws at a fixed radius and a vector scales
cleanly. Nothing in `graphics.py` learned what portrait means beyond three
entries in the table.

### `card_reauthor` could not see the change, and said the project was fine

The finding of the step, and it fired the first time the command was run. A
variant shipping **changes what a canvas draws without changing the canvas**,
so a sweep that compares canvases answered `redrawn: 0` over twelve cards that
were all still the landscape layout — the project read as up to date and every
card was wrong. Not a refusal, not a warning: a green report.

The fix is to record which *file* a card was drawn from, not only what shape it
was drawn at. `card_new` writes `variant` alongside `canvas`, and the sweep
compares both, reporting `layout base -> portrait` as its reason. It is
additive and optional: absent means the record predates variants, which is the
same as none, and is what every record on disk already meant — so it is not a
schema bump, by the rule `caption_style` and `canvas` set.

### Two of the sizes are bound rather than chosen

The type could not simply scale with the frame, and both places it stopped were
measured.

- **The comparison row is 1290 units at five stars against five**, in a
  1640-unit box. That is a ceiling of 1.27x and it sits at 1.2 — the one
  element a taller frame cannot enlarge along with the type, because its width
  is set by the rating rather than by the design.
- **`date_line` caps at 46 on `rerate` and 54 on `receipt`** while the title
  went 122 → 176. `rerate-scream4`'s date line is the widest single line on any
  of the twelve, 1176 units at 42, which reaches the box at 58.6.

That second one is step 2's own finding arriving on schedule: it recorded that
the tightest drawn line on the twelve was that date line at 72% of its box, not
any title, and that it was where an enlargement would be refused first. It was.

### What the layout moved, measured

Trimming a card needs `-shave 3x3` first. librsvg antialiases the background
rect at the viewBox edge, so the corner pixel comes back at **alpha 0.91**,
`-trim` matches nothing against it and hands back the whole frame — 1080x1918,
which reads as a full-bleed card rather than as a failed measurement. With the
edge shaved:

| | before | after |
|---|---|---|
| receipt ink ends | 15.2–25.3% down the frame | **29.9–59.8%** |
| reveal block | 39.2% → 96.9% | **28.1% → 78.5%** |

The second row is finding 4 closing: 96.9% is inside the bottom 20% the
platform's own UI covers, and the year and wordmark were sitting in it.

**The two emptiest cards are the honest limit of a layout fix.**
`rerate-scream4` at 29.9% and `receipt-scream7-2026` at 33.9% — a short quote
has nothing to fill a tall frame with, and repositioning the stack cannot
invent content. Both are on the sheet, labelled, rather than cropped out of it.

### Two tests changed shape, and the change was Tyler's call

Both were step 1's, and both encoded "no variant files exist yet" rather than a
claim about behaviour — the premise step 3 was always going to remove.
`test_a_template_with_no_variant_draws_its_own_file_at_every_canvas` split into
the two properties that outlive it (a canvas no variant selects draws the base
file and `BASE_GEOMETRY`; a template declaring no variant is untouched at any
canvas, staged). And `test_the_same_quote_fits_a_taller_canvas` kept its
assertion and shortened its synthetic quote from forty repetitions to sixteen,
because the portrait quote is 80u against the base file's 46u and the length
that demonstrated the claim at one size overruns at the other. Sixteen is still
longer than any real card and still far past what 2.35:1 holds. Asked rather
than assumed, per CLAUDE.md.

The two guard tests whose *setup* the new files broke — a declared variant with
no file, and a variant file the manifest does not declare — kept their
assertions untouched and had their scenarios restored: the staged copy loses
the file, or the manifest loses the declaration.

### Left to the watch

The sheet asks three things, two of which the design note reserved and one the
build added. How much of the bottom the platform eats — 20% is drawn on the
sheet as an orange band, and everything else was laid out around it. Whether
the wordmark stays bottom-right, which no card on the sheet can show because
none of the twelve sets one. And which quote size reads, 80 or 96: both fit,
80 is shipped, and the sheet puts them side by side.

## The orphaned year — the vertical card layout, the watch — 2026-08-11

Tyler watched `:8798` and answered the three questions the sheet asked, plus
one it did not: *"the spacing on the reveals is a bit weird but the receipts
look mostly fine."* That sentence is the whole of this section, because the
difference between the two cards is one element and the sheet did not name it.

**The reveal drew its year in the footer, and it was the only ink between the
note and the bottom margin.** Ink bands down the frame, at 1080x1920:

| | bands, top to bottom |
|---|---|
| `receipt-scream-1996` | 249 · **75** · 49 · **67** · 55 · **28** · 87 · **200** · 25 · **96** · 989 |
| `reveal-screamVI`, as watched | 540 · **113** · 58 · **41** · **724** · **30** · 414 |
| `reveal-screamVI`, now | 540 · **113** · 58 · **41** · 69 · **32** · 1067 |

(Bold is ink, plain is gap.) The receipt is a block and then a margin. The
reveal was a block, a 724px hole, and a stranded `(2023)` — a cluster and an
orphan. Both cards leave about half the frame empty; only one of them puts
something in the middle of it, and that is what reads as wrong. So the fix is
not more content or a tighter stack: the year moves up into the block, and the
reveal becomes the shape the receipt already was. Gaps 58 → 69, against the
receipt's 49/55/87/25.

Worth recording because the sheet asked about *sizes* and *reserves* and the
answer was about neither. **A layout is judged on where the ink clusters, and
nothing measured in step 3 would have caught this** — every slot fitted its
box, every number was inside its budget, and the card was wrong. It took a
watch, and the watcher named the right card without naming the reason.

### Two answers, one of which changed the layout again

**The bottom reserve: 20% is right, keep it.** 384px of 1920, against the
published overlays — TikTok organic ~324px, TikTok in-feed ads ~370px (the CTA
button is what widens it), Reels ~320px, Shorts ~300px. The portrait
`foot_margin` of 740 puts the footer baseline at 78.4%, 31px clear of the line.
`goodsometimes/branding.md` says "UI covers bottom" and gives no number; this
is the number, and it is now in `BASE_GEOMETRY`'s comment rather than in a
reviewer's head.

**The right edge is the one that was actually broken.** TikTok's action rail —
like, comment, share — runs 180–300px up the right side below the halfway
line. A 140-unit margin is **79px**. So `mark` at `x=1780`, which is where the
landscape file puts it and where all three portrait files inherited it, sat
under the like button. Portrait draws the wordmark bottom *left*, where the
requirement is ~60px and it has 79. Nothing measured this either: the card
fitted its own frame perfectly and the frame was not the whole story.

The wordmark question came back "yeah we can put a watermark i guess?", which
is not an instruction to write one, so none of the twelve gained a `mark` —
the sheet shows `G*` rendered into the corner with both zones drawn over it,
and the write is one pass whenever he says. Two things the sheet flags rather
than decides: the mark is a plain text slot so its asterisk draws muted rather
than amber, and `branding.md` files the corner bug under *long-form* while its
Shorts/TikTok row asks only for the top-third title zone — the doc arguably
wants no mark here at all.

**Quote size settled at 80**; both read, so the shipped value stands.

### The sweep's next blind spot, named and not built

`card_reauthor` compares the recorded canvas and the recorded variant, which
is what step 4 added. Neither moved here: same 1080x1920, same `portrait`
file. **What changed was the file's contents**, so the sweep would have
answered `redrawn: 0` over twelve cards that are all the old spacing — step
4's finding one level down. The twelve were redrawn by name, which is what the
named form is for. Hashing the template into the record would close it and is
deliberately not built: a template edit is a change to lucid's own code, and
"run reauthor after you edit a template" is a rule about the dev loop, not
about a project on disk. It is only worth a paragraph because the shape has
now bitten twice.

## The brand mark on a line slot — 2026-08-11

Tyler approved a wordmark on the twelve vertical cards and then, shown three
renderings of it, picked the one lucid could not draw. `branding.md` locks the
mark as **Zilla Slab Bold with an amber asterisk** — `G*` where the `G` is ink
and the `*` is the accent. A card's `mark` is a `kind: "line"` slot, and a line
slot was a plain substitution: one `font-family`, one `fill`, escaped and
dropped into the template. Two colours in one word was outside what it could
say, and the two shipped-in-error alternatives are worth naming because both
looked fine: the mark drew in **Outfit**, the body face, because the slot
declared `"font": "body_font"`; and the asterisk drew muted grey, because the
`<text>` element has one fill and nothing overrode it. Neither is an error any
check would raise — the card rasterises, `magick` exits 0, every slot fits its
box.

**The fix was not new machinery.** The flowing slots have carried an inline
vocabulary since § The emphasis-capable quote slot — `[em]…[/em]` is amber at
weight 700, `[dim]` is ink at 0.42, `[key]` is plain — and `[em]` is exactly
what an accented asterisk is. So line slots got the same vocabulary, and the
mark is now authored as `G[em]*[/em]`: the brand stays in the brand's document
and lucid learns nothing about Good\*.

Three things had to be true for that to be additive rather than a restyle.

1. **A value with no marker in it takes the old path exactly.** `has_runs`
   gates it, and the reason is `card_reauthor`: if adding the vocabulary
   changed the bytes of every card that never used it, the next canvas sweep
   would report twelve cards redrawn on a release that changed none of them,
   and the sweep would stop meaning anything. A test holds the property.
2. **Unmarked text inside a marked value states nothing.** `_runs_markup`
   names weight and fill on every run, which is right for a flowing slot whose
   element sets neither; a line slot's element sets both, so `line_markup`
   emits a bare `<tspan>` for unmarked runs and lets them inherit. Declaring
   them would silently re-ink the `G` while fixing the `*`. There is also no
   positional `<tspan x= dy=>`: half these elements are `text-anchor="end"`,
   where an explicit `x` opens a second text chunk and moves the line.
   `xml:space="preserve"` is still owed, for the reason that section records.
3. **A marked run measures at the run's weight.** This is the half a drawn
   card cannot show and the only one that could ship wrong quietly. `[em]` is
   a weight change as well as a colour, so `line_parts` expanding the markers
   away without carrying the weight would under-measure exactly the fragment
   the author emphasised — the fragment most likely to be why the line got
   long — and `_check_line_fits` is a line slot's only guard.

The slot's face moved with it: `mark` now declares `title_font`, held by a
test that checks the spec and the six SVG files agree, because the measurement
reads the slot's `font` and the raster reads the file's `font-family`, and a
drift between them measures in one face and draws in another at exit 0.

Settled by reading the render, not the manifest: the finished 336.3s vertical
cut has 112 amber pixels in the mark corner of a receipt at 21.5s and 106 on a
reveal at 156.5s. A grep of the SVG would have said the same thing about a
document librsvg could have quietly declined to draw.

## Keeping the split the sheet argued against — 2026-08-11

The stacked-split sheet asked two questions and recommended dropping back to
one window on the car scene's second, three-face window: sampled at 9.9s the
two panes were near-duplicates of each other, and a stacked frame framing
nobody looks deliberate. Tyler kept it, for the whole scene.

**The watch says he was right, and the sheet's evidence was a sampling
artefact.** At 333.5s of the render the top pane holds the back-seat passenger
alone and the bottom holds the driver and the front passenger — two distinct
groups, not one wide view twice. The 9.9s sample happened to catch the moment
the three converge. That is the same failure mode § The auto-framing detector,
built recorded from the other side: three sampled frames decide whether a
window is a split, and a frame is not the shot. Here it did not produce a wrong
window, only a wrong *recommendation* — the sheet's tiles were accurate and the
prose over-read them.

Worth keeping because the sheet is the review instrument: it draws the sampled
moments, and a reader — including the one who wrote it — will generalise from
them. Recommendations off a sample say which moment they are off.

## The thirty-nine windows, reviewed — 2026-08-11

The detector's 39 windows on the vertical cut, judged one at a time on the
source frame each was placed against. **All 39 are correct for the shot they
were placed on** — faces centred, lead room the right way, no repeat of the
hand pass's two-of-fifteen-wrong-invisibly. The placement rule is not what
needs work, which is the opposite of what the item was watching for.

**What the review found instead is coverage.** Of 245.7s of placed footage,
24.4s carries a window placed for a *different* camera shot at the shipped cut
floor, and 77.6s — about a third — once the floor is right. Two mechanisms,
and they want different fixes.

**One: a refused window carries the previous shot's framing, and it is not a
rare edge.** `cold-open`'s window at 44.461 holds for 21.4s of screen time
across four camera setups. It is exactly right for Casey on the phone and then
sits, unchanged, over a stand of trees and a pan of popcorn on a gas ring. The
cuts at 52.260 and 63.062 scored 0.278 and 0.228 — *above* threshold, so
windows were proposed and refused, there being no face in a tree. Nothing is
written for a refusal, so 13.6s of one clip in a 5:36 film is framed by a rect
chosen for a shot that ended long before. § The auto-framing detector, built
recorded the mechanism from a count of refusals; this is what it costs in
seconds, and nothing in the manifest, `status` or the sheet says it happened.

**Two: `SCENE_THRESHOLD` was pinned on three clips and this cut draws on
nine.** Six cuts scoring 0.155–0.188 inside placed footage, sampled a quarter
second either side: **six of six are real camera cuts**, a different setup and
a different subject each time. A cut with no window is one the framing walks
straight through, so the floor's own miss rate is a framing number. Re-scored,
the film's stale share is 10% at 0.30, 10% at the shipped 0.20, and 32% at
0.15 — a 53-second cliff in one step. Whether every cut in that band is real is
unproven; the six that were checked all were.

**The instrument has the same blind spot as the thing it reviews.**
`reframe_sheet` samples each *placement* at three fractions, which on this
project never looks at 14 of the 55 windows — **eight of them hand-approved**.
And where it does sample it draws the window in force, so the tree frame above
tiles up looking like a composition somebody chose. Reviewing this needed a
tile per window, sampled at the midpoint of the stretch each placement actually
shows of it; the sheet's own unit cannot see a quarter of the project.

**A stacked split's panes are worth measuring against each other.** The four
splits separate cleanly by how much of one pane the other covers: 23.1% and
24.1% for the two on `s4-overexposed`, which hold distinct groups, against
52.3% on `vi-bailey` and 59.4% on `s2022-reveal`, where the same face is in
both halves and stacking shows it twice. That is a line, not an opinion, and it
answers the open question about `s2022-reveal` — it is split unasked, and it is
the duplicating kind.

**Five shots open or close on a flash of the wrong picture**, worst a
three-frame head on `vi-richie`'s shot 7 that jumps 568px once the source's own
cut arrives. Both windows are right for what they hold; the placement's
in-point sits the wrong side of a camera cut. An edit fault the framing merely
made visible — nudging the in-point fixes it and touching the framing would
not.

**But only that one survives being scored, and the count of five does not.**
Scoring all 25 placements head-frame against settled-frame (2026-08-12,
`~/lucid-approvals/flash_scan.py`) separates exactly one: `vi-richie` at
59.528s scores 58.5 against a *continuous* 28.7-to-21.8 band holding everyone
else, and the third-ranked is the film's own fade-up from black at 0.000. So
there is one in-point to nudge on evidence and four that would be guesswork —
and the signal cannot tell a flash from a fade, which is why the by-eye pass
is what named them and a threshold on this score would not.

The measurement walked into this file's own trap on the way: matching ffmpeg's
cut times to window starts *exactly* reported 20 stale stretches where there
are 6, because ffmpeg says 5.588 where the manifest holds 5.5889. A frame of
tolerance, never an epsilon — the same rule § The auto-framing detector, built
already carried, arrived at from the other side.

## `reframe_coverage` — 2026-08-12

§ The thirty-nine windows, reviewed found the detector's placement rule sound
and its **coverage** not, and left the finding nowhere a project could be asked
for it. `reframe_detect` names `falls_back_to` for the windows it refuses in
the call being made and then throws it away; nothing is written for a refusal,
so the manifest, `status` and `reframe_sheet` were all clean over 13.6s of
`cold-open` held by a rect chosen for a shot that ended long before. This is the
asking, and it is a read: scene cuts against stored geometry, no face detector
involved, so it answers on a box where `reframe_detect` cannot run at all.

**One observable, two mechanisms, and it deliberately does not separate them**,
because the render cannot. A refused proposal writes nothing; a cut under
`SCENE_THRESHOLD` is never offered a window. What reaches the film either way
is one rect held across a camera cut.

**The question is asked of the footage, not of the cut, and the first build got
that wrong.** Walking the cuts *inside* each placement finds only the stretches
where the picture changes mid-placement — it cannot see a placement that
**begins** downstream of the cut that stranded it, whose every frame is framed
by a window chosen before that cut and which contains no cut at all. On this
film that mistake cost 6.0 of `cold-open`'s 13.6 stale seconds, and the missing
stretch was the one in the middle. So each placement is split wherever the
framing could change — a window boundary, or a cut the framing does not follow
— and each piece is asked what is covering it: stale iff a cut lies between
where the governing window began and where this footage starts.

**An override held across a cut and the centre crop walking through one are
counted apart.** The first is worse than the default, because a stale window
looks deliberate; the second is the default doing what it always did, and
rolling them together would report a project nobody has framed as one somebody
framed wrong.

**It reconciles with the detector's own accounting, and the review's headline
does not.** On the vertical cut at the shipped 0.20 floor: 245.745s of placed
footage, which is § The thirty-nine windows' own 245.7s to the millisecond, and
**15.557s stale**. `reframe_detect` independently reports 8 refusals of 59
windows — the review's numbers — of which exactly 4 inherit a different shot's
framing, and those four sum to 4.80 + 6.01 + 2.75 + 2.00 = **15.56s**. Three of
them are `cold-open` and sum to 13.56s, which is that section's own 13.6s. So
the per-clip detail in the review, the detector's refusal table and this op all
agree; what does not is the review's summary figure of **24.4s / 10%**, which
cannot be assembled from the four inheriting refusals it also reports. Its
probe is gone and the discrepancy is unresolvable from here, but two of its
three checkable numbers land exactly and the third is the odd one out. At 0.15
this op reads 68.738s / 28.0% against the review's 32%, uncheckable the same
way.

The frame of tolerance is load-bearing here for the reason § The thirty-nine
windows recorded from the other side, and a test pins it: ffmpeg reports a cut
where the manifest holds a number 33µs away, and an exact match reports stale
stretches that are not.

## The approvals round, answered — 2026-08-12

Ten calls in `~/lucid-approvals/`, all answered on the phone in three minutes.
Two of them changed what gets built rather than how, and the record of what was
chosen is `decisions.json` beside the page — this is only what shipped off the
back of it.

**The one that reorders the queue is a note, not a choice.** Against the vertical
cut Tyler picked "needs another pass" and wrote: *I don't need a full vertical
cut like this — I only need the teaser that we're making.* § The hand-framed
teaser, watched had already recorded the reason without drawing the conclusion:
Shorts and Reels cap at 3:00 and the film is 5:36, so **a teaser is the only
vertical output that can reach the feed at all** and the 5:36 vertical was never
distributable. The teaser answer then routes it through `lucid reel`. So the
per-shot framing coverage numbers — 15.557s stale at the 0.20 floor, 68.738s at
0.15 — are sized against a cut nobody will publish; what has to hold is the
teaser's own shots. The framing rects survive the derivation for free, because a
window is addressed in *source* seconds and no edit can invalidate one.

### Every card in the film was the wrong shape, and nothing said so

The quote trims were the item; the finding was underneath it. The twelve cards
in `~/lucid-final-cut/proj/assets/cards/` were all **1920x1080 against a
1920x816 canvas**. MLT `contain`s a still, so each drew shrunk to 1450 wide with
bars either side — for as long as the essay has existed. Nothing reported it:
the cards are assets, not clips, so no `width`/`height` sat in the manifest to
disagree with the canvas, and the project held **zero card records**, which is
the state § The card record calls unrecoverable-by-anything.

Both overrunning quotes fit at the picked trims — `receipt-scream-1996` at B
(3 lines of the box's 3, was 4) and `receipt-scream4-2011` at A (2, was 6) — and
authoring all twelve into the film itself rather than copying records across is
what fixed the shape and the missing records in one pass, because `card new`
records `(template, slots, canvas, variant)` as it draws and defaults the canvas
to `_mlt_resolution`. 12/12 at 1920x816, 12 records, projection still builds:
38 shots, 13 card placements, no refusal.

**The render on disk is still the old one.** v7 carries the pillarboxed cards,
so nobody has yet watched the cards that are now on disk — the same shape as
§ The film had no captions in it, where a manifest, a view and a check all
agreed about something the file did not have.

### `fc-match` is not what libass asks

Captions moved off `DejaVu Sans`, which is not installed here and drew as Noto
Sans in every caption lucid ever burned, onto `Outfit` — the brand face for
"tagline, titles, labels" (`goodsometimes/branding.md` § Type), installed, and
the face the cards' own meta lines use.

Settled by render, per the standing rule. At 64pt the same line inks 768x78 in
Outfit against 679x71 in Noto Sans, RMSE 4740 between them and 0 against a
re-render of itself, so Outfit is genuinely drawing and not substituting.

**Then the control misbehaved, and the reason is worth more than the change.**
A deliberately missing family and `Noto Sans` both answer `NotoSans-Regular` to
`fc-match` — and render **3593 RMSE apart at identical weight**, 613 against 599
ink px. libass's own trace says why: for the literally-correct name `Noto Sans`
its *first* pick on this box is `SymbolsNerdFont-Regular.ttf`, and it only
reaches `NotoSans-Regular` by failing to find glyph 0x45 and falling back; the
missing family lands on `NotoSansArabic` first and falls back the same way. The
Latin glyphs then match, but the primary font still supplies the space advance,
which is the 14px.

So the rule "settle which face draws by measuring a render, never by `fc-match`"
has a mechanism now, and a sharper consequence: **`font_match` reports
fontconfig's answer, which is not the question libass asked.** It reported
`resolves_to: Outfit`, correctly — and it would have reported `Noto Sans` for
`Noto Sans` on a box where libass drew a symbol font. Left as is deliberately;
making it a libass query is a design change, not a fix.

`Outfit` is the one that needed none of this: a single pick,
`Outfit[wght].ttf` instance 458752 as `Outfit-Bold`, no fallback line at all.

## The end card, and what tail time actually costs — 2026-08-12

Tyler asked whether the essay should get an end card the way the teaser got a
bumper. It should, and `goodsometimes/pipeline.md` § Package already had
**"End screen added"** unchecked with `scripts/make_outro_card.py` written for
this exact video — never run, no `outro.png` anywhere on disk.

**It is not the teaser's bumper.** B reads "the full Scream essay / on the
channel", which points at the thing you would already be watching. And the
register runs the other way here: `branding.md` rule 10 has the trajectory
going Hereditary → Sicario, which "ends by ceding the floor to the final
scene. No CTA." The teaser broke that deliberately on the grounds a teaser has
no other job; the essay is where it was meant to hold. So the card is
**bumper A's register** at 16:9 — the mark, no CTA.

### The tagline was on it, and branding.md says it must not be

The first card drew the lockup, an amber rule and the tagline under it. Tyler
watched it and called the tagline repetitive; `branding.md` § Visual identity
had already ruled it out, which is the stronger reason. **Wherever the tagline
appears near the wordmark it *is* the footnote** — so the card drew two
footnotes off one asterisk: "good" twice, "sometimes" twice, and the asterisk
three times in one frame. The joke told, then explained.

The rule has a second reading — drop `* Sometimes` and let the tagline be the
footnote — which is the better joke and the wrong card, because an end card's
one job is naming the channel and that version never says "Sometimes" as a
name. So the tagline goes back to the homes the brand table gives it (channel
description, banner, podcast blurb), and the mark stays whole.

**The amber rule went with it, on a watch.** With nothing under it a rule is a
divider pointing at a missing thing rather than a full stop; served as an A/B
against the mark alone, Tyler picked the mark alone. Settled 2026-08-12: mark,
no rule, no tagline, 6s, no CTA (`~/lucid-watch/decisions.json`).

Two things that cost a step each. **The card is the block, so dropping a piece
re-centres it** — the lockup moved down 52px and its clearance of the subscribe
zone is re-reported per piece rather than assumed. And **the superseded card
has to be rendered with the flags it actually had**: letting the comparison
image inherit the new default drew a tagline card with no rule, which never
existed, illustrating the rejected option with a third thing.

### The house end screen is the wrong shape, and scaling it is the wrong fix

1920x1080 against an 816-tall frame, which MLT `contain`s — the same defect
that had all twelve Scream cards drawing 1450 wide until the morning of the
same day. `make_endcard.py` authors at the canvas instead.

Its subscribe circle does not survive the shape change either, and not by a
scale factor. YouTube positions its own Subscribe element against the **16:9
player**, and 816-tall content is letterboxed inside that player by
`(1080 - 816) / 2 = 132`. So the house circle at player `(555, 660)` lands at
content `(555, 528)` — 96px from where scaling 1080 → 816 would put it. The
card therefore draws **no guide at all** and is *sized* to leave the spot
clear: the lockup width is derived from the circle's right edge, not chosen by
eye. Two layout defects fell out of that check rather than out of a look — the
first attempt ran the block 63px below the bottom edge (the house wordmark size
of 170 does not carry to a frame with 264 fewer pixels of height), and the
lockup sat inside the subscribe zone.

### Tail time is cheaper than `vo_extend`, and the cue table is what costs

PLAN.md § Parked frames runtime-after-the-last-word as `vo_extend`, the item
that "touches `Edit`'s subtractive invariant". For an end card it does not.
Appending real silence to `media/vo.wav` and raising the clip's registered
duration makes the new tail an ordinary **gap**, and `restore` — already
bounded by `Edit.gaps` — brings it onto the timeline. The invariant never
bends, because the recording genuinely got longer. `vo_extend`'s actual
subject is material the source *never had*, and that stays parked.

What costs is addressing. **Cues are `(clip_id, word_index)` and resolve
through the transcript; there is no word in six seconds of silence.** Cueing
on the last available word is not a workaround:

| word | text | source | why not |
|---|---|---|---|
| 1148 | `Thank` | 490.0–491.4 | whisper swallowed "you" into it — the card would come up **1.4s early**, over the sign-off |
| 1149 | `you.` | 491.4–491.4 | zero-width; `build_shots`' overlap test refuses it, correctly |

And **faking a transcript word in the silence is worse than it looks**:
`verify` diffs the render's own transcription against the timeline's words, so
an invented word would make this film's verification permanently report a
miss. The honest shape is a cue addressed by **source time** instead of word
index — the same `timeline_span` resolution, the same survival across cuts,
minus the transcript lookup — which touches `cue_add`/`cue_rm`/`cue_ls`/
`_cue_echo`/`build_shots`, the CLI, the MCP server, the window's cue lane and
their tests.

### So it was watched before it was built

PLAN.md § Parked says the case for tail time "is editorial — decide on a
watch". `make_endcard_proof.py` puts the card on the *finished render* with
ffmpeg — 1s crossfade off the last shot, 5s hold — so the editorial question
is answerable before the cue model changes. **The file is a proof, not a cut,
and the lucid project still ends at "Thank you."**

Checked rather than assumed: 8208 frames against 8064 (+144 = 6.006s at
23.976), the card's own ink `(24,22,18)` at both frame edges through the hold,
tail audio at **-91 dB** (digital silence) with the sign-off still at -10.2 dB
peak immediately before it. One real trap on the way: `fps=24000/1001` sets
the frame *rate* and leaves the timebase at `1001/24000`, where the render's
own is `1/24000` — `xfade` refuses mismatched timebases rather than guessing,
so both inputs need an explicit `settb`.

## The teaser, re-cut — and the two things a watch found — 2026-08-12

The approvals round's answer to *does the teaser ship?* was **re-cut it from
the finished film** (§ The approvals round, answered), which `lucid reel` did
not exist for when the hand teaser was built. This is that re-cut, and what
watching it cost.

The span is the film's own 95.4→139.8s — the same passage the hand teaser
read — derived at `1080x1920` into `~/lucid-teaser/proj`. 44.4s, four shots,
1065 frames against the timeline's 1065, `check_black` clean.

**Two silent wrong-films were one command apart, and neither would have been
visible in the result.**

- **The head cue.** At the obvious span start of 95.9 the opening picture cue
  — word 318, `s1996-billy-stu` — falls outside the kept range and is pruned,
  so the teaser opens on **eleven seconds with no picture**. It is reported,
  honestly, as one line of a 35-entry `cues_dropped` list, which is where a
  reader is least likely to notice that one of them is the *first* one.
  Starting at 95.4 keeps it. **What a derivation drops inside its own opening
  is a different kind of loss from what it drops at the far end**, and the
  list does not say so.
- **The pins.** All four surviving cues came across unpinned, and `plan_picture`
  restarts a per-asset cursor the derivation has emptied. Three would have
  been right by luck. `s4-reveal` is used earlier in the film, so its cursor
  starts at 0 rather than 3.670 — **a different 15 seconds of the movie, at
  exit 0**. CLAUDE.md already says to pin a derivation's survivors; doing it
  by hand is a `cue rm` + `cue add` per cue, and `reel` has the film's own
  shot projection in front of it while it prunes.

Framing came across for free, being addressed in source seconds, and is
**better in the teaser than in the film**: 12 of 12 cuts framed, 0 stale
seconds against the film's 15.6.

### A window boundary with no cut under it

Tyler's watch: *"the clip at the beginning is weird it like switches to a
different clip really quickly."*

It does, and it is not a cut. `s1996-billy-stu`'s first stored window starts
at src **0.5012**, and the teaser opens at src 0.0 — so the first half-second
is drawn by the **centre crop**, which puts Stu at the left edge with half his
face outside the frame, and then the frame jumps 510px sideways to the window
that frames him. The source either side is one continuous take: four frames
across the boundary are the same setup, same lamp, same blocking, and ffmpeg's
scene score at 0.5012 is **0.000**.

Measured across the teaser's three assets, three boundaries have no cut under
them and only one is a defect:

| window | nearest cut | what it is |
|---|---|---|
| `s1996-billy-stu` @0.5012 | none, best score 0.000 within 1s | the jump |
| `s1996-randy` @0.0 | — | the clip head, framed from frame one |
| `s4-reveal` @3.6703 | — | the placement's own in-point |

The other two are the *right* pattern and the first one is missing it: every
other clip is framed from the first frame anyone sees. Fixed by extending the
window back to the head — one `lucid reframe --at 0`, source-addressed, so it
fixes the film's vertical too.

**`reframe_coverage` cannot see this, and the reason is the interesting
half.** It asks *which cuts have no window*; this is *a window with no cut*.
The two are not the same question and the second is the one a viewer notices:
a stale window merely looks wrong, while a framing step inside a continuous
take reads as an edit that isn't there. `default_seconds: 0` was correct and
useless — nothing had been held across a cut, because the footage before the
boundary was never framed at all.

### The nine words the film does not say, marked by evidence

The other half of the watch was the captions, and it was known before he said
it: *"Billy **Billions** and Stu **do -** spend"*. Whisper transcribes across a
retake splice and interleaves both takes, so nine invented words land in these
44 seconds — the same nine § The hand-framed teaser, watched found by eye,
where one survived being read for sense because "Billy and Stu **do** spend"
is a grammatical English sentence.

What is new is that **nothing here needs judgement any more**. `verify`
transcribes the finished render and diffs it against the timeline, and the
render's own ears say the clean line. So the mark is settled by the audio, and
`unspoken` is the state that holds it: `(clip_id, word_index, text)`, additive
and optional the way `canvas` and `caption_style` are, **word-indexed for the
reason a cue is** — the transcript indexes the source, so no cut can
invalidate a mark. It does not touch the transcript file, and must not: word
indices renumbering would move every cue.

One derivation, `_spoken_transcripts`, feeds captions, `caption_view` and
`verify` alike, because what the window draws, what the subtitle file contains
and what the render is checked against cannot be three different word
sequences. `verify` reports the count beside its diff — a check whose
expectation was shortened by hand has to say so, or the mark becomes a way to
make a real miss disappear.

**`unspoken_detect` proposes and never applies by default**, the same way
round as `reframe_detect` and for a sharper reason: a wrong mark deletes a
real word from every check lucid has. Two candidate mechanisms, one witness:

- **A seam** — `find_overlaps`, a word starting before the one ahead of it
  ends. 8 of the 9.
- **A fragment** — a cut that left a sliver of a *real* word. Word 407, `The`,
  from an abandoned take: 0.500s in the source, **0.107s surviving**, drawn on
  screen as a whole word and inaudible. No seam, so the overlap scan is blind
  to it.

The witness is the render, and it is **counted, never looked up**, because the
inventions are function words: asking "does the render say `the` near here"
answers yes off the real `the` standing beside the invented one. The
candidate's token is counted in the timeline over a ±1.5s window and in the
render's transcription over the same seconds, and proposed only where the
timeline has more. That is what catches word 407 — timeline 2, render 1 — and
it is what clears the second fragment candidate, which the render does say.

**The fragment floor asks and never decides.** Over the whole film, **947 of
958 surviving words survive whole**; the 11 under 0.5 hold every clipped
fragment in the cut, the shortest being 33ms of a `The`. So a generous floor
costs nothing: it puts 1.1% of words up for a question the render answers.
A floor that *decided* would be wrong for the reason the overlap scan has none
(§ The overlap scan) — partial survival is normal, and 0.48 of a word is a
word.

**A stale mark is kept, never applied.** If the recorded text and the text at
that index disagree, the transcript was replaced under the mark, and the two
failures are not symmetric: a word wrongly left on screen is visible to anyone
watching, and a real word silently dropped is invisible to every check lucid
has. So a re-transcribe surfaces as `unspoken_stale` — a list to re-check —
rather than as words vanishing from a caption file.

Nine marked on the teaser, and the caption track now reads what the render
says: *"Billy and Stu spend the entire film explaining the rules of a horror
movie to you."*

## The tile that made a wrong window look right — 2026-08-12

The re-cut teaser went back for a second watch and came back with one note:
the first shot is *"a bit too far to the left, like if we panned a little bit
to the right we would see more of his face."* He is right by 184 pixels, and
what is worth writing down is not the number but why a review had already
passed it.

`s1996-billy-stu`'s opening window is `220,0,459,816` — a 459-wide crop
centred on 450. A face detector over twelve moments of the shot puts Stu's
face centre at a **median of 634**, never below 557 and as far right as 739.
The crop's right edge, 679, runs down the middle of his face for most of the
five seconds. It is not a jump at the top of the shot — § The teaser, re-cut
found and fixed a *separate* defect there, a window beginning 0.5s into a
continuous take, and correcting that only made the whole five seconds
consistently wrong instead of wrong-then-wrong-differently. Fixed at
`405,0,459,816`, which is `faces.window_x` of the detector's own median.

**That window was hand-approved off a `reframe_sheet`, and the sheet drew it.**
This is not the known coverage gap (§ The thirty-nine windows, reviewed —
windows a sheet never samples). The sheet sampled the placement at 0.15 / 0.50
/ 0.85, the placement spans two windows, and exactly one tile — src **1.714** —
landed inside the bad one. At 1.714 the face sits at 452–714 against a crop of
220–679: 35 pixels of far cheek clipped, a tile that reads as tight and fine.
It is the *least wrong* moment in the shot. The error there is 122px; at the
median it is 184px and at src 4.0 it is 289px.

So the general shape: **a static rect over a moving subject has a best moment
and a worst moment, and three fixed fractions have no reason to find either.**
The sheet is still the right instrument — a watch cannot tell you a crop is
184px out — but a tile is evidence about the instant it draws, and a window is
a claim about a span. What would actually settle one is sampling where the
subject is *extreme* rather than where the clock is round.

Two asymmetries worth keeping in view. The detector had the right answer all
along: `reframe_detect`'s own head window for this clip in the full-length
vertical is 366, within 39px of the corrected number, while the approved hand
number is 185px out — the third case now of a hand window being wrong
invisibly (§ The auto-framing detector, built). And the same wrong rect is
still in `~/lucid-vertical/proj` at `src_start` 0.5012, because the teaser
inherited its framing from that cut; the teaser was re-rendered and the
vertical was not.

## The bumper the teaser never had — 2026-08-12

Tyler watched the reframed teaser and asked why the bumper had been dropped.
Nothing dropped it. The bumper only ever existed in the **hand** teaser of
2026-08-10 (`~/lucid-final-cut/teaser.mp4`, 45.837s), assembled outside lucid;
v2 and v3 are `lucid reel` derivations and have never had one. Which is the
answer to the question he asked, and not the interesting part.

**The teaser is a strictly harder case than the essay's end card**, and § The
end card's reasoning does not carry to it unchanged. That item's escape was to
append real silence to `media/vo.wav`, raise the clip's registered duration and
let `restore` walk the new tail on — the film ends on "Thank you." with room
after it. The teaser ends on live VO at **-9.9 dB peak in its final second**:
there is no silence, and the last word is not a sign-off but the middle of the
argument. So the tail would have to be manufactured *and* addressed, and the
addressing is the same cue-by-source-time work PLAN.md § Parked already prices.

So the same shape as the essay's proof — `make_teaser_bumper_proof.py`, ffmpeg
over the finished render, **and the lucid project still ends on the last word.**
The treatment is measured off the hand cut rather than chosen, because that is
the version that was approved: footage to 43.710, a 4-frame dissolve, then the
card alone to 45.837. Verified by readback rather than assumed — the card
intact at 1080x1920, audio under it at -91 dB against the -9.9 dB immediately
before, and bumper **B**, since the teaser is the one place the no-CTA rule was
broken deliberately.

**The arithmetic trap is that the dissolve overlaps the film's own last frames
rather than following them.** `xfade` at `offset = DUR - FADE` finishes the
transition exactly at `DUR`, so the tail length passed to it is the time the
card holds *alone*; adding the fade to it on the way in runs the bumper long.
Four frames, caught by measuring the render and not by reading the filter.

**And a derivation cannot inherit a finishing pass.** The bumper is applied
downstream of `export`, so re-deriving the teaser — the exact thing that
happened between the hand cut and v2 — silently produces a cut without one, at
exit 0, and nothing in `status`, `verify` or `check_frames` has an opinion.
That is the real cost of leaving tail time parked, and it is a shipping-level
loss rather than a modelling one.

### The reference on the review page had no bumper either

The page served three cuts, one of them labelled "Hand-built, 2026-08-10 — 15
shots". It was not: it was a later render of a different edit (18 detected
scene changes against the hand cut's 15, and 44.522s against 45.837), and it
had no bumper. So when he went looking for the thing he remembered, **nothing
on the page had it, including the control** — and the question came back as
"why did you drop it" rather than "which of these is right", which is a
different and much slower question to answer.

A review page's reference is load-bearing exactly when the reader is checking a
memory against it, which is the case nobody labels carefully because the
reference is the part that is not being asked about. Settle a served control by
its own measurement — duration, shot count — not by its filename.

## The three gaps, closed — 2026-08-12

Three defects found by watching the teaser, all recorded in `CLAUDE.md` and
none built. They have nothing in common as code and everything in common as a
failure: each is a wrong film that every check in the project agrees with.

### A derivation pins what it keeps

`lucid reel` prunes the cues it orphans and names them. Pruning them is what
strands the rest: `plan_picture` walks one cursor per asset and each shot picks
up where the previous one left it, so dropping the shots before a survivor
empties the cursor it was counting on and it replays its asset from the head.

Measured on the film's own teaser span (95.4–139.8s): **34 cues dropped, 4
survive, and 2 of the 4 need a non-zero in-point** — `s1996-billy-stu` at
11.428s and `s4-reveal` at 3.670s. Unpinned those two show the first seconds of
their clips instead, which is 15 seconds of a different film at exit 0.

So `_reel_cue_pins` reads the in-points off the *film's* own picture plan and
writes them onto the survivors as `src_start`, which is the thing that makes
`plan_picture` refuse rather than rewind them. **The pins reproduce the hand
fix exactly** — the same four numbers already in `~/lucid-teaser/proj`, applied
by hand on 2026-08-12 after the watch found the defect — which is the control
this had: the op now derives what a person had to notice.

Three things it does not do. An existing `src_start` is never overwritten: a
pinned shot has no cursor, so the film's plan agrees with the pin by
construction and a hand-chosen in-point is the last thing a derivation should
rewrite. Stills are left alone, `plan_picture` refusing a pin on a held frame.
And a film whose own projection refuses comes back as `pins_error` rather than
an empty `cues_pinned` — that film cannot be exported either, so the reel is
not newly wrong, but it is why its cues arrive unpinned and an empty list alone
reads as "nothing needed one".

### Which windows have no cut

`reframe_coverage` asks which cuts have no window. The teaser's opening defect
was the other direction — a window boundary 0.5s inside a continuous take,
stepping the frame 510px sideways with no cut behind it — and coverage answered
clean and useless, because nothing was held *across* anything.

`steps` is the mirror, in the same walk: a boundary strictly inside a
placement, where the frame moves and the picture does not. A boundary at a
placement's own edge is not one, the timeline cutting there being reason enough
for the frame to. A boundary with the same rect on both sides is not one
either — nothing moves, so there is nothing for a cut to justify, and a window
per shot normally repeats a rect.

**The two directions score against different cut lists, and that is the load-
bearing part.** A cut must reach `threshold` to *demand* a window, because that
floor was pinned by a control against sixteen approved boundaries. It only has
to be detected to *explain* one. Scoring both off the thresholded list would
report a boundary sitting on a real 0.15 cut as a defect and send someone to
re-frame a shot that is already right.

What it finds on the shipped work, which is the reason it is worth having:

| Project | boundaries that move the frame | with a cut | without |
|---|---|---|---|
| `~/lucid-teaser/proj` (re-cut, watched twice) | 13 | 12 | **1** |
| `~/lucid-vertical/proj` (55 windows) | 33 | 31 | **2** |

**The vertical's number was 15 until the findings were looked at, and 13 of
those were this file's own trap for the third time in one build.** A window
placed *at* a shot boundary is the normal case — it is what `reframe_detect`
writes — and the placement's `src_start` is computed while the window's is a
rounded manifest value, so the two sit ~1e-7 apart and `start < at < end`
called every one of them an interior boundary. The same frame of tolerance had
already been written twice in the same session, once in `reframe_coverage`'s
older half and once in the sheet, and was still missing here. What gave it away
was the drawn evidence and not the number: `vi-richie`'s "before" window was
holding empty background a frame before the boundary, which is not what a step
looks like — it is what a *different placement's* window looks like.

**The two that survive are the two a watch had already found**, which is the
only control available for a check nobody can run twice:

- `s1996-billy-stu` at src 0.501 — a 146px move *left* on a continuous take of
  Stu, whose face sits at 666 then 651. It makes the frame worse, and it is
  § The tile that made a wrong window look right's subject, still in the
  vertical because the teaser was re-rendered and the vertical was not.
- `s4-reveal` at src 7.343 — **410px, and it is in the shipped teaser** at
  32.5s of 44s. This one is not a wrong window: Sidney crosses from 810 to
  1154 over two seconds and the window steps to follow her, which is a
  keyframed *move* (PLAN.md § Parked) rendered as discrete keyframes because
  that is all lucid has. Both crops hold near-featureless dark at the boundary
  itself, which is the only thing softening it. A watch decides this one.

**And the `SCENE_THRESHOLD` reading was wrong too, in the safe direction.**
Five of the fifteen sat within 0.6s of a change scoring 0.15–0.18 and read as
the floor missing a cut. Scored at the boundary itself with no floor at all,
every one of the fifteen is between 0.0016 and 0.0134 — the picture is
continuous at all of them, and the nearby sub-threshold change is a *different*
instant that happens to be nearby. `steps` says nothing about the re-pin.

### The sheet's unit is a window

Three fixed fractions of a placement never looked at 14 of the vertical's 55
windows, **eight of them hand-approved** — a window covering a small slice of a
long placement is one no round fraction lands in, and it was reported as
reviewed. § The thirty-nine windows, reviewed named this and left it.

A row is now a window shown rather than a placement: each placement is split at
the boundaries it crosses and each stretch sampled inside itself, so `moments`
are fractions of the window's own span. A short window gets the same three
looks a long one does, and `count` is no longer the placement count —
`placements` is reported beside it and the two differ by exactly what the old
unit could miss.

**On the vertical cut that is 58 rows against 25 placements, and all 55 stored
windows are drawn** — checked by set difference against the manifest, not by
counting rows. The two extra rows are the centre crop at the head of
`cold-open` and of `s3-reveal`, which is the unframed-head case turning up as
a drawn tile rather than as something to remember to look for.

**The float edge is real and cost fifteen of those rows before it was fixed.**
A window boundary and the placement that starts on it are the same instant a
frame apart — 20.39538 against 20.39541 — so comparing exactly split off a
stretch 30µs long, drew three tiles of it, and left the placement itself
labelled with the window it was about to leave. Same at the tail. It is
`reframe_coverage`'s own rule arrived at from a third direction: **a frame of
tolerance, never an epsilon**, and the later of two addresses inside one frame
is the one that wins, because that is what the render steps to and what a rect
is stored at.

`windows` on a row survives, and it is now counted off the geometry rather than
off where the samples landed. It was the sampling artefact of the two: three
moments crossing three windows could report two. It is also the preview/render
asymmetry's own tell (CLAUDE.md), so it had to keep meaning the *placement's*
count — which is why the row carries `window`, the source address its rect is
stored at, separately.

**This closes the coverage half of § The tile that made a wrong window look
right and not the other half.** Every window that reaches the screen is now
drawn; a tile is still evidence about the instant it draws, and a static rect
over a moving subject still has a best moment for a sample to land on. Sampling
where the subject is *extreme* rather than where the clock is round needs the
face detector, which is `reframe_sheet`'s first dependency on `LUCID_FACE` and
a different build.

## The sheet samples where the subject is — 2026-08-12

`reframe_sheet --extremes`, which is the half of § The tile that made a wrong
window look right that drawing every window did not close. A window is a claim
about a span and a tile is evidence about an instant, so three fixed fractions
have no reason to find either the best moment or the worst one.

**The rect does not move inside a stretch, and that is what makes three tiles
enough.** The error is `|subject_x - crop centre|`, monotonic in `subject_x`
either side of that centre, so the worst moment is at one of the subject's own
ends whatever it did in between — leftmost, median, rightmost, worst first
because a sheet is read left to right on a phone and the reassuring tile was
the one that got looked at. Each stretch is probed at 2Hz (floor 3, ceiling 16)
and each tile is labelled with the subject's signed offset from the middle of
the crop.

Rebuilt the indicted window as a control — `s1996-billy-stu` at 0.5012 set back
to the wrong `220,0,459,816` on a copy of the teaser — and measured both
samplings over all 18 rows:

| | worst moment drawn |
|---|---|
| fixed fractions (the default) | **186px** |
| extremes | **284px** |

At 186 the subject's centre is still inside the crop and the tile reads as
tight; at 284 the crop's right edge runs down the middle of Stu's face. Worth
recording that the fractions do better here than the 122px § The tile… found —
that number was the *placement*-level sampling, and § The three gaps, closed
already moved the row to the window. The instrument's remaining gap was
narrower than the finding that prompted it.

**Two things the measurement corrected, both of which the number alone would
have hidden.**

*The probe grid has to contain the fractions.* Probing at a rate finds the
extreme of the probed *sample*, not of the stretch. Scored against the default
on the first build, extremes was **worse on 5 rows of 16** — by up to 29px —
because a fraction landing between two probes caught a moment no probe did.
That is a sheet that changed its sampling and got quietly worse, which is the
whole failure class this repo keeps finding. Sampling the fractions too costs
at most three frames a row and makes the old sheet a subset of this one: after
it, extremes is never worse and is better on 4 rows of 16.

*A large offset can mean nothing.* `faces.frame_centre` is area-weighted across
every face in the frame, so two faces put the subject between them where
neither is. The teaser's largest offset, **608px on `s1996-billy-stu` at
17.601**, is Stu at 1079 averaged with a bystander at 1775 against a crop
centred on 830 — Stu is 250px out, not 608. `faces.py`'s own which-face-is-the-
shot finding, arriving in a review number. The number is kept, because it is
the same subject rule the framing itself uses, and `multi_face` and a per-tile
face count travel with it.

**One real finding on the shipped teaser**, judged on the drawn frame rather
than the number: `s4-reveal`'s window at 11.053 (`780,0,450,800`) holds the
back-of-head figure and clips Sidney, who is speaking — 187px out at the
subject's leftmost and 274 at its rightmost, one detection, so consistently
rather than at an instant. A watch decides it; it is not the 410px follow at
7.343, which measures 36.

And `~/lucid-vertical/proj` is **gone**, deleted on request 2026-08-12 — only
the teaser ships, so the full-length vertical cut was 468MB of project holding
one known-wrong rect nobody would re-render. Its 55 approved windows, 38 cues
and 12 card records survive as the manifest alone in `~/lucid-archive/vertical/`
(176KB). Nothing in the suite referenced it; the framing-port spike names it as
a target and would now do nothing. The teaser keeps 17 windows over 3 clips,
which is the framing that shipped.

## The scene threshold, re-pinned — 2026-08-12

`SCENE_THRESHOLD` moves from **0.20 to 0.15**, and the reason it moved is that
the first pin was answering a different question than the one it was asked.

PLAN.md § The auto-framing detector, finding 1 scored ffmpeg's candidates
against the sixteen approved framing boundaries and read the match rate as
precision. Recall was flat from 0.05 to 0.20 and "precision climbed
monotonically", so 0.20 looked picked-by-the-control rather than chosen. **What
that column actually measured is how much of the film the hand table had
framed** — fifteen windows over three of the film's nine clips — because a real
camera cut in a shot nobody had chosen to frame counts against the floor in
exactly the same way a false positive does.

So every candidate the film shows was judged directly, on the frames either
side, across all nine clips: 81 candidates inside a placement, of which the 59
in `[0.05, 0.25)` were looked at one pair at a time. Three verdicts — `cut`,
`same` (the same shot either side), and `again` (a transition the scan reported
on a second adjacent frame, which is neither a hit nor a mistake).

| band | judged | real cuts | not a cut | same cut twice |
|---|---|---|---|---|
| 0.20–0.25 | 13 | **13** | 0 | 0 |
| 0.15–0.20 | 21 | **21** | 0 | 0 |
| 0.10–0.15 | 10 | 7 | 1 | 2 |
| 0.05–0.10 | 15 | 5 | 8 | 2 |

**There is no trade-off in the band the old floor sat in.** Every one of the 31
candidates from 0.141 to 0.244 is a real change of camera; the first `same` is
at 0.137, an `s4-overexposed` frame pair inside one continuous car interior.
0.20 was discarding 21 real cuts and buying nothing at all.

0.14 clears the judgements too and is still rejected: it sits 0.003 from a known
false positive, which is a coincidence rather than a margin. **0.15 is the
lowest round value that is all-cut with room**, and
`tests/test_scene_threshold.py` pins it from both sides — nothing judged above
the floor is a non-cut, and every step up from it costs real cuts. The 59
judgements are checked in as `tests/data/scene_cut_judgements.json`, so the
number is re-derivable rather than remembered.

**What it changes is a framing number, not a detector one.** A cut with no
window is one the framing walks through, so on the film's own vertical
projection the stale share goes from 6.3% to **28.0%** of placed seconds, and
unframed cuts from 3 to 23. None of that is new damage: those 21 cuts were
always being walked through, and the floor was the reason nothing said so. It
also means `reframe_detect` now proposes a window per real shot rather than per
shot-that-scored-well, which is the half of § The three gaps, closed that
`steps` explicitly could not speak to.

The measurement ran against the deleted vertical cut, rebuilt from
`~/lucid-archive/vertical/lucid.json` plus the film's own transcript and media
— the archive earning its keep within the hour. The rebuild reproduces the
project exactly: 25 placements, 245.745 placed seconds, 35 cuts and 15.557
stale seconds at the old floor, all matching what the project on disk reported
before it was deleted.

**On the shipped teaser the re-pin surfaces exactly one stretch, and looking at
it is what the rule is for.** `s1996-randy` 4.546–6.673 (2.1s, 4.8% of placed)
is now reported stale: the cut at 4.546 scores 0.183, so the window from 1.960s
is held across it. Drawn on the frame, that inherited window is *fine* — it
centres the curly-haired woman and clips the man at its right edge, which is a
defensible frame for the shot. **`stale` is a structural fact — a window held
across a cut — and not a claim that the framing is wrong.** What the re-pin
bought here is a question attached to 2.1s that previously had none, which is
the whole point of a coverage number; it did not find a defect, and reporting
it as one would have been the third instance this week of a check's first run
being read as findings.

## What the re-pin did to the detector, and the number nobody reported — 2026-08-12

§ The scene threshold, re-pinned changed what `reframe_detect` sees on every
project, so it was run against the film's own vertical projection before being
believed. The floor at 0.15 gives **79 windows against 59**, and the 20 the
lower floor created behave like the ones that were already there: 17 proposed,
3 refused, against 8 refusals in the old 59 — a refusal rate of 15% either way.
So the extra cuts are not extra blind spots, which was the thing worth
checking: a refused window is worse than an unframed one, because whatever is
in force carries over and a stale window looks deliberate.

**The stacked split fired 10 times against the 3 the docs still claimed, and
almost none of that is new two-handers.** Six of the ten sit on windows the old
floor also had. The rule is unchanged — every sampled frame must hold subjects
one window cannot — and what changed is the *unit* it is asked about: three
moments spanning 8 seconds are far less likely to agree than three spanning 2.
**The split rule's measured strictness was partly an artifact of window
length**, and any number quoted as "N of 59" moves with the floor rather than
describing the film.

### The line a split is judged on was never in the output

CLAUDE.md has said since 2026-08-11 to judge a split on how much its panes
overlap — the film's separate at 23–24% and duplicate at 52–59% — and the tool
has never reported that number. It was computed by hand off the two rects,
every time, which is the same defect as a coverage check that reports a
boundary and leaves you to work out whether a cut explains it. Measured across
the ten proposals:

| overlap | windows | reading |
|---|---|---|
| 23–30% | 4 | distinct groups, one in each half |
| 40–45% | 2 | neither, and worth a look |
| 52–63% | **4** | the same face in both halves, twice on screen |

**Four of ten proposals are the duplicating kind, and three of those four
predate the re-pin** — this is not damage the new floor did, it is what the
pass has always offered with nothing saying so. `mlt.pane_overlap` is now that
number, on every `reframe_detect` window and on the `reframe_sheet` row that draws
one, where the lower pane is already dashed for exactly this judgement. It is
**reported and never enforced**, for the pass's standing reason: it proposes
and the sheet disposes, and a duplicating split is sometimes the least bad
answer for a shot one window cannot hold. What was wrong was making the
reviewer derive the number.

The two values in the test are real proposals off the film rather than round
ones, so the assertion is that the measure separates the cases it was drawn
from — a threshold that could not tell `s4-overexposed` at 7.632 from
`vi-bailey` at 19.937 would be worth nothing to whoever is reading the sheet.

## The gap that was never on the timeline — 2026-08-13

The head of the parity long tail was a measurement, not a build: *does a
timeline drag usually land on a gap a cut left?* PLAN.md § Three uncosted
parity items costed the drag gesture as UI-only **if** a timeline range
translates to the `(word_index, src_start)` pair `cue_add` needs, and said the
premise breaks on a drag landing in a gap — with "put b-roll over this
silence" named as a *likely* drag rather than an edge case. If most useful
drags landed there, the build was gap-anchored placement, a different and
unbuilt address space.

**The premise describes something that cannot happen.** `Edit` lays surviving
segments contiguously in timeline coordinates: a cut ripples and the hole
closes, which is why `_seams` reports a seam as a single *instant* with a
`removed` figure beside it rather than as a span. The film has **155.17
seconds removed across 64 ranges, and all 64 have zero width on the timeline**.
Sampled at 20ms over the whole 336.269s, not one instant failed to map back
through `Edit.source_spans`. There is nowhere for a drag to land inside a cut.

The real referent is a different thing that happens to look like it: a
**surviving pause**, real timeline duration between two surviving words with no
word under it. Measured against the film, using lucid's own
`ops.PAUSE_MARKER_MIN` rather than an invented floor, so the threshold is the
one the transcript pane already draws a marker at:

| | holes | seconds | share of the film | longest |
|---|---|---|---|---|
| all | 123 | 49.21 | 14.64% | 2.273s |
| ≥ `PAUSE_MARKER_MIN` (0.4s) | 55 | 35.93 | 10.68% | 2.273s |
| ≥ 1s | **6** | 8.17 | 2.43% | 2.273s |

Median visible pause: 0.54s. **Six pauses in a five-and-a-half minute film are
long enough to be a deliberate silence target**, and they total eight seconds.
"Put b-roll over this silence" is a real drag and a rare one.

### `cue_add` is in-point only, so only the start needs an address

The second correction is the one that decides the item. A cue carries no
out-point — the out is derived from the next cue through the edit, which is
§ The property everything below defends doing its job. So a drag needs its
**start** to resolve to a word and nothing else. Scoring both endpoints answers
a question `cue_add` does not ask.

Across 16,000 sampled drags at plausible b-roll lengths:

| drag | start addressable | both ends addressable |
|---|---|---|
| 1s | 86.2% | 73.2% |
| 2s | 85.4% | 73.3% |
| 3s | 86.8% | 74.6% |
| 5s | 84.9% | 71.8% |

**A timeline drag is word-anchorable ~86% of the time**, and the 14% is not a
missing address space — it is the same inter-word silence in the table above.
So gap-anchored placement is not needed, the third b-roll entry point is UI
work on the address space that already exists, and the residual is one rule
rather than one model: a start landing in a hole snaps to a surviving word.
Which direction it snaps is a UI call, and the 55 visible pauses are where it
will be judged.

The number that would have changed the answer is the one nobody had: had the
holes been most of the timeline, or had `cue_add` needed both ends, this would
have been a model change. Both were cheap to check and neither was checked
before the item was costed.

## The caption default resolved by coincidence — 2026-08-13

Queue item *vendor the caption font* was taken as "put the faces the presets
name where fontconfig finds them". Read against the box, the item had already
half-happened and nobody had noticed which half.

`captions.CAPTION_FONT` is `Outfit`, and it draws. What made it draw was
`~/.local/share/fonts/Outfit[wght].ttf`, **fetched months earlier by a sibling
repo's brand-art tooling for its own reasons**, before captions named the
family. Nothing in lucid put it there, nothing in lucid checked it was there,
and on a fresh box the caption default would have substituted silently with
`verify`, `check_frames` and `caption-view` all still clean. The default was
correct by accident, which is the same state as incorrect for anything that has
to survive a second machine.

### PLAN.md's own measurement of the old default was wrong

§ A default font records that all three presets named `DejaVu Sans` and "every
one of them draws as Noto Sans", on the strength of `fc-match "DejaVu Sans"`
answering Noto Sans. Measured by burning instead of asking: **a burn naming
`DejaVu Sans` is pixel-identical to a burn naming a family that cannot exist**
(RMSE 0), and both differ from a burn naming the literal string `Noto Sans` by
~4600. So the old default did not draw as Noto Sans. It drew as *the absent-name
substitute*, which is a third thing.

`ffmpeg -v verbose` says why, and it is the § The approvals round finding
again from the other side. `DejaVu Sans` and the impossible name are both
primary-picked to `NotoSansArabic-Bold`, both fail to find a Latin glyph, and
both fall back to `NotoSans-Bold.ttf`. The literal `Noto Sans` is
primary-picked to a **Nerd Font symbol face**, fails the same glyph, and falls
back to the same file. All three draw their visible glyphs out of one face —
what separates them is the **space advance**, still supplied by whichever
primary was picked before the fallback.

**There are two distinct flavours of wrong and they do not look like each
other.** That is what makes the obvious check useless: a probe scored as "does
this differ from font X's burn" scores two wrong answers as one right one.

### What was built

`src/lucid/fonts/Outfit[wght].ttf` and its OFL text now ship in the package,
byte-identical to the copy `branding.md` names as canonical on the NAS — the
same discipline `src/lucid/web/FONTS.md` already applies to the browser faces,
and deliberately a separate directory, because a `woff2` beside `app.css` puts
a face nowhere `fc-match`, libass or librsvg can see it. `fonts.install()`
copies it where fontconfig looks, resolving `$XDG_DATA_HOME/fonts` the way
`/etc/fonts/fonts.conf` resolves it rather than hardcoding a path, and compares
by **content** so a box that already has the face is left alone and no render
moves.

`fonts.probe(family)` is the check, and its shape is the whole point: it burns
the probe string twice, once under the family and once under a family that
cannot exist, and compares the pixels. Identical means the name is not drawing,
whatever `fc-match` says. Calibrating against the machine's own substitute
costs one extra frame and needs no stored reference, so it cannot rot and it
works for a family lucid does not vendor. An ink check guards the degenerate
case where both frames are blank and "identical" would otherwise read as fine.
Live: `Outfit` → `drew: true`, 14661 from the substitute; `DejaVu Sans` →
`drew: false`, 0.0, with the warning naming the failure.

Two things this did not close, named so they are not conflated with it. The
card templates name `Noto Serif` and `Lato`, both installed and both drawing
correctly — but neither is a brand face, and `font_report` cannot see that
because it only asks whether a declared stack resolves. That gap belongs to the
channel preset pack. And `fc-match` still cannot say which face drew: it and
the burn are reported side by side and neither is folded into the other.

One trap found and not taken: this box has genuine DejaVu TTFs inside the
Steam compat runtime. Fontconfig never reaches them, and vendoring from there
would tie a video pipeline's caption default to a gaming runtime Valve
re-extracts into ephemeral directories on its own schedule.

## The music bed, measured against a dumb control — 2026-08-13

PLAN.md § Music said the length premise was the thing most likely to be wrong
and could not be settled by inspection: *music is not indifferent to when it
ends, and a bed that loops past a natural beat is a worse defect than a picture
held one frame long.* So the queue item was a render and a listen, not a
design.

Two beds over the film's own render (`essay-cards-fixed.mp4`, 336.341s), on the
real Beltrami cues the video actually used, both landed at −16.1 LUFS / −1.05
dBTP with the same level discipline `music_bed.py` applies — 17 LU under the
VO, 9 dB sidechain duck, measured rather than guessed:

- **A, length-agnostic.** `-stream_loop -1` as an *input* option, trimmed to
  the film's probed total, fade-out at `total − 2.5s`. **No timecode is typed
  anywhere in the command.**
- **B, the dumb control** — built by invoking goodsometimes'
  `scripts/music_bed.py` completely unmodified, md5 verified identical before
  and after, with hand-typed cues: a person watches once, guesses "~5:36",
  picks a splice at 3:20, and types 136 for the remainder.

### The control lost on the one thing a machine can measure

**B's hand-typed length undershot the real remainder by 0.341s** — in a
careful, deliberate build, by someone trying. That is the v7→v8 lost-invocation
failure at small scale, and it was caught only because the render was measured
afterward. And **B's splice landed on live material** (−46.3 dB max across the
seam) where A's machine-anchored wrap landed in genuine hush (−91.0 dB max).

That is a result for the *property*, not for the mechanism, and the difference
matters:

**A's clean wrap is a property of this cue, not of looping.** *A Killer
Confrontation* has a 13.3s near-silent tail and a 3.06s silent head, so its
wrap happens to be silence-to-silence. A cue that ends or opens on live
material produces a click under exactly the same approach. Nothing here says
looping is safe.

And the defect the measurement *did* surface is structural rather than
acoustic: **a naive loop restarts the piece's own establishing material
mid-scene**, at 4:26 into ongoing narration, with the VO's own `silencedetect`
showing nothing there but ordinary sub-second speech pauses. No cover.

### What that leaves

**"Hold" satisfies the same property and avoids the restart entirely** — let
the cue run out once, fade against a probed total, and leave the rest of the
film with no bed rather than force a restart. Still no baked timecode, still
anchored to the end, and structurally incapable of the defect looping has. It
costs not covering the whole runtime with music, which is an editorial price
rather than a modelling one.

So the length-agnostic premise survives its first real test, and the *loop*
shape may not. Both are served for the listen that decides it; the numbers rule
out a click and cannot rule out a phrase defect, which is the whole reason this
item was a render rather than a design.

## The scale spike, half-run — 2026-08-13

The October scale spike wanted one long two-speaker recording through
transcribe → cut → render, to find where the pipeline groans while the format
can still route around it. **The recording exists and no lucid doc knew it
did**: 58m08s, 1920x1080, two separate AAC stereo streams — an OBS-style
dual-mic capture, 11.2× longer than anything lucid has run.

**Half the spike ran. The half that did not is the interesting refusal.**

### The transcribe half is blocked, and the blocker is a person's desktop

A 120s slice through `asr.transcribe` — the exact function `lucid transcribe`
calls — failed in 8.06s with `torch.OutOfMemoryError`, 102.56 MiB free of 11.53
GiB, because a game held 6013 MiB and an unrelated python process held 2014.
`asr.py`'s docstring is accurate: the real reason was buried several frames up
a CUDA traceback and the tail was correctly carried into the exception. Free
memory kept *falling* across the session, 2488 → 881 MiB, so this is contention
rather than a blip. **No GPU rate was measured and none is claimed.**

A CPU-only run of the same slice, explicitly not lucid's path, gives a floor
rather than a substitute: 303.88s for 120s of audio — **2.53× real-time, peak
RSS 4.86 GiB**, extrapolating to ~2.45h per stream. There is no historical
GPU-turbo timing anywhere in HISTORY.md to compare against, and that absence is
itself worth recording.

That run also found a defect nobody was looking for: **the single-pass
`asr.transcribe` has no hallucination guard.** It degraded into a repeat loop
near the tail — the failure mode `_drop_stacked` exists to catch in the
*windowed* path, which the ingest path does not use.

### What did run

| | measured | reads |
|---|---|---|
| windowing | 62 windows for the 310.9s VO → **697** for 3488.35s | linear in duration at 10s/5s; no blowup in the scheme |
| `melt` | 161.24s wall for the 336.269s film, **peak RSS 2.02 GiB** (1s `ps` polling, 157 samples) | 2.09× faster than realtime; matches HISTORY § 4's 2167 MB |

The melt figure is a **repeat measurement, not a confirmation** — it is the
same project at the same duration and source count that produced the original
number, so there is still no evidence whether RSS tracks duration or tracks the
22 concurrently-referenced sources. That is the biggest remaining unknown and
it is flagged rather than extrapolated. `RENDER_MAX_MEMORY` caps a blowup at 6G
regardless, so the 14.6GB incident's shape cannot repeat.

### The groan point is not where the item expected

The item listed cue-table size. `cue_add` is indeed O(n) per call — a full
duplicate scan plus a manifest read/write — so authoring is O(n²), which is
nothing at 38 entries and still sub-second at an estimated 150–450.

**`build_shots` is the one that compounds.** It calls `Edit.timeline_span` once
per cue, and `timeline_span` is an unindexed linear scan over every segment. So
it is **O(cues × segments)** and *both* grow with duration — plausibly 400 cues
against 1000–2000 segments — and it fires on every editing mutation through the
web UI's project-changed event, not on a poll timer.

### The two streams are a new `Edit` primitive, not a parameter

Everything lucid does assumes one speaker and one audio stream, and it is baked
in at **four** separate points:

1. `media.probe()` takes `next(s for s in streams if codec_type=="audio")` —
   literally the first. The second stream is never recorded anywhere.
2. `media.import_media()`'s re-import dedup is keyed on the source path alone,
   so importing the same container twice under two `clip_id`s to reach the
   second stream is a **silent no-op returning the first clip's record** — it
   actively blocks the obvious workaround.
3. `asr.transcribe` and `asr._to_mono_wav` hand ffmpeg the whole container with
   no `-map`, so **ffmpeg's automatic stream selection, not lucid, decides
   which mic gets transcribed.**
4. `Edit`/`Segment` address every timeline instant to exactly one `clip_id`,
   and `transcript.Word` has no speaker field. Both cue and description
   addressing are single-clip spaces by construction.

The third of those is the one that would have bitten silently: on this file
both streams are 2ch, the tie breaks on lowest index, and **stream 2 measures
2.2 kbps — one mic is effectively dead.** A spike that transcribed "the audio"
and reported a result would have been reporting one microphone without saying
so.

What a two-speaker recording needs is stream-aware `-map` at every probe and
ASR touch point, an import path de-duped by *stream* rather than by path, and
the genuinely new part: a way for the `Edit`'s single spine to say which
speaker is authoritative at each instant. That is the audio twin of the picture
cue, and it is a primitive rather than a parameter.

## Tail time, built — 2026-08-13

PLAN.md § Tail time — the design note recommended shape B and this is it: an
optional `tail` manifest key, `{"asset": "card:name", "seconds": …, "fade": …}`,
read by `export` into two ordinary MLT entries after the last frame. The defect
it closes is the one the wiki carried first — a bumper or end card applied
downstream of `export` is dropped by every derivation at exit 0, with `status`,
`verify` and `check_frames` all silent, because nothing in the project ever
knew.

**`mlt.py` needed zero changes, and that is worth stating rather than
assuming.** The note claimed a tail introduces "no new MLT concept at all"; on
the build that turned out to be literally true rather than true in spirit. An
`is_image` picture-lane entry is what a `card:` cue already becomes, and a
`has_video=False` audio-track entry is what an audio-only clip already is. The
tail reuses both paths exactly. The lane-covers-track invariant is satisfied by
appending the same frame count to each, so the check that would otherwise
refuse the tail never has to be relaxed.

The one helper the note insisted on is `ops._frame_total_with_tail`, and the
property that makes it safe is testable: **a project that has never touched
`tail` renders byte-identically**, `_tail_frames` being 0. A duration answered
two ways is the failure `check_frames` exists to catch and would otherwise now
be able to cause.

### The scope boundary nobody had noticed

**A tail can only be exported onto a project whose picture cue lane already
covers the whole film.** `mlt.document` requires exact coverage whenever a
picture lane exists at all, and a project with no cue table has no second lane —
its picture comes straight off the edit track's own `has_video` entries. There
is nowhere for a card to join without duplicating the entire film's picture
onto a lane just to make room for six seconds.

So `export` refuses that combination **by name**. It is a real boundary rather
than an oversight, and it does not block the two projects the item exists for:
the essay and the teaser both already carry full cue tables. But it means "add
a tail" is not universally available, and the refusal is where anyone finds
that out.

### What is stored and not yet drawn

`fade` is validated, stored and echoed, and **`export` cuts to the card hard at
`seconds`**. Drawing a real dissolve is a transition node — a new MLT concept,
which is exactly what shape B was chosen to avoid — so it is left for a later
pass using the same stored value. The frame arithmetic the note warned about
(`xfade` at `offset = DUR - FADE` finishing *at* `DUR`, so adding the fade to
the hold runs the tail long by exactly the fade) is pinned by a test named for
it, `test_a_tail_adds_exactly_seconds_never_seconds_plus_fade`, so the trap
cannot come back quietly when the dissolve lands.

`reel` reports `tail_dropped` beside `cues_dropped`. That call was taken before
the build and it is not a flag: a derivation carries nothing and says so.

The web UI still cannot see a tail, deliberately. Never draw a lane `export`
cannot produce — `export` learning to produce one is this step, and the view
learning to draw one is the next.

## The end card and the bumper became templates — 2026-08-13

Both specs were settled on a watch and lived **only in one-off proof scripts
outside the repo**, so nothing lucid could draw either one and no re-cut could
reproduce them. They are now `endcard` and `bumper` in `graphics.TEMPLATES`,
with real portrait variant files, ported from `make_endcard.py` and
`make_bumper.py`.

Every brand slot ships `default: ""`, and a test holds all four to it. `mark` is
an empty slot deliberately — a project supplies its own, `Name[em]*[/em]` — so
lucid stays generic and the channel's own values remain the pack's job.

**The port found a defect by rendering, which reading had not.** The bumper was
built first without a `footnote` slot, on the assumption that its mark was the
bare wordmark. Compared against `bumper-b.png`, it is the full lockup — the
script calls the same `lockup()` the end card does. That is a difference no
amount of reading the slot table would have surfaced, and it is the same
discipline that settles a caption font: compare the render.

Two honest differences from the hand-authored proofs, both consequences of
routing through lucid's generic vocabulary rather than baking brand geometry
into the tool: the asterisk draws **inline rather than superscript**, because
`line_markup` has no raise mechanism; and the type falls back to Noto Serif and
Lato rather than Zilla Slab and Outfit, as every shipped template does.

### Which card the essay's tail is, settled by rendering both

The build left this open: `endcard` is the `asis`/`norule` design the watch
settled, and PLAN.md § Tail time says the essay gets "bumper A's register at
16:9, mark only" — which reads like the `bumper` template with its lines left
empty. Two candidate cards for one tail.

Rendered, they are not close. `bumper` filled mark-only draws its **amber rule
with nothing underneath** — the rule is fixed markup, drawn unconditionally the
way the source script draws it, so it becomes a divider pointing at a missing
thing, the exact defect the end card was designed around. `endcard` filled the
same way is the lockup alone on ink, which is what "mark only" describes.

**So the essay's tail is `endcard`, and `bumper` is the register that has lines
under its rule.** That reading makes both templates coherent and makes the
orphaned-rule case one nobody has a reason to reach — which is why it stays
reported rather than fixed with conditional-rule machinery. It is still an
editorial call and Tyler has the last word; what changed is that it is now a
call between two rendered cards instead of two sentences.

### The inventory test caught the templates, and that is the check working

`test_card_new_from_a_template_over_the_wire` asserts the *exhaustive* set of
templates reachable over the wire, and adding two broke it. The expected set was
updated rather than the assertion relaxed: a template that ships without
reaching `card_new` is invisible to an agent, and one that reaches it without
being meant to is worse, so the `==` is the point. It is now commented to say
so, because the temptation on the next template will be to loosen it.

## The film check, and the repeat that was never lucid's to see — 2026-08-13

PLAN.md § Open questions has carried *how does a lucid project know it is the
film* since the Scream project turned out to be holding the silence-cut VO
rather than the shipped one — 411s against 351s, 72s of retakes — while the
render, `verify`, the cue table and the shot plan all agreed with it. Two
builds close the cheap half of it.

### `film_check` asks the question no other check can

`check_frames` is the closest relative and is **not** this. It asks whether an
export agrees with *this project's own* arithmetic, framewise — which it did,
cleanly, on the stale cut, because nothing in it compares the project to
anything outside itself. `film_check` asks the other question: does this
project's own answer resemble a *reference export's* at all.

Run against the two projects on disk, which is the only demonstration that
matters:

| project | `timeline_duration` | segments | `duration_delta` | `agrees` |
|---|---|---|---|---|
| `lucid-final-cut` (the film) | 336.269 | 63 | **−0.072** | true |
| `lucid-scream-v2` (the stale cut) | 410.963 | 73 | **74.622** | false |

**`FILM_CHECK_TOLERANCE` is 1.0s and both numbers above are why**, cited in the
constant's own docstring rather than reasoned about: the film's own delta is
frame quantisation plus container padding, two orders of magnitude below the
floor, and the stale cut's is two orders above it. A threshold with no measured
distance on either side of it is a guess.

**A segment count cannot be read back off a finished render at all** — once
encoded there are no cut boundaries left, only frames. So `segments` is
reported for the project side and `notes` says out loud why the reference side
has nothing to set it against. Inventing a number there, or quietly dropping
the field, would both have been worse than saying so.

The reference is **remembered, not just passed**: an additive manifest key on
the canvas/`caption_style`/`tail` precedent, so every later call — from a
script, from an agent that never saw the conversation — asks the same question
without the path being retyped. That is the fix the postmortem actually named,
because a caveat recorded in a results table is not a guard: nothing re-read
it.

### `find_repeats` is the mirror of `find_overlaps`, and neither subsumes it

The repeat-finder that caught the Scream retakes lived in goodsometimes'
`vo_windows.py`, outside lucid, and was run by hand. It is now
`transcript.find_repeats`, surfacing a `repeats` finding beside `overlaps`
wherever a transcript is attached or re-checked.

What makes it worth having beside the seam scan rather than instead of it is
that **the two see opposite halves of the same defect**. `find_overlaps` finds
a retake whisper *swallowed* — hidden inside the inflated duration of the word
after it, detectable only because a word starts before the one ahead of it
ends. `find_repeats` finds a retake that survived transcription as **distinct,
cleanly-timed duplicate words**, which is exactly the case the seam scan cannot
see, because there is no seam. A transcript can carry either shape and the
docstring says so rather than implying the pair is exhaustive.

`transcript-checks` is still how an older project asks: a finding is computed
at attach and returned once, so the Scream VO — attached long before either
check existed — could never have seen them from its own project.

What is not built *in this pass* is the third item, a real `.kdenlive` import,
which is also most of what Elf needs. It was scoped out rather than attempted —
and then built the same day: § The import that was one frame short, sixty-three
times, below. Read that before believing this paragraph.

## The keyframed move — 2026-08-13

Queue item *the keyframed move* was costed as **authoring only**: § Per-shot
framing had already paid for the mechanism, since the writer emits keyframes
and MLT's `=` interpolates where `|=` steps. That costing held. `mlt.py` grew
one field and no new node, and the whole build is a flag deciding which of two
operators an existing key gets.

**The one thing that was not obvious is which key.** A window asking to slide
in is naturally written as a property *of that window*, and the natural
implementation puts `=` on that window's own keyframe. That is wrong, and it is
wrong in the way this repo keeps meeting: it produces a document, renders at
exit 0, and looks like a window that steps.

### Measured on the film's own case, not on a fixture

`~/lucid-kf-probe` carries one flag — `interp` on `s4-reveal` at src **7.3428**,
whose predecessor at src 6.0477 sits 410px to its left (x 520 → 930, both 450
wide). That is the test case the queue item named, chosen because a wrong answer
there is a framing defect somebody already watched, and `s4-reveal`'s eight
windows in the probe are identical to the shipped teaser's eight — same
in-points, same rects — so the move under test is the film's own.

**The probe is not the shipped teaser, though, and calling it one would break
this queue's own control rule.** It is `framed-teaser`, a different derivation:
reel span `[95.429, 139.92]` against the teaser's `[95.4, 139.8]`, no card
records, no `unspoken` marks, and one fewer `s1996-billy-stu` window framed
differently. Its two renders are a valid A/B *of each other* — that is all the
measurement below needs, since they differ by one flag and nothing else — but
neither is a control for the file on the NAS, and the pair must not be served as
one when the watch happens (§ The bumper the teaser never had). Discovering that
took comparing the two manifests, which nothing does automatically; it is the
fourth time a probe or dogfood project has turned out to be a neighbouring cut
(§ The VO the project was holding).

Two renders, differing only in which of the pair's two keys carried `=`,
compared frame by frame across all **1067**:

| timeline frames | PSNR | what it is |
|---|---|---|
| 1010 of 1067 | `inf` — bit-identical | the rest of the film |
| **749–778** (30) | **16.35–26.97 dB** | the move |
| 742–748, 779–798 (27) | 53.07–63.43 dB | encoder residual |

The keys land on source frames **145 and 176** (6.0477 and 7.3428 at
24000/1001). Strictly between them are exactly 30 frames, and exactly those 30
are the ones that moved. **The span that changes is the one *leaving* the
earlier key, and it ends at the flagged key rather than beginning there.** Had
MLT interpolated the segment arriving at a key, those same 30 frames would have
been identical and the divergence would have sat *after* frame 176.

The 27 frames at 53–63 dB are worth naming rather than rounding away, because a
looser threshold reads them as part of the finding and they are not: they are a
37 dB step up from the divergent span, they bracket it on **both** sides —
which causal prediction cannot do and B-frames referencing in both directions
can — and they end at frame 799, where the encoder's next clean reference makes
the two files bit-identical again. They are h264 remembering, not MLT framing.
Sampling this comparison at any single threshold would have merged the two.

Which of the two renders travels is not inferred from the numbers: side by
side, the unflagged render holds its crop on Sidney and hard-cuts to Ghostface's
shoulder exactly at the later key, and the flagged one is already panning across
the same timestamps, crossing between the two subjects mid-span.

So the flag names the window a move **arrives at**, and the writer puts `=` on
its **predecessor's** key. `rect_property` does that lookup rather than the
caller, because the alternative is an off-by-one whose only symptom is a hold.

### Two refusals that are the same fact twice

**The head can never carry `interp`.** There is nothing before frame 0 in the
source to slide from, which is the same sentence as there being no earlier key
to flag. `mlt.Reframe.__post_init__` refuses it, `ops` refuses it at the call
(`at <= 0`), and `_reframe` refuses a manifest that has one hand-edited in —
three layers because a bad flag would otherwise write a document and exit 0.

**A split cannot slide.** A stacked split is two nodes drawing two rects, and
only one of them would be interpolated: `pane_rect_property` has no `interp` of
its own, so the halves would travel out of step and show the seam moving. Both
the dataclass and the op refuse the combination by name.

Everything else is unchanged by construction. `interp` is empty on every
project that has never used it, an empty set writes `|=` on every key exactly
as before, and a project that never touches it renders byte-identically.

### The sheet had to learn what a moving window is

`reframe_sheet` is where framing gets judged (CLAUDE.md: never on a watch), and
it would have reviewed this wrong. Its tiles sample a stretch at fixed
fractions and draw the rect `crop_at` reports there — but `crop_at` only knows
the discrete window governing a source instant, so all three tiles would have
drawn the **departure** rect and the row would have read as a static window.

That is the exact mirror of § The tile that made a wrong window look right: that
one was a still rect whose sampled instant flattered it, this one is a moving
rect the sampling cannot see move. Both are the sheet reporting a window that
the render does not hold.

A sliding row is now drawn as its own case — evenly spaced fractions
**including both ends**, `_lerp_rect` standing in between them, the dashed
overlay carrying the *other* end (the target while travelling, the origin once
arrived), and the row reporting `sliding` and `slides_to`. `_lerp_rect` is a
straight line and says so in its docstring: it is exact at the two rects MLT
actually holds as keys and an approximation of melt's curve between them, which
is what a review tile needs and is not a claim about the render. A sliding row
also forces a **two-tile floor** — the montage is a fixed grid, so a row that
cannot show both ends is refused rather than drawn short.

### What this does not settle

Whether the move *reads*. Everything above is geometry: the right pixels travel
over the right 30 frames. Whether a 410px follow across 1.3s looks like a
camera operator or like a slide is a watch, and the two crops at that moment
hold near-featureless dark — which is the second half of the wiki's own note on
this window and the reason it was queued with a watch attached rather than
closed on a number.

## The import that was one frame short, sixty-three times — 2026-08-13

The third build of the film-check queue item, and the one scoped out of the
first pass: a real `.kdenlive` import. `seed_timeline` lays a clip down and
lets auto-editor find the cuts; `import_edit` takes a cut somebody already made
by hand in Kdenlive. PLAN.md § Open questions names the gap — the Scream retake
pass was done in Kdenlive, and bringing it back meant "63 ranges parsed out of
the `.kdenlive` playlist and written straight to `Edit`, which is not a
supported path — it bypasses `cut` and its history entirely".

**Building the supported path found that the hand-rolled one was wrong, and by
how much.** Run against the file HISTORY named all along, `Scream VO v2 -
retakes trimmed.kdenlive`, the importer reads **63 ranges** — the same count —
totalling **338.367s**. The project that shipped holds **336.269s**. The
difference is 2.098s, which is **63 frames: exactly one per range**.

### Which number is right is not a judgement call

`out` is the last frame *index*, so a range's exclusive end is `out + 1`, and
the hand-parse read `out` as exclusive. Three independent measurements say so,
and none of them is a reading of MLT's documentation:

1. **The document says so about itself, three times.** `producer0`'s `length`
   and both tractors' `out` all read 00:05:38.367 — 10151 frames — which is the
   inclusive sum to the frame. The exclusive sum is 10088.
2. **auto-editor emits the same cut in two formats.** `--export v3` gives
   `dur` 67/103/97 for three segments that `--export kdenlive` writes as
   (0, 66), (114, 216), (264, 360). `out - in + 1 == dur` on all three, and
   lucid already trusts `from_v3`.
3. **Adjacent entries butt up under one convention and not the other.** A pair
   written `out=00:00:46.900` then `in=00:00:46.933` is contiguous if `out` is
   inclusive and leaves a one-frame hole if it is not.

So the shipped film is one frame shorter than the Kdenlive cut at the end of
every one of its 63 segments. **This is a finding, not a repair**: 33ms at a
boundary that was already a silence trim is very unlikely to be audible, the
film has been watched and is on the NAS, and re-importing it would change a cut
Tyler has approved. What has changed is that the number is now knowable.

### The check that would have caught it is the one nothing had

Every individual range in the misread document is plausible. The sum is the
only thing wrong, and it is only wrong against something the file says about
*itself* — which nothing was reading. `mlt.declared_length` reads those
self-declarations back and `import_edit` reports them beside its own total, with
`declares_otherwise` naming any that disagree. It is the reading-side twin of
`declared_frames`, and deliberately a separate function: this module writes bare
frame numbers and Kdenlive writes timecodes into the same attributes, so folding
them together would teach the writer's own check to accept a spelling it should
never see.

### What it refuses, and why refusing is the feature

Run over all fourteen `.kdenlive` files in the Scream project directory, four
refuse and ten import. Every refusal is one of the assemblies, and the reason is
the right one: **`playlist0` and `playlist2` carry different cuts.** Those files
have a real picture track over the VO, and lucid's timeline is one track with
A/V linked — there is no shape to import them into. Preferring a track would
have imported half of somebody's edit and reported success, which is precisely
the failure mode the whole queue item exists to end, so the disagreement is
named instead.

A `<blank>` is refused for the same reason this module never writes one: it is
real runtime with nothing under it, and `Edit` lays segments contiguously, so
importing one would close the hole silently and make the timeline shorter than
the file it came from. No real file in the set has one — the rule is there
because MLT's format allows it, not because Kdenlive uses it.

Two things it does rather than refuse. A range overrunning its clip's registered
duration is **clamped and named** in `overshot`, which is not a rare case:
auto-editor's own exports overshoot the tail by exactly one frame, in `v3` and
`kdenlive` alike. And unregistered media is **named, all of it at once**, never
imported behind the caller's back — an op that reached ffprobe, wrote the
manifest and replaced the timeline in one call is a worse thing to own than a
second command.

### The other cut the reader confirms

`Scream VO v2 - silence cut.kdenlive` reads **73 ranges, 410.967s**. The stale
project § The VO the project was holding is about held 73 segments and
410.963s. The importer identifies the wrong cut as precisely as it identifies
the right one, from the outside, which is the property that makes it worth
having next to `film_check` rather than folded into it.

### What it is routed through, and why that is most of the fix

`_save_edit`, like every other mutation — so the timeline an import replaces is
snapshotted first and the import is undoable. That is the half of "not a
supported path" that had nothing to do with parsing. `plan` matters more here
than on an additive op for the same reason: this one replaces a timeline
somebody may have spent a day on.

Not built: merging adjacent entries that Kdenlive split without cutting
anything. The rule is real — `next.in == prev.out + 1` is one continuous span
in two `<entry>` elements, and counting it as two reports a phantom cut — but
none of the fourteen real files has a single instance outside the assemblies
that already refuse, so it is a guard with no measured case behind it. It is
written down here rather than built.

## The essay's end card went into the project — 2026-08-13

PLAN.md § Tail time's call 1 — *does the essay's project get a tail at all, or
does the card stay a finishing pass?* — was Tyler's, and it is **taken: it gets
a tail.** Call 2 was already settled (a derivation inherits nothing and reports
`tail_dropped`), so the note has no open calls left.

`~/lucid-final-cut/proj` now holds `card:outro` — the `endcard` template, mark
and footnote only, at the project's own 1920x816 — as a 6s tail, and
`essay-with-endcard.mp4` is rendered from it. `status` went 336.269s → an
`expected_duration` of 342.342, which is the point of the whole item: the
project is now the thing that knows the card exists, so a reel derived from it
either keeps the card or names it in `tail_dropped` rather than losing it at
exit 0.

### Three things the doing of it corrected

**The footnote in the standing write-up was the tagline, and `branding.md`
forbids it there.** The command as written passed
`footnote=[em]*[/em] movies are good sometimes`; § The end card had already
ruled that out on a watch, because near the wordmark the tagline *is* the
footnote and drawing both tells the joke twice. What shipped is
`[em]*[/em] Sometimes` — the mark whole, which is the register the watch
settled.

**A card is authored at the canvas, so the font has to be asked for.** The
template's `title_font` defaults to Noto Serif; the brand is Zilla Slab Bold,
which the project's twelve receipt cards already override to. `card new`
reported `drawn: Zilla Slab, drawn_style: Bold` with no warnings — the report
comes from a render, which is the only way this has ever been settled
(§ The approvals round, answered).

**The render was checked in the pixels, not in the status line.** 8208 frames
expected and 8208 in the container, `agrees: true`, 342.357s — and then a frame
pulled at 339.5s to see the card itself, because § The film had no captions in
it is exactly the failure of believing a manifest about what a file contains.

**And that check, run again over the body of the film rather than over the
card, found the thing it is named after.** `essay-with-endcard.mp4` carries **no
burned captions** — sampled at 10s, 62s, 150s and 250s, nothing at any of them,
while the same frames of `essay-cards-fixed.mp4` are bare too. So this is not
something the tail dropped: **no `export --render` of this project has ever
carried captions**, and the only captioned essay artifact on disk is
`out-karaoke.mp4` from 2026-08-10, three days and several cards older than the
cut. `captions --burn` is a separate opt-in step and nothing reports a render
made without it, which is the whole of § The film had no captions in it — met a
second time, in the same project, by the same route, four days later. The
teaser did get its burn back (§ The three served answers); the essay did not,
and the difference was invisible in every number either render reports.

## The three served answers — 2026-08-13

`~/lucid-review/` served the three calls the completion queue was holding — two
renders each for the music and the moving crop, one still for the wrong crop —
with the answers as buttons writing to its own `decisions.json`. All three came
back within a minute of each other, which is the argument for serving a
decision rather than describing one.

### The music bed: the loop lost, and the reason is not length

**"A sounds wrong. I liked B more."** § The music bed, measured against a dumb
control had ruled out a click and could not rule out a phrase defect, and named
the candidate: a naive loop restarts the piece's own establishing material at
4:26, mid-narration.

But the finding is larger than the loop shape, and it is in
`goodsometimes/ideas/scream.md` rather than in either render: **the control is
not one bed, it is an arrangement.** *A Cruel World* opens and closes and *A
Killer Confrontation* carries 1:31→4:08 — two cues placed against the film's
structure. A was one cue looped. So the listen did not choose hand-typed over
computed; it chose an arrangement over a loop, and no length-handling makes one
looped cue into two placed ones.

**What that settles:** nothing gets built on the loop, and the length-agnostic
*premise* is not what was refuted — it was never the thing being heard. If
lucid gets music it is cue **placement**, in the shape the cue table already
has for picture. The "hold" variant § The music bed proposed remains unbuilt
and is now beside the point.

**And the page mislabelled A.** It described the bed as "holds, then fades",
which is the *other* candidate shape; the file loops. He judged the audio, so
the answer stands — but a served page describing the artifact wrongly is the
served-review version of trusting a status line, and it is worth the same
suspicion.

### Both framing calls went onto the shipped teaser

The probe renders were `framed-teaser`, a different cut, which is why the
standing write-up carried that caution. **The window turned out to be identical
in both** — `s4-reveal` src 7.3428, rect `930,0,450,800` — so authoring the
approved move onto `~/lucid-teaser/proj` was `--interp` alone, not a rebuild.
`reframe_sheet` draws it as `slide-from` / `slide-0.50` / `slide-to` rather
than as face offsets, so the review tool reports a slide as a slide.

The wrong crop moved 780 → 1010 across the frame at src 11.0527, centring the
subject over the 1.627s she is on screen. **The sheet's own number went 274 →
44** — and the render was checked as well as the sheet, one frame out of each
of `teaser-v3.mp4` and `teaser-v4.mp4` at the same timeline second, because the
sheet reads the manifest and only the file says what shipped.

`teaser-v4.mp4` rendered at 1065 frames expected and 1065 delivered, with
captions burned back through `captions --burn` at the project's own karaoke
style — a render made without that step carries none and nothing reports it
(§ The film had no captions in it).

## The essay still had no captions, and burning them is a choice — 2026-08-13

§ The film had no captions in it is three days old and the essay had not been
fixed by it: `essay-with-endcard.mp4` and `essay-cards-fixed.mp4` are both bare,
so **no `export --render` of `~/lucid-final-cut/proj` has ever carried
captions** — the project resolves 178 cues and renders none of them, at exit 0,
with `status`, `verify` and `check_frames` all silent. That is the documented
hole doing exactly what the note says it does, in the same project, to somebody
who had read the note.

**The row it opened said "needs `captions --burn`", and rendering it proved
that wrong.** Both burns exist now and both carry captions in their pixels, and
the choice between them is editorial rather than mechanical, because *this*
film's cards are themselves text on cream:

- the stored `karaoke` style is white with a 3px outline — **1.10:1** against
  the card, held together only by the outline, which is why it reads as heavy
  beside the card's own typography;
- `--preset boxed` buys **20.87:1** and is legible over every card, but it is a
  preset rather than a box switch and **drops the per-word amber highlight**.
  Box *and* highlight is a third render nobody has made.

So the queue item is not "run the command", it is a watch — served beside the
re-cut teaser. **A one-command row is the shape a defect takes before anyone
renders it.**

## The ingest path's hallucination guard — 2026-08-13

The scale spike left a one-line row: `asr.transcribe` has no hallucination
guard, because `_drop_stacked` runs only in the windowed path. **Wiring that
same rule across is the obvious fix and it is not sufficient**, which is only
visible because the spike's own artifact was still on disk
(`~/lucid-scale-spike/cpu_out/slice_stream0_120s.json`) and got read rather
than believed.

The failure is eight words in the last 0.20 s of a 120 s slice — an echo of a
sentence from twenty seconds earlier, followed by nine empty segments:

```
119.7800-119.7800  people      119.8800-119.9400  people
119.7800-119.7800  were        119.9400-119.9400  of
119.7800-119.7800  really      119.9400-119.9800  you
119.7800-119.8800  well        119.9800-119.9800  know
```

**Only the first three share an instant.** `_drop_stacked` drops those three
and leaves five standing, which would have shipped as a fix and closed the row.

### The number that separates them is a count, not a rate

The obvious second signal is words per second, and it does not work: over three
consecutive words the *real* Scream VO reaches 50 w/s, because whisper's word
durations are not to be trusted (CLAUDE.md) and a zero-width word makes any
rate meaningless. Over six it separates, but six is longer than some real
hallucinations.

Counting words inside a fixed window separates cleanly at the first thing
tried. Across every transcript on this box — three copies of the 1150-word VO,
the 941-word essay verify pass, the 118-word teaser — **the largest cluster
inside 0.25 s is 3 words**. The spike's loop holds **8**, and the cluster is
exactly the eight hallucinated words with no real one either side. A floor of 5
sits two clear of both. `asr.CLUSTER_WINDOW` / `CLUSTER_WORDS` carry the
numbers; `_drop_dense` is the rule and `clean` is both rules together.

Swept over all 22 real transcripts on disk, `clean_payload` touches exactly one
file — the one holding the loop — and drops exactly its 8 words. The
identical-instant rule is kept rather than replaced: it is not a subset (three
words on one instant is under the cluster floor) and it has its own zero false
positives over the same 22.

### What it is wired to, and what it says

`asr.transcribe` now returns its payload through `clean_payload` and stamps
`hallucinated_words` on it, so `ops.transcribe` and both single-pass ASR
callers in `verify`/`unspoken_detect` report the count the windowed pass has
always reported. The guard is applied and *named*, because a transcript quietly
shortened is worse than one visibly repaired — every cut and every cue is
addressed against it afterwards.

`clean_payload` works on whisper's JSON rather than on a parsed transcript,
because that is the only place a single entry point can sit: the parse is the
last common step before three callers diverge. It rewrites a touched segment's
`text` from its survivors, so the payload never states a sentence it no longer
holds the words for, and it leaves an entry with unusable timings alone —
`parse_whisper` refuses those by design and dropping them here would take the
refusal away.

## The scan the spike named was not the one that costs — 2026-08-13

The same row projected `build_shots` as the pipeline's groan point: O(cues ×
segments), 400 cues against 1000–2000 segments, on every web-UI mutation.
Measured, that case is **25 ms**. It is not a groan point and never was.

The cost is in the same method with a different caller. `Edit.timeline_span` is
called once per *cue* by `build_shots` and once per *word* by `captions.place`,
and the word product is far larger: 6000 words over a 2000-segment edit is
**0.39 s**, and a silence-cut hour (10000 words, 6000 segments) is **2.03 s**,
per mutation. The film as it stands is 63 segments and never noticed.

`_SpanIndex` is the fix: per clip, that clip's segment bounds and the timeline
offset each one starts at, cached on the `Edit`. Measured against the walk it
replaces — 9.5x on the film, 55x on the projection the row actually named, and
**520x** on the hour, which goes 2.03 s to 3.9 ms.

Two things it is careful about.

**The bisect's precondition is not "sorted".** Two segments of one clip may
overlap in *source* — the same footage placed twice, which `import_edit` can
produce from a `.kdenlive` — and then an earlier, longer segment is the first
overlapper while a bisect on starts walks past it. The precondition is sorted
**and disjoint**, recorded per clip, and a clip that fails it gets the exact
linear walk. `tests/test_timeline.py` holds index and walk to each other over
random edits, and asserts each branch is actually reached: a parametrisation
where both cases fall down the same branch would pin the bisect to nothing.

**A cached index over a changed timeline would answer confidently and
wrongly**, which is this repo's worst failure shape. Assigning `segments`
therefore drops the index — through `__setattr__`, so the dataclass field stays
a field — and `restore`, which used to splice in place with
`self.segments[lo0:hi0+1] = own`, the one mutation that would have slipped
through, now rebinds instead. `timeline_time` reads the index's
arrays but walks them exactly rather than bisecting, because a zero-width
instant on a closing boundary is the one lookup whose answer does not follow
from an overlap test, and that is precisely what `closed_end` exists for.

## The flash in-points, answered against the essay — 2026-08-13

The last thread of § The keyframed move: five shots named by eye as opening on
a flash of the wrong picture, one of which survived scoring, and four that
would have been guesswork. The queue's own note had already found that the
scoring ran over the deleted vertical cut; on the essay the placements turn out
to be **the same 25 at the same timeline positions**, so the findings land
directly and the sheet is the essay's own.

**The score could not tell a flash from a fade — so the question was moved to
the source.** A flash is an in-point sitting the wrong side of a camera cut, so
`media.scene_cuts` on the *asset* answers it directly: is there a cut just past
where this shot starts reading? A fade-up from black has none. Three placements
have a cut within 0.40 s of their in-point and **two of the three are at offset
0.000** — the in-point sitting on the cut, which is where it should be. One is
not:

| | offset | scene | head/settled |
|---|---|---|---|
| `vi-richie-1` | **+0.124 s** | 0.53 | 62.6 |
| `cold-open-4` | −0.001 s | 0.264 | 11.1 |
| `s3-reveal-2` | −0.000 s | 0.173 | 6.6 |

So **one placement of 25 has the fault, and it is the one the old score already
separated.** The signal's real work is on the other four: the high scorers
(`s1996-billy-stu-3` at 33.5, `s4-overexposed-1` at 28.9, `cold-open-5` at
27.2) hold no source cut in their opening at all, so what the score sees is
movement or light. `cold-open-1` — the film's own fade-up from black, which the
old scoring ranked third — is answered correctly for the first time.

**The fix is three frames.** The asset is 23.976 fps; frames 0, 1 and 2 are the
previous shot and frame 3 is Richie, which is the "three-frame head" the review
named, confirmed frame by frame off the source. The cue is pinned at **0.125**
— frame 3's own pts is 0.125125 and `plan_picture` rounds `pin × rate`, so any
pin in 0.104–0.146 lands on frame 3 and 0.125 is dead centre of that. A frame
of tolerance, never an epsilon.

Re-rendered as `renders/essay-flashfix.mp4`: `check_frames` agrees at 8208
frames with delta 0, the tail survives, and sampled at 26 points the picture is
**byte-identical to the previous render everywhere outside the two `vi-richie`
shots** — inside them it has moved by exactly the three frames asked for, the
second shot's unpinned cursor carrying the shift as designed. The other 24
placements are on a served sheet at `~/lucid-flash-review/` (8804), each with
its opening frame, its settled frame, and what the source says.

## The flash in-points, watched — and a second one, caught by eye — 2026-08-13

The 24-shot watch came back the same day, and the answer on record ("all")
still does not survive contact with the evidence — but it undercounts by one,
not four. Of the 24, 23 were **looks fine**, agreeing with the source-cut
signal on every one. `s1996-billy-stu-3` was marked **opens on the wrong
picture** — the one the signal itself had called clean, no source cut inside
its opening.

**He was right, and the scan's own margin explains why it missed it.**
`media.scene_cuts` on `s1996-billy-stu.mp4` finds a real cut at source
21.354 s — but the placement's in-point is 20.896 s, **0.458 s** earlier, and
`flash_scan_essay.py`'s `CUT_REACH` only looked 0.40 s past an in-point before
giving up (deliberately short, per its own comment, so a cut a second later
reads as the shot doing its job rather than a flash). This cut landed 0.058 s
past that window — not absent, just outside where the scan was told to look.
Confirmed frame-exact off the source at 23.976 fps: frame 511 (21.313 s) is
still Billy screaming, frame 512 (21.355 s) is Sidney's face, and
`media.scene_cuts` had already found that boundary (21.353958, score 0.266)
without anyone reading past `CUT_REACH` to notice.

**The fix is the same shape as `vi-richie-1`'s: pin the cue.** The placement is
`cue_add(vo, 866, s1996-billy-stu, src_start=...)` (word "It's"); `cue_rm` then
re-`cue_add` at **21.35** lands `plan_picture` on frame 512 exactly
(`src_in: 512`, `src_start: 21.354667`) — dead centre of that frame's own
rounding window, the same tolerance-not-epsilon rule as before. Re-rendered
over the `vi-richie` fix (not from the original): `export --render` reports
`agrees: true` at 8208 frames, and sampled at 30 points against the prior
render the only difference is inside this shot's own span — everything else,
including the `vi-richie` fix already in place, is byte-identical. The prior
render is kept as `essay-flashfix-v1-vi-richie-only.mp4`;
`renders/essay-flashfix.mp4` is now both fixes.

**So the completion queue's flash-in-points item was closed one shot early.**
Two of 25 had the fault, not one — the second was invisible to the signal by
5.8 % of its own search window, and visible immediately to a second watch. The
scan script is a one-off probe outside the repo (like `vo_windows.py`), so
nothing in lucid itself changes; the lesson is for whoever reads it next: a
fixed reach past an in-point is itself a claim, and this one was 0.058 s too
short to hold on a slower dissolve than the one it was tuned against
(`vi-richie`'s cut, at +0.124 s, well inside 0.40 s). Served results, including
the fix, are on the same sheet.

## The essay's captions: none, and the teaser is v4 — 2026-08-13

Both remaining calls on `~/lucid-review/` (8803) came back. **Captions: none.**
Neither the outline (1.10:1, illegible without its outline) nor the box
(20.87:1, drops the karaoke highlight) — YouTube's own subtitles carry it
instead, so the essay ships with none burned in, and the queue's captions row
closes as a deliberate choice rather than a defect. No render changes: this is
the state every export of the project has already been in.

**Teaser: keep.** `teaser-v4-captioned.mp4` — both framing calls already
authored onto it (§ The three served answers) — is confirmed as the one to
publish; the older renders (`v2`, `v3`) stay on disk, untouched, not deleted.

## `lucid review`, built — 2026-08-13

The completion queue's item 6, closed the same day it was designed: renders,
sheets and A/B members now register into an additive `review` manifest key
(`ops.review_add`/`review_verdict`/`review_list`, mirrored as MCP tools and
`lucid review add/verdict/list`) — no schema bump, the `tail`/`caption_style`
shape.

**The rule the round that went wrong exists to enforce is now structural,
not a comment.** `review add --kind control --baseline <name>` hashes both
files and refuses the call outright on any mismatch — the bumper incident
(§ The bumper the teaser never had) was a page that labelled a *different*,
later render a control; here that page cannot exist, because the item is
never registered.

**Loopback+Host, `webui.py`'s own guard, does not fit a server built to be
reached off the machine.** `lucid review serve` (`reviewserver.py`) is meant
to be watched from a phone on Tailscale, so a random token
(`secrets.token_urlsafe`, compared with `hmac.compare_digest`) stands in
instead — every request, GET or POST, carries `?t=`, and the one line printed
at startup is the whole credential. The blast radius is smaller than
`webui.py`'s too: the only mutation this server can cause is a verdict string
against an already-registered item, never an edit.

**Streaming reuses `webui.py`'s Range math rather than a second copy of it.**
`_stream_file` was a bound method with no way to import it, so it came out as
a standalone function (`webui._stream_file(handler, source, head_only=...)`),
the `_ranges`/`_json_body` shape the file already had. `webui.py`'s own test
suite (87 tests, same pass count before and after) confirmed the refactor
changed nothing about how it serves media.

Verified against a real socket, not just green tests: no token → 403, correct
token → 200, a `Range: bytes=` request → 206 with the exact byte slice, a
mismatched control refused with both sha256 prefixes in the message, and an
older project with no `review` key still opening clean through
`Project.open`.

## The window learning to place a cue — 2026-08-13

PLAN.md § The completion queue, item 10: the third b-roll entry point,
drag-select on the timeline (DAYDREAM.md's "right-click-drag on the timeline
selects a range"). Its premise was already settled by measurement
(§ The gap that was never on the timeline, below): 85–87% of drags land
directly on a word, the rest are inter-word silence with a 0.54s median gap,
and only a drag's *start* needs an address because `cue_add` is in-point
only. That finding is what made this small — no gap-anchored address space
to build, just a snap onto the word-index one `Edit` already has.

**Nothing in `Edit`'s addressing changed, and nothing needed to.**
`timeline.js` already drew a selection box (`drawSelectionHighlight`) off a
`'selection'` bus event `{indices: [...]}` that nothing had ever emitted —
dead code since the tier-3 rebuild, commented "speculative." The gesture
built here is the first real emitter: `handleLanesMouseDown`/`Move`/`Up`
resolve pixel position to timeline seconds to a word index via
`nearestWordAt`, a client-side mirror of `ops._nearest_word` (overlap test
first, nearest-by-edge-distance fallback) over `state.words`'s own
`timeline_start`/`timeline_end` — the client already had that array for
drawing, so no server round trip is needed to place the highlight live
during a drag. A plain click with no movement is left alone entirely
(`seekOnClick`'s existing `'click'` listener still owns it); a real drag
sets a flag that a capture-phase `'click'` listener on `#track-lanes`
swallows, so the native click a mouseup can still fire never also seeks.

**The confirm step is a free-text asset field, not a picker, and that was
the one real design call.** The next item on the same list is the assets
pane — drag-and-drop from a library of clip_ids and cards — and it does not
exist yet. Building a picker now risked throwaway UI once that pane ships,
so the floating toolbar (reusing `.selection-toolbar`'s CSS, the same class
transcript.js's Cut/Restore bar uses, for visual consistency without
importing between pane modules — which this repo's pane contract forbids)
just takes a typed `clip_id` or `card:name` and posts straight to a new
`/api/cue`, a fourth caller into `ops.cue_add` alongside the CLI and MCP
tool. The gesture and word-resolution logic — the actual hard part — are
not throwaway regardless of what the picker becomes.

`webui.py` gained one route, `_cue_add`, mirroring `_cut_at`'s shape exactly
in `_POST_ROUTES`. Three new real-socket tests in `test_webui_http.py`
cover it (a cue lands in the manifest at the right word, a duplicate word is
refused, a missing asset is refused) — 91/91 pass. A live server check
against a throwaway project confirmed the whole path end to end: static
`timeline.js` served with the new functions in it, `POST /api/cue` placing
a cue, and the duplicate-word refusal surfacing through the same
`WebUIError`/`TranscriptError` handling every other route uses.

**What this session could not verify: the drag gesture itself, in a real
browser.** `lucid web` binds loopback only by design (CLAUDE.md), and no
browser automation was available to this session. The backend is proven;
the pointer math, the toolbar's positioning, and whether a real drag feels
right are not — CLAUDE.md's own rule (headless Chrome does not composite
what a person would see) applies here as much as it does to the picture
layer. Needs a real-browser pass before this item is fully closed.
