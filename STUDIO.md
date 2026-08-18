# lucid × Studio — the workflow-first reshape

**The direction, set by Tyler 2026-08-17: lucid's window reorganizes around the
workflow — Home · Edit · Frame · Finish — with direct manipulation on the
timeline and a truth strip that makes the film's real state ambient.** The
approved mockup is the visual contract:
<https://claude.ai/code/artifact/ec8ef426-ee7f-40d7-9d6f-0d0bfab2e7d4> — four
detailed screen mocks with numbered callouts, plus the rules kept/amended and
the build order this file expands. This is the one document for that work;
DAYDREAM.md § Build order is superseded by § Build order here wherever the two
conflict (they mostly do not — this plan is *how the window works*, Daydream
parity was *what the window contains*).

**Why**, in one paragraph, so a fresh session doesn't have to re-derive it:
an audit on 2026-08-17 walked the real workflow (footage in → exported film
out) against what the page can post. The window reaches **seven mutations**
(`cut`, `restore`, `cue add`, `cue rm`, `undo`, `render`, `clip role`) plus
the agent prompt, out of ~40 operations in `ops.py`. Everything else —
framing, cards, caption styling *and burning*, verify, reel, packs, import,
transcribe — is CLI/agent-only. The captionless-film incident (HISTORY.md
§ The film had no captions in it) is what this shape produces: burning is a
separate CLI step nothing in the window mentions, so every surface read clean
for three days. The fix is structural: the window carries the workflow, not
just the timeline.

## How to work this plan

- **One numbered step per session.** Each step is independently shippable and
  ends with the verification listed in it. Do not start step N+1 in the same
  session that shipped step N unless the step says it is small.
- **Every step starts with its "Verify first" list** — signatures and
  behaviours to read before writing code. This repo's design notes have
  repeatedly overturned their own premises on measurement; the lists exist
  because this file's claims about code were checked on 2026-08-17 and code
  moves.
- Repo conventions bind throughout: every MCP tool gets a CLI subcommand;
  tools register with `@_tool()`, never `@mcp.tool()`; tests speak to the real
  server (`tests/test_server_stdio.py` over stdio, `tests/test_webui_http.py`
  over a real socket); `ruff check` is the gate and `ruff format` is
  forbidden; the web UI draws and plays, never decides. CLAUDE.md § Conventions
  has each with its reason.
- Status of this work lives **only** in the wiki's Open items table. This file
  never carries a status header.
- The verified bar for every UI item: the real project, in a real browser
  (wiki `tooling.md` § Headless browser), every click driven at **0ms and
  ~120ms dwell** (HISTORY.md § The dwell-timing lesson). Before using any
  dogfood project, run `film_check` — four scratch copies have already been
  the wrong cut while every check passed (CLAUDE.md, last bullet).

## Design invariants — what the mockup does and does not change

**Law, unchanged (the mockup was designed inside these):**

1. **The window never decides.** Every gesture below resolves to an existing
   `ops` call or a new one that CLI and MCP also get. Drag-trim is a prettier
   `cut_by_time --plan`; nothing in JS computes an edit.
2. **Word-index addressing.** Snap targets are word boundaries; cues survive
   re-cuts exactly as now. No persisted coordinate is timeline time
   (`cut_by_time` converts at call time and stores source time — its
   docstring states this contract).
3. **No lane `export` cannot produce.** Modes widen when the model does.
4. **Local, no cloud, no accounts, no build step.** ES modules flat out of
   `/static/`, CSP `default-src 'self'`, no framework, no bundler.
5. **Plan-before-apply**, extended: agent plans render as struck words with an
   Apply button, mutating gestures confirm through the plan echo.

**Amended, deliberately (each was re-examined 2026-08-17, not drifted past):**

- *"Lanes are projections of one `Edit`" stops being a ceiling.* Its
  justification — auto-editor's silent multi-source degrade — expired when
  multi-source moved to melt. Widening is still gated behind a design note
  per lane (step 05 is the first), never done casually.
- *CLI exclusivity ends; CLI parity stays.* Frame and Finish surface what only
  the terminal had. The CLI remains how everything is scripted and debugged.
