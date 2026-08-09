"""Probing and registering source media.

`ffprobe` is the only thing that reads media metadata here — lucid never
guesses fps or duration from a filename or a container assumption.

Imported media is *linked*, not copied, by default: `media/<clip_id><ext>` is a
symlink to wherever the file actually lives. A 74 MB VO on the NAS should not
be duplicated to be edited, and a broken symlink is a visible failure rather
than a silently wrong path. `copy=True` takes a real copy when the source is
somewhere that will not survive.

Not every filesystem cooperates — see `_place`. Read paths through
`media_path()` rather than assuming a `media/` entry exists.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from lucid.project import Project

FFPROBE = "ffprobe"


class MediaError(Exception):
    """Raised when media cannot be probed or registered."""


@dataclass(frozen=True)
class MediaInfo:
    """What ffprobe knows about one file."""

    duration: float
    has_video: bool
    has_audio: bool
    fps: float | None
    width: int | None
    height: int | None
    sample_rate: int | None
    channels: int | None
    video_codec: str | None
    audio_codec: str | None
    #: r_frame_rate disagrees with avg_frame_rate. See PLAN.md — recorded, not
    #: acted on: cut-and-concat works in the time domain where VFR is mostly
    #: fine, so normalising is deferred to NLE export.
    vfr: bool

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _fraction(value: str | None) -> float | None:
    """Parse ffprobe's "30000/1001" rate strings. Returns None for 0/0."""
    if not value or "/" not in value:
        return None
    num, _, den = value.partition("/")
    try:
        n, d = float(num), float(den)
    except ValueError:
        return None
    return n / d if d else None


def _ffprobe(media: Path, *args: str) -> dict[str, Any]:
    """One ffprobe invocation, with the two ways it can fail spelled out."""
    cmd = [FFPROBE, "-v", "error", "-print_format", "json", *args, str(media)]
    try:
        completed = subprocess.run(cmd, capture_output=True, text=True, check=True)
    except FileNotFoundError as exc:
        raise MediaError(f"{FFPROBE} not found on PATH") from exc
    except subprocess.CalledProcessError as exc:
        raise MediaError(f"ffprobe failed on {media}: {exc.stderr.strip()}") from exc
    return json.loads(completed.stdout)


def probe(path: Path | str) -> MediaInfo:
    """Run ffprobe against `path` and summarise its first video/audio stream."""
    media = Path(path).expanduser()
    if not media.exists():
        raise MediaError(f"no such media file: {media}")

    payload = _ffprobe(media, "-show_format", "-show_streams")
    streams = payload.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)

    duration = payload.get("format", {}).get("duration")
    if duration is None:
        # Some containers only carry duration per-stream.
        duration = (video or audio or {}).get("duration")
    if duration is None:
        raise MediaError(f"ffprobe reported no duration for {media}")

    fps = avg = None
    if video is not None:
        fps = _fraction(video.get("r_frame_rate"))
        avg = _fraction(video.get("avg_frame_rate"))

    return MediaInfo(
        duration=float(duration),
        has_video=video is not None,
        has_audio=audio is not None,
        fps=fps,
        width=video.get("width") if video else None,
        height=video.get("height") if video else None,
        sample_rate=int(audio["sample_rate"]) if audio and audio.get("sample_rate") else None,
        channels=audio.get("channels") if audio else None,
        video_codec=video.get("codec_name") if video else None,
        audio_codec=audio.get("codec_name") if audio else None,
        # A 1% tolerance: 30000/1001 vs 29.97 is rounding, not variability.
        vfr=bool(fps and avg and abs(fps - avg) / fps > 0.01),
    )


