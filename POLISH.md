# lucid — the polish plan: user-friendly, finished, useful to strangers

Provenance: a recommendation review on 2026-08-24, after the Studio reshape's
definition of done was met (STUDIO.md — footage in, film out, terminal never
required) and PLAN.md § The completion queue closed its last item. The finding
that frames this plan: **the editing core and the workspace are complete, and
every remaining gap is between "works for Tyler" and "works for anyone."**
Three kinds of gap, in order of value: things a newcomer hits in the first ten
minutes (environment, demo footage, onboarding), things that bite mid-edit
(undo scope, shortcut discoverability), and the oldest open question in
PLAN.md (an agent still cannot look at the film it edited).

This is the one document for that work. Status lives **only** in the wiki's
Open items table (`~/projects/wiki/README.md`); this file never carries a
status header. When a step ships: HISTORY.md gets a named section, the step
here gains a one-line "Shipped — see HISTORY.md § <name>" pointer, and the
wiki row updates.

## How to work this plan

- **One numbered step per session.** Each step is independently shippable and
  ends with the verification listed in it. Do not start step N+1 in the same
  session that shipped step N unless the step says it is small.
- **Every step starts with its "Verify first" list** — signatures and
  behaviours to read before writing code. The line references below were
  checked on 2026-08-24 and code moves; a claim in this file is a lead, never
  a fact to build on unread. This repo's design notes have repeatedly
  overturned their own premises on measurement.
- Repo conventions bind throughout, stated once in CLAUDE.md § Conventions and
  not restated here. The ones this plan leans on hardest: every MCP tool gets
  a CLI subcommand; tools register with `@_tool()`, never `@mcp.tool()`; tests
  speak to the real server (`tests/test_server_stdio.py` over stdio,
  `tests/test_webui_http.py` over a real socket); `ruff check` is the gate and
  `ruff format` is forbidden; the web UI draws and plays, never decides; the
  version bumps by hand in two places when something new becomes callable.
- The verified bar for every UI item: the real project, in a real browser,
  every click driven at **0ms and ~120ms dwell** via the
  `.claude/skills/verify-live/` harness — never a fifth hand-rolled one
  (HISTORY.md § The dwell-timing lesson). Probe `body *` for overflow at
  700/900/1200px, plus the second sweep inside scroll containers, in every
  state the layout can be in (HISTORY.md § The README screenshots, and the
  five defects they found).
- **Commit freely; never push.** Tyler pushes. Never migrate Tyler's project
  data without asking.

## The order, and why

1. **`lucid doctor`** and 2. **the demo project** first — they are what a
   stranger meets before any feature, and both compound with the go-public
   decision already sitting in the wiki's Open items ("publish decisions
   before the repo goes public").
3. **Manifest-aware undo** — the biggest verified polish hole in daily use.
4. **The VFR probe** — the likeliest "it broke on my video" first-contact
   failure for outside footage.
5. **The shortcut overlay** and 6. **Home's guided first run** — cheap,
   window-only, no model surface.
7. **The agent contact sheet** — a design note that stops for review, because
   it opens a new way for the agent to perceive the project.

Steps 1, 2, 4, 5 and 6 are independent of each other; 3 should land before 6
(the guided flow will generate mistakes worth undoing). 7 is last because it
is the only one that needs a design round.

---

## Step 01 — `lucid doctor`

Shipped — see HISTORY.md § `lucid doctor` — six binaries, and the
sentence after the ✗.

**Why.** lucid depends on six external binaries, and the repo's own record is
a catalog of the ways they fail *silently*: `melt` prints `Failed to load` and
exits 0; PyPI's auto-editor is a stale 29.x whose multi-source render degrades
to 720x576 at exit 0; whisper resolves through a three-step chain; fonts
substitute without error. Tyler navigates this with CLAUDE.md; a newcomer has
nothing. One command that probes every dependency and names the trap when a
probe fails is the single highest-value item for anyone else running lucid.

### Verify first

- `asr.py` ~line 80 — the whisper resolution chain (`LUCID_WHISPER` → PATH →
  sibling venv) and the error text it already composes.
- `picture.melt_command()` (~116), `picture.display_env()` (~143),
  `picture.qt_is_headless()` (~189) — melt resolution, the display
  compensation, and the headless answer. **Probe melt by its output, never
  its exit code** (CLAUDE.md — exit 0 proves nothing).
- `autoeditor.py` — what version detection exists, if any. The check doctor
  needs: binary present, version ≥ 31, and the named caveat that 31.x gates
  multi-*source* timelines (single-source is unaffected; lucid routes
  multi-source through melt anyway — the report should say the gate exists
  and that lucid designs around it, not scare the user).
