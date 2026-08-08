/**
 * agent.js — the agent panel plus the in-window render UI:
 * PLAN.md § "The agent panel, in
 * mechanism" and § "Finishing — the render happens in the window".
 *
 * See transcript.js's header comment for the full pane-module interface —
 * `ctx` shape, bus event names, and the `state` shape — this file does not
 * repeat it.
 *
 * What this file draws, and nothing more (CLAUDE.md: the web UI draws and it
 * plays, it never decides):
 *
 *   - a composer that POSTs {prompt} to /api/agent, and a Stop control that
 *     POSTs to /api/agent/stop (PLAN.md § The agent panel, in mechanism);
 *   - the `agent` SSE stream (stream-json passthrough) turned into a
 *     Daydream-style tool-progress list — consecutive tool_use blocks chain
 *     into one running checklist ("Reading transcript" → "Editing
 *     transcript" → "Done!"), assistant prose renders as its own entry and
 *     breaks the chain, and a shape this pane does not recognise degrades to
 *     a compact raw entry rather than throwing;
 *   - ONE feed for everything that happened to the edit (PLAN.md § Where the
 *     cut controls go): `op-result` — a person's own cut/keep/undo — renders
 *     as a system entry alongside the agent's own turns, in arrival order;
 *   - the render job: it does not initiate a render (the top bar's Export
 *     button already POSTs /api/render itself — see the note at the bottom
 *     of this file) but it owns everything after that — a Stop control for
 *     the running job, and a completion card reporting what the file
 *     actually is (dimensions, duration) plus the four verification checks,
 *     because success here is what ffprobe said, not that the job finished
 *     (PLAN.md § Finishing).
 *
 * Every DOM node this pane needs beyond what index.html already provides
 * (#agent-feed, #agent-composer, #agent-prompt, #agent-send, #agent-stop) is
 * built here at runtime — the progress list, the completion card, the
 * per-job Stop button — using only the classes app.css already documents for
 * this pane (.agent-progress, .agent-progress-step, .completion-card,
 * .check-row, .check-badge, .rows) rather than inventing new ones this file
 * cannot style.
 */

import { $, el, fmt } from "./dom.js";

let ctx = null;
let busy = false;

// -- feed plumbing ---------------------------------------------------------

function feedEl() {
  return $("agent-feed");
}

function scrollToBottom() {
  const feed = feedEl();
  feed.scrollTop = feed.scrollHeight;
}

function entry(cls, text) {
  const node = el("div", `agent-entry ${cls}`);
  node.append(el("div", null, text));
  return node;
}

/** Append a fully-built node and keep the feed scrolled to it. */
function append(node) {
  feedEl().append(node);
  scrollToBottom();
}

function setBusy(next) {
  busy = next;
  $("agent-send").disabled = busy;
  $("agent-stop").hidden = !busy;
}

// -- tool-name humanising ----------------------------------------------------

// Every name below is one of server.py's @mcp.tool() functions, which is
// also the whole set an agent turn can ever call — the allowlist is
// `mcp__lucid__*` and nothing else (PLAN.md § The agent panel, and why it
// does not become a fourth implementation).
const TOOL_LABELS = {
  ping: "Checking connection",
  init: "Initializing project",
  import_media: "Importing media",
  attach_transcript: "Attaching transcript",
  transcribe: "Transcribing",
  get_transcript: "Reading transcript",
  seed_timeline: "Seeding timeline",
  cut_by_transcript: "Editing transcript",
  cut_by_time: "Cutting",
  locate: "Locating words",
  timeline_status: "Checking timeline",
  timeline_view: "Reading timeline",
  undo: "Undoing",
  export: "Rendering",
  add_captions: "Adding captions",
  verify: "Verifying render",
  check_frames: "Checking frames",
  check_black: "Checking for black frames",
  spot_frames: "Sampling frames",
  speech_overlap: "Checking speech overlap",
  attenuate_noises: "Attenuating noise",
};

const MCP_PREFIX = /^mcp__[^_]+__/;

/** A tool_use block's `name` → a short present-participle label. Never
 * throws — a name this pane does not recognise (a future tool, or a name
 * shape that changed) still gets a readable fallback rather than sitting
 * raw in the checklist. */
function humanizeTool(name) {
  if (!name) return "Working";
  const bare = String(name).replace(MCP_PREFIX, "");
  if (TOOL_LABELS[bare]) return TOOL_LABELS[bare];
  const words = bare.replace(/_/g, " ").trim();
  return words ? words[0].toUpperCase() + words.slice(1) : String(name);
}

/** Best-effort short text out of a tool_result block's `content`, for a
 * hover title — never the primary UI, just a debugging aid. */
