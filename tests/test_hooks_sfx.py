"""Hook optimization (frame 0, lead trim, variants) and the sound-effects layer."""

import json
import re
import shutil
from pathlib import Path

import pytest

from klip import ffmpeg
from klip.paths import ROOT
from klip.spec import Spec, load_spec
from klip.stages import compose, post, script, voice

GOOD = json.loads((ROOT / "examples" / "tidur-siang.json").read_text())
needs_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")
needs_renderer = pytest.mark.skipif(not (compose.NODE_MODULES / "lucide-static").exists(),
                                    reason="renderer/node_modules not installed")

VARIANTS = [{"narration": "Tidur siang itu buat orang malas? Salah besar.", "on_screen_text": "Salah besar!"},
            {"narration": "Kalau tidur siangmu lebih dari 30 menit, pantesan pusing."}]


# ---- variants

def test_hook_variant_replaces_only_scene_one():
    spec = Spec.model_validate({**GOOD, "hook_variants": VARIANTS})
    b, c = spec.with_hook_variant(0), spec.with_hook_variant(1)
    assert b.scenes[0].narration == VARIANTS[0]["narration"] and b.scenes[0].on_screen_text == "Salah besar!"
    assert c.scenes[0].on_screen_text == spec.scenes[0].on_screen_text      # unset → main hook's
    assert b.scenes[1:] == spec.scenes[1:] and not b.hook_variants


def test_variants_require_hook_template():
    scenes = json.loads(json.dumps(GOOD["scenes"]))
    scenes[0]["template"] = "explain"
    with pytest.raises(ValueError, match="hook_variants requires"):
        Spec.model_validate({**GOOD, "scenes": scenes, "hook_variants": VARIANTS})


class FakeLLM:
    name = "fake"

    def __init__(self, answers):
        self.answers, self.prompts = list(answers), []

    def complete(self, system, user, schema):
        self.prompts.append(user)
        return self.answers.pop(0)


def test_generate_with_hooks_requires_variants():
    llm = FakeLLM([GOOD, {**GOOD, "hook_variants": VARIANTS}])
    res = script.generate("x", "female", 45, provider=llm, hooks=3)
    assert len(res.spec.hook_variants) == 2
    assert "alternative hook" in llm.prompts[0] and "write exactly 2" in llm.prompts[1]


def test_run_variants_renders_each_into_its_own_dir(tmp_path, monkeypatch):
    from klip import pipeline
    spec = Spec.model_validate({**GOOD, "hook_variants": VARIANTS})
    seen = []

    def fake_run_all(vspec, vdir, on_stage=None, **k):
        seen.append((vspec.scenes[0].narration, vdir))
        if vdir.name == "C":
            raise RuntimeError("tts down")
        return {"post": {"final": str(vdir / "final.mp4"), "duration_s": 44.0}, "qa": {"passed": True}}

    monkeypatch.setattr(pipeline, "run_all", fake_run_all)
    main = {"post": {"final": "main.mp4", "duration_s": 45.0}, "qa": {"passed": True}}
    rows = pipeline.run_variants(spec, tmp_path, main)
    assert [r["variant"] for r in rows] == ["A", "B", "C"]
    assert seen[0] == (VARIANTS[0]["narration"], tmp_path / "variants" / "B")
    assert rows[2]["qa_passed"] is False and "tts down" in rows[2]["error"]
    assert json.loads((tmp_path / "variants.json").read_text())[1]["final"].endswith("B/final.mp4")


# ---- frame 0 / lead trim

@needs_ffmpeg
def test_hook_lead_silence_is_trimmed(tmp_path, monkeypatch):
    class LateStarter:
        name = "edge"

        def synthesize(self, text, voice_id, rate, out_path, **kw):
            ffmpeg.run(["-f", "lavfi", "-i", "sine=f=300:d=2", "-c:a", "libmp3lame", str(out_path)])
            # first word at 400 ms (+100 ms engine offset from klip.yaml = 500 ms)
            return [script_word(t, 400 + i * 250) for i, t in enumerate(text.split())]

    monkeypatch.setattr(voice, "CACHE_DIR", tmp_path / "cache")
    spec = Spec.model_validate({"slug": "t", "scenes": [
        {"id": "a", "template": "hook", "narration": "satu dua tiga"},
        {"id": "b", "template": "cta", "narration": "empat lima"}]})
    proj = tmp_path / "p"
    proj.mkdir()
    tl = voice.run(spec, proj, engine=LateStarter())
    words = json.loads((proj / "words.json").read_text())
    assert words[0]["startMs"] == pytest.approx(voice.HOOK_LEAD_MS, abs=1)
    assert tl["scenes"][0]["audio"].endswith(".wav")                      # trimmed copy
    assert words[3]["startMs"] - tl["scenes"][1]["start_ms"] == pytest.approx(500, abs=1)  # scene 2 untouched


