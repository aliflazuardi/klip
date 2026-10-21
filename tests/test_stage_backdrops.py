"""Stage backdrops (themed sets: photo, screenshot, board, phone) and notif cards."""

import json

import pytest
from PIL import Image
from pydantic import ValidationError

from klip import brief
from klip import stage as stage_mod
from klip.lint import lint
from klip.spec import Scene, Spec, Visual
from klip.stages import assets, compose
from tests.test_media import FakeProvider
from tests.test_stage import _photo, _timeline, needs_renderer, stage, words


def _spec(*scenes, **kw):
    return Spec(slug="t", voice="female", target_duration_s=30, scenes=list(scenes),
                post={"caption": "x", "hashtags": ["#x"]}, **kw)


def test_backdrop_kinds_need_their_fields():
    with pytest.raises(ValidationError, match="requires query or who or path"):
        Visual(type="stage", elements=[{"at": "a", "kind": "label", "text": "x"}], backdrop={"kind": "photo"})
    with pytest.raises(ValidationError, match="at least 4 items"):
        Visual(type="stage", elements=[{"at": "a", "kind": "label", "text": "x"}],
               backdrop={"kind": "board", "items": ["BBCA"]})
    with pytest.raises(ValidationError, match="not both"):
        Visual(type="stage", elements=[{"at": "a", "kind": "label", "text": "x"}], background="grid",
               backdrop={"kind": "phone"})
    with pytest.raises(ValidationError, match="only for visual.type='stage'"):
        Visual(type="icon", name="x", backdrop={"kind": "phone"})
    with pytest.raises(ValidationError, match="#RRGGBB"):
        Visual(type="stage", elements=[{"at": "a", "kind": "label", "text": "x"}],
               backdrop={"kind": "phone", "tint": "red"})
    with pytest.raises(ValidationError, match="requires text"):
        Visual(type="stage", elements=[{"at": "a", "kind": "notif"}])


def test_backdrop_key_tone_and_settings():
    a = Visual(type="stage", elements=[{"at": "a", "kind": "label", "text": "x"}],
               backdrop={"kind": "photo", "query": "market", "dim": 0.5})
    b = a.model_copy(deep=True)
    assert stage_mod.background_key(a) == stage_mod.background_key(b) and stage_mod.background_key(a).startswith("bd-")
    s = stage_mod.backdrop_settings(a)
    assert s["dim"] == 0.5 and s["title"] == "box" and stage_mod.tone("x", a) == "dark"


def test_board_rows_colour_by_sign_and_stagger():
    rows = stage_mod.board_rows(["BBCA +1,2%", "GOTO -3%", "TLKM", "ASII −0,5%"], 3, 2)
    assert [c["tone"] for c in rows[0]] == ["up", "down", "neutral"]
    assert [c["text"] for c in rows[1]] != [c["text"] for c in rows[0]]   # rows are staggered


def test_notifs_stack_down_the_screen():
    els = Visual(type="stage", elements=[{"at": "a", "kind": "notif", "text": "x"},
                                         {"at": "b", "kind": "notif", "text": "y", "stat": "Rp1"}]).elements
    places = stage_mod.assign_places(els, [0, 1])
    assert places[0][0] == places[1][0] == 0.5 and places[0][1] < places[1][1]
    boxes = stage_mod.layout("s1", els, {}, (500, 1400))
    assert boxes[0]["y"] < boxes[1]["y"] and boxes[0]["w"] > 700


def test_fetch_backdrop_photo_and_own_file(tmp_path, monkeypatch):
    s = Scene(id="s1", template="explain", narration="di pasar",
              visual=stage({"at": "pasar", "kind": "label", "text": "x"},
                           backdrop={"kind": "photo", "query": "market stalls"}))
    used, warn = set(), []
    row = assets.fetch_backdrop(s, used, [FakeProvider("p", [_photo("m1", ["market", "stalls"])])], warn)
    assert row["origin"] == "stock" and row["credit"]["id"] == "m1" and not warn
    own = tmp_path / "s1-bg.jpg"
    Image.new("RGB", (40, 60), "red").save(own)
    row = assets.fetch_backdrop(s, set(), [], [], own=own)
    assert row["origin"] == "own"
    monkeypatch.setattr(brief, "photo_dir", lambda spec: tmp_path)
    spec = _spec({"id": "s1", "template": "hook", "narration": "di pasar", "visual": s.visual.model_dump()})
    assert brief.own_backdrops(spec) == {"s1": own}


def test_fetch_records_backdrop_credit_and_brief(tmp_path):
    spec = _spec({"id": "s1", "template": "hook", "narration": "di pasar",
                  "visual": stage({"at": "pasar", "kind": "label", "text": "x"},
                                  backdrop={"kind": "photo", "query": "market stalls", "brief": "pasar pagi"})})
    res = assets.fetch(spec, tmp_path, providers=[FakeProvider("p", [_photo("m1", ["market", "stalls"])])])
    assert res["scenes"]["s1"]["backdrop"]["credit"]["id"] == "m1"
    assert [c["id"] for c in json.loads((tmp_path / "credits.json").read_text())] == ["m1"]
    rows = json.loads((tmp_path / "photo-brief.json").read_text())["items"]
    assert rows[0]["kind"] == "backdrop" and rows[0]["file"] == "s1-bg" and rows[0]["want"] == "pasar pagi"


