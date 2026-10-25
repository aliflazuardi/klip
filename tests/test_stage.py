"""Stage scenes (visual.type "stage"): spec rules, timing, layout, lint, cut-outs, assets, compose."""

import json
from pathlib import Path

import pytest
from PIL import Image
from pydantic import ValidationError

from klip import cutout
from klip import stage as stage_mod
from klip.engines.media.base import Candidate, Rendition
from klip.lint import lint
from klip.spec import Scene, Spec, Visual
from klip.stages import assets, compose
from tests.test_media import FakeProvider

needs_renderer = pytest.mark.skipif(not (compose.NODE_MODULES / "lucide-static").exists(),
                                    reason="renderer/node_modules not installed")


def words(*pairs, scene="s1"):
    return [{"text": f" {t}", "startMs": ms, "endMs": ms + 300, "sceneId": scene} for t, ms in pairs]


def stage(*elements, **kw):
    return {"type": "stage", "elements": list(elements), **kw}


# ---- spec

def test_stage_needs_elements_and_kind_fields():
    with pytest.raises(ValidationError, match="requires visual.elements"):
        Visual(type="stage")
    with pytest.raises(ValidationError, match="requires query or path"):
        Visual(**stage({"at": "a", "kind": "cutout"}))
    with pytest.raises(ValidationError, match="2-4 bars"):
        Visual(**stage({"at": "a", "kind": "bar", "bars": [{"label": "x", "value": 1}]}))
    with pytest.raises(ValidationError, match="only for visual.type='stage'"):
        Visual(type="solid", elements=[{"at": "a", "kind": "label", "text": "x"}])
    with pytest.raises(ValidationError, match="`label` is for"):
        Visual(**stage({"at": "a", "kind": "number", "text": "5", "label": "x"}))


def test_highlight_target_and_stage_capacity():
    lab = {"at": "a", "kind": "label", "text": "x"}
    Visual(**stage(lab, {"at": "b", "kind": "highlight", "target": 1}))
    with pytest.raises(ValidationError, match="earlier element"):
        Visual(**stage(lab, {**lab, "clear": True}, {"at": "c", "kind": "highlight", "target": 1}))
    with pytest.raises(ValidationError, match="at most 6"):
        Visual(**stage(*[lab] * 7))
    Visual(**stage(*[lab] * 6, {**lab, "clear": True}))      # a clear starts a fresh stage


# ---- timing

def test_entry_times_follow_anchor_words():
    els = Visual(**stage(*({"at": w, "kind": "label", "text": w} for w in ["harga", "tempe", "naik"]))).elements
    ws = words(("Kamu", 0), ("tahu", 300), ("harga", 600), ("tempe", 700), ("bisa", 1500), ("naik", 2000))
    warn = []
    t = stage_mod.entry_times(els, ws, 0, 3000, warn, "s1")
    # lead 0.06 s; tempe is pushed to keep min_gap_s after harga
    assert t == [0.54, 0.79, 1.94] and not warn


def test_missing_anchor_is_placed_between_neighbours():
    els = Visual(**stage(*({"at": w, "kind": "label", "text": w} for w in ["a", "zzz", "c"]))).elements
    warn = []
    t = stage_mod.entry_times(els, words(("a", 1000), ("c", 3000)), 0, 4000, warn, "s1")
    assert t[0] < t[1] < t[2] and t[1] == pytest.approx(2.0) and "zzz" in warn[0]


# ---- layout

def test_layout_slots_sizes_and_highlight_box():
    v = Visual(**stage({"at": "a", "kind": "icon", "name": "coins"},
                       {"at": "b", "kind": "label", "text": "Mahal", "pos": "tl"},
                       {"at": "c", "kind": "highlight", "target": 1}))
    boxes = stage_mod.layout("s1", v.elements, {}, (450, 1170))
    assert boxes[1]["slot"] == "tl" and boxes[0]["slot"] == "mr"       # explicit pos first, rest auto (pair)
    assert boxes[0]["size"] == "m"                                      # two props share the stage
    hl, ic = boxes[2], boxes[0]
    pad = 2 * stage_mod.cfg("highlight.pad")
    assert (hl["x"], hl["y"], hl["w"], hl["h"]) == (ic["x"], ic["y"], ic["w"] + pad, ic["h"] + pad)
    for b in boxes.values():
        assert stage_mod.SAFE_X[0] <= b["x"] - b["w"] / 2 and b["x"] + b["w"] / 2 <= stage_mod.SAFE_X[1] + pad
        assert 450 <= b["y"] - b["h"] / 2 + (pad if b is hl else 0)


