# lucid — roadmap

Direction and sequence, nothing else. **Status lives in the wiki's Open items
table**; evidence lives in [DOGFOOD.md](DOGFOOD.md) and the goodsometimes repo.
This file exists so a session can start building without re-deriving the
priority order — each item says why it ranks where it does and what "done"
looks like.

**Cite items by name, never by number.** The numbers renumber every time
something ships, and they have: four separate things in `src/` and `tests/`
once all cited "ROADMAP.md item 1" meaning four different items. Anything
built gets a named `##` section in [PLAN.md](PLAN.md); cite that instead — it
is stable, and it is where the evidence is.

Last reshuffled **2026-08-07**, which cleared the **Now** list: `verify
--windowed`, adjacent-near-duplicate and suspect-duration flagging, and the
word-index echo with `cut --plan` under it were all built and run against the
real Scream VO that day. The frame-count half of picture-side checks followed,
and found a real defect on its first run. Each has its own named section in
PLAN.md carrying the numbers; this file does not restate them.

**Ordering answers to measured defects, not to competitors.** A prior-art pass
the same day found Daydream to be a full desktop NLE rather than the chat front
end the README claimed — it corrected the pitch and moved nothing here, because
it produced no failing case and has no Linux build to test against.
PLAN.md § What lucid is, stated narrowly holds the conclusion;
[PRIOR-ART.md](PRIOR-ART.md) § Daydream the evidence.

## The property everything below defends

**Word indices address the source and never renumber.** When two late retakes
shifted every downstream cut by 4.4 seconds, the whole 37-shot plan recomputed
from two `lucid cut` commands — because no cue was written in timeline seconds.
DOGFOOD.md § The core thesis calls this the product, and it is. Any item below
that would trade it away is wrong regardless of what it buys.

A second proof arrived from the audio side, and it widens the claim.
`music_bed.py`'s cues carry explicit lengths tuned to the old 302 s runtime, so
appending ~12 s of outro invalidated the whole bed at once — retuning it was
correctly abandoned as wasted work rather than attempted. Same failure as a cue
written in timeline seconds, on music rather than shots: **the property is about
every cue in a project, not just the shot plan.**

The corollaries, already conventions in [CLAUDE.md](CLAUDE.md): trust word
*order*, never word *durations*; survival is an *overlap* test, never
containment; anything emitting times for playback maps through
`Edit.timeline_span`, never straight off the transcript.

---

## Now — cleared

Nothing is queued ahead of **Next**. What "verified" means for anything that
lands here: run against the real Scream VO, where the defect actually
occurred, not a synthetic fixture. It is on the NAS at `TheVaultData/content
stuff/Good Sometimes/Videos/Every Scream Sequel Falls Apart At The
REVEAL/VO/VO.json`, mounted at `~/TheVaultData`. Its word indices address
**the v1 recording**; the pending re-record produces a different file with
different indices and does not retire the recorded findings as evidence.

## Next — feature-sized, shape known from the Scream one-offs

### 1. Picture-side render checks — the rest of them

The frame count is **built**: `lucid frames` / `check_frames`, run against
`melt -consumer xml` before a render or against the render after. PLAN.md
§ `check_frames` carries the numbers, including what it found on its first real
run — auto-editor's kdenlive export is one frame long and the frame is black.

What is left of this item is `blackdetect` and spot frames. Both were done by
hand for Scream, both belong with rendering/export rather than with `verify`,
and neither is load-bearing the way the count was: the count is what made 68 cut
positions trustworthy *before* anything rendered, where these two read a render
that already exists.

### 2. Attenuate noises; don't cut them

Short, loud, non-speech events between words get pulled down (Scream used
−12 dB), not removed — a hole where a breath was reads as an edit; a quiet
breath reads as a person. The subtlety worth porting is the *safety filter*:
loud audio outside the word map is **not** automatically noise, because the
map has holes — the loudest "events" on Scream turned out to be speech inside
a 4-second hole. Only events that are short *and* sit in a gap narrow enough
to prove the map is dense around them qualify. Evidence: goodsometimes
`ideas/scream.md` § Seven noises.

### 3. Accept cuts in render time — and its mirror, added time

A human watching an export reports flubs as render timestamps. goodsometimes
`scripts/vo_trim.py` takes cuts that way and converts to source itself — the
inverse of `Edit.timeline_span`. Give lucid the same shape, so "cut 0:40.4 for
4.4 s" works directly off someone's watch notes without hand-converting
through the edit.

