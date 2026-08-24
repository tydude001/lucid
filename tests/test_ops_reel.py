"""`reel` — deriving a project, PLAN.md § Three uncosted parity items.

The note that costed this found there was nothing to build for *choosing* a
reel — `cut_by_time` already takes the seconds an export plays at — and that
what was missing sat one level up: the canvas is project state and the cuts
are destructive, so the copy is mandatory and was a `cp -a` done by hand.
That note also said the hand recipe is the dumb control any reel feature has
to beat and should be built as a test first. `test_the_hand_recipe` below is
that control, run against the op, and most of what follows is the two ways
the hand recipe silently goes wrong: the film gets reshaped by a render
nobody kept, and the derived project resolves different bytes than the film.

Built by hand rather than through `import_media`, following
`test_ops_canvas.py`: no ffprobe is needed to have a project with a shape.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from lucid import media, ops
from lucid import timeline as tl
from lucid import transcript as tx
from lucid.project import Project, ProjectError

CLIP: dict[str, Any] = {
    "clip_id": "vo",
    "source": "/tmp/vo.mp4",
    "media": "media/vo.mp4",
    "duration": 12.0,
    "has_video": True,
    "has_audio": True,
    "width": 1920,
    "height": 816,
    "fps": 25.0,
}


def _transcript() -> tx.Transcript:
    """One word a second, so a timeline second reads as a word index."""
    return tx.Transcript(
        clip_id="vo",
        words=tuple(
            tx.Word(index=i, text=f"w{i}", start=float(i), end=float(i) + 0.4)
            for i in range(12)
        ),
    )


@pytest.fixture
def film(tmp_path: Path) -> Project:
    """A 12s single-clip film carrying one of everything a reel has to keep."""
    project = Project.create(tmp_path / "film")
    (tmp_path / "footage").mkdir()
    real = tmp_path / "footage" / "vo.mp4"
    real.write_bytes(b"not really an mp4")
    (project.media_dir / "vo.mp4").symlink_to(real)

    manifest = project.read_manifest()
    manifest["clips"] = [dict(CLIP)]
    manifest["cues"] = [{"clip_id": "vo", "word_index": 6, "asset": "card:title"}]
    manifest["descriptions"] = [
        {"clip_id": "vo", "src_start": 0.0, "src_end": 4.0, "text": "a hallway"}
    ]
    manifest["reframe"] = [{"clip_id": "vo", "rect": [400, 0, 960, 408]}]
    project.write_manifest(manifest)

    tx.save(_transcript(), project.transcript_path("vo"))
    tl.write(
        tl.to_otio(tl.Edit([tl.Segment("vo", 0.0, 12.0)]), {"vo": CLIP}, rate=25.0),
        project.timeline_path,
    )
    return project


# -- the hand recipe, as a test ------------------------------------------


def test_the_hand_recipe(film: Project, tmp_path: Path) -> None:
    """Copy, two cuts, canvas — the control the note said to build first."""
    result = ops.reel(film.root, tmp_path / "teaser", start=4.0, end=9.0, canvas="1080x1920")

    reel = Project.open(result["reel"])
    assert result["cut"] == [[0.0, 4.0], [9.0, 12.0]], "the head and the tail, not the keep"
    assert result["duration"] == pytest.approx(5.0)
    assert ops._load_edit(reel).duration == pytest.approx(5.0)
    assert ops.canvas(reel.root)["canvas"] == "1080x1920"


def test_the_film_is_left_alone(film: Project, tmp_path: Path) -> None:
    """The reason deriving exists at all. Setting a vertical canvas on the film
    to take one reel leaves it swapped after a render nobody kept — the failure
    `tiktok-reels` refuses one level down (HISTORY.md § `tiktok-reels`)."""
    before = film.manifest_path.read_text(encoding="utf-8")

    ops.reel(film.root, tmp_path / "teaser", start=4.0, end=9.0, canvas="1080x1920")

    assert film.manifest_path.read_text(encoding="utf-8") == before
    assert ops._load_edit(film).duration == pytest.approx(12.0)
    assert ops.canvas(film.root)["canvas"] == "1920x816"
    assert film.snapshots() == [], "the film's undo stack is not where the cuts went"


# -- what the derivation has to carry ------------------------------------


def test_the_reel_resolves_the_film_s_own_bytes(film: Project, tmp_path: Path) -> None:
    """Not a copy — a reel of a five-minute film would duplicate every gigabyte
    that went into making one."""
    result = ops.reel(film.root, tmp_path / "teaser", start=4.0, end=9.0)
    reel = Project.open(result["reel"])

    clip = media.get_clip(reel, "vo")
    assert media.media_path(reel, clip).read_bytes() == b"not really an mp4"
    assert media.media_path(reel, clip).resolve() == (tmp_path / "footage" / "vo.mp4")
    assert [entry["how"] for entry in result["linked"]] == ["symlink"]
    assert not any(entry["missing"] for entry in result["linked"])


def test_an_attenuated_copy_is_linked_too(film: Project, tmp_path: Path) -> None:
    """`media_path()` prefers `attenuated` over `media`, which is what makes
    attenuation transparent downstream — so carrying `media/` alone would give
    the reel a render at full noise with nothing in the manifest saying so."""
    calm = film.attenuated_dir / "vo.mp4"
    calm.write_bytes(b"the calm one")
    manifest = film.read_manifest()
    manifest["clips"][0]["attenuated"] = "cache/attenuated/vo.mp4"
    film.write_manifest(manifest)

    result = ops.reel(film.root, tmp_path / "teaser", start=4.0, end=9.0)
    reel = Project.open(result["reel"])

    assert media.media_path(reel, media.get_clip(reel, "vo")).read_bytes() == b"the calm one"
    assert {entry["key"] for entry in result["linked"]} == {"media", "attenuated"}


def test_a_filesystem_that_refuses_symlinks_falls_back_to_an_absolute_path(
    film: Project, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The NAS case that already makes `media/` optional (wiki `files.md`).
    Never a fall back to *dropping* the key: that resolves through
    `clip["source"]`, which is the original import path and so the file
    before any attenuation."""

    def refuse(self: Path, target: Any) -> None:
        raise OSError("this filesystem does not do symlinks")

    monkeypatch.setattr(Path, "symlink_to", refuse)
    result = ops.reel(film.root, tmp_path / "teaser", start=4.0, end=9.0)
    reel = Project.open(result["reel"])

    assert [entry["how"] for entry in result["linked"]] == ["absolute"]
    assert media.media_path(reel, media.get_clip(reel, "vo")).read_bytes() == b"not really an mp4"