def test_compositions_by_count_and_kind():
    cut = {"at": "a", "kind": "cutout", "query": "x"}
    lab = {"at": "a", "kind": "label", "text": "x"}
    comp = lambda *els: stage_mod.composition(Visual(**stage(*els)).elements, list(range(len(els))))  # noqa: E731
    assert comp(cut) == "hero" and comp(cut, lab) == "hero_tag" and comp(cut, cut) == "pair"
    assert comp(cut, lab, lab) == "hero_two" and comp(lab, cut, lab) == "hero_two" and comp(cut, cut, lab) == "trio"
    late = stage_mod.layout("s1", Visual(**stage(lab, cut)).elements, {1: {"w": 800, "h": 800, "render": "cutout"}},
                            (450, 1270))
    assert late[1]["size"] == "l" and late[0]["size"] == "s"            # the photo is the hero, even second
    assert comp(*[lab] * 4) == "grid4" and comp(*[lab] * 6) == "scatter6"
    v = Visual(**stage(cut, lab))
    boxes = stage_mod.layout("s1", v.elements, {0: {"w": 800, "h": 800, "render": "cutout"}}, (450, 1270))
    assert boxes[0]["size"] == "l" and boxes[0]["h"] >= 600 and boxes[1]["y"] > boxes[0]["y"]   # hero + tag below


def test_rows_follow_the_free_area_under_the_title():
    v = Visual(**stage(*({"at": w, "kind": "icon", "name": "coins"} for w in "abcd")))
    short = stage_mod.layout("s1", v.elements, {}, (450, 1170))
    tall = stage_mod.layout("s1", v.elements, {}, (560, 1170))          # two-line title
    assert [b["slot"] for b in short.values()] == ["tl", "tr", "bl", "br"]
    assert all(tall[i]["y"] > short[i]["y"] for i in tall)              # props move down with the title
    gap_top = tall[0]["y"] - tall[0]["h"] / 2 - 560
    gap_bottom = 1170 - (tall[2]["y"] + tall[2]["h"] / 2)
    assert gap_top > 10 and gap_bottom > 10                             # breathing room both ends


def test_builtin_sets_render_css():
    for bg in ("grid", "studio", "spotlight", "desk"):
        css = str(stage_mod.background_css(bg))
        layers = css.split("background-image:")[1].split("; background-size")[0].count("gradient(")
        sizes = css.split("background-size:")[1].rstrip(";").split(",")
        assert layers == len(sizes) and css.startswith("background-color:")       # one size per layer
    assert "34px 34px" in stage_mod.background_css("grid") and stage_mod.tone("spotlight") == "dark"
    assert Visual(**stage({"at": "a", "kind": "stamp", "text": "BERHASIL", "tone": "up"})).elements[0].kind == "stamp"


def test_photo_boxes_keep_aspect_and_fit_the_stage():
    v = Visual(**stage({"at": "a", "kind": "cutout", "query": "x"}))
    [b] = stage_mod.layout("s1", v.elements, {0: {"w": 2000, "h": 500, "render": "cutout"}}, (450, 1170)).values()
    assert b["w"] / b["h"] == pytest.approx(4, rel=0.01) and b["w"] <= 900


def test_stamps_overlap_props_but_never_text():
    def hit(a, b):
        return abs(a["x"] - b["x"]) < (a["w"] + b["w"]) / 2 and abs(a["y"] - b["y"]) < (a["h"] + b["h"]) / 2

    text = Visual(**stage({"at": "a", "kind": "label", "text": "Sembilan = diskon?"},
                          {"at": "b", "kind": "stamp", "text": "Rp100.000"}))
    b = stage_mod.layout("s1", text.elements, {}, (450, 1170))
    assert not hit(b[0], b[1])                                          # a stamp never covers a label
    prop = Visual(**stage({"at": "a", "kind": "cutout", "query": "x"}, {"at": "b", "kind": "stamp", "text": "BOHONG"}))
    b = stage_mod.layout("s1", prop.elements, {0: {"w": 800, "h": 800, "render": "cutout"}}, (450, 1170))
    assert len(b) == 2 and b[0]["h"] >= 400                             # the prop stays big; the stamp may land on it


def test_tilt_is_deterministic_and_bounded():
    assert stage_mod.tilt("s1", 0, "cutout") == stage_mod.tilt("s1", 0, "cutout")
    assert all(abs(stage_mod.tilt("s", i, "cutout")) <= stage_mod.cfg("tilt_deg") for i in range(20))
    assert stage_mod.tilt("s", 3, "highlight") == 0


# ---- lint

def _spec(*scenes):
    return Spec.model_validate({"slug": "t", "scenes": list(scenes)})


