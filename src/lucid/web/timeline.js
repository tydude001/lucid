/**
 * timeline.js — the real timeline of PLAN.md § Tier 3 is the goal:
 * a ruler with time labels, pixels-per-second zoom (fit-to-window
 * by default), sticky track headers, named clip blocks, an A1 waveform
 * canvas from `/api/waveform/<clip_id>`, click-to-seek, and a
 * playhead driven by player.js (PLAN.md § The timeline).
 *
 * Lanes are projections of one single-track `Edit`, never independent
 * tracks. V1 only when the displayed clip `has_video`, A1 always (the
 * recording has audio even for a picture clip), CC only when a transcript
 * exists to caption from. **No V2, no A2, no lane `export` cannot
 * produce** — auto-editor 31.x degrades a multi-*source* render to
 * 720x576 with a warning and exit 0 rather than failing, so a lane this
 * view draws ahead of the model would look right and export wrong
 * (CLAUDE.md; PLAN.md § The trap this section exists to write down). All
 * three lanes below are built from `state.segments` — the same single
 * track `export` reads — never from anything wider.
 *
 * The waveform is drawn THROUGH the edit (PLAN.md § Read-model additions):
 * `drawWaveformLane` slices the *cached source* RMS array by each
 * segment's own `start`/`end` every time it draws, so a cut needs no
 * recompute and no timeline-space envelope is ever built or cached here.
 *
 * See transcript.js's header comment for the full pane-module interface —
 * `ctx` shape, bus event names, and the `state` shape — this file does not
 * repeat it.
 */

import { $, el, fmt, secs } from "./dom.js";

let ctx = null;
let lastState = null;
let zoomMultiplier = 1; // multiplies the fit-to-window base — #zoom is 1..10
let currentPxPerSec = 1; // cached for the per-frame playhead handler, which
// must not pay for a full re-render 60 times a second
let selection = null; // word indices to highlight — see the 'selection'
// subscription in init() for why this degrades to a no-op today

const MIN_PX_PER_SEC = 4; // guards a zero/near-zero duration from a divide
const LANE_H_FALLBACK = 42; // matches app.css's --lane-h if the var lookup fails
const LABEL_MIN_PX = 70; // minimum on-screen spacing before a ruler label repeats

//: "Nice" ruler intervals, seconds — the smallest one that keeps labels this
//: side of LABEL_MIN_PX apart at the current zoom is picked.
const NICE_INTERVALS = [0.1, 0.2, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 900, 1800, 3600];

// clip_id -> {status: "loading" | "ready" | "error", data}. One fetch per
// clip for the life of the page; a project with one source clip (the only
// kind that exists today, per the decision gate) fetches this exactly once.
const waveformCache = new Map();

function header(label) {
  return el("div", "track-header", label);
}

function laneHeightPx() {
  const raw = getComputedStyle(document.documentElement).getPropertyValue("--lane-h");
  const n = parseFloat(raw);
  return Number.isFinite(n) && n > 0 ? n : LANE_H_FALLBACK;
}

/** Fit-to-window pixels-per-second, times the #zoom slider's multiplier. */
function computePxPerSec(duration) {
  const container = $("track-lanes");
  const width = (container && container.clientWidth) || 800;
  const base = duration > 0 ? width / duration : width;
  return Math.max(MIN_PX_PER_SEC, base * zoomMultiplier);
}

function pickInterval(pxPerSec) {
  for (const interval of NICE_INTERVALS) {
    if (interval * pxPerSec >= LABEL_MIN_PX) return interval;
  }
  return NICE_INTERVALS[NICE_INTERVALS.length - 1];
}

function buildRuler(duration, pxPerSec) {
  const ruler = el("div", "ruler");
  ruler.style.width = `${Math.max(1, duration * pxPerSec)}px`;
  const interval = pickInterval(pxPerSec);
  for (let t = 0; t <= duration + 1e-6; t += interval) {
    const tick = el("div", "ruler-tick");
    tick.style.left = `${(t * pxPerSec).toFixed(1)}px`;
    ruler.append(tick);
    const label = el("div", "ruler-label", fmt(t));
    label.style.left = `${(t * pxPerSec + 3).toFixed(1)}px`;
    ruler.append(label);
  }
  return ruler;
}

/** Words this view knows survived and fall inside one timeline segment —
 * only possible for the segment whose clip matches the transcript this
 * view loaded (`state.clip_id`); a segment from another clip gets no
 * caption text, never a guess. */
function captionText(seg, state) {
  if (!state.words || seg.clip_id !== state.clip_id) return null;
  const text = state.words
    .filter(
      (w) => w.present && w.timeline_start >= seg.timeline_start - 1e-6 && w.timeline_start < seg.timeline_end,
    )
    .map((w) => w.text)
    .join(" ");
  if (!text) return null;
  return text.length > 60 ? `${text.slice(0, 57)}…` : text;
}