def test_the_transcript_comes_with_it(film: Project, tmp_path: Path) -> None:
    """It indexes the source, so it is as true of the reel as of the film —
    and it costs ASR minutes to rebuild."""
    result = ops.reel(film.root, tmp_path / "teaser", start=4.0, end=9.0)
    reel = Project.open(result["reel"])

    assert reel.transcript_path("vo").is_file()
    loaded = tx.load(reel.transcript_path("vo"), clip_id="vo")
    assert loaded.words == _transcript().words


def test_the_film_s_renders_and_history_stay_behind(film: Project, tmp_path: Path) -> None:
    """They describe the film's own output and the film's own undo stack;
    neither says anything true about the reel."""
    film.render_dir.mkdir(parents=True, exist_ok=True)
    (film.render_dir / "final.mp4").write_bytes(b"the film")
    film.verify_dir.mkdir(parents=True, exist_ok=True)
    (film.verify_dir / "final.json").write_text("{}", encoding="utf-8")
    film.snapshot()

    result = ops.reel(film.root, tmp_path / "teaser", start=4.0, end=9.0)
    reel = Project.open(result["reel"])

    assert list(reel.render_dir.iterdir()) == []
    assert list(reel.verify_dir.iterdir()) == []
    assert len(reel.snapshots()) == 1, "only the snapshot its own cut took"


