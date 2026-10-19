"""Templates (context), music, and QA checks."""

import shutil

import pytest
from pydantic import ValidationError

from klip import ffmpeg, paths
from klip.spec import Spec
from klip.stages import compose, post, qa

needs_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")
needs_renderer = pytest.mark.skipif(not (compose.NODE_MODULES / "lucide-static").exists(),
                                    reason="renderer/node_modules not installed")


def spec_with(*scenes, **kw):
    return Spec.model_validate({"slug": "t", "scenes": list(scenes), **kw})


# ---- spec / templates

def test_template_data_required():
    with pytest.raises(ValidationError, match="requires: myth, fact"):
        spec_with({"id": "a", "template": "myth_fact", "narration": "x"})
    with pytest.raises(ValidationError, match="requires: stat"):
        spec_with({"id": "a", "template": "stat", "narration": "x"})
    with pytest.raises(ValidationError, match="requires: compare"):
        spec_with({"id": "a", "template": "compare", "narration": "x"})


@pytest.mark.parametrize("value,dec,out", [(20, 0, "20"), (1234567, 0, "1.234.567"), (1.5, 1, "1,5"),
                                           (0, 2, "0,00"), (-2500, 0, "-2.500")])
def test_format_number_indonesian(value, dec, out):
    assert compose.format_number(value, dec) == out


def test_list_items_auto_numbered_per_run():
    li = lambda i, **kw: {"id": i, "template": "list_item", "narration": "x", **kw}
    s = spec_with(li("a"), li("b"), {"id": "m", "template": "explain", "narration": "x"},
                  li("c"), li("d", list_index=9), li("e"))
    assert compose._list_numbers(s) == {"a": (1, 2), "b": (2, 2), "c": (1, 3), "d": (9, 3), "e": (3, 3)}


def test_reveal_time_uses_word_or_default():
    s = spec_with({"id": "a", "template": "myth_fact", "narration": "x", "myth": "m", "fact": "f",
                   "reveal_at": "Faktanya,"}).scenes[0]
    t = {"start_ms": 10_000, "duration_ms": 8_000}
    words = [{"text": " Banyak", "startMs": 10_100}, {"text": " Faktanya,", "startMs": 13_250}]
    assert compose._reveal_time(s, t, words) == 13.25
    assert compose._reveal_time(s, t, [{"text": " lain", "startMs": 10_100}]) == 13.6  # 45%


@needs_renderer
def test_template_ctx_stat_and_compare():
    s = spec_with({"id": "a", "template": "stat", "narration": "x", "on_screen_text": "durasi ideal",
                   "stat": {"value": 1500, "suffix": " menit"}}).scenes[0]
    ctx = compose._template_ctx(s, {"start_ms": 0, "duration_ms": 3000}, [], {})
    assert ctx["final"] == "1.500" and ctx["zero"] == "0" and [h["text"] for h in ctx["label"]] == ["durasi", "ideal"]
    c = spec_with({"id": "c", "template": "compare", "narration": "x", "compare": {
        "left": {"label": "A", "icon": "sun"}, "right": {"label": "B"}}}).scenes[0]
    ctx = compose._template_ctx(c, {"start_ms": 0, "duration_ms": 3000}, [], {})
    assert ctx["left"]["icon"].startswith("<svg") and ctx["right"]["icon"] is None


# ---- music

def test_pick_track_deterministic_and_optional(tmp_path, monkeypatch):
    monkeypatch.setattr(post, "ROOT", tmp_path)
    s = spec_with({"id": "a", "template": "hook", "narration": "x"})
    assert post.pick_track(s) is None                       # no folder -> no music
    d = tmp_path / "assets" / "music" / "calm"
    d.mkdir(parents=True)
    for n in ("a.mp3", "b.mp3", "notes.txt"):
        (d / n).write_bytes(b"x")
    first = post.pick_track(s)
    assert first.suffix == ".mp3" and post.pick_track(s) == first
    assert post.pick_track(s.model_copy(update={"music": s.music.model_copy(update={"mood": None})})) is None


