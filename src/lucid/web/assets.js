/**
 * assets.js — the assets pane: every asset a cue can point at, straight off
 * `GET /api/assets` (`ops.assets`), which is already the whole inspector's
 * worth of data (media probe fields, transcript/described flags, cue-usage
 * counts, card records) — this file draws it and does nothing else.
 *
 * Follows the pane-module interface documented in transcript.js's header
 * comment: `init(ctx)` once, `update(state)` on every view change. `state`
 * (the `/api/view` payload) is used only to know which clip is the one
 * currently loaded in the transcript/timeline/preview — everything this
 * pane actually draws comes from its own `/api/assets` fetch, re-issued
 * every time `update` fires (the initial load, a reload after
 * 'project-changed', and after this pane's own role-toggle mutation), the
 * same "state changed, redraw" contract every other pane follows even
 * though the data itself lives outside `state`.
 *
 * CLAUDE.md's rule applies here like everywhere else in this file set: this
 * pane draws, it never decides. The one mutation it makes — `POST
 * /api/clip-role` — is `ops.clip_role`, the fourth caller alongside the CLI
 * and MCP tool (webui.py's own doc comment on the route says as much), and
 * its result is rendered by re-fetching `/api/assets`, never computed here.
 *
 * Clicking a row does not select a clip for the transcript/timeline/preview
 * — that is the top bar's `#clip` picker, a different piece of state
 * (`view.clip_id`) this pane does not own or touch. A click here only asks
 * properties.js to inspect that asset, over the `inspect-asset` bus event —
 * the two panes are wired through `ctx`, never importing each other
 * (PLAN.md § Files, and why they split).
 */

import { $, el, secs } from "./dom.js";

let ctx = null;
let lastView = null;
let data = null; // the last successful /api/assets payload, or null
let inspected = null; // {kind: "clip", clipId} | {kind: "card", name} | null
// — mirrors properties.js's own `inspected`, kept in sync one-way (a click
// here sets both; a click over there — none exists yet — would not update
// this). Used only to draw the `.inspected` highlight.
let refreshSeq = 0; // guards against an in-flight /api/assets fetch from an
// earlier `refresh()` landing after a later one and overwriting fresh data
// with stale — properties.js's `requestSeq` is the same guard for the same
// reason (its own header comment). Two triggers race here without it: a
// role-toggle click's own post-mutation refresh, and the SSE `project-changed`
// poll's reload (app.js's `load()` -> `assets.update()`) firing around the
// same manifest write. Demonstrated live: a role toggle wrote the manifest
// correctly but the DOM reverted to "off" because an older, slower-resolving
// fetch (issued before the click) rendered after the click's own fresher one.

//: ops.CLIP_ROLES, echoed rather than imported — there is no shared module
//: between the Python ops layer and this file, and the set is small and
//: stable (DAYDREAM.md § Import roles + assets pane: "voiceover" vs
//: "footage"). A role this pane does not recognise cannot reach here in the
//: first place — `clip_role` refuses anything outside the tuple before it
//: ever writes.
const CLIP_ROLES = ["voiceover", "footage"];

function fmtHz(n) {
  return n ? `${n.toLocaleString()} Hz` : "–";
}

function flag(label, ok, title) {
  const cls = ok === null || ok === undefined ? "" : ok ? " ok" : " fail";
  const node = el("span", `asset-flag${cls}`, label);
  if (title) node.title = title;
  return node;
}

/** `media.playability`'s verdict, or `null` when the file was not even
 * reachable to probe (a different claim than "unplayable" — ops.assets'
 * own docstring). Both are worth telling apart at a glance rather than
 * collapsing into one grey flag. */
function playableFlag(clip) {
  if (!clip.media_exists) return flag("missing", false, `not on disk: ${clip.media_path}`);
  if (clip.playable === null || clip.playable === undefined) return flag("unchecked", null);
  const p = clip.playable;
  return flag(p.playable ? "playable" : "unplayable", p.playable, p.reason || "");
}

function roleChips(clip) {
  const row = el("div", "asset-roles");
  for (const role of CLIP_ROLES) {
    const btn = el("button", `toggle${clip.role === role ? " on" : ""}`, role);
    btn.type = "button";
    btn.title =
      clip.role === role
        ? `clear ${clip.clip_id}'s role (back to undeclared)`
        : `set ${clip.clip_id}'s import role to ${role}`;
    btn.addEventListener("click", (event) => {
      event.stopPropagation(); // do not also trigger the row's own inspect click
      setRole(clip.clip_id, clip.role === role ? null : role);
    });
    row.append(btn);
  }
  return row;
}

