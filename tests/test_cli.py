"""CLI-only behaviour: timecode parsing, and how `init` resolves a directory.

Both live only in the CLI by design, so the stdio suite cannot reach them.
`cut-at`'s whole value rests on the span parsing; `init`'s on not creating a
project somewhere the caller did not name.

One exception: `test_cut_through_pause_flag_parses_and_reaches_ops` below,
which checks the CLI-specific plumbing for `cut --through-pause`
(argparse's `store_true` reaching `ops.cut_by_transcript` under the right
keyword) — the underlying behaviour it enables is already covered end-to-end
over the wire in test_server_stdio.py; this only guards the one hop that
file cannot reach, since it never spawns `lucid cut` itself.
"""

from __future__ import annotations

import argparse
import json
import math
import shutil
import struct
import wave
from pathlib import Path

import pytest

from lucid.cli import _parse_timecode, _slot_assignments, _time_span, main
from lucid.project import ProjectError

needs_ffprobe = pytest.mark.skipif(
    shutil.which("ffprobe") is None, reason="ffprobe is not installed"
)


def test_parse_timecode_reads_colon_parts_optional_from_the_right() -> None:
    assert _parse_timecode("4.4") == pytest.approx(4.4)
    assert _parse_timecode("0:40.4") == pytest.approx(40.4)
    assert _parse_timecode("1:00:40.4") == pytest.approx(3640.4)


def test_time_span_start_plus_duration() -> None:
    assert _time_span("0:40.4+4.4") == pytest.approx([40.4, 44.8])


def test_time_span_start_dash_end() -> None:
    assert _time_span("0:40.4-0:44.8") == pytest.approx([40.4, 44.8])


def test_time_span_rejects_garbage() -> None:
    with pytest.raises(argparse.ArgumentTypeError):
        _time_span("banana")


# -- `init` and the global `-C` -------------------------------------------
#
# `init` is the one subcommand whose directory is an argument rather than a
# lookup, so it is the one place `-C` and a positional can disagree. It used
# to read only the positional, which made `lucid -C myproj init` create a
# project in the *current* directory and report success.


def _project_exists(root: Path) -> bool:
    return (root / "lucid.json").is_file()


def test_init_honours_the_global_project_flag(tmp_path: Path) -> None:
    assert main(["-C", str(tmp_path / "proj"), "init"]) == 0
    assert _project_exists(tmp_path / "proj")


def test_init_still_takes_a_positional_path(tmp_path: Path) -> None:
    assert main(["init", str(tmp_path / "proj")]) == 0
    assert _project_exists(tmp_path / "proj")


