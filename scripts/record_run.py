#!/usr/bin/env python3
"""Record the closed loop as a video: an agent editing in the workspace, unattended.

docs/plans/LAUNCH.md § Step 1 asks for a screen recording of the agent pane
driving a brief from `proofcut init` to a verified render. TRIAL.md already ran
that loop twice through `scripts/agent_trial.py` and scored it 9 of 9; what
the launch lacks is a *watchable* run, so this is the same loop driven through
the workspace's own agent pane — `POST /api/agent`, the route a person's Send
button hits — inside the headless Chrome the verify-live harness drives, with
`scripts/screencast.mjs` recording the page the whole time.

    uv run python scripts/record_run.py ~/proofcut-work/spikes/launch-recording
    uv run python scripts/record_run.py ~/proofcut-work/spikes/launch-recording --model claude-opus-5
    uv run python scripts/record_run.py --probe ~/proofcut-work/spikes/screenshots/proj   # compositing check

What comes out of a run, under `<work>/runs/<stamp>/`:

  recording.mp4   the page at 1920x1080, constant 30 fps, from the moment the
                  brief is sent until ~10 s after the agent's final report —
                  the last stretch is the finished cut playing in the preview
  events.jsonl    every `agent` event the pane received, verbatim — the same
                  shape `agent_trial.analyse` reads, so the run is **scored by
                  the trial's own `score()`** and `report.md` is the trial's
                  report. The video is of a measured run, not a staged one.
  frames/         the raw screencast frames and `index.jsonl` of timestamps

Three things it holds to:

- **The project is the trial's, prepared by the trial's own `prepare`**, on the
  generated demo footage — the same `vo.wav` with its fluffed take and the two
  colour-block b-roll clips whose every second names itself. Footage proofcut
  owns, so the recording can be public (LAUNCH.md § Step 1's footage rule).
- **The brief is `agent_trial.DEMO_BRIEF`, formatted the same way**, so the
  run on screen is the run TRIAL.md measured. The only difference from the
  trial is the client: the pane's `AgentSession` rather than the trial's own
  `run_agent`, and `webui.py` is where that client's flags live.
- **Whether the preview's `<video>` reaches the recording is measured, never
  assumed.** `Page.captureScreenshot` composited it on two days and not on a
  third with the same binary (wiki tooling.md § Headless browser), and a
  screencast is the same compositor. `--probe` serves a project that already
  has picture, plays it, and reads the mean luma of the `#frame` rect off the
  captured frames; a run does the same over its own playback tail and reports
  `preview_luma` beside the score. Black there is a fact about the recording
  and never about the edit.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import threading
import time
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "src"))

import agent_trial
import capture_screenshots as shots

SCREENCAST = REPO / "scripts" / "screencast.mjs"
SIZE = (1920, 1080)
#: The page is laid out at this size and drawn at `SIZE`, through a CSS
#: `transform: scale(SCALE)` on `<body>` — so the recording is 1920x1080 with
#: the window's type half again as large as a 1920-wide layout draws it. A
#: whole-window shot of a text-dense UI is unreadable at 13px in a 1080p
#: frame. A transform rather than a device scale factor because CDP's
#: screencast hands back CSS pixels whatever the scale factor is (measured
#: three ways), and rather than CSS `zoom` because zoom reaches the layout's
#: own measurements and the preview pane collapsed to 88x50 mid-run under it
#: (HISTORY.md § The launch clip, third shape).
VIEWPORT = (1280, 720)
SCALE = SIZE[0] / VIEWPORT[0]
#: How long the finished cut plays at the end of the recording. Long enough to
#: cross a shot boundary on the demo edit (its first shot is ~9.7 s).
PLAY_TAIL_SECONDS = 12.0
#: The trial's own ceiling; a run that times out mid-render measures this
#: number rather than the agent.
RUN_TIMEOUT = agent_trial.DEFAULT_TIMEOUT
FPS = 30


class RecordError(RuntimeError):
    pass


log = shots.log


# ------------------------------------------------------------------ the recorder


class Screencast:
    """`screencast.mjs`, started and stopped around whatever is being recorded."""

    def __init__(self, out: Path, cdp_port: int) -> None:
        self.out = out
        self.env = dict(os.environ, CDP_PORT=str(cdp_port))
        self.proc: subprocess.Popen[str] | None = None

    def start(self) -> None:
        self.out.mkdir(parents=True, exist_ok=True)
        self.proc = subprocess.Popen(
            ["node", str(SCREENCAST), str(self.out), str(SIZE[0]), str(SIZE[1])],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env=self.env,
        )
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if (self.out / "STARTED").exists():
                log(f"recording to {self.out}")
                return
            if self.proc.poll() is not None:
                raise RecordError(f"screencast.mjs exited early:\n{self.proc.stdout.read()}")
            time.sleep(0.2)
        raise RecordError("screencast.mjs never started")

    def stop(self) -> int:
        assert self.proc is not None
        self.proc.send_signal(signal.SIGTERM)
        try:
            out, _ = self.proc.communicate(timeout=30)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            raise RecordError("screencast.mjs did not stop") from None
        try:
            return int(json.loads(out.strip().splitlines()[-1])["frames"])
        except (ValueError, IndexError, KeyError):
            raise RecordError(f"screencast.mjs reported nothing usable:\n{out}") from None

    def frames(self) -> list[dict[str, Any]]:
        index = self.out / "index.jsonl"
        return [json.loads(line) for line in index.read_text().splitlines() if line.strip()]


def assemble(frames: list[dict[str, Any]], base: Path, out: Path, *, stop_at: float | None = None) -> Path:
    """Variable-rate frames → a constant-rate mp4, through the concat demuxer.

    Each frame holds until the next one's timestamp; the last holds for a
    second, or until `stop_at` when the recording's end is known. `fps=` then
    resamples to a constant rate, which every editor and every platform in
    LAUNCH.md wants and proofcut's own import expects.
    """
    if not frames:
        raise RecordError("no frames were recorded")
    # `file` in the index is relative to the screencast directory, not the run
    # directory — the first run's frames were all there and ffmpeg was told to
    # look one level up. Absolute paths, so the listing says where they are.
    listing = out.parent / "frames.txt"
    lines = ["ffconcat version 1.0"]
    for i, frame in enumerate(frames):
        nxt = frames[i + 1]["ts"] if i + 1 < len(frames) else (stop_at or frame["ts"] + 1.0)
        # The true interval, never floored: Chrome repaints in bursts far
        # denser than 30 fps (8178 frames in 180 s on the first run, most of
        # them microseconds apart), and a floor of one frame-time on each
        # stretched that run to 313 s. `fps=` downstream is what picks one
        # frame per 1/30 s; here the durations only have to sum to wall time.
        duration = max(nxt - frame["ts"], 1e-4)
        lines.append(f"file '{(base / frame['file']).resolve()}'")
        lines.append(f"duration {duration:.4f}")
    lines.append(f"file '{(base / frames[-1]['file']).resolve()}'")  # concat needs the last file restated
    listing.write_text("\n".join(lines) + "\n")
    done = subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "concat", "-safe", "0", "-i", str(listing),
            "-vf", f"fps={FPS},scale={SIZE[0]}:{SIZE[1]}:flags=lanczos,format=yuv420p",
            "-c:v", "libx264", "-crf", "18", "-preset", "medium", "-movflags", "+faststart",
            str(out),
        ],
        cwd=out.parent,
        capture_output=True,
        text=True,
        check=False,
    )
    if done.returncode != 0:
        raise RecordError(f"ffmpeg failed:\n{done.stderr}")
    return out


# ------------------------------------------------------------------ the measurement


def frame_rect() -> dict[str, int]:
    rect = shots.evaluate(
        '(() => { const r = document.getElementById("frame").getBoundingClientRect();'
        " return {x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height)}; })()"
    )
    if not isinstance(rect, dict) or not rect.get("w"):
        raise RecordError(f"#frame has no rect: {rect!r}")
    # `getBoundingClientRect` reports through the body's transform, so the
    # rect is already in the frame's pixels.
    return rect


def luma(path: Path, rect: dict[str, int]) -> float:
    """Mean Y inside `rect` of one captured frame, on ffmpeg's own 8-bit scale."""
    done = subprocess.run(
        [
            "ffprobe", "-v", "error", "-f", "lavfi",
            "-i", f"movie={path},crop={rect['w']}:{rect['h']}:{rect['x']}:{rect['y']},signalstats",
            "-show_entries", "frame_tags=lavfi.signalstats.YAVG", "-of", "csv=p=0",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    try:
        return float(done.stdout.strip().splitlines()[0])
    except (ValueError, IndexError):
        raise RecordError(f"ffprobe read nothing off {path}:\n{done.stderr}") from None


def preview_luma(frames: list[dict[str, Any]], since: float, rect: dict[str, int], base: Path) -> dict[str, Any]:
    """Mean `#frame` luma over the frames captured after `since` — the playback tail.

    A black preview measures ~16 (video black) or 0; the demo's blue and rust
    blocks measure well above. Reported as min/mean/max over the tail and the
    count of frames read, so a single stray frame cannot answer for the run.
    """
    tail = [f for f in frames if f["ts"] >= since]
    sample = tail[:: max(1, len(tail) // 12)][:12]
    values = [luma(base / f["file"], rect) for f in sample]
    if not values:
        return {"frames": 0, "verdict": "no frames captured during playback"}
    mean = sum(values) / len(values)
    return {
        "frames": len(tail),
        "sampled": len(values),
        "min": round(min(values), 1),
        "mean": round(mean, 1),
        "max": round(max(values), 1),
        "verdict": "the preview composited into the recording" if max(values) > 40 else "BLACK — the preview did not composite",
    }


# ------------------------------------------------------------------ the event tap


class EventTap(threading.Thread):
    """`GET /api/events`, tapped: every `agent` event to `events.jsonl`, verbatim.

    This is the same stream the pane draws from, so the file is the run as
    the pane saw it — `agent_trial.analyse` reads it unchanged. `done` is set
    on the `result` event, which is also what clears the pane's `busy`.
    """

    def __init__(self, port: int, out: Path) -> None:
        super().__init__(daemon=True)
        self.url = f"http://127.0.0.1:{port}/api/events"
        self.out = out
        self.done = threading.Event()
        self.events: list[dict[str, Any]] = []
        self.started = time.time()

    def run(self) -> None:
        with urllib.request.urlopen(self.url) as response, self.out.open("a", encoding="utf-8") as fh:
            event = ""
            for raw in response:
                line = raw.decode("utf-8").rstrip("\n")
                if line.startswith("event: "):
                    event = line[7:]
                elif line.startswith("data: ") and event == "agent":
                    payload = json.loads(line[6:])
                    self.events.append(payload)
                    fh.write(json.dumps(payload) + "\n")
                    fh.flush()
                    agent_trial._echo(payload, self.started)
                    if payload.get("type") == "result":
                        self.done.set()
                        return
                elif line == "":
                    event = ""


# ------------------------------------------------------------------ the two modes


def open_workspace(root: Path, port: int, cdp_port: int, env: dict[str, str]) -> tuple[subprocess.Popen, subprocess.Popen]:
    server = shots.serve(root, port, env)
    browser = shots.browse(cdp_port, size=f"{SIZE[0]},{SIZE[1]}", mute=True)
    os.environ["CDP_PORT"] = str(cdp_port)
    url = f"http://127.0.0.1:{port}/"
    shots.seed_dark(url)
    shots.cdp("viewport", str(SIZE[0]), str(SIZE[1]))
    shots.evaluate(
        "(() => { document.documentElement.style.cssText ="
        f" 'width:{VIEWPORT[0]}px;height:{VIEWPORT[1]}px;overflow:hidden';"
        " document.body.style.cssText ="
        f" 'width:{VIEWPORT[0]}px;height:{VIEWPORT[1]}px;transform:scale({SCALE:g});transform-origin:0 0';"
        " window.dispatchEvent(new Event('resize')); return true; })()"
    )
    # The page opens on Home; the preview, transcript and rail are Edit's.
    shots.cdp("click", "#mode-tab-edit", "120")
    return server, browser


def play(seconds: float) -> None:
    """Space, with focus off every field — `player.js` ignores it in a typing target."""
    shots.evaluate("(() => { document.activeElement?.blur(); return true; })()")
    shots.cdp("key", "Space", "-", "120")
    time.sleep(seconds)


def probe(project: Path, port: int, cdp_port: int, keep: bool) -> int:
    env = shots.render_env()
    server, browser = open_workspace(project, port, cdp_port, env)
    try:
        shots.wait_for('(() => document.querySelectorAll(".w").length > 0 || null)()', "the transcript", 60)
        rect = frame_rect()
        out = project.parent / "probe"
        cast = Screencast(out, cdp_port)
        cast.start()
        since = time.time()
        play(4.0)
        count = cast.stop()
        frames = cast.frames()
        result = preview_luma(frames, since, rect, out)
        result["captured"] = count
        result["frame_rect"] = rect
        print(json.dumps(result, indent=2))
        return 0 if result.get("max", 0) > 40 else 1
    finally:
        if not keep:
            server.send_signal(signal.SIGTERM)
            browser.send_signal(signal.SIGTERM)


def _tilde(path: Path) -> str:
    """`/home/<user>/x` → `~/x`, and any other path as it is."""
    home = Path.home().resolve()
    resolved = Path(path).resolve()
    try:
        return "~/" + resolved.relative_to(home).as_posix()
    except ValueError:
        return str(resolved)


def type_brief(text: str, cps: float) -> None:
    """Type the brief into the pane at `cps` characters a second, as a person would.

    The page's own JS appends a character at a time with a jittered delay, a
    beat on spaces and a longer one on sentence punctuation, and dispatches
    `input` each step so the textarea grows as it fills. Returns when the last
    character is in; the caller clicks Send.
    """
    shots.evaluate(
        "(() => { const t = document.getElementById('agent-prompt'); t.value = ''; t.focus();"
        f" const text = {json.dumps(text)}; const base = 1000 / {cps}; let i = 0;"
        " const step = () => { if (i >= text.length) return; const ch = text[i++]; t.value += ch;"
        "   t.dispatchEvent(new Event('input', {bubbles: true})); t.scrollTop = t.scrollHeight;"
        "   let wait = base * (0.8 + 0.4 * Math.random());"
        "   if (ch === ' ') wait += base * 0.5; if ('.,;:—'.includes(ch)) wait += base * 3;"
        "   if (ch === '\\n') wait += base * 6; setTimeout(step, wait); };"
        " step(); return text.length; })()"
    )
    shots.wait_for(
        f"(() => document.getElementById('agent-prompt').value.length >= {len(text)} || null)()",
        "the brief to finish typing", max(30.0, len(text) / cps * 3),
    )
    time.sleep(0.6)


def record(work: Path, model: str | None, port: int, cdp_port: int, keep: bool, *,
           media_dir: Path | None = None, brief_file: Path | None = None,
           phrases: dict[str, str] | None = None, min_clips: int | None = None,
           typing_cps: float = 0.0) -> int:
    lock = agent_trial.hold_lock(work)
    try:
        # The footage lives in its own folder: `list_media` walks the folder
        # it is handed, and with the media at the work root the second take's
        # agent found the first take's `runs/…/recording.mp4` and reported an
        # unlisted file it had decided not to import.
        # `--media` names real footage and nothing is generated; the default is
        # the trial's own generated demo, made once into `work/media`.
        if media_dir is None:
            media_dir = work / "media"
            media_dir.mkdir(parents=True, exist_ok=True)
            if not (media_dir / "vo.wav").exists():
                agent_trial.make_demo.make_voiceover(media_dir / "vo.wav")
            if not all((media_dir / name).exists() for name, _c, _l in agent_trial.make_demo.BROLL):
                agent_trial.make_demo.make_broll(media_dir)
        media, project = agent_trial.prepare(work, fresh=True, source=media_dir)
        phrases = agent_trial.DEMO_PHRASES if phrases is None else phrases
        min_clips = agent_trial.DEMO_MIN_CLIPS if min_clips is None else min_clips
        output = work / "cut.mp4"
        if output.exists():
            output.unlink()
        # The brief is the trial's, with every path spelled `~/…`: the pane
        # shows the brief verbatim, and a recording meant to be public should
        # not print a username in its first ten seconds. proofcut expands `~` on
        # media sources, output paths and (as of this script) the confined
        # `path`, so the agent can pass them exactly as written.
        template = brief_file.read_text(encoding="utf-8") if brief_file else agent_trial.DEMO_BRIEF
        brief = template.format(media=_tilde(media), project=_tilde(project), output=_tilde(output)).strip()
        stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        run_dir = work / "runs" / stamp
        run_dir.mkdir(parents=True)
        (run_dir / "brief.txt").write_text(brief, encoding="utf-8")
        (run_dir / "scoring.json").write_text(
            json.dumps({"phrases": phrases, "min_clips": min_clips,
                        "material": str(media), "client": "webui agent pane", "model": model,
                        "brief_paths": "tilde"}, indent=2),
            encoding="utf-8",
        )
        lock.write_text(json.dumps({"pid": os.getpid(), "started": datetime.now(UTC).isoformat(),
                                    "run_dir": str(run_dir)}), encoding="utf-8")
        log(f"media   -> {media}")
        log(f"project -> {project}")
        log(f"run     -> {run_dir}")

        env = shots.render_env()
        server, browser = open_workspace(project, port, cdp_port, env)
        try:
            shots.cdp("click", "#rail-tab-agent", "120")
            if model:
                shots.evaluate(
                    "(() => { const s = document.getElementById('agent-model-select');"
                    f" s.value = {json.dumps(model)}; s.dispatchEvent(new Event('change', {{bubbles: true}}));"
                    " return s.value; })()"
                )
            tap = EventTap(port, run_dir / "events.jsonl")
            tap.start()
            cast = Screencast(run_dir / "frames", cdp_port)
            cast.start()
            time.sleep(1.5)  # a beat of the empty workspace before the brief lands
            marks: dict[str, float] = {"typing_started": time.time()}
            # The brief goes in as a paste would — the textarea's value — and
            # Send is a real hit-tested click, the same gesture a person makes.
            if typing_cps > 0:
                type_brief(brief, typing_cps)
            else:
                shots.evaluate(
                    "(() => { const t = document.getElementById('agent-prompt');"
                    f" t.value = {json.dumps(brief)}; t.dispatchEvent(new Event('input', {{bubbles: true}}));"
                    " return t.value.length; })()"
                )
            shots.cdp("click", "#agent-send", "120")
            started = time.time()
            marks["sent"] = started
            log("brief sent — the agent is running (whisper, then the edit, then melt)")
            if not tap.done.wait(RUN_TIMEOUT):
                raise RecordError(f"the agent did not finish inside {RUN_TIMEOUT:.0f}s")
            marks["done"] = time.time()
            wall = round(time.time() - started, 1)
            # The three moments a cut of this recording needs, on the frames' own
            # clock (epoch seconds, like `index.jsonl`'s `ts`).
            (run_dir / "marks.json").write_text(json.dumps(marks), encoding="utf-8")
            log(f"agent finished in {wall}s — playing the cut for the tail")
            time.sleep(2.0)
            rect = frame_rect()
            since = time.time()
            play(PLAY_TAIL_SECONDS)
            stop_at = time.time()
            count = cast.stop()
            log(f"{count} frames captured")
            (run_dir / "tail.json").write_text(
                json.dumps({"since": since, "stop_at": stop_at, "rect": rect, "wall_seconds": wall}), encoding="utf-8"
            )
        finally:
            if not keep:
                server.send_signal(signal.SIGTERM)
                browser.send_signal(signal.SIGTERM)

        return finish(run_dir, project)
    finally:
        lock.unlink(missing_ok=True)


def finish(run_dir: Path, project: Path) -> int:
    """Assemble the mp4, measure the tail, score the run, write the report.

    Everything it reads is on disk — `frames/index.jsonl`, `events.jsonl`,
    `tail.json`, `brief.txt` — so `--assemble RUN_DIR` can redo it without
    spending another agent run, which is how the first run's assembly bug was
    recovered from rather than re-recorded.
    """
    cast = Screencast(run_dir / "frames", 0)
    frames = cast.frames()
    tail = json.loads((run_dir / "tail.json").read_text(encoding="utf-8"))
    video = assemble(frames, run_dir / "frames", run_dir / "recording.mp4", stop_at=tail["stop_at"])
    log(f"recording -> {video}")
    composited = preview_luma(frames, tail["since"], tail["rect"], run_dir / "frames")
    log(f"preview: {composited['verdict']}")

    events = [
        json.loads(line)
        for line in (run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    analysis = agent_trial.analyse(events)
    # Score against the pair the run was recorded with, never the demo's.
    scoring = json.loads((run_dir / "scoring.json").read_text(encoding="utf-8"))
    scored = agent_trial.score(project, agent_trial.evidence_from_analysis(analysis),
                               phrases=scoring.get("phrases"),
                               min_clips=scoring.get("min_clips", agent_trial.DEMO_MIN_CLIPS))
    run = {"returncode": 0, "timed_out": False, "wall_seconds": tail["wall_seconds"],
           "undecodable_lines": 0, "stderr_tail": "", "client": "webui agent pane",
           "recording": str(video), "preview_luma": composited}
    brief = (run_dir / "brief.txt").read_text(encoding="utf-8")
    report = agent_trial.write_report(run_dir, run, analysis, scored, brief)
    print(f"\n{report}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("work", nargs="?", default="~/proofcut-work/spikes/launch-recording",
                        help="the work directory (media, project and runs live here)")
    parser.add_argument("--probe", metavar="PROJECT",
                        help="serve this project, play it, and measure whether the preview reaches the recording")
    parser.add_argument("--assemble", metavar="RUN_DIR",
                        help="redo the post-run half (mp4, tail measurement, score, report) for a recorded run")
    parser.add_argument("--model", default=None, help="pin the pane's model (default: the pane's default)")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--cdp-port", type=int, default=0)
    parser.add_argument("--keep", action="store_true", help="leave the server and browser up")
    parser.add_argument("--media", metavar="DIR", help="real footage to brief the agent on (default: the generated demo)")
    parser.add_argument("--brief-file", metavar="FILE",
                        help="the brief, with {media}, {project} and {output} placeholders (default: the trial's)")
    parser.add_argument("--phrases", metavar="FILE", help="JSON {remove, keep} the run is scored against")
    parser.add_argument("--min-clips", type=int, default=None, help="clips the brief's footage should register")
    parser.add_argument("--type", type=float, default=0.0, metavar="CPS",
                        help="type the brief into the pane at this many characters a second (default: paste)")
    args = parser.parse_args(argv)
    port = args.port or shots.free_port()
    cdp_port = args.cdp_port or shots.free_port()
    shots.require("node", "screencast.mjs and cdp.mjs run on it")
    shots.require("ffmpeg", "the frames are assembled with it")
    shots.require("ffprobe", "the preview is measured with it")
    try:
        if args.probe:
            return probe(Path(args.probe).expanduser().resolve(), port, cdp_port, args.keep)
        if args.assemble:
            run_dir = Path(args.assemble).expanduser().resolve()
            return finish(run_dir, run_dir.parent.parent / "proj")
        phrases = json.loads(Path(args.phrases).expanduser().read_text(encoding="utf-8")) if args.phrases else None
        return record(Path(args.work).expanduser().resolve(), args.model, port, cdp_port, args.keep,
                      media_dir=Path(args.media).expanduser().resolve() if args.media else None,
                      brief_file=Path(args.brief_file).expanduser() if args.brief_file else None,
                      phrases=phrases, min_clips=args.min_clips, typing_cps=args.type)
    except (RecordError, shots.CaptureError, agent_trial.TrialError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
