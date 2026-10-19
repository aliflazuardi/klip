"""Media providers, scoring, caching and normalization — no network."""

import io
import json
import shutil
from pathlib import Path

import pytest

from klip import ffmpeg, http, paths
from klip.engines.media import openverse, pixabay
from klip.engines.media.base import Candidate, Rendition, fill_ratio, score
from klip.engines.media.local import LocalLibrary, tokens
from klip.spec import Scene
from klip.stages import assets

needs_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")


def video(id="1", renditions=((1920, 1080),), duration=10.0, rank=0, provider="t"):
    return Candidate(provider=provider, id=id, kind="video", duration_s=duration, rank=rank,
                     renditions=[Rendition(f"u{w}", w, h) for w, h in renditions])


def test_fill_ratio():
    assert fill_ratio(Rendition("", 1080, 1920)) == 1.0
    assert fill_ratio(Rendition("", 3840, 2160)) == 1.0          # 4K landscape crops to 1215x2160
    assert round(fill_ratio(Rendition("", 1920, 1080)), 2) == 0.56  # 1080p landscape: too soft


def test_best_rendition_prefers_smallest_that_fills():
    c = video(renditions=((3840, 2160), (2560, 1440), (1920, 1080), (1280, 720)))
    assert (c.best_rendition().width, c.best_rendition().height) == (2560, 1440)
    assert video(renditions=((1280, 720), (960, 540))).best_rendition().width == 1280


def test_score_prefers_portrait_long_enough_and_relevant():
    portrait = video("p", ((1080, 1920),), duration=10)
    landscape = video("l", ((1920, 1080),), duration=10)
    short = video("s", ((1080, 1920),), duration=2)
    assert score(portrait, 6) > score(landscape, 6)
    assert score(portrait, 6) > score(short, 6)
    assert score(video("a", ((1080, 1920),), rank=0), 6) > score(video("b", ((1080, 1920),), rank=8), 6)


def test_fill_mode():
    assert assets.fill_mode(2560, 1440) == "cover"
    assert assets.fill_mode(1920, 1080) == "blur"
    assert assets.fill_mode(720, 1280) == "cover"


def test_tokens_drop_stopwords():
    assert tokens("person yawning close up") == {"person", "yawning"}


@needs_ffmpeg
def test_local_library_matches_tags_from_path(tmp_path):
    (tmp_path / "food").mkdir()
    clip = tmp_path / "food" / "warung-nasi-goreng.mp4"
    ffmpeg.run(["-f", "lavfi", "-i", "color=c=red:s=320x568:d=1", "-pix_fmt", "yuv420p", str(clip)])
    lib = LocalLibrary(tmp_path)
    hits = lib.search("nasi goreng street food", "video")
    assert [h.local_path for h in hits] == [str(clip)]
    assert hits[0].duration_s == pytest.approx(1.0, abs=0.1)
    assert lib.search("mountain sunset", "video") == []
    assert lib.search("nasi goreng", "photo") == []


@pytest.fixture
def cache(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "CACHE_DIR", tmp_path / "cache")
    http.stats.reset()
    return tmp_path / "cache"


def test_get_json_caches_and_counts(cache, monkeypatch):
    calls = []

    def fake_urlopen(req, timeout=0):
        calls.append(req.full_url)
        return io.BytesIO(b'{"ok": 1}')

    monkeypatch.setattr(http.urllib.request, "urlopen", fake_urlopen)
    assert http.get_json("https://x/?key=SECRET&q=a", cache_key="x:q=a") == {"ok": 1}
    assert http.get_json("https://x/?key=OTHER&q=a", cache_key="x:q=a") == {"ok": 1}
    assert len(calls) == 1
    assert (http.stats.api_calls, http.stats.api_cache_hits) == (1, 1)
    # the cache file name is derived from cache_key, never from the URL with the key in it
    assert all("SECRET" not in p.read_text() for p in (cache / "api").iterdir())


PIXABAY_VIDEO = {"hits": [{
    "id": 7, "duration": 12, "user": "ann", "user_id": 3, "pageURL": "https://pixabay.com/videos/id-7/",
    "tags": "yawn, woman", "videos": {
        "large": {"url": "https://cdn/l.mp4", "width": 3840, "height": 2160, "size": 9},
        "medium": {"url": "https://cdn/m.mp4", "width": 2560, "height": 1440, "size": 5},
        "small": {"url": "", "width": 0, "height": 0, "size": 0}}}]}


def test_pixabay_parses_videos_and_hides_key(monkeypatch):
    seen = {}

    def fake_get_json(url, headers=None, cache_key=None, **kw):
        seen.update(url=url, cache_key=cache_key)
        return PIXABAY_VIDEO

    monkeypatch.setenv("PIXABAY_API_KEY", "k123")
    monkeypatch.setattr(pixabay.http, "get_json", fake_get_json)
    [c] = pixabay.Pixabay().search("woman yawning", "video")
    assert c.key == "pixabay:7" and c.duration_s == 12 and len(c.renditions) == 2
    assert c.best_rendition().width == 2560
    assert c.creator_url == "https://pixabay.com/users/ann-3/"
    assert "k123" in seen["url"] and "k123" not in seen["cache_key"]


def test_openverse_keeps_license_and_skips_incomplete(monkeypatch):
    data = {"results": [
        {"id": "a", "url": "https://x/a.png", "width": 2000, "height": 3000, "creator": "Bo",
         "license": "by", "license_version": "4.0", "foreign_landing_url": "https://x/a", "title": "A"},
        {"id": "b", "url": "https://x/b.jpg", "width": None, "height": None, "license": "cc0"}]}
    monkeypatch.setattr(openverse.http, "get_json", lambda *a, **k: data)
    [c] = openverse.Openverse().search("brain", "photo")
    assert c.license == "CC BY 4.0" and c.creator == "Bo" and c.title == "A"
    assert openverse.Openverse().search("brain", "video") == []


