/* picker.js — `picker.html`'s only script: list what `GET /api/projects`
 * found under `--root`, and let a click on a ready one call `POST /api/open`
 * and follow the redirect into the normal workspace at `/` (webui.py's
 * `Handler._handle_open` — see its docstring for what "open" commits this
 * process to).
 *
 * Not one of app.js's panes — this is a different page, served instead of
 * index.html while no project is open yet, so there is no `ctx`/event bus
 * to join. It still goes through `api()` (api.js) for the same reason every
 * pane does: one place that knows a mutation needs `application/json`.
 *
 * It also owns the **first run** (docs/plans/POLISH.md § Step 06): create → open →
 * import → transcribe → seed, one control at a time, ending in a jump to
 * the workspace. That flow lives here and not in the workspace because a
 * project with no timeline cannot be drawn there, so everything up to the
 * first seed has to happen on this page — even though `ops.status` itself
 * now reports an un-seeded project as `ok`/`seeded: false` rather than
 * refusing it (TRIAL.md § `timeline_status` is the first call an agent
 * makes and it refuses on a fresh project). `POST /api/open` binds the
 * process before the import step, which is what makes the ordinary job
 * routes reachable from here at all.
 */

import { $, el, fmt } from "./dom.js";
import { api, connectEvents } from "./api.js";

function toast(message) {
  const box = $("toast");
  box.textContent = message;
  box.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => {
    box.hidden = true;
  }, 9000);
}

/** An un-seeded project is `ok` to the scan and a *state* to a person.
 *
 * `ops.status` used to refuse a project with no timeline, which put it in
 * the `error` bucket; it now answers `seeded: false` instead of raising
 * (TRIAL.md § `timeline_status` is the first call an agent makes and it
 * refuses on a fresh project), so the scan reports `ok` too — nothing is
 * wrong with it, it is half-made, and this page can finish it. Told apart
 * by the scan's own `seeded` field, never by matching a refusal sentence. */
function unseeded(entry) {
  return entry.status === "ok" && entry.seeded === false;
}

function badgeClass(status, entry) {
  if (entry && unseeded(entry)) return "picker-badge warn";
  if (status === "needs_migration") return "picker-badge warn";
  if (status === "unreadable" || status === "error") return "picker-badge bad";
  return "picker-badge";
}

function badgeText(entry) {
  if (unseeded(entry)) return "no timeline yet";
  if (entry.status === "needs_migration") return `schema v${entry.schema_version ?? "?"}`;
  if (entry.status === "unreadable") return "unreadable";
  if (entry.status === "error") return "error";
  return "ready";
}

/** Copies `text` to the clipboard and toasts, success or failure alike — a
 * silent copy leaves someone re-typing a path by hand. */
async function copyToClipboard(text, okMessage) {
  try {
    await navigator.clipboard.writeText(text);
    toast(okMessage);
  } catch {
    toast("couldn't copy — clipboard access was denied");
  }
}

