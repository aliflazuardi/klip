"""Stage photos: your photo folder, the photo brief, Commons/Unsplash search, layout spacing, motion."""

import json

import pytest
from PIL import Image
from pydantic import ValidationError

from klip import brief, config
from klip import stage as stage_mod
from klip.engines.media import commons, unsplash
from klip.lint import lint
from klip.spec import Scene, StageElement
from klip.stages import assets, compose
from tests.test_media import FakeProvider
from tests.test_stage import _photo, _spec, _timeline, stage, words


# ---- spec + lint

def test_brief_and_own_only_on_photo_props():
    StageElement(at="a", kind="cutout", query="dice", brief="dadu di meja", own=True, name="dice")
    with pytest.raises(ValidationError, match="`brief` / `own` are for"):
        StageElement(at="a", kind="label", text="x", own=True)


def test_lint_warns_when_icons_outnumber_photos():
    narr = "Bandar judi online nggak pernah bangkrut padahal banyak yang menang katanya"
    icons = stage({"at": "Bandar", "kind": "cutout", "query": "casino dealer"},
                  {"at": "online", "kind": "icon", "name": "smartphone"},
                  {"at": "menang", "kind": "icon", "name": "trophy"})
    photos = stage({"at": "Bandar", "kind": "cutout", "query": "casino dealer"},
                   {"at": "online", "kind": "photo", "query": "phone slot app"},
                   {"at": "menang", "kind": "icon", "name": "trophy"})
    def msgs(v):
        return [i.message for i in lint(_spec({"id": "s1", "template": "hook", "narration": narr, "visual": v}))]
    assert any("2 icon(s) vs 1 real picture(s)" in m for m in msgs(icons))
    assert not any("real picture" in m for m in msgs(photos))


# ---- photo folder + brief

def _jpg(path):
    Image.new("RGB", (40, 30), (200, 10, 10)).save(path)
    return path


def test_find_own_matches_scene_and_number(tmp_path):
    _jpg(tmp_path / "s1-1-bandar.jpg")
    _jpg(tmp_path / "s1-12.jpg")
    (tmp_path / "s1-2.txt").write_text("not a photo")
    assert brief.find_own(tmp_path, "s1", 0).name == "s1-1-bandar.jpg"
    assert brief.find_own(tmp_path, "s1", 11).name == "s1-12.jpg"
    assert brief.find_own(tmp_path, "s1", 1) is None and brief.find_own(tmp_path, "s2", 0) is None
    assert brief.filename("s3b", 2, "Uangnya diputar") == "s3b-3-uangnya-diputar"


def test_own_photo_wins_and_brief_lists_what_is_missing(tmp_path, monkeypatch):
    folder = tmp_path / "photos"
    monkeypatch.setattr(brief, "_cfg", lambda k, d=None: str(folder) if k == "dir" else config.get(f"stage.photos.{k}", d))
    spec = _spec({"id": "s1", "template": "hook", "narration": "bandar slot dan dadu menang",
                  "visual": stage({"at": "bandar", "kind": "cutout", "query": "casino dealer"},
                                  {"at": "slot", "kind": "photo", "query": "slot machine", "own": True},
                                  {"at": "dadu", "kind": "cutout", "query": "dice", "name": "dices",
                                   "brief": "dadu merah di meja hijau"},
                                  {"at": "menang", "kind": "label", "text": "Menang"})})
    (folder / "t").mkdir(parents=True)
    _jpg(folder / "t" / "s1-1-bandar.jpg")
    class ByQuery(FakeProvider):            # fresh candidates per search, like a real provider
        def search(self, query, kind, per_page=15, **kw):
            return [_photo(i, t) for i, t in (("slot", ["slot", "machine"]), ("dealer", ["casino", "dealer"]))]

    res = assets.fetch(spec, tmp_path, providers=[ByQuery("p", [])])
    rows = {r["el"]: r for r in res["scenes"]["s1"]["stage"]}
    assert rows[0]["origin"] == "own" and rows[0]["credit"]["license"] == "own"     # never the stock dealer
    assert rows[1]["origin"] == "stock" and 2 not in rows
    b = res["photo_brief"]
    assert (b["props"], b["need"], b["provided"]) == (3, 2, 1)
    items = {i["el"]: i for i in json.loads((tmp_path / "photo-brief.json").read_text())["items"]}
    assert items[1]["status"] == "own" and items[2]["status"] == "missing" and items[0]["status"] == "provided"
    md = (tmp_path / "photo-brief.md").read_text()
    assert "`s1-3-dadu.jpg`" in md and "dadu merah di meja hijau" in md and "sementara ikon `dices`" in md
    assert "unsplash.com/s/photos/slot-machine" in md


