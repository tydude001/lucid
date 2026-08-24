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
node cdp.mjs viewport 700 900                # resize; two sweeps (see below)
node cdp.mjs key "?" - 120                   # a real key press; `-` = no focus target
node cdp.mjs key Escape "#agent-prompt" 0    # ...or press it with focus in a field
node cdp.mjs console 3000                    # console errors for N ms, each with its url
node cdp.mjs shot out.png
```

`CDP_PORT` overrides 9444.

## What it will not do for you

- **`click` refuses a target it cannot hit.** It asserts
  `document.elementFromPoint` at the point it presses, because `el.click()`
  skips hit-testing and reads green on a control nobody can reach.
- **Whether a screenshot contains `<video>` is not settled** — black on
  2026-08-09, composited on 2026-08-19 and 2026-08-24, same binary. So a black
  capture proves nothing and a good-looking one proves nothing: `drawImage`
  into a canvas and read the pixels, and only after
  `!seeking && readyState >= 2`.
- **`viewport` reports two sweeps and you need both.** `overflowing` walks the
  page and skips anything inside a scroll container — without that skip every
  ruler tick and clip block is a finding, which is a probe that gets ignored.
  `scrollers` is each scroll container against its *own* `clientWidth`, which
  is the only way a pane that clips a value mid-word ever shows up. In Edit
  mode expect exactly one, `#track-lanes`.
- **`key` sends virtual key codes, and that is not cosmetic** — a code-less
  Escape reaches a JS listener but not Chrome's `<dialog>` close watcher, and
  reads as a bug in the page. Measurement in wiki `tooling.md` § Headless
  browser.
- **A lazy image is not a broken image.** Measure `naturalWidth` only after
  scrolling the element's *real* scroll parent; through the wrong one, 30
  perfectly good tiles read exactly like a route that 404s.

Every mechanic and its measurement: wiki `tooling.md` § Headless browser.
