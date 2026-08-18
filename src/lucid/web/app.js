/* app.js — entry point: the one `view` state, the initial /api/view load,
 * reloading on 'project-changed', the top bar's clip picker and Undo/Export
 * buttons, and wiring the three pane modules together through a small event
 * bus.
 *
 * CLAUDE.md's rule for this file, unchanged from tier 2: it draws and it
 * plays, it never decides. Nothing here computes an edit — Undo and Export
 * post to the same `ops` endpoints the CLI and MCP server use and render
 * whatever comes back.
 *
 * See transcript.js's header comment for the full pane-module interface
 * (`ctx` shape, event names, `state` shape). This file builds that `ctx`
 * and is the one place all three pane modules are wired, but otherwise
 * knows nothing about what any one of them draws — a pane can be rebuilt
 * without this file changing, which is the point of the split (PLAN.md §
 * Files, and why they split).
 *
 * The workshop-pass round (2026-08-17) added four more things this file
 * owns and nothing else does: #toast's severity/dismiss behaviour, the
 * #export-status chip that MIRRORS the 'render' bus event agent.js already
 * owns the full rendering of, the '?' shortcuts sheet's open/close, and the
 * two side panes' rail-collapse toggle. Every one of them draws or mirrors
 * something another module (or the server) already decided — see each
 * section's own comment for the specific measurement or trap it answers.
 */

import { $, fmt, debounce } from "./dom.js";
import { api, connectEvents } from "./api.js";
import * as player from "./player.js";
import * as transcript from "./transcript.js";
import * as timeline from "./timeline.js";
import * as agent from "./agent.js";
import * as assets from "./assets.js";
import * as properties from "./properties.js";
import * as finish from "./finish.js";
import * as frame from "./frame.js";

let view = null; // the /api/view payload — the whole read model, shared read-only
let captions = null; // the /api/captions payload: cues in timeline seconds and
// the style in force. A second endpoint rather than a field on the view — it
// is a different derivation of the same edit (placed, grouped, styled), it
// moves when the manifest moves rather than when the timeline does, and the
// view is already the larger of the two payloads.

/* -- the event bus --------------------------------------------------------
 * Panes talk through this, never by importing each other. app.js also
 * re-publishes every SSE record here under its own event name, so a pane
 * can listen for 'agent' or 'render' without this file ever needing to
 * change for a later stage to use them.
 */
const listeners = new Map();

function on(event, cb) {
  if (!listeners.has(event)) listeners.set(event, new Set());
  listeners.get(event).add(cb);
}

function emit(event, payload) {
  for (const cb of listeners.get(event) || []) cb(payload);
}

function getView() {
  return view;
}

function getCaptions() {
  return captions;
}

const ctx = { api, player: player.player, getView, getCaptions, on, emit };

/* -- #toast --------------------------------------------------------------
 * F9: a bare string keeps meaning exactly what it always has — an error —
 * so every existing `emit('toast', someString)` call site in agent.js,
 * transcript.js, player.js, timeline.js and assets.js changes neither
 * appearance nor behaviour. The only thing that changes shape is app.js's
 * own render-accepted toast a few lines down, which now opts into the
 * object form to report success without borrowing the error's red.
 *
 * 'ok' and 'warn' still auto-dismiss on the same 9s timer this file has
 * always run; 'error' sets no timer at all and sits until #toast-dismiss
 * is clicked or another toast() call replaces it — the actual fix for "the
 * wrong default for the long error strings the server actually returns"
 * (F9), which used to vanish at 9s exactly like a one-line success would.
 */
function toast(payload) {
  const { message, severity } =
    typeof payload === "string" ? { message: payload, severity: "error" } : payload;
  // Computed once: an object payload that omits `severity` must default to
  // 'error' exactly like a bare string does, in BOTH the badge colour and
  // the dismiss timer below — reading `severity` (the raw, possibly-
  // undefined field) a second time for the timer check let an omitted
  // severity draw as 'error' but still auto-dismiss like a success.
  const effective = severity || "error";
  const box = $("toast");
  $("toast-message").textContent = message;
  box.dataset.severity = effective;
  box.hidden = false;
  clearTimeout(toast.timer);
  if (effective !== "error") {
    toast.timer = setTimeout(() => {
      box.hidden = true;
    }, 9000);
  }
}

$("toast-dismiss").addEventListener("click", () => {
  clearTimeout(toast.timer);
  $("toast").hidden = true;
});

// The shell owns #toast, like it owns the top bar — a pane emits rather than
// reaching for the element itself.
on("toast", toast);

