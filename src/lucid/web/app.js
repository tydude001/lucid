/* lucid's preview UI.
 *
 * The rule this file lives under: it draws and it plays, it never decides.
 * Mapping timeline time to source time client-side is unavoidable — that is
 * what playing an edit without rendering it *is* — but every question whose
 * answer is an edit ("what do these words resolve to", "what would this
 * remove", "roll that back") is a request to `ops`, and what comes back is
 * rendered as-is. There is no second implementation of a cut in here.
 */

const $ = (id) => document.getElementById(id);
const media = $("media");

let view = null; // the /api/view payload — the whole read model
let sel = null; // {first, last} inclusive word indices
let span = null; // {start, end} timeline seconds, from dragging a strip
let mediaClip = null; // which clip <video> currently has loaded
let segIndex = -1; // which timeline segment is playing
let pendingSeek = null; // a seek waiting on loadedmetadata
let wordCursor = 0; // cache for the playing-word scan
let playhead = null; // kept out of the DOM churn when the strip redraws

/* A seam is a seek, and a seek is not sample-accurate. Stop a segment this
 * far early rather than let the first frames of cut material through. */
const SEAM_EPS = 0.02;

/* -- formatting -------------------------------------------------------- */

function fmt(t) {
  if (t === null || t === undefined || Number.isNaN(t)) return "–";
  const sign = t < 0 ? "-" : "";
  t = Math.abs(t);
  const m = Math.floor(t / 60);
  const s = t - m * 60;
  return `${sign}${m}:${s.toFixed(1).padStart(4, "0")}`;
}

function secs(t) {
  return t === null || t === undefined ? "–" : `${t.toFixed(3)}s`;
}

function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
}

function toast(message) {
  const box = $("toast");
  box.textContent = message;
  box.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => {
    box.hidden = true;
  }, 9000);
}

/* -- talking to ops ---------------------------------------------------- */

async function api(path, body) {
  const opts = body
    ? {
        method: "POST",
        // Not decoration: `application/json` is what a cross-origin form
        // cannot send, and the server refuses anything else.
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      }
    : {};
  const response = await fetch(path, opts);
  const payload = await response.json().catch(() => ({ error: response.statusText }));
  if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
  return payload;
}

async function load(clipId) {
  const query = clipId ? `?clip_id=${encodeURIComponent(clipId)}` : "";
  // Read the playhead against the *old* edit before replacing it: a cut that
  // lands before the playhead moves everything after it, and holding the
  // timeline second would drift the view a little further with each edit.
  const at = view ? timelineNow() : 0;
  try {
    view = await api(`/api/view${query}`);
  } catch (err) {
    toast(err.message);
    return;
  }
  segIndex = -1;
  render(at);
}

/* -- rendering --------------------------------------------------------- */

function render(at = 0) {
  $("project").textContent = view.name;
  $("duration").textContent = fmt(view.timeline_duration);
  $("segcount").textContent = view.segments.length;
  $("cutcount").textContent = view.seams.length;
  $("depth").textContent = view.undo_depth ? `(${view.undo_depth})` : "";
  $("undo").disabled = view.undo_depth === 0;

  const picker = $("clip");
  picker.textContent = "";
  for (const clip of view.clips) {
    const option = el("option", null, clip.clip_id + (clip.has_transcript ? "" : " (no transcript)"));
    option.value = clip.clip_id;
    option.selected = clip.clip_id === view.clip_id;
    picker.append(option);
  }
  picker.hidden = view.clips.length < 2;

  $("viewer").classList.toggle("audio", !currentClip().has_video);

  renderStrips();
  renderTranscript();
  renderSelection();

  // Setting src restarts the element, so only do it on an actual change.
  const wanted = view.segments.length ? view.segments[0].clip_id : view.clip_id;
  if (mediaClip === null) setClip(wanted);
  seekTimeline(Math.min(at, Math.max(0, view.timeline_duration - 0.01)));
}

function currentClip() {
  return view.clips.find((c) => c.clip_id === view.clip_id) || {};
}

function playheadEl() {
  if (!playhead) {
    playhead = $("playhead") || el("div", "playhead");
    playhead.id = "playhead";
  }
  return playhead;
}

