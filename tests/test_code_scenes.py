"""Code scenes (visual.type "code"): spec rules, parsing, lint, look bible, compose."""

import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from klip import codescene
from klip.lint import lint
from klip.spec import Spec, Visual
from klip.stages import compose
from tests.test_stage import _timeline, needs_renderer, words

SCENE = """<svg class="sky" viewBox="0 0 1080 1920"><circle id="sun" cx="540" cy="700" r="120" fill="var(--k-accent)"/></svg>
<img src="@asset/farm.png" alt="">
<style>.sky { position: absolute; inset: 0; } img { width: 300px; }</style>
<script>
const sun = k.$("#sun");
k.tl.from(sun, { scale: 0, transformOrigin: "50% 50%", duration: 0.4, ease: k.look.ease.pop }, k.at("matahari"));
k.frame((t) => { sun.setAttribute("cy", 700 - t * 10); });
</script>
"""


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.setattr(codescene, "ROOT", tmp_path)
    (tmp_path / "specs").mkdir()
    (tmp_path / "specs" / "s1.html").write_text(SCENE)
    (tmp_path / "specs" / "farm.png").write_bytes(b"png")
    return tmp_path


def _spec(*scenes, **kw):
    return Spec.model_validate({"slug": "t", "scenes": list(scenes), **kw})


def code(file="specs/s1.html", **kw):
    return {"type": "code", "code": {"file": file, **kw}}


def test_code_visual_needs_its_file():
    with pytest.raises(ValidationError, match="requires visual.code"):
        Visual(type="code")
    with pytest.raises(ValidationError, match="only for visual.type='code'"):
        Visual(type="solid", code={"file": "a.html"})
    with pytest.raises(ValidationError, match="pattern"):
        Visual(**code("a.js"))


def test_look_bible_palette_is_validated():
    with pytest.raises(ValidationError, match="#RRGGBB"):
        _spec({"id": "s1", "template": "hook", "narration": "a"}, look_bible={"palette": {"bg": "red"}})
    with pytest.raises(ValidationError, match="lowercase"):
        _spec({"id": "s1", "template": "hook", "narration": "a"}, look_bible={"palette": {"Bg": "#000000"}})


def test_parse_splits_markup_css_and_script():
    f = codescene.parse(SCENE)
    assert f.markup.startswith("<svg") and "<style" not in f.markup and "<script" not in f.markup
    assert ".sky" in f.css and "k.tl.from" in f.js
    with pytest.raises(codescene.CodeSceneError, match="exactly one <script>"):
        codescene.parse("<div></div>")
    with pytest.raises(codescene.CodeSceneError, match="inline"):
        codescene.parse('<script src="x.js"></script>')


def test_lint_catches_clock_apis_cues_urls_and_assets(repo):
    bad = SCENE.replace("k.frame", "Math.random(); requestAnimationFrame(() => {}); k.frame") \
        .replace("@asset/farm.png", "https://example.com/a.png").replace('k.at("matahari")', 'k.at("bulan")')
    (repo / "specs" / "bad.html").write_text(bad + "<style>.a { transition: all 1s; }</style>")
    spec = _spec({"id": "s1", "template": "hook", "narration": "matahari terbit pagi ini",
                  "visual": code("specs/bad.html")})
    msgs = [str(i) for i in lint(spec) if i.where == "s1"]
    assert any("Math.random" in m for m in msgs) and any("requestAnimationFrame" in m for m in msgs)
    assert any("k.at('bulan') is not in the narration" in m for m in msgs)
    assert any("remote URL https://example.com/a.png" in m for m in msgs)
    assert any("CSS transitions" in m for m in msgs)
    # the good file, with its asset declared: no code errors (the SVG namespace URL is fine)
    ok = _spec({"id": "s1", "template": "hook", "narration": "matahari terbit pagi ini",
                "visual": code(assets=["specs/farm.png"])})
    assert not [i for i in lint(ok) if i.where == "s1" and i.level == "error"]
    missing = _spec({"id": "s1", "template": "hook", "narration": "matahari terbit", "visual": code()})
    assert any("@asset/farm.png is not in visual.code.assets" in str(i) for i in lint(missing))


