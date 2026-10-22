"""Beat tracking of the music track (klip/beats.py) and k.beats in code scenes."""

import subprocess

import pytest

from klip import beats
from klip.stages import compose
from tests.test_code_scenes import _spec, code, repo  # noqa: F401  (fixture)
from tests.test_stage import _timeline, words


def _click(path, bpm=120.0, first=0.3, dur=20):
    """A kick-like click track: a decaying 70 Hz thump on every beat."""
    period = 60 / bpm
    expr = f"0.8*sin(2*PI*70*t)*exp(-25*mod(t+{period}-{first},{period}))"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"aevalsrc='{expr}':s=22050:d={dur}", str(path)],
                   check=True)
    return path


@pytest.fixture(autouse=True)
def _cache(tmp_path, monkeypatch):
    monkeypatch.setattr(beats, "CACHE_DIR", tmp_path / "cache")


def test_finds_the_tempo_and_beats_of_a_click_track(tmp_path):
    a = beats.analyze(_click(tmp_path / "click.wav"))
    assert abs(a["bpm"] - 120) < 2 and a["confidence"] > 5
    for i, b in enumerate(a["beats"][:30]):
        assert abs(b["t"] - (0.3 + i * 0.5)) < 0.035
    assert sum(b["down"] for b in a["beats"][:8]) == 2
    assert (tmp_path / "cache" / "beats").is_dir()                     # cached by content


def test_a_swelling_tone_has_no_steady_beat(tmp_path):
    pad = tmp_path / "pad.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                    "aevalsrc='0.4*sin(2*PI*220*t)*(0.6+0.4*sin(2*PI*0.13*t))':s=22050:d=20", str(pad)], check=True)
    a = beats.analyze(pad)
    assert a["bpm"] is None and a["beats"] == []


def test_beats_tile_over_the_looping_track_and_split_by_scene(monkeypatch):
    monkeypatch.setattr(beats, "analyze", lambda track: {
        "bpm": 120, "period": 0.5, "duration": 2.0, "beats": [{"t": 0.25, "down": True, "s": 1}, {"t": 1.25, "down": False, "s": 0.5}]})
    v = beats.for_video(None, 5.0)
    assert [b["t"] for b in v["beats"]] == [0.25, 1.25, 2.25, 3.25, 4.25] and [b["n"] for b in v["beats"]] == [0, 1, 2, 3, 4]
    assert beats.in_scene(v, 2.0, 2.0) == [{"t": 0.25, "down": True, "s": 1, "n": 2}, {"t": 1.25, "down": False, "s": 0.5, "n": 3}]


def test_code_scenes_get_their_beats_from_the_music(repo, tmp_path):  # noqa: F811
    track = _click(tmp_path / "click.wav", dur=6)
    spec = _spec({"id": "s1", "template": "hook", "narration": "matahari terbit", "visual": code()},
                 {"id": "s2", "template": "explain", "narration": "lalu terbenam", "visual": code()},
                 music={"track": str(track)})
    ws = words(("matahari", 100), ("terbit", 600)) + words(("lalu", 2100), ("terbenam", 2500), scene="s2")
    ctx, _ = compose.build_context(spec, _timeline(("s1", 2000), ("s2", 2000)), ws, {"scenes": {}})
    m1, m2 = (s["code"]["meta"] for s in ctx["scenes"])
    assert abs(m1["bpm"] - 120) < 2 and abs(m1["period"] - 0.5) < 0.01
    assert [round(b["t"], 1) for b in m1["beats"]] == [0.3, 0.8, 1.3, 1.8]
    assert [round(b["t"], 1) for b in m2["beats"]] == [0.3, 0.8, 1.3, 1.8] and m2["beats"][0]["n"] == 4

    off = _spec(*spec.model_dump()["scenes"], music={"track": str(track), "beats": False})
    ctx, _ = compose.build_context(off, _timeline(("s1", 2000), ("s2", 2000)), ws, {"scenes": {}})
    assert ctx["scenes"][0]["code"]["meta"]["beats"] == []

    silent = _spec({"id": "s1", "template": "hook", "narration": "matahari terbit", "visual": code()})
    ctx, _ = compose.build_context(silent, _timeline(("s1", 2000)), words(("matahari", 100), ("terbit", 600)), {"scenes": {}})
    assert ctx["scenes"][0]["code"]["meta"]["beats"] == [] and ctx["scenes"][0]["code"]["meta"]["bpm"] is None


def test_kit_has_the_beat_helpers():
    from klip.paths import TEMPLATES_DIR
    kit = (TEMPLATES_DIR / "default" / "scenes" / "code_kit.js.j2").read_text()
    for helper in ("beats: meta.beats || []", "k.pulse = function", "k.onBeat = function"):
        assert helper in kit