def test_source_addressed_state_survives_by_construction(film: Project, tmp_path: Path) -> None:
    """Descriptions index the source and a reframe is a rect in source pixels
    refit at render time — so neither a cut nor a canvas change can invalidate
    one. The roadmap's core property paying out rather than work this op does;
    pinned here because a future `reel` that started rewriting them would be
    the bug."""
    result = ops.reel(film.root, tmp_path / "teaser", start=4.0, end=9.0, canvas="1080x1920")
    reel = Project.open(result["reel"])

    assert reel.read_manifest()["descriptions"] == film.read_manifest()["descriptions"]
    assert reel.read_manifest()["reframe"] == film.read_manifest()["reframe"]


# -- the cues, which a cut can orphan even though it cannot invalidate one --


def test_a_cue_the_reel_still_has_the_word_for_comes_across(
    film: Project, tmp_path: Path
) -> None:
    """The fixture's one cue sits on word 6, inside the kept span."""
    result = ops.reel(film.root, tmp_path / "teaser", start=4.0, end=9.0)
    reel = Project.open(result["reel"])

    assert result["cues_dropped"] == []
    assert reel.read_manifest()["cues"] == film.read_manifest()["cues"]


def test_a_cue_whose_word_the_reel_cut_is_dropped_and_named(
    film: Project, tmp_path: Path
) -> None:
    """Found by deriving a reel of the real film, not by reasoning about one:
    keeping 44s of 5:36 orphaned 30-odd cues, and `build_shots` refuses a whole
    projection on a single orphan — so the derived project passed every check
    and could not be rendered."""
    result = ops.reel(film.root, tmp_path / "teaser", start=0.0, end=3.0)
    reel = Project.open(result["reel"])

    assert [cue["word_index"] for cue in result["cues_dropped"]] == [6]
    assert result["cues_dropped"][0]["text"] == "w6", "named by its word, not its index alone"
    assert reel.read_manifest()["cues"] == []


def test_the_derived_project_can_project_shots(film: Project, tmp_path: Path) -> None:
    """The check that would have caught it. `build_shots` is what `export`
    reads, so a cue table it refuses is a reel that cannot be rendered — and
    nothing else in the derivation notices."""
    (film.cards_dir).mkdir(parents=True, exist_ok=True)
    (film.cards_dir / "title.png").write_bytes(b"a card")
    manifest = film.read_manifest()
    manifest["cues"] = [
        {"clip_id": "vo", "word_index": 1, "asset": "card:title"},
        {"clip_id": "vo", "word_index": 6, "asset": "card:title"},
    ]
    film.write_manifest(manifest)

    result = ops.reel(film.root, tmp_path / "teaser", start=5.0, end=10.0)

    assert [cue["word_index"] for cue in result["cues_dropped"]] == [1]
    shots = ops.build_shots(result["reel"])
    assert shots["shots"], "the reel projects, which is what export needs"


# -- and the quieter half: what a survivor shows once the others are gone --


def _three_shots_of_one_clip(film: Project) -> None:
    """A b-roll clip cued three times, which is where the cursor is visible.

    `plan_picture` walks one cursor per asset, so the three shots read 0-6s,
    6-9s and 9-12s of `broll` — a clip used three times showing three
    stretches of itself, which is the whole point of the cursor.
    """
    real = film.root.parent / "footage" / "broll.mp4"
    real.write_bytes(b"twenty seconds of hallway")
    (film.media_dir / "broll.mp4").symlink_to(real)

    manifest = film.read_manifest()
    manifest["clips"].append(
        {
            "clip_id": "broll",
            "source": "/tmp/broll.mp4",
            "media": "media/broll.mp4",
            "duration": 20.0,
            "has_video": True,
            "has_audio": False,
            "width": 1920,
            "height": 816,
            "fps": 25.0,
        }
    )
    manifest["cues"] = [
        {"clip_id": "vo", "word_index": index, "asset": "broll"} for index in (2, 6, 9)
    ]
    film.write_manifest(manifest)