def test_look_merges_config_style_and_spec(repo):
    from klip import config
    style = {**config.style("default"), "look_bible": {"palette": {"bg": "#101010"}, "texture": "hud"}}
    spec = _spec({"id": "s1", "template": "hook", "narration": "a"},
                 look_bible={"palette": {"ink": "#FAFAFA"}, "fonts": {"display": "fraunces"}, "motion": "bouncy"})
    lk = codescene.look(spec, style)
    assert lk["palette"]["bg"] == "#101010" and lk["palette"]["ink"] == "#FAFAFA"
    assert lk["palette"]["accent"] == style["accent_color"] and lk["texture"] == "hud"
    assert lk["families"]["display"] == "Fraunces" and lk["tone"] == "dark"
    assert lk["ease"]["pop"].startswith("elastic") and lk["texture_strength"] == config.get("code.textures.hud")
    bad = Spec.model_validate({**spec.model_dump(), "look_bible": {"fonts": {"display": "comic"}}})
    with pytest.raises(codescene.CodeSceneError, match="unknown font 'comic'"):
        codescene.look(bad, style)


@needs_renderer
def test_compose_inlines_scoped_scene_with_kit(repo):
    spec = _spec({"id": "s1", "template": "hook", "narration": "matahari terbit", "on_screen_text": "Pagi",
                  "visual": code(assets=["specs/farm.png"])},
                 {"id": "s2", "template": "explain", "narration": "lalu terbenam",
                  "visual": code(captions=False, texture="grain")})
    ws = words(("matahari", 100), ("terbit", 600)) + words(("lalu", 2100), ("terbenam", 2500), scene="s2")
    ctx, warnings = compose.build_context(spec, _timeline(("s1", 2000), ("s2", 2000)), ws, {"scenes": {}})
    s1, s2 = (s["code"] for s in ctx["scenes"])
    assert not warnings and s1["meta"]["words"][0] == {"text": "matahari", "t": 0.1, "end": 0.4}
    assert s1["meta"]["start"] == 0 and s2["meta"]["start"] == 2.0 and s2["texture"] == "grain"
    assert "@scope (#sc-s1)" in s1["css"] and 'src="code/s1/farm.png"' in s1["markup"]
    assert s1["assets"] == [{"path": str(repo / "specs" / "farm.png"), "src": "code/s1/farm.png"}]
    assert all(p["stage"] for p in ctx["pages"]) and ctx["pages"][0]["light"]      # paper bg is light
    assert all("lalu" not in [w["text"] for w in p["words"]] for p in ctx["pages"])  # s2: captions off

    from jinja2 import Environment, FileSystemLoader, StrictUndefined
    from klip.paths import TEMPLATES_DIR
    env = Environment(loader=FileSystemLoader(TEMPLATES_DIR / "default"), undefined=StrictUndefined,
                      autoescape=True, trim_blocks=True, lstrip_blocks=True)
    env.filters["rgba"] = compose.rgba
    html = env.get_template("index.html.j2").render(**ctx)
    assert 'class="scene clip code"' in html and "function klipScene" in html
    assert html.count('klipScene({"beats": []') == 2 and 'k.at("matahari")' in html
    assert "--k-bg: #F3EDE2;" in html and 'font-family: "Fraunces"' in html
    assert 'class="k-tex k-tex-grain"' in html and "three.min.js" not in html


def test_cue_times_come_from_the_voice(repo):
    spec = _spec({"id": "s1", "template": "hook", "narration": "matahari terbit", "visual": code()})
    ws = words(("matahari", 1200), ("terbit", 1700))
    assert codescene.cue_times(spec.scenes[0], ws) == [(1.2, "matahari")]


