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

import { $, fmt } from "./dom.js";
import { api, connectEvents } from "./api.js";
import * as player from "./player.js";
import * as transcript from "./transcript.js";
import * as timeline from "./timeline.js";
import * as agent from "./agent.js";
import * as assets from "./assets.js";
import * as properties from "./properties.js";

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

/* -- startup -------------------------------------------------------------- */

player.init(ctx);
transcript.init(ctx);
timeline.init(ctx);
agent.init(ctx);
assets.init(ctx);
properties.init(ctx);
load(null);

// Started last, after the panes exist and the first load is underway: the
// server sends the current revision immediately on connect, which is itself
// a 'project-changed' record — one event path covers an agent edit, the
// page's own edit, and a `lucid cut` run in a terminal beside it (PLAN.md §
// View invalidation is uniform).
connectEvents((name, data) => {
  emit(name, data);
  if (name === "project-changed") load(view ? view.clip_id : null);
});