def test_a_surviving_cue_is_pinned_to_the_in_point_the_film_gave_it(
    film: Project, tmp_path: Path
) -> None:
    """The cursor `plan_picture` walks is per-asset and cumulative, so dropping
    the cues a derivation cut empties it — and the survivors, which asked for
    nothing, arrive reading their asset from the head."""
    _three_shots_of_one_clip(film)

    result = ops.reel(film.root, tmp_path / "teaser", start=5.0, end=11.0)
    reel = Project.open(result["reel"])

    assert [cue["word_index"] for cue in result["cues_dropped"]] == [2]
    assert [(p["word_index"], p["src_start"]) for p in result["cues_pinned"]] == [
        (6, 6.0),
        (9, 9.0),
    ]
    assert [cue.get("src_start") for cue in reel.read_manifest()["cues"]] == [6.0, 9.0]
    assert result["pins_error"] is None


def test_the_reel_shows_what_the_film_showed_over_the_same_seconds(
    film: Project, tmp_path: Path
) -> None:
    """The property the pinning exists for, stated against the two plans rather
    than against the manifest: same asset, same seconds of it. Unpinned this
    reel reads 0s and 4s of `broll` where the film read 6s and 9s — real
    frames, a valid projection, and a different film at exit 0 with `status`,
    `verify` and `check_frames` all agreeing (HISTORY.md § The teaser, re-cut).
    """
    _three_shots_of_one_clip(film)
    film_shots, _ = ops._picture_plan(film, 25.0)
    assert [shot["src_start"] for shot in film_shots] == [0.0, 6.0, 9.0], "the cursor walking"

    result = ops.reel(film.root, tmp_path / "teaser", start=5.0, end=11.0)
    reel_shots, _ = ops._picture_plan(Project.open(result["reel"]), 25.0)

    kept = {(shot["clip_id"], shot["word_index"]): shot for shot in film_shots}
    for shot in reel_shots:
        assert shot["src_start"] == kept[(shot["clip_id"], shot["word_index"])]["src_start"]
    assert [shot["src_start"] for shot in reel_shots] == [6.0, 9.0], "not 0.0 and 4.0"


def test_a_cue_pinned_by_hand_is_left_alone(film: Project, tmp_path: Path) -> None:
    """A pinned shot has no cursor, so the film's plan agrees with the pin by
    construction and there is nothing to add — and a hand-chosen in-point is
    the last thing a derivation should be rewriting."""
    _three_shots_of_one_clip(film)
    manifest = film.read_manifest()
    manifest["cues"][1]["src_start"] = 12.0
    film.write_manifest(manifest)

    result = ops.reel(film.root, tmp_path / "teaser", start=5.0, end=11.0)
    reel = Project.open(result["reel"])

    assert [p["word_index"] for p in result["cues_pinned"]] == [9], "only the one asking for nothing"
    # 15.0 rather than 9.0: the hand pin moved the cursor the third shot picks
    # up, so what the film showed there moved with it. Read off the plan, not
    # off the cue table, which is why this is not the pin arithmetic repeated.
    assert [cue.get("src_start") for cue in reel.read_manifest()["cues"]] == [12.0, 15.0]


def test_a_still_is_not_pinned(film: Project, tmp_path: Path) -> None:
    """A card is a held frame with no playhead to move, and `plan_picture`
    refuses a pin on one rather than ignoring it — so writing one here would
    make the reel unrenderable to fix a problem stills do not have."""
    film.cards_dir.mkdir(parents=True, exist_ok=True)
    (film.cards_dir / "title.png").write_bytes(b"a card")

    result = ops.reel(film.root, tmp_path / "teaser", start=4.0, end=9.0)
    reel = Project.open(result["reel"])

    assert result["cues_pinned"] == []
    assert "src_start" not in reel.read_manifest()["cues"][0]
    assert ops.build_shots(reel.root)["shots"], "and it still projects"