def test_include_runs_before_the_scene_script_and_is_linted(repo):
    (repo / "specs" / "lib.js").write_text("function sun() { return k.$('#sun'); }\n")
    (repo / "specs" / "bad.js").write_text("const t = Date.now();\n")
    spec = _spec({"id": "s1", "template": "hook", "narration": "matahari terbit",
                  "visual": code(assets=["specs/farm.png"], include=["specs/lib.js"])})
    js = codescene.load(spec.scenes[0]).js
    assert js.index("function sun") < js.index("k.tl.from")
    assert not [i for i in lint(spec) if i.where == "s1" and i.level == "error"]
    bad = _spec({"id": "s1", "template": "hook", "narration": "matahari terbit",
                 "visual": code(assets=["specs/farm.png"], include=["specs/bad.js"])})
    assert any("no Date" in str(i) for i in lint(bad))


def test_mascot_names_and_poses_are_checked_against_the_cast(repo, monkeypatch):
    from klip import mascot
    style = {"mascot": {"cast": [{"name": "napa", "dir": "x", "voice": "female"}]}}
    monkeypatch.setattr(mascot, "video_style", lambda spec: style)
    monkeypatch.setattr(mascot, "_poses", lambda d: {"netral": "<svg/>", "kaget": "<svg/>"})
    (repo / "specs" / "m.html").write_text('<div></div><script>const n = k.mascot("napa"); n.pose("kaget", 0);'
                                           'k.mascot("budi"); n.pose("joget", 1);</script>')
    spec = _spec({"id": "s1", "template": "hook", "narration": "a b c", "visual": code("specs/m.html")})
    msgs = [i.message for i in lint(spec) if i.where == "s1"]
    assert any("k.mascot('budi')" in m for m in msgs) and any("pose 'joget'" in m for m in msgs)
    assert not any("k.mascot('napa')" in m or "pose 'kaget'" in m for m in msgs)


def test_kit_layout_puts_the_headline_under_the_series_pill_and_mascots_on_their_spots(monkeypatch):
    from klip import config, mascot
    style = {**config.style("default"), "mascot": {**mascot.settings(config.style("default")),
                                                   "cast": [{"name": "a", "dir": "x", "side": "left"},
                                                            {"name": "b", "dir": "y", "side": "right"}]}}
    monkeypatch.setattr(mascot, "_poses", lambda d: {"netral": '<svg viewBox="0 0 200 200"></svg>'})
    sc = {"start": 0.0, "end": 3.0}
    pill = {"top": 262, "font_size": 34, "spans": [{"start": 0.0, "end": 3.0}]}
    with_pill = codescene.layout(style, sc, {"series": pill, "outro": None}, 1290)
    without = codescene.layout(style, {"start": 3.0, "end": 6.0}, {"series": pill, "outro": None}, 1290)
    assert with_pill["headlineTop"] > 262 + 34 and without["headlineTop"] == config.get("code.kit.headline.top")
    h = mascot.settings(style)["height"]
    a, b = with_pill["cast"]
    assert a["x"] == 60 + mascot.settings(style)["inset_px"] and b["x"] + b["w"] == 960 - mascot.settings(style)["inset_px"]
    assert a["y"] == mascot.top(style, 1290) and a["h"] == h == b["w"]
    assert codescene.uses_mascots("const c = k.cast();") and not codescene.uses_mascots("k.camera(x)")


@needs_renderer
def test_code_scene_sfx_cues_land_on_their_words(repo):
    (repo / "assets" / "sfx").mkdir(parents=True)
    (repo / "assets" / "sfx" / "pop.wav").write_bytes(b"wav")
    spec = _spec({"id": "s1", "template": "hook", "narration": "matahari terbit",
                  "visual": code(assets=["specs/farm.png"], sfx=[{"at": "terbit", "sfx": "pop", "offset_s": -0.1}])})
    assert not [i for i in lint(spec) if i.where == "s1" and i.level == "error"]
    ws = words(("matahari", 100), ("terbit", 900))
    ctx, _ = compose.build_context(spec, _timeline(("s1", 2000)), ws, {"scenes": {}})
    assert {"t": 0.8, "moment": "code_cue", "sfx": "pop"} in ctx["sfx"]
    bad = _spec({"id": "s1", "template": "hook", "narration": "matahari terbit",
                 "visual": code(assets=["specs/farm.png"], sfx=[{"at": "bulan", "sfx": "boom"}])})
    msgs = [i.message for i in lint(bad) if i.where == "s1"]
    assert any("'bulan' is not in the narration" in m for m in msgs) and any("no effect 'boom'" in m for m in msgs)


