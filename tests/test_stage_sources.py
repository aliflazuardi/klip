"""Real-world stage elements: charts from data, unit grids, Wikipedia people/logos, news, screenshots."""

import pytest
from pydantic import ValidationError

from klip import chartdata, http, screenshot
from klip import stage as stage_mod
from klip.engines.media import wikimedia
from klip.lint import lint
from klip.spec import Spec, StageElement, Visual
from klip.stages import assets, compose
from tests.test_stage import _timeline, needs_renderer, stage, words


# ---- spec

def test_new_kinds_need_their_fields():
    for el, msg in [({"kind": "chart"}, "points or csv or ticker"), ({"kind": "unit"}, "requires total"),
                    ({"kind": "person"}, "who or path or query"), ({"kind": "news"}, "requires text"),
                    ({"kind": "logo"}, "who or path"), ({"kind": "screenshot"}, "requires url"),
                    ({"kind": "chart", "ticker": "^JKSE"}, "needs `start`"),
                    ({"kind": "unit", "total": 10, "filled": 11}, "can't be more"),
                    ({"kind": "screenshot", "url": "kaskus.us"}, "http"),
                    ({"kind": "chart", "points": [{"x": "a", "y": 1}]}, "at least 2")]:
        with pytest.raises(ValidationError, match=msg):
            StageElement(at="a", **el)
    assert StageElement(at="a", kind="cutout", who="Joko Widodo").who == "Joko Widodo"


# ---- chart data and geometry

def test_csv_and_downsample(tmp_path, monkeypatch):
    f = tmp_path / "d.csv"
    f.write_text('tahun,nilai\n2019,1000\n2020,"1,500"\n2021,\n2022,900\n')
    assert chartdata.from_csv(str(f)) == [("2019", 1000.0), ("2020", 1500.0), ("2022", 900.0)]
    pts = [(str(i), float(i)) for i in range(1000)]
    d = chartdata.downsample(pts, 10)
    assert len(d) == 10 and d[0] == pts[0] and d[-1] == pts[-1]


def test_ticker_uses_exchange_dates(monkeypatch):
    seen = {}

    def fake(url, headers=None, cache_key=None, **kw):
        seen["url"] = url
        return {"chart": {"result": [{"meta": {"gmtoffset": 25200}, "timestamp": [978282000, 978886800],
                                      "indicators": {"quote": [{"close": [425.6, None]}]}}]}}
    monkeypatch.setattr(http, "get_json", fake)
    with pytest.raises(chartdata.DataError):                     # one usable close is not a series
        chartdata.series(StageElement(at="a", kind="chart", ticker="^JKSE", start="2001-01-01"))
    assert "%5EJKSE" in seen["url"] and "interval=1mo" in seen["url"]
    assert chartdata.from_ticker("^JKSE", "2001-01-01", "2001-01-10")[0] == ("2001-01-01", 425.6)


def test_chart_geometry_bands_tone_and_labels():
    pts = [["2001-01-01", 425], ["2004-10-01", 840], ["2014-10-01", 5040], ["2026-10-16", 5185]]
    g = stage_mod.chart_geometry(pts, [{"start": "2004-10-01", "end": "2014-10-01", "label": "SBY"}],
                                 800, 520, "neutral", True)
    assert g["tone"] == "up" and (g["x0"], g["x1"]) == ("2001", "2026") and g["last"]["text"] == "5.185"
    assert g["line"].startswith("M") and g["len"] > 700
    [b] = g["bands"]
    assert b["label"] == "SBY" and 0 < b["x"] < b["x"] + b["w"] <= 800 * 0.95 + 0.1
    short = stage_mod.chart_geometry([["2026-10-01", 1.5], ["2026-10-16", 1.2]], [], 400, 260, "neutral", False)
    assert short["tone"] == "down" and short["x1"] == "16 Okt" and short["last"]["text"] == "1,20"


def test_unit_grid_fits_the_box():
    u = stage_mod.unit_grid(400, 120, 600, 500)
    assert u["cols"] * u["rows"] >= 400 and u["gw"] <= 600.1 and u["gh"] <= 500.1 and u["filled"] == 120


# ---- wikimedia

def _fake_wiki(monkeypatch, nonfree=False, logo=None):
    def fake(url, headers=None, cache_key=None, **kw):
        if "wbgetentities" in url:
            claims = [{"rank": "normal", "mainsnak": {"datavalue": {"value": n}}} for n in (logo or [])]
            return {"entities": {"Q1": {"claims": {"P154": claims}}}}
        if "pageimages" in url:
            return {"query": {"pages": {"1": {"pageimage": "Joko_Widodo_2019.jpg"}}}}
        return {"query": {"pages": {"-1": {"imageinfo": [{
            "url": "https://upload.wikimedia.org/x.jpg", "thumburl": "https://upload.wikimedia.org/t.jpg",
            "thumbwidth": 900, "thumbheight": 1080, "descriptionurl": "https://commons.wikimedia.org/wiki/File:x",
            "extmetadata": {"Artist": {"value": "<a href='x'>Setneg</a>"}, "LicenseShortName": {"value": "Public domain"},
                            **({"NonFree": {"value": "true"}} if nonfree else {})}}]}}}}
    monkeypatch.setattr(http, "get_json", fake)


