"""Vision relevance check: contact sheets, reviewer parsing, rerank/reject/rescue, fallback."""

import json
from pathlib import Path

import pytest
from PIL import Image

from klip.engines.media import vision
from klip.engines.media.base import Candidate, Rendition
from klip.spec import Scene, Spec
from klip.stages import assets


def cand(id, tags, rank=0):
    return Candidate(provider="p", id=id, kind="video", duration_s=10, rank=rank, tags=tags,
                     renditions=[Rendition("u", 2560, 1440)])


def test_contact_sheet_grid_and_missing_cells(tmp_path):
    imgs = []
    for i, color in enumerate(["red", "green", "blue", "white"]):
        p = tmp_path / f"{i}.jpg"
        Image.new("RGB", (640, 360), color).save(p)
        imgs.append(p)
    out = vision.contact_sheet([*imgs, None], tmp_path / "sheet.jpg")
    im = Image.open(out)
    assert im.size == (3 * vision.CELL_W, 2 * vision.CELL_H)
    # badge of cell 1 is yellow; the missing 5th cell is still drawn (numbering doesn't shift)
    assert im.getpixel((10, 10))[0] > 200 and im.getpixel((10, 10))[2] < 120
    assert im.getpixel((vision.CELL_W + 10, vision.CELL_H + 10))[0] > 200


def test_reviewer_parses_and_sanitizes(monkeypatch, tmp_path):
    sheet = tmp_path / "s.jpg"
    Image.new("RGB", (10, 10)).save(sheet)
    seen = {}

    def fake_run(cmd, input, capture_output, text, cwd, timeout):
        seen.update(cmd=cmd, input=input, files=sorted(p.name for p in Path(cwd).iterdir()))

        class P:
            returncode, stderr = 0, ""
            stdout = json.dumps({"subtype": "success", "is_error": False, "structured_output": {"scenes": [
                {"id": "scene s1", "ratings": [3, 1, 9, "x"]}, {"id": "s2", "ratings": [2]}, {"id": "zz", "ratings": [1]}]}})
        return P()

    monkeypatch.setattr(vision.subprocess, "run", fake_run)
    reviewer = vision.VisionReviewer("/bin/claude")
    out = ORIGINAL_REVIEW(reviewer, [vision.SceneSheet("s1", "narasi", "", "q", sheet, 4),
                                             vision.SceneSheet("s2", "narasi 2", "", "q2", sheet, 2)])
    assert out == {"s1": [3, 1, 3, 0], "s2": [2, 0]}            # clamp, junk→0, pad missing, drop unknown ids
    cmd = seen["cmd"]
    assert cmd[cmd.index("--tools") + 1] == "Read" and seen["files"] == ["s1.jpg", "s2.jpg"]
    assert "./s1.jpg" in seen["input"] and "narasi 2" in seen["input"]


# captured at import, before the autouse fixture blocks VisionReviewer.review
ORIGINAL_REVIEW = vision.VisionReviewer.review


class FakeReviewer:
    def __init__(self, verdicts=None, fail=False):
        self.verdicts, self.fail, self.sheets = verdicts or {}, fail, []

    def review(self, sheets):
        self.sheets = sheets
        if self.fail:
            raise RuntimeError("not logged in")
        return self.verdicts


def spec_one_scene():
    return Spec.model_validate({"slug": "t", "scenes": [
        {"id": "s1", "template": "hook", "narration": "simpan cabai di wadah", "on_screen_text": "Wadah",
         "visual": {"type": "stock_video", "query": "food container refrigerator", "name": "box"}}]})


def pools_with_extra():
    jar, port, rescued = cand("jar", ["food", "container"]), cand("port", ["container", "food"]), cand("fridge", [], 1)
    rescued.vision_only = True
    return {"s1": [("food container refrigerator", object(), [jar, port, rescued])]}


def test_vision_reorders_rejects_and_rescues(tmp_path):
    rev = FakeReviewer({"s1": [2, 1, 3]})       # fridge (rescued) 3 > jar 2; port 1 is below min_score
    plans, report = assets.vision_review(spec_one_scene(), pools_with_extra(), tmp_path, [], rev)
    assert [c.id for c in plans["s1"][0][2]] == ["fridge", "jar"]
    assert report["ok"] and report["kept"] == 2 and report["rejected"] == 1
    assert rev.sheets[0].count == 3 and (tmp_path / "vision" / "s1.jpg").exists()


def test_vision_failure_falls_back_without_extras(tmp_path):
    warnings = []
    plans, report = assets.vision_review(spec_one_scene(), pools_with_extra(), tmp_path, warnings,
                                         FakeReviewer(fail=True))
    assert [c.id for c in plans["s1"][0][2]] == ["jar", "port"] and not report["ok"]
    assert any("vision check unavailable" in w for w in warnings)


def test_vision_reject_all_and_missing_verdict(tmp_path):
    warnings = []
    plans, _ = assets.vision_review(spec_one_scene(), pools_with_extra(), tmp_path, warnings,
                                    FakeReviewer({"s1": [0, 1, 1]}))
    assert plans["s1"][0][2] == [] and any("rejected all" in w for w in warnings)
    plans, _ = assets.vision_review(spec_one_scene(), pools_with_extra(), tmp_path, warnings, FakeReviewer({}))
    assert [c.id for c in plans["s1"][0][2]] == ["jar", "port"]          # no verdict → don't punish


def test_extra_untagged_candidates_join_the_pool():
    class Prov:
        name = "p"

        def enabled(self):
            return True

        def search(self, q, kind, per_page=15):
            return [cand("jar", ["food", "container"]), cand("fridge", ["kitchen"], 1), cand("cat", ["cat"], 2)]

        def fetch(self, c):
            return Path("/tmp/x")

    scene = spec_one_scene().scenes[0]
    pools = assets.build_pools(scene, 3, set(), [Prov()], [], extra=1)
    assert [c.id for c in pools[0][2]] == ["jar", "fridge"] and pools[0][2][1].vision_only
    assert [c.id for c in assets.build_pools(scene, 3, set(), [Prov()], [], extra=0)[0][2]] == ["jar"]
