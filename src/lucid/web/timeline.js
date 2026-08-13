/**
 * timeline.js — the real timeline of PLAN.md § Tier 3 is the goal:
 * a ruler with time labels, pixels-per-second zoom (fit-to-window
 * by default), sticky track headers, named clip blocks, an A1 waveform
 * canvas from `/api/waveform/<clip_id>`, click-to-seek, and a
 * playhead driven by player.js (PLAN.md § The timeline).
 *
 * Lanes are projections of one `Edit`, never independent tracks, and no
 * lane is drawn that `export` cannot produce — auto-editor 31.x degrades a
 * multi-*source* render to 720x576 with a warning and exit 0 rather than
 * failing, so a lane this view drew ahead of the model would look right
 * and export wrong (CLAUDE.md; PLAN.md § The trap this section exists to
 * write down). V1 only when the displayed clip `has_video`, A1 always (the
 * recording has audio even for a picture clip), CC only when a transcript
 * exists to caption from. V1 and A1 are built from `state.segments`, the same
 * single track `export` reads.
 *
 * **CC is built from `/api/captions`, not from segments**, and the difference
 * is the same rule V2 is held to: a cue breaks on sentence ends, silences and
 * a word count, so one block per segment drew caption lines the `.ass` file
 * will never contain. See `buildCaptionRow`.
 *
 * **V2 is the picture lane, and it became legal at step 5 and not before**
 * (PLAN.md § The layered timeline, build order step 6): `export` renders a
 * layered timeline through MLT and `melt` now, so there is finally a lane
 * the file will agree with. It is drawn from `state.shots` and nothing
 * else — `ops._picture_plan`'s answer, which is `build_shots` *already put
 * through the MLT writer's planner*, so a shot the writer would refuse is
 * never drawn as though it would render. When the plan refuses, the view
 * sends `shots_error` instead of shots and this lane draws the message:
 * a stale cue is exactly the thing a person opens this window to find, so
 * the lane says so rather than quietly disappearing.
 *
 * One honest asymmetry to expect: V2 runs on `export`'s frame grid
 * (`state.shots_rate`) while the ruler runs on the edit's own seconds, so
 * the last shot can end a fraction of a frame past the ruler — 411.077s of
 * picture against 410.963s of edit on the Scream assembly. That is
 * `frame_total` versus a summed duration (CLAUDE.md), not a drawing bug,
 * and the lane is sized to whichever is longer rather than clipped to hide
 * it.
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
let selection = null; // word indices to highlight — set by this file's own
// drag gesture below, or by the 'selection' bus event for any other pane
// that wants to drive the highlight
let cueDrag = null; // {anchorIndex, currentIndex, moved} while a mousedown
// on the lanes is live — anchorIndex is the drag's *start* word, which is
// the only address `cue_add` uses (PLAN.md § Three uncosted parity items:
// "only a drag's start needs an address")
let cueSelection = null; // {wordIndex, boxLeft, boxTop} once a real drag
// (cueDrag.moved) finishes — drives the floating cue-placement toolbar
let cueToolbarEl = null;
let cueInfoEl = null;
let suppressNextClick = false; // set when a drag moved, so the native
// 'click' a mouseup can still fire doesn't also trigger seekOnClick

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

function header(label, title) {
  const node = el("div", "track-header", label);
  if (title) node.title = title;
  return node;
}

/** Click anywhere in a lane — including on a child block — seeks the player.
 * Event bubbling plus the row's own bounding rect, so it works regardless of
 * scroll or which child was hit. Shared by every lane so the picture lane
 * cannot drift into being the one that does not seek. */
function seekOnClick(row, pxPerSec) {
  row.addEventListener("click", (event) => {
    if (!ctx) return;
    const rect = row.getBoundingClientRect();
    ctx.player.seek((event.clientX - rect.left) / pxPerSec);
  });
}

function laneHeightPx() {
  const raw = getComputedStyle(document.documentElement).getPropertyValue("--lane-h");
  const n = parseFloat(raw);
  return Number.isFinite(n) && n > 0 ? n : LANE_H_FALLBACK;
}

