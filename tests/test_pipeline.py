"""Voice + compose stages end to end with a fake TTS (no network, no browser)."""

import json
import shutil
from pathlib import Path

import pytest

from klip import ffmpeg
from klip.engines.tts.base import Word
from klip.paths import ROOT
from klip.spec import load_spec
from klip.stages import compose, voice

needs_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")
needs_renderer = pytest.mark.skipif(not (compose.NODE_MODULES / "lucide-static").exists(),
                                    reason="renderer/node_modules not installed")


class FakeTTS:
    """Silent audio, 300 ms per word."""

    name = "edge"  # reuse the edge voice mapping; the cache is a tmp dir

    def synthesize(self, text, voice_id, rate, out_path: Path, **kw):
        toks = text.split()
        ffmpeg.run(["-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono", "-t", f"{0.3 * len(toks) + 0.1:.2f}",
                    "-c:a", "libmp3lame", "-b:a", "48k", str(out_path)])
        return [Word(t.strip(",.?!"), 100 + i * 300, 100 + i * 300 + 280) for i, t in enumerate(toks)]


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setattr(voice, "CACHE_DIR", tmp_path / "cache")
    return tmp_path / "proj"


@needs_ffmpeg
def test_voice_stage_writes_timeline_words_and_wav(project):
    spec = load_spec(ROOT / "examples" / "menguap.json")
    project.mkdir()
    tl = voice.run(spec, project, engine=FakeTTS())

    words = json.loads((project / "words.json").read_text())
    assert len(words) == spec.word_count, "every narration word has a timing"
    assert all(w["text"].startswith(" ") for w in words)
    assert all(a["startMs"] <= b["startMs"] for a, b in zip(words, words[1:]))

    starts = [s["start_ms"] for s in tl["scenes"]]
    assert starts == sorted(starts) and starts[0] == 0
    assert abs(ffmpeg.duration_ms(project / "voice.wav") - tl["total_ms"]) < 60

    # tts_override ("Folo") still shows the display word ("Follow") in captions
    assert any(w["text"] == " Follow" for w in words)


@needs_ffmpeg
@needs_renderer
def test_compose_builds_html_with_captions(project):
    spec = load_spec(ROOT / "examples" / "menguap.json")
    project.mkdir()
    voice.run(spec, project, engine=FakeTTS())
    info = compose.run(spec, project)

    html = (project / "composition" / "index.html").read_text()
    assert 'data-composition-id="main"' in html
    assert 'window.__timelines["main"]' in html
    for s in spec.scenes:
        assert f'id="sc-{s.id}"' in html
    assert info["pages"] > 0 and not info["warnings"]
    assert (project / "composition" / "gsap.min.js").exists()

    # no media -> gradient scenes only
    assert "<video" not in html and "scene clip has-media" not in html

    # same inputs -> same hash (render cache relies on this)
    assert compose.run(spec, project)["hash"] == info["hash"]


@needs_ffmpeg
@needs_renderer
def test_compose_places_media_layer_and_icon_fallback(project):
    spec = load_spec(ROOT / "examples" / "menguap.json")
    project.mkdir()
    voice.run(spec, project, engine=FakeTTS())
    (project / "media").mkdir()
    (project / "media" / "s1.mp4").write_bytes(b"fake")
    (project / "media" / "s2.jpg").write_bytes(b"fake")
    (project / "assets.json").write_text(json.dumps({"scenes": {
        "s1": {"kind": "video", "file": "media/s1.mp4"},
        "s2": {"kind": "photo", "file": "media/s2.jpg"},
        "s3": {"kind": None, "fallback": "icon"},
    }}))
    compose.run(spec, project)
    html = (project / "composition" / "index.html").read_text()
    assert '<video id="m-s1-0" class="media clip" src="media/s1.mp4" muted' in html
    assert '<img id="m-s2-0" class="media clip" src="media/s2.jpg"' in html
    assert 'class="scene clip has-media"' in html
    assert (project / "composition" / "media" / "s1.mp4").exists()
    # s3 had no media but a fallback icon (brain) -> inline svg in its section
    s3 = html.split('id="sc-s3"')[1].split("</section>")[0]
    assert "<svg" in s3