function renderStrips() {
  const strip = $("timeline");
  // Take the playhead out of the way first: clearing the strip would detach
  // it, and a detached node is no longer findable by id.
  const head = playheadEl();
  strip.textContent = "";
  strip.append(head);
  const total = view.timeline_duration || 1;

  for (const seg of view.segments) {
    const block = el("div", "seg");
    block.style.left = `${(seg.timeline_start / total) * 100}%`;
    block.style.width = `${(seg.duration / total) * 100}%`;
    block.title = `${seg.clip_id} ${secs(seg.start)}–${secs(seg.end)} → plays at ${fmt(seg.timeline_start)}`;
    strip.append(block);
  }
  for (const seam of view.seams) {
    const tick = el("div", "seam");
    tick.style.left = `${(seam.timeline_time / total) * 100}%`;
    tick.title = seamLabel(seam);
    strip.append(tick);
  }

  // The source strip is the same edit in the coordinates that never
  // renumber: full recording, with the removed stretches drawn as holes.
  const source = $("source");
  source.textContent = "";
  const length = view.source_duration || total;
  const mine = view.segments.filter((s) => s.clip_id === view.clip_id);
  let cursor = 0;
  const gap = (from, to) => {
    if (to - from <= 0.001) return;
    const hole = el("div", "gap");
    hole.style.left = `${(from / length) * 100}%`;
    hole.style.width = `${((to - from) / length) * 100}%`;
    hole.title = `removed — ${secs(to - from)} of source, ${secs(from)}–${secs(to)}`;
    source.append(hole);
  };
  for (const seg of mine) {
    gap(cursor, seg.start);
    const block = el("div", "seg");
    block.style.left = `${(seg.start / length) * 100}%`;
    block.style.width = `${(seg.duration / length) * 100}%`;
    block.title = `kept — source ${secs(seg.start)}–${secs(seg.end)}, plays at ${fmt(seg.timeline_start)}`;
    source.append(block);
    cursor = Math.max(cursor, seg.end);
  }
  gap(cursor, length);
}

function seamLabel(seam) {
  const words =
    seam.before && seam.after
      ? `\n…${seam.before.text} (#${seam.before.index})  ✂  (#${seam.after.index}) ${seam.after.text}…`
      : "";
  return `cut at ${fmt(seam.timeline_time)} — ${secs(seam.removed)} removed from source ${secs(
    seam.source_end,
  )}–${secs(seam.source_start)}${words}`;
}

function renderTranscript() {
  const pane = $("transcript");
  pane.textContent = "";
  if (!view.words) {
    pane.append(
      el(
        "p",
        "hint",
        `${view.clip_id} has no transcript, so there are no words to address. ` +
          `Run \`lucid transcribe ${view.clip_id}\` or attach a whisper JSON; ` +
          `the strips above still show the edit.`,
      ),
    );
    return;
  }
  const frag = document.createDocumentFragment();
  for (const word of view.words) {
    const node = el("span", "w", word.text);
    if (!word.present) node.classList.add("gone");
    if (word.partial) node.classList.add("partial");
    if (word.suspect) node.classList.add("suspect");
    node.dataset.i = word.index;
    node.title = wordLabel(word);
    frag.append(node, document.createTextNode(" "));
  }
  pane.append(frag);
  paintSelection();
}

function wordLabel(word) {
  const where = word.present
    ? `plays at ${fmt(word.timeline_start)}`
    : "cut — it is not in the timeline";
  const parts = [`#${word.index}  source ${secs(word.start)}–${secs(word.end)}`, where];
  if (word.partial)
    parts.push(`survives in part: ${secs(word.covered)} of ${secs(word.end - word.start)}`);
  if (word.suspect)
    parts.push(
      `suspect duration — claims ${secs(word.suspect.duration)}, over the ` +
        `${secs(word.suspect.limit)} limit; it may be hiding a retake`,
    );
  return parts.join("\n");
}

/* -- selection --------------------------------------------------------- */

function paintSelection() {
  for (const node of $("transcript").querySelectorAll(".w")) {
    const i = Number(node.dataset.i);
    node.classList.toggle("sel", sel !== null && i >= sel.first && i <= sel.last);
  }
}

function wordAt(index) {
  return view.words ? view.words[index] : null;
}