function resultPreview(block) {
  const content = block?.content;
  if (typeof content === "string") return content;
  if (Array.isArray(content)) {
    return content
      .map((b) => (b && b.type === "text" ? b.text : JSON.stringify(b)))
      .join(" ");
  }
  if (content && typeof content === "object") return JSON.stringify(content);
  return "";
}

// -- the tool-progress checklist --------------------------------------------
//
// One `.agent-progress` list per run of consecutive tool_use blocks.
// Assistant prose closes the current list (a person reads "Reading
// transcript ✓" then a sentence, not a sentence stitched mid-checklist) and
// the turn's `result` event, if a list is open, appends a final "Done!" step
// — this is the "Reading transcript → Editing transcript → Done!" shape
// PLAN.md names, drawn as a vertical checklist per the CSS app.css already
// ships for it rather than an inline arrow chain.

let currentProgress = null; // the open .agent-progress list, or null
const pendingSteps = new Map(); // tool_use id -> {step, label}

function openProgress() {
  const wrap = el("div", "agent-entry agent-entry--tool");
  const list = el("div", "agent-progress");
  wrap.append(list);
  append(wrap);
  return list;
}

function addStep(block) {
  const label = humanizeTool(block?.name);
  const step = el("div", "agent-progress-step active", `○ ${label}`);
  if (block?.input) {
    try {
      step.title = JSON.stringify(block.input);
    } catch {
      // Non-serialisable input (a circular structure, in principle) — the
      // checklist still works without a tooltip.
    }
  }
  if (!currentProgress) currentProgress = openProgress();
  currentProgress.append(step);
  if (block?.id) pendingSteps.set(block.id, { step, label });
}

function finishStep(toolUseId, ok, preview) {
  const pending = pendingSteps.get(toolUseId);
  if (!pending) return; // a result for a step outside this page's memory — drop it, not a crash
  pending.step.className = "agent-progress-step done";
  pending.step.textContent = `${ok ? "✓" : "✗"} ${pending.label}`;
  if (preview) pending.step.title = preview.slice(0, 400);
  pendingSteps.delete(toolUseId);
}

function closeProgress(final) {
  if (currentProgress && final) {
    currentProgress.append(el("div", "agent-progress-step done", `✓ ${final}`));
  }
  currentProgress = null;
}

// -- parsing one `agent` stream-json record ----------------------------------

function handleAssistantOrUser(data) {
  const role = data.type; // "assistant" | "user"
  const content = data.message?.content;
  const blocks = Array.isArray(content)
    ? content
    : typeof content === "string"
      ? [{ type: "text", text: content }]
      : [];

  for (const block of blocks) {
    if (!block || typeof block !== "object") continue;
    if (role === "assistant" && block.type === "text") {
      if (block.text && block.text.trim()) {
        closeProgress(null); // prose breaks the checklist without a synthetic "done"
        append(entry("agent-entry--agent", block.text));
      }
    } else if (role === "assistant" && block.type === "tool_use") {
      addStep(block);
    } else if (role === "user" && block.type === "tool_result") {
      // Tool results arrive as a "user" role message in stream-json — this
      // is the harness handing the tool's own output back, not a person
      // typing; it is never re-shown as a prompt (the composer already
      // echoed what the person actually sent).
      finishStep(block.tool_use_id, !block.is_error, resultPreview(block));
    }
    // Any other block type (image, thinking, …) is silently skipped rather
    // than dumped raw — it is not part of the progress story this pane
    // draws, and skipping beats guessing at a shape this pane doesn't know.
  }
}

function handleResult(data) {
  closeProgress("Done!");
  if (data.subtype && data.subtype !== "success") {
    const detail = typeof data.result === "string" ? data.result : JSON.stringify(data.result ?? {});
    append(entry("agent-entry--system bad", `Agent turn ended — ${data.subtype}${detail ? `: ${detail}` : ""}`));
  }
  setBusy(false);
}

function handleAgentEvent(data) {
  if (!data || typeof data !== "object") return;
  switch (data.type) {
    case "assistant":
    case "user":
      handleAssistantOrUser(data);
      return;
    case "result":
      handleResult(data);
      return;
    case "system":
      // Session/init bookkeeping from the harness — not part of the
      // Daydream-style progress story, and noisy every turn if shown.
      return;
    default: {
      // An event shape this pane does not recognise — degrade to a compact
      // raw entry rather than crash or stay silent (this file's contract).
      let raw;
      try {
        raw = JSON.stringify(data);
      } catch {
        raw = String(data);
      }
      append(entry("agent-entry--tool", raw.length > 300 ? raw.slice(0, 300) + "…" : raw));
    }
  }
}

