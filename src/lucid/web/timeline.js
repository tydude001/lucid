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
 * **Filmstrip thumbnails, V1 and V2, same trap the waveform names above.** A
 * shot (or a segment) plays a stretch of its own source starting at
 * `src_start` (V2) or `start` (V1/A1) — never from the head of the file, so
 * a clip used three times reads from three different places and a filmstrip
 * that reloaded each block from 0 would draw a real-looking, wrong film
 * (CLAUDE.md). `buildFilmstrip` below is given exactly the one source second
 * each block already carries and walks forward from there — the same
 * source-second-plus-offset arithmetic `drawWaveformLane` already does one
 * lane down, just against `/api/thumb/<clip_id>?at=<seconds>` (`ops.thumbnail`,
 * itself bucketed to `THUMB_INTERVAL` and cached under `cache/thumbs/`)
 * instead of a cached RMS array. No client-side cache is kept for it —
 * unlike the waveform, a thumbnail is a plain `<img src>`, and the browser's
 * own HTTP cache already dedupes identical URLs across re-renders.
 *

 * See transcript.js's header comment for the full pane-module interface —
 * `ctx` shape, bus event names, and the `state` shape — this file does not
 * repeat it.
 */

import { $, el, fmt, secs, clampFloating } from "./dom.js";

let ctx = null;
let lastState = null;
let zoomMultiplier = 1; // multiplies the fit-to-window base — #zoom is 1..10
let currentPxPerSec = 1; // cached for the per-frame playhead handler, which
// must not pay for a full re-render 60 times a second
let followPlayhead = true; // F5, default ON per the contract — index.html's
// own #follow-playhead ships with its 'on' class already applied so there is
// no flash of the wrong state before this file's init() runs; this variable
// just has to agree with that markup, not set it.
let lastFollowScrollLeft = null; // the scrollLeft THIS FILE last set via the
// follow nudge, compared against what #track-lanes's own 'scroll' event later
// reports — not a boolean "ignore the next event" flag. A flag cannot survive
// a nudge that lands on a value the lane is already at: setting scrollLeft to
// its current value dispatches NO 'scroll' event at all, so a flag armed and
// never consumed would misattribute some LATER real user scroll as the nudge
// that never fired, and follow would silently fail to disengage. Comparing
// the reported value against the one this file itself last wrote means a
// stale unconsumed value only ever fails to match a real scroll to a
// different pixel — it does not falsely swallow one.
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
const THUMB_TARGET_PX = 64; // desired on-screen width per filmstrip frame
const THUMB_MIN_BLOCK_PX = 24; // below this a block is too narrow for even one legible frame

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
    // Same fix as buildPictureRow's identical branch, same reason: a
    // refusal should not silently drop the lane out of seekOnClick's "every
    // lane" guarantee.
    seekOnClick(row, pxPerSec);
    return row;
  }

  for (const cue of captions.cues) {
    const block = el("div", "clip-block");
    block.style.left = `${(cue.start * pxPerSec).toFixed(1)}px`;
    block.style.width = `${Math.max(1, (cue.end - cue.start) * pxPerSec).toFixed(1)}px`;
    block.textContent = cue.text;
    block.title = `${fmt(cue.start)}–${fmt(cue.end)} · ${cue.words.length} words\n${cue.text}`;
    // A CueWord (captions.py) carries text/start/end only, no transcript word
    // index — grouping is a placed, styled derivation and does not keep one.
    // Nearest-by-time against the transcript's own words is the same
    // approximation `nearestWordAt` already makes for a lane drag, applied to
    // a cue's start instead of a click point.
    block.addEventListener("click", () => {
      if (!ctx || !lastState || !lastState.words) return;
      const word = nearestWordAt(lastState.words, cue.start);
      if (word) ctx.emit("inspect-word", { clipId: lastState.clip_id, wordIndex: word.index });
    });
    row.append(block);
  }

  seekOnClick(row, pxPerSec);
  return row;
}