def count_frames(path: Path | str) -> dict[str, Any]:
    """Count a render's video frames, exactly enough to compare one against.

    `probe`'s `nb_frames` is read out of the container header, and a muxer is
    free to write it wrong or leave it out — which is no basis for a check
    whose entire value is that the number is exact. `-count_packets` walks the
    stream instead. For one-frame-per-packet video that is exact, and unlike
    `-count_frames` it never decodes a pixel.

    Both numbers come back, and a disagreement between them is reported rather
    than resolved here: two ffprobe readings of the same file differing is
    itself a finding, and picking the nicer one would bury it.

    `frames` is None when there is no video stream at all. An audio-only render
    is the ordinary case for a VO project, not an error — see `ops.check_frames`.
    """
    media = Path(path).expanduser()
    if not media.exists():
        raise MediaError(f"no such media file: {media}")

    payload = _ffprobe(
        media,
        "-select_streams",
        "v:0",
        "-count_packets",
        "-show_entries",
        "stream=nb_read_packets,nb_frames:format=duration",
        "-show_format",
    )
    streams = payload.get("streams", [])
    duration = payload.get("format", {}).get("duration")

    def _count(value: Any) -> int | None:
        return int(value) if value is not None and str(value).isdigit() else None

    if not streams:
        return {
            "frames": None,
            "container_frames": None,
            "duration": float(duration) if duration is not None else None,
            "has_video": False,
        }
    return {
        "frames": _count(streams[0].get("nb_read_packets")),
        "container_frames": _count(streams[0].get("nb_frames")),
        "duration": float(duration) if duration is not None else None,
        "has_video": True,
    }


# -- what a browser will actually play ------------------------------------
#
# The preview pane is a <video> element, so "can this be edited" and "can this
# be *watched in the window*" are different questions and only ffprobe can tell
# them apart. Every set below is the intersection that holds for the browsers
# `lucid web` is used from on this box (Chromium and Firefox on Linux), which
# is narrower than the spec and narrower than Safari — an `hvc1`-tagged HEVC
# plays on iOS and not here (wiki `home.md`).
_PLAYABLE_VIDEO = frozenset({"h264", "vp8", "vp9", "av1", "theora"})
_PLAYABLE_AUDIO = frozenset({"aac", "mp3", "opus", "vorbis", "flac", "pcm_s16le", "pcm_u8"})
#: 10-bit and 4:2:2 decode in ffmpeg and not in a browser's H.264 decoder, so
#: the pixel format is a separate gate from the codec name and not implied by it.
_PLAYABLE_PIX = frozenset({"yuv420p", "yuvj420p"})
_PLAYABLE_CONTAINER = frozenset(
    {".mp4", ".m4v", ".mov", ".webm", ".ogg", ".ogv", ".oga", ".mp3", ".m4a", ".wav", ".flac"}
)


def playability(path: Path | str) -> dict[str, Any]:
    """Can a browser play this file, and if not, name the reason.

    Answers the question the preview pane fails at silently: a `<video>` whose
    source it cannot decode fires one contentless `error` event and shows black,
    which is indistinguishable from a correct black frame in the edit. So the
    reason is worked out here, on the box that has ffprobe, and reported as
    words a person can act on rather than inferred in JS from an empty event.

    Only ever consulted *about* the preview — no render path reads it, because
    ffmpeg and melt decode everything in this list and a good deal more. A file
    this call refuses still exports correctly.

    `{"playable": bool, "reason": str | None, ...}` plus the four fields the
    verdict was reached on, so a surprising answer can be checked against what
    was actually measured rather than re-probed by hand.
    """
    media = Path(path).expanduser()
    if not media.exists():
        raise MediaError(f"no such media file: {media}")

    payload = _ffprobe(
        media,
        "-show_entries",
        "stream=codec_type,codec_name,codec_tag_string,profile,pix_fmt",
        "-show_streams",
    )
    streams = payload.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)

    measured: dict[str, Any] = {
        "container": media.suffix.lower(),
        "video_codec": video.get("codec_name") if video else None,
        "video_tag": video.get("codec_tag_string") if video else None,
        "profile": video.get("profile") if video else None,
        "pix_fmt": video.get("pix_fmt") if video else None,
        "audio_codec": audio.get("codec_name") if audio else None,
    }

    def verdict(reason: str | None) -> dict[str, Any]:
        return {"playable": reason is None, "reason": reason, **measured}

    if media.suffix.lower() not in _PLAYABLE_CONTAINER:
        return verdict(f"{media.suffix or 'this'} is not a container browsers open")
    if video is None and audio is None:
        return verdict("this file has neither a video nor an audio stream")
    if video is not None:
        codec = video.get("codec_name")
        if codec not in _PLAYABLE_VIDEO:
            tag = video.get("codec_tag_string")
            tagged = f" (tagged {tag})" if tag else ""
            return verdict(f"video codec {codec}{tagged} is not decodable in a browser here")
        pix = video.get("pix_fmt")
        if pix not in _PLAYABLE_PIX:
            profile = video.get("profile") or codec
            return verdict(f"{profile} at {pix} is beyond a browser's 8-bit 4:2:0 decoder")
    if audio is not None and audio.get("codec_name") not in _PLAYABLE_AUDIO:
        return verdict(f"audio codec {audio.get('codec_name')} is not decodable in a browser here")
    return verdict(None)


