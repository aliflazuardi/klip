"""Mascots: brand-pack characters above the stage captions (poses, lip sync, reactions, lint, compose)."""

from klip import config, mascot
from klip.lint import lint
from klip.spec import Spec
from klip.stages import compose
from tests.test_stage import _timeline, needs_renderer, stage, words

STYLE = config.style("example")      # brands/example: one mascot, "bulat" (netral, tunjuk)


def spec(*scenes):
    return Spec.model_validate({"slug": "t", "style": "example", "scenes": list(scenes)})


def test_example_cast_loads_with_scoped_ids():
    assert mascot.names(STYLE) == ["bulat"] and mascot.poses(STYLE, "bulat") == ["netral", "tunjuk"]
    svg = mascot._scoped(mascot._poses(STYLE["mascot"]["cast"][0]["dir"])["netral"], "ms-bulat-netral")
    assert 'id="ms-bulat-netral-body"' in svg and "url(#ms-bulat-netral-body)" in svg and 'id="body"' not in svg


def test_flaps_one_per_word_two_for_long_words():
    m = STYLE["mascot"]["mouth"]
    flaps = mascot._flaps([{"startMs": 1000, "endMs": 1200}, {"startMs": 2000, "endMs": 2600}], m)
    assert flaps[0] == (1.0, 1.12) and len(flaps) == 3                # 0.6 × 0.2 s; the 0.6 s word flaps twice
    assert flaps[1][0] == 2.0 and flaps[2][0] == 2.3 and flaps[1][1] - flaps[1][0] <= m["open_s"] + 1e-9


def test_segments_hold_then_return_and_skip_unknown_poses():
    segs = mascot._segments([(2.0, "tunjuk", 1.0), (5.0, "nope", None), (2.5, "tunjuk", None)], {"netral", "tunjuk"})
    assert segs == [{"t": 0.0, "pose": "netral"}, {"t": 2.0, "pose": "tunjuk"}]   # the second tunjuk outlasts the hold
    segs = mascot._segments([(2.0, "tunjuk", 1.0)], {"netral", "tunjuk"})
    assert segs[-1] == {"t": 3.0, "pose": "netral"}


def test_lint_checks_cast_poses_and_words():
    base = {"id": "s1", "template": "explain", "narration": "bandar selalu menang",
            "visual": stage({"at": "bandar", "kind": "label", "text": "Bandar"})}
    ok = {**base, "mascot": {"speaker": "bulat", "poses": [{"who": "bulat", "pose": "tunjuk", "at": "menang"}]}}
    assert not [i for i in lint(spec(ok)) if i.where == "s1" and i.level == "error"]
    bad = {**base, "mascot": {"speaker": "napa", "poses": [{"who": "bulat", "pose": "kaget", "at": "kalah"}]}}
    errs = [str(i) for i in lint(spec(bad)) if i.level == "error"]
    assert any("speaker 'napa'" in e for e in errs) and any("no pose 'kaget'" in e for e in errs)
    assert any("mascot pose at 'kalah'" in e for e in errs)


@needs_renderer
def test_compose_plans_mascots_on_stage_scenes():
    sp = spec({"id": "s1", "template": "hook", "narration": "bandar selalu menang",
               "visual": stage({"at": "bandar", "kind": "chart", "points": [{"x": "a", "y": 1}, {"x": "b", "y": 2}]})},
              {"id": "s2", "template": "explain", "narration": "kok bisa", "visual": {"type": "solid"}},
              {"id": "s3", "template": "explain", "narration": "karena hitungan",
               "visual": stage({"at": "karena", "kind": "label", "text": "x"}),
               "mascot": {"speaker": "none", "poses": [{"who": "bulat", "pose": "tunjuk", "at": "hitungan", "hold_s": 0.5}]}})
    ws = words(("bandar", 100), ("selalu", 500), ("menang", 900)) + words(("kok", 3100), ("bisa", 3400), scene="s2") + \
        words(("karena", 5100), ("hitungan", 5600), scene="s3")
    ctx, warnings = compose.build_context(sp, _timeline(("s1", 3000), ("s2", 2000), ("s3", 2000)), ws, {"scenes": {}})
    [m] = ctx["mascots"]
    assert [(s["start"], s["end"]) for s in m["spans"]] == [(0.0, 3.0), (5.0, 7.0)]      # not on the solid scene
    assert len(m["mouth"]) == 3 and all(a < 3 for a, _ in m["mouth"])                # speaks s1 only ("none" in s3)
    poses = [(s["t"], s["pose"]) for s in m["segments"]]
    assert any(p == "tunjuk" and t < 1 for t, p in poses)                          # points at the new chart
    assert (5.6, "tunjuk") in poses and (6.1, "netral") in poses
    top = mascot.top(STYLE, compose.caption_style(STYLE, True)["top"])
    assert m["y"] == top and ctx["scenes"][0]["stage"]["area"][1] <= top - STYLE["mascot"]["clear_px"]
    from jinja2 import Environment, FileSystemLoader, StrictUndefined
    from klip.paths import TEMPLATES_DIR
    env = Environment(loader=FileSystemLoader(TEMPLATES_DIR / "default"), undefined=StrictUndefined,
                      autoescape=True, trim_blocks=True, lstrip_blocks=True)
    env.filters["rgba"] = compose.rgba
    html = env.get_template("index.html.j2").render(**ctx)
    assert 'id="ms-bulat" class="ms clip"' in html and "ms-bulat-netral-body" in html
    assert 'tl.set("#ms-bulat .mouth-open", { opacity: 1 }' in html and "#ms-bulat .eye" in html


