# Plan: README screenshots + the UI polish they revealed

Written 2026-08-19 from a review of the two screenshots the README ships
(`docs/img/edit-mode.png`, `docs/img/frame-mode.png`, both added in 43fafc8).
This file is a working plan, not documentation: when the work is done, delete
it (or move it under `~/lucid-archive/`), and if any phase is left unfinished,
record that in the wiki README's Open items table — never as a status line in
this file or any other doc.

The phases are ordered so the code changes land before the screenshots are
retaken — the retakes should capture the fixed chips, not the old ones. Phase
1–3 are pure UI polish: no new op, no schema change, no version bump (nothing
new becomes callable). Phase 4 is the retakes and README edits.

**Read the repo's `CLAUDE.md` before starting.** Every trap referenced below
is stated there in full. The ones this plan walks closest to: `ruff format`
is forbidden; `ruff --fix` auto-runs after Python edits and will delete an
import you just added; the full suite takes ~7.5 min and gets backgrounded to
a *file*, never a pipe; UI changes are verified with the
`.claude/skills/verify-live/` harness at both 0ms and ~120ms dwell; and a
probe walks `body *` against `innerWidth`, never a subtree.

---

## Phase 1 — the chips say what they mean (small code changes)

### 1a. Truth-strip chips get nouns

The hero screenshot's most visible content is three unlabeled mysteries:
a bare amber `unknown`, a bare `5:42.3` that disagrees with the header's
`5:36.3 timeline` (correctly — it includes the 6s tail — but nothing says
so), and `1 flag` (of what?).

Sites, all in `src/lucid/web/app.js`:

- `captionLabel()` (~line 382) returns `"no style" | "burned" |
  "not burned" | "unknown"`. Prefix the subject: `"captions: unknown"`,
  `"captions burned"`, `"no caption style"`, etc. Pick phrasings that stay
  short — these chips live in the `#bar` row that has already overflowed
  once at 700px (see verification below).
- The duration chip (~line 424): `setChip($("truth-duration"),
  fmt(bundle.duration.total_seconds), false)`. Change the text to
  `"total 5:42.3"` (or similar) and set a `title` tooltip breaking it out —
  the fields exist and are already used by Finish mode
  (`finish.js:150-151`): `duration.edit_seconds`, `duration.tail_seconds`,
  `duration.total_seconds`. Tooltip like `edit 5:36.3 + tail 0:06.0`.
  Do **not** compute anything new — this is `finish_report`'s bundle,
  display-only.
- The flags chip (~line 429): keep `"1 flag"` short but add a `title`
  listing the flagged kinds. The `flagged` set is built a few lines up from
  the bundle's flag kinds (`canvas` / `captions` / `framing`) — join those.
- `framingLabel()` (~line 396) is fine as-is (`"framing — see Frame"` is
  already legible); leave it.

**Before renaming any string**: `grep -rn` the exact old strings through
`tests/` — `tests/test_webui_http.py` is the one file that touches UI
markup. The chip *texts* are set client-side so HTTP tests likely don't
assert them, but check rather than assume.

### 1b. Assets-pane flags: a negative state says the negative

`src/lucid/web/assets.js` ~lines 213–218. `flag(label, ok, title)` colors
red when `ok` is false but the *label* stays positive for two of them — in
the screenshot, `vo` wears a red chip reading `described`, which reads as
"described, and that's bad". The video/audio pair already does this right
(`"video"` / `"no video"`). Make transcript and described match:

```js
flags.append(flag(clip.transcript ? "transcript" : "no transcript", ...));
flags.append(flag(clip.described ? "described" : "not described", ...));
```

Keep the existing `title` tooltips. The `described`/`transcript` *API
fields* (ops layer, `test_ops_assets.py` etc.) are untouched — this is
label text only. Watch the pane-height economy: the labels get a few
characters longer, and CLAUDE.md records two incidents of a control eating
`#assets-list`'s height; confirm the flag row still wraps sanely on the
narrowest pane width.

### 1c. Properties pane stops printing raw JSON

`src/lucid/web/properties.js`, `fmtValue()` (~lines 47–59). Currently an
array of strings renders as `["vo","cold-open",...]` and an object as
`{"applied":false}`. Change:

- Array of primitives → `value.join(", ")` (keep `[]` → `"–"` or `"none"`).
- Flat object of primitives → `k: v` pairs joined with ` · `
  (so `pack` reads `applied: no`).
- Anything nested → keep the `JSON.stringify` fallback; this is an
  inspector, and lying about structure would be worse than being ugly.

### 1d. Decision — doc citations in user-facing copy