/** The waveform's ink, read off the canvas's own computed `color`.
 *
 * A canvas fill cannot inherit, so the colour has to come across from CSS
 * somehow — and it is deliberately NOT read from the `--waveform-ink` custom
 * property, because a custom property reads back as its literal text
 * (`light-dark(…)`), which `fillStyle` cannot parse and silently ignores. A
 * real `color` on a real element is resolved to `rgb(…)` before JS sees it.
 * app.css's header has the full account; this was a black-on-black waveform
 * in the dark theme until a real browser showed it. */
function canvasInk(canvas, fallback) {
  return getComputedStyle(canvas).color || fallback;
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

/** The CC lane: one block per *cue*, straight off `/api/captions`.
 *
 * Not one block per segment, which is what this drew until captions grew a
 * stored style. A segment is a piece of the edit and a cue is a line of
 * subtitle, and they are not the same shape — cues break on sentence ends,
 * silences and a word count, so a lane of segments showed caption blocks the
 * `.ass` file will never contain. That is the picture lane's rule applied to
 * this one (never draw a lane the export cannot produce), and it is the same
 * failure in a quieter register: nothing looks wrong, it is just a different
 * set of captions from the ones that ship.
 *
 * Consequently the grouping is never computed here — `ops._caption_cues` is
 * the one derivation, and this draws its answer, refusals included. */
function buildCaptionRow(captions, pxPerSec, duration) {
  const row = el("div", "lane lane-cc");
  row.style.width = `${Math.max(1, duration * pxPerSec)}px`;

  if (!captions || captions.cues_error) {
    const why = captions ? captions.cues_error : "captions unavailable";
    row.append(el("div", "lane-refusal", `no captions — ${why}`));
    return row;
  }

  for (const cue of captions.cues) {
    const block = el("div", "clip-block");
    block.style.left = `${(cue.start * pxPerSec).toFixed(1)}px`;
    block.style.width = `${Math.max(1, (cue.end - cue.start) * pxPerSec).toFixed(1)}px`;
    block.textContent = cue.text;
    block.title = `${fmt(cue.start)}–${fmt(cue.end)} · ${cue.words.length} words\n${cue.text}`;
    row.append(block);
  }

  seekOnClick(row, pxPerSec);
  return row;
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
    block.textContent = seg.clip_id;
    block.title = `${seg.clip_id} · source ${secs(seg.start)}–${secs(seg.end)} · timeline ${fmt(seg.timeline_start)}–${fmt(seg.timeline_end)}`;
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

  seekOnClick(row, pxPerSec);
  return row;
}

/** What a shot shows, said the way a person names it: a card by its own name,
 * a film clip by its clip_id. `card:` is the cue table's own prefix and it is
 * noise once the block is tinted as a still. */
function shotLabel(shot) {
  return shot.asset.startsWith("card:") ? shot.asset.slice("card:".length) : shot.asset;
}

/** Everything a shot is, on hover — and the two facts that are only visible
 * here. **Where inside the asset it reads**, because a clip used three times
 * shows three different stretches of itself and a lane of identical blocks
 * cannot say which; and **the cue that put it there**, by word index and text,
 * because that is the thing a person edits to move the shot (the word index
 * addresses the source and never renumbers — PLAN.md § The property everything
 * below defends). The first shot says out loud that it does not start at its
 * own cue: the picture track is contiguous by construction, so whichever cue
 * resolves first covers from the open regardless of where its word lands.
 *
 * Whether that in-point is *pinned* is the third fact, and it is not cosmetic:
 * an unpinned shot's content slides when an upstream cue moves, and a pinned
 * one's does not — it shows the moment its cue names or `export` refuses
 * (PLAN.md § B-roll by description). Two shots reading from the same second
 * look identical here otherwise. */
function shotTitle(shot, state, index) {
  const rate = state.shots_rate;
  const pinned = shot.src_pin !== null && shot.src_pin !== undefined;
  const lines = [
    `${shotLabel(shot)} · ${fmt(shot.start)}–${fmt(shot.start + shot.duration)} · ${shot.frames} frames${rate ? ` @ ${rate.toFixed(3)}fps` : ""}`,
    shot.is_image
      ? "a card, held for the shot"
      : `reads the asset from ${fmt(shot.src_start)}${pinned ? " — pinned there by the cue" : ""}`,
    `cue: ${shot.clip_id} word ${shot.word_index} — ${shot.text}`,
  ];
  if (index === 0) lines.push("(the first shot covers from the open, not from its own cue's word)");
  return lines.join("\n");
}

/** V2 — the picture lane, drawn from `state.shots` and nothing else.
 *
 * `state.shots` is the projection *already put through the MLT writer's
 * planner* (`ops._picture_plan`), so every block here is a shot `export` will
 * actually produce. When the plan refuses instead, the view sends
 * `shots_error` and this draws the message across the lane: a cue that was
 * cut, or a shot longer than the clip it points at, is the thing a person
 * opened this window to find, and a lane that silently vanished would hide it.
 */
function buildPictureRow(state, pxPerSec, duration) {
  const row = el("div", "lane lane-v2");
  const shots = state.shots || [];
  // The picture runs on export's frame grid and the ruler on the edit's
  // seconds, so the last shot can end a hair past the ruler — size to the
  // longer of the two rather than clip the difference out of sight.
  const last = shots.length ? shots[shots.length - 1] : null;
  const end = last ? last.start + last.duration : duration;
  row.style.width = `${Math.max(1, Math.max(duration, end) * pxPerSec)}px`;

  if (state.shots_error) {
    row.append(el("div", "lane-refusal", `picture refused — ${state.shots_error}`));
    return row;
  }

  shots.forEach((shot, index) => {
    const block = el("div", `clip-block shot-block${shot.is_image ? " shot-card" : ""}`);
    block.style.left = `${(shot.start * pxPerSec).toFixed(1)}px`;
    block.style.width = `${Math.max(1, shot.duration * pxPerSec).toFixed(1)}px`;
    block.textContent = shotLabel(shot);
    block.title = shotTitle(shot, state, index);
    row.append(block);
  });

  seekOnClick(row, pxPerSec);
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
  g.fillStyle = canvasInk(canvas, "rgba(20, 22, 26, 0.55)"); // read over the block's own pastel

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

/** The selected words' span, if there is one. Driven by this file's own
 * drag gesture (below) — a click-and-drag on any lane resolves to a pair
 * of word indices — or by an external `'selection'` event `{indices:
 * [wordIndex, …]}` (mirroring `'playing-word'`'s `{index}`), for any other
 * pane that wants to drive the highlight without owning the box math. Only
 * the extremal two of `indices` matter: `state.words` is filtered to the
 * given set and the box spans their min `timeline_start` to max
 * `timeline_end`, so `[first, last]` alone is enough. */
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

/** Timeline second -> nearest word, client-side mirror of `ops._nearest_word`
 * (overlap test first, nearest by edge distance across a gap otherwise) —
 * but over `state.words`' own `timeline_start`/`timeline_end`, since the
 * client already has that array for drawing and a drag needs no server
 * round trip to resolve. Settled by measurement, not guessed at (PLAN.md §
 * Three uncosted parity items: 85-87% of drags land on a word directly; the
 * residual is inter-word silence with a 0.54s median gap, snapped here to
 * whichever word is closer). Present words only — a cut word has no
 * meaningful timeline position to measure from. */
function nearestWordAt(words, t) {
  let nearest = null;
  let nearestDist = Infinity;
  for (const w of words) {
    if (!w.present) continue;
    if (t >= w.timeline_start && t < w.timeline_end) return w;
    const dist = t < w.timeline_start ? w.timeline_start - t : t - w.timeline_end;
    if (dist < nearestDist) {
      nearestDist = dist;
      nearest = w;
    }
  }
  return nearest;
}

function laneTimeFromEvent(event) {
  const lanes = $("track-lanes");
  const rect = lanes.getBoundingClientRect();
  return Math.max(0, (event.clientX - rect.left) / currentPxPerSec);
}

/** Word-range echo, three either side (CLAUDE.md) — the placement word
 * bracketed so it reads correctly even if it lands one off from what the
 * drag looked like it meant. */
function cueEcho(words, wordIndex) {
  return words
    .filter((w) => w.index >= wordIndex - 3 && w.index <= wordIndex + 3)
    .map((w) => (w.index === wordIndex ? `[${w.text}]` : w.text))
    .join(" ");
}

function refreshCueToolbar() {
  if (!cueToolbarEl) return;
  if (!cueSelection || !lastState || !lastState.words) {
    cueToolbarEl.hidden = true;
    return;
  }
  cueInfoEl.textContent = cueEcho(lastState.words, cueSelection.wordIndex);
  cueToolbarEl.style.left = `${cueSelection.boxLeft.toFixed(1)}px`;
  cueToolbarEl.style.top = `${cueSelection.boxTop.toFixed(1)}px`;
  cueToolbarEl.hidden = false;
}

function cancelCueSelection() {
  cueDrag = null;
  cueSelection = null;
  selection = null;
  refreshCueToolbar();
  render();
}

/** `POST /api/cue` — the fourth caller into `ops.cue_add`, alongside the
 * CLI and MCP tool (CLAUDE.md: every mutation posts to the same `ops`
 * function). The result is never rendered here, same rule as Cut/Restore
 * in transcript.js — it goes on the shared bus and agent.js draws it into
 * the feed; 'project-changed' brings the new shot through the normal
 * update() path. */
async function placeCue(assetInput) {
  if (!cueSelection || !ctx || !lastState) return;
  const asset = assetInput.value.trim();
  if (!asset) {
    assetInput.focus();
    return;
  }
  let payload = null;
  let error = null;
  try {
    payload = await ctx.api("/api/cue", {
      clip_id: lastState.clip_id,
      word_index: cueSelection.wordIndex,
      asset,
    });
  } catch (err) {
    error = err.message;
    ctx.emit("toast", error);
  }
  ctx.emit("op-result", { payload, error });
  if (!error) {
    assetInput.value = "";
    cancelCueSelection();
  }
}

function buildCueToolbar() {
  const bar = el("div", "selection-toolbar cue-toolbar");
  bar.hidden = true;

  const info = el("div", "quote");
  const assetInput = document.createElement("input");
  assetInput.type = "text";
  assetInput.placeholder = "asset — clip_id or card:name";
  assetInput.style.width = "18em";
  const placeBtn = el("button", null, "Place cue");
  const cancelBtn = el("button", null, "Cancel");

  placeBtn.addEventListener("click", () => placeCue(assetInput));
  assetInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter") placeCue(assetInput);
    if (event.key === "Escape") cancelCueSelection();
  });
  cancelBtn.addEventListener("click", cancelCueSelection);

  bar.append(info, assetInput, placeBtn, cancelBtn);
  cueToolbarEl = bar;
  cueInfoEl = info;
}