/** One row: a `.clip-block` per timeline segment (hover/title/hit-testing,
 * per PLAN.md § The timeline — DOM, not canvas, for exactly this reason)
 * plus a `.seam-tick` per cut boundary, and a click-to-seek handler on the
 * row itself so a click anywhere in the lane — including on a child block —
 * seeks the player (event bubbling; the handler reads the row's own
 * bounding rect, so it works regardless of scroll or which child was hit). */
function buildLaneRow(kind, segments, pxPerSec, duration, state) {
  const row = el("div", `lane lane-${kind.toLowerCase()}`);
  row.style.width = `${Math.max(1, duration * pxPerSec)}px`;

  for (const seg of segments) {
    const block = el("div", "clip-block");
    block.style.left = `${(seg.timeline_start * pxPerSec).toFixed(1)}px`;
    block.style.width = `${Math.max(1, (seg.timeline_end - seg.timeline_start) * pxPerSec).toFixed(1)}px`;
    if (kind === "CC") {
      const text = captionText(seg, state);
      block.textContent = text || "";
      block.title = text || `${seg.clip_id} — no caption text (no transcript for this segment's clip)`;
    } else {
      block.textContent = seg.clip_id;
      block.title = `${seg.clip_id} · source ${secs(seg.start)}–${secs(seg.end)} · timeline ${fmt(seg.timeline_start)}–${fmt(seg.timeline_end)}`;
    }
    row.append(block);
  }

  for (const seam of state.seams) {
    const tick = el("div", "seam-tick");
    tick.style.left = `${(seam.timeline_time * pxPerSec).toFixed(1)}px`;
    const before = seam.before ? seam.before.text : "…";
    const after = seam.after ? seam.after.text : "…";
    tick.title = `cut ${secs(seam.removed)} of source — ]${before}  ${after}[`;
    row.append(tick);
  }

  row.addEventListener("click", (event) => {
    if (!ctx) return;
    const rect = row.getBoundingClientRect();
    const t = (event.clientX - rect.left) / pxPerSec;
    ctx.player.seek(t);
  });

  return row;
}

/** Lazily fetches and caches one clip's waveform (`GET
 * /api/waveform/<clip_id>`, contract in PLAN.md § Read-model additions).
 * Triggers one re-render when it lands so the canvas that asked for it
 * redraws with real data instead of the blank frame it drew while waiting. */
function ensureWaveform(clipId) {
  const cached = waveformCache.get(clipId);
  if (cached) return cached;
  const entry = { status: "loading", data: null };
  waveformCache.set(clipId, entry);
  if (ctx) {
    ctx
      .api(`/api/waveform/${encodeURIComponent(clipId)}`)
      .then((data) => {
        entry.status = "ready";
        entry.data = data;
        if (lastState) render();
      })
      .catch(() => {
        // No waveform for this clip (missing media, no clips at all) — the
        // lane just stays blank there. The clip-blocks underneath still
        // carry hover/title, so the lane is not otherwise broken.
        entry.status = "error";
      });
  }
  return entry;
}

/** Draws A1's envelope THROUGH the edit: each segment reslices its own
 * clip's cached *source* RMS array by its own `start`/`end` and paints
 * that slice at the segment's timeline position. No timeline-length
 * envelope is ever assembled — a cut changes which slice of the cached
 * array a segment reads and where it paints, nothing this function
 * precomputes. */
function drawWaveformLane(canvas, segments, pxPerSec, laneHeight, contentWidth) {
  canvas.width = Math.max(1, Math.round(contentWidth));
  canvas.height = Math.max(1, Math.round(laneHeight));
  const g = canvas.getContext("2d");
  if (!g) return;
  g.clearRect(0, 0, canvas.width, canvas.height);
  const mid = canvas.height / 2;
  g.fillStyle = "rgba(20, 22, 26, 0.55)"; // var(--bg), read over the block's own fill

  for (const seg of segments) {
    const entry = ensureWaveform(seg.clip_id);
    if (entry.status !== "ready") continue;
    const { rms, frame_ms } = entry.data;
    const frameSec = frame_ms / 1000;
    const startFrame = Math.max(0, Math.floor(seg.start / frameSec));
    const endFrame = Math.min(rms.length, Math.ceil(seg.end / frameSec));
    const frameCount = Math.max(1, endFrame - startFrame);
    const segLeft = seg.timeline_start * pxPerSec;
    const segWidth = Math.max(1, (seg.timeline_end - seg.timeline_start) * pxPerSec);
    const barWidth = Math.max(1, segWidth / frameCount);
    for (let i = 0; i < frameCount; i++) {
      const value = rms[startFrame + i] ?? 0;
      const h = (value / 255) * (canvas.height - 4);
      g.fillRect(segLeft + (i / frameCount) * segWidth, mid - h / 2, barWidth, h);
    }
  }
}

