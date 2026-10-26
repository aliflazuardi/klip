"""Quizzes ("tebak dulu"): a hook/explain scene's options, countdown and reveal, on every kind of visual."""

import pytest
from pydantic import ValidationError

from klip.lint import lint
from klip.spec import Scene, Spec
from klip.stages import compose
from tests.test_stage import _timeline, needs_renderer, stage, words

Q = {"options": ["Hiu", "Ular", "Nyamuk"], "answer": 3}


def _spec(*scenes, **kw):
    return Spec.model_validate({"slug": "t", "voice": "female", "target_duration_s": 30, "scenes": list(scenes),
                                "post": {"caption": "x", "hashtags": ["#x"]}, **kw})


def _scene(sid="s1", template="hook", narration="tebak dulu hiu ular atau nyamuk tiga dua satu", quiz=None, **kw):
    return {"id": sid, "template": template, "narration": narration, "on_screen_text": "Hewan paling mematikan?",
            "quiz": quiz or {**Q, "countdown_at": "tiga"}, **kw}


def test_quiz_fields():
    with pytest.raises(ValidationError, match="only 3 options"):
        Scene.model_validate(_scene(quiz={**Q, "answer": 4}))
    with pytest.raises(ValidationError, match="at least 2"):
        Scene.model_validate(_scene(quiz={"options": ["Hiu"], "answer": 1}))
    with pytest.raises(ValidationError, match="'hook' or 'explain'"):
        Scene.model_validate({**_scene(template="stat"), "stat": {"value": 3}})


def test_quiz_context_times_options_ring_and_reveal():
    sc = Scene.model_validate(_scene(narration="tebak hiu ular atau nyamuk tiga dua satu jawabannya nyamuk",
                                     quiz={**Q, "countdown_at": "tiga", "reveal_at": "jawabannya"}))
    ws = words(("tebak", 100), ("hiu", 600), ("ular", 1000), ("atau", 1300), ("nyamuk", 1600), ("tiga", 2200),
               ("dua", 2700), ("satu", 3200), ("jawabannya", 3800), ("nyamuk", 4400))
    q = compose._quiz_ctx(sc, {"start_ms": 0, "duration_ms": 5000}, ws, {"accent_color": "#FFD43B",
                          "fact_color": "#22C55E", "myth_color": "#F43F5E"}, (560, 1400))
    assert [o["t"] for o in q["options"]] == [0.6, 1.0, 1.6]                 # on their words
    assert [o["right"] for o in q["options"]] == [False, False, True]
    assert q["ring"] == {"t": 2.2, "dur": 1.6} and q["reveal"] == 3.8       # the ring stops at the reveal
    assert q["right"] == "#22C55E" and q["letter"] == "#FFD43B"
    asked = Scene.model_validate(_scene(narration="tebak dulu siapa", quiz=Q))
    q2 = compose._quiz_ctx(asked, {"start_ms": 0, "duration_ms": 3000}, words(("tebak", 100), ("dulu", 500), ("siapa", 900)),
                           {"accent_color": "#000000", "fact_color": "#000000", "myth_color": "#000000"}, (560, 1400))
    assert q2["ring"] is None and q2["reveal"] is None
    assert [o["t"] for o in q2["options"]] == [0.35, 0.57, 0.79]             # not said: staggered


def test_lint_quiz_cues_answer_and_loop():
    narr = "tebak dulu hiu ular atau nyamuk tiga dua satu"
    msgs = [i.message for i in lint(_spec(_scene(quiz={**Q, "countdown_at": "empat"})))]
    assert any("countdown_at 'empat' is not a word" in m for m in msgs)
    assert any("never answered" in m for m in msgs)
    msgs = [i.message for i in lint(_spec(_scene(narration=narr + " jawabannya nyamuk",
                                                 quiz={**Q, "countdown_at": "tiga", "reveal_at": "jawabannya"})))]
    assert any("answered in the hook" in m for m in msgs)
    later = _scene("s3", "explain", "jawabannya nyamuk", quiz={**Q, "reveal_at": "jawabannya"})
    msgs = [i.message for i in lint(_spec(_scene(narration=narr), _scene("s2", "explain", "lalu apa lagi", quiz=None) | {"quiz": None}, later))]
    assert not any("never answered" in m or "answered in the hook" in m for m in msgs)
    assert not any("hook narration has" in m for m in msgs)                  # options + countdown don't count
    long = _scene(narration=narr, quiz={"options": ["Hiu yang sangat besar sekali", "Ular"], "answer": 1})
    assert any("keep options ≤ 4" in i.message for i in lint(_spec(long)))
    bad = _scene(narration="tebak jawabannya hiu tiga", quiz={**Q, "countdown_at": "tiga", "reveal_at": "jawabannya"})
    assert any("reveal_at comes before countdown_at" in i.message for i in lint(_spec(bad)))


def test_lint_quiz_on_chat_set():
    sc = _scene(narration="tebak dulu hiu ular atau nyamuk tiga dua satu",
                visual=stage({"at": "hiu", "kind": "bubble", "text": "hiu kali"}, backdrop={"kind": "chat", "title": "Grup"}))
    assert any("covers the bubbles" in i.message for i in lint(_spec(sc)))


@needs_renderer
@pytest.mark.parametrize("visual", [{"type": "solid"}, {"type": "stock_video", "query": "shark", "name": "fish"},
                                    stage({"at": "tebak", "kind": "label", "text": "?"})])
def test_compose_renders_the_quiz_on_cards_and_stages(visual):
    spec = _spec(_scene(narration="tebak hiu ular atau nyamuk tiga dua satu jawabannya nyamuk",
                        quiz={**Q, "countdown_at": "tiga", "reveal_at": "jawabannya"}, visual=visual))
    ws = words(("tebak", 100), ("hiu", 600), ("ular", 1000), ("atau", 1300), ("nyamuk", 1600), ("tiga", 2200),
               ("dua", 2700), ("satu", 3200), ("jawabannya", 3800), ("nyamuk", 4400))
    media = {"kind": "video", "file": "media/s1.mp4"} if visual["type"] == "stock_video" else {"kind": None, "stage": []}
    ctx, _ = compose.build_context(spec, _timeline(("s1", 5000)), ws, {"scenes": {"s1": media}})
    s = ctx["scenes"][0]
    assert s["quiz"] and s["quiz"]["reveal"] == 3.8
    if s["stage"]:                                                           # the props keep the top of the area
        assert s["stage"]["quiz_box"][0] > s["stage"]["area"][1]
    from jinja2 import Environment, FileSystemLoader, StrictUndefined
    from klip.paths import TEMPLATES_DIR
    env = Environment(loader=FileSystemLoader(TEMPLATES_DIR / "default"), undefined=StrictUndefined,
                      autoescape=True, trim_blocks=True, lstrip_blocks=True)
    env.filters["rgba"] = compose.rgba
    html = env.get_template("index.html.j2").render(**ctx)
    assert html.count('class="qz"') == 1 and html.count('class="qz-opt"') == 2 and html.count('class="qz-opt right"') == 1
    assert "qz-ring" in html and ".qz-opts > .qz-opt:nth-child(3)" in html
    moments = [e["moment"] for e in compose.sfx_events(ctx["scenes"], [])]
    assert moments.count("quiz_option") == 3 and "quiz_countdown" in moments and "quiz_reveal" in moments