/* -- loading the view ------------------------------------------------- */

async function load(clipId) {
  const query = clipId ? `?clip_id=${encodeURIComponent(clipId)}` : "";
  // Read the playhead against the *old* edit before replacing it: a cut that
  // lands before the playhead moves everything after it, and holding the
  // timeline second would drift the view a little further with each edit
  // (tier 2's app.js, ported unchanged — PLAN.md § Files, and why they split).
  const at = view ? player.player.now() : 0;
  try {
    view = await api(`/api/view${query}`);
  } catch (err) {
    toast(err.message);
    return;
  }
  // Fetched after the view and not in parallel with it: a bad clip_id has to
  // fail on the view, where the toast above already reports it, rather than
  // as a second error about captions. Its own failure is deliberately quiet —
  // a project with no transcript is the ordinary case, not something to
  // interrupt anyone about, and `caption_view` already reports rather than
  // raises for every case that is not a broken project.
  try {
    captions = await api(`/api/captions${query}`);
  } catch {
    captions = null;
  }

  renderBar();
  transcript.update(view);
  timeline.update(view);
  agent.update(view);
  assets.update(view);
  properties.update(view);
  finish.update(view);
  frame.update(view);
  player.update(view);
  player.captions(captions);
  player.player.seek(Math.min(at, Math.max(0, view.timeline_duration - 0.01)));
}

function renderBar() {
  $("project").textContent = view.name;
  $("duration").textContent = fmt(view.timeline_duration);
  $("segcount").textContent = view.segments.length;
  $("cutcount").textContent = view.seams.length;
  $("depth").textContent = view.undo_depth ? `(${view.undo_depth})` : "";
  $("undo").disabled = view.undo_depth === 0;

  // F3: the preview pane is the one surface with no label saying what it is
  // — a person had to open the properties pane to learn the canvas is not
  // the media's own shape. `view.canvas` is `[width, height]` (ops.py's
  // timeline_view, `"canvas": list(resolution)`); render it here rather
  // than in properties.js, which is unowned and already renders it for a
  // different reason (the read-only inspector's own copy of the fact).
  $("preview-canvas-note").textContent =
    view.canvas && view.canvas.length === 2
      ? `${view.canvas[0]}×${view.canvas[1]} canvas, not the media's shape`
      : "";

  const picker = $("clip");
  picker.textContent = "";
  for (const clip of view.clips) {
    const option = document.createElement("option");
    option.value = clip.clip_id;
    option.textContent = clip.clip_id + (clip.has_transcript ? "" : " (no transcript)");
    option.selected = clip.clip_id === view.clip_id;
    picker.append(option);
  }
  picker.hidden = view.clips.length < 2;
}

/* -- top bar actions ---------------------------------------------------- */

$("clip").addEventListener("change", (event) => load(event.target.value));

// Factored out so both the #undo button and the Cmd/Ctrl-Z keyboard chord
// (F7 — player.js emits 'shortcut-undo' on the keydown, this file is the
// one place that turns that into the same /api/undo call the button
// already made) go through one path rather than two copies of it.
async function doUndo() {
  let payload = null;
  let error = null;
  try {
    payload = await api("/api/undo", {});
  } catch (err) {
    error = err.message;
    toast(error);
  }
  emit("op-result", { payload, error });
  if (!error) await load(view.clip_id);
}

$("undo").addEventListener("click", doUndo);
on("shortcut-undo", doUndo);

// 'custom' is the only preset with anything to type in — everything else
// leaves #export-resolution hidden and unread.
$("export-preset").addEventListener("change", (event) => {
  $("export-resolution").hidden = event.target.value !== "custom";
});

// Parses "WIDTHxHEIGHT" into [width, height], or null for anything else —
// this widget only assembles what the user typed, it does not validate a
// combination (ops.export does that, and a bad one surfaces as the render
// job's own 'error' event).
function parseResolution(text) {
  const match = /^(\d+)x(\d+)$/.exec(text.trim());
  return match ? [Number(match[1]), Number(match[2])] : null;
}

$("export").addEventListener("click", async () => {
  const body = {};
  const preset = $("export-preset").value;
  if (preset) body.preset = preset;
  const resolution = parseResolution($("export-resolution").value);
  if (resolution) body.resolution = resolution;
  try {
    const result = await api("/api/render", body);
    // F9's actual visible fix: this is the one call site in the whole app
    // that opts into the {message,severity} object form today. Every other
    // emit('toast', someString) above and in every other file stays a bare
    // string — and a bare string still means 'error' (see toast() above) —
    // so "Render started" is the only success that stops dressing as one.
    toast({ message: `Render started · job ${result.job_id}`, severity: "ok" });
  } catch (err) {
    toast(err.message);
  }
});