def test_lint_stage_anchors_template_and_gaps():
    narr = "Harga tempe naik karena kedelai impor makin mahal dan rupiah melemah terus menerus sepanjang tahun ini"
    good = {"id": "s1", "template": "explain", "narration": narr,
            "visual": stage({"at": "tempe", "kind": "label", "text": "Tempe"},
                            {"at": "kedelai", "kind": "icon", "name": "bean"},
                            {"at": "rupiah", "kind": "number", "text": "Rp18rb"})}
    issues = [str(i) for i in lint(_spec(good))]
    assert not any("not a word" in i for i in issues)
    assert any("nothing new on the stage" in i for i in issues)              # long tail after 'rupiah'

    bad = {**good, "template": "stat", "stat": {"value": 1},
           "visual": stage({"at": "kedelai", "kind": "label", "text": "x"}, {"at": "tempe", "kind": "label", "text": "y"})}
    msgs = [str(i) for i in lint(_spec(bad)) if i.level == "error"]
    assert any("not 'stat'" in m for m in msgs)
    assert any("'tempe' is not a word in the narration after the previous stage element" in m for m in msgs)


def test_look_stage_needs_most_stageable_scenes_staged():
    lab = {"at": "harga", "kind": "label", "text": "Harga"}
    st = lambda i: {"id": f"s{i}", "template": "explain", "narration": "Harga naik lagi", "visual": stage(lab)}  # noqa: E731
    stock = lambda i: {"id": f"s{i}", "template": "explain", "narration": "Harga naik lagi",  # noqa: E731
                       "visual": {"type": "stock_video", "query": "market", "name": "store"}}
    card = {"id": "c", "template": "stat", "narration": "Naik lima persen", "stat": {"value": 5}}

    def look_errors(*scenes, look="stage"):
        spec = Spec.model_validate({"slug": "t", "look": look, "scenes": list(scenes)})
        return [str(i) for i in lint(spec) if i.level == "error" and 'look "stage"' in str(i)]

    assert look_errors(stock(1), st(2), st(3), card)                       # 2/3 < 70%
    assert "s1" in look_errors(stock(1), st(2), st(3), card)[0]            # names what to convert
    assert not look_errors(stock(1), st(2), st(3), st(4), card)            # 3/4, stat cards don't count
    assert not look_errors(stock(1), stock(2), card, look="mixed")
    assert Spec.model_validate({"slug": "t", "scenes": [card]}).look == "mixed"


def test_writer_asks_for_and_keeps_the_stage_look():
    from klip.stages import script
    _, user = script.build_prompts("Kenapa harga tempe naik?", "male", 45, "default", False, look="stage")
    assert "Look: stage" in user and "70%" in user
    _, plain = script.build_prompts("Kenapa harga tempe naik?", "male", 45, "default", False)
    assert "Look:" not in plain
    data = {"slug": "t", "look": "mixed", "scenes": [
        {"id": "s1", "template": "hook", "narration": "Harga naik lagi", "visual": stage({**{"at": "harga", "kind": "label", "text": "Harga"}})}]}
    spec, _, _ = script._validate(data, "male", 45, "default", look="stage")
    assert spec.look == "stage"                                             # the caller's switch wins


# ---- cut-outs

def _rgba(w, h, box):
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    im.paste((200, 30, 30, 255), box)
    return im


def test_sticker_crops_to_subject_and_adds_outline():
    out = cutout.sticker(_rgba(400, 300, (100, 100, 200, 200)), outline_px=10, max_px=900)
    assert out.size == (124, 124)                               # 100 px subject + 2 * (10 + 2)
    assert out.getpixel((5, 62))[3] > 200 and out.getpixel((5, 62))[:3] == (255, 255, 255)  # white rim
    assert out.getpixel((62, 62))[:3] == (200, 30, 30)
    assert out.getpixel((0, 0))[3] < 10                         # only the soft edge of the rim


@pytest.fixture
def cut_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(cutout, "CACHE_DIR", tmp_path / "cache")
    return tmp_path


def test_cut_out_uses_a_given_transparent_png(cut_cache):
    src = cut_cache / "own.png"
    _rgba(300, 300, (50, 50, 250, 250)).save(src)
    out, how = cutout.cut_out(src)
    assert how == "given" and Image.open(out).mode == "RGBA"