- `fonts.probe` (fonts.py ~307) and `captions.font_match` (captions.py ~378)
  — which face actually draws vs. which fontconfig claims; doctor reports the
  vendored caption default resolving, with `font_match`'s caveat intact.
- `ops.describe(plan=True)` (ops.py ~705) — the standing precedent for
  "report whether this machine can run it without paying for it." Doctor's
  optional-capability section reuses whatever probe that path uses for
  `LUCID_VLM`; mirror the same shape for `LUCID_FACE` and `LUCID_TTS`
  (tts.py — note `LUCID_TTS_VOICE` has **no default on purpose**; doctor
  reports it unset as an expected refusal, never as an error, and never
  prints a path that would out a private voice reference).
- `media.py` — how ffmpeg/ffprobe are invoked (doctor checks both on PATH).
- How the CLI and server handle a **project-less** command — `lucid init`
  (ops.py ~100) is the precedent on the CLI side; check how a tool that takes
  no `path` registers with `@_tool()` and whether the `-C` binding tolerates
  it. If every existing tool takes a path, that is the first thing to solve,
  not to work around.

### Build

- `ops.doctor()` → a dict, report-only, fixes nothing, needs no project.
  Sections: `required` (ffmpeg, ffprobe, whisper, auto-editor, melt, magick)
  and `optional` (`LUCID_VLM`, `LUCID_FACE`, `LUCID_TTS`/`LUCID_TTS_VOICE`),
  plus `display` (the qt_is_headless / display_env answer — an unattended box
  renders under `QT_QPA_PLATFORM=offscreen`, and doctor should say so rather
  than just "no display").