async function setRole(clipId, role) {
  if (!ctx) return;
  let payload = null;
  let error = null;
  try {
    payload = await ctx.api(
      "/api/clip-role",
      role === null ? { clip_id: clipId, reset: true } : { clip_id: clipId, role },
    );
  } catch (err) {
    error = err.message;
    ctx.emit("toast", error);
  }
  ctx.emit("op-result", { payload, error });
  if (!error) await refresh();
}

function inspect(next) {
  inspected = next;
  ctx.emit("inspect-asset", next);
  render();
}

function buildClipRow(clip) {
  const row = el("div", "asset-row");
  row.dataset.clipId = clip.clip_id; // a stable hook — .asset-id's own text
  // grows a " · loaded" suffix on the active clip, below, so it is not one
  if (inspected && inspected.kind === "clip" && inspected.clipId === clip.clip_id) {
    row.classList.add("inspected");
  }
  row.addEventListener("click", () => inspect({ kind: "clip", clipId: clip.clip_id }));

  const id = el("div", "asset-id", clip.clip_id);
  if (lastView && lastView.clip_id === clip.clip_id) {
    id.append(el("span", "hint", "  · loaded"));
  }
  row.append(id);

  const dims = clip.width && clip.height ? `${clip.width}×${clip.height}` : null;
  const meta = [
    secs(clip.duration),
    dims,
    clip.fps ? `${Number(clip.fps).toFixed(2)}fps` : null,
    clip.video_codec,
    clip.has_audio ? `${clip.channels || "?"}ch @ ${fmtHz(clip.sample_rate)}` : null,
  ]
    .filter(Boolean)
    .join(" · ");
  row.append(el("div", "asset-meta", meta || "no probe metadata"));

  const flags = el("div", "asset-flags");
  flags.append(flag(clip.has_video ? "video" : "no video", !!clip.has_video));
  flags.append(flag(clip.has_audio ? "audio" : "no audio", !!clip.has_audio));
  flags.append(flag("transcript", clip.transcript, clip.transcript ? "transcribed" : "not transcribed"));
  flags.append(flag("described", clip.described, clip.described ? "indexed by describe" : "not indexed"));
  flags.append(flag(`${clip.cues} cue${clip.cues === 1 ? "" : "s"}`, clip.cues > 0 ? true : null));
  flags.append(playableFlag(clip));
  row.append(flags);

  row.append(roleChips(clip));
  return row;
}

function buildCardRow(card) {
  const row = el("div", "asset-row");
  row.dataset.cardName = card.name;
  if (inspected && inspected.kind === "card" && inspected.name === card.name) {
    row.classList.add("inspected");
  }
  row.addEventListener("click", () => inspect({ kind: "card", name: card.name }));

  row.append(el("div", "asset-id", card.asset));
  const meta = [
    card.template ? `template ${card.template}` : "no template record",
    card.canvas,
    card.variant ? `variant ${card.variant}` : null,
  ]
    .filter(Boolean)
    .join(" · ");
  row.append(el("div", "asset-meta", meta));

  const flags = el("div", "asset-flags");
  flags.append(flag("recorded", card.recorded, card.recorded ? "card_new/card_reauthor wrote this" : "no record — cannot be re-authored"));
  flags.append(flag(card.files_exist ? "files on disk" : "missing files", card.files_exist));
  flags.append(flag(`${card.cues} cue${card.cues === 1 ? "" : "s"}`, card.cues > 0 ? true : null));
  row.append(flags);

  return row;
}

function render() {
  const list = $("assets-list");
  if (!list) return;
  list.textContent = "";

  if (!data) {
    list.append(el("div", "pane-placeholder", "loading…"));
    return;
  }

  list.append(el("div", "asset-section-label", `clips · ${data.clips.length}`));
  if (!data.clips.length) list.append(el("div", "pane-placeholder", "no clips imported"));
  for (const clip of data.clips) list.append(buildClipRow(clip));

  list.append(el("div", "asset-section-label", `cards · ${data.cards.length}`));
  if (!data.cards.length) list.append(el("div", "pane-placeholder", "no cards yet"));
  for (const card of data.cards) list.append(buildCardRow(card));
}

async function refresh() {
  if (!ctx) return;
  const seq = ++refreshSeq;
  let next;
  try {
    next = await ctx.api("/api/assets");
  } catch (err) {
    // A project with a broken manifest is the only realistic way this
    // fails, and `/api/view` already surfaced that on load — no second
    // toast for the same fact, just an empty pane rather than a stale one.
    next = null;
  }
  if (seq !== refreshSeq) return; // superseded by a later refresh
  data = next;
  render();
}

export function init(passedCtx) {
  ctx = passedCtx;
}

export function update(state) {
  lastView = state;
  refresh();
}