def test_init_refuses_two_different_directories(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Neither spelling silently wins — the old behaviour picked the positional
    and created a project somewhere the caller had not named.
    """
    assert main(["-C", str(tmp_path / "flag"), "init", str(tmp_path / "positional")]) == 1
    assert not _project_exists(tmp_path / "flag")
    assert not _project_exists(tmp_path / "positional")
    assert "two directories" in capsys.readouterr().err


def test_init_with_neither_uses_the_working_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    assert main(["init"]) == 0
    assert _project_exists(tmp_path)


def test_explicit_dash_c_dot_is_not_mistaken_for_an_unset_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`-C .` is a real answer, so pairing it with a positional is still the
    two-directories error rather than being waved through as "no -C given".
    """
    monkeypatch.chdir(tmp_path)
    assert main(["-C", ".", "init", "proj"]) == 1
    assert not _project_exists(tmp_path)
    assert not _project_exists(tmp_path / "proj")


# -- `card reauthor` -------------------------------------------------------
#
# The behaviour is proven over the wire in test_server_stdio.py and against
# ops in test_ops_card_reauthor.py. What only the CLI has is the optional
# positional: `card reauthor` with no name is the sweep, and argparse would
# otherwise make that a usage error rather than the common case.


def test_card_reauthor_takes_no_name_and_means_every_card(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    project = tmp_path / "proj"
    assert main(["-C", str(project), "init"]) == 0
    capsys.readouterr()

    assert main(["-C", str(project), "card", "reauthor", "--plan"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["cards"] == []
    assert out["plan"] is True


# -- `cut --through-pause` -------------------------------------------------
#
# The behaviour `through_pause` enables is proven end-to-end over the wire in
# test_server_stdio.py; what only a real `lucid cut` invocation can prove is
# that the flag's plumbing through argparse actually reaches `ops` under the
# right keyword.


def _make_wav(path: Path, *, tones: list[tuple[float, float]], duration: float = 12.0) -> None:
    """A wav with tone bursts at `tones` and silence elsewhere — the same
    shape test_server_stdio.py's `sources` fixture builds, kept local here so
    this file stays free of a cross-file import for one helper.
    """
    rate = 22050
    with wave.open(str(path), "w") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        frames = bytearray()
        for i in range(int(rate * duration)):
            t = i / rate
            loud = any(a <= t < b for a, b in tones)
            value = int(12000 * math.sin(2 * math.pi * 220 * t)) if loud else 0
            frames += struct.pack("<h", value)
        out.writeframes(bytes(frames))


def _make_sources(root: Path) -> tuple[Path, Path]:
    """A four-burst recording and a transcript with two words per burst —
    words 0.1s apart within a burst, 1.1s apart across a burst boundary, so
    word 3 -> word 4's gap (1.1s) clears PAUSE_MARKER_MIN and word 0 -> word
    1's gap (0.1s) does not.
    """
    audio = root / "vo.wav"
    _make_wav(audio, tones=[(0.0, 2.0), (3.0, 5.0), (6.0, 8.0), (9.0, 11.0)])

    words = []
    for burst, (start, _) in enumerate([(0.0, 2.0), (3.0, 5.0), (6.0, 8.0), (9.0, 11.0)]):
        for n in range(2):
            at = start + n
            words.append({"word": f"w{burst}{n}", "start": at, "end": at + 0.9})

    transcript = root / "vo.json"
    transcript.write_text(json.dumps({"language": "en", "words": words}), encoding="utf-8")
    return audio, transcript


@needs_ffprobe
def test_cut_through_pause_flag_parses_and_reaches_ops(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    project = tmp_path / "proj"
    audio, transcript = _make_sources(project.parent)

    assert main(["-C", str(project), "init"]) == 0
    capsys.readouterr()
    assert main(["-C", str(project), "import", str(audio)]) == 0
    clip_id = json.loads(capsys.readouterr().out)["clip_id"]
    assert main(["-C", str(project), "attach-transcript", clip_id, str(transcript)]) == 0
    capsys.readouterr()
    assert main(["-C", str(project), "seed", clip_id, "--keep-silences"]) == 0
    capsys.readouterr()

    # Word 3 (w11, end 4.9s) sits right before the 1.1s gap to word 4 (w20,
    # start 6.0s) — wide enough to have drawn a `[1.1s]` marker.
    assert main(["-C", str(project), "cut", clip_id, "2:3", "--through-pause", "--plan"]) == 0
    plan = json.loads(capsys.readouterr().out)
    applied = plan["applied"][0]
    assert applied["word_end"] == pytest.approx(4.9)
    assert applied["source_end"] == pytest.approx(6.0)

    # Without the flag, the same range's boundary stays at the word's own end.
    assert main(["-C", str(project), "cut", clip_id, "2:3", "--plan"]) == 0
    plain = json.loads(capsys.readouterr().out)
    assert plain["applied"][0]["source_end"] == pytest.approx(4.9)


@needs_ffprobe
def test_transcript_checks_clip_id_is_optional(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The one hop the stdio suite cannot reach: argparse's `nargs="?"`
    reaching `ops.transcript_checks` as None, which is what makes
    `lucid transcript-checks` with no argument mean "every clip with a
    transcript" rather than a missing-argument error.
    """
    project = tmp_path / "proj"
    audio, transcript = _make_sources(project.parent)

    assert main(["-C", str(project), "init"]) == 0
    capsys.readouterr()
    assert main(["-C", str(project), "import", str(audio)]) == 0
    clip_id = json.loads(capsys.readouterr().out)["clip_id"]
    assert main(["-C", str(project), "attach-transcript", clip_id, str(transcript)]) == 0
    capsys.readouterr()

    assert main(["-C", str(project), "transcript-checks"]) == 0
    every = json.loads(capsys.readouterr().out)
    assert [c["clip_id"] for c in every["clips"]] == [clip_id]
    assert {"near_duplicates", "suspect_durations", "overlaps"} <= set(every["clips"][0])

    # Naming the clip explicitly reaches the same result.
    assert main(["-C", str(project), "transcript-checks", clip_id]) == 0
    named = json.loads(capsys.readouterr().out)
    assert named == every


# -- `restore` --------------------------------------------------------------
#
# The op itself is proven end-to-end over the wire in test_server_stdio.py;
# what only a real `lucid restore` invocation can prove is that argparse's
# word-range/`--pad`/`--plan` plumbing actually reaches `ops.restore` under
# the right keywords.


@needs_ffprobe
def test_restore_flag_parses_and_reaches_ops(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    project = tmp_path / "proj"
    audio, transcript = _make_sources(project.parent)

    assert main(["-C", str(project), "init"]) == 0
    capsys.readouterr()
    assert main(["-C", str(project), "import", str(audio)]) == 0
    clip_id = json.loads(capsys.readouterr().out)["clip_id"]
    assert main(["-C", str(project), "attach-transcript", clip_id, str(transcript)]) == 0
    capsys.readouterr()
    assert main(["-C", str(project), "seed", clip_id, "--keep-silences"]) == 0
    capsys.readouterr()

    assert main(["-C", str(project), "cut", clip_id, "2:3"]) == 0
    cut = json.loads(capsys.readouterr().out)
    assert cut["removed"] > 0.0

    # --plan resolves the same numbers a real restore would, without writing.
    assert main(["-C", str(project), "restore", clip_id, "2:3", "--plan"]) == 0
    planned = json.loads(capsys.readouterr().out)
    assert planned["plan"] is True
    assert planned["applied"][0]["already_present"] is False
    assert planned["restored"] == pytest.approx(cut["removed"], abs=1e-6)

    # The real call reverses the cut exactly.
    assert main(["-C", str(project), "restore", clip_id, "2:3"]) == 0
    restored = json.loads(capsys.readouterr().out)
    assert restored["restored"] == pytest.approx(cut["removed"], abs=1e-6)
    assert restored["applied"][0]["already_present"] is False

    # A second restore of the same, now-present range is a no-op, not an error.
    assert main(["-C", str(project), "restore", clip_id, "2:3"]) == 0
    noop = json.loads(capsys.readouterr().out)
    assert noop["applied"][0]["already_present"] is True
    assert noop["restored"] == pytest.approx(0.0)


# -- `export --preset`/`--resolution` ----------------------------------------
#
# `ops.export` itself, its presets, and the resolution/melt/NLE refusals are
# proven end-to-end over the wire in test_server_stdio.py; this only guards
# the CLI-specific hop those tests cannot reach — `_resolution`'s own parsing,
# and that `--preset`/`--resolution` reach `ops.export` under the right
# keywords.


def test_resolution_reads_widthxheight() -> None:
    from lucid.cli import _resolution

    assert _resolution("1920x1080") == (1920, 1080)
    assert _resolution("608x1080") == (608, 1080)


def test_resolution_rejects_garbage() -> None:
    from lucid.cli import _resolution

    with pytest.raises(argparse.ArgumentTypeError):
        _resolution("banana")
    with pytest.raises(argparse.ArgumentTypeError):
        _resolution("1920")


def test_export_preset_and_resolution_flags_reach_ops(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    project = tmp_path / "proj"
    audio, transcript = _make_sources(project.parent)

    assert main(["-C", str(project), "init"]) == 0
    capsys.readouterr()
    assert main(["-C", str(project), "import", str(audio)]) == 0
    clip_id = json.loads(capsys.readouterr().out)["clip_id"]
    assert main(["-C", str(project), "attach-transcript", clip_id, str(transcript)]) == 0
    capsys.readouterr()
    assert main(["-C", str(project), "seed", clip_id, "--keep-silences"]) == 0
    capsys.readouterr()

    # An unknown preset is refused by ops.export, not silently accepted —
    # argparse's own `choices=` can't even construct this call, so this
    # proves the CLI hop reaches ops.export's own check for 'custom' without
    # a resolution.
    out = tmp_path / "out.wav"
    assert main(["-C", str(project), "export", str(out), "--render", "--preset", "custom"]) == 1
    err = capsys.readouterr().err
    assert "custom" in err

    # `--preset`/`--resolution` do reach ops.export under the right keywords:
    # a bare NLE export (the default `--format kdenlive`, no `--render`)
    # combined with `--preset` is refused for the "no bitrate" reason, which
    # only fires if `preset` actually arrived at ops.export.
    assert (
        main(
            [
                "-C",
                str(project),
                "export",
                str(tmp_path / "out.kdenlive"),
                "--preset",
                "youtube",
            ]
        )
        == 1
    )
    err = capsys.readouterr().err
    assert "bitrate" in err


def test_slot_assignments_parses_pairs_and_the_newline_escape() -> None:
    """CLI-only plumbing: `--set` pairs, and `\\n` standing in for a line break.

    The escape lives here rather than in `graphics` because it is a shell
    problem — the op and the MCP tool both take a string with real newlines
    already in it.
    """
    assert _slot_assignments(["title=Scream", "year=1996"]) == {
        "title": "Scream",
        "year": "1996",
    }
    assert _slot_assignments([r"quote=one\ntwo"]) == {"quote": "one\ntwo"}
    # A value containing `=` keeps it; only the first one separates.
    assert _slot_assignments(["date_line=watched 2021 — a=b"]) == {
        "date_line": "watched 2021 — a=b"
    }


def test_slot_assignments_refuses_a_pair_with_no_equals() -> None:
    with pytest.raises(ProjectError, match="SLOT=VALUE"):
        _slot_assignments(["title"])


# -- `info` and the 103 KB manifest ---------------------------------------
#
# Descriptions live in the manifest, and `info` prints the manifest — which
# took a described project's `info` to 103 KB of prose in a command whose job
# is being readable at a glance. `describe-ls` is where that text is meant to
# be read, so `info` points at it. Substituting a summary is only honest with
# an escape hatch, which is what `--raw` is and why it is asserted here.


def _described_project(tmp_path: Path) -> Path:
    from lucid.project import Project

    root = tmp_path / "proj"
    project = Project.create(root)
    manifest = project.read_manifest()
    manifest["clips"] = [
        {"clip_id": "clipa", "source": "/tmp/a.mp4", "duration": 25.0, "has_video": True}
    ]
    manifest["descriptions"] = [
        {"clip_id": "clipa", "src_start": 0.0, "src_end": 12.5, "text": "A kitchen."},
        {"clip_id": "clipa", "src_start": 12.5, "src_end": 25.0, "text": "A car."},
    ]
    project.write_manifest(manifest)
    return root


def test_info_stands_descriptions_down_to_a_count(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["-C", str(_described_project(tmp_path)), "info"]) == 0
    out = json.loads(capsys.readouterr().out)

    assert out["descriptions"] == {
        "count": 2,
        "clips": {"clipa": 2},
        "read": "lucid describe-ls (or `lucid info --raw` for the stored entries)",
    }
    # Everything else is still the manifest, verbatim.
    assert out["clips"][0]["clip_id"] == "clipa"


def test_info_raw_still_prints_the_stored_entries(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Nothing else in lucid can show you what is actually on disk."""
    assert main(["-C", str(_described_project(tmp_path)), "info", "--raw"]) == 0
    out = json.loads(capsys.readouterr().out)

    assert [d["text"] for d in out["descriptions"]] == ["A kitchen.", "A car."]


def test_info_on_an_undescribed_project_is_untouched(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The summary is a substitution, so it must not appear where there is
    nothing to substitute — an empty list stays the empty list `describe`
    wrote."""
    assert main(["init", str(tmp_path / "plain")]) == 0
    capsys.readouterr()

    assert main(["-C", str(tmp_path / "plain"), "info"]) == 0
    assert json.loads(capsys.readouterr().out)["descriptions"] == []


@needs_ffprobe
def test_reel_span_parses_and_reaches_ops_as_two_arguments(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The one hop the stdio suite cannot reach: `reel` takes `START+DURATION`
    on the command line, because that is how a watch-note is phrased, and the
    op takes `start=`/`end=` because that is what an agent can pass. Unpacking
    the pair is CLI-only plumbing, and getting it backwards would read as a
    correct span right up until the reel came out wrong.
    """
    project = tmp_path / "proj"
    audio, transcript = _make_sources(project.parent)

    assert main(["-C", str(project), "init"]) == 0
    capsys.readouterr()
    assert main(["-C", str(project), "import", str(audio)]) == 0
    clip_id = json.loads(capsys.readouterr().out)["clip_id"]
    assert main(["-C", str(project), "attach-transcript", clip_id, str(transcript)]) == 0
    capsys.readouterr()
    assert main(["-C", str(project), "seed", clip_id, "--keep-silences"]) == 0
    capsys.readouterr()

    assert main(["-C", str(project), "reel", str(tmp_path / "teaser"), "0:03+5", "--plan"]) == 0
    planned = json.loads(capsys.readouterr().out)

    assert planned["keep"] == pytest.approx([3.0, 8.0]), "a length, not a second timestamp"
    head, tail = planned["cut"]
    assert head == pytest.approx([0.0, 3.0])
    assert tail[0] == pytest.approx(8.0)
    assert tail[1] == pytest.approx(planned["source_duration"])
    assert not (tmp_path / "teaser").exists()
