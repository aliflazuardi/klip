"""Designed cover."""

import pytest
from pydantic import ValidationError

from klip import config
from klip.paths import ROOT
from klip.spec import Cover, load_spec
from klip.stages import cover
from tests.test_pipeline import needs_renderer


def _spec(**kw):
    return load_spec(ROOT / "examples" / "menguap.json").model_copy(update=kw)


def test_split_title_uses_emphasised_end_as_keyword():
    assert cover.split_title("Madu awet ribuan tahun?", ["ribuan tahun"]) == ("Madu awet", "ribuan tahun?")
    assert cover.split_title("Kenapa kita menguap?", []) == ("Kenapa kita", "menguap?")
    # emphasis that isn't at the end doesn't count
    assert cover.split_title("Madu awet ribuan tahun?", ["Madu"]) == ("Madu awet ribuan", "tahun?")
    assert cover.split_title("Menguap?", []) == ("", "Menguap?")


def test_cover_spec_forms():
    Cover(lines=["Kenapa Kita", "Ikut Ikutan", "Menguap?"])
    Cover(title="Kenapa Kita Ikut Ikutan", keyword="Menguap?", subtitle="Ternyata bukan karena bosan")
    with pytest.raises(ValidationError):
        Cover(lines=["a", "b"], keyword="c")
    with pytest.raises(ValidationError):
        Cover(lines=["only one"])


def test_title_falls_back_to_hook_on_screen_text():
    spec = _spec()
    hook = spec.scenes[0]
    parts = cover.title_parts(spec)
    assert f"{parts['title']} {parts['keyword']}".strip() == (hook.on_screen_text or hook.narration)
    assert parts["lead"] is None and parts["subtitle"] is None


def test_explicit_lines_and_title_keyword():
    p = cover.title_parts(_spec(cover=Cover(lines=["Kenapa Kita", "Ikut Ikutan", "Menguap?"], subtitle="S")))
    assert p["lead"] == ["Kenapa Kita", "Ikut Ikutan"] and p["keyword"] == "Menguap?" and p["subtitle"] == "S"
    p = cover.title_parts(_spec(cover=Cover(title="Kenapa Kita Ikut Ikutan", keyword="Menguap?")))
    assert p["title"] == "Kenapa Kita Ikut Ikutan" and p["keyword"] == "Menguap?"
    # title alone: its last word becomes the keyword
    assert cover.title_parts(_spec(cover=Cover(title="Kenapa kita menguap?")))["keyword"] == "menguap?"


def test_reference_cover_fits_at_full_size():
    # the brand book's example sets 130 px title lines and a 170 px keyword
    cv = config.style("example")["cover"]
    ctx = cover.cover_context(_spec(style="example", series="why", cover=Cover(
        title="Kenapa Kita Ikut Ikutan", keyword="Menguap?", subtitle="Ternyata bukan karena bosan")),
        config.style("example"), has_media=False)
    assert ctx["title_size"] == cv["title_size"] and ctx["keyword_size"] == cv["keyword_size"]
    assert ctx["keyword"] == "MENGUAP?"


def test_long_text_shrinks_but_not_below_minimum():
    style = config.style("example")
    cv = style["cover"]
    ctx = cover.cover_context(_spec(cover=Cover(title="Ternyata ini alasan sebenarnya kenapa kita sering sekali "
                                                      "menguap waktu rapat", keyword="Pembuluh darah")),
                              style, has_media=True)
    assert cv["title_min_size"] <= ctx["title_size"] < cv["title_size"]
    assert cv["keyword_min_size"] <= ctx["keyword_size"] < cv["keyword_size"]
    assert cover.wrap_count(ctx["keyword"], ctx["keyword_size"], cv["width"], cv["caps_em"]) == 1


def test_brand_parts_come_from_the_style():
    wn = cover.cover_context(_spec(style="example", series="myth-fact", episode=3),
                             config.style("example"), has_media=True)
    assert wn["pill"]["label"] == "MYTH / FACT #3" and wn["pill"]["bg"] == "#38BDF8"
    assert wn["logo"]["src"] == "brand/logo.svg" and wn["wordmark"]["src"] == "brand/wordmark.svg"
    assert wn["disc"] == "#1E293B" and wn["handle"] is None
    plain = cover.cover_context(_spec(), config.style("default"), has_media=False)
    assert plain["pill"] is None and plain["logo"] is None and plain["wordmark"] is None
    assert (plain["c1"], plain["c2"]) == tuple(config.style("default")["palette"][0])


def test_layout_stays_in_profile_grid_crop():
    # profile grids crop 9:16 covers to the centre 3:4: y 240-1680
    for name in ("default", "example"):
        cv = config.style(name)["cover"]
        assert 240 <= cv["pill_top"] and cv["text_top"] > cv["pill_top"]
        assert cv["text_bottom"] < cv["footer_y"] - cv["logo_size"] / 2
        assert cv["footer_y"] + max(cv["logo_size"], cv["wordmark_height"]) / 2 <= 1680
        assert cv["width"] <= 1080


@needs_renderer
def test_build_writes_cover_composition(tmp_path):
    spec = _spec(style="example", series="why", cover=Cover(title="Kenapa Kita Ikut Ikutan",
                                                                   keyword="Menguap?", subtitle="Bukan karena bosan"))
    out = cover.build(spec, tmp_path, assets=None)
    html = (out / "index.html").read_text()
    assert "MENGUAP?" in html and "WHY?" in html and "Bukan karena bosan" in html
    assert 'src="bg.jpg"' not in html          # no media -> palette gradient
    assert (out / "brand" / "wordmark.svg").exists() and (out / "gsap.min.js").exists()
