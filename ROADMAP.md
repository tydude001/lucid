# lucid — roadmap

Direction and sequence, nothing else. **Status lives in the wiki's Open items
table**; evidence lives in [DOGFOOD.md](DOGFOOD.md) and the goodsometimes repo.
This file exists so a session can start building without re-deriving the
priority order — each item says why it ranks where it does and what "done"
looks like.

Last reshuffled **2026-08-07**, after the Scream v2/v3 recut. That pass
produced findings that postdate DOGFOOD.md; they are ranked here and their
evidence is in goodsometimes (`ideas/scream.md` § v2 and v3, `pipeline.md`
§ One transcription of the whole file is not enough).

## The property everything below defends

**Word indices address the source and never renumber.** When two late retakes
shifted every downstream cut by 4.4 seconds, the whole 37-shot plan recomputed
from two `lucid cut` commands — because no cue was written in timeline seconds.
DOGFOOD.md § The core thesis calls this the product, and it is. Any item below
that would trade it away is wrong regardless of what it buys.

The corollaries, already conventions in [CLAUDE.md](CLAUDE.md): trust word
*order*, never word *durations*; survival is an *overlap* test, never
containment; anything emitting times for playback maps through
`Edit.timeline_span`, never straight off the transcript.

---

## Now — small, each with a real failing case to test against

These three are ordered by value, but all are days-not-weeks and all can be
verified against the Scream VO, where the defect they target actually occurred.

### 1. `verify --windowed` — close verify's known blind spot

`verify` as built has been beaten by real material. Three retakes survived a
*correctly run* pass, because whisper's repeat-collapse has no size limit: the
word "bit" was handed **3.96 s** with a complete second reading of its own
sentence inside it, and the single-pass transcript read clean on both sides.
What found them: transcribing in **10-second windows with 3 s overlap** and
treating the **energy envelope as arbiter over any transcript** — a 4.12 s
"gap" between words that holds 2.4 s of speech cannot hide. A bigger model
does the opposite of helping (`medium` reported one take where the envelope
plainly shows two).

Method to port: goodsometimes `pipeline.md` § One transcription of the whole
file is not enough. **Done when** a windowed verify of the Scream v1-era
export surfaces all three retakes the single-pass run missed, and a run on the
shipping v3 export stays clean.

### 2. Flag suspect word durations at `attach-transcript`

Any word running past ~3× the median duration is a lie about something —
usually a swallowed retake. Report the list at attach time; refuse to use a
flagged word as a cut boundary without confirmation. DOGFOOD.md § 2,
proposal 1. **Done when** the Scream VO attach flags words 446 (2.2 s),
890 (2.0 s) and the 3.96 s "bit" — the three that each hid a restart.

### 3. Echo resolved words on every word-index argument

Six cues in the Scream shot plan pointed one word past the intended phrase —
invisible in the index, obvious the moment `--plan` printed the words each
index resolved to. Generalise that: **any lucid command or MCP tool that
accepts a word index echoes back the text it resolved to.** DOGFOOD.md § 3,
last paragraph. Cheapest item on this list, and it pays on every future video.

## Next — feature-sized, shape known from the Scream one-offs

### 4. Picture-side render checks

`verify` deliberately covers only audio. The picture half — frame count equals
the timeline's computed total, `blackdetect`, spot frames — was done by hand
for Scream and belongs with rendering/export, not with `verify`. The frame
count check is the load-bearing one: exact agreement with `melt`'s count is
what made 68 cut positions trustworthy before anything rendered.

### 5. Attenuate noises; don't cut them

Short, loud, non-speech events between words get pulled down (Scream used
−12 dB), not removed — a hole where a breath was reads as an edit; a quiet
breath reads as a person. The subtlety worth porting is the *safety filter*:
loud audio outside the word map is **not** automatically noise, because the
map has holes — the loudest "events" on Scream turned out to be speech inside
a 4-second hole. Only events that are short *and* sit in a gap narrow enough
to prove the map is dense around them qualify. Evidence: goodsometimes
`ideas/scream.md` § Seven noises.

### 6. Accept cuts in render time

A human watching an export reports flubs as render timestamps. goodsometimes
`scripts/vo_trim.py` takes cuts that way and converts to source itself — the
inverse of `Edit.timeline_span`. Give lucid the same shape, so "cut 0:40.4 for
4.4 s" works directly off someone's watch notes without hand-converting
through the edit.

## Decision gate — multi-track, decide mid-September

**The call:** does lucid *trim your VO* (single track, done) or *edit your
video* (tracks, cue tables, compositing)? PLAN.md § Open questions says to
decide against the next real video, and that video now has a date: the
**October Horror Bracket, part 1 due Oct 1**, format decisions wanted
mid-September.

Until then, `assemble_scream.py` (403 lines, stdlib) is the worked reference,
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
  infidelity, which items 1–2 address instead. DOGFOOD.md § 2's revision of
  PLAN.md § Word-timestamp accuracy. Revisit if a video demands mid-sentence
  cuts.
- **Everything one video couldn't establish.** One speaker, audio-only VO, no
  camera footage, no VFR, no speed changes, every cut at a generous restart
  pause. DOGFOOD.md § What this does not establish. The October bracket is
  where several of these get their first real test — expect this file to
  reshuffle then.

Non-goals stay where they are: PLAN.md § Non-goals, written down so they stay
dead.
