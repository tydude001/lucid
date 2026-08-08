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

**Next** refilled the same day with the tier-2 preview/timeline web UI, which
this file had never named, and that shipped the same day too — `lucid web`.
It bought more than the "see it before rendering" it was queued for: the page
plays the source and jumps the seams, so **seeing an edit costs no render at
all**. PLAN.md § The preview/timeline web UI.

**Then it got worked in, and refilled Next again** — with the workspace that
`lucid web` turned out not to be. Tier 3 is now the goal; the queue is under
**Now** below. PLAN.md § Tier 3 is the goal — the Daydream-shaped workspace.

**Ordering answers to measured defects, not to competitors**, and the
workspace is not the exception it looks like. A prior-art pass on 2026-08-07
found Daydream to be a full desktop NLE rather than the chat front end the
README claimed — it corrected the pitch and moved nothing here, because it
produced no failing case and has no Linux build to test against. That is still
what happened: the thing that moved the roadmap a day later was **using
`lucid web` on the real Scream VO**, which produced five specific failing
cases inside the window. Daydream supplies the shape of the fix. It did not
supply the reason. PLAN.md § What lucid is, stated narrowly holds the
conclusion; [PRIOR-ART.md](PRIOR-ART.md) § Daydream the evidence.

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

## Now — the workspace

**Tier 3 is the goal, decided 2026-08-08**, and this is the queue that follows
from it. The decision, the evidence that drove it, and the trap it exists to
prevent are in PLAN.md § Tier 3 is the goal — the Daydream-shaped workspace;
this file does not restate them.

The trigger was use, not argument. `lucid web` shipped the same day it was
queued and was then worked in, and what came back was that it is a correct
instrument and a poor editor — every complaint being about the inside of the
window, none about the handoff the tier-3 note had expected to be the wall.

In order, each item standing alone — the first four are the window, the fifth
is the tier line:

1. **App shell and design system.** Three panes over a bottom timeline; the
   picture becomes the centre of the window rather than a 34vh strip above two
   others. No framework and no build step — that constraint is unchanged.
2. **The transcript as a document.** Paragraphs off whisper's own segments,
   inline timestamps, a show-cuts toggle, cut text struck through in place,
   scroll to the playing word. It is addressable already; this makes it
   readable at the same time.
3. **A real timeline.** Ruler, zoom, track headers, named clip blocks, and a
   waveform from `energy.envelope` — cached, because it is a second read of
   the media. **Lanes drawn over today's single-track `Edit` are projections
   of one track and are labelled as such in the code.**
4. **The agent panel.** A local `claude` subprocess with `lucid mcp` attached,
   streamed to the page. This is the category difference and the only piece
   with genuinely new plumbing; everything above it is front end. Its tool
   allowlist is lucid's MCP tools and nothing else — **decided against the
   looser options, not defaulted into**, and not a flag to widen mid-debug.
5. **Render in the window.** Export produces a watermark-free MP4 from the
   page, through a job model, with the existing render checks reported on the
   completion card. `ops.export` already renders; what is new is the job, the
   progress, and reading auto-editor's *output* rather than its exit code.
   **This is the item that crosses the tier line** — everything above it is a
   better window onto the tier-2 lucid that already exists.

"Verified" is unchanged and is not negotiable for a UI item either: run
against the real Scream VO, where the defects actually occurred, not a
synthetic fixture. It is on the NAS at `TheVaultData/content stuff/Good
Sometimes/Videos/Every Scream Sequel Falls Apart At The REVEAL/VO/VO.json`,
mounted at `~/TheVaultData`. Its word indices address **the v1 recording**;
the pending re-record produces a different file with different indices and
does not retire the recorded findings as evidence. A UI item is additionally
verified **in a browser** — the flatpak-Chrome recipe, and the silent trap in
it, are in wiki `tooling.md` § Headless browser.

The Decision gate below still does not move, and the workspace does not move
it either — for the reason the web UI was queued ahead of it in the first
place: the picture track is a derived projection, so a view built against
today's `Edit` widens with the model rather than blocking on it. **The
converse is the standing constraint on item 3:** the view must not widen
*ahead* of the model, because the export degrades silently rather than
failing.

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

**The cost is measured, and it moved the gate off lucid's data model.**
Widening the model is cheap and the picture track turns out to be a *derived
projection* rather than state, so `Edit` stays single-track. The expense is
getting a multi-**source** timeline out at all: auto-editor 31.x gates that
behind a paid key, and a duck needs the clip's audio *and* the VO — so
**Billy/Stu is unexportable free whichever way the model question falls.** What
is actually being decided in September is therefore one of four: pay for a key
(collides with PLAN.md § Non-goals), build auto-editor from source (its licence
permits it), write MLT directly (reverses the rule below), or keep exports
single-source and hand Kdenlive a computed cue sheet. Evidence, tables and the
two designs costed: PLAN.md § The multi-track costing spike.

`assemble_scream.py` (534 lines, stdlib) is still the worked reference for the
mechanism — though auto-editor's own exporter now writes the MLT structure it
hand-rolls — and the decision is cheaper than it was because the model is
validated:

- A cue table of `(source_word_index, asset)` — nothing positioned in
  timeline coordinates. Each cue runs to the next.
- `timeline_time()` honouring MLT's frame-inclusive `out`, validated by exact
  frame-count agreement with `melt`.
- **Refuse to build** when a cue points into a cut range — this failed loudly
  and correctly twice on Scream, both times catching a stale cue after a
  recut. Whatever multi-track shape lucid adopts keeps this behaviour.
- Rendering multi-track does **not** in itself mean `melt` — measured
  2026-08-08, auto-editor renders a two-track v3 at full resolution and exports
  it to a four-tractor MLT project that `melt` reads. It is multi-*source*, not
  multi-track, that auto-editor gates; the costing spike above has the table.
  When rendering does fall to `melt`, it has three silent traps (consumer
  profile → runaway memory; Qt needs a display; flatpak `/tmp`), all documented
  in DOGFOOD.md § 4 — do not re-derive them.

## Parked — deliberately, with the reasoning

- **`vo_extend`, the mirror of `cut_by_time`.** Appending real tail time only
  becomes lucid's problem the day it mutates an MLT project in place instead
  of regenerating one through auto-editor, which is not on the table. The two
  constraints it would inherit are written down so they are not rediscovered
  as a surprise: PLAN.md § The `vo_extend` mirror is a deliberate non-goal,
  for now.
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
dead — cloud, competing on finishing, a plugin system before two users.

**What separates tier 2 from tier 3 is still finishing, not mutation** — the
definition did not change, only lucid's intent to cross it, which § Now item 5
is. The order is workspace first, finishing second, because the window is what
makes the render path's gaps visible.

**This note predicted the wrong wall, and the prediction stays on the record.**
It expected tier 3 to reopen on evidence that the *handoff* was trapping
timelines — the failure the OpenChatCut trial measured, where export was
flattened media, subtitles or FCPXML, none of which opens on this box. What
actually reopened it was the *window*: every complaint from working in `lucid
web` sat inside it, and the handoff was never reached.

The Electron-as-MCP-host friction this note held up as tier 3's cost is still
measured and still true, and it now argues for a **workspace rather than a
desktop app** — a distinction the original tier-3 wording never drew.
PLAN.md § First milestones, the trial; [PRIOR-ART.md](PRIOR-ART.md)
§ OpenChatCut.
