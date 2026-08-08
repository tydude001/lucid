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

**Then it got worked in, refilled Next with the workspace `lucid web` turned
out not to be — and the workspace shipped the same day as well.** Tier 3 is
the goal, and its queue is now built; what little remains of it is in the
wiki's Open items table. PLAN.md § Tier 3 is the goal — the Daydream-shaped
workspace.

**And then it refilled Next a third time, with the Decision gate itself — now
decided rather than pending.** **Next is the layered timeline**, a six-step
build order in PLAN.md § The layered timeline. Nothing in it is written yet.

**And a direction was set the same day, wider than any refill: lucid copies
Daydream — the full feature set and the look/feel.** Tyler's call, 2026-08-08,
made after capturing the entire site (every page, all sixteen videos, the
docs, the CSS tokens). The whole parity plan — the product observed, the
design system, the feature map, the build order — is one document,
[DAYDREAM.md](DAYDREAM.md); the order it implies is § Then — the Daydream
parity queue, below.

**Ordering answers to measured defects, not to competitors** — that was the
rule, and the workspace was not the exception it looked like: a prior-art pass
on 2026-08-07 corrected the pitch and moved nothing here, because Daydream
produced no failing case and has no Linux build to test against; what moved
the roadmap a day later was **using `lucid web` on the real Scream VO**, which
produced five specific failing cases inside the window. Daydream supplied the
shape of the fix, not the reason. **Amended 2026-08-08: the parity decision
above is the exception, and it is deliberate** — parity is now a goal by
owner's decision rather than by measurement. What survives of the rule is the
*order*: the parity queue below still ranks by what the layered timeline
unblocks and what a real video demands first, and the constraints that kept
the window honest (no lane the export cannot produce, cues stay
source-addressed) bind every parity item. PLAN.md § What lucid is, stated
narrowly holds the conclusion; [PRIOR-ART.md](PRIOR-ART.md) § Daydream the
evidence.

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

## Now — the workspace is built; the gate is decided, and the build is queued

**The workspace queue shipped 2026-08-08** — shell, transcript-as-document,
the real timeline, the agent panel, and render in the window, the last of
which crossed the tier line. Verified in a real browser against the Scream
VO, not a fixture. Evidence, and the two `claude`-flag traps the build found
(`--verbose`, and `--tools ''` being what actually confines the agent):
PLAN.md § Tier 3 is the goal — the Daydream-shaped workspace.

