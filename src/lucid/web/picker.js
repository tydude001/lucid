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

function card(entry) {
  const row = el("div", "picker-card");

  const main = el("div", "picker-card-main");
  main.append(el("div", "picker-name", entry.name));
  main.append(el("div", "picker-path", entry.path));

  const meta = el("div", "picker-meta");
  if (entry.status === "ok") {
    const clips = entry.clips === 1 ? "1 clip" : `${entry.clips} clips`;
    meta.textContent = `${fmt(entry.timeline_duration)} timeline · ${entry.segments} segments · ${clips}`;
  } else if (entry.status === "needs_migration") {
    meta.textContent = `needs \`lucid migrate -C ${entry.path}\` before it can open`;
  } else {
    meta.className = "picker-meta picker-error";
    meta.textContent = entry.error;
  }
  main.append(meta);
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
