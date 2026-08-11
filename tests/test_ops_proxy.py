"""The preview proxy — PLAN.md § The preview proxy transcode.

Real encodes throughout, following `test_media_playability.py`'s rationale: the
thing under test is whether a file a browser refuses becomes one it accepts,
and only ffprobe reading real bytes can answer that. A stub would pin the
argument list handed to ffmpeg, which is not the claim.

The load-bearing test in this file is not the transcode — it is
`test_export_never_names_the_proxy`. Everything else here would still pass if
the proxy leaked into the render path, and a render silently taken at preview
quality is exactly the failure this design exists to make structurally
impossible.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from lucid import media, ops
from lucid.project import Project

needs_ffmpeg = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg/ffprobe are not installed",
)

pytestmark = needs_ffmpeg


def _needs_encoder(name: str) -> None:
    encoders = subprocess.run(
        ["ffmpeg", "-hide_banner", "-encoders"], capture_output=True, text=True, check=True
    ).stdout
    if f" {name} " not in encoders:
        pytest.skip(f"this ffmpeg has no {name} encoder")


def _encode(path: Path, *args: str, size: str = "1280x960", duration: float = 1.0) -> Path:
    """A real encode from lavfi. 1280x960 by default, deliberately: the proxy
    downscales to 720 tall, so the *height* of a file is enough to say which of
    the two any later step actually read."""
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg", "-y", "-loglevel", "error",
            "-f", "lavfi", "-i", f"testsrc=size={size}:rate=24:duration={duration}",
            "-f", "lavfi", "-i", f"sine=frequency=440:duration={duration}",
            *args, str(path),
        ],
        check=True,
        capture_output=True,
    )  # fmt: skip
    return path


def _hevc_source(tmp_path: Path) -> Path:
    """An `hev1` MP4 — decodable by ffmpeg and melt, black in the preview.

    The exact class the viewer already names and cannot show, and one of the
    three `playability()` refuses that a transcode closes.
    """
    _needs_encoder("libx265")
    return _encode(
        tmp_path / "src" / "hevc.mp4",
        "-c:v", "libx265", "-tag:v", "hev1", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-shortest",
    )  # fmt: skip


def _probe(path: Path) -> dict[str, object]:
    out = subprocess.run(
        [
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=codec_name,width,height,pix_fmt",
            "-of", "json", str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout  # fmt: skip
    return json.loads(out)["streams"][0]


@pytest.fixture
def project_with_hevc(tmp_path: Path) -> tuple[Path, str]:
    source = _hevc_source(tmp_path)
    project_root = tmp_path / "proj"
    ops.init(project_root)
    record = ops.import_media(project_root, source)
    return project_root, record["clip_id"]


# -- the structural rule -------------------------------------------------
#
# The proxy never enters the manifest and `media_path()` gains no branch. The
# first test is cheap and looks almost too trivial to write; it is the one that
# fails if somebody ever "helpfully" folds proxy resolution into the chain that
# `export`, `verify` and `check_frames` all read through.


def test_media_path_ignores_a_proxy_key_entirely(tmp_path: Path) -> None:
    """Not "the manifest has no proxy key" — that is a fact about today's
    writer. This is the stronger claim: even handed a clip dict that *does*
    carry one, `media_path` resolves as though it did not."""
    project_root = tmp_path / "proj"
    ops.init(project_root)
    project = Project.open(project_root)
    clip = {
        "clip_id": "c",
        "source": "/somewhere/original.mkv",
        "proxy": "cache/proxy/c.mp4",
    }

    assert media.media_path(project, clip) == Path("/somewhere/original.mkv")

    clip["media"] = "media/c.mkv"
    assert media.media_path(project, clip) == project_root / "media/c.mkv"

    clip["attenuated"] = "cache/attenuated/c.mkv"
    assert media.media_path(project, clip) == project_root / "cache/attenuated/c.mkv"


def test_export_never_names_the_proxy(project_with_hevc: tuple[Path, str]) -> None:
    """The load-bearing one. With a current proxy sitting in the cache, an
    export must still reference the original — because it resolves through
    `media_path()`, which cannot see a proxy, and never through
    `preview_path()`.

    `attenuate_noises` had the mirror-image bug pointing the other way
    (`to_v3` built "src" from `record["source"]` and skipped `media_path()`
    entirely, so a render carried noise at full volume with `written: true`
    giving no sign). A leak in this direction is worse: it is silently
    delivering a downscaled preview encode as the finished film.

    An NLE export rather than a render, because it names its sources in plain
    text — this reads what the render path *resolved*, not what came out of an
    encoder, so it fails for the right reason.
    """
    project_root, clip_id = project_with_hevc
    ops.seed_timeline(project_root, clip_id=clip_id, remove_silences=False)
    built = ops.proxy_transcode(project_root, clip_id)
    assert built["built"] is True
    proxy = Path(built["proxy"])
    assert proxy.is_file()

    out = project_root / "handoff.kdenlive"
    ops.export(project_root, out, export_format="kdenlive")
    written = out.read_text(encoding="utf-8")

    assert str(proxy) not in written
    assert "cache/proxy" not in written
    # And positively: the file it does name is the one the manifest resolves to.
    project = Project.open(project_root)
    clip = media.get_clip(project, clip_id)
    assert str(media.media_path(project, clip)) in written


def test_preview_path_prefers_the_proxy_and_media_path_does_not(
    project_with_hevc: tuple[Path, str],
) -> None:
    """The two resolvers, side by side on one clip — which is the whole design
    in a single assertion pair."""
    project_root, clip_id = project_with_hevc
    project = Project.open(project_root)
    clip = media.get_clip(project, clip_id)

    assert media.preview_path(project, clip) == media.media_path(project, clip)

    ops.proxy_transcode(project_root, clip_id)

    assert media.preview_path(project, clip) == project.proxy_path(clip_id)
    assert media.media_path(project, clip) != project.proxy_path(clip_id)


# -- the cache key -------------------------------------------------------


def test_a_stale_proxy_is_treated_as_no_proxy(project_with_hevc: tuple[Path, str]) -> None:
    """Serving the previous cut of a re-imported clip is the one wrong answer
    that looks right, so invalidation falls back rather than raising."""
    project_root, clip_id = project_with_hevc
    ops.proxy_transcode(project_root, clip_id)
    project = Project.open(project_root)
    clip = media.get_clip(project, clip_id)
    assert media.proxy_is_current(project, clip) is True

    # Re-write the source: same path, different bytes — what a re-import or
    # `attenuate_noises` does, and exactly what size+mtime is keyed to catch.
    source = media.media_path(project, clip).resolve()
    _encode(source, "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest")

    assert media.proxy_is_current(project, clip) is False
    assert media.preview_path(project, clip) == media.media_path(project, clip)


def test_a_proxy_with_no_sidecar_is_not_current(project_with_hevc: tuple[Path, str]) -> None:
    """The key is written only after ffmpeg returns, so an interrupted job
    leaves a file with no sidecar. It must read as no proxy, not as a good
    one — this is what makes cancelling a `ProxyJob` safe by construction
    rather than by handling."""
    project_root, clip_id = project_with_hevc
    ops.proxy_transcode(project_root, clip_id)
    project = Project.open(project_root)
    project.proxy_key_path(clip_id).unlink()

    clip = media.get_clip(project, clip_id)
    assert media.proxy_is_current(project, clip) is False


def test_a_second_call_reuses_the_proxy_and_force_rebuilds(
    project_with_hevc: tuple[Path, str],
) -> None:
    project_root, clip_id = project_with_hevc
    first = ops.proxy_transcode(project_root, clip_id)
    assert first["built"] is True

    again = ops.proxy_transcode(project_root, clip_id)
    assert again["built"] is False
    assert again["proxy"] == first["proxy"]

    forced = ops.proxy_transcode(project_root, clip_id, force=True)
    assert forced["built"] is True


# -- what a transcode does, and what it refuses --------------------------


def test_the_proxy_is_playable_and_downscaled(project_with_hevc: tuple[Path, str]) -> None:
    """Read back off the finished file, never assumed from the flags handed to
    ffmpeg — the same discipline every render check in this repo follows."""
    project_root, clip_id = project_with_hevc
    project = Project.open(project_root)
    source = media.media_path(project, media.get_clip(project, clip_id))
    assert media.playability(source)["playable"] is False

    result = ops.proxy_transcode(project_root, clip_id)

    assert result["playable"]["playable"] is True
    stream = _probe(Path(result["proxy"]))
    assert stream["codec_name"] == "h264"
    assert stream["pix_fmt"] == "yuv420p"
    assert stream["height"] == media.PROXY_HEIGHT
    # Even dimensions, because an odd width is a hard x264 error rather than a
    # rounded one — which is why the filter says `scale=-2:`, not `-1:`.
    assert int(stream["width"]) % 2 == 0


def test_a_ten_bit_source_is_closed_too(tmp_path: Path) -> None:
    """The pixel-format refusal class, which is a separate gate from the codec
    name and not implied by it (`media._PLAYABLE_PIX`)."""
    source = _encode(
        tmp_path / "src" / "high10.mp4",
        "-c:v", "libx264", "-profile:v", "high10", "-pix_fmt", "yuv420p10le",
        "-c:a", "aac", "-shortest",
    )  # fmt: skip
    assert media.playability(source)["playable"] is False

    project_root = tmp_path / "proj"
    ops.init(project_root)
    clip_id = ops.import_media(project_root, source)["clip_id"]

    result = ops.proxy_transcode(project_root, clip_id)

    assert result["playable"]["playable"] is True
    assert _probe(Path(result["proxy"]))["pix_fmt"] == "yuv420p"


def test_an_already_small_source_is_never_upscaled(tmp_path: Path) -> None:
    """`min(ih,720)`, not a flat 720: a proxy larger than the file it stands in
    for is pure cost, and it would make `cache/proxy/` bigger than the media."""
    source = _encode(
        tmp_path / "src" / "small.mp4",
        "-c:v", "libx265", "-tag:v", "hev1", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-shortest",
        size="320x240",
    )  # fmt: skip
    _needs_encoder("libx265")
    project_root = tmp_path / "proj"
    ops.init(project_root)
    clip_id = ops.import_media(project_root, source)["clip_id"]

    result = ops.proxy_transcode(project_root, clip_id)

    assert _probe(Path(result["proxy"]))["height"] == 240


def test_a_playable_clip_is_refused(tmp_path: Path) -> None:
    """A proxy of a file the browser opens directly is a second, lower-quality
    copy of footage nothing needed a copy of. `force` overrides the cache, not
    this judgement."""
    source = _encode(
        tmp_path / "src" / "fine.mp4",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
    )  # fmt: skip
    project_root = tmp_path / "proj"
    ops.init(project_root)
    clip_id = ops.import_media(project_root, source)["clip_id"]

    with pytest.raises(Exception, match="already plays"):
        ops.proxy_transcode(project_root, clip_id)
    with pytest.raises(Exception, match="already plays"):
        ops.proxy_transcode(project_root, clip_id, force=True)

    assert not Project.open(project_root).proxy_path(clip_id).is_file()


def test_preview_source_reports_the_proxy(project_with_hevc: tuple[Path, str]) -> None:
    """`ops.preview_source` is one of the two callers allowed to resolve through
    `preview_path`, and it is what the viewer's `/api/preview/<asset>` reads —
    so an asset that was black and named its reason now plays and says so."""
    project_root, clip_id = project_with_hevc
    before = ops.preview_source(project_root, clip_id)
    assert before["playable"] is False
    assert before["reason"]

    ops.proxy_transcode(project_root, clip_id)
    after = ops.preview_source(project_root, clip_id)

    assert after["playable"] is True
    assert after["reason"] is None
    assert after["path"] == str(Project.open(project_root).proxy_path(clip_id))
