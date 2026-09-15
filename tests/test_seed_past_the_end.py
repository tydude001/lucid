"""Seed never lays the timeline past the end of its clip — HISTORY.md § The phone's black last frame.

An iPhone 17 Pro clip holds its frames on a 1/30 grid and stretches only the
last one, by 5/600 s: 1054 frames in 35.141667 s, so `avg_frame_rate` reads
126480/4217 against an `r_frame_rate` of 30. auto-editor 31.4.2 rounds that
to a 2999/100 timebase and reports 1055 frames of it, 35.178 s, which is past
the end of the file. `seed` took the number, `export` laid 1055 frames down
at 30 fps, and the 1055th rendered black. `frames` compares the render
against the timeline, so it read 1055 of 1055 and passed.

The fixture rebuilds that timing at five seconds rather than 35: 150 frames
on the grid, the last stretched the same 5 ticks, and AAC muxed in separately
so the audio ends where the phone's did — just short of the picture. Five, not
two: at 60 frames ffprobe guesses `r_frame_rate` 120 off the one long frame,
and the render runs at 120 fps, which is not the phone's case. So each test
first asserts the clip probes at 30 fps and that auto-editor still overshoots
on it, and only then says anything about proofcut.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from proofcut import autoeditor, media, ops

needs_tools = pytest.mark.skipif(
    shutil.which("ffmpeg") is None
    or shutil.which("ffprobe") is None
    or (shutil.which("auto-editor") is None and not (Path.home() / ".local/bin/auto-editor").exists()),
    reason="ffmpeg, ffprobe and auto-editor are needed",
)

pytestmark = needs_tools

FRAMES = 150


def _ffmpeg(*args: str) -> None:
    subprocess.run(["ffmpeg", "-y", "-v", "error", *args], check=True)


def _phone_timed_clip(tmp_path: Path) -> Path:
    """`FRAMES` frames at 30 fps in a 1/600 timebase, the last one 5 ticks long."""
    even, stretched, audio, clip = (tmp_path / n for n in ("even.mov", "stretched.mov", "a.m4a", "phone.mov"))
    last = FRAMES - 1
    _ffmpeg("-f", "lavfi", "-i", "testsrc2=s=160x120:r=30", "-frames:v", str(FRAMES),
            "-c:v", "libx264", "-bf", "0", "-g", "30", "-pix_fmt", "yuv420p",
            "-video_track_timescale", "600", str(even))
    _ffmpeg("-i", str(even), "-c", "copy",
            "-bsf:v", f"setts=pts=if(eq(N\\,{last})\\,PTS+5\\,PTS):dts=if(eq(N\\,{last})\\,DTS+5\\,DTS)",
            "-video_track_timescale", "600", str(stretched))
    picture_seconds = (FRAMES * 20 + 5) / 600
    _ffmpeg("-f", "lavfi", "-i", "sine=f=440:r=48000", "-t", f"{picture_seconds - 0.0017:.3f}",
            "-c:a", "aac", str(audio))
    _ffmpeg("-i", str(audio), "-i", str(stretched), "-map", "0:a", "-map", "1:v", "-c", "copy",
            "-video_track_timescale", "600", str(clip))
    return clip


def _video_frames(path: Path) -> int:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0",
         "-show_entries", "stream=nb_read_frames", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout
    return int(out.strip())


def _seeded(tmp_path: Path) -> Path:
    clip = _phone_timed_clip(tmp_path)
    assert _video_frames(clip) == FRAMES
    info = media.probe(clip)
    assert info.fps == 30.0
    overshoot = autoeditor.silence_edit(clip, "own").duration
    assert overshoot > info.duration, "the fixture no longer makes auto-editor overshoot"
    root = tmp_path / "proj"
    ops.init(root)
    ops.import_media(root, clip, clip_id="own")
    return root


def test_seed_stops_at_the_end_of_the_clip(tmp_path: Path) -> None:
    root = _seeded(tmp_path)
    report = ops.seed_timeline(root, "own")
    assert report["timeline_duration"] <= report["source_duration"]
    assert ops.check_frames(root)["expected_frames"] == FRAMES


def test_the_render_has_no_frame_the_clip_has_not(tmp_path: Path) -> None:
    root = _seeded(tmp_path)
    ops.seed_timeline(root, "own")
    render = tmp_path / "own.mp4"
    ops.export(root, render, export_format=None, log=False)
    assert _video_frames(render) == FRAMES
    last = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(render), "-vf", f"select=eq(n\\,{FRAMES - 1})",
         "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "gray", "-"],
        capture_output=True, check=True,
    ).stdout
    assert last and sum(last) / len(last) > 40, "the render's last frame is black"
