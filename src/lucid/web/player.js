/* player.js — the seam-jumping playback loop and transport.
 *
 * Ported UNCHANGED in logic from tier 2's app.js (PLAN.md § Files, and why
 * they split: "it is the one genuinely good piece and is not rewritten for
 * tidiness — it is the thing that makes seeing an edit cost no render").
 * What changed is wiring only: DOM ids for the new layout, and reading the
 * view through `ctx.getView()` instead of a module-level variable, because
 * the view now lives in app.js and every pane reads the same copy of it.
 *
 * New in tier 3, and not a logic change to the loop itself: the audio-only
 * level display (PLAN.md § Layout — #viewer is never `display:none`).
 *
 * Exports:
 *   init(ctx)      call once, after `$("media")` etc. exist. Wires the
 *                  <video>, the transport, the audio-only visualiser, and
 *                  starts the tick loop.
 *   update(state)  call with the current /api/view payload whenever it
 *                  changes. Toggles the audio-only state and loads the
 *                  timeline's own clip the first time a view arrives.
 *   player         the object placed on `ctx.player` for the other panes:
 *                    seek(t)       seek the timeline to `t` seconds
 *                    now()         the current timeline second
 *                    toggle()      play/pause
 *                    playing()     bool
 *                    seekWord(w)   seek to a word's timeline_start, if present
 *
 * player.js owns #viewer, #media, #visualizer, #transport, #play, #clock,
 * #playhint and touches no other pane's DOM. Every animation frame it emits
 * a 'playhead' event `{now, total}` on the shared bus, and a 'playing-word'
 * event `{index}` whenever the playing word changes — transcript.js and
 * timeline.js paint their own playheads/highlights from those rather than
 * this module reaching into their DOM (PLAN.md § Files, and why they
 * split: panes never import each other).
 */

import { $, fmt } from "./dom.js";

/* A seam is a seek, and a seek is not sample-accurate. Stop a segment this
 * far early rather than let the first frames of cut material through. */
const SEAM_EPS = 0.02;

let ctx = null;
let media = null;
let visualizer = null;
let vizCtx = null;
let audioCtx = null;
let analyser = null;

let mediaClip = null; // which clip <video> currently has loaded
let segIndex = -1; // which timeline segment is playing
let pendingSeek = null; // a seek waiting on loadedmetadata
let wordCursor = 0; // cache for the playing-word scan

function view() {
  return ctx.getView();
}

function currentClip() {
  const v = view();
  if (!v) return {};
  return v.clips.find((c) => c.clip_id === v.clip_id) || {};
}

function setClip(clipId) {
  if (mediaClip === clipId) return;
  mediaClip = clipId;
  media.src = `/api/media/${encodeURIComponent(clipId)}`;
}

function segAt(t) {
  const segments = view().segments;
  for (let i = 0; i < segments.length; i++) {
    if (t < segments[i].timeline_end - 1e-6) return i;
  }
  return segments.length - 1;
}

function seek(t) {
  const v = view();
  if (!v || !v.segments.length) return;
  t = Math.max(0, Math.min(t, v.timeline_duration));
  segIndex = segAt(t);
  const seg = v.segments[segIndex];
  const target = seg.start + Math.max(0, t - seg.timeline_start);
  if (mediaClip !== seg.clip_id) {
    setClip(seg.clip_id);
    pendingSeek = target;
  } else if (media.readyState === 0) {
    pendingSeek = target;
  } else {
    media.currentTime = target;
  }
  paintPlayhead(t);
}

function now() {
  const v = view();
  if (!v || segIndex < 0 || !v.segments.length) return 0;
  const seg = v.segments[segIndex];
  if (!seg || mediaClip !== seg.clip_id) return seg ? seg.timeline_start : 0;
  const into = Math.min(Math.max(media.currentTime - seg.start, 0), seg.duration);
  return seg.timeline_start + into;
}

function playing() {
  return media ? !media.paused : false;
}

function toggle() {
  if (!media) return;
  if (media.paused) {
    ensureVisualizer();
    media.play().catch((err) => ctx.emit("toast", err.message));
  } else {
    media.pause();
  }
}

function seekWord(word) {
  if (word && word.present) seek(word.timeline_start);
}

export const player = { seek, now, toggle, playing, seekWord };

