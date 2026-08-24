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

## Capturing the README screenshots

They are dark, all three, and the theme is **seeded before the page loads,
never toggled after it** — `theme.js` is the one classic script in `<head>`
and applies `data-theme` before paint, so a toggle afterwards is a repaint the
two canvases only follow via its `lucid:theme` event. Seeding means
`localStorage`, which needs the origin, so it is goto, set, goto:

```sh
node cdp.mjs goto http://127.0.0.1:8793/
node cdp.mjs eval '(() => localStorage.setItem("lucid.theme", "dark"))()'
node cdp.mjs goto http://127.0.0.1:8793/    # now data-theme="dark" before paint
```

**Confirm the seed took, and then confirm the set agrees.** `#theme` reading
`☾` says the attribute is set; only mean luma across the three says they read
as one theme, and it is the check a recapture has twice not run. Two of the
shots are mostly dark b-roll and Frame's sheet is mostly empty page, so a
whole-set spread near 100 is a light capture wearing dark footage —
HISTORY.md § The screenshots went back to dark.

Each shot's state, and the order that gets all three from one page:

- Render once from Finish (`#finish-render`). That one SSE stream fills both
  Finish's stage report *and* the Edit agent pane's completion card — the card
  is `handleRenderEvent`, not an agent run, so no `claude -p` is needed. It
  does not survive a reload, so seed the theme **before** rendering.
- **Finish** at `viewport 1400 1100`: click `Watch` (the player is not in the
  page until then), seek the `<video>`, then `#finish-view`'s own `scrollTop`
  to the bottom so the report sits above the picture.
- **Frame** at 1400x900: `#frame-build-sheet`, then wait on `shot #` appearing
  — a sheet takes seconds and the pane is honestly empty before it.
- **Edit** at 1400x900: the highlighted word is `.w.playing`, the playhead's,
  **not `.w.sel`** — clicking a word to seek raises the `.selection-toolbar`
  over the transcript and Escape does not lower it. Seek from the ruler, or
  clear with a `dragxy` on transcript whitespace, which is the gesture
  `handleMouseDown` actually listens for.

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