function card(entry) {
  const row = el("div", "picker-card");

  // Left of everything else, per the contract. `loading="lazy"` and no
  // fetch of our own: the browser requests it, `/api/poster` 404s when the
  // project has never been opened (audio-only, unedited, or just never
  // bound), and the `error` listener hides the element rather than leaving
  // a broken-image glyph.
  const poster = el("img", "picker-poster");
  poster.loading = "lazy";
  poster.alt = "";
  poster.src = `/api/poster?path=${encodeURIComponent(entry.path)}`;
  poster.addEventListener("error", () => {
    poster.hidden = true;
  });
  row.append(poster);

  const main = el("div", "picker-card-main");
  main.append(el("div", "picker-name", entry.name));
  main.append(el("div", "picker-path", entry.path));

  if (entry.status === "ok" && entry.seeded) {
    // Three chips, one per already-scanned field — never arithmetic done
    // here, only `_scan_one`'s own `timeline_duration`/`segments`/`clips`
    // (CLAUDE.md: the page draws what an op/scan returned, it never decides).
    const chips = el("div", "picker-chips");
    chips.append(el("span", "chip", `${fmt(entry.timeline_duration)} timeline`));
    chips.append(el("span", "chip", `${entry.segments} segments`));
    chips.append(el("span", "chip", entry.clips === 1 ? "1 clip" : `${entry.clips} clips`));
    main.append(chips);
  } else if (unseeded(entry)) {
    const meta = el("div", "picker-meta");
    meta.textContent =
      entry.clips === 0
        ? "no footage imported yet"
        : `${entry.clips === 1 ? "1 clip" : `${entry.clips} clips`} imported, no timeline yet`;
    main.append(meta);
  } else if (entry.status === "needs_migration") {
    const meta = el("div", "picker-meta");
    meta.textContent = `needs \`lucid migrate -C ${entry.path}\` before it can open`;
    main.append(meta);
  } else {
    // Still the op's own message. Red is reserved for the cases this page
    // cannot act on; a half-made project is handled above, not here.
    const meta = el("div", "picker-meta picker-error");
    meta.textContent = entry.error;
    main.append(meta);
  }

  // Read-only, from `session.json` — this file writes nothing back. Shown
  // for any status the scan reports a session for, `needs_migration`
  // included: the session file carries no schema version of its own.
  if (entry.session && typeof entry.session === "object") {
    const mode = entry.session.mode ?? "edit";
    main.append(el("div", "picker-resume", `resumed in ${mode} mode`));
  }

  row.append(main);

  row.append(el("span", badgeClass(entry.status, entry), badgeText(entry)));

  if (entry.status === "ok" && entry.seeded) {
    const button = el("button", "primary", "Open");
    button.type = "button";
    button.addEventListener("click", async () => {
      button.disabled = true;
      try {
        await api("/api/open", { path: entry.path });
        window.location.href = "/";
      } catch (err) {
        toast(err.message);
        button.disabled = false;
      }
    });
    row.append(button);
  } else if (unseeded(entry)) {
    // A project that exists and has no timeline — `lucid init` or
    // `POST /api/create` with no seed behind it. It is not broken: it is
    // half-made, and the first-run flow is exactly what finishes it. Read
    // off the scan's own `seeded` field rather than by matching a sentence.
    const button = el("button", "primary", "Finish setup");
    button.type = "button";
    button.addEventListener("click", () => resumeSetup(entry, button));
    row.append(button);
  } else if (entry.status === "needs_migration") {
    // `lucid migrate` stays terminal-only and user-triggered — this calls
    // no API route (CLAUDE.md: never migrate on open, and on this box never
    // migrate the user's data without asking). Copying the command is the
    // entire action.
    const button = el("button", "", "Copy command");
    button.type = "button";
    button.addEventListener("click", () => {
      copyToClipboard(`lucid migrate -C ${entry.path}`, "copied — run it in a terminal");
    });
    row.append(button);
  }

  return row;
}

/* -- the first run (docs/plans/POLISH.md § Step 06) ------------------------------------
 *
 * Four steps, and the control for each one appears only when the step before
 * it has finished: name → footage → transcribe → seed. That ordering is not
 * decoration — every step needs the one before it (import needs a bound
 * project, transcribe needs a registered clip, seed needs a clip too), and
 * showing all four at once would offer three controls that refuse.
 *
 * Three rules this flow inherits rather than reinvents:
 *
 *   * **Every report is the op's own return value**, rendered from the
 *     job's `done` event. Nothing here computes a duration or a segment
 *     count (CLAUDE.md: the window draws and plays, it never decides).
 *   * **Never reload the page to pick up a finished job.** The `done` event
 *     carries the whole report, and a reload throws it away — the defect
 *     the assets pane already paid for (HISTORY.md § Import and transcribe
 *     became window operations). The one navigation here is deliberate and
 *     last: into the workspace, once there is a timeline to draw.
 *   * **A finished step folds down to one line.** A control that stays
 *     expanded spends height out of the list under it, which is how the
 *     assets pane left the second clip's own button outside the scroll
 *     window (CLAUDE.md § A floating panel is clamped, its sibling).
 */

const setup = {
  //: The project this flow is working on — set by create, or by "finish
  //: setting up" on a listed project that never got a timeline.
  path: null,
  //: The clip import registered. Transcribe and seed both address it.
  clipId: null,
  //: The SSE connection, opened only after `/api/open` — `/api/events` is
  //: not reachable on a picker server until a project is bound.
  events: null,
  //: Per-step `done` payloads, so a step that has finished can keep showing
  //: what it actually returned.
  reports: {},
  //: Which step is live. Steps before it are folded; steps after it are not
  //: drawn at all.
  step: "name",
};

const STEPS = ["name", "footage", "transcribe", "seed"];

const STEP_TITLE = {
  name: "Name it",
  footage: "Add footage",
  transcribe: "Transcribe it",
  seed: "Lay it down",
};

/** One folded line for a finished step: what it was, and what came back. */
function doneRow(step, summary) {
  const row = el("div", "setup-done");
  row.append(el("span", "setup-tick", "✓"));
  row.append(el("span", "setup-done-label", STEP_TITLE[step]));
  row.append(el("span", "setup-done-detail", summary));
  return row;
}

/** The live step's own body — a heading, a control, and a status line. */
function stepCard(title, hint) {
  const card = el("div", "setup-step");
  card.append(el("div", "setup-step-head", title));
  if (hint) card.append(el("div", "setup-hint", hint));
  return card;
}