def test_tag_feet_marks_the_two_lowest_ellipses_left_to_right():
    svg = ('<svg viewBox="0 0 200 220"><ellipse cx="128" cy="208" rx="18" ry="9"/><ellipse cx="72" cy="208" rx="18" ry="9"/>'
           '<ellipse cx="100" cy="120" rx="60" ry="70"/></svg>')
    out = codescene.tag_feet(svg)
    assert '<ellipse class="k-foot k-foot-l" cx="72"' in out and '<ellipse class="k-foot k-foot-r" cx="128"' in out
    assert '<ellipse cx="100"' in out                                     # the body is left alone
    ball = '<svg viewBox="0 0 200 220"><ellipse cx="100" cy="120" rx="60" ry="70"/></svg>'
    assert codescene.tag_feet(ball) == ball                               # no feet (a rolled-up pose): unchanged
    marked = '<svg viewBox="0 0 10 10"><path class="foot-l" d=""/><path class="foot-r" d=""/></svg>'
    assert 'class="k-foot k-foot-l"' in codescene.tag_feet(marked)       # an SVG's own marks win


def test_kit_and_scenes_avoid_template_literal_selectors(repo):
    from klip.paths import TEMPLATES_DIR
    kit = (TEMPLATES_DIR / "default" / "scenes" / "code_kit.js.j2").read_text()
    assert not re.search(r"querySelector(All)?\(\s*`[^`]*\$\{", kit)      # HyperFrames --strict rejects them
    (repo / "specs" / "q.html").write_text("<div></div><script>document.querySelector(`#a${1}`);</script>")
    spec = _spec({"id": "s1", "template": "hook", "narration": "a b", "visual": code("specs/q.html")})
    assert any("template literals in querySelector" in i.message for i in lint(spec))


def test_the_starter_gallery_uses_every_starter_and_lints_clean():
    from klip.paths import ROOT
    from klip.spec import load_spec
    spec = load_spec(ROOT / "examples" / "code-gallery.json")
    used = {Path(s.visual.code.file).name for s in spec.scenes}
    assert used == {p.name for p in (ROOT / "examples" / "code-scenes" / "starters").glob("*.html")}
    assert not [str(i) for i in lint(spec) if i.level == "error"]


def test_cinematic_preset_sits_between_the_style_and_the_spec(repo):
    from klip import config
    style = {**config.style("default"), "look_bible": {"texture": "paper", "line": 6}}
    spec = _spec({"id": "s1", "template": "hook", "narration": "a"},
                 look_bible={"preset": "cinematic", "palette": {"accent": "#FF8A3D"}, "line": 2})
    lk = codescene.look(spec, style)
    preset = config.get("code.looks.cinematic")
    assert lk["palette"]["bg"] == preset["palette"]["bg"] and lk["tone"] == "dark"
    assert lk["texture"] == "film" and lk["texture_strength"] == config.get("code.textures.film")
    assert lk["ease"]["inOut"] == "expo.inOut" and lk["line"] == 2 and lk["palette"]["accent"] == "#FF8A3D"
    assert "preset" not in lk
    branded = codescene.look(_spec({"id": "s1", "template": "hook", "narration": "a"}),
                             {**style, "look_bible": {"preset": "cinematic"}})
    assert branded["palette"]["accent"] == style["accent_color"] and branded["texture"] == "film"
    bad = _spec({"id": "s1", "template": "hook", "narration": "a"}, look_bible={"preset": "noir"})
    with pytest.raises(codescene.CodeSceneError, match="unknown look 'noir'"):
        codescene.look(bad, style)