def test_prepare_backdrop_covers_the_frame(tmp_path):
    src = tmp_path / "wide.jpg"
    Image.new("RGB", (1600, 900), "blue").save(src)
    v = Visual(type="stage", elements=[{"at": "a", "kind": "label", "text": "x"}],
               backdrop={"kind": "photo", "query": "x"})
    (tmp_path / "media").mkdir()
    out = assets.prepare_backdrop("s1", v, {"src": str(src), "credit": {"provider": "p", "id": "1"}},
                                  tmp_path / "media", tmp_path)
    with Image.open(tmp_path / out["file"]) as im:
        assert im.size == (1200, 2040)


def test_lint_suggests_more_sets_and_phone_for_notifs():
    scenes = [{"id": f"s{k}", "template": "explain", "narration": "harga naik lagi",
               "visual": stage({"at": "harga", "kind": "label", "text": "x"}, {"at": "naik", "kind": "label", "text": "y"})}
              for k in range(1, 6)]
    issues = lint(_spec(*scenes))
    assert any("one set" in i.message for i in issues)
    scenes[0]["visual"] = stage({"at": "harga", "kind": "notif", "text": "x"}, {"at": "naik", "kind": "label", "text": "y"})
    scenes[1]["visual"] = stage({"at": "harga", "kind": "label", "text": "x"}, {"at": "naik", "kind": "label", "text": "y"},
                                backdrop={"kind": "phone"})
    msgs = [i.message for i in lint(_spec(*scenes))]
    assert not any("one set" in m for m in msgs)
    assert any("phone backdrop" in m and "notif" in m for m in msgs)
    assert any("notif cards sit best" in m for m in msgs)


@needs_renderer
def test_compose_renders_each_backdrop_kind(tmp_path):
    spec = _spec(
        {"id": "s1", "template": "hook", "narration": "harga naik", "on_screen_text": "Harga naik?", "emphasis": ["naik"],
         "visual": stage({"at": "harga", "kind": "label", "text": "x"},
                         backdrop={"kind": "photo", "query": "market", "tint": "#7A0F14"})},
        {"id": "s2", "template": "explain", "narration": "saham turun",
         "visual": stage({"at": "saham", "kind": "label", "text": "x"},
                         backdrop={"kind": "board", "title": "IDX", "items": ["BBCA -2%", "GOTO +4%", "TLKM", "ASII"]})},
        {"id": "s3", "template": "explain", "narration": "notif masuk",
         "visual": stage({"at": "notif", "kind": "notif", "outlet": "m-banking", "text": "Cicilan", "stat": "Rp4,5 jt"},
                         backdrop={"kind": "phone", "title": "autodebet"})},
        {"id": "s4", "template": "explain", "narration": "halaman lama",
         "visual": stage({"at": "halaman", "kind": "label", "text": "x"},
                         backdrop={"kind": "screenshot", "url": "https://example.com"})})
    ws = words(("harga", 100), ("naik", 600)) + words(("saham", 2100), ("turun", 2600), scene="s2") + \
        words(("notif", 4100), ("masuk", 4600), scene="s3") + words(("halaman", 6100), ("lama", 6600), scene="s4")
    media = {"s1": {"kind": None, "stage": [], "backdrop": {"file": "media/s1_backdrop.jpg", "source": "p:1"}},
             "s2": {"kind": None, "stage": []}, "s3": {"kind": None, "stage": []}, "s4": {"kind": None, "stage": []}}
    ctx, warnings = compose.build_context(spec, _timeline(("s1", 2000), ("s2", 2000), ("s3", 2000), ("s4", 2000)),
                                          ws, {"scenes": media})
    st = [s["stage"] for s in ctx["scenes"]]
    assert st[0]["image"]["src"] == "media/s1_backdrop.jpg" and st[0]["title_style"] == "box"
    assert st[1]["backdrop"]["rows"] and st[2]["title_style"] == "plain" and st[2]["tone"] == "dark"
    assert st[3]["bg"] == "grid" and any("no screenshot for the backdrop" in w for w in warnings)   # its page is missing
    assert not st[1]["continues"]                                   # a new set: a real cut

    from jinja2 import Environment, FileSystemLoader, StrictUndefined
    from klip.paths import TEMPLATES_DIR
    env = Environment(loader=FileSystemLoader(TEMPLATES_DIR / "default"), undefined=StrictUndefined,
                      autoescape=True, trim_blocks=True, lstrip_blocks=True)
    env.filters["rgba"] = compose.rgba
    html = env.get_template("index.html.j2").render(**ctx)
    assert 'class="st-title box"' in html and 'class="bx"' in html and "bd-tint" in html
    assert 'class="bd-cell down"' in html and 'class="bd-cell up"' in html and ">IDX<" in html
    assert 'class="nf-card"' in html and "Rp4,5 jt" in html and "bd-status" in html
    assert "y: -220" in html                                        # the notif slides down
