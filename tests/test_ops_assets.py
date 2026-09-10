"""`ops.info`, `ops.clip_role`, `ops.assets`, `ops.properties`, `ops.thumbnail`.

The backend half of the three remaining parity items (docs/plans/DAYDREAM.md § Import
roles + assets pane, § Properties pane): an assets catalogue that lists both
halves of the cue vocabulary, a properties composer, and a cached filmstrip
frame primitive. Real ffmpeg/ffprobe throughout, following the rest of the
suite's rationale in test_ops_waveform.py and test_ops_proxy.py: the claims
under test are about real probed metadata and real cached bytes, not about
argument lists handed to a stub.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from lucid import media, ops, picture
from lucid.project import Project

needs_ffmpeg = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg/ffprobe are not installed",
)

needs_magick = pytest.mark.skipif(
    shutil.which("magick") is None, reason="ImageMagick is not installed"
)

pytestmark = needs_ffmpeg


def _encode_video(path: Path, *, size: str = "320x240", duration: float = 5.0) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg", "-y", "-loglevel", "error",
            "-f", "lavfi", "-i", f"testsrc=size={size}:rate=24:duration={duration}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ],
        check=True,
        capture_output=True,
    )  # fmt: skip
    return path


def _encode_audio(path: Path, *, duration: float = 6.0) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg", "-y", "-loglevel", "error",
            "-f", "lavfi", "-i", f"sine=frequency=440:duration={duration}",
            str(path),
        ],
        check=True,
        capture_output=True,
    )  # fmt: skip
    return path


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """One video clip (`vid`, 5s, no audio track) and one voiceover clip
    (`vo`, 6s, transcribed, seeded, with one cue at word 2 pointing at `vid`).
    """
    root = tmp_path / "proj"
    ops.init(root)

    video = _encode_video(tmp_path / "src" / "vid.mp4")
    ops.import_media(root, video, clip_id="vid")

    audio = _encode_audio(tmp_path / "src" / "vo.wav")
    ops.import_media(root, audio, clip_id="vo")

    words = [{"word": f"w{n}", "start": float(n), "end": n + 0.9} for n in range(6)]
    transcript = tmp_path / "vo.json"
    transcript.write_text(json.dumps({"language": "en", "words": words}), encoding="utf-8")
    ops.attach_transcript(root, "vo", transcript)
    ops.seed_timeline(root, "vo", remove_silences=False)
    ops.cue_add(root, "vo", 2, "vid")
    return root


# -- info -------------------------------------------------------------------


def test_info_matches_the_manifest_when_there_are_no_descriptions(project: Path) -> None:
    result = ops.info(project)
    assert result == Project.open(project).read_manifest()


def test_info_stands_descriptions_down_to_a_count(project: Path) -> None:
    manifest = Project.open(project).read_manifest()
    manifest["descriptions"] = [
        {"clip_id": "vid", "window_start": 0.0, "window_end": 1.0, "text": "x" * 5000},
        {"clip_id": "vid", "window_start": 1.0, "window_end": 2.0, "text": "y" * 5000},
    ]
    Project.open(project).write_manifest(manifest)

    result = ops.info(project)
    assert result["descriptions"]["count"] == 2
    assert result["descriptions"]["clips"] == {"vid": 2}
    assert "x" * 5000 not in json.dumps(result)

    raw = ops.info(project, raw=True)
    assert raw["descriptions"] == manifest["descriptions"]


# -- clip_role ----------------------------------------------------------------


def test_role_is_absent_by_default(project: Path) -> None:
    result = ops.clip_role(project, "vid")
    assert result == {"clip_id": "vid", "role": None, "written": False, "reset": False}


def test_setting_a_role_persists_it(project: Path) -> None:
    written = ops.clip_role(project, "vid", "footage")
    assert written == {"clip_id": "vid", "role": "footage", "written": True, "reset": False}

    again = ops.clip_role(project, "vid")
    assert again["role"] == "footage"
    assert again["written"] is False, "a bare read must not write"


def test_reset_clears_a_role_back_to_absent(project: Path) -> None:
    ops.clip_role(project, "vid", "footage")
    result = ops.clip_role(project, "vid", reset=True)
    assert result["role"] is None
    assert ops.clip_role(project, "vid")["role"] is None


def test_an_unknown_role_is_refused(project: Path) -> None:
    with pytest.raises(ops.ProjectError, match="voiceover|footage"):
        ops.clip_role(project, "vid", "b-roll")


def test_role_and_reset_together_is_refused(project: Path) -> None:
    with pytest.raises(ops.ProjectError, match="reset"):
        ops.clip_role(project, "vid", "footage", reset=True)


def test_an_unknown_clip_is_refused_by_name(project: Path) -> None:
    with pytest.raises(media.MediaError, match="nope"):
        ops.clip_role(project, "nope", "footage")


def test_setting_a_role_does_not_touch_describe_eligibility(project: Path) -> None:
    """CLAUDE.md: absent means undeclared, not "neither" — and setting a role
    changes no other op's gate. `describe`'s own eligibility check
    (`ops._describable`) still gates on `has_video` alone, never on `role`.
    Exercised at the gate directly rather than through the full `describe`
    pipeline, which needs a real vision-model subprocess this suite does not
    configure (CLAUDE.md § `describe`'s vision model)."""
    project_obj = Project.open(project)
    ops.clip_role(project, "vo", "footage")  # a deliberately "wrong" role
    with pytest.raises(ops.ProjectError, match="no video track"):
        ops._describable(project_obj, "vo")
    # `vid` has no role declared and the gate must not care.
    assert ops._describable(project_obj, "vid")[0]["clip_id"] == "vid"


# -- assets -------------------------------------------------------------------


def test_assets_lists_both_clips_with_probe_metadata_and_playability(project: Path) -> None:
    result = ops.assets(project)
    by_id = {c["clip_id"]: c for c in result["clips"]}
    assert set(by_id) == {"vid", "vo"}

    vid = by_id["vid"]
    assert vid["kind"] == "clip"
    assert vid["has_video"] is True
    assert vid["media_exists"] is True
    assert vid["role"] is None
    assert vid["transcript"] is False
    assert vid["described"] is False
    assert vid["cues"] == 1, "the cue_add fixture points a cue at vid"
    assert vid["playable"]["playable"] is True
    assert vid["playable"]["video_codec"] == "h264"
    assert vid["media_path"] == str(media.media_path(Project.open(project), media.get_clip(Project.open(project), "vid")))

    vo = by_id["vo"]
    assert vo["has_audio"] is True
    assert vo["transcript"] is True
    assert vo["cues"] == 0, "no cue points at the VO clip itself"


def test_assets_reports_role_once_set(project: Path) -> None:
    ops.clip_role(project, "vid", "footage")
    result = ops.assets(project)
    vid = next(c for c in result["clips"] if c["clip_id"] == "vid")
    assert vid["role"] == "footage"


def test_a_missing_media_file_reports_playable_null_not_a_crash(project: Path) -> None:
    project_obj = Project.open(project)
    source = media.media_path(project_obj, media.get_clip(project_obj, "vid"))
    source.unlink()

    result = ops.assets(project)
    vid = next(c for c in result["clips"] if c["clip_id"] == "vid")
    assert vid["media_exists"] is False
    assert vid["playable"] is None, "missing is a different claim than unplayable"


@needs_magick
def test_assets_lists_a_recorded_card_with_usage_count(project: Path) -> None:
    ops.card_new(project, "outro", "endcard", {})
    ops.cue_add(project, "vo", 4, "card:outro")

    result = ops.assets(project)
    cards = {c["name"]: c for c in result["cards"]}
    assert cards["outro"]["kind"] == "card"
    assert cards["outro"]["asset"] == "card:outro"
    assert cards["outro"]["template"] == "endcard"
    assert cards["outro"]["files_exist"] is True
    assert cards["outro"]["recorded"] is True
    assert cards["outro"]["cues"] == 1


def test_a_card_with_files_and_no_record_is_reported_not_guessed(project: Path) -> None:
    """CLAUDE.md: a card with files and no record cannot be re-authored by
    anything, and this is where that is reported."""
    cards_dir = Project.open(project).cards_dir
    cards_dir.mkdir(parents=True, exist_ok=True)
    (cards_dir / "orphan.png").write_bytes(b"\x89PNG\r\n\x1a\nfake")

    result = ops.assets(project)
    orphan = next(c for c in result["cards"] if c["name"] == "orphan")
    assert orphan["files_exist"] is True
    assert orphan["recorded"] is False
    assert orphan["template"] is None


@needs_magick
def test_a_recorded_card_with_no_files_is_also_reported(project: Path) -> None:
    ops.card_new(project, "outro", "endcard", {})
    cards_dir = Project.open(project).cards_dir
    (cards_dir / "outro.svg").unlink()
    (cards_dir / "outro.png").unlink()

    result = ops.assets(project)
    outro = next(c for c in result["cards"] if c["name"] == "outro")
    assert outro["files_exist"] is False
    assert outro["recorded"] is True


# -- properties -----------------------------------------------------------


def test_properties_with_no_selection_is_project_state_only(project: Path) -> None:
    result = ops.properties(project)
    assert set(result) == {"status", "canvas", "caption_style"}
    assert result["status"] == ops.status(project)
    assert result["canvas"] == ops.canvas(project)


def test_properties_with_a_clip_adds_its_assets_reframe_and_cues(project: Path) -> None:
    result = ops.properties(project, clip_id="vid")
    assert result["clip"]["clip_id"] == "vid"
    assert result["reframe"]["clip_id"] == "vid"
    assert result["cues"] == ops.cue_ls(project, clip_id="vid")["cues"]
    assert "cue" not in result, "no word_index was given"


def test_properties_with_a_word_index_finds_its_cue(project: Path) -> None:
    result = ops.properties(project, clip_id="vo", word_index=2)
    assert result["cue"]["word_index"] == 2
    assert result["cue"]["asset"] == "vid"
    assert "context" not in result, "the cue's own entry already carries context"


def test_properties_with_an_uncued_word_falls_back_to_context(project: Path) -> None:
    result = ops.properties(project, clip_id="vo", word_index=0)
    assert result["cue"] is None
    assert result["context"]["text"] == "w0 w1 w2 w3"


def test_word_index_without_clip_id_is_refused(project: Path) -> None:
    with pytest.raises(ops.ProjectError, match="clip_id"):
        ops.properties(project, word_index=0)


def test_negative_word_index_is_refused_not_silently_widened(project: Path) -> None:
    """A negative `word_index` must not reach `get_transcript` — `hi =
    word_index + 3` stays negative there and a negative slice bound counts
    from the end of the transcript, so word -100 used to return most of a
    1150-word VO as its 'three words either side' context."""
    with pytest.raises(ops.ProjectError, match="out of range"):
        ops.properties(project, clip_id="vo", word_index=-100)


def test_out_of_range_positive_word_index_is_refused(project: Path) -> None:
    with pytest.raises(ops.ProjectError, match="out of range"):
        ops.properties(project, clip_id="vo", word_index=99)


def test_properties_composes_rather_than_reimplements(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every field must come from calling the real op, not from a parallel
    read of the manifest — proved by making the real op lie and checking the
    lie shows up here too."""
    real_canvas = ops.canvas

    def _lying_canvas(path: object, **kwargs: object) -> dict[str, object]:
        result = real_canvas(path, **kwargs)  # type: ignore[arg-type]
        return {**result, "canvas": "9999x9999"}

    monkeypatch.setattr(ops, "canvas", _lying_canvas)
    assert ops.properties(project)["canvas"]["canvas"] == "9999x9999"


# -- thumbnail --------------------------------------------------------------


def test_thumbnail_writes_a_real_jpeg_under_cache_thumbs(project: Path) -> None:
    result = ops.thumbnail(project, "vid", 2.3)
    assert result["clip_id"] == "vid"
    assert result["src_time"] == pytest.approx(2.0)
    assert result["cached"] is False
    frame = Path(result["path"])
    assert frame.is_file()
    assert frame.parent == Project.open(project).root / "cache" / "thumbs" / "vid"
    assert frame.read_bytes()[:3] == b"\xff\xd8\xff", "a JPEG SOI marker"


def test_a_nearby_request_reuses_the_same_bucket(project: Path) -> None:
    first = ops.thumbnail(project, "vid", 2.3)
    assert first["cached"] is False

    second = ops.thumbnail(project, "vid", 2.4)
    assert second["path"] == first["path"]
    assert second["cached"] is True


def test_a_cache_hit_never_calls_extract_frame(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ops.thumbnail(project, "vid", 2.3)

    def _must_not_run(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("picture.extract_frame must not run on a cache hit")

    monkeypatch.setattr(picture, "extract_frame", _must_not_run)
    ops.thumbnail(project, "vid", 2.4)


def test_a_changed_media_file_invalidates_the_cache(project: Path) -> None:
    project_obj = Project.open(project)
    source = media.media_path(project_obj, media.get_clip(project_obj, "vid"))

    first = ops.thumbnail(project, "vid", 2.0)
    first_bytes = Path(first["path"]).read_bytes()

    _encode_video(source, size="640x480", duration=5.0)  # same path, re-encoded
    second = ops.thumbnail(project, "vid", 2.0)
    assert second["cached"] is False
    assert Path(second["path"]).read_bytes() != first_bytes


def test_different_intervals_snap_to_different_buckets(project: Path) -> None:
    coarse = ops.thumbnail(project, "vid", 2.3, interval=2.0)
    assert coarse["src_time"] == pytest.approx(2.0)
    fine = ops.thumbnail(project, "vid", 2.3, interval=0.5)
    assert fine["src_time"] == pytest.approx(2.5)


def test_a_non_positive_interval_is_refused(project: Path) -> None:
    with pytest.raises(ops.ProjectError, match="positive"):
        ops.thumbnail(project, "vid", 2.0, interval=0.0)


def test_an_audio_only_clip_is_refused(project: Path) -> None:
    with pytest.raises(ops.ProjectError, match="no video track"):
        ops.thumbnail(project, "vo", 1.0)


def test_missing_media_is_refused(project: Path) -> None:
    project_obj = Project.open(project)
    source = media.media_path(project_obj, media.get_clip(project_obj, "vid"))
    source.unlink()
    with pytest.raises(ops.ProjectError, match="missing from disk"):
        ops.thumbnail(project, "vid", 1.0)


def test_a_request_past_the_end_is_clamped_rather_than_refused(project: Path) -> None:
    result = ops.thumbnail(project, "vid", 999.0)
    assert result["src_time"] < 5.0
    assert Path(result["path"]).is_file()


def test_thumbnail_never_enters_the_manifest_or_a_media_resolver(project: Path) -> None:
    """The containment rule: a thumbnail is a preview artifact, never
    reachable as source media (CLAUDE.md, `media.preview_path`'s own split)."""
    result = ops.thumbnail(project, "vid", 2.0)
    frame = Path(result["path"])

    manifest = Project.open(project).read_manifest()
    manifest_text = json.dumps(manifest)
    assert frame.name not in manifest_text
    assert str(frame) not in manifest_text
    assert "cache/thumbs" not in manifest_text

    project_obj = Project.open(project)
    clip = media.get_clip(project_obj, "vid")
    assert media.media_path(project_obj, clip) != frame
    assert media.preview_path(project_obj, clip) != frame