def test_a_film_that_cannot_project_says_so_rather_than_pinning_silently(
    film: Project, tmp_path: Path
) -> None:
    """A film that cannot project shots cannot be exported either, so the reel
    is not made newly wrong by deriving from one. But it is why its cues arrive
    unpinned, and an empty list alone would read as "nothing needed one"."""
    _three_shots_of_one_clip(film)
    manifest = film.read_manifest()
    manifest["clips"][1]["duration"] = 2.0
    film.write_manifest(manifest)

    result = ops.reel(film.root, tmp_path / "teaser", start=5.0, end=11.0)

    assert result["cues_pinned"] == []
    assert result["pins_error"] and "broll" in result["pins_error"]
    assert [cue.get("src_start") for cue in Project.open(result["reel"]).read_manifest()["cues"]] == [
        None,
        None,
    ]


def test_plan_names_the_pins_and_creates_nothing(film: Project, tmp_path: Path) -> None:
    """Same convention as `cues_dropped`: both are resolved against the film
    before anything is created, so the plan is the answer rather than a guess
    at it."""
    _three_shots_of_one_clip(film)

    result = ops.reel(film.root, tmp_path / "teaser", start=5.0, end=11.0, plan=True)

    assert [(p["word_index"], p["src_start"]) for p in result["cues_pinned"]] == [
        (6, 6.0),
        (9, 9.0),
    ]
    assert not (tmp_path / "teaser").exists()


def test_the_reel_records_where_it_came_from(film: Project, tmp_path: Path) -> None:
    """The question a hand-made scratch copy could not answer once already:
    which film is this, and which seconds of it (HISTORY.md § The VO the
    project was holding)."""
    result = ops.reel(film.root, tmp_path / "teaser", start=4.0, end=9.0)
    reel = Project.open(result["reel"])

    assert reel.read_manifest()["derived_from"] == {
        "project": str(film.root),
        "keep": [4.0, 9.0],
        "source_duration": pytest.approx(12.0),
    }
    assert reel.read_manifest()["name"] == "teaser"


# -- a tail is never inherited (PLAN.md § Tail time — the design note) ---


def test_a_films_tail_is_dropped_and_named(film: Project, tmp_path: Path) -> None:
    """Taken 2026-08-12: a derivation carries nothing and reports — the same
    'never' `cues_pinned` proves out for pruning, applied to a finishing pass.
    A teaser derived from an essay must not silently end on the essay's own
    end card."""
    ops.tail(film.root, asset="card:title", seconds=6.0, fade=0.167)

    result = ops.reel(film.root, tmp_path / "teaser", start=4.0, end=9.0)
    reel = Project.open(result["reel"])

    assert result["tail_dropped"] == {"asset": "card:title", "seconds": 6.0, "fade": 0.167}
    assert ops.TAIL_KEY not in reel.read_manifest()
    assert ops.tail(reel.root)["tail"] is None
    # And the film itself is untouched — the same guarantee every other
    # `reel` field already gets (test_the_film_is_left_alone).
    assert ops.tail(film.root)["tail"] == {"asset": "card:title", "seconds": 6.0, "fade": 0.167}


def test_a_film_with_no_tail_reports_none_dropped(film: Project, tmp_path: Path) -> None:
    result = ops.reel(film.root, tmp_path / "teaser", start=4.0, end=9.0)

    assert result["tail_dropped"] is None


def test_tail_dropped_is_reported_under_plan_too(film: Project, tmp_path: Path) -> None:
    """Read early, before anything is created — the same as `cues_dropped`."""
    ops.tail(film.root, asset="card:title", seconds=6.0)

    result = ops.reel(film.root, tmp_path / "teaser", start=4.0, end=9.0, plan=True)

    assert result["tail_dropped"] == {"asset": "card:title", "seconds": 6.0, "fade": 0.0}
    assert not (tmp_path / "teaser").exists()


# -- a head is never inherited either, `tail_dropped`'s rule mirrored -----


