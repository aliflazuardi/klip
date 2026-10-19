"""Faster cuts: shot planning, clip selection/assignment, per-shot media."""

import json
import shutil
from pathlib import Path

import pytest

from klip import ffmpeg, shots
from klip.engines.media.base import Candidate, Rendition
from klip.paths import ROOT
from klip.spec import Scene, load_spec
from klip.stages import assets, compose, voice

needs_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")
needs_renderer = pytest.mark.skipif(not (compose.NODE_MODULES / "lucide-static").exists(),
                                    reason="renderer/node_modules not installed")


def words(*pairs):
    return [{"text": f" {t}", "startMs": ms} for t, ms in pairs]


# ---- planning

def test_short_scene_is_one_shot():
    assert shots.plan(0, 3000, words(("a", 0), ("b", 1500))) == [shots.Shot(0, 3000)]


def test_cuts_land_on_word_starts_and_prefer_pauses():
    ws = words(("Kulit", 100), ("merinding,", 600), ("bulu", 1400), ("kuduk", 1800), ("berdiri,", 2300),
               ("kadang", 3200), ("sampai", 3600), ("mau", 4000), ("nangis.", 4300), ("x", 5000))
    plan = shots.plan(0, 7500, ws, target_ms=2500, min_ms=1400, max_shots=4)
    cuts = [s.start_ms for s in plan[1:]]
    assert len(plan) == 3 and all(c in [w["startMs"] for w in ws] for c in cuts)
    # ideal cuts at 2500/5000; "kadang" (after "berdiri,") wins the first despite being 700 ms off
    assert cuts == [3200, 5000]
    assert plan[0].start_ms == 0 and plan[-1].end_ms == 7500
    assert all(s.dur_ms >= 1400 for s in plan)


def test_max_shots_and_cap():
    ws = words(*[(f"w{i}", i * 400) for i in range(40)])
    assert len(shots.plan(0, 16000, ws, max_shots=4)) == 4
    assert len(shots.plan(0, 16000, ws, max_shots=4, cap=1)) == 1


def test_min_shot_length_drops_cramped_cuts():
    ws = words(("a", 0), ("b", 4600), ("c", 4700))
    plan = shots.plan(0, 5200, ws, target_ms=2500, min_ms=1400)
    assert all(s.dur_ms >= 1400 for s in plan)


def test_beats_cut_on_anchor_words_in_order():
    ws = words(("Rupiah", 0), ("melemah,", 500), ("impor", 1600), ("mahal:", 2000), ("kedelai,", 3300),
               ("pakan,", 4000), ("BBM.", 4600))
    plan = shots.plan_beats(0, 6000, ws, ["impor mahal", "kedelai", "BBM"], min_ms=1400)
    # "BBM" at 4600 would leave a 1.3 s shot after kedelai (and 1.4 s to the end): dropped
    assert [(s.start_ms, s.end_ms, k) for s, k in plan] == [(0, 1600, 0), (1600, 3300, 1), (3300, 6000, 2)]


def test_beat_anchor_missing_or_out_of_order_is_dropped():
    ws = words(("a", 0), ("b", 2000), ("c", 4000))
    assert shots.anchor_times(ws, ["c", "b", "zzz"]) == [4000, None, None]
    plan = shots.plan_beats(0, 6000, ws, ["zzz", "c"])
    assert [k for _, k in plan] == [0, 2]


