"""Progress bar, watermark, series pill and brand end card."""

from klip import config
from klip.paths import ROOT
from klip.spec import load_spec
from klip.stages import compose, voice
from tests.test_pipeline import FakeTTS, needs_ffmpeg, needs_renderer, project  # noqa: F401

SCENES = [{"idx": 0, "template": "hook", "start": 0.06}, {"idx": 1, "template": "explain", "start": 3.0},
          {"idx": 2, "template": "explain", "start": 7.5}, {"idx": 3, "template": "cta", "start": 12.0}]


def _spec(**kw):
    spec = load_spec(ROOT / "examples" / "menguap.json")
    return spec.model_copy(update=kw)


def test_progress_bar_default_off_and_spec_can_turn_it_on():
    style = config.style("default")
    assert compose.branding(_spec(), style, SCENES, 14.0)["progress"] is None
    b = compose.branding(_spec(progress_bar=True), style, SCENES, 14.0)
    assert b["progress"]["width"] == 900 and len(b["progress"]["ticks"]) == 3
    assert b["progress"]["ticks"][0] == round(900 * 3.0 / 14.0, 1)
    assert compose.branding(_spec(progress_bar=False), style, SCENES, 14.0)["progress"] is None
    assert b["watermark"] is None and b["series"] is None and b["end_card"] is None


def test_brand_pack_branding():
    style = config.style("example")
    b = compose.branding(_spec(style="example", series="why", episode=12, progress_bar=True), style, SCENES, 14.0)
    # bar stops short of the watermark logo at the right of the strip
    assert b["progress"]["left"] + b["progress"]["width"] < 1080 - style["watermark"]["right"] - style["watermark"]["size"]
    # watermark hidden on the cta scene; pill on the hook only, from frame 0
    assert b["watermark"]["spans"] == [{"start": 0.0, "end": 12.0, "k": 0, "dur": 12.0}]
    assert b["series"]["label"] == "WHY? #12"
    assert b["series"]["spans"] == [{"start": 0.0, "end": 3.0, "k": 0, "dur": 3.0}]
    assert b["end_card"]["logo"]["src"] == "brand/logo.svg"


def test_unknown_series_shows_key_in_capitals():
    b = compose.branding(_spec(series="fakta-harian"), config.style("default"), SCENES, 14.0)
    assert b["series"]["label"] == "FAKTA HARIAN"


def test_rgba():
    assert compose.rgba("#12213B", 0.6) == "rgba(18,33,59,0.6)"
    assert compose.rgba("#fff", 0) == "rgba(255,255,255,0)"


@needs_ffmpeg
@needs_renderer
def test_compose_renders_brand_layer(project):  # noqa: F811
    spec = _spec(style="example", series="myth-fact", progress_bar=True)
    project.mkdir()
    voice.run(spec, project, engine=FakeTTS())
    compose.run(spec, project)
    out = project / "composition"
    html = (out / "index.html").read_text()
    assert 'id="progress" class="progress clip"' in html and 'tl.fromTo("#progress .fill"' in html
    assert 'id="pill-0" class="pill clip" data-start="0.0"' in html and "MYTH / FACT" in html
    assert 'class="wm clip"' in html and (out / "brand" / "watermark.svg").exists()
    assert 'class="ec-word"' in html and (out / "brand" / "wordmark.svg").exists()
    assert "#38BDF8" in html and "rgba(15,23,42," in html


def test_hook_punch_keeps_headline_on_canvas():
    # the 900 px headline block, scaled at frame 0, must fit the 1080 px canvas
    for name in config.styles():
        assert 900 * config.style(name)["headline"]["hook_punch"] <= 1080, name