@needs_ffmpeg
def test_mix_music_keeps_tail_and_ducks(tmp_path):
    voice = tmp_path / "voice.wav"
    music = tmp_path / "music.wav"
    # 4 s of "speech" (tone) then 4 s silence; music is a steady tone, shorter than the video.
    ffmpeg.run(["-f", "lavfi", "-i", "sine=f=300:d=4", "-af", "apad=whole_dur=8", "-ar", "48000", str(voice)])
    ffmpeg.run(["-f", "lavfi", "-i", "sine=f=500:d=3", "-ar", "48000", str(music)])
    out = tmp_path / "mix.wav"
    post.mix_music(voice, music, 8.0, out, {"under_voice_db": 16, "fade_out_s": 1.0})
    assert ffmpeg.duration_ms(out) == pytest.approx(8000, abs=50)

    def level(start, dur):
        proc = ffmpeg.run(["-ss", str(start), "-t", str(dur), "-i", str(out), "-af", "volumedetect", "-f", "null", "-"])
        import re
        return float(re.search(r"mean_volume: (-?[\d.]+) dB", proc.stderr).group(1))

    # music is looped and still present after the voice ends, before the fade (regression:
    # single-pass loudnorm used to swallow the last ~3 s)
    assert level(5.5, 1.0) > -60


# ---- QA checks

def probe_like(w=1080, h=1920, fps="30/1", vc="h264", ac="aac"):
    streams = [{"codec_type": "video", "width": w, "height": h, "r_frame_rate": fps, "codec_name": vc}]
    if ac:
        streams.append({"codec_type": "audio", "codec_name": ac})
    return {"streams": streams, "format": {"duration": "40"}}


def test_check_format():
    assert qa.check_format(probe_like())["ok"]
    bad = qa.check_format(probe_like(w=720, h=1280, fps="25/1", ac=None))
    assert not bad["ok"] and "720×1280" in bad["detail"] and "fps 25/1" in bad["detail"] and "no audio" in bad["detail"]


def test_check_duration():
    assert qa.check_duration(44.0, 45)["ok"]
    assert not qa.check_duration(14.5, 12)["ok"]
    assert not qa.check_duration(61.0, 60)["ok"]   # inside ±15% but over the 60 s cap


def test_check_loudness():
    assert qa.check_loudness({"input_i": "-14.1", "input_tp": "-1.5"})["ok"]
    assert not qa.check_loudness({"input_i": "-18", "input_tp": "-1.5"})["ok"]
    assert not qa.check_loudness({"input_i": "-14", "input_tp": "-0.2"})["ok"]


def test_check_captions_counts_and_page_size():
    s = spec_with({"id": "a", "template": "hook", "narration": "satu dua tiga"})
    words = [{"text": f" {w}", "startMs": i * 100, "endMs": i * 100 + 90, "sceneId": "a"}
             for i, w in enumerate(["satu", "dua", "tiga"])]
    assert qa.check_captions(s, words, [{"words": ["satu", "dua", "tiga"]}], 4)["ok"]
    r = qa.check_captions(s, words[:2], [{"words": ["a", "b", "c", "d", "e"]}], 4)
    assert not r["ok"] and "2/3 words timed" in r["detail"] and "> 4 words" in r["detail"]


def test_check_credits():
    assets = {"scenes": {"a": {"kind": "video", "provider": "pixabay"}, "b": {"kind": "video", "provider": "local"},
                         "c": {"kind": None}}}
    assert qa.check_credits(assets, [{"scene": "a"}])["ok"]
    assert not qa.check_credits(assets, [])["ok"]


def test_check_voice():
    assert qa.check_voice({"a": -20.0, "b": -25.0})["ok"]
    assert not qa.check_voice({"a": -20.0, "b": float("-inf")})["ok"]


@needs_ffmpeg
def test_detect_still_finds_black_and_frozen(tmp_path):
    clip = tmp_path / "v.mp4"
    # 2 s black, then 2 s moving test pattern, then 2 s frozen (static color)
    ffmpeg.run(["-f", "lavfi", "-i", "color=c=black:s=320x568:r=30:d=2",
                "-f", "lavfi", "-i", "testsrc2=s=320x568:r=30:d=2",
                "-f", "lavfi", "-i", "color=c=blue:s=320x568:r=30:d=2",
                "-filter_complex", "[0:v][1:v][2:v]concat=n=3:v=1[v]", "-map", "[v]",
                "-pix_fmt", "yuv420p", str(clip)])
    black, frozen = qa.detect_still(clip)
    assert black and black[0][0] == pytest.approx(0, abs=0.1)
    assert any(a >= 3.9 for a, _ in frozen)