def slugify(name: str) -> str:
    """Turn a filename into a clip_id candidate: lowercase, dashes, no cruft."""
    stem = Path(name).stem.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", stem).strip("-")
    return slug or "clip"


def _unique_clip_id(candidate: str, taken: set[str]) -> str:
    if candidate not in taken:
        return candidate
    n = 2
    while f"{candidate}-{n}" in taken:
        n += 1
    return f"{candidate}-{n}"


def import_media(
    project: Project,
    path: Path | str,
    *,
    clip_id: str | None = None,
    copy: bool = False,
) -> dict[str, Any]:
    """Probe `path`, link it into the project, and record it in the manifest.

    Returns the clip record. Re-importing the same source path is a no-op that
    returns the existing record, so an agent retrying a call cannot silently
    register the same media twice under two ids.
    """
    source = Path(path).expanduser().resolve()
    info = probe(source)

    manifest = project.read_manifest()
    clips: list[dict[str, Any]] = manifest.setdefault("clips", [])

    existing = next((c for c in clips if c["source"] == str(source)), None)
    if existing is not None:
        return existing

    taken = {c["clip_id"] for c in clips}
    if clip_id is None:
        clip_id = _unique_clip_id(slugify(source.name), taken)
    elif clip_id in taken:
        raise MediaError(f"clip_id {clip_id!r} is already registered in this project")

    record: dict[str, Any] = {"clip_id": clip_id, "source": str(source)}
    record.update(_place(project, source, clip_id, copy=copy))
    record.update(info.as_dict())

    clips.append(record)
    project.write_manifest(manifest)
    return record


def _place(project: Project, source: Path, clip_id: str, *, copy: bool) -> dict[str, Any]:
    """Give the clip an entry under `media/`, if the filesystem allows one.

    SMB/CIFS shares reject `symlink()` outright with EOPNOTSUPP, and the NAS
    this is used against is one — so the link is best-effort. Falling back to a
    *copy* would be worse than useless: it silently duplicates gigabytes of
    source footage to work around a filesystem limitation. Reference the file
    where it lies instead, and record which of the three happened.
    """
    project.media_dir.mkdir(parents=True, exist_ok=True)
    local = project.media_dir / f"{clip_id}{source.suffix}"
    if local.exists() or local.is_symlink():
        local.unlink()

    if copy:
        shutil.copy2(source, local)
        return {"media": str(local.relative_to(project.root)), "link": "copy"}

    try:
        local.symlink_to(source)
    except OSError:
        # Nothing under media/ for this clip; `media_path` falls back to source.
        return {"link": "reference"}
    return {"media": str(local.relative_to(project.root)), "link": "symlink"}


def get_clip(project: Project, clip_id: str) -> dict[str, Any]:
    """Look up a registered clip, or explain which ids do exist."""
    clips = project.read_manifest().get("clips", [])
    for clip in clips:
        if clip["clip_id"] == clip_id:
            return clip
    known = ", ".join(c["clip_id"] for c in clips) or "none"
    raise MediaError(f"no clip {clip_id!r} in this project (registered: {known})")


def media_path(project: Project, clip: dict[str, Any]) -> Path:
    """The path tools should hand to ffmpeg/auto-editor for this clip.

    The `attenuated` entry when `attenuate_noises` has produced one, else the
    `media/` entry, else the original source when the filesystem would not
    take a symlink. Preferring `attenuated` here — rather than threading a
    "use the calm copy" flag through every caller — is what makes attenuation
    transparent to every downstream op (seed/cut/export/verify) for free.
    """
    local = clip.get("attenuated") or clip.get("media")
    return (project.root / local) if local else Path(clip["source"])


def original_media_path(project: Project, clip: dict[str, Any]) -> Path:
    """What `media_path()` resolved to before `attenuate_noises` ever ran.

    `attenuate_noises` always reads from here, never from `media_path()`, so a
    second call cannot attenuate an already-attenuated file — every run is a
    clean rebuild from the untouched original, not a compounding one.
    """
    local = clip.get("media")
    return (project.root / local) if local else Path(clip["source"])
