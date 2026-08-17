"""`ops.finish_report` — STUDIO.md § Step 01's truth-strip composer.

Built by hand, the same no-ffmpeg pattern `test_ops_shots.py` uses: a real
`Project`, a hand-written `Edit` with a genuine cut gap, and a registered
clip whose media file is a stub (its `has_video` flag is set in the manifest
directly, never probed). `finish_report` never touches media on disk itself
— every field is another op's own return, filtered or summed — so this
fixture is enough to exercise all of it.

The point of this file is the composition claim: every field must be
*another op's own answer*, not a parallel read of the manifest. Proved the
`test_properties_composes_rather_than_reimplements` way — monkeypatch the
real op to lie, and check the lie surfaces here too, rather than by
asserting a value the honest op happens to produce today.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from lucid import ops
from lucid import timeline as tl
from lucid import transcript as tx
from lucid.project import Project, ProjectError

CLIPS = {
    "vo": {
        "clip_id": "vo",
        "source": "/tmp/vo.wav",
        "duration": 4.0,
        "has_video": False,
        "has_audio": True,
    },
    "clipa": {
        "clip_id": "clipa",
        "duration": 10.0,
        "has_video": True,
        "has_audio": True,
    },
}


def _words(clip_id: str, *specs: tuple[str, float, float]) -> tx.Transcript:
    return tx.Transcript(
        clip_id=clip_id,
        words=tuple(
            tx.Word(index=i, text=text, start=start, end=end)
            for i, (text, start, end) in enumerate(specs)
        ),
    )


@pytest.fixture
def project(tmp_path: Path) -> Project:
    """A VO clip cut to two surviving source ranges — [0.0, 1.0) and
    [2.0, 3.5) — with a gap at [1.0, 2.0), plus a registered video clip
    whose media file exists but is not real video (`has_video` is declared
    in the manifest, never probed — `_footage_resolution` only consults
    `width`/`height`, absent here, so the canvas falls back to
    `mlt.DEFAULT_RESOLUTION`, 1920x1080 — a 16:9 canvas, deliberately, so
    that `tiktok-reels`'s 9:16 claim is refused by every test in this file
    without any extra setup).
    """
    project = Project.create(tmp_path / "proj")

    clip_a_media = tmp_path / "clipa.mp4"
    clip_a_media.write_bytes(b"not really a video, just needs to exist")

    manifest = project.read_manifest()
    manifest["clips"] = [CLIPS["vo"], {**CLIPS["clipa"], "source": str(clip_a_media)}]
    project.write_manifest(manifest)

    edit = tl.Edit([tl.Segment("vo", 0.0, 1.0), tl.Segment("vo", 2.0, 3.5)])
    clips_by_id = {c["clip_id"]: c for c in manifest["clips"]}
    tl.write(tl.to_otio(edit, clips_by_id, rate=1000.0, name="proj"), project.timeline_path)

    tx.save(
        _words(
            "vo",
            ("cold", 0.0, 0.3),
            ("open", 0.5, 0.8),
            ("cut1", 1.2, 1.5),  # inside the cut gap [1.0, 2.0)
            ("after", 2.2, 2.5),
            ("last", 3.0, 3.3),
        ),
        project.transcript_path("vo"),
    )
    return project


def _with_one_pinned_cue(project: Project) -> Project:
    """A baseline, un-orphaned cue table: one cue, pinned, pointing at a
    surviving word — the shape `finish_report`'s non-error-path fields
    (`picture`, and the flags that would otherwise trip on it) assume."""
    ops.cue_add(project.root, "vo", 1, "clipa", src_start=0.0)  # "open" survives
    return project


# -- composition --------------------------------------------------------------


def test_finish_report_composes_rather_than_reimplements(
    project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`duration` must come from calling the real `status`, not from a
    parallel read of the edit/manifest — proved by making `status` lie and
    checking the lie shows up in `finish_report` too."""
    _with_one_pinned_cue(project)
    real_status = ops.status

    def _lying_status(path: object, **kwargs: object) -> dict[str, object]:
        result = real_status(path, **kwargs)  # type: ignore[arg-type]
        return {**result, "timeline_duration": 999.5, "expected_duration": 1000.5}

    monkeypatch.setattr(ops, "status", _lying_status)
    result = ops.finish_report(project.root)
    assert result["duration"]["edit_seconds"] == 999.5
    assert result["duration"]["total_seconds"] == 1000.5