class FakeProvider:
    def __init__(self, name, results, enabled=True, fail_fetch=()):
        self.name, self.results, self._enabled, self.fail_fetch = name, results, enabled, set(fail_fetch)
        self.searches = []

    def enabled(self):
        return self._enabled

    def search(self, query, kind, per_page=15):
        self.searches.append(kind)
        return [c for c in self.results if c.kind == kind]

    def fetch(self, c):
        if c.id in self.fail_fetch:
            raise http.HTTPError("boom")
        return Path(f"/tmp/{c.id}")


def scene(vtype="stock_video", **visual):
    return Scene(id="s1", template="explain", narration="halo", visual={"type": vtype, "query": "q", **visual})


def test_select_priority_reuse_and_download_retry():
    first = FakeProvider("first", [video("a", provider="first")], enabled=False)
    second = FakeProvider("second", [video("b", provider="second"), video("c", provider="second", rank=1)],
                          fail_fetch={"b"})
    used, warnings = set(), []
    c, _ = assets.select(scene(), 5, used, [first, second], warnings)
    assert c.id == "c" and used == {"second:c"}           # disabled skipped, failed download retried
    assert first.searches == [] and any("download failed" in w for w in warnings)
    assert assets.select(scene(), 5, used, [second], []) is None  # b fails, c already used


def test_select_falls_back_from_video_to_photo():
    photo = Candidate(provider="p", id="ph", kind="photo", renditions=[Rendition("u", 1080, 1920)])
    prov = FakeProvider("p", [photo])
    c, _ = assets.select(scene(), 5, set(), [prov], [])
    assert c.kind == "photo" and prov.searches == ["video", "photo"]


def test_fetch_records_fallback_and_credits(tmp_path):
    from klip.spec import Spec
    spec = Spec.model_validate({"slug": "t", "scenes": [
        {"id": "s1", "template": "hook", "narration": "a b c", "visual": {"type": "stock_video", "query": "zz", "name": "brain"}},
        {"id": "s2", "template": "cta", "narration": "x", "visual": {"type": "solid"}}]})
    res = assets.fetch(spec, tmp_path, providers=[FakeProvider("p", [])])
    assert res["scenes"]["s1"] == {"kind": None, "fallback": "icon"}
    assert res["scenes"]["s2"] == {"kind": None}
    assert json.loads((tmp_path / "credits.json").read_text()) == []


@needs_ffmpeg
def test_normalize_video_and_photo(tmp_path, monkeypatch):
    monkeypatch.setattr(assets, "CACHE_DIR", tmp_path / "cache")
    src = tmp_path / "land.mp4"
    ffmpeg.run(["-f", "lavfi", "-i", "testsrc2=s=1920x1080:r=25:d=2", "-pix_fmt", "yuv420p", str(src)])
    out, mode = assets.normalize(src, "video", 3.0)   # 2 s source, 3 s scene -> slowed, blur fill
    info = ffmpeg.probe(out)
    v = info["streams"][0]
    assert mode == "blur" and (v["width"], v["height"]) == (1080, 1920) and v["r_frame_rate"] == "30/1"
    assert float(info["format"]["duration"]) == pytest.approx(3.0, abs=0.1)
    assert not any(s["codec_type"] == "audio" for s in info["streams"])
    assert assets.normalize(src, "video", 3.0)[0] == out   # cached

    img = tmp_path / "tall.png"
    ffmpeg.run(["-f", "lavfi", "-i", "color=c=blue:s=1200x2000", "-frames:v", "1", str(img)])
    out, mode = assets.normalize(img, "photo", 4.0)
    p = ffmpeg.probe(out)["streams"][0]
    assert mode == "cover" and (p["width"], p["height"]) == (1080, 1920)


def test_relevance_gate_uses_tags_with_plural_folding():
    from klip.engines.media.base import relevance
    port = video("port")
    port.tags = ["bridge", "container", "port", "shipping"]
    jar = video("jar")
    jar.tags = ["olives", "spices", "container", "glass", "food"]
    assert relevance(port, "food container refrigerator") == pytest.approx(1 / 3)
    assert relevance(jar, "food container refrigerator") == pytest.approx(2 / 3)
    chili = video("c")
    chili.tags = ["chili", "pepper", "red"]
    assert relevance(chili, "red chili peppers") == 1.0          # peppers ~ pepper
    assert relevance(video("untagged"), "anything") is None


def test_select_skips_off_topic_results():
    port = video("port", provider="p")
    port.tags = ["bridge", "container", "port", "shipping"]
    jar = video("jar", provider="p", rank=5)
    jar.tags = ["olives", "spices", "container", "glass", "food"]
    s = Scene(id="s1", template="explain", narration="halo",
              visual={"type": "stock_video", "query": "food container refrigerator"})
    c, _ = assets.select(s, 5, set(), [FakeProvider("p", [port, jar])], [])
    assert c.id == "jar"
    assert assets.select(s, 5, set(), [FakeProvider("p", [port])], []) is None


def test_download_backs_off_on_429(cache, monkeypatch):
    import urllib.error
    calls = []

    def fake_urlopen(req, timeout=0):
        calls.append(1)
        if len(calls) < 3:
            raise urllib.error.HTTPError(req.full_url, 429, "Too Many Requests", {"Retry-After": "0"}, None)
        return io.BytesIO(b"jpegdata")

    monkeypatch.setattr(http.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(http.time, "sleep", lambda s: None)
    assert http.download("https://x/a.jpg", "a.jpg").read_bytes() == b"jpegdata" and len(calls) == 3
