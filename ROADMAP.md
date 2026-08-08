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

Last reshuffled **2026-08-08**, which clears everything that was in **Next**:
render-time cuts, the rest of the picture-side render checks, attenuating
noises instead of cutting them, and the decision gate's prerequisite overlap
check were all built and run against the real Scream VO the same day. An
adversarial review found and fixed seven correctness bugs across that work —
notably that `export` was silently skipping attenuated audio and that a
`plan=True` preview of `attenuate_noises` could promise a write the matching
real call would not perform — both now fixed. PLAN.md § `cut_by_time`, cuts
addressed by what an export played; § `check_black` and `spot_frames`, the
rest of the picture-side checks; § `attenuate_noises`, pulling noise down
instead of cutting it; and § `speech_overlap`, the ducking prerequisite
Billy/Stu never had, carry the numbers; this file does not restate them.

Two CLI gaps the same run surfaced also closed, neither ever a roadmap item:
PLAN.md § `locate` and § `init` stops silently ignoring `-C`.

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

## Next — cleared

All three items queued here shipped the same day, against the real Scream VO,
with an adversarial review finding and fixing seven correctness bugs across
the batch before any of it counted as done.

Picture-side render checks are now complete: the frame count was already
built, and `check_black`/`spot_frames` (CLI `black`/`spots`) close out
blackdetect and spot frames — the first correctly refused to explain away a
genuine 11.8s dark outro card as the known auto-editor tail-frame defect, and
along the way turned up a measured ffmpeg quirk (a black run reaching EOF
reports zero duration) that shaped the tool's own default. PLAN.md
§ `check_black` and `spot_frames`, the rest of the picture-side checks,
carries the numbers.

Attenuate noises shipped as `attenuate_noises` (CLI `attenuate`), and its most
useful result on real material is a negative one: at every default, the
Scream VO attenuates **nothing** — the safety filter this item asked for
disqualified all thirteen candidate events by gap width and withheld five more
as suspect neighbours, which is the filter working, not failing to fire. The
review caught two write-affecting bugs here — `export` was silently reading
past attenuated audio back to the original file, and a `plan=True` preview
could promise a write the matching real call would not perform — both fixed.
PLAN.md § `attenuate_noises`, pulling noise down instead of cutting it, has
the detail.

Accepting cuts in render time shipped as `cut_by_time` (CLI `cut-at`) —
`Edit.source_spans`, the timeline→source inverse of `Edit.timeline_span`,
resolves every span against the pre-cut timeline before any of them applies,
padding only the two true outer edges and echoing words the same way
`cut --plan` does. PLAN.md § `cut_by_time`, cuts addressed by what an export
played, carries the numbers. Its mirror — `vo_extend`, appending real tail
time — is **not** built, on purpose: lucid never writes MLT itself, so the two
constraints that mirror would inherit (a real `silence` producer rather than a
`<blank>`; four declared-length spots swept in step) only become lucid's
problem the day it starts mutating an MLT project in place instead of
regenerating one through auto-editor, which is not on the table now. Nothing
is queued behind it.

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

**Its prerequisite now exists.** Billy/Stu was rejected for v4 on measurement,
not taste: a word-level whisper pass on the *source clip* put the line at
105.35–109.15 s against VO's own thesis sentence at 105.97–109.85 s — no seam,
so ducking there would cut a load-bearing VO line rather than empty air. The
missing comparison — does this clip's speech overlap VO's speech once both are
mapped through the edit? — is `speech_overlap` (CLI `speech-overlap`): clip
words against a proposed placement, VO words through `Edit.timeline_span`
exactly as captions map them, both trimmed through `energy.believable` first,
overlap tested in timeline coordinates rather than containment. Run against
the actual Billy/Stu clip and the VO's own nearest thesis region, it measured
74–85% overlap with only sub-second clean seams — the same "no seam" verdict
that shelved the duck for v4, now from the tool rather than by hand. PLAN.md
§ `speech_overlap`, the ducking prerequisite Billy/Stu never had, has the
numbers. What it does not do is design or build the duck itself, and the
DECISION stays open at mid-September regardless — the check answers "can this
clip speak here", not "should lucid grow tracks to let it".

`assemble_scream.py` (534 lines, stdlib) is still the worked reference for the
mechanism, and the decision is cheaper than it was because the model is
validated:

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