def test_film_texture_keeps_its_vignette_still_while_the_grain_jumps(repo):
    css = str(codescene.texture_css("film", 0.3))
    assert "radial-gradient" in css and "opacity: 0.3" in css
    from klip.paths import ROOT
    kit = (ROOT / "templates" / "default" / "scenes" / "code_kit.js.j2").read_text()
    assert '"film" ? "0px 0px, "' in kit
    for helper in ("k.glow = function", "k.bloom = function", "k.flare = function"):
        assert helper in kit


def test_paper_ink_contrasts_with_paper(repo):
    from klip import config
    style = config.style("default")
    dark = _spec({"id": "s1", "template": "hook", "narration": "a"},
                 look_bible={"palette": {"bg": "#101418", "paper": "#F4EFE6", "ink": "#F4EFE6"}})
    assert codescene.look(dark, style)["palette"]["paper-ink"] == "#101418"      # light ink on light paper: use bg
    light = _spec({"id": "s1", "template": "hook", "narration": "a"})
    lk = codescene.look(light, style)
    assert lk["palette"]["paper-ink"] == lk["palette"]["ink"]


def test_world_runs_under_consecutive_code_scenes(repo):
    world = {"file": "specs/s1.html"}
    a = {"id": "a", "template": "hook", "narration": "matahari terbit", "visual": code()}
    b = {"id": "b", "template": "explain", "narration": "lalu terbenam", "visual": code()}
    c = {"id": "c", "template": "cta", "narration": "ikuti kami"}
    spec = _spec(a, b, c, world=world)
    assert [s.id for s in codescene.world_run(spec)] == ["a", "b"]
    assert codescene.world_scene(spec).narration == "matahari terbit lalu terbenam"
    ws = words(("matahari", 100), ("terbit", 600), scene="a") + words(("lalu", 2100), ("terbenam", 2500), scene="b") \
        + words(("ikuti", 4100), ("kami", 4400), scene="c")
    ctx, _ = compose.build_context(spec, _timeline(("a", 2000), ("b", 2000), ("c", 1000)), ws, {"scenes": {}})
    w = ctx["world"]["meta"]
    assert w["start"] == 0 and w["dur"] == 4.0 and w["texture"] == "none"
    assert w["scenes"] == [{"id": "a", "start": 0, "end": 2.0}, {"id": "b", "start": 2.0, "end": 4.0}]
    assert [x["text"] for x in w["words"]] == ["matahari", "terbit", "lalu", "terbenam"] and w["words"][2]["t"] == 2.1
    assert [bool(s.get("on_world")) for s in ctx["scenes"]] == [True, True, False]

    gap = _spec(a, c, b, world=world)
    with pytest.raises(codescene.CodeSceneError, match="consecutive"):
        codescene.world_run(gap)
    with pytest.raises(codescene.CodeSceneError, match="must be code scenes"):
        codescene.world_run(_spec(a, b, c, world={**world, "scenes": ["b", "c"]}))
    (repo / "specs" / "w.html").write_text("<script>k.tl.set({}, {}, k.at('terbenam')); k.at('bulan');</script>")
    world_issues = [i for i in lint(_spec(a, b, world={"file": "specs/w.html"})) if i.where == "world"]
    assert [i.message for i in world_issues if i.level == "error"] == ["specs/w.html: k.at('bulan') is not in the narration"]


def test_dark_bg_below_video_black_warns(repo):
    s = {"id": "s1", "template": "hook", "narration": "matahari terbit", "visual": code()}
    issues = lint(_spec(s, look_bible={"palette": {"bg": "#0A0A0A"}}))
    assert any("darker than video black" in i.message for i in issues if i.level == "warning")
    assert not any("video black" in i.message for i in lint(_spec(s, look_bible={"preset": "cinematic"})))


def test_kit_has_motion_helpers():
    from klip.paths import TEMPLATES_DIR
    kit = (TEMPLATES_DIR / "default" / "scenes" / "code_kit.js.j2").read_text()
    assert "k.trail = function" in kit and "k.motionBlur = function" in kit and "sceneAt(t)" in kit
