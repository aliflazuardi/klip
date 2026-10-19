"""Vision relevance check for stage props: one sheet per cutout/photo element, top rating wins."""

import pytest

from klip.spec import Scene
from klip.stages import assets
from tests.test_stage import _photo, _spec, stage
from tests.test_media import FakeProvider
from tests.test_vision import FakeReviewer


def _tempe_spec():
    return _spec({"id": "s1", "template": "hook", "narration": "harga tempe naik",
                  "visual": stage({"at": "tempe", "kind": "cutout", "query": "tempeh", "label": "Tempe"},
                                  {"at": "naik", "kind": "label", "text": "naik"})})


def _tempe_provider():
    burger = _photo("burger", ["tempeh", "burger", "plate"])        # tag-relevant, wrong subject
    block = _photo("block", ["tempeh", "isolated"])
    busy = _photo("busy", ["tempeh", "market"])
    return FakeProvider("p", [burger, block, busy])


@pytest.fixture
def vision_on(monkeypatch):
    from klip import config
    real = config.get
    monkeypatch.setattr(config, "get", lambda k, d=None: {**real(k, d), "enabled": True}
                        if k == "assets.vision_check" else real(k, d))
    monkeypatch.setattr(assets, "_thumb", lambda c: None)


def test_vision_check_picks_top_rated_stage_prop(tmp_path, vision_on):
    rev = FakeReviewer({"s1-el0": [0, 3, 2]})                    # sheet order: burger, block, busy
    res = assets.fetch(_tempe_spec(), tmp_path, providers=[_tempe_provider()], reviewer=rev)
    [sheet] = rev.sheets
    assert sheet.id == "s1-el0" and sheet.count == 3 and sheet.query == "tempeh"
    assert "'tempe'" in sheet.prop and "'Tempe'" in sheet.prop and sheet.narration == "harga tempe naik"
    assert [r["credit"]["id"] for r in res["scenes"]["s1"]["stage"]] == ["block"]
    assert res["vision"]["props"] == 1 and res["vision"]["rejected"] == 1


def test_vision_check_stage_prop_reject_all_and_fallback(tmp_path, vision_on):
    res = assets.fetch(_tempe_spec(), tmp_path, providers=[_tempe_provider()],
                       reviewer=FakeReviewer({"s1-el0": [0, 1, 0]}))
    assert res["scenes"]["s1"]["stage"] == [] and any("rejected all" in w for w in res["warnings"])
    # vision check unavailable → the first tag-relevant photo, as without the check
    res = assets.fetch(_tempe_spec(), tmp_path, providers=[_tempe_provider()], reviewer=FakeReviewer(fail=True))
    assert [r["credit"]["id"] for r in res["scenes"]["s1"]["stage"]] == ["burger"]
    assert any("vision check unavailable" in w for w in res["warnings"])


def test_stage_pools_gate_on_plain_query_and_add_extras():
    zebra = _photo("zebra", ["zebra", "isolated"])
    s = Scene(id="s1", template="explain", narration="tempe",
              visual=stage({"at": "tempe", "kind": "cutout", "query": "tempeh"}))
    plans = assets.stage_pools(s, set(), [FakeProvider("p", [zebra, _photo("t", ["tempeh"])])], [], extra=1)
    [(q1, _, c1), (q2, _, _)] = plans["s1-el0"]
    assert q1 == "tempeh isolated" and q2 == "tempeh"
    assert [c.id for c in c1] == ["t", "zebra"] and c1[1].vision_only     # zebra only as a rescue extra