// -- the render chip (F8) --------------------------------------------------
//
// Export's progress, Stop control and completion card all land in the
// agent feed — one column over from the button that started the render —
// and the only trace near the button itself is a toast that has long since
// expired by the time a real render finishes. #export-status mirrors the
// same 'render' SSE record agent.js already owns the full rendering of;
// this is a second, additive subscriber on the same bus event (`on()`
// backs every event with a Set, so agent.js's own subscription is
// untouched) — it draws a status word, never the checks or the Stop
// button, which stay agent.js's alone.
//
// It cannot scroll to its own job's card without agent.js stamping a
// data-job-id on the wrapper it builds, and agent.js is out of scope this
// round — so the click scrolls #agent-feed to its bottom (the same public
// id agent.js's own feed lives at) rather than to the exact card. The
// natural follow-up once agent.js is back in scope.
on("render", (data) => {
  if (!data || typeof data !== "object") return;
  const chip = $("export-status");
  chip.hidden = false;
  chip.dataset.status = data.status;
  chip.dataset.jobId = data.job_id ?? "";
  chip.textContent =
    data.status === "running"
      ? "rendering…"
      : data.status === "done"
        ? "render done"
        : data.status === "cancelled"
          ? "render cancelled"
          : data.status === "error"
            ? "render failed"
            : data.status;
});

$("export-status").addEventListener("click", () => {
  const feed = $("agent-feed");
  feed.scrollTop = feed.scrollHeight;
});

// -- the '?' shortcuts sheet and the rail toggles (F2, F7) ------------------

on("shortcut-help", () => $("shortcuts-sheet").showModal());
// The top bar's `?` goes through the same bus event the key does rather than
// calling showModal() itself — two open paths is how one of them ends up
// missing a step the other grew later.
$("shortcuts-open").addEventListener("click", () => emit("shortcut-help"));
$("shortcuts-close").addEventListener("click", () => $("shortcuts-sheet").close());
$("shortcuts-sheet").addEventListener("click", (event) => {
  // A click on the <dialog> element itself (not something inside it) is a
  // backdrop click — the dialog's own box does not fill the element, native
  // <dialog> sizing hugs its content, so `event.target === dialog` is the
  // reliable test rather than comparing coordinates against a rect.
  if (event.target === $("shortcuts-sheet")) $("shortcuts-sheet").close();
});

// F2: below 1200px the inspector collapses to a ~46px icon rail, and below
// 980px the agent pane does too (app.css's own two media queries — see the
// grid-track indirection in its tokenChanges). Both rails and both panes'
// collapse buttons share this one function rather than each getting its
// own copy — a duplicated fix is exactly how F4's clamp bug reached only
// one of the two toolbars it was needed on. The state lives as a token in
// #workspace's data-expand attribute (a space-separated set of pane names,
// DOMTokenList-compatible) because app.css's breakpoint rules read it
// directly — this file never toggles a class or inline style the CSS would
// have to duplicate.
function toggleRailPane(name) {
  const workspace = $("workspace");
  const expanded = workspace.dataset.expand ? workspace.dataset.expand.split(" ") : [];
  const i = expanded.indexOf(name);
  if (i === -1) expanded.push(name);
  else expanded.splice(i, 1);
  workspace.dataset.expand = expanded.join(" ");
}

for (const btn of document.querySelectorAll(".pane-rail-tab, .pane-collapse-btn")) {
  const pane = btn.closest("#agent-pane") ? "agent" : "inspector";
  btn.addEventListener("click", () => toggleRailPane(pane));
}

// -- mode tabs and the truth strip (Studio reshape step 01, step 03) --------
//
// Plain `hidden` on the four top-level containers — no `data-mode` scheme,
// per the implementation contract. `#workspace` and `#timeline-pane` (the
// timeline section) move together: Edit is the only mode that shows either
// one, since Frame and Finish each have their own single full-height view.
let currentMode = "edit"; // agrees with index.html's own default-visible pane;
// tracked here (not re-derived from the DOM) so getMode() below is O(1) —
// step 04's session restore/save is the first caller (contract § E).