def test_a_films_head_is_dropped_and_named(film: Project, tmp_path: Path) -> None:
    """A cold open is a decision about *this* cut's own opening beat, not a
    fact a span of the film carries forward into a teaser — a teaser derived
    from an essay must not silently open on the essay's own cold open."""
    ops.head(film.root, asset="vo", src_start=1.0, seconds=2.0, gain_db=15.1)

    result = ops.reel(film.root, tmp_path / "teaser", start=4.0, end=9.0)
    reel = Project.open(result["reel"])

    assert result["head_dropped"] == {
        "asset": "vo",
        "src_start": 1.0,
        "seconds": 2.0,
        "fade_in": 0.0,
        "fade_out": 0.0,
        "gain_db": 15.1,
    }
    assert ops.HEAD_KEY not in reel.read_manifest()
    assert ops.head(reel.root)["head"] is None
    # And the film itself is untouched — the same guarantee every other
    # `reel` field already gets (test_the_film_is_left_alone).
    assert ops.head(film.root)["head"]["seconds"] == 2.0


def test_a_film_with_no_head_reports_none_dropped(film: Project, tmp_path: Path) -> None:
    result = ops.reel(film.root, tmp_path / "teaser", start=4.0, end=9.0)

    assert result["head_dropped"] is None


def test_head_dropped_is_reported_under_plan_too(film: Project, tmp_path: Path) -> None:
    """Read early, before anything is created — the same as `cues_dropped`."""
    ops.head(film.root, asset="vo", seconds=2.0)

    result = ops.reel(film.root, tmp_path / "teaser", start=4.0, end=9.0, plan=True)

    assert result["head_dropped"]["asset"] == "vo"
    assert not (tmp_path / "teaser").exists()


def test_a_films_music_bed_is_dropped_and_named(film: Project, tmp_path: Path) -> None:
    """The tail's rule, not the cue table's: the bed is project state beside
    `Edit`, and unlike a picture cue it cannot simply be kept where its word
    survives — the film's bed has been playing for however long by the reel's
    first second, and re-opening it from its head is the `cues_pinned` shape
    with no pin to give it (PLAN.md § The A2 music lane, what the note does
    not settle)."""
    manifest = film.read_manifest()
    manifest["clips"].append(
        {"clip_id": "bed", "source": "/tmp/bed.wav", "duration": 30.0,
         "has_video": False, "has_audio": True}
    )
    film.write_manifest(manifest)
    ops.music(film.root, asset="bed", clip_id="vo", word_index_start=2)

    result = ops.reel(film.root, tmp_path / "teaser", start=4.0, end=9.0)
    reel = Project.open(result["reel"])

    assert result["music_dropped"]["asset"] == "bed"
    assert ops.MUSIC_KEY not in reel.read_manifest()
    assert ops.music(reel.root)["music"] is None
    assert ops.music(film.root)["music"]["asset"] == "bed", "the film is untouched"


def test_a_film_with_no_music_reports_none_dropped(film: Project, tmp_path: Path) -> None:
    result = ops.reel(film.root, tmp_path / "teaser", start=4.0, end=9.0)

    assert result["music_dropped"] is None


# -- a hold is never inherited either, `tail_dropped`'s rule mirrored -----


def _stored_hold() -> dict[str, Any]:
    return {
        "clip_id": "vo",
        "gap_word_index": 6,
        "cue_word_index": 3,
        "asset": "vo",
        "word_index_first": 0,
        "word_index_last": 1,
        "head_margin": ops.HOLD_HEAD_MARGIN,
        "tail_margin": ops.HOLD_TAIL_MARGIN,
        "under": ops.HOLD_UNDER,
        "fade_in": ops.HOLD_FADE_IN,
        "fade_out": ops.HOLD_FADE_OUT,
    }


def test_a_films_holds_are_dropped_and_named(film: Project, tmp_path: Path) -> None:
    """A hold ties a VO gap to a picture cue *and* to a specific mix — none of
    which the reel's own re-cut cue table has anything to do with. Dropped
    unconditionally and named, `tail_dropped`/`music_dropped`'s own rule."""
    manifest = film.read_manifest()
    manifest[ops.HOLDS_KEY] = [_stored_hold()]
    film.write_manifest(manifest)

    result = ops.reel(film.root, tmp_path / "teaser", start=4.0, end=9.0)
    reel = Project.open(result["reel"])

    assert result["holds_dropped"] == [_stored_hold()]
    assert ops.HOLDS_KEY not in reel.read_manifest()
    assert ops.hold_ls(reel.root)["holds"] == []
    # And the film itself is untouched.
    assert ops.hold_ls(film.root)["holds"][0]["gap_word_index"] == 6