- Each entry: what was looked for, where it was found (path), the version
  when one is readable, `ok`, and — when not ok — **the named trap and the
  fix**, in the words CLAUDE.md already has ("pip install auto-editor gets
  29.3.1; install the upstream binary"). The value of doctor is the sentence
  after the ✗.
- CLI `lucid doctor` (human-readable render of the dict) + MCP tool (parity).
- Optional entries missing are reported as "feature X unavailable", never as
  failures — everything required works without them (README § Requirements).

### Verify

- `tests/test_server_stdio.py`: the tool reachable over stdio.
- Unit tests monkeypatching a missing binary, a stale auto-editor version
  string, and an unset `LUCID_TTS_VOICE` — each surfaces its named message.
- Run it on this box and read the whole report; every row should be true.
- README § Requirements gains one line: "run `lucid doctor` to check all of
  this at once."

---

## Step 02 — the demo project

Shipped — see HISTORY.md § The demo project — footage generated, nothing
vendored. **One half is left and it is Tyler's**: the README screenshot swap.
Drafts against the demo project are at `~/lucid-work/demo-shots-*.png`,
deliberately not committed over `docs/img/`. The *media* choice this step said
to bring to him resolved itself — generating everything vendors nothing and
needs no licence review at all.

**Why.** The README quickstart assumes the user has a voiceover with retakes
lying around. A demo a stranger can run in two minutes — cut by transcript,
watch a cue land, export, verify — is the difference between reading about
lucid and experiencing it. It also dissolves half of the publish blocker:
screenshots of the demo project replace the three recognisably-Scream frames
in README.md (the wiki open item "publish decisions before the repo goes
public", call 1).

### Verify first

- The wiki open item's exact wording, so this step's output can be judged
  against it.
- `media.import` requirements (what containers/codecs import cleanly; the
  multi-stream refusal — the demo VO must be single-stream).
- How small a usable whisper input can be — the demo VO must transcribe with
  word timings good enough to cut by.
- The `testsrc`-proxies-larger trap (CLAUDE.md § The preview proxy) — pure
  synthetic b-roll footage has already violated a size assumption once.

### Build

**The media, decided before anything is vendored.** Constraints: freely
redistributable, small (the repo should not grow by more than a few MB, if it
carries media at all), speech real enough for whisper, containing **a
deliberate retake** (the thing the quickstart cuts), and at least two visually
distinct b-roll clips (the thing the cue table places). The recommendation:

- A generator script (`scripts/make_demo.py`, or a `lucid demo <dir>`
  command — prefer the script; a CLI command implies API surface this does
  not need) that *builds* the fixture locally rather than vendoring blobs:
  splice the retake with ffmpeg from a vendored public-domain VO clip
  (LibriVox is public domain; a short own-recording works too), and cut
  b-roll from public-domain footage (NASA archives) or generate
  colour-distinct clips with burnt-in labels — the repo's own "every moment
  names itself" precedent, though real footage screenshots better.
- **Present the media choice to Tyler before vendoring anything** — licence
  diligence on whatever is chosen, and the screenshots that come out of this
  are his channel's shop window.

**The walkthrough.** `docs/DEMO.md`: the full loop, verbatim commands —
import → transcribe → seed → find the retake in the transcript → `cut --plan`
→ cut → cue a b-roll clip → `export --render` → `verify` → `lucid open`.
Every command's expected output sketched, so a reader knows they are on
track. README's "Try it" section points at it.

**The screenshots.** Retake the three README images (`docs/img/`) against the
demo project at the same three modes they currently show. Propose the swap to
Tyler rather than committing over the existing images unasked — the current
ones are recognisably his video.

### Verify

- A fresh-checkout run: clone to a temp dir, `uv sync`, run DEMO.md top to
  bottom verbatim, confirm the export verifies. This is the whole point;
  nothing else substitutes.
- The generated VO transcribes with the retake visible in the transcript and
  cleanly cuttable (the cut lands in silence, `verify` clean after).

---

## Step 03 — manifest-aware undo

Shipped — see HISTORY.md § Manifest-aware undo — a snapshot is a pair.

**Why.** Verified 2026-08-24: `Project.snapshot()` copies only
`project.otio` (project.py ~344) and `undo` restores only it (ops.py ~5227).
But most authoring state now lives in the **manifest** — the cue table,
framing rects, the music bed, caption style, tail/head/holds, marks, card
records. A mis-drag on the A2 bed or a wrong cue placement has no undo at
all, while a cut undoes fine. The window made these one-gesture mutations;
undo has to cover what a gesture can now do.

### Verify first

- `Project.snapshot`/`snapshots`/`restore` (project.py ~338–370) — note
  `snapshot()` returns `None` when no timeline exists yet; a manifest-only
  mutation on a pre-seed project still deserves undo, so that early-return
  needs rethinking, not inheriting.
- **Every call site of `snapshot()`** — which ops snapshot today. The new
  rule has to be stated as a list (which ops snapshot, which don't), not
  discovered per bug.
- The manifest write path (how ops persist manifest changes — one save
  choke point or many).
- `webui.py`'s `_revision` watcher — it already watches the manifest, so a
  manifest restore fires `project-changed` for free; confirm.
- The `/api/undo` route and the window's undo affordance (app.js ~192,
  player.js's `shortcut-undo`).
- What else lives in the manifest that undo would roll back: `pack`,
  `review` verdicts, registered clips. Decide scope deliberately (below).

### Build

- Paired snapshots: `N.otio` + `N.manifest.json`, written together;
  `restore` restores the pair. An **older otio-only snapshot restores the
  timeline alone and reports `manifest_restored: false`** — never guesses at
  a manifest it doesn't have.
- Manifest-mutating ops snapshot too. Recommended scope: snapshot the
  **whole manifest** (one file, one copy, no per-key surgery) on every
  mutating op that changes it. Consequences to accept and report rather than
  special-case: undoing an import un-registers the clip but leaves media
  files on disk (report it in undo's return); undoing past a `pack_apply`
  rolls the pack back (correct — it was a mutation).
- `undo`'s return says what changed: timeline, manifest, or both, plus the
  existing depth.
- No schema bump — history files are cache-class, not manifest keys.

### Verify

- stdio tests: `cue_add` → `undo` restores the prior cue table; `reframe` →
  `undo`; a mixed sequence (cut, cue, cut) undoes in reverse order with each
  step restoring exactly one mutation.
- The otio-only legacy snapshot case: seed a history dir by hand, restore,
  read `manifest_restored: false`.
- HTTP: undo bumps `/api/view`'s revision and `project-changed` fires (the
  `_revision`-watches-the-manifest case).
- Existing undo tests pass unchanged.

---

## Step 04 — the VFR probe

Shipped — see HISTORY.md § The VFR probe — measured, and reported rather
than flagged.

**Why.** PLAN.md § Open questions (*Variable frame rate footage*) already
holds the lean — do **not** transcode on import; probe, record `vfr: true`,
normalize only where frame-exactness matters (NLE export) — and it is
unverified. Every dogfood recording is controlled; a stranger's first clip is
a phone or screen recording, which is often VFR, and VFR is where naive cut
math breaks. Cheap to build, and it converts a mystery failure into a named
condition.

### Verify first

- The PLAN.md bullet itself, so the build matches the recorded lean.
- `media.py`'s ffprobe helpers — what is already read at import.
- How to *detect* VFR reliably: `avg_frame_rate` vs `r_frame_rate`
  disagreement is the cheap signal; measure it against a real VFR file
  before trusting it (a screen recording made on this box, or a phone clip).
  If the cheap signal is unreliable, a bounded packet-timing sample is the
  fallback — measure, don't assume.
- `ops.import_media` (~147) — where the manifest entry is written;
  `ops.properties` and `finish_report` — where the flag surfaces.

### Build

- Probe at import; record `vfr: true` on the clip's manifest entry —
  **additive-optional, absent means what every older manifest meant, no
  schema bump** (the `caption_style` precedent).
- Surface it: `import`'s own return, `properties`, and `finish_report` as an
  informational line (not a flag/warning — the render path is time-domain
  and mostly fine; the point is that when something *is* off, the condition
  has a name on the record).
- Normalization at NLE export is **out of scope here, deliberately** — state
  it in the op's docstring and leave the PLAN.md bullet open on that half.

### Verify

- A real VFR recording through import: flag recorded, visible in
  `properties` and `finish_report`.
- A CFR fixture: no key written (absent, not `false`).
- Unit test with a monkeypatched probe for both shapes.

---

## Step 05 — the shortcut overlay

Shipped — see HISTORY.md § The shortcut sheet grew the three panes it never
listed. **The overlay itself already existed** when this step was worked; what
this plan's step description got wrong is worth keeping: the `?` dialog, its
Escape/backdrop close and its typing suppression were all built, and the real
gap was that it listed only player.js's bindings. Its recommendation of a
JS-side shortcut table was also declined — the hand-typed HTML is deliberate,
so the map reads whether or not the bindings it documents are wired.

**Why.** The window has real shortcuts (player.js ~882 holds a window-level
keydown; undo, `⌘K` for the composer) and nothing lists them. A `?` overlay
is the difference between shortcuts existing and being used. Small step —
may share a session with step 04.

### Verify first

- Every existing keydown handler: player.js ~882, transcript.js
  `handleTranscriptKeyDown` (~999), timeline.js's input handlers (~1083,
  ~1162), agent.js's composer (~729) — the overlay's list is compiled from
  what these actually do, read, not remembered.
- The `[hidden]` trap: anything this stylesheet gives a `display:` needs the
  companion `[hidden]` rule or `el.hidden` does nothing (CLAUDE.md).
- An existing modal/popover precedent in app.css to match, rather than
  inventing a new one.

### Build

- One shortcut table in JS — a static list, the single source the overlay
  renders. Group by mode/pane. No server surface at all.
- `?` opens, `Esc` closes; suppressed while focus is in an input, textarea,
  or the composer (the transcript pane's keydown already threads this
  needle — reuse its discipline).
- The overlay is centered and height-capped (`clampFloating` MOVES, never
  SHRINKS — CLAUDE.md; a fixed max-height with internal scroll avoids the
  whole class).

### Verify

- verify-live at 0ms and ~120ms: open, close, and confirm `?` typed *into*
  the agent composer does not open it.
- Overflow probes at 700/900/1200px, both themes.

---

## Step 06 — Home's empty state, the guided first run

Shipped — see HISTORY.md § Home's first run — create, import, transcribe,
seed, on the page.

**Why.** Import and transcribe are window operations now (HISTORY.md
§ Import and transcribe became window operations), so a first-run guided flow
is mostly wiring — but today a fresh Home with zero projects is a dead end
for anyone who doesn't know the CLI. The empty state should walk
create → import → transcribe → seed, each step's control appearing as the
previous completes.

### Verify first

- `picker.js`/`picker.html`, the four scan outcomes, and the **one-way
  `_bind_singletons` bind** via `POST /api/open` (CLAUDE.md § The
  multi-project picker) — the picker never binds, and this step must not
  change that.
- Whether a create-project route exists (almost certainly not — `ops.init`
  at ops.py ~100 is CLI-only today).
- Whether `seed` is reachable from the window — `ops.seed_timeline`
  (~2678); the reshape's record names import and transcribe as window ops
  and does not mention seed. Auto-editor runs cost real seconds, so if a
  route is needed it is a **job** on the import/transcribe pattern, never a
  plain `_POST_ROUTES` mutation.
- The `--root` confinement rules: symlinks refused, `Path.is_dir()` follows
  symlinks (CLAUDE.md) — a create route inherits every one of these
  obligations.
- The assets pane's import form and the two defects its browser pass found
  (a control spending the pane's height; a reload discarding a completion
  report) — the empty-state flow will meet both shapes.

### Build

- `POST /api/create`: name validated, path confined to the scanned root,
  symlink and escape refused **before** anything is written; calls
  `ops.init`; then the normal `/api/open` one-way bind. Under `-C` (no
  root), create is absent — the project already exists.
- The empty-state card in Home: create → (open) → import (existing job
  route) → transcribe (existing job route) → seed. Progress over the
  existing bus; completion reports rendered from each op's own return value,
  never wiped by a reload (the pane-bus `reload` rule).
- Standard guards on the new mutation: Host + `application/json`.

### Verify

- HTTP tests: create round-trip; path-escape and symlink refusals; create
  refused under `-C`; picker still lists a broken sibling project.
- Browser: the full first run driven at both dwells from an empty root to a
  seeded project; measure what the flow's controls leave of the pane's
  height (the 60px-cap lesson).

---

## Step 07 — the agent contact sheet (design note first — stops for review)

Note written — see PLAN.md § The agent contact sheet — the design note.
**Nothing is built; this is the step that stops for Tyler's review.** Two of
its questions were answered by measurement rather than argued: the image
channel works end to end (`claude -p --tools ""` puts an MCP tool's
`ImageContent` in front of the model — verified by reading burnt-in text back),
and the ±0.5s-around-each-cut lean loses to per-shot in-points on this film.

**Why.** PLAN.md § Open questions, *Preview delivery in tier 1* — the oldest
still-open question: **an agent cannot watch the film it edited.** `verify`
lets it listen; nothing lets it look. The recorded lean is a contact sheet of
frames at ±0.5s around each cut boundary, which a vision model can actually
check. This is the missing half of the self-check loop for the product's
whole thesis, and it is the one step here that opens a new perception channel
— so it ships as a **PLAN.md design note and stops for review** (the standing
plan-before-building rule). Build nothing in this step.

The note must answer, with measurements where the repo doesn't have them:

- **How the image reaches the model.** The agent panel runs `claude` with
  `--tools ''`, so the agent **cannot Read a file path** — the sheet must
  travel inside the MCP tool result as image content. Verify the installed
  MCP SDK v2 supports image content blocks in tool results, and what the
  size/count limits are, *before* designing around it. The CLI parity
  subcommand writes a file for the human — same op, two deliveries.
- **Frame picking.** ±0.5s around each cut boundary is the lean; the note
  argues it against alternatives (per-shot head frames off `build_shots`,
  the cue in-points — where the pinned-cue machinery already knows what
  matters) and sizes the grid (an hour-long edit has hundreds of
  boundaries; the note needs a budget and a paging story).
- **Containment.** Frames resolve through `media.media_path()` +
  `picture.extract_frame`, cached under `cache/` — the `ops.thumbnail`
  precedent exactly. **No third caller of `media.preview_path()`, ever.**
- **Composition.** magick montage vs ffmpeg tile — measured on real frames,
  including whether burnt-in labels (timeline second, clip_id, boundary
  kind) survive downscaling legibly, since an unlabeled tile is the
  "which source second is this" trap in reverse.
- **Cost.** Frames per second of wall time on the real film, and what is
  cached vs re-cut per call.

---

## Not this plan — named so they stay decided

- **Frame mode used in anger** — usage, not code. The next real video's
  framing round runs through Frame mode instead of the CLI sheet; its defect
  list gets found the way every pane's was (STUDIO.md § Open questions notes
  it has not been used in anger).
- **The publish decisions** (Scream-frame screenshots, HISTORY.md's tailnet
  exposure) — Tyler's calls, tracked in the wiki. Step 02 dissolves the
  screenshot half's dependency but decides nothing.
- **`attribute_speakers` accuracy and forced alignment** — both parked on
  measured evidence (CLAUDE.md; PLAN.md § Open questions). Nothing new has
  overturned either measurement.
- **Packaging (PyPI, `uv tool install`)** — real, but it postdates going
  public and decides distribution questions this plan doesn't need to open.
- **Non-goals hold**: no cloud, no accounts, no plugin system before there
  are two users, no desktop stack.

## Cross-cutting do-not list, concentrated from CLAUDE.md for this work

- No third caller of `media.preview_path()` — posters, tiles, thumbnails and
  contact sheets are `media_path()` + cache-file reads.
- No UI state or disposable record in the manifest; no schema bump anywhere
  in this plan (every new key is additive-optional or cache-class).
- The truth strip and every report draw only what an op returned; the window
  never decides.
- Exit codes prove nothing for melt or ffmpeg-with-libass — check output,
  or pixels.
- A new slow check either says it is running or its silence reads as the
  answer (the blank-chip lesson, HISTORY.md § Frame mode).
- Cite roadmap items by name, never number, in every doc this work touches.
- `ruff check` before every commit; never `ruff format`; never push.
