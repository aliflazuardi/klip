"""Per-scene delivery (rate/pitch/volume presets)."""

import json
import shutil
from pathlib import Path

import pytest

from klip import config, ffmpeg, pipeline, prosody
from klip.engines.tts.base import Word
from klip.paths import ROOT
from klip.spec import Scene, Spec
from klip.stages import voice

GOOD = json.loads((ROOT / "examples" / "tidur-siang.json").read_text())


def sc(template, **kw):
    extra = {"stat": {"value": 1}} if template == "stat" else {}
    return Scene(id="s", template=template, narration="x", **extra, **kw)


def test_combine_rate():
    assert prosody.combine_rate("+15%", "+6%") == "+21%"
    assert prosody.combine_rate("+8%", "-6%") == "+2%"
    assert prosody.combine_rate("+0%", "-8%") == "-8%"
    with pytest.raises(ValueError):
        prosody.combine_rate("fast", "+1%")


def test_delivery_by_template_and_override():
    assert prosody.delivery_name(sc("hook")) == "energetic"
    assert prosody.delivery_name(sc("cta")) == "warm"
    assert prosody.delivery_name(sc("stat")) == "emphatic"
    assert prosody.delivery_name(sc("explain")) == "neutral"
    assert prosody.delivery_name(sc("hook", delivery="calm")) == "calm"


def test_for_scene_uses_preset_on_top_of_base_rate():
    p = prosody.for_scene(sc("hook"), "+15%")
    preset = config.get("prosody.presets.energetic")
    assert p.rate == prosody.combine_rate("+15%", preset["rate"])
    assert (p.pitch, p.volume) == (preset["pitch"], preset["volume"])
    assert prosody.for_scene(sc("explain"), "+8%") == prosody.Prosody("neutral", "+8%", "+0Hz", "+0%")


def test_disabled_falls_back_to_neutral_unless_scene_says_so(monkeypatch):
    real = config.get
    monkeypatch.setattr(config, "get", lambda k, d=None: False if k == "prosody.enabled" else real(k, d))
    assert prosody.delivery_name(sc("hook")) == "neutral"
    assert prosody.delivery_name(sc("hook", delivery="energetic")) == "energetic"


def test_neutral_cache_key_unchanged():
    old = voice._cache_key("edge", "v", "+8%", "halo")
    assert voice._cache_key("edge", "v", "+8%", "halo", "+0Hz", "+0%") == old
    assert voice._cache_key("edge", "v", "+8%", "halo", "+8Hz", "+5%") != old


def test_estimate_accounts_for_per_scene_rate(monkeypatch):
    spec = Spec.model_validate(GOOD)
    with_prosody = pipeline.estimate_duration_s(spec)
    real = config.get
    monkeypatch.setattr(config, "get", lambda k, d=None: False if k == "prosody.enabled" else real(k, d))
    flat = pipeline.estimate_duration_s(spec)
    assert with_prosody != pytest.approx(flat, abs=0.05)   # emphatic/warm scenes are slower


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")
def test_voice_stage_passes_prosody_to_engine(tmp_path, monkeypatch):
    calls = []

    class Rec:
        name = "edge"

        def synthesize(self, text, voice_id, rate, out_path, pitch="+0Hz", volume="+0%"):
            calls.append((text, rate, pitch, volume))
            ffmpeg.run(["-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono", "-t", "1", "-c:a", "libmp3lame", str(out_path)])
            return [Word(t, 100 + i * 200, 280 + i * 200) for i, t in enumerate(text.split())]

    monkeypatch.setattr(voice, "CACHE_DIR", tmp_path / "cache")
    spec = Spec.model_validate({"slug": "t", "voice": "female", "scenes": [
        {"id": "a", "template": "hook", "narration": "satu dua"},
        {"id": "b", "template": "explain", "narration": "tiga empat", "delivery": "calm"},
        {"id": "c", "template": "cta", "narration": "lima enam"}]})
    proj = tmp_path / "p"
    proj.mkdir()
    tl = voice.run(spec, proj, engine=Rec())
    base = config.default_rate("female")
    assert [c[1:] for c in calls] == [(prosody.for_scene(s, base).rate, prosody.for_scene(s, base).pitch,
                                       prosody.for_scene(s, base).volume) for s in spec.scenes]
    assert [s["delivery"] for s in tl["scenes"]] == ["energetic", "calm", "warm"]