def test_a_film_with_no_holds_reports_none_dropped(film: Project, tmp_path: Path) -> None:
    result = ops.reel(film.root, tmp_path / "teaser", start=4.0, end=9.0)

    assert result["holds_dropped"] == []


# -- the edges of the span -----------------------------------------------


def test_keeping_the_head_cuts_only_the_tail(film: Project, tmp_path: Path) -> None:
    result = ops.reel(film.root, tmp_path / "teaser", start=0.0, end=5.0)

    assert result["cut"] == [[5.0, 12.0]]
    assert ops._load_edit(Project.open(result["reel"])).duration == pytest.approx(5.0)


def test_keeping_the_whole_film_is_a_plain_copy(film: Project, tmp_path: Path) -> None:
    """Not an error: a derivation with no cut in it is still a derivation, and
    it is how a reel gets a canvas of its own without losing a second."""
    result = ops.reel(film.root, tmp_path / "copy", start=0.0, end=12.0)

    assert result["cut"] == []
    assert ops._load_edit(Project.open(result["reel"])).duration == pytest.approx(12.0)


def test_the_platform_cap_is_reported_never_enforced(film: Project, tmp_path: Path) -> None:
    """Why a reel exists at all — a 5:36 film reaches no feed. Reported so it
    can be read, not refused so it has to be worked around."""
    under = ops.reel(film.root, tmp_path / "short", start=0.0, end=5.0)
    assert under["over_platform_cap"] is False

    planned = ops.reel(film.root, tmp_path / "long", start=0.0, end=12.0, plan=True)
    assert planned["platform_cap"] == ops.PLATFORM_CAP
    assert planned["over_platform_cap"] is False, "12s is not over three minutes"


# -- what it refuses -----------------------------------------------------


def test_a_span_past_the_end_names_the_duration(film: Project, tmp_path: Path) -> None:
    with pytest.raises(tl.TimelineError, match="12.000s"):
        ops.reel(film.root, tmp_path / "teaser", start=4.0, end=40.0)

    assert not (tmp_path / "teaser").exists(), "a refusal leaves nothing behind"


@pytest.mark.parametrize("start, end", [(9.0, 4.0), (4.0, 4.0), (-1.0, 4.0)])
def test_a_span_that_is_not_a_span_is_refused(
    film: Project, tmp_path: Path, start: float, end: float
) -> None:
    with pytest.raises(tl.TimelineError):
        ops.reel(film.root, tmp_path / "teaser", start=start, end=end)


def test_a_destination_with_anything_in_it_is_refused(film: Project, tmp_path: Path) -> None:
    """`Project.create` adopts an existing empty directory, so the refusal has
    to be here — and it is what makes the cleanup below safe to do."""
    dest = tmp_path / "teaser"
    dest.mkdir()
    (dest / "notes.txt").write_text("mine", encoding="utf-8")

    with pytest.raises(ProjectError, match="already has something in it"):
        ops.reel(film.root, dest, start=4.0, end=9.0)

    assert (dest / "notes.txt").read_text(encoding="utf-8") == "mine"


def test_deriving_a_project_from_itself_is_refused(film: Project) -> None:
    with pytest.raises(ProjectError, match="cannot be that project"):
        ops.reel(film.root, film.root, start=4.0, end=9.0)