function setMode(mode) {
  currentMode = mode;
  $("workspace").hidden = mode !== "edit";
  $("timeline-pane").hidden = mode !== "edit";
  $("frame-view").hidden = mode !== "frame";
  $("finish-view").hidden = mode !== "finish";
  for (const btn of document.querySelectorAll(".mode-tab")) {
    if (btn.dataset.mode === mode) btn.setAttribute("aria-current", "page");
    else btn.removeAttribute("aria-current");
  }
  // A hidden mode's pane can now defer its work until it is looked at.
  // `frame.js` is why this exists: its coverage scan decodes every placed
  // clip (5.5s measured on the film, uncached, per call), which must not
  // ride a reload nobody in Edit mode asked for — the same cost that made
  // `finish_report`'s framing opt-in (CLAUDE.md).
  emit("mode", mode);
}

/** The active mode — `"edit" | "frame" | "finish"` — for session save. */
function getMode() {
  return currentMode;
}

$("mode-tab-edit").addEventListener("click", () => setMode("edit"));
$("mode-tab-frame").addEventListener("click", () => setMode("frame"));
$("mode-tab-finish").addEventListener("click", () => setMode("finish"));

// Every truth-strip chip links to the mode that explains it — in this step
// that is always Finish, including the never-warned duration chip (Finish
// is where duration is broken out into edit/tail/total, so the link is
// still useful even on a chip that carries no warning).
for (const chip of document.querySelectorAll(".truth-chip")) {
  chip.addEventListener("click", (event) => {
    event.preventDefault();
    setMode(chip.dataset.modeLink);
  });
}

function setChip(node, text, warn) {
  if (!node) return;
  node.textContent = text;
  node.classList.toggle("warn", warn);
}

/** `"no style"` when captions were never configured, else the render log's
 * own burned/not-burned/unknown answer — a small local formatter with no
 * other module depending on its exact string. */
function captionLabel(captions) {
  if (!captions.configured) return "no style";
  if (captions.burned === "yes") return "burned";
  if (captions.burned === "no") return "not burned";
  return "unknown";
}

/** `"framing ok"` when `ops.finish_report`'s composed `framing` section
 * raised neither flag, else the stale-seconds / step-gap counts it did
 * raise, joined — the `captionLabel` precedent one line up: a small local
 * formatter, no decision. `worst_offset` is deliberately not read here or
 * anywhere in this file — it has no reliable-to-zero fix, so it is not a
 * flag (STUDIO.md § step 03 / § Cross-cutting: a flag must be something the
 * window can fix). */
function framingLabel(framing) {
  // `null` means the op was not asked to measure — distinct from a measured
  // zero, and it has to read that way. `finish_report`'s framing section
  // decodes placed footage for a scene-cut scan (5.7s wall, 46s CPU on the
  // film, uncached), and this strip re-reads the bundle on every
  // `project-changed`, so measuring it here would have made every cut pay
  // six seconds for a number the cut did not ask about. Frame mode measures
  // it, from its own `/api/reframe/coverage`, where the answer is the point.
  if (!framing) return "framing — see Frame";
  const parts = [];
  if (framing.stale_seconds > 0) parts.push(`${framing.stale_stretches} stale`);
  if (framing.steps > 0) parts.push(`${framing.steps} step gap${framing.steps === 1 ? "" : "s"}`);
  return parts.length ? parts.join(" / ") : "framing ok";
}

// finish.js is the only module that calls GET /api/finish; every other
// consumer of that bundle (this truth strip included) gets it by listening
// for the event finish.js re-broadcasts on every fetch, never by fetching
// it again itself.
on("finish-report", (bundle) => {
  // A chip warns when the op raised a flag of that kind, and never because
  // this file looked at the numbers and formed an opinion — the strip draws
  // what an op returned (STUDIO.md § Cross-cutting). The earlier version
  // warned the canvas chip whenever any preset refused, which lit permanently
  // on every 16:9 film for refusing `tiktok-reels`, and warned the caption
  // chip on `burned !== "yes"`, which lit permanently on a project that has
  // no captions to burn. Both were this file deciding.
  const flagged = new Set(bundle.flags.items.map((f) => f.kind));
  setChip($("truth-duration"), fmt(bundle.duration.total_seconds), false);
  setChip($("truth-canvas"), bundle.canvas.canvas, flagged.has("canvas"));
  setChip($("truth-captions"), captionLabel(bundle.captions), flagged.has("captions"));
  setChip($("truth-framing"), framingLabel(bundle.framing), flagged.has("framing"));
  const n = bundle.flags.count;
  setChip($("truth-flags"), n === 1 ? "1 flag" : `${n} flags`, n > 0);
});

