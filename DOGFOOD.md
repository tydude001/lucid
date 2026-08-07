# Dogfood — what the first real video taught us

Milestone 7's output. lucid cut the voiceover for the goodsometimes Scream
essay on **2026-08-07** — its first job on material somebody actually intends
to publish — and the video was assembled, rendered and verified around it.

This is the pain-point list that milestone says to promote into the plan. It is
written for whoever picks lucid up next; the evidence lives in goodsometimes
`ideas/scream.md` § Retakes trimmed and `pipeline.md`.

## What the video was

5:10.9 of VO across 67 segments, under 37 shots of film clips and title cards.
lucid's part: strip silences, then cut eight retakes by word range. Everything
above the audio bed was done by a one-off script, `goodsometimes/scripts/
assemble_scream.py`, because lucid has no multi-track model.

## The core thesis held, and it paid off late

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

## 1. Build `verify` — transcribe the render, diff against the timeline

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
  re-transcription covers the audio. Both are needed. **The picture half is
  still unbuilt** — `verify` is audio-only, and it lives with rendering rather
  than with this.

## 2. Word durations are not addresses — only word *order* is

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

## 3. Multi-track: the shape is known now, so the decision is cheaper

PLAN.md § Open questions calls laying clips and graphics over the VO "the next
real decision", to be made against the next video rather than this one. That
still stands — but `assemble_scream.py` is now a worked reference (403 lines,
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

## 4. Rendering a multi-track project needs `melt`, not auto-editor

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

## What this does not establish

One video, one speaker, one voice. The source was **audio-only** — no VFR
question was touched, no camera footage, no speed changes or transitions. Every
cut landed at a restart pause, the most generous case there is; a mid-sentence
cut has no such margin.

The multi-track findings come from a script written for one project and are
descriptive of MLT, not of a design lucid has committed to.