/** One filmstrip: a row of `<img>` elements reading `clipId`'s own source
 * forward from `sourceStart`, one every `THUMB_TARGET_PX`-ish on-screen
 * pixels — the mapping this file's header comment names as the trap. Each
 * frame's `at=` is `/api/thumb`'s own address (source seconds, snapped
 * server-side to `THUMB_INTERVAL`), never a timeline second and never 0.
 *
 * Every image gets an explicit pixel width up front rather than sizing off
 * its own decoded aspect ratio — an unset width collapses to 0 until the
 * network round trip finishes, which would draw an empty lane on first
 * paint and reflow every block under it once thumbnails arrived. `object-fit:
 * cover` (app.css) crops each frame to that fixed box instead.
 *
 * A block wider than its own duration's worth of pixels near its right edge
 * (the last frame, clipped by the block's own `overflow: hidden`) is normal
 * and left alone — matching how the picture lane already tolerates its own
 * frame-grid/ruler-seconds mismatch (this file's header comment, one
 * paragraph up). Returns `null` for a block too narrow to bother (below
 * `THUMB_MIN_BLOCK_PX`), so a caller can skip appending it. */
function buildFilmstrip(clipId, sourceStart, durationSec, pxPerSec) {
  if (!(durationSec > 0) || !(pxPerSec > 0) || durationSec * pxPerSec < THUMB_MIN_BLOCK_PX) {
    return null;
  }
  const strip = el("div", "filmstrip");
  const stepSec = Math.max(1, THUMB_TARGET_PX / pxPerSec);
  for (let t = 0; t < durationSec; t += stepSec) {
    const widthPx = Math.min(stepSec, durationSec - t) * pxPerSec;
    if (widthPx < 2) continue;
    const img = document.createElement("img");
    img.alt = "";
    img.loading = "lazy";
    img.style.width = `${widthPx.toFixed(1)}px`;
    img.src = `/api/thumb/${encodeURIComponent(clipId)}?at=${(sourceStart + t).toFixed(3)}`;
    // A clip with no video track (audio-only, or media missing from disk)
    // 400s — same "refused" discipline as the picture lane's own
    // `shots_error`, but at single-frame granularity a toast per image would
    // be noise, so this just leaves the block's own label showing through
    // an empty strip rather than a broken-image glyph.
    img.addEventListener("error", () => {
      img.style.display = "none";
    });
    strip.append(img);
  }
  return strip;
}

/** One row: a `.clip-block` per timeline segment (hover/title/hit-testing,
 * per PLAN.md § The timeline — DOM, not canvas, for exactly this reason)
 * plus a `.seam-tick` per cut boundary, and a click-to-seek handler on the
 * row itself so a click anywhere in the lane — including on a child block —
 * seeks the player (event bubbling; the handler reads the row's own
 * bounding rect, so it works regardless of scroll or which child was hit). */