def test_a_failure_leaves_no_half_derived_project(
    film: Project, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A half-derived one is worse than none: it opens, it reads as a film, and
    its timeline is the uncut one."""

    def explode(*args: Any, **kwargs: Any) -> None:
        raise ProjectError("boom")

    monkeypatch.setattr(ops, "cut_by_time", explode)
    with pytest.raises(ProjectError, match="boom"):
        ops.reel(film.root, tmp_path / "teaser", start=4.0, end=9.0)

    assert not (tmp_path / "teaser").exists()


# -- the suspect-duration guard, at a reel's own granularity -------------


def _with_a_suspect_word(film: Project, index: int, length: float) -> None:
    """Stretch one word past the 3x-median cutoff `energy.suspect_durations` uses."""
    words = list(_transcript().words)
    was = words[index]
    words[index] = tx.Word(index=was.index, text=was.text, start=was.start, end=was.start + length)
    tx.save(tx.Transcript(clip_id="vo", words=tuple(words)), film.transcript_path("vo"))


def test_a_suspect_word_at_a_kept_edge_is_refused(film: Project, tmp_path: Path) -> None:
    """The edge the reel keeps is where an inflated duration costs something:
    a word that does not end where it claims means the reel opens on material
    from the wrong take, and that reads as an editing choice."""
    _with_a_suspect_word(film, 4, 3.0)

    with pytest.raises(tl.TimelineError, match="hides a retake"):
        ops.reel(film.root, tmp_path / "teaser", start=4.5, end=9.0)

    assert not (tmp_path / "teaser").exists()
    result = ops.reel(film.root, tmp_path / "teaser", start=4.5, end=9.0, confirm_suspect=True)
    assert [hit["index"] for hit in result["suspect_edges"]] == [4]
    assert result["suspect_edges"][0]["edge"] == "start"


def test_a_suspect_word_the_reel_merely_cuts_away_is_not_a_refusal(
    film: Project, tmp_path: Path
) -> None:
    """The measurement this exists for: `cut_by_time` flags every suspect word
    a removed span overlaps, and a reel removes most of the film — on the real
    film a 44s reel of 5:36 flagged fifteen, none of them near either edge. A
    guard that has to be suppressed every time guards nothing."""
    _with_a_suspect_word(film, 1, 3.0)

    result = ops.reel(film.root, tmp_path / "teaser", start=6.0, end=9.0)

    assert result["suspect_edges"] == []
    assert ops._load_edit(Project.open(result["reel"])).duration == pytest.approx(3.0)


def test_the_film_s_own_head_and_tail_are_never_edges(film: Project, tmp_path: Path) -> None:
    """Keeping from zero has no kept head to check — there is nothing before
    the film's first frame for a word to run into."""
    _with_a_suspect_word(film, 0, 3.0)

    result = ops.reel(film.root, tmp_path / "teaser", start=0.0, end=9.0)

    assert result["suspect_edges"] == []


def test_plan_reports_a_suspect_edge_instead_of_refusing_it(film: Project, tmp_path: Path) -> None:
    """Refusing to *look* would be backwards, and it is `cut_by_time`'s own
    convention for the same finding."""
    _with_a_suspect_word(film, 4, 3.0)

    planned = ops.reel(film.root, tmp_path / "teaser", start=4.5, end=9.0, plan=True)

    assert [hit["index"] for hit in planned["suspect_edges"]] == [4]


# -- planning ------------------------------------------------------------


def test_plan_creates_nothing(film: Project, tmp_path: Path) -> None:
    planned = ops.reel(film.root, tmp_path / "teaser", start=4.0, end=9.0, plan=True)

    assert planned["plan"] is True
    assert planned["cut"] == [[0.0, 4.0], [9.0, 12.0]]
    assert planned["duration"] == pytest.approx(5.0)
    assert not (tmp_path / "teaser").exists()
    assert ops._load_edit(film).duration == pytest.approx(12.0)


def test_plan_resolves_both_spans_against_the_uncut_timeline(
    film: Project, tmp_path: Path
) -> None:
    """One `cut_by_time` call rather than two, because that is what the real
    path runs: planning them separately would resolve the tail against a
    timeline the head had not been taken out of."""
    planned = ops.reel(film.root, tmp_path / "teaser", start=4.0, end=9.0, plan=True)

    applied = planned["cut_plan"]["applied"]
    assert [entry["requested_start"] for entry in applied] == [0.0, 9.0]
    assert planned["cut_plan"]["duration_after"] == pytest.approx(5.0)
    assert planned["would_link"] == [{"clip_id": "vo", "key": "media"}]
