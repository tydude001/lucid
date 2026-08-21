"""`vo_synth` — a line in a cloned voice, rendered several times, ranked, read back, optionally spliced.

The synthesiser itself is stubbed (it is a 3.7 GB model behind another
interpreter — `tts.py`'s docstring); what is pinned here is everything the op
decides around it: which candidate wins and why, that a capped render never
wins over an uncapped one, that the readback is reported and never decides,
that the cache answers a repeat call and a widened seed range renders only
what it lacks, that a plan with nothing cached spends no GPU, and that the
splice goes through `vo_extend`'s own mechanism — a registered clip,
`Edit.insert`, `covered_by`. Built by hand rather than through `import_media`,
following `test_ops_vo_extend.py`.
"""

from __future__ import annotations

import json
import math
import struct
import wave
from pathlib import Path
from typing import Any

import pytest

from lucid import ops, tts
from lucid import timeline as tl
from lucid import transcript as tx
from lucid.project import Project

CLIP = {
    "clip_id": "vo",
    "source": "/tmp/vo.wav",
    "duration": 5.0,
    "has_video": False,
    "has_audio": True,
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
    project = Project.create(tmp_path / "proj")
    manifest = project.read_manifest()
    manifest["clips"] = [CLIP]
    project.write_manifest(manifest)
    tx.save(
        _words(
            "vo",
            ("one", 0.0, 0.5),
            ("two", 1.0, 1.5),
            ("three", 2.0, 2.5),
            ("four", 3.0, 3.5),
            ("five", 4.0, 4.5),
        ),
        project.transcript_path("vo"),
    )
    edit = tl.Edit([tl.Segment("vo", 0.0, 5.0)])
    tl.write(tl.to_otio(edit, {CLIP["clip_id"]: CLIP}, rate=1000.0), project.timeline_path)
    return project


@pytest.fixture
def voice(tmp_path: Path) -> Path:
    voice = tmp_path / "voice"
    voice.mkdir()
    _tone(voice / "ref.wav", 2.0)
    (voice / "ref.txt").write_text("the reference words", encoding="utf-8")
    return voice


def _tone(path: Path, seconds: float, rate: int = 24000) -> None:
    with wave.open(str(path), "w") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        n = int(seconds * rate)
        out.writeframes(b"".join(struct.pack("<h", int(8000 * math.sin(2 * math.pi * 220 * i / rate))) for i in range(n)))


def _stub(monkeypatch: pytest.MonkeyPatch, answers: dict[int, dict[str, Any]]) -> list[list[int]]:
    """Stand in for the worker: `answers` is seed → {sim, duration[, capped]}; records each call's seeds."""
    calls: list[list[int]] = []

    def fake_synth(text: str, voice: Path, out_dir: Path, seeds: list[int], *, max_seconds: float, language: str = "English"):
        calls.append(list(seeds))
        out_dir.mkdir(parents=True, exist_ok=True)
        out = []
        for seed in seeds:
            spec = answers[seed]
            if "error" in spec:
                out.append({"seed": seed, "error": spec["error"]})
                continue
            path = out_dir / f"s{seed}.wav"
            _tone(path, spec["duration"])
            out.append({"seed": seed, "path": str(path), "duration": spec["duration"], "sim": spec["sim"], "capped": spec.get("capped", False)})
        return out

    monkeypatch.setattr(tts, "available", lambda voice=None: {"available": True, "python": "/stub", "model": "/stub", "voice": "/stub", "why": None})
    monkeypatch.setattr(tts, "synth", fake_synth)
    monkeypatch.setattr(ops.asr, "transcribe", lambda path, model=None, language=None: {"segments": [{"text": "hello there world"}]})
    return calls


# -- ranking -----------------------------------------------------------------


def test_the_highest_likeness_wins_and_the_readback_is_reported(project: Project, voice: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _stub(monkeypatch, {0: {"sim": 0.981, "duration": 1.0}, 1: {"sim": 0.990, "duration": 1.2}, 2: {"sim": 0.985, "duration": 0.9}})

    result = ops.vo_synth(project.root, "hello there, world", voice=str(voice))

    assert calls == [[0, 1, 2]]
    assert result["chosen"]["seed"] == 1
    assert [c["seed"] for c in result["candidates"]] == [0, 1, 2]
    assert result["heard"] == "hello there world"
    assert result["wer"] == 0.0
    assert result["written"] is False and result["cached"] is False
    assert Path(result["chosen"]["path"]).is_file()
    assert Path(result["cache_dir"]).is_relative_to(project.root / "cache" / "synth")


def test_a_tie_goes_to_the_lower_seed(project: Project, voice: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _stub(monkeypatch, {0: {"sim": 0.99, "duration": 1.0}, 1: {"sim": 0.99, "duration": 1.0}, 2: {"sim": 0.98, "duration": 1.0}})
    assert ops.vo_synth(project.root, "x", voice=str(voice))["chosen"]["seed"] == 0


def test_a_capped_render_never_wins_while_an_uncapped_one_exists(project: Project, voice: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A render at the cap did not end because the line ended. Round 2's 655 s
    renders scored fine on likeness for their first seconds; the cap is what
    makes them visible and the ranking is what keeps them out."""
    _stub(monkeypatch, {0: {"sim": 0.999, "duration": 19.6, "capped": True}, 1: {"sim": 0.980, "duration": 1.0}})
    result = ops.vo_synth(project.root, "x", voice=str(voice), candidates=2)
    assert result["chosen"]["seed"] == 1
    assert result["capped"] == [0]


def test_a_failed_seed_is_reported_and_the_others_still_answer(project: Project, voice: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _stub(monkeypatch, {0: {"error": "RuntimeError: CUDA"}, 1: {"sim": 0.98, "duration": 1.0}})
    result = ops.vo_synth(project.root, "x", voice=str(voice), candidates=2)
    assert result["chosen"]["seed"] == 1
    assert result["candidates"][0]["error"].startswith("RuntimeError")


def test_every_seed_failing_is_a_refusal_naming_each(project: Project, voice: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _stub(monkeypatch, {0: {"error": "RuntimeError: a"}, 1: {"error": "RuntimeError: b"}})
    with pytest.raises(tts.TTSError, match="seed 0: RuntimeError: a; seed 1"):
        ops.vo_synth(project.root, "x", voice=str(voice), candidates=2)


# -- cache -------------------------------------------------------------------


def test_a_repeat_call_answers_from_the_cache_and_a_wider_range_renders_only_what_it_lacks(project: Project, voice: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _stub(monkeypatch, {s: {"sim": 0.98 + s / 1000, "duration": 1.0} for s in range(5)})
    first = ops.vo_synth(project.root, "same line", voice=str(voice))
    again = ops.vo_synth(project.root, "same   line ", voice=str(voice))  # whitespace-normalised: same key
    wider = ops.vo_synth(project.root, "same line", voice=str(voice), candidates=5)

    assert calls == [[0, 1, 2], [3, 4]]
    assert again["cached"] is True and again["cache_dir"] == first["cache_dir"]
    assert wider["chosen"]["seed"] == 4
    meta = json.loads((Path(first["cache_dir"]) / "candidates.json").read_text())
    assert [c["seed"] for c in meta] == [0, 1, 2, 3, 4]


def test_a_plan_with_nothing_cached_spends_no_gpu_and_says_so(project: Project, voice: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _stub(monkeypatch, {})
    result = ops.vo_synth(project.root, "fresh", voice=str(voice), plan=True)
    assert calls == []
    assert result["rendered"] is False and result["missing_seeds"] == [0, 1, 2]
    assert result["plan"] is True and result["written"] is False


def test_a_plan_over_a_cached_line_ranks_without_reading_back(project: Project, voice: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _stub(monkeypatch, {0: {"sim": 0.97, "duration": 1.0}, 1: {"sim": 0.99, "duration": 1.0}, 2: {"sim": 0.98, "duration": 1.0}})
    ops.vo_synth(project.root, "cached line", voice=str(voice))
    planned = ops.vo_synth(project.root, "cached line", voice=str(voice), plan=True)
    assert planned["rendered"] is True and planned["chosen"]["seed"] == 1
    assert "heard" not in planned


# -- refusals ----------------------------------------------------------------


def test_no_synthesiser_is_a_refusal_naming_what_was_looked_for(project: Project, voice: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tts, "available", lambda voice=None: {"available": False, "why": "no interpreter with a voice synthesiser. Looked at $LUCID_TTS"})
    with pytest.raises(tts.TTSError, match="LUCID_TTS"):
        ops.vo_synth(project.root, "x", voice=str(voice))


def test_a_voice_missing_its_transcript_is_refused_by_name(project: Project, tmp_path: Path) -> None:
    bare = tmp_path / "bare"
    bare.mkdir()
    _tone(bare / "ref.wav", 1.0)
    with pytest.raises(tts.TTSError, match="missing ref.txt"):
        ops.vo_synth(project.root, "x", voice=str(bare))


def test_clip_and_word_go_together(project: Project, voice: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _stub(monkeypatch, {})
    with pytest.raises(tl.TimelineError, match="both or neither"):
        ops.vo_synth(project.root, "x", voice=str(voice), clip_id="vo")


def test_empty_text_is_refused(project: Project, voice: Path) -> None:
    with pytest.raises(tl.TimelineError, match="empty"):
        ops.vo_synth(project.root, "   ", voice=str(voice))


# -- the splice --------------------------------------------------------------


def test_the_winner_is_spliced_after_the_word_through_vo_extends_mechanism(project: Project, voice: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _stub(monkeypatch, {0: {"sim": 0.98, "duration": 1.5}, 1: {"sim": 0.99, "duration": 2.0}, 2: {"sim": 0.97, "duration": 1.0}})

    result = ops.vo_synth(project.root, "hello there world", voice=str(voice), clip_id="vo", word_index=2)

    splice = result["splice"]
    assert result["written"] is True and splice["written"] is True
    assert splice["text"] == "three"
    assert splice["timeline_start"] == pytest.approx(2.5)
    assert splice["seconds"] == pytest.approx(2.0)
    assert splice["duration_after"] == pytest.approx(splice["duration_before"] + 2.0)
    assert splice["covered_by"] == []

    manifest = Project.open(project.root).read_manifest()
    registered = {c["clip_id"] for c in manifest["clips"]}
    assert splice["hold_clip_id"] in registered and splice["hold_clip_id"].startswith("synth-")
    assert splice["hold_clip_id"].endswith("-s1")
    edit = ops._load_edit(Project.open(project.root))
    assert [s.clip_id for s in edit.segments] == ["vo", splice["hold_clip_id"], "vo"]
    assert edit.duration == pytest.approx(7.0)


def test_a_planned_splice_writes_nothing_and_reports_a_placeholder(project: Project, voice: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _stub(monkeypatch, {0: {"sim": 0.98, "duration": 1.5}, 1: {"sim": 0.99, "duration": 2.0}, 2: {"sim": 0.97, "duration": 1.0}})
    ops.vo_synth(project.root, "hello there world", voice=str(voice))  # render, so the plan can rank
    before = project.timeline_path.read_bytes()

    result = ops.vo_synth(project.root, "hello there world", voice=str(voice), clip_id="vo", word_index=2, plan=True)

    assert result["written"] is False and result["splice"]["written"] is False
    assert result["splice"]["hold_clip_id"].startswith("synth-")
    assert result["splice"]["duration_after"] == pytest.approx(7.0)
    assert project.timeline_path.read_bytes() == before
    assert {c["clip_id"] for c in Project.open(project.root).read_manifest()["clips"]} == {"vo"}


def test_a_splice_after_cut_material_is_refused_before_anything_is_rendered(project: Project, voice: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The refusal is `vo_extend`'s; what this adds is the order. The render is
    the expensive half (a model load and three GPU passes), so a call that is
    about to be refused must be refused first — `_splice_point` runs before
    the synthesiser does, and nothing lands in the cache."""
    calls = _stub(monkeypatch, {0: {"sim": 0.98, "duration": 1.0}, 1: {"sim": 0.99, "duration": 1.0}, 2: {"sim": 0.97, "duration": 1.0}})
    edit = tl.Edit([tl.Segment("vo", 0.0, 1.0), tl.Segment("vo", 3.0, 5.0)])
    tl.write(tl.to_otio(edit, {CLIP["clip_id"]: CLIP}, rate=1000.0), project.timeline_path)
    before = project.timeline_path.read_bytes()
    with pytest.raises(tl.TimelineError, match="not on the timeline"):
        ops.vo_synth(project.root, "x", voice=str(voice), clip_id="vo", word_index=2)
    assert calls == []
    assert not (project.root / "cache" / "synth").exists()
    assert project.timeline_path.read_bytes() == before


# -- no built-in voice -------------------------------------------------------


def test_there_is_no_default_voice(project: Project, monkeypatch: pytest.MonkeyPatch) -> None:
    """A voice is a person, not tooling: with neither `voice=` nor
    `LUCID_TTS_VOICE` the op refuses by name rather than reaching for a path
    baked into the package — so a public checkout has no pointer to anyone's
    reference clip."""
    monkeypatch.delenv("LUCID_TTS_VOICE", raising=False)
    with pytest.raises(tts.TTSError, match="no voice.*LUCID_TTS_VOICE.*no default voice"):
        ops.vo_synth(project.root, "x")
    assert tts.available()["available"] is False
    assert "no voice" in tts.available()["why"]

