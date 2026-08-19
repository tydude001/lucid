/**
 * frame.js — the Frame view: `GET /api/reframe/coverage` drawn as three
 * coverage chips, the sheet/detect job triggers and their live per-job SSE
 * progress, and one row per WINDOW the sheet drew — never a placement, and
 * never a hand-drawn canvas rect (CLAUDE.md § Per-shot framing, read in
 * full before touching this file):
 *
 *   - A sheet row is a window, not a placement. `row.windows` is the
 *     PLACEMENT's total window count (shown as context — "window n of
 *     windows"); `lastSheet.count` is windows, `lastSheet.placements` is
 *     placements. Never conflate the two.
 *   - The tile a row shows is the sheet's OWN drawn-on PNG, fetched through
 *     `/api/reframe/tile/<basename>` and rendered as a plain `<img>`. This
 *     file never opens a `<canvas>` and paints a rect over a `<video>`
 *     frame itself — a wrong window reads as framing in motion on a watch,
 *     invisibly, which is the whole reason the sheet exists as the review
 *     instrument.
 *   - `worst_offset` is drawn BESIDE `multi_face`, never after it alone —
 *     a two-face frame's worst offset sits between both faces, where
 *     nobody is.
 *   - Coverage chips read `stale_seconds`/`steps`, never `default_seconds`
 *     (the centre crop doing what it always did — not a defect).
 *   - A split row draws `pane_overlap` on the ROW, reported, never enforced.
 *   - Approve writes nothing at all — no fetch, purely local UI state.
 *   - Detect proposes; `apply` is never sent from here (the job and the
 *     endpoint both refuse it independently — see the backend report).
 *
 * The `finish.js` two-export module contract exactly: `init(ctx)` wires
 * listeners once, `update(state)` marks coverage owed. The sheet/detect
 * jobs are NOT re-triggered by update() — they stay whatever they were,
 * keyed on their own buttons, exactly like finish.js's render job.
 *
 * **Coverage is fetched when this view is looked at, never merely when the
 * project reloads.** `reframe_coverage` decodes every placed clip for its
 * scene-cut scan — 5.5s measured on the film, uncached, per call — and
 * `update()` runs on every `project-changed`, so re-fetching there made
 * every cut taken in Edit mode pay for a scan of a view nobody had open
 * (twice per page load, once per mutation). That is the exact cost
 * `finish_report`'s framing is opt-in to avoid (CLAUDE.md), and this pane
 * had reintroduced it. `update()` now sets `coverageStale`; the fetch runs
 * if Frame is already on screen, and otherwise when `app.js` emits `mode`
 * for it. The two rules that outrank the saving: the scan still says
 * "scanning for cuts…" while it runs, and a project with no placements
 * says so rather than drawing a blank chip.
 */

import { $, el, secs, clampFloating } from "./dom.js";

let ctx = null;

let lastSheet = null; // the full "done" event payload from the reframe-sheet job
let lastDetect = null; // the full "done" event payload from the reframe-detect job
let sheetBusy = false;
let detectBusy = false;
let lastState = null; // the last /api/view payload, read only for `shots`
let coverageStale = true; // is a coverage fetch owed? set by update(), paid
// for when this view is on screen — the scan is 5.5s of decoding per call,
// so it rides being *looked at* rather than every project reload.

// Ephemeral, both of them — reset whenever update() runs (a fresh project
// state), never persisted anywhere. Approve is pure bookkeeping for one
// sitting (STUDIO's "report-only is the standing precedent," restated for
// the reviewer's own use); reframedKeys tracks which windows this session
// wrote a rect for so their tile strip can say it is showing a stale
// picture until the sheet is rebuilt, cleared only when a fresh sheet
// actually lands.
let approvedKeys = new Set();
let reframedKeys = new Set();

let openPanel = null; // the currently-open Re-frame… panel element, if any

const STEP_FINE = 4;
const STEP_COARSE = 32;

