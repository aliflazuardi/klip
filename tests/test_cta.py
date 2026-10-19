"""CTA types (action chip, comment question) and the mid-video save nudge."""

import pytest
from pydantic import ValidationError

from klip import config
from klip.lint import lint
from klip.paths import ROOT
from klip.spec import Scene, load_spec
from klip.stages import compose, voice
from tests.test_pipeline import FakeTTS, needs_ffmpeg, needs_renderer, project  # noqa: F401


def _list_spec(cta_type="comment", **kw):
    """menguap.json with scenes 3-5 as a list and a typed cta."""
    spec = load_spec(ROOT / "examples" / "menguap.json")
    scenes = [s.model_copy(update={"template": "list_item"}) if s.id in ("s3", "s4", "s5") else s
              for s in spec.scenes]
    scenes[-1] = scenes[-1].model_copy(update={"cta_type": cta_type,
                                               "on_screen_text": "Kamu gampang ketularan menguap?"})
    return spec.model_copy(update={"scenes": scenes, **kw})


def _ctx(templates, starts, dur=4.0):
    return [{"idx": i, "template": t, "start": st, "end": st + dur, "dur": dur, "icon": None, "t": {}}
            for i, (t, st) in enumerate(zip(templates, starts))]


def test_cta_type_only_on_cta_scenes():
    with pytest.raises(ValidationError, match="cta_type"):
        Scene(id="a", template="explain", narration="x", cta_type="save")
    assert Scene(id="a", template="cta", narration="x", cta_type="share").cta_type == "share"


def test_cta_ctx_chip_per_type():
    style = config.style("example")
    for ty in ("follow", "save", "comment", "share"):
        c = compose._cta_ctx(Scene(id="c", template="cta", narration="x", cta_type=ty), style)
        assert c["chip"]["label"] == style["cta"]["types"][ty]["label"] and c["chip"]["icon"].startswith("<svg")
        assert c["question"] is (ty == "comment")
    assert compose._cta_ctx(Scene(id="c", template="cta", narration="x"), style)["chip"] is None


def test_save_nudge_on_second_list_item():
    style = config.style("default")
    sn = style["save_nudge"]
    scenes = _ctx(["hook", "list_item", "list_item", "list_item", "cta"], [0, 3, 7, 11, 15])
    n = compose.save_nudge(_list_spec(), style, scenes)
    assert n["start"] == round(7 + sn["delay_s"], 3) and n["dur"] == sn["duration_s"]
    assert n["text"] == sn["text"] and n["icon"].startswith("<svg")
    # spec switch wins over the style
    assert compose.save_nudge(_list_spec(save_nudge=False), style, scenes) is None
    off = {**style, "save_nudge": {**sn, "enabled": False}}
    assert compose.save_nudge(_list_spec(), off, scenes) is None
    assert compose.save_nudge(_list_spec(save_nudge=True), off, scenes)["start"] == n["start"]


def test_save_nudge_needs_a_second_item_in_the_first_run():
    style = config.style("default")
    spec = _list_spec()
    assert compose.save_nudge(spec, style, _ctx(["hook", "explain", "cta"], [0, 3, 7])) is None
    # first run has one item; a later run doesn't count
    assert compose.save_nudge(spec, style, _ctx(["hook", "list_item", "explain", "list_item", "list_item"],
                                                [0, 3, 7, 11, 15])) is None
    # item too short for the pill
    assert compose.save_nudge(spec, style, _ctx(["list_item", "list_item"], [0, 3], dur=1.2)) is None
    # long enough, but shortened to end before the item does
    n = compose.save_nudge(spec, style, _ctx(["list_item", "list_item"], [0, 3], dur=2.5))
    assert n["dur"] == round(3 + 2.5 - 0.1 - n["start"], 3)


def test_sfx_cues_for_chip_and_nudge():
    scenes = _ctx(["hook", "list_item", "cta"], [0, 3, 7])
    scenes[2]["t"] = {"chip": {"label": "Simpan"}, "chip_at": 0.5}
    ev = {(e["moment"], e["t"]) for e in compose.sfx_events(scenes, [], end_card=True, nudge={"start": 3.6})}
    assert ("cta_ask", 7.5) in ev and ("save_nudge", 3.6) in ev and ("cta_icon", 7.0) in ev
    plain = compose.sfx_events(_ctx(["hook", "cta"], [0, 3]), [])
    assert not any(e["moment"] in ("cta_ask", "save_nudge") for e in plain)


def test_lint_comment_cta_wants_a_question():
    spec = _list_spec()
    assert not any("two-sided question" in i.message for i in lint(spec))
    bad = spec.model_copy(update={"scenes": [*spec.scenes[:-1], spec.scenes[-1].model_copy(
        update={"on_screen_text": "Sampai jumpa lagi."})]})
    assert any("two-sided question" in i.message for i in lint(bad))


@needs_ffmpeg
@needs_renderer
@pytest.mark.parametrize("style", ["example", "default"])
def test_compose_renders_chip_question_and_nudge(project, style):  # noqa: F811
    spec = _list_spec(style=style, series="cara-kerja")
    project.mkdir()
    voice.run(spec, project, engine=FakeTTS())
    compose.run(spec, project)
    html = (project / "composition" / "index.html").read_text()
    assert 'class="cta-chip"' in html and "Komen di bawah" in html and 'class="cta-stack"' in html
    assert 'id="nudge" class="nudge clip"' in html and "Simpan dulu biar nggak lupa" in html
    assert 'tl.fromTo("#sc-s6 .cta-chip"' in html
    if style == "example":
        disc = config.style(style)["cta"]["compact_disc"]
        assert f"width: {disc}px; height: {disc}px;" in html      # question → compact logo block
        assert 'class="ec-tag"' not in html                      # chip takes the tagline's place


@needs_ffmpeg
@needs_renderer
def test_untyped_cta_keeps_the_old_layout(project):  # noqa: F811
    spec = load_spec(ROOT / "examples" / "menguap.json").model_copy(update={"style": "example"})
    project.mkdir()
    voice.run(spec, project, engine=FakeTTS())
    compose.run(spec, project)
    html = (project / "composition" / "index.html").read_text()
    assert 'class="ec-tag"' in html and 'class="cta-chip"' not in html and 'id="nudge"' not in html
