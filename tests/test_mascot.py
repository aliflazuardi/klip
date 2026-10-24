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


@needs_renderer
def test_scene_shows_some_mascots_bigger():
    from klip.stages import compose as comp
    sp = Spec.model_validate({"slug": "t", "style": "example", "scenes": [
        {"id": "s1", "template": "hook", "narration": "aku bulat", "mascot": {"scale": 2},
         "visual": stage({"at": "aku", "kind": "label", "text": "x"})},
        {"id": "s2", "template": "explain", "narration": "dan ini", "mascot": {"show": []},
         "visual": stage({"at": "dan", "kind": "label", "text": "y"})},
        {"id": "s3", "template": "explain", "narration": "lagi kecil", "visual": stage({"at": "lagi", "kind": "label", "text": "z"})}]})
    ws = words(("aku", 100), ("bulat", 500)) + words(("dan", 3100), scene="s2") + words(("lagi", 5100), scene="s3")
    ctx, _ = comp.build_context(sp, _timeline(("s1", 3000), ("s2", 2000), ("s3", 2000)), ws, {"scenes": {}})
    [m] = ctx["mascots"]
    assert m["scale0"] == 2 and m["scales"] == [{"t": 5.0, "s": 1.0, "dx": 0, "snap": True}]       # off screen in s2: no tween and m["origin"] == "0% 100%"
    assert [(x["start"], x["end"]) for x in m["spans"]] == [(0.0, 3.0), (5.0, 7.0)]     # an empty show hides it
    cap = comp.caption_style(STYLE, True)["top"]
    assert ctx["scenes"][0]["stage"]["area"][1] <= mascot.top(STYLE, cap, 2) - STYLE["mascot"]["clear_px"]
    assert ctx["scenes"][2]["stage"]["area"][1] > ctx["scenes"][0]["stage"]["area"][1]


def test_closing_pose_waits_for_a_held_reaction():
    segs = mascot._segments([(11.9, "tunjuk", 1.5), (12.2, "netral", mascot.SOFT)], {"netral", "tunjuk"})
    assert segs == [{"t": 0.0, "pose": "netral"}, {"t": 11.9, "pose": "tunjuk"}, {"t": 13.4, "pose": "netral"}]


def test_listener_leans_in_when_the_speaker_first_points_at_a_notif():
    c = STYLE["mascot"]
    duo = {**STYLE, "mascot": {**c, "cast": [{**c["cast"][0], "name": "a", "voice": "female"},
                                              {**c["cast"][0], "name": "b", "side": "right", "voice": "male"}],
                               "auto": {**c["auto"], "point": "tunjuk", "listen": "tunjuk"}}}
    sp = Spec.model_validate({"slug": "t", "voice": "male", "scenes": [
        {"id": "s1", "template": "explain", "narration": "notif masuk lagi",
         "visual": stage({"at": "notif", "kind": "notif", "text": "x"}, {"at": "lagi", "kind": "notif", "text": "y"})}]})
    scenes = [{"id": "s1", "start": 0.0, "end": 6.0, "stage": {"elements": [
        {"kind": "notif", "start": 0.5, "i": 0}, {"kind": "notif", "start": 4.0, "i": 1}]}}]
    a, b = mascot.plan(sp, scenes, words(("notif", 500), ("lagi", 4000)), duo, 1400)
    assert [s["pose"] for s in b["segments"] if s["t"] in (0.5, 4.0)] == ["tunjuk", "tunjuk"]   # b speaks and points
    assert [(s["t"], s["pose"]) for s in a["segments"]][:2] == [(0.0, "netral"), (0.65, "tunjuk")]  # a once, at the first


@needs_renderer
def test_mascots_get_a_sticker_outline_and_ground_shadow():
    sp = spec({"id": "s1", "template": "hook", "narration": "bandar menang",
               "visual": stage({"at": "bandar", "kind": "stamp", "text": "x"}, backdrop={"kind": "phone"})})
    ctx, _ = compose.build_context(sp, _timeline(("s1", 3000)), words(("bandar", 100), ("menang", 500)), {"scenes": {}})
    assert ctx["scenes"][0]["stage"]["elements"][0]["color"] == config.get("stage.stamp.neutral_dark")   # dark set
    from jinja2 import Environment, FileSystemLoader, StrictUndefined
    from klip.paths import TEMPLATES_DIR
    env = Environment(loader=FileSystemLoader(TEMPLATES_DIR / "default"), undefined=StrictUndefined,
                      autoescape=True, trim_blocks=True, lstrip_blocks=True)
    env.filters["rgba"] = compose.rgba
    html = env.get_template("index.html.j2").render(**ctx)
    assert '<filter id="ms-outline"' in html and "url(#ms-outline)" in html and 'class="ms-ground"' in html