function buildLaneRow(kind, segments, pxPerSec, duration, state, withFilmstrip) {
  const row = el("div", `lane lane-${kind.toLowerCase()}`);
  row.style.width = `${Math.max(1, duration * pxPerSec)}px`;

  for (const seg of segments) {
    const block = el("div", "clip-block");
    const blockWidth = Math.max(1, (seg.timeline_end - seg.timeline_start) * pxPerSec);
    block.style.left = `${(seg.timeline_start * pxPerSec).toFixed(1)}px`;
    block.style.width = `${blockWidth.toFixed(1)}px`;
    block.title = `${seg.clip_id} · source ${secs(seg.start)}–${secs(seg.end)} · timeline ${fmt(seg.timeline_start)}–${fmt(seg.timeline_end)}`;
    if (withFilmstrip) {
      const strip = buildFilmstrip(seg.clip_id, seg.start, seg.end - seg.start, pxPerSec);
      if (strip) block.append(strip);
      block.append(el("span", "clip-label", seg.clip_id));
    } else {
      block.textContent = seg.clip_id;
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
    // seekOnClick is "shared by every lane so the picture lane cannot drift
    // into being the one that does not seek" (this file's own doc comment
    // on seekOnClick) — a refusal is exactly the state that comment is
    // guarding against silently losing, so it still applies here. Found via
    // the browser pass's assertion-5 control click landing on a refused V2
    // lane and doing nothing.
    seekOnClick(row, pxPerSec);
    return row;
  }

  shots.forEach((shot, index) => {
    const block = el("div", `clip-block shot-block${shot.is_image ? " shot-card" : ""}`);
    block.style.left = `${(shot.start * pxPerSec).toFixed(1)}px`;
    block.style.width = `${Math.max(1, shot.duration * pxPerSec).toFixed(1)}px`;
    block.title = shotTitle(shot, state, index);
    // A card is a still asset, not a clip's own footage — /api/thumb only
    // ever answers for a video-carrying clip_id (ops.thumbnail refuses one
    // with no video track), so there is nothing to sample for one.
    //
    // **`shot.asset` is the footage being shown; `shot.clip_id` is the cue's
    // OWN address — the transcript clip its word_index lives on, which on
    // this project is `vo`, an audio-only clip with no video track of its
    // own.** Sampling `shot.clip_id` here would ask `/api/thumb` for a frame
    // of the voiceover on every single shot and 400 every time — exactly
    // the reload-from-the-wrong-source trap this file's header comment
    // names, just one field over rather than one asset-use over. `asset` is
    // what `shotLabel`/`shotTitle` already draw the block's own label from.
    if (!shot.is_image) {
      const strip = buildFilmstrip(shot.asset, shot.src_start, shot.duration, pxPerSec);
      if (strip) block.append(strip);
      block.append(el("span", "clip-label", shotLabel(shot)));
    } else {
      block.textContent = shotLabel(shot);
    }
    // Target-phase listener: fires before the row's own bubble-phase
    // seekOnClick (below), so a shot click both inspects its cue AND seeks —
    // harmless, and it means this needs no stopPropagation.
    block.addEventListener("click", () => {
      if (ctx) ctx.emit("inspect-word", { clipId: shot.clip_id, wordIndex: shot.word_index });
    });
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
  // `getBoundingClientRect` is the container's own on-screen box, which does
  // NOT move when its content scrolls (only `overflow-x: auto`'s content
  // does) — so a click after scrolling the timeline needs `scrollLeft` added
  // back in, or it resolves against whatever was under this same screen x at
  // scrollLeft 0. Confirmed by driving a real drag at a fixed screen point
  // under two scroll positions: unpatched, both resolved the same word
  // regardless of which part of the transcript was actually under the
  // cursor (browser pass, CLAUDE.md's discipline of verifying against the
  // real running service). `seekOnClick` does not have this bug because it
  // reads the *row's* rect, which does move with scroll.
  return Math.max(0, (event.clientX - rect.left + lanes.scrollLeft) / currentPxPerSec);
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

/** Clamps a floating toolbar's raw drop point to the lanes pane's own
 * *visible* box — never trusted as-is (browser pass: an unclamped drop on
 * the bottom-most lane rendered the whole toolbar past both `#track-lanes`'s
 * own `overflow-y: hidden` clip and the browser viewport, at zero opacity of
 * "found" — no error, just nothing a person could see or click). Unhide
 * before measuring: a `hidden` element reports a zero-size rect, which would
 * clamp everything to (0, 0). `boxLeft` is in the same content-relative
 * coordinate space `laneTimeFromEvent` resolves a click into (scrollLeft
 * already folded in at drag time), so the clamp's own bounds are the visible
 * window converted into that same space — `[lanes.scrollLeft, scrollLeft +
 * clientWidth]` — not `[0, clientWidth]`.
 *
 * The clamp MATH now lives once, in `dom.js`'s `clampFloating` — shared with
 * transcript.js's own selection toolbar, which had this exact bug fixed here
 * first and then carried it separately (a duplicated fix is how F4 reached
 * only one of the two toolbars the first time). This file still supplies its
 * OWN bounds rather than a container element: transcript.js's toolbar lives
 * in unscrolled space (`[0, container.clientWidth]`) while this one's
 * `boxLeft`/`boxTop` already have `lanes.scrollLeft` folded in, so its bounds
 * are the visible window in that same scrolled space — a helper that derived
 * bounds from `clientWidth` alone would be correct for one caller and
 * silently wrong for the other. */
function refreshCueToolbar() {
  if (!cueToolbarEl) return;
  if (!cueSelection || !lastState || !lastState.words) {
    cueToolbarEl.hidden = true;
    return;
  }
  cueInfoEl.textContent = cueEcho(lastState.words, cueSelection.wordIndex);
  cueToolbarEl.hidden = false;

  const lanes = $("track-lanes");
  if (lanes) {
    const { left, top } = clampFloating(
      cueSelection.boxLeft,
      cueSelection.boxTop,
      cueToolbarEl.offsetWidth,
      cueToolbarEl.offsetHeight,
      lanes.scrollLeft,
      lanes.scrollLeft + lanes.clientWidth,
      0,
      lanes.clientHeight,
    );
    cueToolbarEl.style.left = `${left.toFixed(1)}px`;
    cueToolbarEl.style.top = `${top.toFixed(1)}px`;
  } else {
    cueToolbarEl.style.left = `${cueSelection.boxLeft.toFixed(1)}px`;
    cueToolbarEl.style.top = `${cueSelection.boxTop.toFixed(1)}px`;
  }
}

/** Redraws only the drag-box, leaving every lane/row/block untouched.
 *
 * `render()` is not safe to call from `handleLanesMouseDown`/`Move`, or from
 * `handleLanesMouseUp`'s non-drag branch — it does `lanes.textContent = ""`
 * then rebuilds every lane wholesale, which removes whatever node the
 * in-progress gesture is anchored to. A `setTimeout(render, 0)` used to sit
 * in those three spots instead of a synchronous call, and it is not a fix,
 * only a race it usually wins: CDP's back-to-back mousePressed/mouseReleased
 * has no gap for the timer to land in before mouseup, so it read as correct
 * against a scripted test. Driven with a realistic human dwell between press
 * and release (measured 10ms-250ms; a real click dwells roughly 60-150ms),
 * the timer fires *during* the dwell, the mousedown target is gone by the
 * time mouseup arrives, and Chrome suppresses the trailing native 'click'
 * exactly as it did before the timer existed — click-to-seek stayed broken
 * for every real click on a transcript lane, just no longer for a
 * script-driven one. Measured with a dwell-time probe:
 * `/home/<user>/.claude/jobs/c23505b8/tmp/dwell/dwell_probe.py` — seeks at
 * 0ms and 5ms dwell, silently fails at 10ms and every dwell above it.
 *
 * The highlight is the only thing a mousedown/mousemove/plain-click-release
 * changes, and `drawSelectionHighlight` already draws it as one standalone
 * `.drag-box` appended to `lanes` — so removing that element and redrawing
 * it (if `selection` is set) is the whole update, and it never touches the
 * row/block elements a gesture or a pending click is anchored to. */
function updateSelectionHighlight() {
  const lanes = $("track-lanes");
  if (!lanes || !lastState) return;
  for (const box of lanes.querySelectorAll(".drag-box")) box.remove();
  if (selection) drawSelectionHighlight(lanes, selection, currentPxPerSec, lastState);
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
    ctx.emit("toast", "Type an asset — a clip_id or card:name — before placing the cue.");
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
  // A drag's own trailing native 'click' is not guaranteed to follow its
  // mouseup — measured by driving real Input events: a press/release pair at
  // different points produced no 'click' at all here, so a stale `true` left
  // by a drag would otherwise swallow the *next* click instead of the drag's
  // own, which — right after placing a drag selection — is a click on the
  // toolbar's own "Place cue" button (browser pass). Any new mousedown means
  // that window has closed either way, so clear it unconditionally before
  // anything else below runs, including the toolbar-click early return.
  suppressNextClick = false;
  if (cueToolbarEl && cueToolbarEl.contains(event.target)) return;
  if (!lastState || !lastState.words || !lastState.words.length) return;
  const word = nearestWordAt(lastState.words, laneTimeFromEvent(event));
  if (!word) {
    if (ctx) ctx.emit("toast", "No word here to anchor a cue to — every word in this clip is cut.");
    return;
  }
  cueSelection = null;
  refreshCueToolbar();
  cueDrag = { anchorIndex: word.index, currentIndex: word.index, moved: false };
  selection = [word.index];
  // properties.js's word-inspection input — raised on every lane mousedown
  // that resolves to a word, drag or plain click alike, since a plain click
  // throws the resolved word away below (no cue gesture follows it) and
  // inspecting it is a reasonable thing for a click to do along the way.
  if (ctx) ctx.emit("inspect-word", { clipId: lastState.clip_id, wordIndex: word.index });
  // See updateSelectionHighlight's own comment: a full render() here (even
  // deferred) tears down whatever node this mousedown landed on, and a
  // realistic human dwell before mouseup gives a deferred one time to fire
  // before the click is dispatched — measured, not assumed.
  updateSelectionHighlight();
}

function handleLanesMouseMove(event) {
  if (!cueDrag || !lastState || !lastState.words) return;
  const word = nearestWordAt(lastState.words, laneTimeFromEvent(event));
  if (!word) return;
  if (word.index !== cueDrag.anchorIndex) cueDrag.moved = true;
  cueDrag.currentIndex = word.index;
  selection = [cueDrag.anchorIndex, cueDrag.currentIndex];
  // Same reason as handleLanesMouseDown: a full render() on every mousemove
  // tore down and rebuilt every lane dozens of times over one drag, for a
  // change that is only ever the highlight box.
  updateSelectionHighlight();
}

function handleLanesMouseUp(event) {
  if (!cueDrag) return;
  if (cueDrag.moved) {
    suppressNextClick = true;
    const lanes = $("track-lanes");
    const rect = lanes.getBoundingClientRect();
    // boxLeft lives in the same content-relative space laneTimeFromEvent
    // resolves a click into — scrollLeft folded back in, for the same
    // reason (the container's own rect does not move when its content
    // scrolls). refreshCueToolbar's clamp expects this space.
    cueSelection = {
      wordIndex: cueDrag.anchorIndex,
      boxLeft: Math.max(0, event.clientX - rect.left + lanes.scrollLeft),
      boxTop: Math.max(0, event.clientY - rect.top + 10),
    };
    refreshCueToolbar();
  } else {
    selection = null;
    // Same reason as handleLanesMouseDown: this mouseup's handlers run
    // before the browser decides whether to dispatch the trailing 'click'
    // for this exact gesture, and any render() here — deferred or not —
    // risks removing the clicked node out from under that decision.
    updateSelectionHighlight();
  }
  cueDrag = null;
}

/** F5 — nudges `#track-lanes`'s `scrollLeft` so the playhead stays inside
 * the middle ~60% of the visible lane while playing. Called from the SAME
 * per-frame `'playhead'` subscription that already moves the line, and must
 * touch nothing but `scrollLeft` — no `render()`, on this file's own
 * "redraw only the node a gesture owns" discipline (`updateSelectionHighlight`'s
 * comment above): this runs every animation frame, so anything heavier than
 * a scroll assignment here would cost what the deferred-render race already
 * cost this repo a day to find, just on a hot path instead of a gesture.
 *
 * Measured at zoom 6.0x before this existed: viewport 1516px, content
 * 9101px, playhead at 4548px with scrollLeft stuck at 0 — the timeline
 * silently stopped being a view of what was playing within seconds of
 * pressing play. */
function nudgePlayhead(nowSec) {
  if (!followPlayhead || !ctx || !ctx.player.playing()) return;
  const lanes = $("track-lanes");
  if (!lanes) return;
  const viewport = lanes.clientWidth;
  if (!(viewport > 0)) return;
  const playheadPx = nowSec * currentPxPerSec;
  const visibleLeft = lanes.scrollLeft;
  const margin = viewport * 0.2; // 20% each side leaves the middle 60% named above
  if (playheadPx >= visibleLeft + margin && playheadPx <= visibleLeft + viewport - margin) return;
  const maxScroll = Math.max(0, lanes.scrollWidth - viewport);
  const target = Math.min(maxScroll, Math.max(0, playheadPx - viewport / 2));
  lanes.scrollLeft = target;
  // Read back rather than trust `target`: the browser clamps scrollLeft to
  // its own valid range, and the value the 'scroll' event later reports is
  // THAT clamped number, not the one just assigned.
  lastFollowScrollLeft = lanes.scrollLeft;
}

/** The click handler for `#follow-playhead` and the disengage branch of the
 * `#track-lanes` 'scroll' listener share this — one place that keeps the
 * variable and the button's `.on` class from drifting apart. */
function setFollowPlayhead(value) {
  followPlayhead = value;
  const btn = $("follow-playhead");
  if (btn) btn.classList.toggle("on", followPlayhead);
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
          : buildLaneRow(kind, state.segments, pxPerSec, duration, state, kind === "V1");
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

  const followBtn = $("follow-playhead");
  if (followBtn) {
    followBtn.classList.toggle("on", followPlayhead); // agree with the markup's own default-on class
    followBtn.addEventListener("click", () => setFollowPlayhead(!followPlayhead));
  }
  if (lanes) {
    lanes.addEventListener("scroll", () => {
      // See lastFollowScrollLeft's own comment: compare the reported value,
      // don't trust a flag. A match means this file's own nudge produced
      // this event — consume it and leave follow engaged. Anything else,
      // including a nudge that landed on the SAME pixel it started at (which
      // dispatches no event and so is never seen here at all), is a real
      // scroll and releases follow so it never fights a person scrubbing by
      // hand.
      if (lastFollowScrollLeft !== null && lanes.scrollLeft === lastFollowScrollLeft) {
        lastFollowScrollLeft = null;
        return;
      }
      if (followPlayhead) setFollowPlayhead(false);
    });
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
    nudgePlayhead(now); // F5 — see nudgePlayhead's own comment: scrollLeft only, never render()
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