def test_cut_out_rejects_bad_masks_and_falls_back(cut_cache, monkeypatch):
    src = cut_cache / "photo.jpg"
    Image.new("RGB", (300, 300), (90, 90, 90)).save(src)

    def whole_frame(s, out):
        _rgba(300, 300, (0, 0, 300, 300)).save(out)     # "subject" = the whole photo
        return True

    monkeypatch.setitem(cutout.BACKENDS, "apple", whole_frame)
    monkeypatch.setitem(cutout.BACKENDS, "rembg", lambda s, o: False)
    out, why = cutout.cut_out(src)
    assert out is None and "covers 100%" in why
    assert Image.open(cutout.card(src)).format == "JPEG"


def test_backend_setting(monkeypatch):
    from klip import config
    monkeypatch.setattr(config, "get", lambda k, d=None: {"backend": "rembg"} if k == "stage.cutout" else d)
    assert cutout.backends() == ["rembg"]
    monkeypatch.setattr(config, "get", lambda k, d=None: {"backend": "nope"} if k == "stage.cutout" else d)
    with pytest.raises(cutout.CutoutError):
        cutout.backends()


# ---- assets

def _photo(id, tags):
    c = Candidate(provider="p", id=id, kind="photo", renditions=[Rendition("u", 1000, 1000)])
    c.tags = tags
    return c


def test_fetch_stage_one_unused_relevant_photo_per_prop():
    zebra = _photo("zebra", ["zebra", "isolated", "animal"])      # matches only the suffix word
    tempe = _photo("tempe", ["tempeh", "food"])
    s = Scene(id="s1", template="explain", narration="tempe dan tahu",
              visual=stage({"at": "tempe", "kind": "cutout", "query": "tempeh"},
                           {"at": "tahu", "kind": "photo", "query": "tempeh"},
                           {"at": "dan", "kind": "label", "text": "x"}))
    used, warn = set(), []
    rows = assets.fetch_stage(s, used, [FakeProvider("p", [zebra, tempe])], warn)
    assert [(r["el"], r["credit"]["id"]) for r in rows] == [(0, "tempe")]   # never the zebra; never twice
    assert "no photo for stage element at 'tahu'" in warn[0]


def test_fetch_records_stage_props_and_credits(tmp_path):
    spec = _spec({"id": "s1", "template": "hook", "narration": "harga tempe",
                  "visual": stage({"at": "tempe", "kind": "cutout", "query": "tempeh"})})
    res = assets.fetch(spec, tmp_path, providers=[FakeProvider("p", [_photo("t1", ["tempeh"])])])
    assert res["scenes"]["s1"]["kind"] is None and res["scenes"]["s1"]["stage"][0]["el"] == 0
    assert [c["scene"] for c in json.loads((tmp_path / "credits.json").read_text())] == ["s1"]


def test_qa_counts_stage_props_as_sources_and_credits():
    from klip.stages.qa import check_credits, check_footage
    a = {"scenes": {"s1": {"stage": [{"source": "p:1"}]}, "s2": {"stage": [{"source": "p:1"}]}}}
    assert not check_footage(a)["ok"]
    assert not check_credits(a, [{"scene": "s1"}])["ok"]
    c = check_credits(a, [{"scene": "s1"}, {"scene": "s2"}])
    assert c["ok"] and c["detail"].startswith("2 stock")


# ---- compose

def _timeline(*scenes):
    t, out = 0.0, []
    for sid, ms in scenes:
        out.append({"id": sid, "start_ms": t, "duration_ms": ms})
        t += ms
    return {"scenes": out, "total_ms": t}