/* -- small local helpers ---------------------------------------------- */

function basename(path) {
  return String(path).split("/").pop();
}

function tileUrl(png) {
  // §B: a `png` field is an absolute filesystem path — never URL-encode it
  // as given, always strip to its basename first. The confinement check on
  // the server refuses anything else (a name that is not its own basename).
  return `/api/reframe/tile/${encodeURIComponent(basename(png))}`;
}

function windowAddress(row) {
  // The address `reframe --src-start` takes: the window's own start when
  // known, else the stretch's src_start (the head-window case) — CLAUDE.md's
  // rule for `window`, restated once here since every caller needs it.
  return row.window !== null && row.window !== undefined ? row.window : row.src_start;
}

function rowKey(row) {
  return `${row.asset}@${windowAddress(row)}`;
}

function parseRect(text) {
  if (!text) return { x: 0, y: 0, w: 0, h: 0 };
  const [x, y, w, h] = text.split(",").map((part) => Number(part));
  return { x: x || 0, y: y || 0, w: w || 0, h: h || 0 };
}

function rectText(rect) {
  // `ops._parse_rect` refuses anything but a plain integer X,Y,W,H — never
  // send the fractional values a nudge can accumulate.
  return [rect.x, rect.y, rect.w, rect.h].map((v) => String(Math.round(v))).join(",");
}

function setChip(node, text, warn, title) {
  if (!node) return;
  node.textContent = text;
  node.classList.toggle("warn", warn);
  if (title) node.title = title;
  else node.removeAttribute("title");
}

/** One decimal for a chip or a header, the full value for the tooltip.
 *
 * `secs()` renders three (`11.719s`, `20.395s`), which is the right precision
 * for an address someone might type back into `reframe --src-start` and the
 * wrong one for a quantity someone is reading — a coverage chip saying
 * `11.719s stale` spends three characters on a number nobody acts on at that
 * resolution. Display only: nothing downstream parses these, and the frame-of-
 * tolerance arithmetic in the coverage math never sees them. */
function coarse(t) {
  return t === null || t === undefined ? "–" : `${t.toFixed(1)}s`;
}

function setButtonBusy(btn, busyLabel, idleLabel) {
  if (!btn) return;
  btn.disabled = Boolean(busyLabel);
  btn.textContent = busyLabel || idleLabel;
}

/* -- coverage chips ------------------------------------------------------ */

/** Is the Frame view actually on screen? `app.js`'s `setMode` owns this
 * element's `hidden`, and this pane only ever reads it. */
function frameVisible() {
  const view = $("frame-view");
  return Boolean(view) && !view.hidden;
}

/** Does this project have anything a crop window could apply to?
 *
 * `ops.reframe_coverage` refuses outright when it has no footage
 * placements — correct for the CLI, but as a fetch it is a 400 and a red
 * toast on every load of an audio-only project, where having no picture is
 * the normal state rather than a fault. `/api/view` already answers this
 * (`shots`), so the question is not asked rather than asked and refused.
 * A `shots_error` means the projection itself refused — that is a real
 * finding and coverage is still worth asking, so it is NOT treated as
 * "nothing here". */
function hasPlacements(state) {
  if (!state) return false;
  if (state.shots_error) return true;
  return Boolean(state.shots && state.shots.length);
}