def test_wikimedia_lookup_person_and_logo(monkeypatch):
    _fake_wiki(monkeypatch)
    c = wikimedia.lookup("Joko Widodo")
    assert c.provider == "wikimedia" and c.creator == "Setneg" and c.license == "Public domain" and not c.nonfree
    assert c.renditions[0].url.endswith("t.jpg") and c.page_url.startswith("https://commons")
    _fake_wiki(monkeypatch, logo=["Softbank mobile logo.svg", "SoftBank Group logo.svg"])
    assert wikimedia.lookup("SoftBank Group", logo=True).id.endswith("SoftBank Group logo.svg")
    _fake_wiki(monkeypatch, logo=[])                       # no Wikidata logo, lead image isn't a logo
    assert wikimedia.lookup("eFishery", logo=True) is None


def test_nonfree_person_photo_is_left_out(monkeypatch):
    _fake_wiki(monkeypatch, nonfree=True)
    scene = Spec.model_validate({"slug": "t", "scenes": [{"id": "s1", "template": "explain", "narration": "jokowi",
                                 "visual": stage({"at": "jokowi", "kind": "person", "who": "Joko Widodo"})}]}).scenes[0]
    warnings = []
    assert assets._stage_source(scene, 0, scene.visual.elements[0], set(), warnings) is None
    assert "non-free" in warnings[0]


# ---- screenshot, lint

def test_wayback_url_and_credit():
    assert screenshot.target_url("http://kaskus.us/", "2010") == "https://web.archive.org/web/2010if_/http://kaskus.us/"
    assert "Wayback" in screenshot.credit("http://kaskus.us/", "2010")["creator"]


def test_lint_person_news_unit():
    narr = "Jokowi bilang begini dan beritanya ramai sekali di mana mana"
    spec = Spec.model_validate({"slug": "t", "scenes": [{"id": "s1", "template": "explain", "narration": narr,
        "visual": stage({"at": "Jokowi", "kind": "person", "query": "indonesian president"},
                        {"at": "beritanya", "kind": "news", "text": "Ramai"},
                        {"at": "ramai", "kind": "unit", "total": 300})}]})
    msgs = " ".join(str(i) for i in lint(spec))
    assert "set `who`" in msgs and "set `outlet`" in msgs and "300 squares" in msgs


# ---- compose

@needs_renderer
def test_compose_renders_the_new_elements():
    spec = Spec.model_validate({"slug": "t", "scenes": [
        {"id": "s1", "template": "explain", "narration": "ihsg jatuh jokowi panik berita kaskus logo kotak",
         "visual": stage({"at": "ihsg", "kind": "chart", "ticker": "^JKSE", "start": "2001-01-01", "text": "IHSG"},
                         {"at": "jokowi", "kind": "person", "who": "Joko Widodo", "stat": "+53%", "tone": "up"},
                         {"at": "berita", "kind": "news", "outlet": "Katadata", "date": "16 Okt", "text": "IHSG anjlok"},
                         {"at": "kaskus", "kind": "screenshot", "url": "http://kaskus.us/", "wayback": "2010", "clear": True},
                         {"at": "logo", "kind": "logo", "who": "SoftBank Group"},
                         {"at": "kotak", "kind": "unit", "total": 40, "filled": 10, "text": "1 kotak = 1.000 alat"})}]})
    ws = words(("ihsg", 100), ("jatuh", 500), ("jokowi", 900), ("panik", 1300), ("berita", 1700),
               ("kaskus", 2400), ("logo", 3000), ("kotak", 3600))
    rows = [{"el": 0, "render": "chart", "data": [["2001-01-01", 425], ["2026-10-16", 5185]], "source": "yahoo:^JKSE"},
            {"el": 1, "render": "person", "file": "media/s1_el1.jpg", "w": 600, "h": 720, "source": "wikimedia:x"},
            {"el": 3, "render": "screenshot", "file": "media/s1_el3.png", "w": 1100, "h": 1300, "source": "screenshot:x"},
            {"el": 4, "render": "logo", "file": "media/s1_el4.png", "w": 800, "h": 200, "source": "wikimedia:y"}]
    ctx, warnings = compose.build_context(spec, _timeline(("s1", 4500)), ws, {"scenes": {"s1": {"kind": None, "stage": rows}}})
    els = {e["kind"]: e for e in ctx["scenes"][0]["stage"]["elements"]}
    assert not warnings and set(els) == {"chart", "person", "news", "screenshot", "logo", "unit"}
    assert els["person"]["name"] == "Joko Widodo" and els["screenshot"]["host"] == "kaskus.us"
    assert els["unit"]["unit"]["filled"] == 10 and els["chart"]["chart"]["tone"] == "up"

    from jinja2 import Environment, FileSystemLoader, StrictUndefined
    from klip.paths import TEMPLATES_DIR
    env = Environment(loader=FileSystemLoader(TEMPLATES_DIR / "default"), undefined=StrictUndefined,
                      autoescape=True, trim_blocks=True, lstrip_blocks=True)
    env.filters["rgba"] = compose.rgba
    html = env.get_template("index.html.j2").render(**ctx)
    for needle in ("lc-line", "strokeDashoffset", "un-grid", "st-person", "Katadata", "sh-bar", "st-logo"):
        assert needle in html, needle
    assert html.count('<i class="on"') == 10 and html.count('<i class="off"') == 30