function renderSelection() {
  const box = $("selection");
  box.textContent = "";
  const controls = $("controls");

  if (span) {
    controls.hidden = false;
    box.classList.remove("empty");
    box.append(el("div", null, `Timeline span ${fmt(span.start)} – ${fmt(span.end)}`));
    box.append(
      el(
        "div",
        "hint",
        `${secs(span.end - span.start)} of what plays. Preview resolves it back ` +
          `to source through the edit — that is \`cut-at\`, the same op the CLI uses.`,
      ),
    );
    $("keep").hidden = true;
    return;
  }
  $("keep").hidden = false;

  if (!sel) {
    controls.hidden = true;
    box.className = "empty";
    box.textContent = view.words
      ? "Nothing selected. Click a word, or drag across the timeline strip."
      : "Nothing selected. This clip has no transcript; drag the timeline strip to cut by time.";
    return;
  }

  controls.hidden = false;
  box.classList.remove("empty");
  const first = wordAt(sel.first);
  const last = wordAt(sel.last);
  const count = sel.last - sel.first + 1;
  box.append(
    el("div", null, `Words ${sel.first}–${sel.last} · ${count} word${count === 1 ? "" : "s"}`),
  );

  // The neighbours either side are the whole point of the echo (CLAUDE.md):
  // a range one word past the intended phrase reads correctly on its own.
  const quote = el("div", "quote");
  const context = 3;
  for (let i = Math.max(0, sel.first - context); i <= Math.min(view.words.length - 1, sel.last + context); i++) {
    const inside = i >= sel.first && i <= sel.last;
    quote.append(el("span", inside ? "hit" : "ctx", view.words[i].text + " "));
  }
  box.append(quote);

  box.append(rows([["source", `${secs(first.start)} – ${secs(last.end)}`]]));
  const suspects = view.words.slice(sel.first, sel.last + 1).filter((w) => w.suspect);
  if (suspects.some((w) => w.index === sel.first || w.index === sel.last)) {
    box.append(
      el(
        "div",
        "warn",
        "A boundary word here claims a suspect duration — it may be hiding a " +
          "retake rather than ending where it says. Preview it; cutting needs " +
          "the checkbox below.",
      ),
    );
  }
}

function rows(pairs) {
  const table = el("table", "rows");
  for (const [key, value] of pairs) {
    const tr = el("tr");
    tr.append(el("td", null, key), el("td", null, value));
    table.append(tr);
  }
  return table;
}

/* -- playback ---------------------------------------------------------- */

function setClip(clipId) {
  if (mediaClip === clipId) return;
  mediaClip = clipId;
  media.src = `/api/media/${encodeURIComponent(clipId)}`;
}

function segAt(t) {
  const segments = view.segments;
  for (let i = 0; i < segments.length; i++) {
    if (t < segments[i].timeline_end - 1e-6) return i;
  }
  return segments.length - 1;
}