async function refreshCoverage() {
  if (!ctx) return;
  coverageStale = false;
  if (!hasPlacements(lastState)) {
    // Not a warning and not a blank chip — both would read as a verdict on
    // framing that nobody measured.
    setChip($("frame-chip-stale"), "no footage placements to frame", false);
    $("frame-chip-steps") && ($("frame-chip-steps").textContent = "");
    $("frame-chip-cuts") && ($("frame-chip-cuts").textContent = "");
    return;
  }
  // Say so while it runs. `reframe_coverage` decodes placed footage for a
  // scene-cut scan and took ~4s on the real film, during which these three
  // chips sat empty — and an empty chip where a warning would go reads as
  // "nothing to report", which is the one thing this view must never say by
  // accident. Measured in a browser: chips blank for 4s, then correct.
  setChip($("frame-chip-stale"), "scanning for cuts…", false);
  $("frame-chip-steps") && ($("frame-chip-steps").textContent = "");
  $("frame-chip-cuts") && ($("frame-chip-cuts").textContent = "");
  let coverage;
  try {
    coverage = await ctx.api("/api/reframe/coverage");
  } catch (err) {
    setChip($("frame-chip-stale"), "coverage unavailable", true);
    $("frame-chip-steps") && ($("frame-chip-steps").textContent = "");
    $("frame-chip-cuts") && ($("frame-chip-cuts").textContent = "");
    ctx.emit("toast", err.message);
    return;
  }
  renderCoverage(coverage);
}

function renderCoverage(coverage) {
  const staleOn = coverage.stale_seconds > 0;
  setChip(
    $("frame-chip-stale"),
    staleOn ? `${coarse(coverage.stale_seconds)} stale` : "no stale framing",
    staleOn,
    staleOn
      ? `${coverage.stale_seconds}s of framing held across a cut, over ${coverage.stale_stretches} stretch${coverage.stale_stretches === 1 ? "" : "es"}`
      : null,
  );
  const steps = coverage.steps.length;
  setChip(
    $("frame-chip-steps"),
    steps ? `${steps} unexplained step${steps === 1 ? "" : "s"}` : "no step gaps",
    steps > 0,
  );
  // Informational only — never .warn. default_seconds (the centre crop
  // doing what it always did) is deliberately not read anywhere here.
  setChip($("frame-chip-cuts"), `${coverage.cuts_framed}/${coverage.cuts} cuts framed`, false);
}

/* -- the sheet job --------------------------------------------------------- */

async function onBuildSheetClick() {
  if (!ctx || sheetBusy) return;
  try {
    await ctx.api("/api/reframe/sheet", {});
  } catch (err) {
    // A 409 (already generating) or a 400 (bad project) both land here
    // before any "running" event would — the button was never flipped busy
    // by this call, so nothing to unwind.
    ctx.emit("toast", err.message);
  }
}

function onSheetEvent(data) {
  if (!data || typeof data !== "object") return;
  const btn = $("frame-build-sheet");
  if (data.status === "running") {
    sheetBusy = true;
    setButtonBusy(btn, "generating sheet…", "Build sheet");
  } else if (data.status === "done") {
    sheetBusy = false;
    setButtonBusy(btn, null, "Build sheet");
    lastSheet = data;
    reframedKeys = new Set(); // a fresh sheet has fresh tiles — no row is stale anymore
    closeReframePanel();
    renderRows();
  } else if (data.status === "error") {
    sheetBusy = false;
    setButtonBusy(btn, null, "Build sheet");
    ctx.emit("toast", data.error || "reframe sheet failed");
  }
}

/* -- the detect job --------------------------------------------------------
 *
 * `apply` is never a control in this UI at all — the job hard-codes it off
 * and the endpoint refuses the key outright, so there is nothing here that
 * could send it even by accident.
 */

async function onDetectClick() {
  if (!ctx || detectBusy) return;
  setDetectError("");
  try {
    await ctx.api("/api/reframe/detect", {});
  } catch (err) {
    ctx.emit("toast", err.message);
  }
}

function setDetectError(message) {
  const node = $("frame-detect-error");
  if (!node) return;
  node.textContent = message || "";
  node.className = message ? "warn bad" : "";
}

