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