`vo_extend.py` is now its mirror — appending real tail time, built to give the
Scream postscript room before the outro card — and it carries two constraints
any lucid timeline mutation inherits:

- The added time must be a real MLT `silence` producer entry, **not** a
  `<blank>`. Cue tables addressed by word index cannot see blanks, so a
  `<blank>` adds runtime every downstream cue is blind to.
- Four declared-length spots have to be swept in step — both tractors' `out`,
  the sequence track's `out`, `producer0`'s `length`. Same bug class as
  trimming, opposite sign; `vo_trim.py` sweeps the same four.

Neither is lucid's problem *yet*, and the reason is worth writing down so it
isn't rediscovered as a surprise: lucid never writes MLT itself. It shells out
to `auto-editor --export kdenlive` (`autoeditor.py`) and auto-editor owns the
XML, so lucid regenerates timelines rather than mutating them. The day it
mutates one in place, it owns both constraints above.

## Decision gate — multi-track, decide mid-September

**The call:** does lucid *trim your VO* (single track, done) or *edit your
video* (tracks, cue tables, compositing)? PLAN.md § Open questions says to
decide against the next real video. That is no longer October: the **Scream VO
re-record** comes first, and it drags a full re-cut, a re-carded beat map, a
reapplied score and one specific multi-track edit behind it. The **October
Horror Bracket, part 1 due Oct 1** still sets the outside date, format
decisions wanted mid-September.

**The gate now has a named edit to answer rather than a hypothetical.** Beat 3's
Billy/Stu line — "Movies don't create psychos. Movies make psychos more
creative." — is the film stating the video's own thesis, and the wanted edit is
to duck VO under the clip's own audio and let it land. The mechanism exists:
splitting a shot into muted and unmuted producers with an extra mix transition,
built for the v4 postscript, rejected on the watch *there* for a reason that
does not apply here (that line was merely adjacent dialogue, and adjacency is
not a joke), and left inert in `assemble_scream.py` rather than deleted. It is
blocked only on the re-record opening a clean seam. If lucid cannot express
this edit, it trims your VO.

**Its prerequisite is a check lucid does not have.** Billy/Stu was rejected for
v4 on measurement, not taste: a word-level whisper pass on the *source clip* put
the line at 105.35–109.15 s against VO's own thesis sentence at 105.97–109.85 s
— no seam, so ducking there would cut a load-bearing VO line rather than empty
air. That is a third use for `transcribe`, which until now ran against the VO
and against renders. The missing piece is the comparison: **does this clip's
speech overlap VO's speech once both are mapped through the edit?** Both sides
map through `Edit.timeline_span`, making it an overlap test in timeline
coordinates — and it wants building whichever way the gate falls, because
"can this clip speak here?" is asked before any ducking is designed.

Until then, `assemble_scream.py` (534 lines, stdlib) is the worked reference,
and the decision is cheaper than it was because the model is validated:

- A cue table of `(source_word_index, asset)` — nothing positioned in
  timeline coordinates. Each cue runs to the next.
- `timeline_time()` honouring MLT's frame-inclusive `out`, validated by exact
  frame-count agreement with `melt`.
- **Refuse to build** when a cue points into a cut range — this failed loudly
  and correctly twice on Scream, both times catching a stale cue after a
  recut. Whatever multi-track shape lucid adopts keeps this behaviour.
- Rendering multi-track means `melt`, not auto-editor, and `melt` has three
  silent traps (consumer profile → runaway memory; Qt needs a display;
  flatpak `/tmp`). All documented in DOGFOOD.md § 4 — do not re-derive them.

## Parked — deliberately, with the reasoning

- **Energy-snapping cut edges.** Measured non-urgent on Scream-like material:
  every known retake boundary had 0.34–2.48 s of silence and a flat 0.1 s pad
  never clipped. The failures that *looked* like drift were transcript
  infidelity, which the near-duplicate check and suspect-duration flagging
  (both built) address instead. DOGFOOD.md § 2's revision of
  PLAN.md § Word-timestamp accuracy. Revisit if a video demands mid-sentence
  cuts.
- **Everything one video couldn't establish.** One speaker, audio-only VO, no
  camera footage, no VFR, no speed changes, every cut at a generous restart
  pause. DOGFOOD.md § What this does not establish. The October bracket is
  where several of these get their first real test — expect this file to
  reshuffle then.

Non-goals stay where they are: PLAN.md § Non-goals, written down so they stay
dead.
