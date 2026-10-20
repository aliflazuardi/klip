"""Whole-take voice, scene cutting, ElevenLabs / Gemini response handling, the aligner hook."""

import base64
import json

import pytest

from klip import align, config, ffmpeg
from klip.engines.tts import elevenlabs, gemini
from klip.engines.tts.base import Word
from klip.paths import ROOT
from klip.spec import load_spec
from klip.stages import voice
from tests.test_pipeline import needs_ffmpeg, project  # noqa: F401


class FakeTake:
    """Silent audio; 300 ms per word and a 600 ms pause after each sentence."""
    name = "edge"
    ext = ".mp3"

    def __init__(self, timed=True):
        self.timed, self.calls = timed, []

    def words_for(self, text):
        t, out = 100.0, []
        for tok in text.split():
            out.append(Word(tok.strip(",.?!"), t, t + 280))
            t += 300 + (600 if tok[-1] in ".?!" else 0)
        return out, t

    def synthesize(self, text, voice_id, rate, out_path, **kw):
        self.calls.append(text)
        words, end = self.words_for(text)
        ffmpeg.run(["-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono", "-t", f"{end / 1000 + 0.2:.2f}",
                    "-c:a", "libmp3lame", "-b:a", "48k", str(out_path)])
        return words if self.timed else []


@pytest.fixture
def whole(monkeypatch):
    monkeypatch.setitem(config.load()["voices"], "take", "whole")


@needs_ffmpeg
def test_whole_take_is_one_call_cut_into_scenes(project, whole):  # noqa: F811
    spec = load_spec(ROOT / "examples" / "menguap.json")
    project.mkdir()
    eng = FakeTake()
    tl = voice.run(spec, project, engine=eng)
    assert len(eng.calls) == 1 and tl["take"] == "whole"
    words = json.loads((project / "words.json").read_text())
    assert len(words) == spec.word_count and all(a["startMs"] <= b["startMs"] for a, b in zip(words, words[1:]))
    for s in tl["scenes"]:                          # every scene has its own clip and its own words
        mine = [w for w in words if w["sceneId"] == s["id"]]
        assert mine and s["start_ms"] <= mine[0]["startMs"] and mine[-1]["endMs"] <= s["start_ms"] + s["duration_ms"]
    # no extra gap between scenes: clip lengths add up to the take (+ the tail)
    assert sum(s["duration_ms"] for s in tl["scenes"]) == pytest.approx(tl["total_ms"])


@needs_ffmpeg
def test_untimed_engine_is_aligned(project, whole, monkeypatch):  # noqa: F811
    spec = load_spec(ROOT / "examples" / "menguap.json")
    project.mkdir()
    eng = FakeTake(timed=False)
    seen = {}

    def fake_align(path, text):
        seen["text"] = text
        return eng.words_for(text)[0]
    monkeypatch.setattr(align, "align_audio", fake_align)
    tl = voice.run(spec, project, engine=eng)
    assert seen["text"] == eng.calls[0] and len(tl["scenes"]) == len(spec.scenes)


def test_scene_cuts_land_in_the_pause():
    spans = [(100, 1000), (1600, 2500), (3000, 3900)]
    pauses = [(1050, 1550), (2520, 2980)]
    cuts = voice.scene_cuts(spans, pauses, 4200, 60)
    assert cuts == [40, 1300.0, 2750.0, 4200]
    assert voice.scene_cuts([(0, 500), (500, 900)], [], 1000, 60)[1] == 500       # no pause: cut at the join


def test_elevenlabs_characters_to_words_and_speed():
    chars = list("Halo, Warga!")
    t = [i * 0.1 for i in range(len(chars))]
    words = elevenlabs.chars_to_words(chars, t, [x + 0.08 for x in t])
    assert [w.text for w in words] == ["Halo,", "Warga!"]
    assert words[1].start_ms == pytest.approx(600) and words[1].end_ms == pytest.approx(1180)
    assert elevenlabs.speed_for("+8%") == 1.08 and elevenlabs.speed_for("+40%") == 1.2


def test_gemini_audio_extraction_and_wav_header():
    pcm = b"\x00\x01" * 100
    b64 = base64.b64encode(pcm).decode()
    interactions = {"steps": [{"type": "model_output", "content": [{"type": "audio", "data": b64}]}]}
    legacy = {"candidates": [{"content": {"parts": [{"inlineData": {"mimeType": "audio/L16", "data": b64}}]}}]}
    assert gemini.find_audio(interactions) == gemini.find_audio(legacy) == b64
    wav = gemini.to_wav(pcm)
    assert wav[:4] == b"RIFF" and wav[8:12] == b"WAVE" and wav.endswith(pcm) and gemini.to_wav(wav) == wav


def test_engines_need_their_keys(monkeypatch):
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr("klip.env.get", lambda name: None)
    for name in ("elevenlabs", "gemini"):
        with pytest.raises(Exception, match="API_KEY"):
            voice.get_engine(name).synthesize("halo", "x", "+0%", ROOT / "nope.mp3")
    with pytest.raises(ValueError, match="unknown TTS engine"):
        voice.get_engine("nope")