def test_plan_shots_never_reuses_a_clip():
    from klip.spec import Visual
    t = {"start_ms": 0, "duration_ms": 10000}
    ws = words(*[(f"w{i}", i * 500) for i in range(20)])
    cut = {"target_ms": 2500, "min_ms": 1400, "max_shots": 4}
    one_clip = [{"kind": "video"}]
    # timed cuts: a 10 s scene with one clip is one shot, not four jump cuts of the same clip
    assert [ci for _, ci in assets.plan_shots(Visual(type="stock_video", query="q"), t, ws, one_clip, cut)] == [0]
    three = [{"kind": "video"}] * 3
    assert [ci for _, ci in assets.plan_shots(Visual(type="stock_video", query="q"), t, ws, three, cut)] == [0, 1, 2]
    # beats: beat 2 found no clip → beat 1's shot runs on to the end
    v = Visual(type="stock_video", query="q", beats=[{"at": "w6", "query": "b1"}, {"at": "w12", "query": "b2"}])
    clips = [{"kind": "video", "beat": 0}, {"kind": "video", "beat": 1}]
    plan = assets.plan_shots(v, t, ws, clips, cut)
    assert [(s.start_ms, s.end_ms, ci) for s, ci in plan] == [(0, 3000, 0), (3000, 10000, 1)]
    # main query found nothing: the first beat's clip opens the scene
    plan = assets.plan_shots(v, t, ws, [{"kind": "video", "beat": 2}], cut)
    assert [(s.start_ms, s.end_ms, ci) for s, ci in plan] == [(0, 10000, 0)]


# ---- selection

def vid(id, tags, provider="p"):
    return Candidate(provider=provider, id=id, kind="video", duration_s=10, tags=tags,
                     renditions=[Rendition("u", 2560, 1440)])


class Prov:
    name = "p"

    def __init__(self, by_query):
        self.by_query = by_query

    def enabled(self):
        return True

    def search(self, q, kind, per_page=15):
        return [c for c in self.by_query.get(q, []) if c.kind == kind]

    def fetch(self, c):
        return Path(f"/tmp/{c.id}")


def test_select_many_round_robins_queries_without_reuse():
    scene = Scene(id="s", template="explain", narration="x", visual={
        "type": "stock_video", "query": "goosebumps skin", "queries": ["woman listening music"]})
    prov = Prov({"goosebumps skin": [vid("g1", ["goosebumps", "skin"]), vid("g2", ["skin", "goosebumps"])],
                 "woman listening music": [vid("m1", ["woman", "listening", "music"]), vid("g1", ["goosebumps", "skin"])]})
    used: set[str] = set()
    picked = assets.select_many(scene, 3, used, [prov], [], n=3)
    assert [(c.id, q) for c, _, q in picked] == [("g1", "goosebumps skin"), ("m1", "woman listening music"),
                                                 ("g2", "goosebumps skin")]
    assert used == {"p:g1", "p:m1", "p:g2"}


def test_pick_beats_one_clip_per_beat_query():
    scene = Scene(id="s", template="explain", narration="rupiah melemah impor mahal kedelai", visual={
        "type": "stock_video", "query": "rupiah notes",
        "beats": [{"at": "impor", "query": "container port"}, {"at": "kedelai", "query": "soybeans"}]})
    prov = Prov({"rupiah notes": [vid("r1", ["rupiah", "notes"]), vid("r2", ["rupiah", "notes"])],
                 "container port": [vid("r1", ["rupiah", "notes"]), vid("c1", ["container", "port"])]})
    pools = assets.build_pools(scene, 3, set(), [prov], [])
    warnings: list[str] = []
    picked = assets.pick_beats(scene, pools, set(), warnings)
    assert [(c.id, k) for c, _, _, k in picked] == [("r1", 0), ("c1", 1)]
    assert "kedelai" in warnings[0]


def test_take_skips_same_footage_under_another_id(tmp_path):
    class Dup(Prov):
        def fetch(self, c):
            f = tmp_path / f"{c.id}.mp4"
            f.write_bytes(b"same bytes")
            return f
    scene = Scene(id="s", template="explain", narration="x", visual={"type": "stock_video", "query": "q"})
    used: set[str] = set()
    picked = assets.pick(scene, [("q", Dup({}), [vid("a", ["q"]), vid("b", ["q"])])], used, [], 2)
    assert [c.id for c, _, _ in picked] == ["a"]


def test_select_many_returns_fewer_when_pool_is_small():
    scene = Scene(id="s", template="explain", narration="x", visual={"type": "stock_video", "query": "rare thing"})
    picked = assets.select_many(scene, 3, set(), [Prov({"rare thing": [vid("r1", ["rare", "thing"])]})], [], n=3)
    assert [c.id for c, _, _ in picked] == ["r1"]


# ---- media