def test_no_cast_no_mascots():
    sp = Spec.model_validate({"slug": "t", "scenes": [{"id": "s1", "template": "explain", "narration": "a b",
                                                       "visual": stage({"at": "a", "kind": "label", "text": "x"})}]})
    assert mascot.plan(sp, [], [], config.style("default"), 1290) is None
    assert not mascot.active(sp.scenes[0], config.style("default"))


WN = {**STYLE, "mascot": {**STYLE["mascot"], "speaker": {"hook": "napa", "default": "gulung"},
                          "cast": [{"name": "napa", "dir": STYLE["mascot"]["cast"][0]["dir"], "voice": "female"},
                                   {"name": "gulung", "dir": STYLE["mascot"]["cast"][0]["dir"], "side": "right",
                                    "voice": "male"}]}}


def test_video_picks_which_mascots_appear():
    sp = spec({"id": "s1", "template": "hook", "narration": "a", "visual": stage({"at": "a", "kind": "label", "text": "x"})})
    assert mascot.names(mascot.with_cast(WN, sp)) == ["napa", "gulung"]
    assert mascot.names(mascot.with_cast(WN, sp.model_copy(update={"mascots": ["gulung"]}))) == ["gulung"]
    assert mascot.names(mascot.with_cast(WN, sp.model_copy(update={"mascots": False}))) == []
    bad = Spec.model_validate({"slug": "t", "style": "example", "mascots": ["napa"], "scenes": [sp.scenes[0].model_dump()]})
    assert any("mascots: 'napa' isn't in style 'example'" in str(i) for i in lint(bad))


def test_the_narrator_decides_who_speaks_and_vice_versa():
    sp = Spec.model_validate({"slug": "t", "voice": "male", "scenes": [
        {"id": "s1", "template": "hook", "narration": "a"},
        {"id": "s2", "template": "explain", "narration": "b", "voice": "female"},
        {"id": "s3", "template": "explain", "narration": "c", "mascot": {"speaker": "napa"}},
        {"id": "s4", "template": "explain", "narration": "d", "mascot": {"speaker": "none"}}]})
    s1, s2, s3, s4 = sp.scenes
    assert mascot.speaker(sp, s1, WN) == "gulung"               # the male narrator is Gulung, even on the hook
    assert mascot.speaker(sp, s2, WN) == "napa" and mascot.scene_voice(sp, s2, WN) == "female"
    assert mascot.scene_voice(sp, s3, WN) == "female"          # naming Napa as the speaker makes it her voice
    assert mascot.speaker(sp, s4, WN) is None and mascot.scene_voice(sp, s4, WN) == "male"
    solo = mascot.with_cast(WN, sp.model_copy(update={"mascots": ["napa"]}))
    assert mascot.speaker(sp, s1, solo) == "napa"              # a lone mascot speaks every line
    no_voices = {**WN, "mascot": {**WN["mascot"], "cast": [{**m, "voice": None} for m in WN["mascot"]["cast"]]}}
    assert mascot.speaker(sp, s1, no_voices) == "napa"         # without voices the template map decides


def test_cli_mascots_option():
    from klip.cli import parse_mascots
    assert parse_mascots(None) is None and parse_mascots("none") is False and parse_mascots("all") is True
    assert parse_mascots("Napa, gulung") == ["napa", "gulung"]