def test_brief_marks_weak_vision_picks():
    spec = _spec({"id": "s1", "template": "hook", "narration": "bandar dan dadu",
                  "visual": stage({"at": "bandar", "kind": "cutout", "query": "casino dealer"},
                                  {"at": "dadu", "kind": "cutout", "query": "dice"})})
    scenes = {"s1": {"stage": [{"el": 0, "origin": "stock", "vision_score": 2, "credit": {}},
                               {"el": 1, "origin": "stock", "vision_score": 3, "credit": {}}]}}
    assert [i["status"] for i in brief.items(spec, scenes, vision_ok=True)] == ["weak", "ok"]
    scenes["s1"]["stage"][1]["vision_rescued"] = True          # rescued by vision and rated 3: fine
    assert [i["status"] for i in brief.items(spec, scenes, vision_ok=True)] == ["weak", "ok"]
    unrated = {"s1": {"stage": [{"el": k, "origin": "stock", "credit": {}} for k in (0, 1)]}}
    assert [i["status"] for i in brief.items(spec, unrated, vision_ok=False)] == ["unchecked", "unchecked"]


def test_props_search_every_provider_in_any_shape():
    seen = []

    class Shaped(FakeProvider):
        def search(self, query, kind, per_page=15, **kw):
            seen.append((self.name, kw.get("shape")))
            return super().search(query, kind, per_page)

    s = Scene(id="s1", template="explain", narration="dadu acak",
              visual=stage({"at": "dadu", "kind": "cutout", "query": "dice"}))
    pools = assets.prop_pools(s, s.visual.elements[0], set(),
                              [Shaped("a", [_photo("d1", ["dice"])]), Shaped("b", [_photo("d2", ["dice"])])], [])
    assert {p.name for _, p, _ in pools} == {"a", "b"} and all(shape == "any" for _, shape in seen)


# ---- providers

def test_commons_keeps_free_licences_only(monkeypatch):
    def page(i, lic, w=2000, h=1500, nonfree=""):
        return {"index": i, "title": f"File:Dice {i}.jpg", "imageinfo": [{
            "url": f"https://u/{i}.jpg", "thumburl": f"https://t/{i}.jpg", "thumbwidth": w, "thumbheight": h,
            "mime": "image/jpeg", "descriptionurl": f"https://c/{i}",
            "extmetadata": {"LicenseShortName": {"value": lic}, "Artist": {"value": "<a>Ann</a>"},
                            "NonFree": {"value": nonfree}, "ImageDescription": {"value": "red dice on a table"}}}]}
    data = {"query": {"pages": {"1": page(1, "CC BY-SA 4.0"), "2": page(2, "CC BY 4.0"), "3": page(3, "CC0"),
                                "4": page(4, "Fair use", nonfree="true"), "5": page(5, "CC BY 2.0", 300, 200)}}}
    monkeypatch.setattr(commons.http, "get_json", lambda *a, **k: data)
    got = commons.Commons().search("dice", "photo", shape="any")
    assert [c.id for c in got] == ["Dice 2.jpg", "Dice 3.jpg"] and got[0].creator == "Ann"
    assert "dice" in got[0].tags and commons.Commons().search("dice", "video") == []
    assert commons.Commons().search("dice", "photo") == []          # portrait b-roll: all are landscape
    assert not commons.license_ok("CC BY-NC 4.0") and commons.license_ok("Public domain")


def test_unsplash_parses_and_hides_key(monkeypatch):
    seen = {}

    def fake(url, headers=None, cache_key=None, **kw):
        seen.update(url=url, headers=headers, cache_key=cache_key)
        return {"results": [{"id": "abc", "width": 4000, "height": 3000, "urls": {"raw": "https://img/abc?ixid=1",
                             "small": "https://img/abc-s"}, "alt_description": "red dice", "user": {"name": "Bo",
                             "links": {"html": "https://unsplash.com/@bo"}}, "links": {"html": "https://unsplash.com/photos/abc",
                             "download_location": "https://api/dl"}}]}

    monkeypatch.setenv("UNSPLASH_ACCESS_KEY", "sekret")
    monkeypatch.setattr(unsplash.http, "get_json", fake)
    [c] = unsplash.Unsplash().search("dice", "photo", shape="any")
    assert c.title == "red dice" and c.renditions[0].width == 1600 and "orientation" not in seen["url"]
    assert "sekret" in seen["headers"]["Authorization"] and "sekret" not in seen["cache_key"]
    assert c.page_url.endswith("utm_medium=referral")