Two strings cite PLAN.md sections at the user: the agent panel intro
(`agent.js:685` — "…and nothing else (PLAN.md § The agent panel…)") and the
timeline hint (`index.html:375-376` — "…no lane the render cannot produce
(PLAN.md § The timeline)").

**Recommendation: keep the behavior sentence, move the `(PLAN.md § …)`
parenthetical into a `title` attribute** on the same element. The guarantee
("the agent reaches the timeline only through lucid's own MCP tools") is
the user-facing content; the citation is for the operator and survives as a
tooltip. This is a house-style call — if Tyler has said he wants the
citations visible, skip this item; nothing else depends on it.

---

## Phase 2 — timeline labels stop degrading to noise

In the hero screenshot the V2 lane shows label fragments of 1–3 characters
("c", "re", "col") and the CC lane is unreadable glyph soup. All in
`src/lucid/web/timeline.js`:

- **Gate clip labels on block width.** `buildLaneRow` (~line 390) appends a
  `.clip-label` span (or sets `textContent`) unconditionally;
  `buildPictureRow` (~line 533) does the same via `shotLabel(shot)`. Add a
  constant next to the existing measured ones (`TRIM_MIN_BLOCK_PX`,
  `THUMB_MIN_BLOCK_PX` ~lines 89–198) — e.g. `LABEL_MIN_BLOCK_PX = 40` —
  and skip the label when `blockWidth` is below it. Every block already
  carries a full `title` tooltip (lines 386, 517, 604), so no information
  is lost, and an unlabeled colored block reads better than "c".
- **Gate CC cue text on zoom.** `buildCaptionRow` (~line 289) renders one
  block per cue with its text. Below the same width threshold (per-block,
  same rule as above), render the block empty; `block.title` (line 308)
  already carries the text.
- Note the constants are described in-file as *measured, not picked* — pick
  40px by looking at a real render at default zoom, and adjust to where
  labels first become readable, then note the measurement in the constant's
  comment the way its siblings do.

**Traps this walks near** (both in CLAUDE.md): never rebuild the node a
live gesture owns — these changes are render-time only and must stay that
way (no re-render on hover); and the drag-trim / click-to-seek gestures on
these same blocks mean the verify-live pass must drive clicks and a trim at
both 0ms and ~120ms dwell after the change.

---

## Phase 3 — Frame-sheet polish

All in `src/lucid/web/frame.js` unless noted.

- **Chip consistency.** In the screenshot, `#frame-chip-cuts` ("12/54 cuts
  framed") renders visibly larger/rounder than the two amber chips beside
  it. All three are `span.chip` (`index.html:359-361`) and all are set via
  the same `setChip`, so the difference is CSS — diff `.chip` vs
  `.chip.warn` in `app.css` (~lines 748, 881) in a real browser and unify
  the geometry so only *color* distinguishes warn from ok.
- **Rect caption redundancy.** Every tile carries the rect twice — burnt
  into the sheet PNG *and* appended as a caption (`frame.js:405`), and
  within a row all three captions read identically. A sheet row is a
  *window* (one rect per row by construction — HISTORY.md § The
  thirty-nine windows, reviewed), so: render the rect once in the row
  header (next to `window N of M`), and drop the per-tile caption **when
  all samples in the row agree**. Keep the per-tile `pane` caption
  (line 406) — the dashed split rect is per-row too but its presence is
  the point. **Verify the data shape first**: fetch a real
  `/api/reframe/sheet` payload and confirm `sample.crop` is constant
  within a row before deleting the per-tile caption; if it can vary,
  keep the caption only on tiles that differ from the row's head.
- **Precision.** `11.719s stale` (chip, ~line 183) and
  `src 0.000s–20.395s` (row header) → one decimal in the visible text,
  full value in `title`. Display-only; the frame-of-tolerance semantics
  in the coverage math are untouched.
- **The shot-numbering gap.** Rows run #0, #2, #3 — #1 is silently absent,
  which reads as a rendering bug. **First find out why** (judge the finding
  before shipping copy for it — this is the repo's own rule): read where
  the sheet rows are built server-side (`ops.reframe_sheet` /
  `build_shots`) and determine what filters a shot out — likely a card or
  still, which are never cropped. Then either render a one-line muted
  placeholder row ("shot #1 — card, never cropped") or add a count line
  above the rows ("showing N of M shots; cards and stills are never
  cropped"). Do not guess the reason into the copy.
- **Optional / lowest priority:** the yellow burn-in text on the tile PNGs
  is illegible at rendered size. That text is baked by the Python sheet
  renderer, not the browser — enlarging it is a server-side change to the
  tile drawing. Skip unless everything else lands early.

---

## Phase 4 — retake the screenshots, extend the README

### Ground rules for all captures

- **Never work in Tyler's real projects.** Copy the project into a scratch
  under `~/lucid-work/readme-shots/` (the convention — `$HOME`, so melt's
  flatpak can see it) and serve from the copy. Manifests store absolute
  paths — after copying, grep the copy's `*.json`/`*.otio` for paths
  pointing back at the original and rewrite them, or media/renders will
  resolve into the source project.
- Capture with the verify-live harness (`node cdp.mjs shot out.png`) at
  **1400×900**, matching the existing images. Caveat from the skill:
  headless Chrome does not composite `<video>` into a capture — the
  preview's picture layer is canvas-drawn so it *does* capture, but eyeball
  every PNG for a live preview frame before accepting it, and remember a
  readback/screenshot proves neither currency nor visibility (CLAUDE.md).
- Light theme, like the existing pair. (A dark variant per image via
  `<picture media="(prefers-color-scheme: dark)">` is a nice-to-have;
  defer unless time allows.)
- Keep files roughly the current size (~300KB PNG); `docs/img/` naming:
  `edit-mode.png`, `frame-mode.png`, `finish-mode.png`.

### 4a. `frame-mode.png` — show actual crop windows

The current image undercuts its own caption: every visible window is
`0,0,1920,816`, the full-frame default, so nothing is cropped and the drawn
rect reads as a border. Retake from the **vertical project** — the only
project holding the film's approved vertical framing. It was deleted
2026-08-12 but `~/lucid-archive/vertical/` rebuilds it exactly (read that
directory's own instructions). Rebuild into `~/lucid-work/readme-shots/`,
open Frame mode, Build sheet, and capture a viewport showing: real vertical
crop rects drawn on widescreen frames, at least one **stacked-split** row
(dashed lower pane — the vertical has splits among its 55 windows), and the
coverage chips populated. Scroll so the first visible rows are cropped
shots, not full-frame ones.

### 4b. `edit-mode.png` — the agent mid-edit, a live frame

The product's pitch is agent-driven editing and the current hero shows the
agent panel idle. Retake with:

- The agent panel mid-conversation: a real request ("cut the stumble at
  …"), the tool activity, and the op's return value visible. The panel
  needs a working `claude` CLI; the MCP config generation is automatic
  (and its PATH trap is already fixed — see CLAUDE.md if the panel shows
  `tools: []`).
- A playhead moment whose preview frame is visually alive (not the black
  title card).
- A project with cues on the timeline so V2 is populated — the film
  project copy works (38 cues, 1920×816). Source it from
  `~/lucid-final-cut/proj` **as a copy** (see ground rules; never touch
  the original).
- The truth strip may keep honest warnings — after Phase 1 they are
  legible — but prefer a state where `captions` resolves to something
  better than "unknown" if one is cheap to reach.

### 4c. `finish-mode.png` — new

The README names three modes and shows two, and Finish is where the
strongest claim lives (verify, the duration breakout, the render playing in
the page). Capture Finish mode on the same project copy after an
`export --render` + `verify`: the report visible, the finished file
playable. Place it in the README under the **Render verification** bullet,
same pattern as the frame-mode image under Reframing, with alt text in the
same voice (e.g. "Finish mode: presets, the verify diff against what the
timeline should play, and the finished render playing in the page").

### 4d. README edits

- Insert the finish-mode image (4c).
- Re-check both existing alt texts still describe the retaken images;
  update if the visible content changed (the frame-mode alt already
  promises "every crop window drawn on the source's own frames" — after 4a
  it will finally be true).
- **Decision — the *Scream* footage.** Every screenshot is built from
  recognizably copyrighted film frames. Recommendation: proceed with the
  same footage — it is Tyler's own video essay and his call to make — but
  flag it in the handoff summary so the decision is made consciously
  before the repo is shown anywhere public. Do not silently switch
  footage; a different project would misrepresent the real workflow.

---

## Verification (every phase)

1. **Lint:** `ruff check` only. Never `ruff format`.
2. **Suite:** background the full run to a log file and poll the file's
   summary line (`uv run pytest > /tmp/…` is wrong twice — use
   `~/lucid-work/` or the job tmp dir, and never pipe to `tail`). Expect
   ~7.5 min. On a headless session the four melt-rendering tests in
   `test_server_stdio.py` fail on "no display" — that's environment, not
   regression; confirm by the failure text, not by hunting.
3. **Browser pass** (Phases 1–3): the verify-live harness, real page, both
   dwell speeds for anything near a gesture (timeline blocks especially).
   Overflow probe walks **`body *`** against `innerWidth` — not a subtree —
   at 1400px *and* ~700px: Phase 1 makes several `#bar` chips longer, and
   `#bar` is exactly where the last overflow hid.
4. **Chip strings:** after renames, grep `tests/` and `web/` for the old
   strings to catch any straggler that composes them.
5. Commit per repo conventions (`fix:` for the chip/label changes,
   `chore:` for screenshots + README), push to Gitea `origin`. No version
   bump — nothing new is callable.