/** Drag-select on the timeline, the third b-roll entry point beside the
 * agent prompt and the transcript selection (DAYDREAM.md). Only the drag's
 * *start* resolves to a word — that measured premise (see `nearestWordAt`'s
 * comment) is what makes this cheap: no gap-anchored address space to
 * build, just a snap onto the existing word-index one. A plain click with
 * no movement is left alone, so `seekOnClick` still owns it. */
function handleLanesMouseDown(event) {
  if (event.button !== 0) return;
  if (cueToolbarEl && cueToolbarEl.contains(event.target)) return;
  if (!lastState || !lastState.words || !lastState.words.length) return;
  const word = nearestWordAt(lastState.words, laneTimeFromEvent(event));
  if (!word) return;
  cueSelection = null;
  refreshCueToolbar();
  cueDrag = { anchorIndex: word.index, currentIndex: word.index, moved: false };
  selection = [word.index];
  render();
}

function handleLanesMouseMove(event) {
  if (!cueDrag || !lastState || !lastState.words) return;
  const word = nearestWordAt(lastState.words, laneTimeFromEvent(event));
  if (!word) return;
  if (word.index !== cueDrag.anchorIndex) cueDrag.moved = true;
  cueDrag.currentIndex = word.index;
  selection = [cueDrag.anchorIndex, cueDrag.currentIndex];
  render();
}