def script_word(text, start):
    from klip.engines.tts.base import Word
    return Word(text, start, start + 200)


@needs_ffmpeg
@needs_renderer
def test_hook_visible_at_frame_zero(tmp_path, monkeypatch):
    from tests.test_pipeline import FakeTTS
    monkeypatch.setattr(voice, "CACHE_DIR", tmp_path / "cache")
    spec = load_spec(ROOT / "examples" / "tidur-siang.json")
    proj = tmp_path / "p"
    proj.mkdir()
    voice.run(spec, proj, engine=FakeTTS())
    compose.run(spec, proj)
    html = (proj / "composition" / "index.html").read_text()
    hook_js = html.split("// ---- scene s1 (hook)")[1].split("// ---- scene s2")[0]
    assert "opacity: 0" not in hook_js                                    # nothing fades in on the hook
    assert 'id="p0" class="cap clip" data-start="0.0"' in html            # first caption page at frame 0


# ---- SFX

def scene(idx, template, start, dur=4.0, **t):
    return {"idx": idx, "template": template, "start": start, "dur": dur, "icon": "<svg/>", "t": t}


def test_sfx_events_follow_visual_moments():
    scenes = [scene(0, "hook", 0.0), scene(1, "myth_fact", 4.0, reveal=6.0), scene(2, "list_item", 9.0),
              scene(3, "stat", 12.0), scene(4, "compare", 16.0), scene(5, "cta", 20.0)]
    ev = {(e["moment"], e["t"]) for e in compose.sfx_events(scenes, [{"start": 0.0}])}
    assert ("hook_start", 0.0) in ev and ("fact_reveal", 6.0) in ev and ("myth_riser", 5.0) in ev
    assert ("scene_cut", round(4.0 - compose.WHOOSH_PEAK_S, 3)) in ev
    assert ("stat_land", 13.4) in ev and ("compare_vs", 16.7) in ev and ("cta_icon", 20.0) in ev
    assert not any(m == "caption_page" for m, _ in ev)                    # off by default


@needs_ffmpeg
def test_build_sfx_places_cues_and_mixes(tmp_path):
    if not post.sfx_file("ding"):
        pytest.skip("default sfx not generated (scripts/make_sfx.py)")
    out = tmp_path / "sfx.wav"
    assert post.build_sfx([{"t": 1.0, "moment": "stat_land", "sfx": "ding"},
                           {"t": 2.5, "moment": "x", "sfx": "does-not-exist"}], 4.0, out)
    assert ffmpeg.duration_ms(out) == pytest.approx(4000, abs=30)

    def level(start):
        err = ffmpeg.run(["-ss", str(start), "-t", "0.3", "-i", str(out), "-af", "volumedetect", "-f", "null", "-"]).stderr
        m = re.search(r"max_volume: (-?[\d.]+|-inf) dB", err)
        return float(m.group(1)) if m and m.group(1) != "-inf" else -200

    assert level(1.0) > -40 and level(0.2) < -80                          # ding at 1.0 s, silence before
    assert not post.build_sfx([], 4.0, tmp_path / "none.wav")


def test_snap_to_speech_moves_words_out_of_pauses():
    from klip.engines.tts.base import Word
    words = [Word("kaget.", 1000, 1400), Word("Faktanya,", 1500, 2400), Word("otak", 2400, 2700)]
    out = voice.snap_to_speech(words, [(1450, 1850)])
    assert [w.start_ms for w in out] == [1000, 1850, 2400] and out[1].end_ms == 2400
    late = [Word("kaget.", 1000, 1400), Word("Faktanya,", 2000, 2400), Word("otak", 2400, 2700)]
    out = voice.snap_to_speech(late, [(1450, 1850)], late_ms=300)            # aligned word 150 ms late
    assert [w.start_ms for w in out] == [1000, 1850, 2400]
    assert voice.snap_to_speech(late, [(1450, 1850)], late_ms=100)[1].start_ms == 2000   # too late: a real gap


def test_breaths_between_pauses_are_merged():
    assert voice.merge_breaths([(2900, 3827), (3957, 4084), (4498, 4918)]) == [(2900, 4084), (4498, 4918)]
