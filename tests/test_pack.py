"""The channel preset pack: `pack.py`'s pure logic, and the `ops` surface on top.

PLAN.md § The completion queue, item 8. Split the way `test_fonts.py`/
`test_captions.py` are: `pack.load_pack`/`pack.pack_hash` need no project, no
subprocess, and no font — they are covered with plain dicts and a `tmp_path`
JSON file. Everything that touches a project (`pack_apply`'s font probing,
`card_new`'s pre-merge, `card_safe_zones`'s measurement) needs the real
renderer and is marked accordingly, the same `needs_magick`/`needs_ffmpeg`
split `test_fonts.py` and `test_ops_card_reauthor.py` already use.

MCP registration/reachability is covered here too, against a real `lucid mcp`
process — `test_server_stdio.py` has an uncommitted diff of its own in this
working tree as this session starts (`git status` on this repo shows it, and
`src/proofcut/cli.py`/`ops.py`/`server.py` alongside it), so its `EXPECTED_TOOLS`
exact-equality assertions are not this session's to extend. A second,
independent stdio round trip proves the six new tools are registered and
reachable without touching that file.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path
from typing import Any

import anyio
import pytest
from mcp import ClientSession, StdioServerParameters, stdio_client

from proofcut import fonts, graphics, ops
from proofcut import timeline as tl
from proofcut.pack import PackError, load_pack, pack_hash
from proofcut.project import Project, ProjectError

needs_magick = pytest.mark.skipif(
    shutil.which("magick") is None, reason="ImageMagick is not installed"
)
needs_probe = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("magick") is None,
    reason="fonts.probe is a render comparison; it needs ffmpeg with libass and ImageMagick",
)

CLIP = {
    "clip_id": "cold-open",
    "source": "/nonexistent/cold-open.mp4",
    "duration": 12.0,
    "has_video": True,
    "has_audio": True,
    "width": 1920,
    "height": 816,
}


@pytest.fixture
def project(tmp_path: Path) -> Project:
    """A project with a clip and a minimal seeded timeline — `ops.status`
    (and so `ops.pack_status`/the "pack" section on `status`) needs one, the
    same reason `test_ops_canvas.py` builds this by hand rather than through
    `import_media`.
    """
    project = Project.create(tmp_path / "proj")
    manifest = project.read_manifest()
    manifest["clips"] = [CLIP]
    project.write_manifest(manifest)
    edit = tl.Edit([tl.Segment(CLIP["clip_id"], 0.0, 12.0)])
    tl.write(tl.to_otio(edit, {CLIP["clip_id"]: CLIP}, rate=1000.0), project.timeline_path)
    return project


# -- a minimal pack, built in Python so a test can mutate one field at a time --


def _pack_dict(**overrides: Any) -> dict[str, Any]:
    """A pack with every required section, small enough to read at a glance.

    `overrides` replaces whole top-level keys — a test wanting to break one
    field of `variants.default.palette` copies this and mutates the copy,
    which is more honest than a merge helper hiding what changed.
    """
    base: dict[str, Any] = {
        "name": "test-pack",
        "format": 1,
        "variants": {
            "default": {
                "palette": {"paper": "#ffffff", "ink": "#000000"},
                "fonts": {"title_font": "'Made Up Face', serif"},
                "mark": {"wordmark": "Test[em]*[/em]"},
            }
        },
    }
    base.update(overrides)
    return base


def _write_pack(tmp_path: Path, data: dict[str, Any], name: str = "pack.json") -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


# -- load_pack: the happy path -----------------------------------------------


def test_load_pack_resolves_the_default_variant(tmp_path: Path) -> None:
    path = _write_pack(tmp_path, _pack_dict())
    loaded = load_pack(path)

    assert loaded["name"] == "test-pack"
    assert loaded["format"] == 1
    assert set(loaded["variants"]) == {"default"}
    default = loaded["variants"]["default"]
    assert default["palette"] == {"paper": "#ffffff", "ink": "#000000"}
    assert default["fonts"] == {"title_font": "'Made Up Face', serif"}
    assert default["mark"] == {"wordmark": "Test[em]*[/em]"}
    # Sections a pack never mentioned resolve to their own empty default,
    # never a missing key — every caller (`ops.pack_apply`'s font loop,
    # `card_safe_zones`'s `.get("safe_zones", {})`) reads them unconditionally.
    assert default["weights"] == {}
    assert default["safe_zones"] == {}
    assert default["caption_presets"] == {}


def test_a_non_default_variant_merges_onto_default_one_key_at_a_time(tmp_path: Path) -> None:
    """The october-swaps-amber shape, in miniature: only the overridden
    palette slot changes, and everything else — fonts, mark, and the
    palette slots the variant never mentioned — carries over from default."""
    data = _pack_dict()
    data["variants"]["october"] = {"palette": {"ink": "#111111"}}
    loaded = load_pack(_write_pack(tmp_path, data))

    october = loaded["variants"]["october"]
    assert october["palette"] == {"paper": "#ffffff", "ink": "#111111"}
    assert october["fonts"] == {"title_font": "'Made Up Face', serif"}
    assert october["mark"] == {"wordmark": "Test[em]*[/em]"}


def test_a_variant_merges_caption_presets_per_preset_name_not_wholesale(tmp_path: Path) -> None:
    """A variant restating one field of one preset does not have to carry
    every other field, or every other preset, along with it."""
    data = _pack_dict()
    data["variants"]["default"]["caption_presets"] = {
        "clean": {"preset": "clean", "size": 60},
        "boxed": {"preset": "boxed"},
    }
    data["variants"]["loud"] = {"caption_presets": {"clean": {"size": 90}}}
    loaded = load_pack(_write_pack(tmp_path, data))

    loud_presets = loaded["variants"]["loud"]["caption_presets"]
    assert loud_presets["clean"] == {"preset": "clean", "size": 90}
    assert loud_presets["boxed"] == {"preset": "boxed"}


# -- $palette. / $fonts. token resolution ------------------------------------


def test_dollar_tokens_resolve_from_the_same_variants_own_palette_and_fonts(
    tmp_path: Path,
) -> None:
    data = _pack_dict()
    data["variants"]["default"]["caption_presets"] = {
        "clean": {"preset": "clean", "outline_colour": "$palette.ink", "font": "Outfit"}
    }
    data["variants"]["october"] = {"palette": {"ink": "#222222"}}
    loaded = load_pack(_write_pack(tmp_path, data))

    assert loaded["variants"]["default"]["caption_presets"]["clean"]["outline_colour"] == "#000000"
    # The whole point: october's own overridden ink flows into the preset
    # with no second hex code written anywhere in the file.
    october_presets = loaded["variants"]["october"]["caption_presets"]
    assert october_presets["clean"]["outline_colour"] == "#222222"


def test_a_dollar_token_naming_an_unresolved_slot_refuses(tmp_path: Path) -> None:
    data = _pack_dict()
    data["variants"]["default"]["caption_presets"] = {
        "clean": {"preset": "clean", "outline_colour": "$palette.nonexistent"}
    }
    with pytest.raises(PackError, match="nonexistent"):
        load_pack(_write_pack(tmp_path, data))


# -- refusals, one per rule --------------------------------------------------


def test_refuses_an_unrecognised_format_version(tmp_path: Path) -> None:
    with pytest.raises(PackError, match="format"):
        load_pack(_write_pack(tmp_path, _pack_dict(format=99)))


def test_refuses_a_pack_with_no_default_variant(tmp_path: Path) -> None:
    data = _pack_dict()
    data["variants"] = {"october": {"palette": {}, "fonts": {}, "mark": {}}}
    with pytest.raises(PackError, match="default"):
        load_pack(_write_pack(tmp_path, data))


def test_refuses_an_unknown_top_level_key(tmp_path: Path) -> None:
    with pytest.raises(PackError, match="unknown top-level"):
        load_pack(_write_pack(tmp_path, _pack_dict(bogus=1)))


def test_refuses_an_unknown_per_variant_key(tmp_path: Path) -> None:
    data = _pack_dict()
    data["variants"]["default"]["bogus"] = {}
    with pytest.raises(PackError, match="unknown key"):
        load_pack(_write_pack(tmp_path, data))


@pytest.mark.parametrize("missing", ["palette", "fonts", "mark"])
def test_refuses_a_default_variant_missing_a_required_section(
    tmp_path: Path, missing: str
) -> None:
    data = _pack_dict()
    del data["variants"]["default"][missing]
    with pytest.raises(PackError, match=missing):
        load_pack(_write_pack(tmp_path, data))


def test_refuses_a_malformed_palette_colour(tmp_path: Path) -> None:
    data = _pack_dict()
    data["variants"]["default"]["palette"]["paper"] = "not-a-colour"
    with pytest.raises(PackError, match="colour"):
        load_pack(_write_pack(tmp_path, data))


def test_refuses_an_unknown_palette_slot(tmp_path: Path) -> None:
    data = _pack_dict()
    data["variants"]["default"]["palette"]["neon"] = "#ff00ff"
    with pytest.raises(PackError, match="neon"):
        load_pack(_write_pack(tmp_path, data))


def test_refuses_a_font_role_with_no_fallback_stack(tmp_path: Path) -> None:
    """A single face with no generic tail — exactly the failure `fonts.py`'s
    own docstring names: a face this box lacks renders identically to one it
    has, at exit 0, unless a stack always has somewhere to fall back to."""
    data = _pack_dict()
    data["variants"]["default"]["fonts"]["title_font"] = "'Solo Face'"
    with pytest.raises(PackError, match="fallback"):
        load_pack(_write_pack(tmp_path, data))


def test_refuses_an_unknown_font_role(tmp_path: Path) -> None:
    data = _pack_dict()
    data["variants"]["default"]["fonts"]["subtitle_font"] = "'X', serif"
    with pytest.raises(PackError, match="subtitle_font"):
        load_pack(_write_pack(tmp_path, data))


def test_refuses_an_unknown_mark_key(tmp_path: Path) -> None:
    data = _pack_dict()
    data["variants"]["default"]["mark"]["subtitle"] = "nope"
    with pytest.raises(PackError, match="mark"):
        load_pack(_write_pack(tmp_path, data))


def test_refuses_an_unknown_caption_style_field(tmp_path: Path) -> None:
    data = _pack_dict()
    data["variants"]["default"]["caption_presets"] = {"clean": {"not_a_real_field": 1}}
    with pytest.raises(PackError, match="not_a_real_field"):
        load_pack(_write_pack(tmp_path, data))


def test_refuses_a_caption_preset_naming_an_unknown_base(tmp_path: Path) -> None:
    data = _pack_dict()
    data["variants"]["default"]["caption_presets"] = {"clean": {"preset": "not-a-real-preset"}}
    with pytest.raises(PackError, match="base preset"):
        load_pack(_write_pack(tmp_path, data))


def test_refuses_malformed_json(tmp_path: Path) -> None:
    path = tmp_path / "broken.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(PackError):
        load_pack(path)


def test_refuses_a_missing_file(tmp_path: Path) -> None:
    with pytest.raises(PackError):
        load_pack(tmp_path / "nowhere.json")


# -- pack_hash: content, not bytes --------------------------------------------


def test_pack_hash_ignores_key_order_and_whitespace() -> None:
    a = {"palette": {"paper": "#fff", "ink": "#000"}, "mark": {"wordmark": "X"}}
    b = {"mark": {"wordmark": "X"}, "palette": {"ink": "#000", "paper": "#fff"}}
    assert pack_hash(a) == pack_hash(b)


def test_pack_hash_changes_when_content_changes() -> None:
    a = {"palette": {"amber": "#e8a13c"}}
    b = {"palette": {"amber": "#d95f18"}}
    assert pack_hash(a) != pack_hash(b)


def test_pack_hash_is_sha256_of_sorted_json() -> None:
    payload = {"b": 1, "a": 2}
    expected = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()
    assert pack_hash(payload) == expected


def test_reformatting_the_pack_file_does_not_change_its_hash(tmp_path: Path) -> None:
    """Hashing the *resolved* payload, never the file's raw bytes — an
    upstream whitespace reformat cannot trigger a spurious `card_reauthor`
    "the pack moved" sweep."""
    data = _pack_dict()
    tight = tmp_path / "tight.json"
    tight.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
    spaced = tmp_path / "spaced.json"
    spaced.write_text(json.dumps(data, indent=4, sort_keys=False), encoding="utf-8")

    tight_hash = pack_hash(load_pack(tight)["variants"]["default"])
    spaced_hash = pack_hash(load_pack(spaced)["variants"]["default"])
    assert tight_hash == spaced_hash


# -- fonts.py's additive `source` param --------------------------------------


def test_vendored_and_install_take_a_source_directory(tmp_path: Path) -> None:
    """A pack's own font directory gets the identical treatment lucid's own
    vendored set gets, through the same functions rather than a second
    installer — `vendored(source=...)` sees only that directory, and
    `install(source=...)` copies from it, unrelated to `VENDORED_DIR`."""
    pack_fonts = tmp_path / "pack-fonts"
    pack_fonts.mkdir()
    fake = pack_fonts / "FakeFace-Bold.ttf"
    fake.write_bytes(b"not a real font, just bytes to copy and compare")

    found = fonts.vendored(pack_fonts)
    assert [p.name for p in found] == ["FakeFace-Bold.ttf"]
    # Lucid's own vendored set is unaffected — `source` narrows, it does not replace.
    assert any("Outfit" in p.name for p in fonts.vendored())

    dest = tmp_path / "installed"
    report = fonts.install(source=pack_fonts, dest=dest)
    assert report["changed"] is True
    assert (dest / "FakeFace-Bold.ttf").read_bytes() == fake.read_bytes()

    again = fonts.install(source=pack_fonts, dest=dest)
    assert again["changed"] is False
    assert again["faces"][0]["state"] == "unchanged"


# -- ops.pack_apply / pack_activate / pack_apply_captions --------------------


@needs_probe
def test_pack_apply_snapshots_every_variant_and_activates_one(project: Project) -> None:
    data = _pack_dict()
    data["variants"]["default"]["fonts"]["title_font"] = (
        "'lucid No Such Face 0000', serif"  # never draws, forces allow_fallback below
    )
    data["variants"]["october"] = {"palette": {"ink": "#111111"}}
    path = _write_pack(project.root.parent, data)

    result = ops.pack_apply(project.root, path, allow_fallback=True)
    assert result["written"] is True
    assert set(result["variants"]) == {"default", "october"}
    assert result["active_variant"] == "default"

    manifest = project.read_manifest()
    stored = manifest["pack"]
    assert stored["name"] == "test-pack"
    assert set(stored["variants"]) == {"default", "october"}
    assert "hash" in stored["variants"]["default"]
    assert stored["variants"]["default"]["font_fallback_used"] == {
        "title_font": "'lucid No Such Face 0000', serif"
    }


@needs_probe
def test_pack_apply_refuses_a_font_that_does_not_draw_without_allow_fallback(
    project: Project,
) -> None:
    data = _pack_dict()
    data["variants"]["default"]["fonts"]["title_font"] = "'lucid No Such Face 0000', serif"
    path = _write_pack(project.root.parent, data)

    with pytest.raises(ProjectError, match="does not draw"):
        ops.pack_apply(project.root, path)

    # And nothing was written on the refused call.
    assert project.read_manifest().get("pack") is None


def test_pack_apply_records_unvendored_provenance_for_a_real_but_unshipped_face(
    project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A family that genuinely draws on this box but ships in neither lucid's
    own vendored set nor the pack's own — recorded, never refused, because
    the render is correct today. `fonts.probe` is stubbed rather than relying
    on a specific non-vendored face being installed on whatever box runs this
    suite (goodsometimes' own real pack does exercise the real path with
    Zilla Slab — see its own README note — but that is this *box's* local
    font inventory, not a portable fixture)."""
    from proofcut import ops as ops_module

    def _stub_probe(family: str, **kwargs: Any) -> dict[str, Any]:
        return {"font": family, "drew": True, "rmse_against_substitute": 999.0}

    monkeypatch.setattr(ops_module.lucid_fonts, "probe", _stub_probe)

    data = _pack_dict()
    data["variants"]["default"]["fonts"]["title_font"] = "'Definitely Not Vendored Face', serif"
    path = _write_pack(project.root.parent, data)

    ops.pack_apply(project.root, path)
    stored = project.read_manifest()["pack"]["variants"]["default"]
    assert stored["font_provenance"] == {"title_font": "unvendored"}