function onDetectEvent(data) {
  if (!data || typeof data !== "object") return;
  const btn = $("frame-detect-gaps");
  if (data.status === "running") {
    detectBusy = true;
    setButtonBusy(btn, "detecting gaps…", "Detect gaps");
    setDetectError("");
  } else if (data.status === "done") {
    detectBusy = false;
    setButtonBusy(btn, null, "Detect gaps");
    lastDetect = data;
    renderRows(); // re-join every drawn row's provenance chip — no new fetch
  } else if (data.status === "error") {
    detectBusy = false;
    setButtonBusy(btn, null, "Detect gaps");
    // Rendered inline, in this row, never as a toast and never left as a
    // silent spinner — this is exactly the LUCID_FACE-absence case the
    // backend report names: with FaceError now EXPECTED, this branch is
    // what actually fires instead of the job hanging forever.
    setDetectError(data.error || "reframe detect failed");
  }
}

/* -- provenance join (display-only, never a decision) ---------------------- */

function findDetectEntry(row) {
  if (!lastDetect || !Array.isArray(lastDetect.windows)) return null;
  const at = windowAddress(row);
  return (
    lastDetect.windows.find(
      (entry) => entry.clip_id === row.asset && entry.src_start <= at && at <= entry.src_end,
    ) || null
  );
}

function provenanceChip(row) {
  const entry = findDetectEntry(row);
  if (!entry) return null;
  const text =
    entry.rect !== null
      ? `detector proposes: ${entry.rect}`
      : entry.refused
        ? `detector: refused (${entry.refused})`
        : null;
  if (!text) return null;
  return el("span", "frame-badge", text);
}

/* -- rows -------------------------------------------------------------- */

function renderRows() {
  const box = $("frame-rows");
  if (!box) return;
  box.textContent = "";
  closeReframePanel();
  if (!lastSheet || !Array.isArray(lastSheet.rows)) {
    box.append(el("div", "hint", "build the sheet to see per-window crops"));
    return;
  }
  // `row.windows` on each row is the PLACEMENT's own total window count —
  // `n` here (this window's own position within that placement) is not a
  // field the op returns, so it is derived purely from the rows' own
  // ordering, which the op emits in placement order (CLAUDE.md: "the row
  // is a window, not a placement, and that is a correction" — the rows for
  // one placement are contiguous and in source order).
  const seenPerShot = new Map();
  // **The gap in the shot numbers is answered, not left to be read as a
  // rendering fault.** Rows ran #0, #2, #3 on the film, and #1 is a card:
  // `ops._sheet_placements` puts stills in its own `skipped` list precisely
  // so the difference between "nothing to check" and "not checked" survives,
  // and each entry already carries the reason ("a still is never cropped").
  // Drawing that list is all this needs — the copy is the op's, not this
  // file's, so a new skip reason arrives here without an edit.
  //
  // Placed by index, so a skipped shot sits where its number would have been
  // rather than in a footnote under the rows: `skipped[].index` and
  // `row.shot` are both positions in the same shot list.
  const skipped = Array.isArray(lastSheet.skipped) ? lastSheet.skipped : [];
  const pending = [...skipped].sort((a, b) => a.index - b.index);
  const flushSkippedBefore = (limit) => {
    while (pending.length && pending[0].index < limit) {
      const entry = pending.shift();
      const note = el("div", "frame-row frame-row-skipped");
      note.append(el("span", "frame-row-shot", `shot #${entry.index}`));
      note.append(el("span", null, entry.asset));
      note.append(el("span", "hint", entry.why));
      box.append(note);
    }
  };
  for (const row of lastSheet.rows) {
    flushSkippedBefore(row.shot);
    const n = (seenPerShot.get(row.shot) || 0) + 1;
    seenPerShot.set(row.shot, n);
    box.append(buildRow(row, n));
  }
  flushSkippedBefore(Infinity);
}

