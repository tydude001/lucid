"""`export` on a multi-source timeline — step 4 of the layered timeline.

The routing is the point. auto-editor 31.x refuses to *export* a second `src`
(exit 2) and *renders* one at 720x576 while exiting 0, so a project that has
grown a picture lane must never reach it — and the choice cannot be a flag,
because a flag can be left off. These tests are about which writer runs, and
about the frame grid the two halves of the document are quantised on.

The document's own structure is `test_mlt.py`; what melt does with it is
HISTORY.md § The MLT writer, measured against a real render rather than
asserted here (melt lives in a flatpak that cannot read `tmp_path`).
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import pytest

from lucid import autoeditor, mlt, ops, picture
from lucid import timeline as tl
from lucid import transcript as tx
from lucid.project import Project, ProjectError

EXPORT_FPS = 30.0


@pytest.fixture
def project(tmp_path: Path) -> Project:
    """An audio-only VO cut to [0, 2) and [3, 6) — 5s of timeline — plus a
    video clip and a card to lay over it.

    The project timebase is milliseconds, which is the whole reason the export
    has to state its own rate: `build_shots` answers on the project's grid by
    default, and 1000 is not a frame rate.
    """
    project = Project.create(tmp_path / "proj")

    film = tmp_path / "film.mp4"
    film.write_bytes(b"not really a video, just needs to exist")

    manifest = project.read_manifest()
    manifest["clips"] = [
        {
            "clip_id": "vo",
            "source": str(tmp_path / "vo.wav"),
            "duration": 6.0,
            "has_video": False,
            "has_audio": True,
        },
        {
            "clip_id": "film",
            "source": str(film),
            "duration": 10.0,
            "has_video": True,
            "has_audio": True,
        },
    ]
    manifest["timebase"] = 1000.0
    project.write_manifest(manifest)

    edit = tl.Edit([tl.Segment("vo", 0.0, 2.0), tl.Segment("vo", 3.0, 6.0)])
    tl.write(
        tl.to_otio(edit, {c["clip_id"]: c for c in manifest["clips"]}, rate=1000.0, name="proj"),
        project.timeline_path,
    )

    tx.save(
        tx.Transcript(
            clip_id="vo",
            words=tuple(
                tx.Word(index=i, text=text, start=start, end=end)
                for i, (text, start, end) in enumerate(
                    [("one", 0.2, 0.5), ("two", 1.2, 1.5), ("three", 3.4, 3.7), ("four", 4.6, 4.9)]
                )
            ),
        ),
        project.transcript_path("vo"),
    )

    project.cards_dir.joinpath("red.png").write_bytes(b"\x89PNG")
    return project


def _document(path: Path) -> ET.Element:
    return ET.fromstring(path.read_text(encoding="utf-8"))


def _declared(path: Path) -> int:
    """What a stand-in melt would report for a document: its own declared
    length. `mlt.declared_frames` has already refused a document whose spots
    disagree, so there is exactly one number to read back."""
    return next(iter(set(mlt.declared_frames(_document(path)).values())))


def test_a_cue_table_routes_the_export_through_the_mlt_writer(
    project: Project, tmp_path: Path
) -> None:
    ops.cue_add(project.root, "vo", 0, "film")
    ops.cue_add(project.root, "vo", 2, "card:red")

    result = ops.export(project.root, tmp_path / "out.kdenlive")

    assert result["writer"] == "mlt"
    assert result["shots"] == 2
    assert result["sources"] == 3  # the VO, the film, the card
    assert Path(result["output"]).is_file()


def test_the_exported_document_is_the_edits_own_frame_total(
    project: Project, tmp_path: Path
) -> None:
    """Not `round(duration * fps)` — every segment edge quantises on its own,
    and the layout's sum is the timeline that actually gets rendered
    (CLAUDE.md)."""
    ops.cue_add(project.root, "vo", 0, "film")
    ops.cue_add(project.root, "vo", 2, "card:red")

    result = ops.export(project.root, tmp_path / "out.kdenlive")

    edit = tl.read(project.timeline_path)
    expected = autoeditor.frame_total(edit, EXPORT_FPS)
    assert result["frames"] == expected
    assert set(mlt.declared_frames(_document(Path(result["output"]))).values()) == {expected}


def test_the_picture_lane_is_quantised_on_the_exports_grid_not_the_projects(
    project: Project, tmp_path: Path
) -> None:
    """The project's timebase is 1000 (milliseconds); the export's is 30. Ask
    for shots on the wrong grid and the lane comes out 33x too long, which
    `mlt.document` would refuse — so this asserts the frames that reached the
    document, not just that it was written."""
    ops.cue_add(project.root, "vo", 0, "film")
    ops.cue_add(project.root, "vo", 2, "card:red")

    result = ops.export(project.root, tmp_path / "out.kdenlive")

    playlist = _document(Path(result["output"])).find("*[@id='playlist2']")
    assert playlist is not None
    lane = [int(e.get("out", "0")) - int(e.get("in", "0")) + 1 for e in playlist.findall("entry")]
    assert sum(lane) == result["frames"]
    assert ops.build_shots(project.root, fps=EXPORT_FPS)["total_frames"] == result["frames"]


def test_build_shots_defaults_to_the_projects_own_timebase(project: Project) -> None:
    """1000 frames a second, because that is what an audio-only project's
    timebase is. Stated so the default is a decision rather than a surprise."""
    ops.cue_add(project.root, "vo", 0, "film")

    assert ops.build_shots(project.root)["rate"] == 1000.0
    assert ops.build_shots(project.root, fps=EXPORT_FPS)["rate"] == EXPORT_FPS


def test_a_second_clip_on_the_timeline_routes_through_mlt_without_any_cues(
    project: Project, tmp_path: Path
) -> None:
    """Two `src` files is the wall, whether they arrived from a cue table or
    from the edit itself."""
    edit = tl.Edit([tl.Segment("vo", 0.0, 2.0), tl.Segment("film", 0.0, 3.0)])
    manifest = project.read_manifest()
    tl.write(
        tl.to_otio(edit, {c["clip_id"]: c for c in manifest["clips"]}, rate=1000.0, name="proj"),
        project.timeline_path,
    )

    result = ops.export(project.root, tmp_path / "out.kdenlive")

    assert result["writer"] == "mlt"
    assert result["shots"] == 0
    assert result["sources"] == 2


def test_rendering_a_multi_source_timeline_goes_to_melt_not_auto_editor(
    project: Project, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The failure this routes around is silent: auto-editor renders two
    sources at 720x576 and exits 0, so a fallback would write a file that looks
    like a success. melt has no source-count gate."""
    ops.cue_add(project.root, "vo", 0, "film")
    seen: dict[str, Any] = {}

    def fake_render(project_file: Path, output: Path, **kwargs: Any) -> dict[str, Any]:
        seen["project_file"] = Path(project_file)
        seen["expect"] = kwargs
        return {"output": str(output), "width": 1920, "height": 1080, "frames": 150}

    monkeypatch.setattr(
        autoeditor,
        "run_timeline",
        lambda *a, **k: pytest.fail("auto-editor must never be handed a multi-source timeline"),
    )
    monkeypatch.setattr(picture, "project_frames", lambda p: _declared(Path(p)))
    monkeypatch.setattr(picture, "render", fake_render)

    result = ops.export(project.root, tmp_path / "out.mp4", export_format=None)

    assert result["writer"] == "melt"
    assert result["format"] == "media"
    assert result["rendered"]["width"] == 1920
    # What melt was handed, and what it was checked against.
    assert seen["expect"]["expect_frames"] == result["frames"]
    assert seen["expect"]["expect_resolution"] == (1920, 1080)
    assert seen["expect"]["expect_duration"] == pytest.approx(result["frames"] / EXPORT_FPS)


