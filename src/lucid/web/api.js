/* api.js — the one place that talks to the server: the mutation fetch
 * wrapper and the SSE client for /api/events.
 *
 * Every pane gets `api` through `ctx`, never calls `fetch` itself, so the
 * `application/json` header a mutation needs (the server refuses anything
 * else — CLAUDE.md: the web UI draws and it plays, it never decides, but a
 * mutation still needs the header the server actually requires) lives in
 * exactly one place.
 */

/**
 * GET when called with no body, POST JSON when called with one. Throws
 * `Error(message)` on a non-2xx response, using the server's own
 * `{"error": …}` when it sent one.
 */
export async function api(path, body) {
  const opts = body
    ? {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      }
    : {};
  const response = await fetch(path, opts);
  const payload = await response.json().catch(() => ({ error: response.statusText }));
  if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
  return payload;
}

//: Event names webui.py's EventBus actually publishes on /api/events.
// "reframe-sheet"/"reframe-detect" (Studio step 03, frame.js) are here for
// the reason stated once already by "proxy"'s own absence from this list —
// a topic missing here is never delivered to onEvent at all, which is
// exactly the spinner-forever failure mode a missing FaceError handler
// would otherwise cause on the detect job (see webui.py's own note).
const SSE_EVENTS = ["project-changed", "agent", "render", "reframe-sheet", "reframe-detect"];

/**
 * Subscribe to `/api/events`. `onEvent(name, data)` fires once per SSE
 * record — `name` is one of SSE_EVENTS, `data` is the parsed JSON payload
 * (or `null` if a record failed to parse, which should not happen against
 * this server but is not treated as fatal here either).
 *
 * Returns `{close()}`. A clean drop is handled by the browser's own
 * `EventSource` retry; this wraps that in a `close()` a caller can use to
 * stop listening on purpose, and re-opens a fresh `EventSource` if the
 * connection ever reaches `CLOSED` on its own (e.g. the server restarted).
 */
export function connectEvents(onEvent) {
  let source = null;
  let closed = false;
  let retryTimer = null;

  function connect() {
    source = new EventSource("/api/events");
    for (const name of SSE_EVENTS) {
      source.addEventListener(name, (event) => {
        let data = null;
        try {
          data = JSON.parse(event.data);
        } catch {
          // Dropped, not fatal — the server's own agent-stdout reader has
          // the same policy for a line that fails to parse.
        }
        onEvent(name, data);
      });
    }
    source.onerror = () => {
      if (closed || !source) return;
      if (source.readyState === EventSource.CLOSED) {
        retryTimer = setTimeout(connect, 1000);
      }
    };
  }

  connect();

  return {
    close() {
      closed = true;
      if (retryTimer) clearTimeout(retryTimer);
      if (source) source.close();
    },
  };
}
