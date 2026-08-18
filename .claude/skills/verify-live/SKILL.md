---
name: verify-live
description: Drive lucid's web UI in a real headless browser over CDP — clicks with dwell and hit-testing, drags, viewport overflow probes, console capture, canvas readback. Use whenever a UI change has to be verified the way STUDIO.md requires, rather than through DOM stubs or the HTTP tests.
---

# verify-live

`tests/test_webui_http.py` speaks HTTP to a real socket and proves routing.
It cannot prove a gesture works. STUDIO.md's bar for every UI item is the
real project in a real browser, every click driven at **0ms and ~120ms**
dwell — a rule that exists because a fix once read green at 0ms and was dead
in the hand (HISTORY.md § The dwell-timing lesson).

`cdp.mjs` is that harness, kept here because it has been rebuilt from scratch
in more than one session. Node 24's global `WebSocket`, no dependencies.

## Run it

```sh
# 1. serve a project (a COPY of anything real — check it first with film-check)
uv run lucid -C /path/to/proj web --port 8793

# 2. a browser to drive, left running between calls
~/.cache/ms-playwright/chromium_headless_shell-*/chrome-headless-shell-linux64/chrome-headless-shell \
  --remote-debugging-port=9444 --headless --disable-gpu --no-sandbox \
  --window-size=1400,900 about:blank &

# 3. drive it — each call attaches to the same page, so state persists
node cdp.mjs goto http://127.0.0.1:8793/
node cdp.mjs eval '(() => document.querySelector("#truth-strip").textContent)()'
node cdp.mjs click "#finish-render" 120      # dwell in ms; 0 and ~120 both
node cdp.mjs dragxy 81 327 145 326 120       # press, move in steps, release
node cdp.mjs viewport 700 900                # resizes and reports overflowing nodes
node cdp.mjs console 3000                    # collect console errors for N ms
node cdp.mjs shot out.png
```

`CDP_PORT` overrides 9444.

## What it will not do for you

- **`click` refuses a target it cannot hit.** It asserts
  `document.elementFromPoint` at the point it presses, because `el.click()`
  skips hit-testing and reads green on a control nobody can reach.
- **A screenshot never contains `<video>`** — headless Chrome does not
  composite it. `drawImage` into a canvas and read the pixels, and only after
  `!seeking && readyState >= 2`.
- **A lazy image is not a broken image.** Measure `naturalWidth` only after
  scrolling the element's *real* scroll parent; through the wrong one, 30
  perfectly good tiles read exactly like a route that 404s.

Every mechanic and its measurement: wiki `tooling.md` § Headless browser.