// -- the render job ----------------------------------------------------------
//
// The top bar's Export button already POSTs /api/render itself and toasts
// the accepted job_id (app.js — the shell owns the top bar). This pane does
// not duplicate that POST; it owns everything the render SSE stream reports
// afterwards, keyed by job_id so a running/cancelled/error/done sequence for
// one job updates a single feed entry in place rather than spamming four.

const CHECK_ORDER = ["verify", "check_frames", "check_black", "spot_frames"];
const CHECK_LABELS = {
  verify: "Audio verify",
  check_frames: "Frame count",
  check_black: "Black frames",
  spot_frames: "Spot frames",
};

const renderSlots = new Map(); // job_id -> the .agent-entry wrapper for that job

function slotFor(jobId) {
  if (jobId && renderSlots.has(jobId)) return renderSlots.get(jobId);
  const wrap = el("div", "agent-entry agent-entry--tool");
  append(wrap);
  if (jobId) renderSlots.set(jobId, wrap);
  return wrap;
}

function stopRenderButton() {
  const btn = el("button", null, "Stop render");
  btn.type = "button";
  btn.addEventListener("click", async () => {
    btn.disabled = true;
    try {
      await ctx.api("/api/render/stop", {});
    } catch (err) {
      ctx.emit("toast", err.message);
      btn.disabled = false;
    }
  });
  return btn;
}

/** One check's badge class — "skip" when the server itself skipped it;
 * otherwise a small per-check heuristic over the fields that check's own ops
 * function actually returns. Never assumes a field is present. */
function badgeClass(name, result) {
  if (!result || result.skipped) return "skip";
  switch (name) {
    case "verify":
      return (result.repeated?.length || result.dropped?.length) > 0 ? "warn" : "ok";
    case "check_frames":
      return result.agrees === true ? "ok" : result.agrees === false ? "fail" : "skip";
    case "check_black":
      return result.clean === true ? "ok" : result.clean === false ? "warn" : "skip";
    case "spot_frames": {
      const errors = (result.frames || []).filter((f) => f && f.error).length;
      return errors > 0 ? "warn" : "ok";
    }
    default:
      return "skip";
  }
}

/** A one-line summary under each check's badge — the specific fields when
 * this pane knows the check, a generic dump when it does not. */
function checkSummary(name, result) {
  if (!result) return "no result";
  if (result.skipped) return `skipped — ${result.reason || "no reason given"}`;
  switch (name) {
    case "verify": {
      const repeated = result.repeated?.length ?? 0;
      const dropped = result.dropped?.length ?? 0;
      return `similarity ${result.similarity ?? "–"} · ${repeated} repeated run${repeated === 1 ? "" : "s"} · ${dropped} dropped run${dropped === 1 ? "" : "s"}`;
    }
    case "check_frames":
      return `expected ${result.expected_frames ?? "–"} frames · target ${result.target_frames ?? "–"} · delta ${result.delta ?? "–"}`;
    case "check_black": {
      const runs = result.runs?.length ?? 0;
      return `${runs} black run${runs === 1 ? "" : "s"}${result.clean === false ? " — unexplained" : ""}`;
    }
    case "spot_frames": {
      const frames = result.frames?.length ?? 0;
      return `${frames} frame${frames === 1 ? "" : "s"} sampled${result.mapping_trusted === false ? " · mapping not trusted" : ""}`;
    }
    default: {
      const dump = JSON.stringify(result);
      return dump.length > 200 ? dump.slice(0, 200) + "…" : dump;
    }
  }
}

function buildCompletionCard(data) {
  const card = el("div", "completion-card");
  card.append(el("div", null, "Export complete"));

  const rows = el("table", "rows");
  const row = (label, value) => {
    const tr = document.createElement("tr");
    tr.append(el("td", null, label), el("td", null, value));
    rows.append(tr);
  };
  row("output", (data.output || "").split("/").pop() || "–");
  row("dimensions", data.width && data.height ? `${data.width}×${data.height}` : "audio only");
  row("duration", fmt(data.duration));
  row("video / audio", `${data.has_video ? "yes" : "no"} / ${data.has_audio ? "yes" : "no"}`);
  card.append(rows);

  const checks = data.checks || {};
  for (const name of CHECK_ORDER) {
    const result = checks[name];
    const checkRow = el("div", "check-row");
    checkRow.append(el("span", null, CHECK_LABELS[name]));
    checkRow.append(el("span", `check-badge ${badgeClass(name, result)}`, badgeClass(name, result)));
    card.append(checkRow);
    const summary = el("div", null, checkSummary(name, result));
    summary.style.fontSize = "11px";
    summary.style.opacity = "0.75";
    summary.style.margin = "-4px 0 4px";
    card.append(summary);
  }
  return card;
}