def test_the_rendered_document_is_written_where_melt_can_read_it(
    project: Project, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Not `/tmp`: melt runs from a flatpak that cannot see the host's, and
    exits 0 having read nothing (CLAUDE.md). The document is also the same one
    `export` would have written, not a second construction of it."""
    ops.cue_add(project.root, "vo", 0, "film")
    monkeypatch.setattr(picture, "RENDER_SCRATCH", tmp_path / "scratch")
    handed: dict[str, Any] = {}

    def fake_project_frames(path: Path) -> int:
        handed["path"] = Path(path)
        handed["text"] = Path(path).read_text(encoding="utf-8")
        return _declared(Path(path))

    monkeypatch.setattr(picture, "project_frames", fake_project_frames)
    monkeypatch.setattr(
        picture, "render", lambda p, output, **k: {"output": str(output), "frames": 150}
    )

    ops.export(project.root, tmp_path / "out.mp4", export_format=None)
    exported = ops.export(project.root, tmp_path / "out.kdenlive")

    assert handed["path"].is_relative_to(tmp_path / "scratch")
    assert handed["text"] == Path(exported["output"]).read_text(encoding="utf-8")


def test_a_render_is_refused_before_encoding_when_melt_disagrees(
    project: Project, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """melt renders to the longest declared length it finds, so a document it
    already reads as a different length would render that long and exit 0.
    Cheaper to catch with `-consumer xml` than with an encode."""
    ops.cue_add(project.root, "vo", 0, "film")
    monkeypatch.setattr(picture, "project_frames", lambda p: _declared(Path(p)) + 1)
    monkeypatch.setattr(
        picture, "render", lambda *a, **k: pytest.fail("the encode must not be spent")
    )

    with pytest.raises(ProjectError, match="refusing to spend an encode"):
        ops.export(project.root, tmp_path / "out.mp4", export_format=None)


def test_another_nles_format_is_refused_on_a_multi_source_timeline(
    project: Project, tmp_path: Path
) -> None:
    ops.cue_add(project.root, "vo", 0, "film")

    with pytest.raises(ProjectError, match="exit 2"):
        ops.export(project.root, tmp_path / "out.xml", export_format="premiere")


def test_mlt_is_a_spelling_of_the_same_export(project: Project, tmp_path: Path) -> None:
    """`.kdenlive` is MLT; the extension is the only thing Kdenlive cares
    about, so both names have to work and produce one document."""
    ops.cue_add(project.root, "vo", 0, "film")

    kdenlive = ops.export(project.root, tmp_path / "out.kdenlive")
    plain = ops.export(project.root, tmp_path / "out.mlt", export_format="mlt")

    assert Path(kdenlive["output"]).read_text() == Path(plain["output"]).read_text()


def test_a_single_source_timeline_with_no_cues_still_goes_to_auto_editor(
    project: Project, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The narrowing, asserted from the other side: nothing about today's
    single-source behaviour moves (PLAN.md § What this does to "lucid never
    writes MLT"). Stubbed at `run_timeline` so the assertion is about the
    route taken, not about auto-editor being installed."""
    monkeypatch.setattr(
        autoeditor, "run_timeline", lambda payload, output, export=None: Path(output)
    )
    monkeypatch.setattr(
        autoeditor, "template", lambda source: {"version": "3", "timebase": "30/1"}
    )

    result = ops.export(project.root, tmp_path / "out.kdenlive")

    assert result["writer"] == "auto-editor"