function seekTimeline(t) {
  if (!view || !view.segments.length) return;
  t = Math.max(0, Math.min(t, view.timeline_duration));
  segIndex = segAt(t);
  const seg = view.segments[segIndex];
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

function timelineNow() {
  if (!view || segIndex < 0 || !view.segments.length) return 0;
  const seg = view.segments[segIndex];
  if (!seg || mediaClip !== seg.clip_id) return seg ? seg.timeline_start : 0;
  const into = Math.min(Math.max(media.currentTime - seg.start, 0), seg.duration);
  return seg.timeline_start + into;
}

function tick() {
  requestAnimationFrame(tick);
  if (!view || !view.segments.length) return;

  if (!media.paused && segIndex >= 0) {
    const seg = view.segments[segIndex];
    // The seam: this segment's source material has run out, and the next
    // frame of the file is something the edit removed.
    if (seg && mediaClip === seg.clip_id && media.currentTime >= seg.end - SEAM_EPS) {
      if (segIndex + 1 < view.segments.length) {
        const next = view.segments[segIndex + 1];
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
  const now = timelineNow();
  paintPlayhead(now);
  paintPlayingWord(now);
}

function paintPlayhead(now) {
  const total = view.timeline_duration || 1;
  playheadEl().style.left = `${(now / total) * 100}%`;
  $("clock").textContent = `${fmt(now)} / ${fmt(view.timeline_duration)}`;
  $("play").textContent = media.paused ? "▶" : "❚❚";
}

function paintPlayingWord(now) {
  if (!view.words) return;
  const words = view.words;
  // Walk from where we left off; playback is monotonic except on a seek, and
  // a seek just costs one wrap.
  let found = -1;
  for (let n = 0; n < words.length; n++) {
    const i = (wordCursor + n) % words.length;
    const w = words[i];
    if (w.present && w.timeline_start <= now && now < w.timeline_end) {
      found = i;
      break;
    }
  }
  if (found === -1) return;
  wordCursor = found;
  const index = words[found].index;
  if (paintPlayingWord.last === index) return;
  const pane = $("transcript");
  if (paintPlayingWord.last !== undefined) {
    const old = pane.querySelector(`.w[data-i="${paintPlayingWord.last}"]`);
    if (old) old.classList.remove("playing");
  }
  const node = pane.querySelector(`.w[data-i="${index}"]`);
  if (node) node.classList.add("playing");
  paintPlayingWord.last = index;
}

/* -- actions ----------------------------------------------------------- */

function request(planned, mode) {
  if (span) {
    return {
      path: "/api/cut-at",
      body: {
        spans: [[span.start, span.end]],
        pad: Number($("pad").value) || 0,
        confirm_suspect: $("confirm").checked,
        plan: planned,
      },
    };
  }
  return {
    path: "/api/cut",
    body: {
      clip_id: view.clip_id,
      ranges: [[sel.first, sel.last]],
      mode,
      pad: Number($("pad").value) || 0,
      confirm_suspect: $("confirm").checked,
      plan: planned,
    },
  };
}

async function run(planned, mode) {
  if (!sel && !span) return;
  const { path, body } = request(planned, mode);
  let payload;
  try {
    payload = await api(path, body);
  } catch (err) {
    renderResult(null, err.message);
    toast(err.message);
    return;
  }
  renderResult(payload, null);
  if (!planned) {
    sel = null;
    span = null;
    await load(view.clip_id);
  }
}

function renderResult(payload, error) {
  const box = $("result");
  box.textContent = "";
  box.classList.remove("empty");

  if (error) {
    box.append(el("div", "warn bad", error));
    return;
  }

  const planned = Boolean(payload.plan);
  box.append(
    el(
      "div",
      null,
      planned
        ? `Preview — nothing was written.`
        : `Applied. \`Undo\` rolls it back.`,
    ),
  );
  box.append(
    rows([
      ["before", fmt(payload.duration_before)],
      ["after", fmt(payload.duration_after)],
      [planned ? "would remove" : "removed", secs(payload.removed)],
      ["segments", String(payload.segments)],
    ]),
  );

  for (const item of payload.applied || []) {
    // Word ranges echo their own text; a timeline span echoes the words it
    // turned out to overlap, one entry per surviving piece it landed in.
    if (item.pieces) {
      for (const piece of item.pieces) box.append(echo(piece, piece.words_overlapped));
    } else {
      box.append(echo(item, null));
    }
  }

  for (const flag of payload.suspect_boundaries || []) {
    box.append(
      el(
        "div",
        "warn",
        `Word ${flag.index} (${flag.text}) claims ${secs(flag.duration)}, over the ` +
          `${secs(flag.limit)} limit — it likely hides a retake. Applying this ` +
          `needs "allow a suspect boundary".`,
      ),
    );
  }

  const raw = el("details");
  raw.append(el("summary", "hint", "raw payload"));
  raw.append(el("pre", null, JSON.stringify(payload, null, 2)));
  box.append(raw);
}

function echo(item, overlapped) {
  const wrap = el("div");
  const quote = el("div", "quote");
  for (const w of item.context_before || []) quote.append(el("span", "ctx", w.text + " "));
  if (item.text !== undefined) {
    quote.append(el("span", "hit", item.text + " "));
  } else {
    for (const w of overlapped || []) quote.append(el("span", "hit", w.text + " "));
    if (!(overlapped || []).length) quote.append(el("span", "ctx", "(no words — silence) "));
  }
  for (const w of item.context_after || []) quote.append(el("span", "ctx", w.text + " "));
  wrap.append(quote);

  const detail = [["source", `${secs(item.source_start)} – ${secs(item.source_end)}`]];
  if (item.segments_touched !== undefined) detail.push(["segments touched", String(item.segments_touched)]);
  wrap.append(rows(detail));

  if (item.already_cut) {
    wrap.append(el("div", "warn", "This range was already gone — the edit does not change."));
  }
  if (item.pad_reach && item.pad_reach.length) {
    wrap.append(
      el(
        "div",
        "warn",
        "The padding also reaches: " +
          item.pad_reach.map((w) => `${w.text} (#${w.index}, ${w.side})`).join(", "),
      ),
    );
  }
  return wrap;
}

/* -- wiring ------------------------------------------------------------ */

let dragging = null;

$("transcript").addEventListener("mousedown", (event) => {
  const node = event.target.closest(".w");
  if (!node) return;
  event.preventDefault();
  const i = Number(node.dataset.i);
  span = null;
  if (event.shiftKey && sel) {
    sel = { first: Math.min(sel.first, i), last: Math.max(sel.last, i) };
  } else {
    dragging = { anchor: i, moved: false };
    sel = { first: i, last: i };
  }
  paintSelection();
  renderSelection();
});

$("transcript").addEventListener("mouseover", (event) => {
  if (!dragging) return;
  const node = event.target.closest(".w");
  if (!node) return;
  const i = Number(node.dataset.i);
  if (i !== dragging.anchor) dragging.moved = true;
  sel = { first: Math.min(dragging.anchor, i), last: Math.max(dragging.anchor, i) };
  paintSelection();
  renderSelection();
});

window.addEventListener("mouseup", () => {
  if (dragging && !dragging.moved) {
    // A plain click on one word is also "play from here" — the fastest way
    // to check whether a cut landed where it reads like it did.
    const word = wordAt(dragging.anchor);
    if (word && word.present) seekTimeline(word.timeline_start);
  }
  dragging = null;
});

function stripDrag(strip, toTime, total, onSpan, onClick) {
  let start = null;
  let latest = null;
  let box = null;
  strip.addEventListener("mousedown", (event) => {
    if (event.target.classList.contains("seam")) return;
    start = latest = toTime(event);
    box = el("div", "drag-box");
    strip.append(box);
  });
  strip.addEventListener("mousemove", (event) => {
    if (start === null) return;
    latest = toTime(event);
    const span = total();
    const lo = Math.min(start, latest);
    const hi = Math.max(start, latest);
    box.style.left = `${(lo / span) * 100}%`;
    box.style.width = `${((hi - lo) / span) * 100}%`;
  });
  window.addEventListener("mouseup", (event) => {
    if (start === null) return;
    // Releasing outside the strip is a real drag too — keep the last position
    // it tracked rather than collapsing the span to a click. `target` is only
    // a Node for a real release; guard it so a stray event cannot leave the
    // drag box on screen and the strip stuck mid-drag.
    const over = event.target instanceof Node && strip.contains(event.target);
    const end = over ? toTime(event) : latest;
    const lo = Math.min(start, end);
    const hi = Math.max(start, end);
    if (box) box.remove();
    box = null;
    start = null;
    if (hi - lo > 0.05) onSpan(lo, hi);
    else onClick(lo);
  });
}

const timeAt = (strip, total) => (event) => {
  const rect = strip.getBoundingClientRect();
  const ratio = Math.min(Math.max((event.clientX - rect.left) / rect.width, 0), 1);
  return ratio * total();
};

const timelineTotal = () => view.timeline_duration || 1;
const sourceTotal = () => view.source_duration || view.timeline_duration || 1;

stripDrag(
  $("timeline"),
  timeAt($("timeline"), timelineTotal),
  timelineTotal,
  (lo, hi) => {
    sel = null;
    span = { start: lo, end: hi };
    paintSelection();
    renderSelection();
  },
  (t) => seekTimeline(t),
);

// The source strip is addressed in source seconds, so a click there is
// "where does this instant play now" — the same question `locate` answers.
stripDrag(
  $("source"),
  timeAt($("source"), sourceTotal),
  sourceTotal,
  () => toast("Drag-to-cut works on the timeline strip; the source strip seeks only."),
  (t) => {
    const seg = view.segments.find(
      (s) => s.clip_id === view.clip_id && s.start <= t && t < s.end,
    );
    if (!seg) {
      toast(`Source ${secs(t)} is not in the timeline — the edit removed it.`);
      return;
    }
    seekTimeline(seg.timeline_start + (t - seg.start));
  },
);

media.addEventListener("loadedmetadata", () => {
  if (pendingSeek !== null) {
    media.currentTime = pendingSeek;
    pendingSeek = null;
  }
});

media.addEventListener("error", () => {
  if (media.src) toast(`Could not play ${mediaClip} — the browser refused this file.`);
});

$("play").addEventListener("click", () => {
  if (media.paused) media.play().catch((err) => toast(err.message));
  else media.pause();
});

$("clip").addEventListener("change", (event) => {
  sel = null;
  span = null;
  load(event.target.value);
});

$("reload").addEventListener("click", () => load(view && view.clip_id));

$("undo").addEventListener("click", async () => {
  try {
    const result = await api("/api/undo", {});
    toast(`Rolled back to ${fmt(result.timeline_duration)} · ${result.segments} segments.`);
  } catch (err) {
    toast(err.message);
    return;
  }
  sel = null;
  span = null;
  await load(view.clip_id);
});

$("plan").addEventListener("click", () => run(true, "cut"));
$("apply").addEventListener("click", () => run(false, "cut"));
$("keep").addEventListener("click", () => run(false, "keep"));
$("clear").addEventListener("click", () => {
  sel = null;
  span = null;
  paintSelection();
  renderSelection();
});

window.addEventListener("keydown", (event) => {
  if (event.target.tagName === "INPUT") return;
  if (event.code === "Space") {
    event.preventDefault();
    $("play").click();
  }
});

requestAnimationFrame(tick);
load(null);
