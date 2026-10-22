"""Preview review (klip/sheetcheck.py): prompt, parsing, review.json and its place in qa.json."""

import json

from klip import sheetcheck
from klip.spec import Spec

ROWS = [{"scene": "s1", "sheet": "s1.jpg", "frames": [{"t": 0.15, "label": "start", "png": "a.png"},
                                                       {"t": 1.2, "label": "“terbit”", "png": "b.png"}]},
        {"scene": "s2", "sheet": "s2.jpg", "frames": [{"t": 2.2, "label": "start", "png": "c.png"}]}]
WORDS = [{"text": " matahari", "startMs": 100, "endMs": 400, "sceneId": "s1"},
         {"text": " terbit", "startMs": 1200, "endMs": 1500, "sceneId": "s1"},
         {"text": " lalu", "startMs": 2300, "endMs": 2500, "sceneId": "s2"}]


def spec():
    return Spec.model_validate({"slug": "t", "scenes": [
        {"id": "s1", "template": "hook", "narration": "matahari terbit", "on_screen_text": "Pagi"},
        {"id": "s2", "template": "explain", "narration": "lalu"}]})


def test_prompt_lists_each_still_with_what_the_voice_says():
    text = sheetcheck.prompt(spec(), ROWS, WORDS, {"palette": {"bg": "#000000"}, "texture": "grain",
                                                   "families": {}, "notes": "flat 2D"})
    assert "sheet ./s1.jpg (2 stills)" in text and "2. 1.20s (“terbit”): voice says “terbit”" in text
    assert "Art direction: flat 2D" in text and "on-screen text: Pagi" in text


def test_parse_clamps_scores_maps_stills_and_flags_low_scenes():
    data = {"scenes": [{"id": "scene s1", "score": 2, "issues": [
        {"still": 2, "kind": "unreadable_text", "problem": "headline over cars", "fix": "add a scrim"},
        {"still": 9, "kind": "weird", "problem": "x", "fix": "y"}]}]}
    out = sheetcheck.parse(data, ROWS)
    s1, s2 = out
    assert s1["flagged"] and s1["issues"][0]["t"] == 1.2 and s1["issues"][1]["kind"] == "off_style"
    assert s1["issues"][1]["t"] == 1.2                               # a still past the sheet maps to its last
    assert s2 == {"scene": "s2", "score": None, "flagged": False, "issues": []}


def test_run_writes_review_and_qa_marks_changed_scenes_stale(tmp_path, monkeypatch):
    (tmp_path / "preview").mkdir()
    (tmp_path / "words.json").write_text(json.dumps(WORDS))
    monkeypatch.setattr(sheetcheck, "_call", lambda user, sheets: {"scenes": [
        {"id": "s1", "score": 5, "issues": []}, {"id": "s2", "score": 3, "issues": []}]})
    hashes = {"s1": "aaa", "s2": "bbb"}
    monkeypatch.setattr(sheetcheck, "file_hash", lambda sp, sid: hashes[sid])
    rev = sheetcheck.run(spec(), tmp_path, ROWS)
    assert rev["flagged"] == ["s2"] and json.loads((tmp_path / "preview" / "review.json").read_text()) == rev
    hashes["s2"] = "changed"
    qa = sheetcheck.for_qa(spec(), tmp_path)
    assert qa["stale"] == ["s2"] and qa["flagged"] == []          # a stale flag isn't reported as current


def test_a_partial_review_keeps_the_other_scenes(tmp_path, monkeypatch):
    (tmp_path / "preview").mkdir()
    (tmp_path / "words.json").write_text(json.dumps(WORDS))
    monkeypatch.setattr(sheetcheck, "file_hash", lambda sp, sid: "h")
    monkeypatch.setattr(sheetcheck, "_call", lambda user, sheets: {"scenes": [
        {"id": "s1", "score": 5, "issues": []}, {"id": "s2", "score": 2, "issues": []}]})
    sheetcheck.run(spec(), tmp_path, ROWS)
    monkeypatch.setattr(sheetcheck, "_call", lambda user, sheets: {"scenes": [{"id": "s1", "score": 3, "issues": []}]})
    rev = sheetcheck.run(spec(), tmp_path, ROWS[:1])
    assert [(s["scene"], s["score"]) for s in rev["scenes"]] == [("s1", 3), ("s2", 2)]
    assert rev["flagged"] == ["s1", "s2"]
