"""Chat backdrops and bubbles: a group chat that fills up message by message."""

import pytest
from pydantic import ValidationError

from klip import stage as stage_mod
from klip.lint import lint
from klip.spec import Spec, Visual
from klip.stages import compose
from tests.test_stage import _timeline, needs_renderer, stage, words

CHAT = {"kind": "chat", "title": "Keluarga Besar", "info": "23 anggota"}


def _spec(*scenes):
    return Spec(slug="t", voice="female", target_duration_s=30, scenes=list(scenes),
                post={"caption": "x", "hashtags": ["#x"]})


def _bubble(at, text="halo semua", **kw):
    return {"at": at, "kind": "bubble", "text": text, **kw}


def test_bubble_and_chat_fields():
    with pytest.raises(ValidationError, match="requires text"):
        Visual(**stage({"at": "a", "kind": "bubble"}))
    with pytest.raises(ValidationError, match="are for bubble elements"):
        Visual(**stage({"at": "a", "kind": "label", "text": "x", "sender": "Om"}))
    with pytest.raises(ValidationError, match="no `sender`"):
        Visual(**stage(_bubble("a", me=True, sender="Om")))
    with pytest.raises(ValidationError, match="requires title"):
        Visual(**stage(_bubble("a"), backdrop={"kind": "chat"}))
    with pytest.raises(ValidationError, match="`info` is for chat"):
        Visual(**stage(_bubble("a"), backdrop={"kind": "phone", "info": "online"}))
    Visual(**stage(_bubble("a", sender="Om", forwarded=True, date="07.02"), _bubble("b", me=True), backdrop=CHAT))


def test_bubbles_stack_down_theirs_left_mine_right():
    els = Visual(**stage(_bubble("a", sender="Om Hendra"), _bubble("b", "oke", me=True),
                         {"at": "c", "kind": "stamp", "text": "HOAKS", "target": 1}, backdrop=CHAT)).elements
    assert stage_mod.is_chat_page(els, [0, 1, 2])
    boxes = stage_mod.layout("s1", els, {}, (450, 1300))
    a, b, st = boxes[0], boxes[1], boxes[2]
    assert a["y"] - a["h"] / 2 == pytest.approx(450, abs=0.2)                  # from the top of the area
    assert b["y"] - b["h"] / 2 > a["y"] + a["h"] / 2                          # below it, a gap apart
    assert a["x"] - a["w"] / 2 == pytest.approx(60, abs=0.2)                  # theirs on the left
    assert b["x"] + b["w"] / 2 == pytest.approx(960, abs=0.2)                 # mine on the right
    assert b["w"] < a["w"] and a["rot"] == b["rot"] == 0
    assert a["y"] < st["y"] <= a["y"] + a["h"] / 2 + st["h"] / 2              # the stamp on its bubble's lower edge


def test_bubble_size_grows_with_text_name_and_forward():
    short = stage_mod.bubble_size(Visual(**stage(_bubble("a", "ok"))).elements[0])
    long = stage_mod.bubble_size(Visual(**stage(_bubble("a", "kata " * 30))).elements[0])
    named = stage_mod.bubble_size(Visual(**stage(_bubble("a", "ok", sender="Om", forwarded=True))).elements[0])
    assert long[0] > short[0] and long[1] > short[1] and named[1] > short[1]
    assert long[0] <= 860                                                    # stage.chat.max_w


def test_chat_scrolls_when_a_bubble_would_not_fit():
    els = [{"kind": "bubble", "y": 500, "h": 200, "start": 1.0},
           {"kind": "bubble", "y": 800, "h": 200, "start": 2.0},
           {"kind": "bubble", "y": 1100, "h": 200, "start": 3.0, "me": True}]
    keys = stage_mod.chat_scroll(els, 1000, 0.45)
    assert keys == [{"t": 3.0, "y": -200.0}]                                 # mine: no typing dots first
    els[2]["me"] = False
    assert stage_mod.chat_scroll(els, 1000, 0.45)[0]["t"] == 2.55              # theirs: with the dots
    assert stage_mod.chat_scroll(els, 2000, 0.45) == []


def test_sender_colour_is_stable():
    assert stage_mod.sender_color("Om Hendra") == stage_mod.sender_color("Om Hendra")
    assert stage_mod.sender_color(None) is None


def test_lint_chat_pairing_length_and_mixing():
    long = " ".join(["kata"] * 30)
    sc = {"id": "s1", "template": "explain", "narration": "pesan masuk lagi ke grup keluarga",
          "visual": stage(_bubble("pesan", long), {"at": "grup", "kind": "cutout", "query": "phone", "name": "phone"})}
    msgs = [i.message for i in lint(_spec(sc))]
    assert any("bubbles sit on a chat backdrop" in m for m in msgs)
    assert any("30 words" in m for m in msgs)
    assert any("breaks the chat layout" in m for m in msgs)
    sc["visual"] = stage({"at": "pesan", "kind": "label", "text": "x"}, backdrop=CHAT)
    assert any("bubble elements" in i.message for i in lint(_spec(sc)))


@needs_renderer
def test_compose_renders_a_chat(tmp_path):
    spec = _spec({"id": "s1", "template": "hook", "narration": "pesan masuk lalu dibalas lalu dicek",
                  "on_screen_text": "Pesan berantai", "visual": stage(
                      _bubble("pesan", "PENTING!! sebarkan", sender="Om Hendra", forwarded=True, date="07.02"),
                      _bubble("dibalas", "makasih infonya", sender="Tante Rina"),
                      {"at": "dicek", "kind": "stamp", "text": "HOAKS", "tone": "down", "target": 1},
                      _bubble("dicek", "sudah dicek, hoaks", me=True), backdrop=CHAT)})
    ws = words(("pesan", 100), ("masuk", 500), ("lalu", 900), ("dibalas", 1300), ("lalu", 1800), ("dicek", 2200))
    ctx, _ = compose.build_context(spec, _timeline(("s1", 3000)), ws, {"scenes": {"s1": {"kind": None, "stage": []}}})
    st = ctx["scenes"][0]["stage"]
    assert st["title_top"] == 350 and st["mask"] == st["area"][0] and st["depth"]["fg"] == []
    bubbles = [e for e in st["elements"] if e["kind"] == "bubble"]
    assert [b["enter"] for b in bubbles] == ["bubble"] * 3 and bubbles[2]["me"] and not bubbles[2]["sender"]
    assert bubbles[0]["color"] and st["camera"] == []

    from jinja2 import Environment, FileSystemLoader, StrictUndefined
    from klip.paths import TEMPLATES_DIR
    env = Environment(loader=FileSystemLoader(TEMPLATES_DIR / "default"), undefined=StrictUndefined,
                      autoescape=True, trim_blocks=True, lstrip_blocks=True)
    env.filters["rgba"] = compose.rgba
    html = env.get_template("index.html.j2").render(**ctx)
    assert 'class="bd-chat"' in html and ">Keluarga Besar<" in html and "23 anggota" in html
    assert 'class="cb them"' in html and 'class="cb me"' in html and "Diteruskan" in html
    assert html.count('class="cb-typing"') == 2 and "mask-image" in html
    assert any(e["moment"] == "stage_bubble" for e in compose.sfx_events(ctx["scenes"], []))