function buildRow(row, windowIndex) {
  const key = rowKey(row);
  const wrapper = el("div", "frame-row");
  if (row.split) wrapper.classList.add("frame-row-split");
  if (approvedKeys.has(key)) wrapper.classList.add("frame-row-approved");
  wrapper.dataset.rowKey = key;

  const header = el("div", "frame-row-header");
  header.append(el("span", "frame-row-shot", `shot #${row.shot}`));
  header.append(el("span", null, row.asset));
  const span = el(
    "span",
    "mono",
    `src ${coarse(row.src_start)}–${coarse(row.src_start + row.duration)}`,
  );
  // The full source seconds stay one hover away: this is the address
  // `reframe --src-start` takes, and three decimals is how it is stored.
  span.title = `src ${secs(row.src_start)}–${secs(row.src_start + row.duration)}`;
  header.append(span);
  header.append(el("span", "hint", `window ${windowIndex} of ${row.windows}`));
  // **The rect belongs to the row, not the tile** — a row is one window
  // (ops.reframe_sheet: "a sheet row is a window shown, not a placement"), so
  // its samples all read `crop_at` inside that one window and come back
  // identical. Three tiles captioned with the same rect, under a rect already
  // burnt into each tile by the sheet renderer, is the same number four
  // times. The exception is a **sliding** window, where the rects are
  // `_lerp_rect` interpolations and genuinely differ tile to tile — so this
  // asks the data rather than assuming, and a row whose samples disagree
  // keeps its per-tile captions.
  const crops = (row.samples || []).map((sample) => sample.crop);
  const sharedCrop = crops.length && crops.every((c) => c && c === crops[0]) ? crops[0] : null;
  if (sharedCrop) header.append(el("span", "mono", sharedCrop));
  if (row.sliding) {
    header.append(el("span", "hint", `slides to ${secs(row.slides_to)}`));
  }
  wrapper.append(header);

  const badges = el("div", "frame-row-badges");
  if (row.split) {
    const overlapText =
      row.pane_overlap === null || row.pane_overlap === undefined
        ? "pane overlap: n/a"
        : `${Math.round(row.pane_overlap * 100)}% pane overlap`;
    badges.append(el("span", "frame-badge", overlapText));
  }
  // worst_offset beside multi_face, never alone — CLAUDE.md's rule, honoured
  // even though this step's own data path (no --extremes call) never
  // populates either field, so a later step turning extremes on needs no
  // change here.
  if (row.worst_offset !== null && row.worst_offset !== undefined) {
    const offsetText = `worst offset ${row.worst_offset}px${row.multi_face ? " (multi-face)" : ""}`;
    badges.append(el("span", "frame-badge", offsetText));
  }
  const provenance = provenanceChip(row);
  if (provenance) badges.append(provenance);
  if (badges.childNodes.length) wrapper.append(badges);

  const strip = el("div", "frame-tile-strip");
  for (const sample of row.samples || []) {
    strip.append(buildTile(sample, sharedCrop));
  }
  wrapper.append(strip);

  if (reframedKeys.has(key)) {
    wrapper.append(el("div", "frame-row-note", "reframed — rebuild the sheet to see it"));
  }

  const actions = el("div", "frame-row-actions");
  const approveBtn = el("button", null, approvedKeys.has(key) ? "Approved" : "Approve");
  approveBtn.type = "button";
  approveBtn.addEventListener("click", () => {
    if (approvedKeys.has(key)) approvedKeys.delete(key);
    else approvedKeys.add(key);
    wrapper.classList.toggle("frame-row-approved", approvedKeys.has(key));
    approveBtn.textContent = approvedKeys.has(key) ? "Approved" : "Approve";
  });
  const reframeBtn = el("button", null, "Re-frame…");
  reframeBtn.type = "button";
  reframeBtn.addEventListener("click", () => toggleReframePanel(row, reframeBtn));
  actions.append(approveBtn, reframeBtn);
  wrapper.append(actions);

  return wrapper;
}

/** One tile. `sharedCrop` is the rect the row header already states, when
 * every sample in the row agreed on one — the caption is then redundant and
 * is dropped. The **pane** caption is never dropped: a split's lower rect is
 * per-row too, but its presence is the finding (CLAUDE.md § The stacked
 * split), and a row that silently stopped saying it was split would be
 * indistinguishable from one that is not. */