function setStatus(node, text, kind) {
  node.textContent = text;
  node.className = kind ? `setup-status ${kind}` : "setup-status";
  node.hidden = !text;
}

/** Wait for one job topic to reach `done` or `error`.
 *
 * The job routes answer 202 and report on the stream, so this is where the
 * flow actually learns what happened. `error` rejects with the message the
 * op itself produced, never a sentence composed here.
 */
const jobListeners = [];

function awaitJob(topic) {
  return new Promise((resolve, reject) => {
    const handler = (name, data) => {
      if (name !== topic || !data) return;
      if (data.status === "done") {
        cleanup();
        resolve(data);
      } else if (data.status === "error") {
        cleanup();
        reject(new Error(data.error || `${topic} failed`));
      }
    };
    const cleanup = () => {
      const at = jobListeners.indexOf(handler);
      if (at >= 0) jobListeners.splice(at, 1);
    };
    jobListeners.push(handler);
  });
}

function openEvents() {
  if (setup.events) return;
  setup.events = connectEvents((name, data) => {
    for (const listener of [...jobListeners]) listener(name, data);
  });
}

/** Redraw `#setup` from `setup`. Called after every state change. */
function renderSetup() {
  const box = $("setup");
  box.hidden = false;
  box.textContent = "";

  for (const step of STEPS) {
    if (STEPS.indexOf(step) >= STEPS.indexOf(setup.step)) break;
    box.append(doneRow(step, setup.reports[step] ?? ""));
  }

  if (setup.step === "done") {
    const card = stepCard("Ready", "opening the workspace…");
    box.append(card);
    return;
  }
  box.append(BUILD[setup.step]());
}

function advance(step, summary) {
  setup.reports[step] = summary;
  setup.step = STEPS[STEPS.indexOf(step) + 1] ?? "done";
  renderSetup();
  if (setup.step === "done") window.location.href = "/";
}

const BUILD = {
  name() {
    const card = stepCard(
      "Name it",
      "A plain directory name. It is created under the root above — never anywhere else.",
    );
    const row = el("div", "setup-row");
    const input = el("input", "setup-input");
    input.type = "text";
    input.placeholder = "my-video";
    input.autofocus = true;
    const go = el("button", "primary", "Create");
    go.type = "button";
    const status = el("div", "setup-status");
    status.hidden = true;

    const submit = async () => {
      const name = input.value.trim();
      if (!name) {
        setStatus(status, "type a name first", "bad");
        return;
      }
      go.disabled = true;
      input.disabled = true;
      setStatus(status, "creating…", null);
      try {
        const created = await api("/api/create", { name });
        await api("/api/open", { path: created.path });
        setup.path = created.path;
        openEvents();
        advance("name", created.path);
      } catch (err) {
        setStatus(status, err.message, "bad");
        go.disabled = false;
        input.disabled = false;
      }
    };
    go.addEventListener("click", submit);
    input.addEventListener("keydown", (event) => {
      if (event.key === "Enter") submit();
    });

    row.append(input, go);
    card.append(row, status);
    return card;
  },

  footage() {
    const card = stepCard(
      "Add footage",
      "A path on this machine — a voiceover, or the clip you are cutting. " +
        "lucid links it where it lies rather than copying it.",
    );
    const row = el("div", "setup-row");
    const input = el("input", "setup-input");
    input.type = "text";
    input.placeholder = "/path/to/voiceover.wav";
    const go = el("button", "primary", "Import");
    go.type = "button";
    const status = el("div", "setup-status");
    status.hidden = true;

    const submit = async () => {
      const source = input.value.trim();
      if (!source) {
        setStatus(status, "type a path first", "bad");
        return;
      }
      go.disabled = true;
      input.disabled = true;
      setStatus(status, "importing…", null);
      try {
        const waiting = awaitJob("import");
        await api("/api/import", { source });
        const done = await waiting;
        setup.clipId = done.clip_id;
        // The op's own record, not a sentence assembled here.
        const bits = [done.clip_id, `${fmt(done.duration)}`];
        if (done.has_video) bits.push(`${done.width}×${done.height}`);
        advance("footage", bits.join(" · "));
      } catch (err) {
        setStatus(status, err.message, "bad");
        go.disabled = false;
        input.disabled = false;
      }
    };
    go.addEventListener("click", submit);
    input.addEventListener("keydown", (event) => {
      if (event.key === "Enter") submit();
    });

    row.append(input, go);
    card.append(row, status);
    return card;
  },

  transcribe() {
    const card = stepCard(
      "Transcribe it",
      "whisper reads the words and their timings. This is what makes the edit " +
        "addressable — every cut lucid makes names a word. Minutes on real footage.",
    );
    const row = el("div", "setup-row");
    const go = el("button", "primary", "Transcribe");
    go.type = "button";
    const skip = el("button", "", "Skip");
    skip.type = "button";
    const status = el("div", "setup-status");
    status.hidden = true;

    go.addEventListener("click", async () => {
      go.disabled = true;
      skip.disabled = true;
      setStatus(status, "transcribing… this one takes a while", null);
      try {
        const waiting = awaitJob("transcribe");
        await api("/api/transcribe", { clip_id: setup.clipId });
        const done = await waiting;
        // Every number here is the op's own. `hallucinated_words` and
        // `overlaps` are findings the transcription reports about itself
        // and are worth seeing on the way past rather than only in a pane
        // nobody has opened yet.
        const bits = [`${done.words} words`];
        if (done.hallucinated_words) bits.push(`${done.hallucinated_words} hallucinated, dropped`);
        if (done.overlaps?.length) bits.push(`${done.overlaps.length} seams`);
        advance("transcribe", bits.join(" · "));
      } catch (err) {
        setStatus(status, err.message, "bad");
        go.disabled = false;
        skip.disabled = false;
      }
    });
    // Skipping is real: a timeline can be seeded and cut by time without a
    // transcript. It is offered because whisper is the one dependency most
    // likely to be missing on a first run, and a flow that dead-ends there
    // teaches that lucid does not work.
    skip.addEventListener("click", () => advance("transcribe", "skipped"));

    row.append(go, skip);
    card.append(row, status);
    return card;
  },

  seed() {
    const card = stepCard(
      "Lay it down",
      "auto-editor strips the silences and the result becomes the timeline. " +
        "Turn it off to lay the clip down whole.",
    );
    const row = el("div", "setup-row");
    const label = el("label", "setup-check");
    const strip = el("input");
    strip.type = "checkbox";
    strip.checked = true;
    label.append(strip, document.createTextNode(" remove silences"));
    const go = el("button", "primary", "Seed");
    go.type = "button";
    const status = el("div", "setup-status");
    status.hidden = true;

    go.addEventListener("click", async () => {
      go.disabled = true;
      strip.disabled = true;
      setStatus(status, "seeding…", null);
      try {
        const waiting = awaitJob("seed");
        await api("/api/seed", { clip_id: setup.clipId, remove_silences: strip.checked });
        const done = await waiting;
        advance("seed", `${done.segments} segments · ${fmt(done.timeline_duration)}`);
      } catch (err) {
        setStatus(status, err.message, "bad");
        go.disabled = false;
        strip.disabled = false;
      }
    });

    row.append(label, go);
    card.append(row, status);
    return card;
  },
};

