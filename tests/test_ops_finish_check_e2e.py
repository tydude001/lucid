"""`ops.finish_check`, end to end against a real (small, synthetic) delivered
file — real ffmpeg/ffprobe for steps 1-3, a supplied transcript (`verify`'s
own `--transcript` escape hatch) for step 5 so no real whisper is needed
here. The stdio suite covers the branching-fake-whisper case where the
windowed pass and the boundary recheck actually run.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from proofcut import finishlog, ops
from proofcut import timeline as tl
from proofcut import transcript as tx
from proofcut.project import Project

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is not installed")
needs_ffprobe = pytest.mark.skipif(shutil.which("ffprobe") is None, reason="ffprobe is not installed")

CLIPS = {
    "vo": {
        "clip_id": "vo",
        "source": "/tmp/vo.wav",
        "duration": 6.0,
        "has_video": False,
        "has_audio": True,
    }
}

VO_WORDS = (
    ("the", 0.0, 0.3),
    ("first", 0.5, 0.9),
    ("twelve", 1.0, 1.4),
    ("minutes", 1.5, 1.9),
    ("of", 2.0, 2.2),
    ("scream", 5.0, 5.4),
)


@pytest.fixture
def project(tmp_path: Path) -> Project:
    project = Project.create(tmp_path / "proj")
    manifest = project.read_manifest()
    manifest["clips"] = list(CLIPS.values())
    project.write_manifest(manifest)
    tx.save(
        tx.Transcript(
            clip_id="vo",
            words=tuple(tx.Word(index=i, text=t, start=s, end=e) for i, (t, s, e) in enumerate(VO_WORDS)),
        ),
        project.transcript_path("vo"),
    )
    edit = tl.Edit([tl.Segment("vo", 0.0, 6.0)])
    tl.write(tl.to_otio(edit, {"vo": CLIPS["vo"]}, rate=1000.0), project.timeline_path)
    return project


def _sine_wav(dest: Path, *, duration: float) -> Path:
    subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-y", "-f", "lavfi",
         "-i", f"sine=frequency=300:duration={duration}:sample_rate=48000", str(dest)],
        capture_output=True,
        check=True,
    )  # fmt: skip
    return dest


def _clean_transcript(dest: Path) -> Path:
    """A whisper-shaped JSON that says exactly what the timeline expects —
    `similarity` comes back 1.0, nothing dropped, nothing repeated."""
    words = [{"word": t, "start": s, "end": e} for t, s, e in VO_WORDS]
    dest.write_text(json.dumps({"language": "en", "words": words}), encoding="utf-8")
    return dest


@needs_ffmpeg
@needs_ffprobe
def test_a_clean_delivered_file_reports_zero_faults_and_logs_a_passing_run(
    project: Project, tmp_path: Path
) -> None:
    final = _sine_wav(tmp_path / "final.wav", duration=6.0)
    transcript_path = _clean_transcript(tmp_path / "heard.json")

    result = ops.finish_check(project.root, final, transcript_path=transcript_path)

    assert {
        "faults", "ok", "streams", "duration", "black", "holds", "missing",
        "boundary_misses", "repeats",
    } <= set(result)  # fmt: skip
    assert result["streams"]["clean"] is True
    assert result["duration"]["agrees"] is True
    assert result["black"]["has_video"] is False
    assert result["black"]["faults"] == 0
    assert result["holds"] == []
    assert result["hold_errors"] == []
    assert result["missing"] == []
    assert result["boundary_misses"] == []
    assert result["repeats"] == []
    assert result["similarity"] == 1.0
    assert result["faults"] == 0
    assert result["ok"] is True
    assert result["mode"] == "supplied"

    logged = finishlog.last(project)
    assert logged is not None
    assert logged["ok"] is True
    assert logged["faults"] == 0
    assert logged["sha256"] == result["sha256"]
    assert logged["final"] == str(final)


@needs_ffmpeg
@needs_ffprobe
def test_a_short_delivered_file_disagrees_on_duration(project: Project, tmp_path: Path) -> None:
    """The timeline wants 6s; a 2s file is well outside `duration_tolerance`."""
    final = _sine_wav(tmp_path / "short.wav", duration=2.0)
    transcript_path = _clean_transcript(tmp_path / "heard.json")

    result = ops.finish_check(project.root, final, transcript_path=transcript_path)

    assert result["duration"]["agrees"] is False
    assert result["duration"]["delta"] < 0
    assert result["faults"] >= 1
    assert result["ok"] is False


@needs_ffmpeg
@needs_ffprobe
def test_a_chapter_list_on_the_final_file_is_a_stream_fault(project: Project, tmp_path: Path) -> None:
    meta = tmp_path / "chapters.ffmeta"
    meta.write_text(
        ";FFMETADATA1\n[CHAPTER]\nTIMEBASE=1/1000\nSTART=0\nEND=3000\ntitle=Chapter 01\n",
        encoding="utf-8",
    )
    final = tmp_path / "chaptered.mp4"
    subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-y",
         "-f", "lavfi", "-i", "sine=frequency=300:duration=6.0:sample_rate=48000",
         "-i", str(meta), "-map_metadata", "1", "-map_chapters", "1",
         "-map", "0:a", "-c:a", "aac", str(final)],
        capture_output=True,
        check=True,
    )  # fmt: skip
    transcript_path = _clean_transcript(tmp_path / "heard.json")

    result = ops.finish_check(project.root, final, transcript_path=transcript_path)

    assert result["streams"]["clean"] is False
    assert result["faults"] >= 1
    assert result["ok"] is False