/** The selected words' span, if the shell exposes one. Nothing in the
 * documented `ctx`/bus contract names a selection event today — this
 * listens for a speculative `'selection'` event `{indices: [wordIndex,
 * …]}` (mirroring `'playing-word'`'s `{index}`) and degrades to a plain
 * timeline, unhighlighted, until some pane actually emits it. See this
 * stage's report for the exact contract assumed. */
function drawSelectionHighlight(lanes, indices, pxPerSec, state) {
  if (!state.words || !indices || !indices.length) return;
  const set = new Set(indices);
  const spans = state.words.filter((w) => w.present && set.has(w.index));
  if (!spans.length) return;
  const start = Math.min(...spans.map((w) => w.timeline_start));
  const end = Math.max(...spans.map((w) => w.timeline_end));
  const box = el("div", "drag-box");
  box.style.left = `${(start * pxPerSec).toFixed(1)}px`;
  box.style.width = `${Math.max(1, (end - start) * pxPerSec).toFixed(1)}px`;
  lanes.append(box);
}

function render() {
  const headers = $("track-headers");
  const lanes = $("track-lanes");
  if (!headers || !lanes) return;
  headers.textContent = "";
  lanes.textContent = "";
  headers.append(el("div", "track-header ruler-spacer"));

  const state = lastState;
  if (!state || !state.segments) {
    lanes.append(el("div", "ruler"));
    return;
  }

  const duration = Math.max(state.timeline_duration, 0.001);
  const pxPerSec = computePxPerSec(duration);
  currentPxPerSec = pxPerSec;
  lanes.append(buildRuler(duration, pxPerSec));

  const clip = state.clips.find((c) => c.clip_id === state.clip_id) || {};

  // Lanes are projections of one single-track `Edit`, drawn from
  // `state.segments` only — the same segments `export` renders. No V2, no
  // A2, no lane `export` cannot produce (CLAUDE.md; PLAN.md § The trap
  // this section exists to write down).
  const kinds = [];
  if (clip.has_video) kinds.push("V1");
  kinds.push("A1"); // always — the recording has audio even for a picture clip
  if (state.words && state.words.length) kinds.push("CC"); // captions come out of the timeline (CLAUDE.md) — any transcript is enough to try

  const waveformDraws = [];
  for (const kind of kinds) {
    headers.append(header(kind));
    const row = buildLaneRow(kind, state.segments, pxPerSec, duration, state);
    if (kind === "A1") {
      const canvas = el("canvas", "waveform-canvas");
      // The blocks underneath still carry hover/title/hit-testing; letting
      // the canvas ignore pointer events is what keeps that true once it's
      // painted on top of them.
      canvas.style.pointerEvents = "none";
      row.append(canvas);
      waveformDraws.push(() =>
        drawWaveformLane(canvas, state.segments, pxPerSec, row.clientHeight || laneHeightPx(), duration * pxPerSec),
      );
    }
    lanes.append(row);
  }

  const playhead = el("div", "playhead-line");
  playhead.id = "timeline-playhead";
  playhead.style.left = `${(ctx ? ctx.player.now() : 0) * pxPerSec}px`;
  lanes.append(playhead);

  if (selection) drawSelectionHighlight(lanes, selection, pxPerSec, state);

  // Deferred until the rows are actually in the DOM: drawWaveformLane reads
  // row.clientHeight, which is 0 for a detached node.
  for (const draw of waveformDraws) draw();
}

export function init(passedCtx) {
  ctx = passedCtx;

  const zoomInput = $("zoom");
  if (zoomInput) {
    zoomMultiplier = parseFloat(zoomInput.value) || 1;
    zoomInput.addEventListener("input", () => {
      zoomMultiplier = parseFloat(zoomInput.value) || 1;
      if (lastState) render();
    });
  }

  window.addEventListener("resize", () => {
    if (lastState) render();
  });

  // Cheap per-frame path: player.js emits this every animation frame, so
  // this must not re-render the whole lane set — just slide the one line,
  // in the same px-per-second coordinate space `render()` last computed.
  ctx.on("playhead", ({ now }) => {
    const line = $("timeline-playhead");
    if (line) line.style.left = `${now * currentPxPerSec}px`;
  });

  // Speculative — see drawSelectionHighlight's comment above.
  ctx.on("selection", (payload) => {
    selection = payload && Array.isArray(payload.indices) && payload.indices.length ? payload.indices : null;
    if (lastState) render();
  });
}

export function update(state) {
  lastState = state;
  render();
}