# ---- layout + motion

def test_layout_pushes_overlapping_props_apart():
    els = [StageElement(at="a", kind="icon", name="smartphone", label="Judol"),
           StageElement(at="b", kind="label", text="Nggak bangkrut?"),
           StageElement(at="c", kind="icon", name="trophy", label="Menang?"),
           StageElement(at="d", kind="label", text="Menang?")]
    boxes = stage_mod.layout("s1", els, {}, (480.0, 1450.0))
    gap = config.get("stage.layout_gap_px")
    for i in boxes:
        for j in boxes:
            if i < j:
                a, b = boxes[i], boxes[j]
                apart_x = abs(a["x"] - b["x"]) >= (a["w"] + b["w"]) / 2 + gap - 1
                apart_y = abs(a["y"] - b["y"]) >= (a["h"] + b["h"]) / 2 + gap - 1
                assert apart_x or apart_y, (i, j)
        assert 60 <= boxes[i]["x"] - boxes[i]["w"] / 2 and boxes[i]["x"] + boxes[i]["w"] / 2 <= 960


@pytest.mark.parametrize("text,want", [("Rp12.000", ("Rp", 12000, 0, "")), ("-4%", ("-", 4, 0, "%")),
                                       ("2,5 jt", ("", 2.5, 1, " jt")), ("2025", None), ("8/10", None)])
def test_count_up_parses_indonesian_numbers(text, want):
    c = stage_mod.count_up(text)
    assert (c and (c["prefix"], c["value"], c["decimals"], c["suffix"])) == want or (c is None and want is None)


def test_motion_floats_until_exit_and_follows_props():
    spec = _spec({"id": "s1", "template": "explain", "narration": "bandar dadu menang besar",
                  "visual": stage({"at": "bandar", "kind": "cutout", "query": "dealer"},
                                  {"at": "dadu", "kind": "number", "text": "-4%"},
                                  {"at": "menang", "kind": "label", "text": "Menang", "clear": True})})
    ws = words(("bandar", 100), ("dadu", 900), ("menang", 3000), ("besar", 3600))
    media = {"s1": {"kind": None, "stage": [{"el": 0, "render": "cutout", "file": "media/s1_el0.png",
                                             "w": 400, "h": 500, "source": "p:1"}]}}
    ctx, _ = compose.build_context(spec, _timeline(("s1", 5000)), ws, {"scenes": media})
    st = ctx["scenes"][0]["stage"]
    cut, num, lab = st["elements"]
    assert cut["enter"] in ("drop", "slide") and cut["float"]["repeat"] % 2 == 0    # odd half-cycles: ends at rest
    f = cut["float"]
    assert f["t"] + f["half"] * (f["repeat"] + 1) <= cut["exit"] + 1e-6
    assert num["count"] == {"prefix": "-", "value": 4.0, "decimals": 0, "suffix": "%"}
    assert lab["exit"] is None and lab["exit_to"]["x"] in (-1100, 1100)
    assert [k["t"] for k in st["camera"]] == [cut["start"], num["start"], lab["start"]]
    assert all(k["dur"] > 0 for k in st["camera"])


def test_missing_photo_with_name_becomes_its_icon():
    spec = _spec({"id": "s1", "template": "explain", "narration": "dadu acak",
                  "visual": stage({"at": "dadu", "kind": "cutout", "query": "dice", "name": "dices", "label": "Acak"})})
    ctx, warnings = compose.build_context(spec, _timeline(("s1", 3000)), words(("dadu", 100), ("acak", 600)),
                                          {"scenes": {"s1": {"kind": None, "stage": []}}})
    [e] = ctx["scenes"][0]["stage"]["elements"]
    assert e["kind"] == "icon" and "<svg" in e["svg"] and any("showing its icon 'dices'" in w for w in warnings)