What remains of it is tracked in the wiki's Open items table: binding the
spawned MCP server to its `-C` project (the gap between the shipped panel
and the section's stated security boundary), and the video preview proxy,
which waits on a project with real footage.

The verified bar for any future UI item is unchanged: run against the real
Scream VO (NAS, `TheVaultData/content stuff/Good Sometimes/Videos/Every
Scream Sequel Falls Apart At The REVEAL/VO/VO.json`, mounted at
`~/TheVaultData`; its word indices address **the v1 recording**), and
additionally in a browser — the flatpak-Chrome recipe and its silent trap
are in wiki `tooling.md` § Headless browser.

The workspace did not move the Decision gate below, for the reason the web
UI was queued ahead of it in the first place: the picture track is a derived
projection, so the view widens with the model rather than blocking on it.
**The converse is the standing constraint on the timeline:** the view must
not widen *ahead* of the model, because the export degrades silently rather
than failing.

**And it is what moved the gate below** — the question that decided it was
asked of the window, not of the code.

## Next — the layered timeline. The gate is decided: lucid edits your video

**Decided 2026-08-08, ahead of its mid-September date, because the decision
turned out to rest on a measurement rather than a preference.** The gate asked
whether lucid *trims your VO* (single track, done) or *edits your video*
(tracks, cue tables, compositing). It edits your video. Design, build order,
evidence and what stays blocked: PLAN.md § The layered timeline — the gate is
decided, and `melt` renders it. That section is written to be picked up cold;
this one says only why it ranks first.

**What moved it was that the gate had been costed against the wrong renderer.**
§ The multi-track costing spike priced multi-*source* export as gated behind
auto-editor's paid key — correctly — and concluded the choice was one of four
options, none free. But DOGFOOD.md § 4 had **already** concluded, from the video
that shipped, that rendering a multi-track project needs `melt` rather than
auto-editor. Nothing connected the two. Measured 2026-08-08: `melt` renders the
real 23-source Scream assembly at **1920x1080** with no gate, from the Kdenlive
flatpak already installed and already resolved by `picture.melt_command()`. Two
of the four options existed only to buy back what `melt` does for free.

The build order is six steps in that PLAN.md section, each shippable alone.
Three constraints on it that this file owns:

- **The cue table stays source-addressed** — `(clip_id, word_index, asset)`,
  nothing in timeline coordinates. This is § The property everything below
  defends, and Design B preserves it by construction rather than by care.
- **Refuse to build when a cue lands in a cut range.** It fired correctly twice
  on Scream. Build it before the thing it guards.
- **The picture lane lands in the same change that lets `export` produce it**,
  never earlier — the view must not widen ahead of the model, because the
  export degrades silently rather than failing.

Seed the table from `assemble_scream.py`'s existing 37 cues, so the first
layered timeline lucid builds is a video that has already been watched.

**The outside date is unchanged and still real:** the **October Horror Bracket,
part 1 due Oct 1**, with format decisions wanted mid-September. The **Scream VO
re-record** still comes first for *that video* and still drags a re-cut, a
re-carded beat map and a reapplied score behind it — but it no longer gates
this work, because the layered timeline ships without the duck.

### The one edit that stays blocked, and it is not lucid's fault

Beat 3's Billy/Stu line — "Movies don't create psychos. Movies make psychos
more creative." — is the film stating the video's own thesis, and the wanted
edit is to duck VO under the clip's own audio and let it land. The mechanism
exists: splitting a shot into muted and unmuted producers with an extra mix
transition, built for the v4 postscript and left inert in
`assemble_scream.py` rather than deleted.

**It is blocked by the recording, not by the model.** Billy/Stu was rejected
for v4 on measurement, not taste: a word-level whisper pass on the *source
clip* put the line at 105.35–109.15 s against VO's own thesis sentence at
105.97–109.85 s. `speech_overlap` (CLI `speech-overlap`) re-measured that
properly — both sides trimmed through `energy.believable`, overlap tested in
timeline coordinates rather than containment — and returned **74–85% overlap
with only sub-second clean seams**. There is no seam to duck into. PLAN.md
§ `speech_overlap`, the ducking prerequisite Billy/Stu never had, has the
numbers.

So this edit waits on the **VO re-record**, or on **inserting a hold** — opening
a gap in the VO for the film's line to play in, which is new work because
`Edit` only ever removes. That is the same work as `vo_extend` below, whose
stated reason for being parked expires with this decision. Decide it on a
watch, not in the abstract. **Nothing here blocks the six build steps**; the
layered timeline ships without the duck.

### Two things worth not re-deriving

- **It is multi-*source*, not multi-track, that auto-editor gates.** Measured
  2026-08-08: auto-editor renders a two-track v3 at full resolution and exports
  it to a four-tractor MLT that `melt` reads. Two distinct `src` files is the
  wall, on one track or several. The costing spike has the table.
- **`melt` has three silent traps** — consumer profile → runaway memory; Qt
  needs a display; a flatpak's `/tmp` is not the host's. All three produce
  output rather than an error. DOGFOOD.md § 4, and
  `goodsometimes/scripts/render.py` handles all of them plus a `systemd-run`
  memory cap. Read it before writing the render call.

`assemble_scream.py` (534 lines, stdlib) remains the worked reference for the
mechanism and the source of the 37 seed cues.

## Then — the Daydream parity queue

The whole parity plan lives in [DAYDREAM.md](DAYDREAM.md) — the observed
product, the design system, the per-feature design notes, and what parity
deliberately does not import. This section keeps only the ranking, governed
by two facts: **the layered timeline is the enabler for most of the map**
(b-roll, graphics, and the V2 lane are illegal to draw until `export` can
produce them), and **the look/feel pass is the one big item gated on
nothing**.

1. **The look/feel pass** — the warm-paper retheme plus the small cosmetics
   that ride it (DAYDREAM.md § Build order names them). Independent of the
   model; it is UI work, so the verified bar applies.
2. **The layered timeline, steps 1–6** — already Next, above. Everything
   below waits on its picture lane.
3. **Caption styling**, then 4. **motion graphics + templates**, then
   5. **b-roll by description** — the last two get costed design notes
   before any build; b-roll especially must not copy Daydream blind, whose
   hour-metering implies cloud inference where lucid is local-only.
6. **The long tail** — aspect swap, import roles + assets pane,
   multi-project picker, HTTP MCP transport, properties pane.

## Parked — deliberately, with the reasoning

- **`vo_extend`, the mirror of `cut_by_time` — unparked by the gate decision,
  but not yet queued.** Its stated reason for being parked was that appending
  real tail time only matters the day lucid stops regenerating timelines
  through auto-editor. That day is the layered timeline above. It is also the
  same operation as *inserting a hold* to unblock Billy/Stu without a
  re-record, which is what would actually motivate building it. Two reasons it
  is still not in **Next**: it is the one item that touches `Edit`'s
  subtractive invariant, and the case for it is editorial — decide it on a
  watch, after the six steps land. The two MLT constraints it inherits are
  already written down: PLAN.md § The `vo_extend` mirror is a deliberate
  non-goal, for now.
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
definition did not change, and lucid crossed it on 2026-08-08: Export renders
a watermark-free MP4 in the window, with the render checks reported on the
completion card rather than left for a person to remember.

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