@needs_ffmpeg
def test_normalize_short_clip_slows_then_holds_instead_of_looping(tmp_path, monkeypatch):
    monkeypatch.setattr(assets, "CACHE_DIR", tmp_path / "cache")
    src = tmp_path / "v.mp4"
    ffmpeg.run(["-f", "lavfi", "-i", "testsrc2=s=1080x1920:r=30:d=2", "-pix_fmt", "yuv420p", str(src)])
    out, _ = assets.normalize(src, "video", 5.0)          # 2 s clip, 5 s shot: 3.33 s slowed + held
    assert ffmpeg.duration_ms(out) == pytest.approx(5000, abs=60)
    assert assets.normalize(src, "video", 5.0)[0] == out  # cached


@needs_ffmpeg
@needs_renderer
def test_compose_emits_one_media_clip_per_shot(tmp_path, monkeypatch):
    from tests.test_pipeline import FakeTTS
    monkeypatch.setattr(voice, "CACHE_DIR", tmp_path / "cache")
    spec = load_spec(ROOT / "examples" / "tidur-siang.json")
    proj = tmp_path / "p"
    proj.mkdir()
    tl = voice.run(spec, proj, engine=FakeTTS())
    s3 = next(s for s in tl["scenes"] if s["id"] == "s3")
    (proj / "media").mkdir()
    rows = []
    for k, (a, b) in enumerate([(0, 0.4), (0.4, 0.7), (0.7, 1.0)]):
        f = proj / "media" / f"s3_{k}.mp4"
        f.write_bytes(b"x")
        rows.append({"file": f"media/s3_{k}.mp4", "kind": "video",
                     "start_ms": s3["start_ms"] + s3["duration_ms"] * a, "dur_ms": s3["duration_ms"] * (b - a)})
    (proj / "assets.json").write_text(json.dumps({"scenes": {"s3": {"kind": "video", "file": rows[0]["file"], "shots": rows}}}))
    compose.run(spec, proj)
    html = (proj / "composition" / "index.html").read_text()
    for k in range(3):
        assert f'id="m-s3-{k}"' in html and (proj / "composition" / "media" / f"s3_{k}.mp4").exists()
    assert f'tl.fromTo("#m-s3-1", {{ scale: {compose.config.get("cuts.cut_zoom")}' in html


# ---- lint / QA

def test_lint_beat_anchor_must_be_in_narration_in_order():
    from klip import lint
    spec = load_spec(ROOT / "examples" / "tidur-siang.json")
    sc = spec.scenes[1]
    first, last = sc.narration.split()[0], sc.narration.split()[-1]
    from klip.spec import Visual
    sc.visual = Visual(type="stock_video", query="q", beats=[
        {"at": last, "query": "a"}, {"at": first, "query": "b"}, {"at": "zzzz", "query": "c"}])
    msgs = [str(i) for i in lint.errors(lint.lint(spec)) if i.where == sc.id]
    assert any("after the previous beat" in m for m in msgs) and any("'zzzz'" in m for m in msgs)


def test_spec_rejects_beats_with_queries_or_on_icons():
    from pydantic import ValidationError
    from klip.spec import Visual
    with pytest.raises(ValidationError):
        Visual(type="stock_video", query="q", queries=["x"], beats=[{"at": "a", "query": "b"}])
    with pytest.raises(ValidationError):
        Visual(type="icon", name="brain", beats=[{"at": "a", "query": "b"}])


def test_qa_fresh_footage_flags_reused_sources_and_long_shots():
    from klip.stages import qa
    row = lambda src, ms: {"source": src, "dur_ms": ms}  # noqa: E731
    ok = qa.check_footage({"scenes": {"s1": {"shots": [row("p:1", 2000), row("p:2", 9000)]}}})
    assert ok["ok"] and "s1 9.0s" in ok["detail"]
    bad = qa.check_footage({"scenes": {"s1": {"shots": [row("p:1", 2000)]}, "s2": {"shots": [row("p:1", 2000)]}}})
    assert not bad["ok"] and "p:1 (s1 and s2)" in bad["detail"]
    assert qa.check_footage(None)["ok"]
