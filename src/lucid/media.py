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


def probe(path: Path | str) -> MediaInfo:
    """Run ffprobe against `path` and summarise its first video/audio stream."""
    media = Path(path).expanduser()
    if not media.exists():
        raise MediaError(f"no such media file: {media}")

    cmd = [
        FFPROBE,
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(media),
    ]
    try:
        completed = subprocess.run(cmd, capture_output=True, text=True, check=True)
    except FileNotFoundError as exc:
        raise MediaError(f"{FFPROBE} not found on PATH") from exc
    except subprocess.CalledProcessError as exc:
        raise MediaError(f"ffprobe failed on {media}: {exc.stderr.strip()}") from exc

    payload = json.loads(completed.stdout)
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

    The `media/` entry when there is one, and the original source when the
    filesystem would not take a symlink.
    """
    local = clip.get("media")
    return (project.root / local) if local else Path(clip["source"])