/* -- session restore and save (STUDIO.md Step 04, contract § E) -----------
 *
 * `cache/session.json` — playhead, zoom, timeline scroll, pane collapse,
 * mode, selection. Cache, never manifest: `/api/session` touches no file
 * `_revision` watches, so it never fires `project-changed` and this file
 * never has to guard against its own save round-tripping into a reload.
 *
 * `restoring` blocks the save heartbeat from firing while step 2-7 below
 * apply a saved value — each of those calls (setMode, a dataset write,
 * timeline.setZoom/setScrollLeft, emit('selection', ...), player.seek) would
 * otherwise look exactly like a person just did that thing.
 */
let restoring = true;
let lastSavedSnapshot = null;

const sendSession = debounce((snapshot) => {
  // Best-effort: a session write failing must never toast — losing the
  // resume position is not worth interrupting anyone over.
  api("/api/session", snapshot).catch(() => {});
}, 800);

function sessionSnapshot() {
  const sel = timeline.getSelection();
  return {
    playhead: player.player.now(),
    zoom: timeline.getZoom(),
    scroll_left: timeline.getScrollLeft(),
    pane_expand: $("workspace").dataset.expand ?? "",
    mode: getMode(),
    selection: sel && view ? { clip_id: view.clip_id, indices: sel.indices } : null,
  };
}

// The cheap half of "debounced": a 2s comparison heartbeat, matching
// timeline.js's own hand-rolled per-frame throttling idiom rather than a
// change listener on every field (fragile — easy to miss one). Only the
// actual network write, inside sendSession above, is what's debounced.
function checkAndSave() {
  const snapshot = sessionSnapshot();
  const serialized = JSON.stringify(snapshot);
  if (serialized === lastSavedSnapshot) return;
  sendSession(snapshot);
  lastSavedSnapshot = serialized;
}

async function restoreSession() {
  let session;
  try {
    session = await api("/api/session");
  } catch {
    session = {}; // a corrupt or unreadable session file restores nothing
  }
  try {
    // 1. Mode first, so hidden/shown panes match before anything below
    // queries their layout.
    if (session.mode) setMode(session.mode);
    if (session.pane_expand != null) $("workspace").dataset.expand = session.pane_expand;
    // Zoom before scroll: zoom changes the scrollable width scroll_left
    // addresses.
    if (session.zoom != null) timeline.setZoom(session.zoom);
    if (session.scroll_left != null) timeline.setScrollLeft(session.scroll_left);
    // A saved selection is only ever applied against the transcript it was
    // taken from — a stale one (a different clip loaded since) is silently
    // skipped rather than misapplied to the wrong words.
    if (session.selection && view && session.selection.clip_id === view.clip_id) {
      emit("selection", session.selection);
    }
    // Seek last, so it sees the already-restored zoom/scroll rather than
    // fighting the follow-playhead nudge those trigger.
    if (session.playhead != null) player.player.seek(session.playhead);
  } finally {
    restoring = false;
  }
  lastSavedSnapshot = JSON.stringify(sessionSnapshot());
  setInterval(() => {
    if (restoring) return;
    checkAndSave();
  }, 2000);
}

/* -- startup -------------------------------------------------------------- */

player.init(ctx);
transcript.init(ctx);
timeline.init(ctx);
agent.init(ctx);
assets.init(ctx);
properties.init(ctx);
finish.init(ctx);
frame.init(ctx);
setMode("edit");
load(null).then(restoreSession);

// Started last, after the panes exist and the first load is underway: the
// server sends the current revision immediately on connect, which is itself
// a 'project-changed' record — one event path covers an agent edit, the
// page's own edit, and a `lucid cut` run in a terminal beside it (PLAN.md §
// View invalidation is uniform).
connectEvents((name, data) => {
  emit(name, data);
  if (name === "project-changed") load(view ? view.clip_id : null);
});

// The same reload, asked for by a pane rather than by the revision poll —
// because two ops write a file `_revision` does not stat. `transcribe` and
// `attach-transcript` write only a transcript, touching neither
// `project.otio` nor the manifest, so no 'project-changed' ever follows one
// (webui.py's TranscribeJob docstring). This is the signal in its place, and
// it is `load()` rather than `location.reload()` on purpose: a page reload
// would throw away the very report the finished op just returned — the words
// attached, the hallucinated ones dropped, the seams found — which is the
// one thing the panel is supposed to render (CLAUDE.md: the panel renders
// that function's own return value).
on("reload", () => load(view ? view.clip_id : null));
