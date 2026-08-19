"""Attribution over a real project: a two-mic container, imported and labelled.

The container is built with the turn structure `test_speakers.py` uses — one
mic hot per turn — and then imported the way a co-hosted recording would be,
with `--mix`. That combination is the point of this file: after import,
everything downstream reads the *mixdown*, and attribution is the one op that
has to reach past it to the individual mics. PLAN.md § The co-hosted recording.
"""

from __future__ import annotations

import json
import math
import shutil
import subprocess
import wave
from pathlib import Path
from typing import Any

import pytest

from lucid import media, ops
from lucid import transcript as tx
from lucid.project import Project, ProjectError

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is not installed")
needs_ffprobe = pytest.mark.skipif(
    shutil.which("ffprobe") is None, reason="ffprobe is not installed"
)

RATE = 16000
TURN = 2.0
TURNS = 6
LOUD = 8000.0
BLEED_DB = -12.0


def _mic_wav(dest: Path, *, hot_turns: set[int]) -> Path:
    bleed = LOUD * (10.0 ** (BLEED_DB / 20.0))
    frames = int(TURN * TURNS * RATE)
    samples = bytearray()
    for n in range(frames):
        level = LOUD if int((n / RATE) // TURN) in hot_turns else bleed
        samples += int(level * math.sin(2 * math.pi * 200.0 * n / RATE)).to_bytes(
            2, "little", signed=True
        )
    with wave.open(str(dest), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(RATE)
        handle.writeframes(bytes(samples))
    return dest


def _cohost_container(tmp_path: Path, *, video: bool = False) -> Path:
    """One file, two audio streams, alternating turns — the OBS two-track shape.

    `video` puts a picture in front of them, which is what a real capture has
    and what every fixture written first does not: with video at stream 0 the
    first mic is absolute index 1, while ffmpeg's own `-map 0:a:0` still means
    the first *audio*. The two numberings agree exactly on an audio-only file
    (CLAUDE.md § `audio_index` is the container's absolute stream index).
    """
    a = _mic_wav(tmp_path / "mic_a.wav", hot_turns={t for t in range(TURNS) if t % 2 == 0})
    b = _mic_wav(tmp_path / "mic_b.wav", hot_turns={t for t in range(TURNS) if t % 2 == 1})
    dest = tmp_path / ("cohost-video.mp4" if video else "cohost.mp4")
    command = ["ffmpeg", "-nostdin", "-v", "error", "-y"]
    if video:
        command += ["-f", "lavfi", "-i", f"testsrc=size=160x120:rate=25:duration={TURN * TURNS}"]
    command += ["-i", str(a), "-i", str(b)]
    first = 1 if video else 0
    if video:
        command += ["-map", "0:v", "-c:v", "libx264", "-pix_fmt", "yuv420p"]
    command += ["-map", f"{first}:a", "-map", f"{first + 1}:a", "-c:a", "aac", str(dest)]
    subprocess.run(command, capture_output=True, check=True)
    return dest


def _transcript_json(dest: Path, *, per_turn: int = 4) -> tuple[Path, list[str]]:
    """A word every so often inside each turn, plus who really said each one."""
    words, truth = [], []
    step = TURN / (per_turn + 1)
    for turn in range(TURNS):
        for k in range(per_turn):
            start = turn * TURN + step * (k + 1)
            words.append({"word": f"w{turn}{k}", "start": start, "end": start + 0.2})
            truth.append("ana" if turn % 2 == 0 else "ben")
    dest.write_text(json.dumps({"language": "en", "words": words}), encoding="utf-8")
    return dest, truth


@pytest.fixture
def cohost(tmp_path: Path) -> tuple[Path, str, list[str]]:
    """A project holding one imported two-mic clip with a transcript attached."""
    project = tmp_path / "proj"
    ops.init(project)
    container = _cohost_container(tmp_path)
    clip = ops.import_media(project, container, mix=True)
    whisper, truth = _transcript_json(tmp_path / "words.json")
    ops.attach_transcript(project, clip["clip_id"], whisper)
    return project, clip["clip_id"], truth


@needs_ffmpeg
@needs_ffprobe
def test_every_word_is_attributed_to_the_mic_that_was_loudest(
    cohost: tuple[Path, str, list[str]],
) -> None:
    project, clip_id, truth = cohost

    report = ops.attribute_speakers(project, clip_id, labels=["ana", "ben"])

    assert report["words"] == len(truth)
    assert report["attributed"] == len(truth)
    assert report["by_label"] == {"ana": truth.count("ana"), "ben": truth.count("ben")}
    assert report["ambiguous_spans"] == []


@needs_ffmpeg
@needs_ffprobe
def test_it_reads_the_container_and_not_the_mixdown(
    cohost: tuple[Path, str, list[str]],
) -> None:
    """The whole reason `container_path` exists.

    Import summed both mics into `cache/mixed/`, and `media_path()` prefers
    it — correctly, since that is what gets edited and rendered. Attribution
    read from there would compare the mixdown against itself and could not
    tell the two speakers apart at all.
    """
    project = Project.open(cohost[0])
    clip = media.get_clip(project, cohost[1])

    assert clip.get("mixed"), "this fixture is only meaningful with a mixdown present"
    assert media.media_path(project, clip) != media.container_path(project, clip)

    report = ops.attribute_speakers(project.root, cohost[1])

    assert report["container"] == str(media.container_path(project, clip))
    assert report["audio_streams"] == 2


@needs_ffmpeg
@needs_ffprobe
def test_nothing_is_written_without_apply(cohost: tuple[Path, str, list[str]]) -> None:
    """`apply` is off by default — `reframe_detect`'s precedent, not `cut --plan`'s."""
    project, clip_id, _ = cohost
    before = Project.open(project).transcript_path(clip_id).read_text(encoding="utf-8")

    report = ops.attribute_speakers(project, clip_id)

    assert report["applied"] is False
    assert "transcript" not in report
    assert Project.open(project).transcript_path(clip_id).read_text(encoding="utf-8") == before


@needs_ffmpeg
@needs_ffprobe
def test_applying_writes_the_label_onto_every_word(
    cohost: tuple[Path, str, list[str]],
) -> None:
    project, clip_id, truth = cohost

    report = ops.attribute_speakers(project, clip_id, labels=["ana", "ben"], apply=True)

    assert report["applied"] is True
    assert report["changed"] == len(truth)
    parsed = tx.load(Project.open(project).transcript_path(clip_id), clip_id=clip_id)
    assert [w.speaker for w in parsed.words] == truth


@needs_ffmpeg
@needs_ffprobe
def test_a_label_this_refuses_to_call_is_kept_rather_than_cleared(
    cohost: tuple[Path, str, list[str]],
) -> None:
    """A word someone attributed by hand is not information this can recreate."""
    project, clip_id, _ = cohost
    cached = Project.open(project).transcript_path(clip_id)
    parsed = tx.load(cached, clip_id=clip_id)
    hand = tuple(
        w if i else tx.Word(index=w.index, text=w.text, start=w.start, end=w.end, speaker="guest")
        for i, w in enumerate(parsed.words)
    )
    tx.save(tx.Transcript(clip_id=clip_id, words=hand, language=parsed.language), cached)

    # A floor nothing can clear, so every word is refused.
    report = ops.attribute_speakers(project, clip_id, margin_db=90.0, apply=True)

    assert report["attributed"] == 0
    assert report["kept"] == 1
    assert report["changed"] == 0
    assert tx.load(cached, clip_id=clip_id).words[0].speaker == "guest"


@needs_ffmpeg
@needs_ffprobe
def test_a_high_floor_reports_spans_rather_than_guessing(
    cohost: tuple[Path, str, list[str]],
) -> None:
    """Under the floor the words come back to be listened to, with their neighbours."""
    project, clip_id, truth = cohost

    report = ops.attribute_speakers(project, clip_id, margin_db=90.0)

    assert report["attributed"] == 0
    assert report["ambiguous"] == len(truth)
    assert report["ambiguous_spans_total"] == 1
    span = report["ambiguous_spans"][0]
    assert span["first_word"] == 0
    assert span["words"] == len(truth)
    assert "dB" in span["why"]


@needs_ffmpeg
@needs_ffprobe
def test_the_span_list_is_capped_and_says_so(cohost: tuple[Path, str, list[str]]) -> None:
    """A truncated list that does not name the total reads as the whole finding."""
    project, clip_id, _ = cohost

    report = ops.attribute_speakers(project, clip_id, margin_db=90.0, limit=0)

    assert report["ambiguous_spans"] == []
    assert report["ambiguous_spans_total"] == 1


@needs_ffmpeg
@needs_ffprobe
def test_naming_one_stream_of_the_two_is_refused_by_the_labels(
    cohost: tuple[Path, str, list[str]],
) -> None:
    project, clip_id, _ = cohost

    with pytest.raises(ProjectError, match="at least two"):
        ops.attribute_speakers(project, clip_id, streams=[0], labels=["ana"])


@needs_ffmpeg
@needs_ffprobe
def test_a_stream_the_container_does_not_have_is_refused(
    cohost: tuple[Path, str, list[str]],
) -> None:
    project, clip_id, _ = cohost

    with pytest.raises(ProjectError, match="numbered 0-1"):
        ops.attribute_speakers(project, clip_id, streams=[0, 5])


@needs_ffmpeg
@needs_ffprobe
def test_a_label_per_mic_or_none_at_all(cohost: tuple[Path, str, list[str]]) -> None:
    project, clip_id, _ = cohost

    with pytest.raises(ProjectError, match="every mic gets exactly one"):
        ops.attribute_speakers(project, clip_id, labels=["ana"])


@needs_ffmpeg
@needs_ffprobe
def test_the_default_labels_are_positional(cohost: tuple[Path, str, list[str]]) -> None:
    project, clip_id, _ = cohost

    report = ops.attribute_speakers(project, clip_id)

    assert report["labels"] == ["speaker1", "speaker2"]
    assert set(report["by_label"]) == {"speaker1", "speaker2"}


@needs_ffprobe
def test_a_one_mic_clip_says_so_rather_than_attributing_nothing(tmp_path: Path) -> None:
    """The refusal names the real situation: there is no local route to speaker
    identity on a mixed track, so this is not a missing flag."""
    project = tmp_path / "proj"
    ops.init(project)
    mono = _mic_wav(tmp_path / "vo.wav", hot_turns={0, 1, 2, 3, 4, 5})
    clip = ops.import_media(project, mono)
    whisper, _ = _transcript_json(tmp_path / "words.json")
    ops.attach_transcript(project, clip["clip_id"], whisper)

    with pytest.raises(ProjectError, match="one audio stream"):
        ops.attribute_speakers(project, clip["clip_id"])


@needs_ffprobe
def test_an_unknown_clip_is_refused_by_name(tmp_path: Path) -> None:
    project = tmp_path / "proj"
    ops.init(project)

    with pytest.raises(ProjectError, match="no clip 'nope'"):
        ops.attribute_speakers(project, "nope")


@needs_ffmpeg
@needs_ffprobe
def test_a_clip_with_no_transcript_is_refused_before_any_decoding(tmp_path: Path) -> None:
    """Decoding two mics of an hour costs minutes; the refusal arrives first."""
    project = tmp_path / "proj"
    ops.init(project)
    clip = ops.import_media(project, _cohost_container(tmp_path), mix=True)

    with pytest.raises(tx.TranscriptError, match="no transcript"):
        ops.attribute_speakers(project, clip["clip_id"])


@needs_ffmpeg
@needs_ffprobe
def test_an_older_record_with_no_stream_count_is_probed(
    cohost: tuple[Path, str, list[str]],
) -> None:
    """`audio_streams` is additive, so a record written before it existed has
    none — and absent must not read as one mic on a two-mic file."""
    project = Project.open(cohost[0])
    manifest: dict[str, Any] = project.read_manifest()
    for clip in manifest["clips"]:
        clip.pop("audio_streams", None)
    project.write_manifest(manifest)

    report = ops.attribute_speakers(project.root, cohost[1])

    assert report["audio_streams"] == 2
    assert report["attributed"] == report["words"]


@needs_ffmpeg
@needs_ffprobe
def test_a_video_container_maps_by_audio_ordinal_not_absolute_index(tmp_path: Path) -> None:
    """The trap every audio-only fixture hides.

    With a picture at stream 0, the first mic is absolute index 1 and the
    second is 2 — which is what MLT's `audio_index` would take — while the
    decode here asks for `-map 0:a:0` and `0:a:1`. Both numberings agree on
    an audio-only file, so the rest of this file cannot tell them apart; a
    container with video can. Read absolutely, stream 0 is the *picture* and
    stream 1 is mic A twice over, which separates nobody.
    """
    project = tmp_path / "proj"
    ops.init(project)
    clip = ops.import_media(project, _cohost_container(tmp_path, video=True), mix=True)
    whisper, truth = _transcript_json(tmp_path / "words.json")
    ops.attach_transcript(project, clip["clip_id"], whisper)

    report = ops.attribute_speakers(project, clip["clip_id"], labels=["ana", "ben"])

    assert report["audio_streams"] == 2, "the video stream is not one of them"
    assert report["attributed"] == len(truth)
    assert report["by_label"] == {"ana": truth.count("ana"), "ben": truth.count("ben")}