function buildTile(sample, sharedCrop) {
  const tile = el("div", "frame-tile");
  if (sample.png) {
    const img = document.createElement("img");
    img.src = tileUrl(sample.png);
    img.alt = sample.crop ? `crop ${sample.crop}` : "reframe sample";
    img.loading = "lazy";
    tile.append(img);
  }
  if (sample.crop && sample.crop !== sharedCrop) {
    tile.append(el("div", "frame-tile-caption", sample.crop));
  }
  if (sample.pane) tile.append(el("div", "frame-tile-caption pane", sample.pane));
  return tile;
}

/* -- the Re-frame… panel ----------------------------------------------------
 *
 * A floating panel positioned relative to `#frame-rows`, clamped with
 * dom.js's ONE `clampFloating` (never a second inline clamp — the trap that
 * cost both other toolbars once already) and height-capped in CSS so a
 * panel taller than the pane pins with its own scrollbar rather than with
 * its buttons pushed off-screen. `#frame-rows` and every element between it
 * and the button that opens this stay `position: static` on purpose, so the
 * button's own `offsetLeft`/`offsetTop` resolve against `#frame-rows` — the
 * exact transcript.js selection-toolbar precedent dom.js's own header
 * documents (no scroll offset to fold in here, since `#frame-rows` does not
 * scroll on its own — `#frame-view` is the one scrolling ancestor).
 */

function closeReframePanel() {
  if (openPanel && openPanel.parentNode) openPanel.remove();
  openPanel = null;
}

function toggleReframePanel(row, anchorBtn) {
  const key = rowKey(row);
  if (openPanel && openPanel.dataset.rowKey === key) {
    closeReframePanel();
    return;
  }
  closeReframePanel();
  const head = row.samples && row.samples[0];
  const draft = {
    rect: parseRect(head && head.crop),
    pane: row.split ? parseRect(head && head.pane) : null,
  };
  const panel = buildReframePanel(row, draft);
  panel.dataset.rowKey = key;
  const container = $("frame-rows");
  container.append(panel);
  positionPanel(panel, anchorBtn, container);
  openPanel = panel;
}

function positionPanel(panel, anchorBtn, container) {
  const left = anchorBtn.offsetLeft;
  const top = anchorBtn.offsetTop + anchorBtn.offsetHeight;
  const { left: clampedLeft, top: clampedTop } = clampFloating(
    left,
    top,
    panel.offsetWidth,
    panel.offsetHeight,
    0,
    container.clientWidth,
    0,
    container.clientHeight,
  );
  panel.style.left = `${clampedLeft}px`;
  panel.style.top = `${clampedTop}px`;
}

function buildReframePanel(row, draft) {
  const panel = el("div", "toolbar-popover frame-reframe-panel");
  panel.append(
    el("div", "hint", `${row.asset} · src ${secs(windowAddress(row))} — nudge or type the crop`),
  );
  panel.append(buildRectEditor("rect", draft, "rect"));
  if (row.split) {
    panel.append(el("div", "hint", "pane (lower half of the split)"));
    panel.append(buildRectEditor("pane", draft, "pane"));
  }

  const actions = el("div", "frame-reframe-actions");
  const cancelBtn = el("button", null, "Cancel");
  cancelBtn.type = "button";
  cancelBtn.addEventListener("click", () => closeReframePanel());
  const submitBtn = el("button", "primary", "Submit");
  submitBtn.type = "button";
  submitBtn.addEventListener("click", () => submitReframe(row, draft, submitBtn));
  actions.append(cancelBtn, submitBtn);
  panel.append(actions);

  return panel;
}