@needs_renderer
def test_compose_stage_run_keeps_background_and_cues_sfx(tmp_path):
    spec = _spec(
        {"id": "s1", "template": "hook", "narration": "harga tempe naik", "on_screen_text": "Tempe naik?",
         "visual": stage({"at": "tempe", "kind": "cutout", "query": "tempeh", "label": "Tempe"},
                         {"at": "naik", "kind": "number", "text": "+20%", "tone": "up"})},
        {"id": "s2", "template": "explain", "narration": "karena kedelai impor",
         "visual": stage({"at": "kedelai", "kind": "bar", "bars": [{"label": "A", "value": 1}, {"label": "B", "value": 3}]},
                         {"at": "impor", "kind": "highlight", "target": 1})},
        {"id": "s3", "template": "cta", "narration": "follow ya"})
    ws = words(("harga", 100), ("tempe", 600), ("naik", 1400)) + \
        words(("karena", 3100), ("kedelai", 3600), ("impor", 4400), scene="s2") + \
        words(("follow", 6100), ("ya", 6500), scene="s3")
    media = {"s1": {"kind": None, "stage": [{"el": 0, "render": "cutout", "file": "media/s1_el0.png",
                                             "w": 400, "h": 500, "source": "p:1"}]}}
    ctx, warnings = compose.build_context(spec, _timeline(("s1", 3000), ("s2", 3000), ("s3", 2000)), ws,
                                          {"scenes": media})
    s1, s2 = ctx["scenes"][0]["stage"], ctx["scenes"][1]["stage"]
    assert not warnings and s1["bg"] == s2["bg"] == "grid" and s1["tone"] == "light"
    assert not s1["continues"] and s1["next_same"] and s2["continues"] and not s2["next_same"]
    assert s1["bg_to"] == s2["bg_from"]                                 # one continuous pan
    assert all(e["exit"] == pytest.approx(3 - 0.25) for e in s1["elements"])   # props sweep off before s2
    assert s2["elements"][0]["bars"][1]["pct"] == 100
    moments = [(e["moment"], e["t"]) for e in ctx["sfx"]]
    assert ("scene_cut", pytest.approx(3 - compose.WHOOSH_PEAK_S)) not in moments     # no whoosh s1→s2
    assert any(m in ("scene_cut", "transition") and t == pytest.approx(6 - compose.WHOOSH_PEAK_S)
               for m, t in moments)                                                 # stage → cta
    assert ("stage_pop", pytest.approx(0.54)) in moments and ("stage_number", pytest.approx(1.34)) in moments

    from jinja2 import Environment, FileSystemLoader, StrictUndefined
    from klip.paths import TEMPLATES_DIR
    env = Environment(loader=FileSystemLoader(TEMPLATES_DIR / "default"), undefined=StrictUndefined,
                      autoescape=True, trim_blocks=True, lstrip_blocks=True)
    env.filters["rgba"] = compose.rgba
    html = env.get_template("index.html.j2").render(**ctx)
    assert 'id="st-s1-0"' in html and "media/s1_el0.png" in html and ".bg-grid" in html
    assert "stage tone-light" in html and 'class="st-title plain"' in html
    assert all(p["stage"] for p in ctx["pages"])          # stage captions; the cta's words aren't captioned
    assert 'class="cap clip st light"' in html and "backgroundSize" in html                        # underline marker
    assert "st-s2-1 .st-hl" in html and "#sc-s1 .bg" not in html


@needs_renderer
@pytest.mark.parametrize("mode", ["overlay", "none"])
def test_outro_overlay_keeps_the_last_scene_playing(monkeypatch, mode):
    from klip import config
    base = config.style("default")
    style = {**base, "outro": {**base["outro"], "mode": mode, "text": "Tetap bernalar."}}
    monkeypatch.setattr(compose.config, "style", lambda name="default": style)
    spec = _spec({"id": "s1", "template": "explain", "narration": "harga tempe naik",
                  "visual": stage({"at": "tempe", "kind": "label", "text": "Tempe"})},
                 {"id": "s2", "template": "cta", "cta_type": "follow", "narration": "follow ya",
                  "on_screen_text": "Follow ya"})
    ws = words(("harga", 100), ("tempe", 600), ("naik", 1400)) + words(("follow", 3100), ("ya", 3500), scene="s2")
    ctx, _ = compose.build_context(spec, _timeline(("s1", 3000), ("s2", 2000)), ws, {"scenes": {}})
    s1, s2 = ctx["scenes"]
    assert s2["hidden"] and s1["end"] == 5.0 and s1["dur"] == 5.0          # s1 runs under the cta narration
    assert all(p["words"][0]["text"] != "follow" for p in ctx["pages"])
    moments = [e["moment"] for e in ctx["sfx"]]
    assert "scene_cut" not in moments
    o = ctx["brand"]["outro"]
    if mode == "none":
        assert o is None and "cta_icon" not in moments
        return
    assert [h["text"] for h in o["text"]] == ["Tetap", "bernalar."] and o["chip"]["label"] == "Follow"
    assert o["start"] == 3.0 and "cta_ask" in moments


@needs_renderer
def test_compose_leaves_out_props_without_an_image():
    spec = _spec({"id": "s1", "template": "explain", "narration": "harga tempe naik",
                  "visual": stage({"at": "tempe", "kind": "cutout", "query": "tempeh"},
                                  {"at": "naik", "kind": "highlight", "target": 1},
                                  {"at": "naik", "kind": "label", "text": "Naik"})})
    ctx, warnings = compose.build_context(spec, _timeline(("s1", 3000)), words(("harga", 0), ("tempe", 500), ("naik", 1200)),
                                          {"scenes": {"s1": {"kind": None, "stage": []}}})
    assert [e["kind"] for e in ctx["scenes"][0]["stage"]["elements"]] == ["label"]
    assert any("no image for stage element" in w for w in warnings)
