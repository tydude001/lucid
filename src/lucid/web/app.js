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

function toast(message) {
  const box = $("toast");
  box.textContent = message;
  box.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => {
    box.hidden = true;
  }, 9000);
}

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

$("undo").addEventListener("click", async () => {
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
});

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
    toast(`Render started · job ${result.job_id}`);
  } catch (err) {
    toast(err.message);
  }
});

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