function handleLanesMouseUp(event) {
  if (!cueDrag) return;
  if (cueDrag.moved) {
    suppressNextClick = true;
    const rect = $("track-lanes").getBoundingClientRect();
    cueSelection = {
      wordIndex: cueDrag.anchorIndex,
      boxLeft: Math.max(0, event.clientX - rect.left),
      boxTop: Math.max(0, event.clientY - rect.top + 10),
    };
    refreshCueToolbar();
  } else {
    selection = null;
    render();
  }
  cueDrag = null;
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

  // Which lanes exist is a data question, answered by the view. V1/A1/CC are
  // projections of the one `Edit`, drawn from `state.segments` — the same
  // segments `export` renders. V2 is the cue table's picture, drawn from
  // `state.shots` — which `export` renders through MLT and `melt`, and could
  // not before step 5 (CLAUDE.md; PLAN.md § The layered timeline).
  // The captions are their own read model (/api/captions) — same edit, but
  // placed, grouped and styled, and none of those three are this file's to do.
  const captions = ctx ? ctx.getCaptions() : null;

  const kinds = [];
  if (state.shots || state.shots_error) kinds.push("V2"); // topmost: the picture sits over the edit's own track
  if (clip.has_video) kinds.push("V1");
  kinds.push("A1"); // always — the recording has audio even for a picture clip
  if (state.words && state.words.length) kinds.push("CC"); // captions come out of the timeline (CLAUDE.md) — any transcript is enough to try

  const waveformDraws = [];
  for (const kind of kinds) {
    let note;
    if (kind === "V2") note = "the cue table's picture, over the edit";
    if (kind === "CC") note = "one block per cue, as the .ass will break them";
    headers.append(header(kind, note));
    const row =
      kind === "V2"
        ? buildPictureRow(state, pxPerSec, duration)
        : kind === "CC"
          ? buildCaptionRow(captions, pxPerSec, duration)
          : buildLaneRow(kind, state.segments, pxPerSec, duration, state);
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

  // Persistent node, re-appended every render — `lanes.textContent = ""`
  // above would otherwise drop it along with the rows, and a fresh element
  // each time would lose whatever the asset field has typed in it.
  lanes.append(cueToolbarEl);
  refreshCueToolbar();

  // Deferred until the rows are actually in the DOM: drawWaveformLane reads
  // row.clientHeight, which is 0 for a detached node.
  for (const draw of waveformDraws) draw();
}

export function init(passedCtx) {
  ctx = passedCtx;
  buildCueToolbar();

  const lanes = $("track-lanes");
  if (lanes) {
    lanes.addEventListener("mousedown", handleLanesMouseDown);
    window.addEventListener("mousemove", handleLanesMouseMove);
    window.addEventListener("mouseup", handleLanesMouseUp);
    // Capture phase, so this runs before any row's own bubble-phase
    // seekOnClick listener — a drag that moved should not also seek.
    lanes.addEventListener(
      "click",
      (event) => {
        if (!suppressNextClick) return;
        suppressNextClick = false;
        event.stopPropagation();
        event.preventDefault();
      },
      true,
    );
  }

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

  // The lanes are CSS and repaint themselves, but the waveform is a canvas
  // and holds whatever ink it was drawn with — so a theme flip has to redraw
  // it or it keeps the previous theme's. theme.js raises this for both the
  // toggle and an OS preference change.
  window.addEventListener("lucid:theme", () => {
    if (lastState) render();
  });

  // Cheap per-frame path: player.js emits this every animation frame, so
  // this must not re-render the whole lane set — just slide the one line,
  // in the same px-per-second coordinate space `render()` last computed.
  ctx.on("playhead", ({ now }) => {
    const line = $("timeline-playhead");
    if (line) line.style.left = `${now * currentPxPerSec}px`;
  });

  // This file's own drag gesture (handleLanesMouseDown/Move/Up) sets
  // `selection` directly rather than round-tripping through the bus — this
  // subscription is for any other pane that wants to drive the highlight
  // without duplicating drawSelectionHighlight's box math.
  ctx.on("selection", (payload) => {
    selection = payload && Array.isArray(payload.indices) && payload.indices.length ? payload.indices : null;
    if (lastState) render();
  });
}

export function update(state) {
  lastState = state;
  render();
}