def test_pack_apply_does_not_flag_a_family_lucid_actually_vendors(
    project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    from proofcut import ops as ops_module

    def _stub_probe(family: str, **kwargs: Any) -> dict[str, Any]:
        return {"font": family, "drew": True, "rmse_against_substitute": 999.0}

    monkeypatch.setattr(ops_module.lucid_fonts, "probe", _stub_probe)

    data = _pack_dict()
    data["variants"]["default"]["fonts"]["title_font"] = "'Outfit', sans-serif"
    path = _write_pack(project.root.parent, data)

    ops.pack_apply(project.root, path)
    stored = project.read_manifest()["pack"]["variants"]["default"]
    assert "font_provenance" not in stored


@needs_probe
def test_pack_apply_plan_resolves_and_probes_without_writing(project: Project) -> None:
    data = _pack_dict()
    path = _write_pack(project.root.parent, data)

    ops.pack_apply(project.root, path, allow_fallback=True, plan=True)
    assert project.read_manifest().get("pack") is None


def test_pack_activate_refuses_an_unknown_variant(project: Project) -> None:
    manifest = project.read_manifest()
    manifest["pack"] = {
        "name": "x",
        "source": "x.json",
        "active_variant": "default",
        "variants": {"default": {"hash": "abc"}},
        "caption_preset_applied": None,
    }
    project.write_manifest(manifest)

    with pytest.raises(ProjectError, match="no variant"):
        ops.pack_activate(project.root, "nonexistent")

    # And it did not touch the active_variant it refused to change to.
    assert project.read_manifest()["pack"]["active_variant"] == "default"


def test_pack_activate_refuses_with_no_pack_applied_at_all(project: Project) -> None:
    with pytest.raises(ProjectError, match="pack_apply"):
        ops.pack_activate(project.root, "default")


def test_pack_activate_switches_with_no_file_re_read(project: Project) -> None:
    manifest = project.read_manifest()
    manifest["pack"] = {
        "name": "x",
        "source": "/this/path/no/longer/exists.json",
        "active_variant": "default",
        "variants": {"default": {"hash": "a"}, "october": {"hash": "b"}},
        "caption_preset_applied": None,
    }
    project.write_manifest(manifest)

    result = ops.pack_activate(project.root, "october")
    assert result == {
        "project": str(project.root),
        "was": "default",
        "active_variant": "october",
        "written": True,
        "plan": False,
    }
    assert project.read_manifest()["pack"]["active_variant"] == "october"


def test_pack_apply_captions_uses_concrete_fields_not_a_live_pointer(project: Project) -> None:
    manifest = project.read_manifest()
    manifest["pack"] = {
        "name": "x",
        "source": "x.json",
        "active_variant": "default",
        "variants": {
            "default": {
                "hash": "abc",
                "caption_presets": {"loud": {"preset": "clean", "size": 90}},
            }
        },
        "caption_preset_applied": None,
    }
    project.write_manifest(manifest)

    result = ops.pack_apply_captions(project.root, "loud")
    assert result["preset"] == "loud"
    assert result["resolved"]["size"] == 90

    stored = project.read_manifest()
    assert stored["caption_style"]["size"] == 90
    # captions.py's own manifest key holds the concrete field, not the pack's
    # preset name or a pointer back to it.
    assert stored["pack"]["caption_preset_applied"] == {
        "preset": "loud",
        "variant": "default",
        "hash": "abc",
    }


def test_pack_apply_captions_refuses_an_unknown_preset(project: Project) -> None:
    manifest = project.read_manifest()
    manifest["pack"] = {
        "name": "x",
        "source": "x.json",
        "active_variant": "default",
        "variants": {"default": {"hash": "abc", "caption_presets": {}}},
        "caption_preset_applied": None,
    }
    project.write_manifest(manifest)

    with pytest.raises(ProjectError, match="no caption preset"):
        ops.pack_apply_captions(project.root, "nonexistent")


# -- ops.pack_show / pack_status ---------------------------------------------


def test_pack_show_with_a_pack_path_needs_no_project(tmp_path: Path) -> None:
    path = _write_pack(tmp_path, _pack_dict())
    result = ops.pack_show(str(path))
    assert result["file"]["name"] == "test-pack"
    assert "hash" in result["file"]["variants"]["default"]
    assert "project" not in result


def test_pack_show_with_no_pack_path_and_no_project_refuses() -> None:
    with pytest.raises(ProjectError, match="pack_path"):
        ops.pack_show()


def test_pack_show_reports_the_projects_own_snapshot(project: Project) -> None:
    manifest = project.read_manifest()
    manifest["pack"] = {
        "name": "x",
        "source": "x.json",
        "active_variant": "default",
        "variants": {"default": {"hash": "abc", "palette": {"paper": "#fff"}}},
        "caption_preset_applied": None,
    }
    project.write_manifest(manifest)

    result = ops.pack_show(path=project.root)
    assert result["project"]["applied"] is True
    assert result["project"]["variant"] == "default"
    assert result["project"]["resolved"]["palette"]["paper"] == "#fff"


def test_pack_status_reports_no_pack_applied(project: Project) -> None:
    assert ops.pack_status(project.root) == {"project": str(project.root), "applied": False}


def test_pack_status_names_stale_cards_and_caption_staleness(project: Project) -> None:
    manifest = project.read_manifest()
    manifest["pack"] = {
        "name": "x",
        "source": "x.json",
        "active_variant": "default",
        "variants": {"default": {"hash": "new-hash"}},
        "caption_preset_applied": {"preset": "loud", "variant": "default", "hash": "old-hash"},
    }
    manifest["cards"] = [
        {"card": "fresh", "template": "endcard", "slots": {}, "pack_hash": "new-hash"},
        {"card": "stale", "template": "endcard", "slots": {}, "pack_hash": "old-hash"},
        {"card": "no-pack", "template": "endcard", "slots": {}},
    ]
    project.write_manifest(manifest)

    status = ops.pack_status(project.root)
    assert status["stale_cards"] == [{"card": "stale", "recorded_hash": "old-hash"}]
    assert status["caption_preset_stale"] is True


def test_pack_status_catches_captions_going_stale_via_a_variant_switch(
    project: Project,
) -> None:
    """The hash-only comparison misses this: the *recorded* variant's own
    hash never changes just because `active_variant` moved to a different
    variant, so a caption burn made under one variant read as fresh forever
    once a project switched to another — even though the manifest's actual
    `caption_style` no longer matches anything the pack currently calls
    active."""
    manifest = project.read_manifest()
    manifest["pack"] = {
        "name": "x",
        "source": "x.json",
        "active_variant": "october",
        "variants": {
            "default": {"hash": "default-hash"},
            "october": {"hash": "october-hash"},
        },
        # Applied while "default" was active, at "default"'s own then-current
        # hash — which has not moved. Only `active_variant` has.
        "caption_preset_applied": {
            "preset": "loud",
            "variant": "default",
            "hash": "default-hash",
        },
    }
    project.write_manifest(manifest)

    status = ops.pack_status(project.root)
    assert status["caption_preset_stale"] is True


# -- card_new / card_reauthor: the pre-merge and the record ------------------


@needs_magick
def test_a_card_authored_with_no_pack_is_byte_identical_to_before_this_change(
    project: Project,
) -> None:
    """`card_new`'s pre-merge is `_active_pack_style`, which is `({}, None)`
    with no pack applied — so `{**{}, **dict(slots)} == dict(slots)`, the
    exact call `fill_template` always got. Proven by comparing against that
    call directly rather than against a stored golden file."""
    slots = {"title": "Scream", "quote": "a good time", "year": "2022", "rating": 4}
    ops.card_new(project.root, "plain", "receipt", slots)
    on_disk = (project.cards_dir / "plain.svg").read_text(encoding="utf-8")

    direct = graphics.fill_template("receipt", dict(slots), width=1920, height=816)
    assert on_disk == direct

    record = ops.card_templates()  # sanity: templates still load post-change
    assert any(t["template"] == "receipt" for t in record["templates"])

    stored = project.read_manifest()["cards"][0]
    assert "pack_hash" not in stored


@needs_magick
def test_a_card_authored_with_a_pack_pre_merges_style_slots_under_the_callers_own(
    project: Project,
) -> None:
    manifest = project.read_manifest()
    manifest["pack"] = {
        "name": "x",
        "source": "x.json",
        "active_variant": "default",
        "variants": {
            "default": {
                "hash": "pack-hash-1",
                "palette": {"paper": "#123456"},
            }
        },
        "caption_preset_applied": None,
    }
    project.write_manifest(manifest)

    ops.card_new(
        project.root,
        "styled",
        "receipt",
        {"title": "Scream", "quote": "hi", "year": "2022", "rating": 4},
    )
    svg = (project.cards_dir / "styled.svg").read_text(encoding="utf-8")
    assert "#123456" in svg  # the pack's paper, not graphics.PALETTE's own

    record = ops.card_templates()
    assert record  # unaffected by the pre-merge — sanity only

    stored = project.read_manifest()["cards"][0]
    assert stored["pack_hash"] == "pack-hash-1"
    # And the recorded *slots* are still only the caller's own — the
    # pre-merge is not baked into the record, or a later pack swap could
    # never reach a card that already exists.
    assert stored["slots"] == {"title": "Scream", "quote": "hi", "year": "2022", "rating": 4}


@needs_magick
def test_a_per_call_slot_still_wins_over_the_packs_own(project: Project) -> None:
    manifest = project.read_manifest()
    manifest["pack"] = {
        "name": "x",
        "source": "x.json",
        "active_variant": "default",
        "variants": {"default": {"hash": "h", "palette": {"paper": "#123456"}}},
        "caption_preset_applied": None,
    }
    project.write_manifest(manifest)

    ops.card_new(
        project.root,
        "overridden",
        "receipt",
        {"title": "T", "quote": "q", "year": "2022", "rating": 4, "paper": "#abcdef"},
    )
    svg = (project.cards_dir / "overridden.svg").read_text(encoding="utf-8")
    assert "#abcdef" in svg
    assert "#123456" not in svg


@needs_magick
def test_card_reauthor_redraws_a_card_when_the_pack_has_moved(project: Project) -> None:
    manifest = project.read_manifest()
    manifest["pack"] = {
        "name": "x",
        "source": "x.json",
        "active_variant": "default",
        "variants": {"default": {"hash": "hash-1", "palette": {"paper": "#111111"}}},
        "caption_preset_applied": None,
    }
    project.write_manifest(manifest)
    ops.card_new(
        project.root, "moving", "receipt", {"title": "T", "quote": "q", "year": "2022", "rating": 4}
    )

    # The pack moves — a re-apply with a different resolved palette, same
    # active variant name, new hash. `card_reauthor` never re-reads a pack
    # file; it only compares the card's own recorded hash to the manifest's
    # current active-variant hash.
    manifest = project.read_manifest()
    manifest["pack"]["variants"]["default"] = {"hash": "hash-2", "palette": {"paper": "#222222"}}
    project.write_manifest(manifest)

    result = ops.card_reauthor(project.root)
    entry = result["cards"][0]
    assert entry["why"] == "the pack moved"
    assert entry["redrawn"] is True

    svg = (project.cards_dir / "moving.svg").read_text(encoding="utf-8")
    assert "#222222" in svg
    assert project.read_manifest()["cards"][0]["pack_hash"] == "hash-2"


@needs_magick
def test_card_reauthor_plan_reports_the_pack_moved_reason_without_redrawing(
    project: Project,
) -> None:
    manifest = project.read_manifest()
    manifest["pack"] = {
        "name": "x",
        "source": "x.json",
        "active_variant": "default",
        "variants": {"default": {"hash": "hash-1"}},
        "caption_preset_applied": None,
    }
    project.write_manifest(manifest)
    ops.card_new(
        project.root, "planned", "receipt", {"title": "T", "quote": "q", "year": "2022", "rating": 4}
    )

    manifest = project.read_manifest()
    manifest["pack"]["variants"]["default"] = {"hash": "hash-2"}
    project.write_manifest(manifest)

    before = (project.cards_dir / "planned.svg").read_bytes()
    result = ops.card_reauthor(project.root, plan=True)
    assert result["cards"][0]["why"] == "the pack moved"
    assert result["cards"][0]["redrawn"] is False
    assert (project.cards_dir / "planned.svg").read_bytes() == before


# -- ops.status: the "pack" section -------------------------------------------


def test_status_reports_pack_applied_false_with_no_pack(project: Project) -> None:
    assert ops.status(project.root)["pack"] == {"applied": False}


def test_status_names_stale_cards_the_same_way_pack_status_does(project: Project) -> None:
    manifest = project.read_manifest()
    manifest["pack"] = {
        "name": "x",
        "source": "x.json",
        "active_variant": "default",
        "variants": {"default": {"hash": "new"}},
        "caption_preset_applied": None,
    }
    manifest["cards"] = [{"card": "stale", "template": "endcard", "slots": {}, "pack_hash": "old"}]
    project.write_manifest(manifest)

    pack_section = ops.status(project.root)["pack"]
    assert pack_section["applied"] is True
    assert pack_section["active_variant"] == "default"
    assert pack_section["stale_cards"] == ["stale"]


# -- ops.card_safe_zones ------------------------------------------------------


@needs_magick
def test_card_safe_zones_refuses_a_card_with_no_rendered_png(project: Project) -> None:
    with pytest.raises(ProjectError, match="no rendered PNG"):
        ops.card_safe_zones(project.root, "nonexistent", "tiktok-organic")


@needs_magick
def test_card_safe_zones_refuses_an_unknown_platform(project: Project) -> None:
    ops.card_new(project.root, "z", "endcard", {"mark": "M"})
    with pytest.raises(ProjectError, match="no safe zone"):
        ops.card_safe_zones(project.root, "z", "not-a-real-platform")


@needs_magick
def test_card_safe_zones_reports_three_numbers_relative_to_the_background(
    project: Project,
) -> None:
    ops.card_new(project.root, "z", "endcard", {"mark": "M"})
    result = ops.card_safe_zones(project.root, "z", "worst-case")

    for key in ("ink_in_band", "ink_outside_band", "background_ink", "ink_vs_background"):
        assert isinstance(result[key], float)
    # `endcard`'s own background is `ink` (TEMPLATE_BACKGROUND), so the
    # measured background matches graphics.PALETTE["ink"]'s own luminance
    # with no pack applied.
    assert result["background_ink"] == pytest.approx(graphics._hex_luminance(graphics.PALETTE["ink"]))


@needs_magick
def test_card_safe_zones_sees_a_pack_variants_own_platform(project: Project) -> None:
    manifest = project.read_manifest()
    manifest["pack"] = {
        "name": "x",
        "source": "x.json",
        "active_variant": "default",
        "variants": {
            "default": {"hash": "h", "safe_zones": {"my-platform": {"bottom_px": 200}}}
        },
        "caption_preset_applied": None,
    }
    project.write_manifest(manifest)
    ops.card_new(project.root, "z", "endcard", {"mark": "M"})

    result = ops.card_safe_zones(project.root, "z", "my-platform")
    assert result["zone"]["bottom_px"] == 200


@needs_magick
def test_card_safe_zones_resolves_background_against_the_authoring_variant(
    project: Project,
) -> None:
    """A card drawn under one variant, measured after the project activates
    a *different* one, must still be measured against the variant it was
    actually drawn from — never the pack's current active variant, which the
    card's own pixels know nothing about."""
    manifest = project.read_manifest()
    manifest["pack"] = {
        "name": "x",
        "source": "x.json",
        "active_variant": "default",
        "variants": {
            "default": {"hash": "default-hash", "palette": {"ink": "#ffffff"}},
            "other": {"hash": "other-hash", "palette": {"ink": "#000000"}},
        },
        "caption_preset_applied": None,
    }
    project.write_manifest(manifest)
    ops.card_new(project.root, "z", "endcard", {"mark": "M"})
    assert project.read_manifest()["cards"][0]["pack_hash"] == "default-hash"

    ops.pack_activate(project.root, "other")

    result = ops.card_safe_zones(project.root, "z", "worst-case")
    # The card was drawn white (`default`'s ink), not black (`other`'s) —
    # the reported background must still say white.
    assert result["background_ink"] == pytest.approx(graphics._hex_luminance("#ffffff"))


# -- Project.open on an older manifest with no "pack" key --------------------


def test_an_older_manifest_with_no_pack_key_still_opens(tmp_path: Path) -> None:
    project = Project.create(tmp_path / "old-proj")
    manifest = project.read_manifest()
    assert "pack" not in manifest  # the state every project written before this had

    reopened = Project.open(project.root)  # must not refuse, and must not migrate
    assert reopened.read_manifest() == manifest
    assert ops.pack_status(project.root) == {"project": str(project.root), "applied": False}


# -- MCP registration/reachability -------------------------------------------
#
# Its own file, per this session's scope note above: test_server_stdio.py's
# EXPECTED_TOOLS is an exact-equality set this session did not touch, so this
# proves the six new tools independently, over a real `lucid mcp` subprocess.

SERVER = StdioServerParameters(command=sys.executable, args=["-m", "proofcut.cli", "mcp"])
NEW_PACK_TOOLS = {
    "pack_apply",
    "pack_activate",
    "pack_apply_captions",
    "pack_show",
    "pack_status",
    "card_safe_zones",
}


class Client:
    def __init__(self, session: ClientSession) -> None:
        self._session = session

    async def call(self, tool: str, **arguments: Any) -> Any:
        result = await self._session.call_tool(tool, arguments)
        payload = json.loads(result.content[0].text)
        assert not result.is_error, f"{tool} failed: {payload}"
        return payload

    async def call_expecting_error(self, tool: str, **arguments: Any) -> str:
        result = await self._session.call_tool(tool, arguments)
        assert result.is_error, f"{tool} unexpectedly succeeded"
        return result.content[0].text


async def _with_server(body: Any) -> Any:
    async with (
        stdio_client(SERVER) as (read, write),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        return await body(session)


def test_all_six_pack_tools_are_registered_over_stdio() -> None:
    async def body(session: ClientSession) -> set[str]:
        tools = await session.list_tools()
        return {t.name for t in tools.tools}

    names = anyio.run(_with_server, body)
    assert NEW_PACK_TOOLS <= names


@needs_probe
def test_pack_apply_and_pack_show_round_trip_over_the_wire(tmp_path: Path) -> None:
    project = tmp_path / "proj"
    pack_path = _write_pack(tmp_path, _pack_dict())

    async def body(session: ClientSession) -> dict[str, Any]:
        client = Client(session)
        await client.call("init", path=str(project))
        applied = await client.call(
            "pack_apply", path=str(project), pack_path=str(pack_path), allow_fallback=True
        )
        assert applied["active_variant"] == "default"
        return await client.call("pack_show", path=str(project))

    out = anyio.run(_with_server, body)
    assert out["project"]["applied"] is True
    assert out["project"]["name"] == "test-pack"


def test_pack_activate_over_the_wire_refuses_an_unknown_variant(tmp_path: Path) -> None:
    project = tmp_path / "proj"

    async def body(session: ClientSession) -> str:
        client = Client(session)
        await client.call("init", path=str(project))
        return await client.call_expecting_error(
            "pack_activate", path=str(project), variant="nonexistent"
        )

    message = anyio.run(_with_server, body)
    assert "no pack applied" in message or "no variant" in message