function buildRectEditor(label, draft, key) {
  const wrap = el("div", "frame-rect-editor");
  wrap.append(el("div", "hint", label));

  const fields = el("div", "frame-rect-fields");
  const inputs = {};
  for (const f of ["x", "y", "w", "h"]) {
    const fieldWrap = el("label", "frame-rect-field", f.toUpperCase());
    const input = document.createElement("input");
    input.type = "number";
    input.value = draft[key][f];
    input.addEventListener("change", () => {
      draft[key][f] = Number(input.value) || 0;
    });
    inputs[f] = input;
    fieldWrap.append(input);
    fields.append(fieldWrap);
  }
  wrap.append(fields);

  function syncInputs() {
    for (const f of ["x", "y", "w", "h"]) inputs[f].value = draft[key][f];
  }

  // Nudges move x/y only — a size change goes through the number inputs
  // above directly (STUDIO names nudge buttons for position; width/height
  // are direct-entry only, same field).
  const nudges = el("div", "frame-nudges");
  const nudgeSpecs = [
    ["←", -1, 0, STEP_FINE],
    ["→", 1, 0, STEP_FINE],
    ["↑", 0, -1, STEP_FINE],
    ["↓", 0, 1, STEP_FINE],
    ["← ×8", -1, 0, STEP_COARSE],
    ["→ ×8", 1, 0, STEP_COARSE],
    ["↑ ×8", 0, -1, STEP_COARSE],
    ["↓ ×8", 0, 1, STEP_COARSE],
  ];
  for (const [text, dx, dy, step] of nudgeSpecs) {
    const btn = el("button", null, text);
    btn.type = "button";
    btn.addEventListener("click", () => {
      draft[key].x += dx * step;
      draft[key].y += dy * step;
      syncInputs();
    });
    nudges.append(btn);
  }
  wrap.append(nudges);

  return wrap;
}

async function submitReframe(row, draft, submitBtn) {
  if (!ctx) return;
  submitBtn.disabled = true;
  const body = {
    clip_id: row.asset,
    rect: rectText(draft.rect),
    src_start: windowAddress(row),
  };
  if (row.split && draft.pane) body.pane = rectText(draft.pane);
  try {
    await ctx.api("/api/reframe", body);
  } catch (err) {
    submitBtn.disabled = false;
    ctx.emit("toast", err.message);
    return;
  }
  reframedKeys.add(rowKey(row));
  closeReframePanel();
  renderRows();
}

/* -- module contract --------------------------------------------------------- */

export function init(passedCtx) {
  ctx = passedCtx;

  const buildBtn = $("frame-build-sheet");
  if (buildBtn) buildBtn.addEventListener("click", onBuildSheetClick);

  const detectBtn = $("frame-detect-gaps");
  if (detectBtn) detectBtn.addEventListener("click", onDetectClick);

  ctx.on("reframe-sheet", onSheetEvent);
  ctx.on("reframe-detect", onDetectEvent);
  // The other half of the deferral in `update()`: opening Frame is what
  // pays for the scan, and only if something changed since the last one.
  ctx.on("mode", (mode) => {
    if (mode === "frame" && coverageStale) refreshCoverage();
  });
}

export function update(state) {
  // Ephemeral, per-sitting UI state — reset on every reload, never
  // persisted (STUDIO: "report-only is the standing precedent"). The sheet
  // and detect jobs themselves are NOT re-triggered here — they stay
  // whatever they were, keyed on their own buttons, the finish.js render-job
  // precedent.
  approvedKeys = new Set();
  lastState = state;
  // Coverage is NOT re-fetched here unless this view is on screen. It was,
  // and it cost 5.5s of scene-cut decoding per call on the film — twice on
  // every page load and once more on every `project-changed`, so every cut
  // made in Edit mode paid for a scan of footage nobody was looking at.
  // That is precisely the cost `finish_report`'s framing was made opt-in to
  // avoid (CLAUDE.md), reintroduced through this pane. Deferred, the answer
  // is fetched when Frame is opened, and refreshed while it stays open.
  coverageStale = true;
  if (frameVisible()) refreshCoverage();
}