- *"Not a desktop app" softens to "not a desktop stack."* Same page, wrapped:
  `lucid open` = server + app-mode browser window + session restore. No
  Electron, no Tauri yet — PLAN.md § Not a desktop app's reasoning holds; only
  the launch ergonomics change.
- *Timeline-addressed state gets a designed answer eventually* (music in/outs,
  transitions are timeline-shaped). Step 05 writes that design note; nothing
  before it touches the model.

**The organizing concept.** The top bar gains a mode switcher: **Edit** (the
current workspace, plus direct manipulation), **Frame** (the reframe sheet as
a view), **Finish** (export as an honest flow). **Home** is the picker, grown
into a project gallery. Riding all modes: the **truth strip** — duration,
canvas, caption state, open-flag count — ambient `film_check`-class facts in
the top bar, each warning chip linking to the mode that fixes it. The agent
pane stays in Edit and collapses to its rail elsewhere; `⌘K` focuses the
composer from any mode.

---

## Step 01 — the truth strip and Finish mode

Shipped — see HISTORY.md § The truth strip and Finish mode.

The highest value per line of code, and it closes the captionless-film class
of failure. Ships alone.

### Verify first

- `ops.export(path, output, *, export_format="kdenlive", fps=None,
  preset=None, resolution=None)` — confirmed 2026-08-17. Rendering is
  `export_format=None`. Presets: `youtube`, `web`, `custom`, `tiktok-reels`;
  canvas refusal comes from `_check_preset_canvas`.
- `ops.add_captions(path, output, *, clip_id=None, preset=None, …,
  burn=None, burn_output=None)` — confirmed. `burn` takes the rendered file;
  read the body to confirm whether `burn_output` defaults or must be named,
  and whether burning re-encodes in place or writes a new file.
- `ops.film_check(path, reference=None, *, reset=False, plan=False)` —
  confirmed. Read its return keys before drawing them.
- Read `ops.verify` and `ops.check_frames` signatures (not re-verified for
  this file) — the post-render pipeline calls both.
- `webui.py`: `RenderJob` (bound in `_bind_singletons`, line ~1803),
  `_handle_render_start`/`_handle_render_stop` (~1399/1446), the SSE bus.
  The pipeline below extends this job, it does not add a second one.
- How `status`/`check_frames` get `expected_duration` (the tail is not in
  `Edit` — CLAUDE.md § Tail time).

### Build

**1. `ops.finish_report(path)` — a composition op, no new derivation.** The
`ops.properties` precedent exactly: it assembles existing answers and invents
none. Fields:

- `duration`: edit duration, tail seconds if `TAIL_KEY` present, and their
  sum (the `expected_duration` the render must hit).
- `canvas`: stored canvas or footage fallback, plus per-preset compatibility
  — for each export preset, `ok` or the refusal message with the fix
  (reuse the same in-module helpers `export` uses; do not restate the
  cross-multiplied aspect check).
- `captions`: whether `caption_style` exists, the resolved font and whether
  it resolves in one pick (`captions.font_match` / `font_report` — report
  `resolves_to` *and* the caveat that only a measured render settles the
  face), and — critically — **what the last render did about burning** (see
  the render log below). Absent log ⇒ `burned: "unknown"`, drawn as a
  warning, never as clean.
