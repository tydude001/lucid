#!/usr/bin/env python3
"""Recapture the README screenshots, deterministically.

They have drifted three times now, and the cause was the same each time: the
capture was driven by hand, so the theme seed, the viewport and the demo
project's state were re-derived from memory and one of them got forgotten.
2026-08-19 seeded `localStorage["lucid.theme"]` deliberately; 2026-08-24
recaptured onto new footage and simply did not, so the set came back light and
nothing said so (HISTORY.md § The screenshots went back to dark). This script
is that route written down as code instead of prose.

    uv run python scripts/capture_screenshots.py            # build, serve, shoot
    uv run python scripts/capture_screenshots.py --reuse    # keep the project
    uv run python scripts/capture_screenshots.py --keep     # leave the server up

Everything it needs is generated: `make_demo.py` writes the footage, and the
state each shot wants is `docs/DEMO.md`'s own walkthrough, replayed here as
`PROJECT_STEPS` so the two cannot drift.

**The theme is seeded before the page loads, never toggled after it.**
`theme.js` is the one classic script in `<head>` and applies `data-theme`
before paint; a toggle afterwards is a repaint that the two canvases only
follow via its `lucid:theme` event. Seeding means `localStorage`, which needs
the origin, so it is goto, set, goto — and it happens **before the render**,
because the render's SSE stream draws Edit's completion card and that does not
survive a reload.

The last step is a check, not a courtesy: `--check` measures mean luma across
the set and refuses a spread wide enough to read as two themes. That is the
check a recapture has now twice not run.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CDP = REPO / ".claude" / "skills" / "verify-live" / "cdp.mjs"
OUT = REPO / "docs" / "img"

# `docs/DEMO.md` steps 4, 5 and its "what to try next", in order. The cut and
# the two cues are what put a struck-through retake in the transcript and two
# shots on the picture lane; the reframe is what gives Frame mode a window to
# draw, without which the pane is honestly empty (HISTORY.md § The README
# screenshots came off the demo project).
PROJECT_STEPS: list[list[str]] = [
    ["cut", "vo", "11:23", "--pad", "0.1"],
    ["cue", "add", "vo", "--phrase", "Every cut you make names a word", "blue"],
    ["cue", "add", "vo", "--phrase", "the render can be checked", "rust"],
    ["caption-style", "--preset", "karaoke"],
    ["reframe", "blue", "--rect", "0,0,320,180"],
]

# Frame's shot sheet decodes real footage; it takes seconds and the pane is
# honestly empty before it lands.
SHEET_TIMEOUT = 180.0
RENDER_TIMEOUT = 600.0

# A set that disagrees with itself by more than this does not read as one
# theme, whatever `data-theme` says. The light set that prompted the complaint
# spread 97 points; the dark one that replaced it spread 23.
LUMA_SPREAD_MAX = 30
LUMA_DARK_MAX = 80


class CaptureError(RuntimeError):
    pass


def log(message: str) -> None:
    print(f"  {message}", flush=True)


def require(binary: str, why: str) -> str:
    found = shutil.which(binary)
    if not found:
        raise CaptureError(f"{binary} is not on PATH — {why}")
    return found


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def lucid(root: Path | None, *args: str) -> str:
    """Run a lucid subcommand through this interpreter, never a bare `lucid`.

    A bare name is absent from PATH for every launch that skips an activated
    venv, which is the failure CLAUDE.md records against the generated MCP
    config.
    """
    command = [sys.executable, "-m", "lucid.cli"]
    if root is not None:
        command += ["-C", str(root)]
    command += list(args)
    done = subprocess.run(command, capture_output=True, text=True, cwd=REPO, check=False)
    if done.returncode != 0:
        raise CaptureError(f"lucid {' '.join(args)} failed:\n{done.stdout}{done.stderr}")
    return done.stdout


def cdp(*args: str, timeout: float = 120.0) -> object:
    done = subprocess.run(
        ["node", str(CDP), *args], capture_output=True, text=True, timeout=timeout, check=False
    )
    if done.returncode != 0:
        raise CaptureError(f"cdp {' '.join(args)} failed:\n{done.stdout}{done.stderr}")
    text = done.stdout.strip()
    try:
        return json.loads(text) if text else None
    except json.JSONDecodeError:
        return text


def evaluate(expression: str) -> object:
    return cdp("eval", expression)


def wait_for(expression: str, what: str, timeout: float) -> object:
    """Poll a page expression until it answers truthily, or say what was waited on."""
    deadline = time.monotonic() + timeout
    last: object = None
    while time.monotonic() < deadline:
        last = evaluate(expression)
        if last:
            return last
        time.sleep(1.0)
    raise CaptureError(f"timed out after {timeout:.0f}s waiting for {what} (last: {last!r})")


def render_env() -> dict[str, str]:
    """The server's environment, with a display for MLT's Qt module.

    `picture.display_env()` finds the socket *and* the directory Qt resolves it
    under — naming one without the other aborts melt printing nothing. With no
    desktop behind the session at all, `QT_QPA_PLATFORM=offscreen` is the
    documented route and is sufficient alone (CLAUDE.md).
    """
    sys.path.insert(0, str(REPO / "src"))
    from lucid import picture

    env = dict(os.environ)
    env.update(picture.display_env())
    if not env.get("WAYLAND_DISPLAY") and not env.get("DISPLAY"):
        env.setdefault("QT_QPA_PLATFORM", "offscreen")
        log("no display found — rendering under QT_QPA_PLATFORM=offscreen")
    return env


def build_project(work: Path, reuse: bool) -> Path:
    root = work / "proj"
    if reuse and root.exists():
        log(f"reusing {root}")
        return root
    if root.exists():
        shutil.rmtree(root)
    log(f"generating demo footage in {work}")
    subprocess.run(
        [sys.executable, str(REPO / "scripts" / "make_demo.py"), str(work), "--build"],
        check=True,
        cwd=REPO,
    )
    for step in PROJECT_STEPS:
        log(f"$ lucid {' '.join(step)}")
        lucid(root, *step)
    return root


def serve(root: Path, port: int, env: dict[str, str]) -> subprocess.Popen:
    process = subprocess.Popen(
        [sys.executable, "-m", "lucid.cli", "-C", str(root), "web", "--port", str(port)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        cwd=REPO,
        env=env,
        start_new_session=True,
    )
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise CaptureError(f"lucid web exited early:\n{process.stdout.read()}")
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                log(f"serving {root} on :{port}")
                return process
        except OSError:
            time.sleep(0.3)
    raise CaptureError(f"lucid web never bound :{port}")


def browse(cdp_port: int) -> subprocess.Popen:
    binaries = sorted(
        Path.home().glob(
            ".cache/ms-playwright/chromium_headless_shell-*/"
            "chrome-headless-shell-linux64/chrome-headless-shell"
        )
    )
    if not binaries:
        raise CaptureError(
            "no chrome-headless-shell — install one with "
            "`npx playwright install chromium-headless-shell`"
        )
    process = subprocess.Popen(
        [
            str(binaries[-1]),
            f"--remote-debugging-port={cdp_port}",
            "--headless",
            "--disable-gpu",
            "--no-sandbox",
            "--hide-scrollbars",
            "--force-device-scale-factor=1",
            "--window-size=1400,900",
            "about:blank",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", cdp_port), timeout=0.5):
                log(f"browser listening on :{cdp_port}")
                return process
        except OSError:
            time.sleep(0.3)
    raise CaptureError(f"chrome-headless-shell never bound :{cdp_port}")


def seed_dark(url: str) -> None:
    """goto, set, goto — `localStorage` needs the origin before it can be written."""
    cdp("goto", url)
    evaluate('(() => localStorage.setItem("lucid.theme", "dark"))()')
    cdp("goto", url)
    glyph = evaluate('(() => document.getElementById("theme").textContent.trim())()')
    theme = evaluate('(() => document.documentElement.dataset.theme || "auto")()')
    if theme != "dark":
        raise CaptureError(f'the theme seed did not take: data-theme={theme!r} #theme={glyph!r}')
    log(f'seeded dark before paint (data-theme="dark", #theme={glyph})')


def drive_render(burn: bool = True) -> None:
    """One render fills two panes.

    Finish's stage report and Edit's "Export complete" card are the same SSE
    stream — the card is `agent.js`'s `handleRenderEvent`, not an agent run —
    so this is what puts a finished render in the Edit shot, and no `claude -p`
    is needed. It does not survive a reload, so the theme is already seeded.
    """
    cdp("viewport", "1400", "1100")
    cdp("click", "#mode-tab-finish", "120")
    checked = evaluate('(() => !!document.querySelector("#finish-burn-checkbox")?.checked)()')
    if burn and not checked:
        cdp("click", "#finish-burn-checkbox", "120")
    log("rendering from Finish (this is the slow part)")
    cdp("click", "#finish-render", "120")
    wait_for(
        '(() => /complete|failed|error/i.test('
        'document.querySelector("#finish-report")?.textContent || "") || null)()',
        "the render to finish",
        RENDER_TIMEOUT,
    )
    report = evaluate('(() => document.querySelector("#finish-report").textContent)()')
    if isinstance(report, str) and "ailed" in report:
        raise CaptureError(f"the render failed:\n{report}")
    log("render complete")


def content_height(view: str) -> int:
    """The natural height of a mode's content, so the shot has no dead space.

    Frame mode is why this exists: captured flat at 1400x900 it came out 44%
    dead black, because its content stops at ~503px and the pane below it is
    empty. Beside a full Edit shot that reads as a different, emptier product.

    **Skip anything that stretches to the pane's own bottom.** Measuring every
    descendant answers the pane height, not the content: `.frame-body` and
    both of its columns are `flex: 1 1 auto` and all three end exactly at the
    view's bottom edge. Their *children* are the content, and a column with
    more content than fits pushes a child past that edge, so it still grows
    the shot rather than being cropped. Measuring the columns' `scrollHeight`
    instead does not work — with content shorter than the box it reports the
    box.
    """
    return int(
        evaluate(
            f"""(() => {{
      const view = document.querySelector({json.dumps(view)});
      if (!view) return 0;
      const viewBottom = view.getBoundingClientRect().bottom;
      let bottom = 0;
      for (const el of view.querySelectorAll('*')) {{
        const r = el.getBoundingClientRect();
        if (!r.width || !r.height) continue;
        if (Math.abs(r.bottom - viewBottom) < 2) continue;  // stretches to the pane
        bottom = Math.max(bottom, r.bottom);
      }}
      return Math.ceil(bottom);
    }})()"""
        )
        or 0
    )


def fit_viewport(view: str, floor: int = 420, ceiling: int = 1600, pad: int = 18) -> int:
    """Resize to the content, twice — the first resize reflows what it measured."""
    height = 900
    for _ in range(2):
        measured = content_height(view)
        if not measured:
            break
        height = max(floor, min(ceiling, measured + pad))
        cdp("viewport", "1400", str(height))
        time.sleep(0.4)
    return height


def click_at(x: int, y: int, dwell: int = 120) -> None:
    """A real click at a point — a zero-distance `dragxy` is press, move, release."""
    cdp("dragxy", str(x), str(y), str(x), str(y), str(dwell))


def rebuild_timeline() -> int:
    """Nudge the viewport so the timeline re-measures, and say how wide it came out.

    `computePxPerSec` reads `#track-lanes`'s `clientWidth` **or 800**, and a
    hidden pane measures 0 — so a `project-changed` landing while Edit is not
    the visible mode rebuilds every lane at the 800px fallback, and coming back
    to Edit does not re-measure. The render this script drives from Finish is
    exactly such an event, which is how the first automated capture came out
    with a timeline 800px wide in a 1316px pane: the film drawn shorter than it
    is, every block at the wrong scale. A resize is what re-measures.
    """
    cdp("viewport", "1400", "901")
    time.sleep(0.4)
    cdp("viewport", "1400", "900")
    time.sleep(0.6)
    return int(
        evaluate(
            '(() => Math.round(document.querySelector(".ruler")?.getBoundingClientRect().width || 0))()'
        )
        or 0
    )


def seek_timeline(seconds: float) -> str:
    """Seek by clicking the caption lane, which is what a person would do.

    Not the ruler — `seekOnClick` is bound to the lanes, not to it. Not a word
    in the transcript either: clicking one raises the `.selection-toolbar` over
    the transcript and Escape does not lower it, because `refreshToolbar` hides
    on a null selection and the only gesture that nulls one is a mousedown
    outside any `.w`. A lane click leaves the playhead's own `.w.playing`
    highlight and no toolbar, which is what the shot wants.
    """
    point = evaluate(
        f"""(() => {{
      const lane = document.querySelector('.lane-cc') || document.querySelector('.lane-a1');
      const ruler = document.querySelector('.ruler');
      const clock = document.querySelector('#clock')?.textContent || '';
      const total = (() => {{
        const m = clock.match(/\\/\\s*(\\d+):(\\d+(?:\\.\\d+)?)/);
        return m ? Number(m[1]) * 60 + Number(m[2]) : 0;
      }})();
      if (!lane || !ruler || !total) return null;
      const r = ruler.getBoundingClientRect(), l = lane.getBoundingClientRect();
      return {{x: Math.round(r.x + ({seconds} / total) * r.width),
               y: Math.round(l.y + l.height / 2), total}};
    }})()"""
    )
    if not isinstance(point, dict):
        raise CaptureError(f"could not place a seek at {seconds}s — no lane, ruler or clock")
    click_at(int(point["x"]), int(point["y"]))
    time.sleep(1.0)
    state = evaluate(
        """(() => ({clock: document.querySelector('#clock').textContent,
                    playing: [...document.querySelectorAll('.w.playing')].map(e => e.textContent.trim()),
                    toolbar: [...document.querySelectorAll('.selection-toolbar')].some(e => !e.hidden)}))()"""
    )
    if not isinstance(state, dict) or state.get("toolbar"):
        raise CaptureError(f"the seek raised a selection toolbar: {state!r}")
    if not state.get("playing"):
        raise CaptureError(f"the seek did not move the playhead: {state!r}")
    return f"{state['clock']}  ·  playing {', '.join(state['playing'])}"


def shoot(name: str, out: Path) -> Path:
    path = out / name
    cdp("shot", str(path))
    return path


def capture_edit(out: Path, seconds: float = 9.9) -> Path:
    """The hero: the whole workspace with a finished render reported in the rail."""
    cdp("viewport", "1400", "900")
    cdp("click", "#mode-tab-edit", "120")
    time.sleep(0.6)
    width = rebuild_timeline()
    lanes = int(evaluate('(() => document.querySelector("#track-lanes").clientWidth)()') or 0)
    if width < lanes - 4:
        raise CaptureError(
            f"the timeline drew {width}px in a {lanes}px pane — it is still on "
            "computePxPerSec's 800 fallback, so the resize did not re-measure"
        )
    # The rail is one pane with three tab panels, and the render's completion
    # card is on the agent one. `setRailTab` is the only thing that moves the
    # selection, so this is a click and not an attribute.
    cdp("click", "#rail-tab-agent", "120")
    time.sleep(0.4)
    # The README's caption for this image claims the rail is reporting a
    # finished render, so the card has to actually be there. It is drawn by
    # `handleRenderEvent` off the render's own SSE stream and does not survive
    # a reload, which is the failure this asserts against.
    feed = evaluate('(() => document.querySelector("#agent-feed")?.textContent || "")()')
    if not isinstance(feed, str) or "Export complete" not in feed:
        raise CaptureError(
            "the agent pane is not showing the render's completion card — it does "
            "not survive a reload, so nothing may reload the page after the render"
        )
    log(f"timeline {width}px in a {lanes}px pane · {seek_timeline(seconds)}")
    time.sleep(0.8)
    path = shoot("edit-mode.png", out)
    log(f"edit-mode.png  <- {path}")
    return path


def capture_frame(out: Path) -> Path:
    cdp("viewport", "1400", "900")
    cdp("click", "#mode-tab-frame", "120")
    time.sleep(0.6)
    cdp("click", "#frame-build-sheet", "120")
    log("building the shot sheet")
    wait_for(
        '(() => (document.querySelector("#frame-rows")?.textContent || "")'
        '.includes("window 1") || null)()',
        "the shot sheet to draw",
        SHEET_TIMEOUT,
    )
    height = fit_viewport("#frame-view")
    log(f"frame content measured at {height}px — shooting 1400x{height}")
    time.sleep(0.5)
    path = shoot("frame-mode.png", out)
    log(f"frame-mode.png <- {path}")
    return path


def luma(path: Path) -> int:
    done = subprocess.run(
        ["magick", str(path), "-colorspace", "Gray", "-format", "%[fx:round(mean*255)]", "info:"],
        capture_output=True,
        text=True,
        check=False,
    )
    if done.returncode != 0:
        raise CaptureError(f"magick could not read {path}: {done.stderr}")
    return int(done.stdout.strip())


def check_set(paths: list[Path]) -> None:
    """Only mean luma says the set reads as one theme; `data-theme` does not.

    Two of the shots are mostly dark b-roll and Frame's sheet sits on a
    near-empty page, so a wide spread is a light capture wearing dark footage.
    """
    readings = {path.name: luma(path) for path in paths}
    spread = max(readings.values()) - min(readings.values())
    for name, value in readings.items():
        log(f"{name:<16} mean luma {value}")
    log(f"spread {spread}")
    bright = [name for name, value in readings.items() if value > LUMA_DARK_MAX]
    if bright:
        raise CaptureError(
            f"these read as a light capture (mean luma over {LUMA_DARK_MAX}): {', '.join(bright)}"
        )
    if spread > LUMA_SPREAD_MAX:
        raise CaptureError(
            f"the set spreads {spread} points (limit {LUMA_SPREAD_MAX}) — it will not read as "
            "one theme, whatever data-theme says"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--work",
        default="~/lucid-work/screenshots",
        help="where the demo project is built (default: %(default)s)",
    )
    parser.add_argument("--out", default=str(OUT), help="where the PNGs land")
    parser.add_argument("--port", type=int, default=0, help="serve on this port (0: pick one)")
    parser.add_argument("--cdp-port", type=int, default=0, help="CDP port (0: pick one)")
    parser.add_argument("--reuse", action="store_true", help="keep an existing demo project")
    parser.add_argument("--keep", action="store_true", help="leave the server and browser up")
    parser.add_argument(
        "--no-check", action="store_true", help="skip the mean-luma agreement check"
    )
    args = parser.parse_args(argv)

    require("node", "the CDP harness runs on it")
    require("magick", "the luma check reads the captures with it")
    if not CDP.exists():
        raise CaptureError(f"no CDP harness at {CDP}")

    work = Path(args.work).expanduser()
    out = Path(args.out).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    port = args.port or free_port()
    cdp_port = args.cdp_port or free_port()
    os.environ["CDP_PORT"] = str(cdp_port)

    server: subprocess.Popen | None = None
    browser: subprocess.Popen | None = None
    try:
        root = build_project(work, args.reuse)
        server = serve(root, port, render_env())
        browser = browse(cdp_port)
        url = f"http://127.0.0.1:{port}/"

        seed_dark(url)
        drive_render()
        paths = [capture_edit(out), capture_frame(out)]

        if not args.no_check:
            check_set(paths)
        print(f"\n{len(paths)} screenshots in {out}", flush=True)
        return 0
    except (CaptureError, subprocess.CalledProcessError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        if args.keep:
            print(f"\nleft up: page http://127.0.0.1:{port}/  ·  CDP_PORT={cdp_port}")
        else:
            for process in (browser, server):
                if process and process.poll() is None:
                    os.killpg(os.getpgid(process.pid), signal.SIGTERM)


if __name__ == "__main__":
    sys.exit(main())