# -- field shape ----------------------------------------------------------------


def test_finish_report_field_shape(project: Project) -> None:
    _with_one_pinned_cue(project)
    result = ops.finish_report(project.root)

    assert set(result) == {
        "duration",
        "canvas",
        "captions",
        "picture",
        "marks",
        "seams",
        "framing",
        "flags",
    }
    assert set(result["duration"]) == {"edit_seconds", "tail_seconds", "total_seconds"}
    assert set(result["canvas"]) == {"canvas", "presets"}
    assert set(result["canvas"]["presets"]) == {"youtube", "web", "tiktok-reels"}
    for preset in result["canvas"]["presets"].values():
        assert set(preset) == {"ok", "message"}
    assert set(result["captions"]) == {"configured", "font", "burned"}
    assert set(result["picture"]) == {"cue_count", "pinned_count", "shots_error"}
    assert set(result["marks"]) == {"applied", "stale"}
    assert set(result["seams"]) == {"count"}
    assert set(result["flags"]) == {"count", "items"}
    for item in result["flags"]["items"]:
        assert set(item) == {"kind", "message", "mode"}
        assert item["mode"] == "finish"


# -- captions.burned / the render log --------------------------------------------


def test_finish_report_captions_burned_unknown_with_no_render_log(project: Project) -> None:
    """No `cache/renders.jsonl` at all — reported as `unknown`, never as a
    clean or a `no`. The *flag* is a separate question, below."""
    _with_one_pinned_cue(project)
    assert not project.renders_log_path.exists()

    result = ops.finish_report(project.root)

    assert result["captions"]["burned"] == "unknown"


def test_finish_report_unknown_burn_flags_only_once_a_style_exists(project: Project) -> None:
    """The captionless-film failure is a *styled* project whose render never
    burned. An unstyled one has nothing to burn, so its unknown burn state is
    reported and not flagged — a flag no action can clear is a count that can
    never reach zero, which is the thing STUDIO.md's definition of done needs.
    """
    _with_one_pinned_cue(project)

    unstyled = ops.finish_report(project.root)
    assert unstyled["captions"]["configured"] is False
    assert unstyled["captions"]["burned"] == "unknown"
    assert [f for f in unstyled["flags"]["items"] if f["kind"] == "captions"] == []

    ops.caption_style(project.root, font="Noto Sans")

    styled = ops.finish_report(project.root)
    assert styled["captions"]["configured"] is True
    assert styled["captions"]["burned"] == "unknown"
    matching = [f for f in styled["flags"]["items"] if f["kind"] == "captions"]
    assert len(matching) == 1
    assert "no render log" in matching[0]["message"]
    assert matching[0]["mode"] == "finish"


# -- canvas.presets reuses _check_preset_canvas, never re-implements it ---------


def test_finish_report_canvas_presets_reuse_check_preset_canvas(project: Project) -> None:
    """The project's canvas defaults to 1920x1080 (fixture docstring) —
    `tiktok-reels` claims 9:16 and must be refused, with the *same* message
    `_check_preset_canvas` itself raises, not a restatement of it."""
    _with_one_pinned_cue(project)

    with pytest.raises(ProjectError) as excinfo:
        ops._check_preset_canvas(project, "tiktok-reels")
    expected_message = str(excinfo.value)

    result = ops.finish_report(project.root)

    tiktok = result["canvas"]["presets"]["tiktok-reels"]
    assert tiktok["ok"] is False
    assert tiktok["message"] == expected_message

    # And the presets that name no fixed geometry pass clean.
    assert result["canvas"]["presets"]["youtube"] == {"ok": True, "message": None}
    assert result["canvas"]["presets"]["web"] == {"ok": True, "message": None}

    # And a refusing preset is NOT a flag. It is drawn on the preset's own
    # card with its fix; flagging it would say the film is wrong for having
    # chosen 16:9, permanently and unclearably.
    assert [f for f in result["flags"]["items"] if f["kind"] == "canvas"] == []