- `picture`: cue count, pinned count, orphans (`build_shots` refusal surfaces
  as `shots_error` — report it, never raise; `off_timeline`'s policy).
- `marks`: `unspoken_ls` counts — applied vs stale (stale = kept, never
  applied; drawn as a warning).
- `seams`: `transcript_checks` overlap count, and how many sit near a kept
  edge (reuse the reel's edge logic if extractable; otherwise total only —
  do not invent a new nearness rule for this).
- `flags`: the rolled-up count the truth strip shows — every warning-class
  item above.

MCP tool + `lucid finish-report` CLI subcommand (parity). Composition proved
the `properties` way: a monkeypatch test makes one component lie and watches
the lie surface.

**2. The render log — how "did the burn happen" becomes answerable.**
`cache/renders.jsonl`, one line per pipeline run: output path, preset, stages
run with outcomes (`export` → `burn` → `check_frames` → `verify`), timestamps,
the `expected_duration` at render time. A **cache artifact, never a manifest
key** — `caption_style` says what a burn *would* draw; this says what one
*did*. `finish_report` reads the last line for the current project.

**3. The pipeline.** Extend `RenderJob` to run stages: `export(preset=…,
export_format=None)` → if the Finish flow asked for it, `add_captions(burn=…)`
→ `check_frames` → `verify`, each reported over the existing SSE bus as it
completes, each outcome appended to the render log. Burn default: **on when
`caption_style` exists**, a visible checkbox either way. A stage failure stops
the pipeline and reports; exit codes prove nothing for melt (CLAUDE.md — check
output, not codes).

**4. The web surface.**

- `GET /api/finish` → `finish_report`. The Finish view (`finish.js`, a new
  module on the `properties.js` pattern) draws: preset cards (refusing preset
  shows its message + the fix, mockup screen 04 callout 1), the "what this
  render will contain" manifest (callout 2), the burn checkbox, Render, and
  the post-render report when the job's SSE events land.
- The truth strip: top-bar chips fed by `/api/finish`, refreshed on the
  existing `project-changed` SSE (the `_revision` watcher already covers the
  manifest — CLAUDE.md). Chips: duration · canvas · caption state · `N flags`.
  A warning chip is a link: captions → Finish, framing flags (step 03) →
  Frame.
- Mode tabs render in the top bar now (Edit active, Frame disabled until
  step 03, Finish live) so the shell doesn't reflow twice.

### Verify

- `tests/test_webui_http.py`: `/api/finish` over a real socket; a mutation
  POST without `application/json` still 400s; the picker/bind order still
  holds (`/api/finish` before `/api/open` under `--root` must 400, the
  `_route_picker` rule).
- `tests/test_server_stdio.py`: `finish-report` reachable over stdio.
- The composition monkeypatch test.
- Browser: truth strip updates when a CLI mutation touches the project while
  the page is open (the `_revision`-watches-the-manifest case — set a caption
  style from the CLI, watch the chip move).
- The four melt-rendering stdio tests still fail-by-refusal without a desktop
  (JSONDecodeError on the refusal text) — that pattern is the environment,
  not a regression.

---

## Step 02 — direct manipulation on the timeline

Shipped — see HISTORY.md § Direct manipulation on the timeline.

The Premiere feel: hands on the clips. Everything here posts to existing
mutations; the only new server code is thin endpoints.

### Verify first

- `ops.cut_by_time(path, *, spans, pad=0.0, confirm_suspect=False,
  plan=False)` — confirmed 2026-08-17. Spans are `[start, end)` in *current
  render/timeline seconds*; all spans in one call resolve against the
  pre-call timeline; overlapping spans in one call are refused. Suspect-word
  flags arrive on the plan; `confirm_suspect` acknowledges them.
- `ops.restore` signature and its bounds (`Edit.gaps`; refuses once a clip's
  segments stop being contiguous — CLAUDE.md § `vo_extend`).
- `ops.cue_add` / `ops.locate` signatures — locate maps a timeline instant to
  words (singular vs plural span rule: CLAUDE.md).
- `timeline.js`: the cue-drag machinery (`cueDrag`, `handleLanesMouseDown` at
  ~line 908) — the new gestures extend this dispatch, they do not add a
  second mousedown listener; and the hard-won rule that **you only redraw the
  node a gesture owns while it is live** (HISTORY.md § The cue-drag browser
  pass, and six defects).
- `transcript.js`'s show-cuts rendering — the struck-word style the agent
  plan display reuses.
- `agent.js`'s stream-json parsing — where `tool_use`/`tool_result` events
  are already read for the checklist.

### Build

**1. Endpoints.** `POST /api/cut-time` → `ops.cut_by_time` (body: `spans`,
`plan`, `confirm_suspect`); `/api/cut` and `/api/restore` already exist. All
mutations keep the Host + content-type guards.

**2. Drag-trim** (mockup screen 02, callout 7). Handles appear on hover at V1
block edges. Dragging an edge *inward* selects a removal span; on release,
post `cut_by_time` with `plan: true`, draw the echo popover — the resolved
words ±3 neighbours, any suspect-duration flags — with Apply/Cancel; Apply
re-posts with `plan: false` (plus `confirm_suspect` if flagged). Dragging
*outward* over a gap offers restore of that gap's material (bounded by
`Edit.gaps`; if `restore`'s granularity is the whole cut, the popover says so
and offers exactly that — do not invent partial restore in JS). The popover
is clamped by `dom.js`'s `clampFloating` — **there is exactly one clamp;
hand it bounds** (CLAUDE.md).