DUO = {**STYLE, "mascot": {**STYLE["mascot"], "cast": [
    {**STYLE["mascot"]["cast"][0], "name": "bulat", "side": "left"},
    {**STYLE["mascot"]["cast"][0], "name": "kotak", "side": "right"}]}}


def test_focus_spotlights_the_speaker_in_the_centre():
    sp = Spec.model_validate({"slug": "t", "style": "example", "scenes": [
        {"id": "s1", "template": "hook", "narration": "aku bulat", "emphasis": ["bulat"],
         "mascot": {"focus": True, "speaker": "kotak"}, "visual": stage({"at": "aku", "kind": "label", "text": "x"})},
        {"id": "s2", "template": "explain", "narration": "dan ini", "visual": stage({"at": "dan", "kind": "label", "text": "y"})}]})
    ws = words(("aku", 100), ("bulat", 1300)) + words(("dan", 3100), ("ini", 3500), scene="s2")
    plan = mascot.plan(sp, [{"id": "s1", "start": 0.0, "end": 3.0}, {"id": "s2", "start": 3.0, "end": 5.0}],
                       ws, DUO, 1290)
    b, k = plan
    fh = DUO["mascot"]["focus"]["height"]
    s = fh / DUO["mascot"]["height"]
    # the star (kotak, the speaker) is big and centred in s1, back in its corner in s2
    assert k["scale0"] == round(s, 3)
    assert abs(k["x"] + k["w"] + k["dx0"] - k["w"] * s / 2 - 540) < 1
    assert k["scales"] == [{"t": 3.0, "s": 1.0, "dx": 0, "snap": False}]     # on screen across the cut: tweens
    assert [(f["start"], f["end"]) for f in k["focus"]] == [(0.0, 3.0)] and not b["focus"]
    # the other one sits the focus scene out
    assert [(x["start"], x["end"]) for x in b["spans"]] == [(3.0, 5.0)]
    # spotlit + emphasised word = a hop; the first word gets a lean
    assert [g["k"] for g in k["gestures"] if g["t"] < 3] == [k["gestures"][0]["k"], "hop"]
    assert k["gestures"][0]["k"] in ("lean_l", "lean_r")
    # the props end above the star's head
    assert mascot.scale(sp.scenes[0], DUO) == s and mascot.scale(sp.scenes[1], DUO) == 1.0


def test_gestures_keep_a_gap_and_listeners_nod_along():
    sp = Spec.model_validate({"slug": "t", "style": "example", "scenes": [
        {"id": "s1", "template": "explain", "narration": "satu dua. tiga empat. lima",
         "emphasis": ["empat"], "mascot": {"speaker": "bulat"}, "visual": stage({"at": "satu", "kind": "label", "text": "x"})}]})
    ws = words(("satu", 0), ("dua.", 300), ("tiga", 600), ("empat.", 1800), ("lima", 3000))
    b, k = mascot.plan(sp, [{"id": "s1", "start": 0.0, "end": 4.0}], ws, DUO, 1290)
    ts = [g["t"] for g in b["gestures"]]
    assert ts == sorted(ts) and all(y - x >= DUO["mascot"]["lively"]["gap_s"] for x, y in zip(ts, ts[1:]))
    assert any(g["k"] == "nod" for g in b["gestures"])          # emphasised, not spotlit
    assert k["gestures"] and all(g["k"] == "nod" for g in k["gestures"])


def test_lint_focus_name_and_crowded_strip():
    base = {"id": "s1", "template": "hook", "narration": "aku bulat sekali",
            "visual": stage({"at": "aku", "kind": "label", "text": "a"}, {"at": "bulat", "kind": "label", "text": "b"},
                            {"at": "sekali", "kind": "label", "text": "c"})}
    issues = lint(spec({**base, "mascot": {"focus": "napa"}}))
    errs = [str(i) for i in issues if i.level == "error"]
    warns = [str(i) for i in issues if i.level != "error"]
    assert any("focus: 'napa'" in e for e in errs) and any("strip above the star" in w for w in warns)


def test_lint_warns_when_too_many_mascots_show(monkeypatch):
    m = STYLE["mascot"]
    trio = {**STYLE, "mascot": {**m, "crowd": 2, "cast": [{**m["cast"][0], "name": n} for n in ("a", "b", "c")]}}
    monkeypatch.setattr(config, "style", lambda name: trio)
    scene = {"id": "s1", "template": "hook", "narration": "bandar selalu menang",
             "visual": stage({"at": "bandar", "kind": "label", "text": "Bandar"})}
    crowded = lambda sp: [str(i) for i in lint(sp) if "mascots on stage" in str(i)]   # noqa: E731
    assert crowded(spec(scene)) and "3 mascots" in crowded(spec(scene))[0]
    assert not crowded(Spec.model_validate({**spec(scene).model_dump(), "mascots": ["a", "c"]}))