/** Start the flow at `step`, on `path` if the project already exists.
 *
 * Steps before `step` are folded away as already done, so they need their
 * report line filled in from what is known rather than left blank — a
 * resumed flow that showed a bare "✓ Name it" would read as a step that
 * finished and returned nothing.
 */
function beginSetup(step, path) {
  setup.step = step;
  setup.path = path ?? null;
  setup.clipId = null;
  setup.reports = path ? { name: path } : {};
  renderSetup();
}

/** Take a listed-but-unseeded project forward: bind to it, then import. */
async function resumeSetup(entry, button) {
  button.disabled = true;
  try {
    await api("/api/open", { path: entry.path });
  } catch (err) {
    toast(err.message);
    button.disabled = false;
    return;
  }
  openEvents();
  // The list is left standing but is no longer actionable — this process is
  // bound to one project now and every other Open would 409. Saying so is
  // better than leaving buttons that refuse.
  for (const other of document.querySelectorAll(".picker-card button")) other.disabled = true;
  beginSetup("footage", entry.path);
  $("setup").scrollIntoView({ block: "nearest" });
}

async function load() {
  const list = $("list");
  let payload;
  try {
    payload = await api("/api/projects");
  } catch (err) {
    list.textContent = "";
    list.append(el("p", "picker-empty", err.message));
    return;
  }
  $("root").textContent = payload.root;
  list.textContent = "";
  if (payload.projects.length === 0) {
    // The dead end this step exists to remove: an empty root used to say
    // "no lucid projects found" and stop there, which is only actionable if
    // you already know the CLI. The card *is* the empty state.
    beginSetup("name", null);
    return;
  }
  // With projects listed, the flow is opt-in — one button, above the list,
  // so it costs the list a row rather than a card's worth of height.
  const bar = el("div", "picker-actions");
  const make = el("button", "", "+ New project");
  make.type = "button";
  make.addEventListener("click", () => {
    make.disabled = true;
    beginSetup("name", null);
    $("setup").scrollIntoView({ block: "nearest" });
  });
  bar.append(make);
  list.append(bar);
  for (const entry of payload.projects) list.append(card(entry));
}

load();