**3. Razor = select-a-range** (callout 5). With the razor tool active, drag
across any lane background to select a timeline range, drawn as a shaded
band. Release opens a two-verb popover: **Cut this range** (`cut_by_time`
plan flow as above) or **Place b-roll over it** (resolve the range start to a
word via `ops.locate`, prefill the existing cue-placement flow). This is
deliberately Daydream's right-click-drag range, not a Premiere blade-split —
lucid's model has no "split into two clips that both stay"; do not fake one.

**4. Snap.** A toggle in the timeline toolbar. Snap targets: word boundaries
(from `timeline_view`'s words, already loaded), cue edges, the playhead.
Tolerance is **a frame, never an epsilon** (the rule `reframe_coverage`
already learned, CLAUDE.md); a magnet radius of ~6px at current zoom, whichever
is larger on screen.

**5. Drag-from-assets to V2** (callout 6). HTML5 drag from an assets-pane row
onto the V2 lane; a ghost block tracks the drop point; release resolves the
drop x to a word (`locate`) and opens the cue confirm with the standard echo.
The dragged thing is the **asset**; the cue's addressing clip is the
transcript track — the `clip_id` vs `asset` trap has already cost a draft
(CLAUDE.md § A shot's addressing clip is not its footage).

**6. Agent plans on the page** (callout 4 — `cut --plan` gets a face). When
`agent.js` sees a `tool_result` for a cut-family tool that was called with
`plan: true`, it emits `agent-plan` on the ctx bus with the payload verbatim.
`transcript.js` strikes the planned words in the show-cuts style plus a
distinct "proposed" tint, and shows Apply/Dismiss; Apply posts the same op
with the same arguments, `plan: false`. The page renders **ops' own return
value**, never a re-derivation; if the payload lacks word indices, widen the
op's plan echo, not the JS.

### Verify

Browser pass on the real project, every gesture at 0ms **and** ~120ms dwell:
drag-trim in/out, razor range → cut and → cue, snap on/off, asset drag, agent
plan → Apply. During any live gesture, assert the DOM node under the pointer
is never rebuilt (the silent dropped-click failure). Probe `body *` for
overflow at 700/900/1200px widths — the probe scopes to the page, never to
where a bug is expected (HISTORY.md § The web UI review). HTTP tests for
`/api/cut-time` including the overlapping-spans refusal surfacing as a 4xx
body, not a 500.

---

## Step 03 — Frame mode

Shipped — see HISTORY.md § Frame mode.

The reframe instrument becomes a view: coverage findings lead, one row per
window, approve or adjust in place. (Mockup screen 03.)

### Verify first

- `ops.reframe_sheet` / `reframe_detect` / `reframe_coverage` signatures and
  return shapes — all three exist in `ops.py` and `server.py` (confirmed);
  read what `reframe_sheet` writes (tile files? where?) and what `--extremes`
  costs (~0.5s/probe, needs `LUCID_FACE`).
- `ops.reframe` — the write path (`--src-start`, rect, pane).
- `ProxyJob` in `webui.py` — the job pattern the sheet/detect jobs copy.
- The sheet vocabulary: rows are **windows, not placements**; `windows` on a
  row is the placement's count (the preview/render tell); `moments` are
  fractions of the stretch; `worst_offset` is read **beside** `multi_face`,
  never after it. All CLAUDE.md § Per-shot framing — re-read that whole
  bullet before drawing anything.

### Build

- **Jobs**: sheet generation and `reframe_detect` run as jobs on the
  `RenderJob`/`ProxyJob` pattern (they cost seconds-to-minutes and need
  `LUCID_FACE`), progress over SSE.
- **Endpoints**: `GET /api/reframe/coverage` → `reframe_coverage`;
  `POST /api/reframe/sheet` starts the job; `GET /api/reframe/tile/<…>`
  serves the sheet's own tile files from cache — the tiles are the review
  instrument (a wrong window *reads as framing in motion* on a watch;
  CLAUDE.md), so the view draws **the sheet's tiles**, never its own canvas
  rendering of a rect over a `<video>` frame. `POST /api/reframe` writes.
- **The view** (`frame.js`): coverage chips lead (stale seconds, missing-step
  boundaries, worst-offset warnings — `stale_seconds`, never
  `default_seconds` beside it). Rows: source tiles with drawn windows, split
  rows with both rects and `pane_overlap` on the row, chips for
  detector-vs-hand provenance. Actions: **Approve** (writes nothing —
  report-only is the standing precedent), **Re-frame…** (nudge buttons moving
  the rect by source-pixel steps + a direct rect entry, posting
  `ops.reframe`; draggable rects on tiles are a later nicety, not this
  step), **Detect gaps** (the detect job; `apply` stays off — it proposes,
  the sheet judges).
- Truth strip: framing flags (stale seconds > 0, step gaps) join the flag
  count, linking here.

### Verify

HTTP tests for the endpoints (tile route confined to the cache dir — no new
`preview_path` caller, no path escape). Browser pass: a full review of one
real clip's rows against the same project's CLI sheet — identical tiles,
identical counts. The detect job on a machine without `LUCID_FACE` refuses
legibly in the view (the melt-refusal precedent: refusal text drawn, not a
spinner forever).

---

## Step 04 — `lucid open`, Home, and session restore

Shipped — see HISTORY.md § Home, and the come-back-later step.

The "come back later" step. (Mockup screen 01.)

### Verify first

- `webui.py`'s picker: `_route_picker`, the four scan outcomes
  (`ok`/`needs_migration`/`unreadable`/`error` — one broken project must
  never hide the rest), the one-way `_bind_singletons` bind, and the
  symlink/`--root` confinement rules (CLAUDE.md § The multi-project picker).
- What the scan already computes per project (it calls `ops.status` with a
  handler) — the card chips below should ride that, not add a second scan.
- Which chromium-family browsers this box has: wiki `tooling.md` § Headless
  browser.

### Build

- **`lucid open [--root DIR | -C PATH]`**: start the webui (ephemeral port),
  then launch `$LUCID_BROWSER` if set, else the first of the
  chromium-family binaries found, with `--app=<url>`; fall back to
  `xdg-open`. Print the URL either way. `-C` opens straight into the
  project; `--root` opens Home. The existing `--root`+`-C` mutual refusal
  stays.
- **Session state**: `cache/session.json` per project — playhead, zoom,
  timeline scroll, pane collapse states, active mode, selection. Debounced
  `POST /api/session` (same guards as every mutation, but it never bumps
  `_revision` and never fires `project-changed` — the agent-thumbs
  precedent: it touches no timeline). `GET /api/session` on load restores.
  **Cache, never manifest** — no schema bump, disposable by design.
- **Home**: the picker grows cards. Chips from the scan's existing `status`
  payload (duration, segment count, schema state — `needs_migration` renders
  as a card action, and `lucid migrate` stays explicit and user-triggered:
  **never migrate on open**, and on this box never migrate Tyler's data
  without asking). Poster: a bound session writes `cache/poster.jpg` via
  `ops.thumbnail` on first load; the picker serves it **only if the file
  exists** — the picker never binds, never thumbnails, and never gains a
  media resolver (the containment: `preview_path`'s caller list does not
  grow; a poster is a cache file read, path-confined to the scanned root
  with symlinks refused as the scan already refuses them). Resume line from
  each project's `session.json`, read-only.

### Verify

HTTP tests: `/api/session` round-trip; session POST does not bump
`/api/view`'s revision; picker with one broken project still lists the rest
(exists — extend for the new fields); poster route refuses a path outside
the root and a symlink. Manual: `lucid open`, close the window, reopen —
playhead/zoom/mode restored.

---

## Step 05 — the A2 design note (a note, not a build)

The note was written 2026-08-17, reviewed and approved 2026-08-18, and the
build shipped the same day — PLAN.md § The A2 music lane — the design note;
HISTORY.md § The A2 music lane, built. The requirements below are what the
note had to answer, kept for the record.

The only step that touches the model, so it ships as a PLAN.md design note
and **stops for review** — the standing plan-before-building rule.

The note must answer, with measurements where the repo doesn't already have
them:

- **Render**: what an A2 music lane needs from `mlt.py` — a second audio
  track is two ordinary MLT entries (the tail precedent suggests no new
  writer concept; verify against a hand-built document rendered through
  `melt`, checking `declared_frames` agreement).
- **Addressing**: what coordinates a music in/out is stored in. The music-bed
  history is the cautionary prior — cues carrying explicit lengths tuned to a
  runtime were invalidated wholesale by a ~12s append (PLAN.md § The property
  everything below defends). Candidate: anchor the music start to a word
  index like any cue, and make *duration* the timeline-shaped part, with a
  stated re-derivation rule on edit. The note must argue this against at
  least one alternative.
- **Ducking**: out of scope and why (the Billy/Stu prior: 74–85% overlap, no
  seam to duck into — blocked by the recording, not the model).
- **The gate**: the lane draws only when `export` renders it — the standing
  rule, restated against this lane specifically, with the silent-degrade
  failure it guards named.
- **What `Edit` is afterwards**: whether A2 lives beside `Edit` (the
  `TAIL_KEY` precedent: project state, `expected_duration` already stopped
  reading the edit alone) or in it. Recommend beside; argue it.

---

## Cross-cutting

**Do-not list, concentrated from CLAUDE.md for this work specifically:**

- No third caller of `media.preview_path()` — ever. Posters and tiles are
  cache-file reads.
- No UI state in the manifest; no schema bump for any of this (session,
  render log, posters are all cache).
- No lane, mode, or chip that claims something `export` doesn't do. The truth
  strip draws only what an op returned.
- Never infer a `<video>` failure reason in JS (`media.playability()` has
  it); never read a colour token from JS (`light-dark()` text is silently
  ignored — read `getComputedStyle(el).color` off an element).
- `el.hidden` needs the companion `[hidden]` CSS rule for anything this
  stylesheet gives a `display:` — new popovers and mode panels included.
- An export preset checks the canvas and refuses with the fix named; it never
  sets project state.
- Cite roadmap items by name, never number, in every doc this work touches.

**Docs, at each step's end** (the wrapup discipline): HISTORY.md gets a named
section per shipped step; this file's step gains a one-line "shipped — see
HISTORY.md § <name>" pointer; the wiki Open items row updates; CLAUDE.md
gains only *traps discovered*, not restatements of this plan.

**Definition of done for the reshape as a whole:** the walk that produced the
audit — footage in, exported film out, captions burned, framing reviewed —
completes **in the window**, with the terminal never required (still always
available). The truth strip's flag count on the real project reaches zero by
actions taken in the window, and the render log shows a pipeline run whose
burn stage ran.

Walked 2026-08-18 — see HISTORY.md § The Studio reshape's own walk, end to
end. Met: 1 flag → 0 by a Finish render whose log records `burn: done`, with
the burn confirmed in the render's own pixels rather than from its status
line. Two defects came out of the walk rather than out of a step, both fixed
in the same session — HISTORY.md § The agent panel had no tools at all,
§ The window plays its own render. What the walk does **not** clear: import
and transcribe are still not window mutations, so "footage in" holds only
through the agent pane.

## Open questions, deliberately left

- Whether Apply-from-agent-plan should also cover `reframe` proposals (step
  03 keeps detect's apply off; the sheet is the judge — revisit only after
  the Frame mode has been used in anger).
- Clip filename labels on V1 blocks (held back in DAYDREAM.md § Timeline
  because every other surface names blocks by `clip_id`) — decide when
  drag-trim makes blocks something you look at longer.
- Whether `lucid open` should eventually own a tray/launcher presence.
  Nothing here depends on it.
