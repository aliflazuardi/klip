"""Code scenes (visual.type "code"): spec rules, parsing, lint, look bible, compose."""

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
    assert html.count('klipScene({"dur"') == 2 and 'k.at("matahari")' in html
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
