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
 * level display (PLAN.md § Layout — #viewer is never `display:none`), and the
 * picture layer, which shows the V2 shot under the playhead over whatever the
 * transport is playing. Both hang off the same tick; neither touches the seam
 * logic, which still owns `media` alone.
 *
 * Exports:
 *   init(ctx)      call once, after `$("media")` etc. exist. Wires the
 *                  <video>, the transport, the audio-only visualiser, and
 *                  starts the tick loop.
 *   update(state)  call with the current /api/view payload whenever it
 *                  changes. Toggles the audio-only state and loads the
 *                  timeline's own clip the first time a view arrives.
 *   captions(p)    call with the current /api/captions payload. A second
 *                  read model rather than a field on the view: it is derived
 *                  from the same edit but grouped and styled, and a front end
 *                  must never do either itself.
 *   player         the object placed on `ctx.player` for the other panes:
 *                    seek(t)       seek the timeline to `t` seconds
 *                    now()         the current timeline second
 *                    toggle()      play/pause
 *                    playing()     bool
 *                    seekWord(w)   seek to a word's timeline_start, if present
 *
 * player.js owns #viewer, #media, #visualizer, #picture (with #picture-video,
 * #picture-still, #picture-note), #caption-layer (with #caption-line),
 * #transport, #play, #clock, #playhint and touches no other pane's DOM. Every animation frame it emits
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

/* The picture layer's drift budget. The transport and the picture are two
 * media elements playing from two files, so they cannot be frame-locked —
 * `now()` is the only clock, and the picture is corrected back to it whenever
 * it wanders this far. Small enough that nobody sees the correction, large
 * enough that a decoder's ordinary jitter does not cause one every frame. */
const PICTURE_DRIFT = 0.15;
/* Paused is a different problem: nothing is jittering, so the picture is
 * seeked to the exact frame and only a real disagreement moves it. */
const PICTURE_EPS = 0.04;

let mediaClip = null; // which clip <video> currently has loaded
let segIndex = -1; // which timeline segment is playing
let pendingSeek = null; // a seek waiting on loadedmetadata
let wordCursor = 0; // cache for the playing-word scan

let picture = null; // the V2 layer, or null before init
let pictureVideo = null;
let pictureStill = null;
let pictureNote = null;
let pictureAsset = null; // which asset the picture layer currently holds
let pendingPictureSeek = null; // as pendingSeek, for the picture element
let shotCursor = 0; // cache for the shot-under-the-playhead scan
const pictureRefused = new Set(); // assets the browser would not decode

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
  paintPicture(t);
  paintCaption(t);
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

/* -- the picture layer: the shot under the playhead ----------------------
 *
 * What makes V2 a picture rather than a plan of one. timeline.js draws the
 * shots as blocks; this shows the one the playhead is inside.
 *
 * It reads `view().shots` and nothing else — the same array the lane draws,
 * which is `timeline_view`'s projection *already through `mlt.plan_picture`*
 * (CLAUDE.md). That is the whole reason this is honest: `src_start` is where
 * the MLT writer decided this shot reads from inside its asset, so a clip used
 * three times previews from three different places, exactly as it will render.
 * Reading `build_shots` here instead would preview a shot `export` refuses.
 *
 * The audio is never this element's. The transport owns playback and `now()`
 * is the only clock in the window; the picture is a follower muted at the
 * source, so a shot whose asset has a soundtrack cannot talk over the VO.
 */

function shotAt(t) {
  const shots = view().shots;
  if (!shots || !shots.length) return null;
  // Same wrap-around walk as paintWord, and for the same reason: playback is
  // monotonic except on a seek, and a seek costs one lap.
  for (let n = 0; n < shots.length; n++) {
    const i = (shotCursor + n) % shots.length;
    const shot = shots[i];
    if (shot.start <= t && t < shot.start + shot.duration) {
      shotCursor = i;
      return shot;
    }
  }
  return null;
}

function assetURL(asset) {
  return `/api/asset/${encodeURIComponent(asset)}`;
}

function showPictureNote(text) {
  pictureNote.textContent = text;
  pictureNote.hidden = !text;
}

/* A refused asset is diagnosed on the box rather than guessed at in here: the
 * `error` event carries nothing, so the reason comes from `/api/preview`,
 * which probed the actual file. Asked once per asset — a failure is a property
 * of the file, and re-asking every time the playhead re-enters the shot would
 * put one fetch per frame on a codec problem. */
function diagnose(asset) {
  if (pictureRefused.has(asset)) return;
  pictureRefused.add(asset);
  showPictureNote(`${asset} — the browser refused this file`);
  fetch(`/api/preview/${encodeURIComponent(asset)}`)
    .then((r) => (r.ok ? r.json() : null))
    .then((info) => {
      if (info && info.reason && pictureAsset === asset) showPictureNote(`${asset} — ${info.reason}`);
    })
    .catch(() => {});
}

function loadShot(shot) {
  pictureAsset = shot.asset;
  showPictureNote(pictureRefused.has(shot.asset) ? `${shot.asset} — the browser refused this file` : "");
  if (shot.is_image) {
    pictureVideo.hidden = true;
    pictureVideo.pause();
    pictureStill.hidden = false;
    pictureStill.src = assetURL(shot.asset);
  } else {
    pictureStill.hidden = true;
    pictureStill.removeAttribute("src");
    pictureVideo.hidden = false;
    pictureVideo.src = assetURL(shot.asset);
    pendingPictureSeek = shot.src_start;
  }
}

function paintPicture(t) {
  if (!picture) return;
  const shot = shotAt(t);
  if (!shot) {
    // No shot here is not a failure: the picture track has a hole, and what
    // shows through it is the edit's own track — which is what `export`
    // renders too. Hiding the layer *is* drawing that.
    if (picture.hidden) return;
    picture.hidden = true;
    pictureVideo.pause();
    pictureAsset = null;
    return;
  }
  picture.hidden = false;
  if (pictureAsset !== shot.asset) loadShot(shot);
  if (shot.is_image) return;

  const target = shot.src_start + Math.max(0, t - shot.start);
  if (pictureVideo.readyState === 0) {
    pendingPictureSeek = target;
    return;
  }
  if (media.paused) {
    if (!pictureVideo.paused) pictureVideo.pause();
    if (Math.abs(pictureVideo.currentTime - target) > PICTURE_EPS) pictureVideo.currentTime = target;
    return;
  }
  if (Math.abs(pictureVideo.currentTime - target) > PICTURE_DRIFT) pictureVideo.currentTime = target;
  if (pictureVideo.paused) pictureVideo.play().catch(() => {});
}

/* -- the caption layer: what the burn-in will put on the frame -----------
 *
 * Draws `/api/captions` — `ops.caption_view`, which is `add_captions` without
 * the file. That matters more here than anywhere else in this window: these
 * pixels are a claim about pixels ffmpeg will burn, so every visible property
 * arrives from the server already resolved (font, size, both colours, the
 * outline, the box, which corner, how far in) and nothing about the look is
 * decided in here or taken from lucid's own palette. Where the CSS token rule
 * elsewhere is about a canvas silently refusing `light-dark(…)`, the rule here
 * is stronger and different: a caption that borrowed the theme would be a
 * preview of the window instead of a preview of the render.
 *
 * Three things it gets exactly right, because getting them approximately
 * right would make it a decoration:
 *
 *  * the cue boundaries and word timings are the ones `to_ass` writes — same
 *    grouping, from the same stored style, off the one derivation in
 *    `ops._caption_cues`;
 *  * the karaoke highlight uses `highlight_start`, not the word's own start,
 *    because a `\k` duration covers the gap before its word
 *    (`Cue.karaoke_spans`) — and it *fills* rather than stepping, see
 *    `paintKaraoke`;
 *  * the layer is placed over the *video's content box*, not the viewer's —
 *    a letterboxed frame must not show its captions floating in the black
 *    bars, which is precisely where the burn-in cannot put them.
 *
 * What it only approximates, and cannot do better in a browser: libass's
 * outline and box rendering (drawn here as a text stroke and a background),
 * and font substitution — libass picks its own replacement for a missing
 * family, and so does the browser, but not necessarily the same one.
 */

const CAPTION_REFERENCE = 1080; // captions.REFERENCE_HEIGHT — sizes are quoted
// against this, whatever the footage is, so the overlay scales by the ratio

let captionLayer = null;
let captionLine = null;
let captionState = null; // the /api/captions payload, or null before it lands
let cueCursor = 0;
let shownCue = null;

/* The frame the captions burn into, in #viewer's own coordinates: the
 * project's caption canvas, `contain`-fitted into the viewer the same way
 * both media elements are.
 *
 * The canvas — `caption_view`'s `resolution`, which is the PlayRes `to_ass`
 * writes — and deliberately not whichever element currently has picture in
 * it. Measured off the DOM instead, this box changed size every time a shot
 * started or ended: the Scream assembly's picture track has holes, and the
 * captions are the same size across them because the render's canvas does not
 * move. It is also the only box available on an audio-only project, where
 * every element in here reports `videoWidth 0` and the captions are still the
 * thing being styled. */
function captionBox() {
  const viewer = $("viewer");
  const box = { left: 0, top: 0, width: viewer.clientWidth, height: viewer.clientHeight };
  const canvas = captionState && captionState.resolution;
  if (!canvas || !canvas[0] || !canvas[1] || !box.width || !box.height) return box;

  const scale = Math.min(box.width / canvas[0], box.height / canvas[1]);
  const drawnW = canvas[0] * scale;
  const drawnH = canvas[1] * scale;
  return {
    left: (box.width - drawnW) / 2,
    top: (box.height - drawnH) / 2,
    width: drawnW,
    height: drawnH,
  };
}

/* ASS alignment is the numpad; the server sends it back as a name. */
function placeLine(position) {
  const bottom = position.startsWith("bottom");
  const top = position.startsWith("top");
  captionLayer.style.alignItems = bottom ? "flex-end" : top ? "flex-start" : "center";
  const left = position.endsWith("left");
  const right = position.endsWith("right");
  captionLayer.style.justifyContent = left ? "flex-start" : right ? "flex-end" : "center";
  return { bottom, top };
}

function cueAt(t) {
  const cues = captionState && captionState.cues;
  if (!cues || !cues.length) return null;
  // The same wrap-around walk as shotAt and paintWord, for the same reason.
  for (let n = 0; n < cues.length; n++) {
    const i = (cueCursor + n) % cues.length;
    if (cues[i].start <= t && t < cues[i].end) {
      cueCursor = i;
      return cues[i];
    }
  }
  return null;
}

/* Rebuild the line's contents. Word spans only when karaoke is on — with it
 * off every word is the same colour forever, and a span per word would be
 * churn nobody can see. */
function buildLine(cue, look) {
  captionLine.textContent = "";
  if (!look.karaoke) {
    captionLine.textContent = cue.text;
    captionLine.style.color = look.text;
    return;
  }
  captionLine.style.color = look.text;
  cue.words.forEach((word, n) => {
    const span = document.createElement("span");
    span.className = "cw";
    span.textContent = n ? ` ${word.text}` : word.text;
    captionLine.append(span);
  });
}

/* A `\k` tag switches its word to PrimaryColour when its turn comes and the
 * word *stays* that colour for the rest of the line — karaoke is a fill that
 * sweeps left to right, not a single word lit at a time. So the test is
 * `highlight_start <= t`, with no upper bound.
 *
 * Measured, not assumed: burning this project's own `.ass` over a flat frame
 * and reading the pixels back put four words in the highlight colour at
 * t=4.70 where a one-word-at-a-time overlay had lit one (HISTORY.md § Caption
 * styling). A per-word-only highlight is a different construction — one
 * Dialogue event per word — and is not what `to_ass` writes today. */
function paintKaraoke(cue, look, t) {
  const spans = captionLine.children;
  for (let n = 0; n < spans.length && n < cue.words.length; n++) {
    spans[n].style.color = cue.words[n].highlight_start <= t ? look.highlight : look.text;
  }
}

function paintCaption(t) {
  if (!captionLayer) return;
  const cue = cueAt(t);
  if (!cue) {
    if (!captionLayer.hidden) {
      captionLayer.hidden = true;
      shownCue = null;
    }
    return;
  }

  const look = captionState.style.resolved;
  const frame = captionBox();
  const scale = frame.height / CAPTION_REFERENCE;

  captionLayer.hidden = false;
  captionLayer.style.left = `${frame.left}px`;
  captionLayer.style.top = `${frame.top}px`;
  captionLayer.style.width = `${frame.width}px`;
  captionLayer.style.height = `${frame.height}px`;

  const edge = placeLine(look.position);
  captionLine.style.fontFamily = `"${look.font}", sans-serif`;
  captionLine.style.fontSize = `${Math.max(1, look.size * scale)}px`;
  captionLine.style.fontWeight = look.bold ? "700" : "400";
  captionLine.style.paddingBottom = edge.bottom ? `${look.margin * scale}px` : "0";
  captionLine.style.paddingTop = edge.top ? `${look.margin * scale}px` : "0";

  if (look.box) {
    // BorderStyle 3 draws an opaque box, and libass paints it in the
    // *outline* colour — not the box/shadow colour, whose ASS name
    // (BackColour) suggests otherwise.
    captionLine.style.background = look.outline_colour;
    captionLine.style.webkitTextStroke = "";
    captionLine.style.boxDecorationBreak = "clone";
    captionLine.style.padding = `${0.12 * look.size * scale}px ${0.3 * look.size * scale}px`;
  } else {
    captionLine.style.background = "none";
    captionLine.style.webkitTextStroke = `${look.outline_width * scale}px ${look.outline_colour}`;
    captionLine.style.paintOrder = "stroke fill";
  }

  if (shownCue !== cue.start) {
    shownCue = cue.start;
    buildLine(cue, look);
  }
  if (look.karaoke) paintKaraoke(cue, look, t);
}

/* Called by app.js whenever /api/captions lands — on load, and again after
 * every 'project-changed', which now fires on a manifest write too so a
 * restyle from the agent panel reaches this without a reload
 * (webui.py `_revision`). */
export function captions(payload) {
  captionState = payload && payload.cues && payload.cues.length ? payload : null;
  cueCursor = 0;
  shownCue = null;
  if (captionLayer && !captionState) captionLayer.hidden = true;
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

/* The bar colour comes from CSS, so the palette keeps exactly one home
 * (app.css § TOKENS AND THEME). It is read off #visualizer's own computed
 * `color` and not from the `--viz-bar` custom property, which reads back as
 * unparsed `light-dark(…)` text that `fillStyle` silently refuses — see
 * app.css's header, and timeline.js's `canvasInk` for the same trap.
 *
 * Cached because this is called every animation frame, and invalidated by
 * theme.js's event rather than re-measured: that event covers both the toggle
 * and an OS preference change, which is every way the answer can move. */
let barColour = null;

function vizBarColour() {
  if (barColour === null) barColour = getComputedStyle(visualizer).color || "#74a8e8";
  return barColour;
}

function drawVisualizer() {
  if (!analyser || !vizCtx) return;
  if (!$("viewer").classList.contains("audio")) return;
  // The picture layer is opaque and covers this; drawing under it is work
  // nobody can see.
  if (picture && !picture.hidden) return;
  const data = new Uint8Array(analyser.frequencyBinCount);
  analyser.getByteFrequencyData(data);
  const w = visualizer.width;
  const h = visualizer.height;
  vizCtx.clearRect(0, 0, w, h);
  vizCtx.fillStyle = vizBarColour();
  const barW = w / data.length;
  for (let i = 0; i < data.length; i++) {
    const barH = (data[i] / 255) * h;
    vizCtx.fillRect(i * barW, h - barH, Math.max(1, barW - 1), barH);
  }
}

export function update(state) {
  if (!state) return;
  $("viewer").classList.toggle("audio", !currentClip().has_video);
  // A cue changed, or the plan started refusing: drop what the layer holds so
  // the next frame reloads against the new projection rather than keeping a
  // shot that no longer exists on screen.
  shotCursor = 0;
  pictureAsset = null;
  if (picture && !state.shots) picture.hidden = true;
  if (!state.segments.length) return;
  const wanted = state.segments[0].clip_id;
  if (mediaClip === null) setClip(wanted);
}

export function init(passedCtx) {
  ctx = passedCtx;
  media = $("media");
  visualizer = $("visualizer");
  vizCtx = visualizer.getContext("2d");
  picture = $("picture");
  pictureVideo = $("picture-video");
  pictureStill = $("picture-still");
  pictureNote = $("picture-note");
  captionLayer = $("caption-layer");
  captionLine = $("caption-line");

  media.addEventListener("loadedmetadata", () => {
    if (pendingSeek !== null) {
      media.currentTime = pendingSeek;
      pendingSeek = null;
    }
  });

  pictureVideo.addEventListener("loadedmetadata", () => {
    if (pendingPictureSeek !== null) {
      pictureVideo.currentTime = pendingPictureSeek;
      pendingPictureSeek = null;
    }
  });

  pictureVideo.addEventListener("error", () => {
    if (pictureVideo.src && pictureAsset) diagnose(pictureAsset);
  });

  pictureStill.addEventListener("error", () => {
    if (pictureStill.src && pictureAsset) diagnose(pictureAsset);
  });

  media.addEventListener("error", () => {
    if (media.src) ctx.emit("toast", `Could not play ${mediaClip} — the browser refused this file.`);
  });

  $("play").addEventListener("click", () => toggle());

  // Drop the cached bar colour; the next frame re-reads it in the new theme.
  window.addEventListener("lucid:theme", () => {
    barColour = null;
  });

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