function tick() {
  requestAnimationFrame(tick);
  const v = view();
  if (!v || !v.segments.length) return;

  if (!media.paused && segIndex >= 0) {
    const seg = v.segments[segIndex];
    // The seam: this segment's source material has run out, and the next
    // frame of the file is something the edit removed.
    if (seg && mediaClip === seg.clip_id && media.currentTime >= seg.end - SEAM_EPS) {
      if (segIndex + 1 < v.segments.length) {
        const next = v.segments[segIndex + 1];
        segIndex += 1;
        if (mediaClip !== next.clip_id) {
          setClip(next.clip_id);
          pendingSeek = next.start;
        } else {
          media.currentTime = next.start;
        }
      } else {
        media.pause();
      }
    }
  }
  const t = now();
  paintPlayhead(t);
  paintWord(t);
  drawVisualizer();
}

function paintPlayhead(t) {
  const v = view();
  $("clock").textContent = `${fmt(t)} / ${fmt(v ? v.timeline_duration : 0)}`;
  $("play").textContent = media.paused ? "▶" : "❚❚";
  ctx.emit("playhead", { now: t, total: (v && v.timeline_duration) || 1 });
}

function paintWord(t) {
  const v = view();
  if (!v || !v.words) return;
  const words = v.words;
  // Walk from where we left off; playback is monotonic except on a seek, and
  // a seek just costs one wrap.
  let found = -1;
  for (let n = 0; n < words.length; n++) {
    const i = (wordCursor + n) % words.length;
    const w = words[i];
    if (w.present && w.timeline_start <= t && t < w.timeline_end) {
      found = i;
      break;
    }
  }
  if (found === -1) return;
  wordCursor = found;
  const index = words[found].index;
  if (paintWord.last === index) return;
  paintWord.last = index;
  ctx.emit("playing-word", { index });
}

/* -- the audio-only level display ----------------------------------------
 * Never `display:none` the viewer (PLAN.md § Layout) — an audio-only clip
 * gets a level display driven by the actual playing audio instead. A
 * `MediaElementSourceNode` can only be created once per element, so it is
 * created lazily on first play and then survives every later `src` change,
 * because `setClip` only ever reassigns `media.src`, never replaces the
 * element.
 */
function ensureVisualizer() {
  if (audioCtx || !visualizer) return;
  try {
    const Ctx = window.AudioContext || window.webkitAudioContext;
    audioCtx = new Ctx();
    const source = audioCtx.createMediaElementSource(media);
    analyser = audioCtx.createAnalyser();
    analyser.fftSize = 256;
    source.connect(analyser);
    analyser.connect(audioCtx.destination);
  } catch {
    // Web Audio unsupported, or blocked until a user gesture that hasn't
    // happened yet — the transport still works either way, there is just no
    // level display drawn.
    audioCtx = null;
  }
}

function drawVisualizer() {
  if (!analyser || !vizCtx) return;
  if (!$("viewer").classList.contains("audio")) return;
  const data = new Uint8Array(analyser.frequencyBinCount);
  analyser.getByteFrequencyData(data);
  const w = visualizer.width;
  const h = visualizer.height;
  vizCtx.clearRect(0, 0, w, h);
  vizCtx.fillStyle = "#74a8e8";
  const barW = w / data.length;
  for (let i = 0; i < data.length; i++) {
    const barH = (data[i] / 255) * h;
    vizCtx.fillRect(i * barW, h - barH, Math.max(1, barW - 1), barH);
  }
}

export function update(state) {
  if (!state) return;
  $("viewer").classList.toggle("audio", !currentClip().has_video);
  if (!state.segments.length) return;
  const wanted = state.segments[0].clip_id;
  if (mediaClip === null) setClip(wanted);
}

export function init(passedCtx) {
  ctx = passedCtx;
  media = $("media");
  visualizer = $("visualizer");
  vizCtx = visualizer.getContext("2d");

  media.addEventListener("loadedmetadata", () => {
    if (pendingSeek !== null) {
      media.currentTime = pendingSeek;
      pendingSeek = null;
    }
  });

  media.addEventListener("error", () => {
    if (media.src) ctx.emit("toast", `Could not play ${mediaClip} — the browser refused this file.`);
  });

  $("play").addEventListener("click", () => toggle());

  window.addEventListener("keydown", (event) => {
    const tag = event.target.tagName;
    if (tag === "INPUT" || tag === "TEXTAREA") return;
    if (event.code === "Space") {
      event.preventDefault();
      toggle();
    }
  });

  requestAnimationFrame(tick);
}
