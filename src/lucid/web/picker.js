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
 */

import { $, el, fmt } from "./dom.js";
import { api } from "./api.js";

function toast(message) {
  const box = $("toast");
  box.textContent = message;
  box.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => {
    box.hidden = true;
  }, 9000);
}

function badgeClass(status) {
  if (status === "needs_migration") return "picker-badge warn";
  if (status === "unreadable" || status === "error") return "picker-badge bad";
  return "picker-badge";
}

function badgeText(entry) {
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

  if (entry.status === "ok") {
    // Three chips, one per already-scanned field — never arithmetic done
    // here, only `_scan_one`'s own `timeline_duration`/`segments`/`clips`
    // (CLAUDE.md: the page draws what an op/scan returned, it never decides).
    const chips = el("div", "picker-chips");
    chips.append(el("span", "chip", `${fmt(entry.timeline_duration)} timeline`));
    chips.append(el("span", "chip", `${entry.segments} segments`));
    chips.append(el("span", "chip", entry.clips === 1 ? "1 clip" : `${entry.clips} clips`));
    main.append(chips);
  } else if (entry.status === "needs_migration") {
    const meta = el("div", "picker-meta");
    meta.textContent = `needs \`lucid migrate -C ${entry.path}\` before it can open`;
    main.append(meta);
  } else {
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

  row.append(el("span", badgeClass(entry.status), badgeText(entry)));

  if (entry.status === "ok") {
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
    list.append(el("p", "picker-empty", "no lucid projects found under this root"));
    return;
  }
  for (const entry of payload.projects) list.append(card(entry));
}

load();