# -- picture.shots_error is reported, never raised -------------------------------


def test_finish_report_picture_shots_error_reported_not_raised(project: Project) -> None:
    """A cue whose word was cut makes `timeline_view` refuse the projection
    (`test_ops_shots.py`'s own fixture for this: word 2, 'cut1', sits inside
    the [1.0, 2.0) gap) — `finish_report` must surface that as `shots_error`
    and a flag, and must not raise itself."""
    ops.cue_add(project.root, "vo", 2, "clipa")  # "cut1" is inside the cut gap

    # Sanity: the underlying view really does refuse this, so the assertion
    # below is exercising the pass-through and not a fixture that never hit it.
    view = ops.timeline_view(project.root)
    assert view["shots"] is None
    assert "was cut from the edit" in view["shots_error"]

    result = ops.finish_report(project.root)  # must not raise

    assert result["picture"]["shots_error"] is not None
    assert "was cut from the edit" in result["picture"]["shots_error"]
    assert result["picture"]["cue_count"] == 1

    flags = result["flags"]["items"]
    picture_flags = [f for f in flags if f["kind"] == "picture"]
    assert len(picture_flags) == 1
    assert picture_flags[0]["message"] == result["picture"]["shots_error"]


# -- flags.count always matches len(flags.items) ---------------------------------


def test_finish_report_flags_count_matches_items_length(project: Project) -> None:
    """A healthy project reaches zero flags. That is the property the whole
    strip rests on: the count is an inbox, and an inbox that cannot be emptied
    is a guard someone learns to ignore."""
    _with_one_pinned_cue(project)
    result = ops.finish_report(project.root)
    assert result["flags"]["count"] == len(result["flags"]["items"])
    assert result["flags"]["count"] == 0
    # Not vacuous — the fixture does carry the two conditions that used to
    # flag here and deliberately no longer do.
    assert result["canvas"]["presets"]["tiktok-reels"]["ok"] is False
    assert result["captions"]["burned"] == "unknown"


def test_finish_report_flags_count_matches_items_length_on_the_orphan_case(
    project: Project,
) -> None:
    ops.cue_add(project.root, "vo", 2, "clipa")  # orphaned, see above
    result = ops.finish_report(project.root)
    assert result["flags"]["count"] == len(result["flags"]["items"])
    assert [f["kind"] for f in result["flags"]["items"]] == ["picture"]


# -- framing is opt-in ----------------------------------------------------------


def test_framing_is_opt_in_and_none_is_not_zero(project: Project) -> None:
    """Off by default, and `None` rather than an empty dict when off.

    The framing section calls `reframe_coverage`, which decodes placed
    footage for a scene-cut scan — 5.7s wall and 46s of CPU on the real film,
    every call, uncached. The truth strip re-reads this op on every
    `project-changed`, so composing it in unconditionally made every cut pay
    for a number the cut had not asked about. `None` has to stay
    distinguishable from a measured zero, or "nobody scanned" reads as
    "nothing stale" — which is the captionless-film shape all over again.
    """
    _with_one_pinned_cue(project)

    off = ops.finish_report(project.root)
    assert off["framing"] is None
    assert [f for f in off["flags"]["items"] if f["kind"] == "framing"] == []

    on = ops.finish_report(project.root, framing=True)
    assert set(on["framing"]) == {"stale_seconds", "stale_stretches", "steps"}
    assert on["framing"]["stale_seconds"] == 0.0