function handleRenderEvent(data) {
  if (!data || typeof data !== "object") return;
  const wrap = slotFor(data.job_id);
  wrap.textContent = "";
  switch (data.status) {
    case "running": {
      const label = el(
        "span",
        null,
        `Rendering${data.preset ? ` · preset ${data.preset}` : ""}…`,
      );
      wrap.append(label, stopRenderButton());
      break;
    }
    case "cancelled":
      wrap.append(el("div", null, "Render cancelled — the partial output was deleted."));
      break;
    case "error":
      wrap.append(el("div", "warn bad", `Render failed — ${data.error || "unknown error"}`));
      break;
    case "done":
      wrap.append(buildCompletionCard(data));
      break;
    default: {
      let raw;
      try {
        raw = JSON.stringify(data);
      } catch {
        raw = String(data);
      }
      wrap.append(el("div", null, raw));
    }
  }
  scrollToBottom();
}

// -- op-result: one feed for everything that happened to the edit -----------

/** A short human line for a mutating op's own JSON reply. `ops` functions
 * return different shapes per op (undo has no `removed`; cut/keep do) — this
 * recognises the shapes this pane knows and still renders anything else
 * rather than staying silent, per PLAN.md's "one feed for everything that
 * happened to the edit". */
function describeOp(payload) {
  if (payload && typeof payload.restored_from === "string") {
    return (
      `Undo — restored ${payload.segments ?? "?"} segment(s), ` +
      `${fmt(payload.timeline_duration)} timeline. Undo depth ${payload.undo_depth ?? "?"}.`
    );
  }
  if (payload && typeof payload.removed === "number") {
    const removed = payload.removed.toFixed(2);
    let line = payload.plan
      ? `Preview — nothing was written. Would remove ${removed}s.`
      : `Applied — removed ${removed}s. Undo rolls it back.`;
    const suspects = payload.suspect_boundaries?.length;
    if (suspects) line += ` ${suspects} suspect boundary${suspects === 1 ? "" : "ies"} flagged.`;
    return line;
  }
  if (!payload) return "Applied.";
  const bits = Object.entries(payload)
    .slice(0, 4)
    .map(([k, v]) => `${k}: ${typeof v === "object" ? JSON.stringify(v) : v}`);
  return `Applied — ${bits.join(" · ")}`;
}

// -- wiring -------------------------------------------------------------

export function init(passedCtx) {
  ctx = passedCtx;
  append(
    el(
      "p",
      "pane-placeholder",
      "Ask the agent to edit this project. It reaches the timeline only " +
        "through lucid's own MCP tools, and nothing else (PLAN.md § The " +
        "agent panel, and why it does not become a fourth implementation).",
    ),
  );

  const composer = $("agent-composer");
  const promptBox = $("agent-prompt");

  composer.addEventListener("submit", async (event) => {
    event.preventDefault();
    const prompt = promptBox.value.trim();
    if (!prompt || busy) return;
    append(entry("agent-entry--user", prompt));
    promptBox.value = "";
    closeProgress(null); // a fresh prompt starts a fresh checklist, not a continuation
    setBusy(true);
    try {
      await ctx.api("/api/agent", { prompt });
    } catch (err) {
      append(entry("agent-entry--system bad", err.message));
      setBusy(false);
    }
  });

  // Enter sends (matches every chat composer this panel is imitating);
  // shift-Enter still inserts a newline for a multi-line prompt.
  promptBox.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      composer.requestSubmit();
    }
  });

  $("agent-stop").addEventListener("click", async () => {
    try {
      await ctx.api("/api/agent/stop", {});
    } catch (err) {
      ctx.emit("toast", err.message);
    }
    setBusy(false);
  });

  ctx.on("agent", (data) => {
    try {
      handleAgentEvent(data);
    } catch (err) {
      // This pane's own contract: an event shape it fails to parse still
      // shows up rather than crashing the panel or vanishing silently.
      append(entry("agent-entry--tool", `agent event (unparsed) — ${err.message}`));
    }
  });

  ctx.on("render", (data) => {
    try {
      handleRenderEvent(data);
    } catch (err) {
      append(entry("agent-entry--tool", `render event (unparsed) — ${err.message}`));
    }
  });

  ctx.on("op-result", ({ payload, error }) => {
    if (error) {
      append(entry("agent-entry--system bad", error));
      return;
    }
    try {
      append(entry("agent-entry--system", describeOp(payload)));
    } catch (err) {
      append(entry("agent-entry--system", `Applied — result not shown (${err.message}).`));
    }
  });
}

export function update(_state) {
  // The feed is a running log, not a projection of the view — there is
  // nothing to redraw when the view changes. Exported anyway: every pane
  // implements the same two-function interface (transcript.js's header
  // comment), so a later stage can rely on `update` existing here too.
}
