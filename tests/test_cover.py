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
    assert 'class="hero-mascot' in html        # the example pack's mascot is the subject
    assert (out / "brand" / "wordmark.svg").exists() and (out / "gsap.min.js").exists()


def test_hero_layout_stays_in_profile_grid_crop():
    for name in ("default", "example"):
        cv = config.style(name)["cover"]
        hv = cv["hero"]
        assert 240 <= hv["pill_top"] < hv["text_top"] < hv["zone"][0] < hv["zone"][1]
        assert hv["zone"][1] < hv["footer_y"] - cv["logo_size"] / 2
        assert hv["footer_y"] + max(cv["logo_size"], cv["wordmark_height"]) / 2 <= 1680


def test_hero_with_photo_and_mascot():
    style = config.style("example")
    cast = cover.hero_mascot(_spec(style="example"), style, style["cover"]["hero"])
    assert cast and cast["pose"] in mascot_poses(style, cast["who"]) and "<svg" in cast["svg"]
    photo = {"w": 600, "h": 800, "kind": "cutout", "src": "hero.png"}
    ctx = cover.cover_context(_spec(style="example", cover=Cover(title="Kenapa Kita", keyword="Menguap?",
                                                                 badge="MITOS?")),
                              style, has_media=False, photo=photo, cast=cast)
    h, hv = ctx["hero"], style["cover"]["hero"]
    z0, z1 = h["zone"]
    for box in (h["photo"], h["mascot"]):
        assert 0 <= box["x"] and box["x"] + box["w"] <= 1080
        assert z0 - 1 <= box["y"] and box["y"] + box["h"] <= z1 + 1
    assert ctx["badge"] == "MITOS?" and h["arrow"]["ok"]
    # the subject never starts above the title block
    assert z0 >= hv["text_top"] + 2 * ctx["title_size"] * 0.9


def test_layout_text_or_no_subject_keeps_the_title_layout():
    style = config.style("default")
    assert cover.cover_context(_spec(), style, has_media=False)["hero"] is None
    photo = {"w": 600, "h": 800, "kind": "cutout", "src": "hero.png"}
    ctx = cover.cover_context(_spec(cover=Cover(title="A b", keyword="C", layout="text")), style,
                              has_media=True, photo=photo)
    assert ctx["hero"] is None and ctx["badge"] is None


def test_mascot_none_and_unknown_pose():
    style = config.style("example")
    hv = style["cover"]["hero"]
    assert cover.hero_mascot(_spec(style="example", cover=Cover(title="A", mascot="none")), style, hv) is None
    m = cover.hero_mascot(_spec(style="example", cover=Cover(title="A", mascot="no-such-pose")), style, hv)
    assert m["pose"] == "netral"
    assert cover.hero_mascot(_spec(), config.style("default"), hv) is None      # no cast


def test_boxy_lift_is_rejected(tmp_path):
    from PIL import Image, ImageDraw
    slab = Image.new("RGBA", (400, 500), (0, 0, 0, 0))
    ImageDraw.Draw(slab).rectangle((0, 0, 399, 499), fill=(200, 100, 50, 255))
    ImageDraw.Draw(slab).polygon([(0, 0), (120, 0), (0, 160)], fill=(0, 0, 0, 0))   # a nibbled corner
    blob = Image.new("RGBA", (400, 500), (0, 0, 0, 0))
    ImageDraw.Draw(blob).ellipse((0, 0, 399, 499), fill=(200, 100, 50, 255))
    slab.save(tmp_path / "slab.png")
    blob.save(tmp_path / "blob.png")
    assert cover.boxy(tmp_path / "slab.png", 0.85, 0.55)
    assert not cover.boxy(tmp_path / "blob.png", 0.85, 0.55)
    still = tmp_path / "still.jpg"
    Image.new("RGB", (1080, 1920), (10, 20, 30)).save(still)
    with Image.open(cover.card_crop(still, 0.8)) as im:
        assert abs(im.width / im.height - 0.8) < 0.01


def mascot_poses(style, who):
    from klip import mascot
    return mascot.poses(style, who)
