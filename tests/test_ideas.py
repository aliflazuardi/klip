"""klip ideas: trends RSS parsing, pasted signals, the LLM call and the batch file it writes."""

import json

import pytest
import yaml

from klip import batch, ideas
from klip.engines.llm.base import LLMError

RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss xmlns:ht="https://trends.google.com/trending/rss" version="2.0"><channel>
<item><title>harga tiket konser</title><ht:approx_traffic>5000+</ht:approx_traffic>
  <ht:news_item><ht:news_item_title>Tiket ludes dalam 3 menit</ht:news_item_title></ht:news_item>
  <ht:news_item><ht:news_item_title>Calo jual 5 kali lipat</ht:news_item_title></ht:news_item></item>
<item><title>skor bola</title><ht:approx_traffic>200+</ht:approx_traffic></item>
</channel></rss>"""


def test_parses_trends_with_traffic_and_news():
    t = ideas.parse_trends_rss(RSS)
    assert [x.title for x in t] == ["harga tiket konser", "skor bola"]
    assert t[0].traffic == "5000+" and t[0].news == ["Tiket ludes dalam 3 menit", "Calo jual 5 kali lipat"]


def test_pasted_signals_skip_comments(tmp_path):
    p = tmp_path / "s.txt"
    p.write_text("# from Creative Center\n#hashtag lebaran\n\nharga beras naik\n")
    assert [t.title for t in ideas.pasted(p)] == ["harga beras naik"] and ideas.pasted(p)[0].source == "pasted"


class FakeLLM:
    def __init__(self, reply):
        self.reply, self.calls = reply, []

    def complete(self, system, user, schema):
        self.calls.append((system, user, schema))
        return self.reply


def test_generate_sorts_by_score_and_writes_a_batch_file(tmp_path, monkeypatch):
    monkeypatch.setattr(ideas, "made_topics", lambda: ["kenapa langit biru"])
    reply = {"ideas": [
        {"topic": "Kenapa calo tiket konser bisa untung besar?", "angle": "a", "hook": "h", "trend": "harga tiket konser",
         "why_now": "w", "sensitivity": "low", "check": "c", "score": 3},
        {"topic": "Kenapa harga tiket konser naik turun?", "angle": "dynamic pricing", "hook": "h2", "trend": "harga tiket konser",
         "why_now": "w2", "series": "kenapa", "sensitivity": "medium", "check": "c2", "score": 5},
        {"topic": "", "score": 5}]}
    llm = FakeLLM(json.dumps(reply))
    rows = ideas.generate(llm, "default", ideas.parse_trends_rss(RSS), count=5)
    assert [r["score"] for r in rows] == [5, 3]
    user = llm.calls[0][1]
    assert "harga tiket konser (5000+ searches)" in user and "news: Tiket ludes" in user and "kenapa langit biru" in user
    out = tmp_path / "ideas.yaml"
    out.write_text(ideas.batch_yaml(rows, "default", 40, "male"))
    items = batch.load(out)
    assert [i.topic for i in items] == [r["topic"] for r in rows] and items[0].duration == 40 and items[0].voice == "male"
    text = out.read_text()
    assert "# [5/5] dynamic pricing" in text and "sensitivity: medium" in text and "series: kenapa" in text
    assert yaml.safe_load(text)["defaults"]["style"] == "default"


def test_generate_needs_signals():
    with pytest.raises(LLMError, match="no trends"):
        ideas.generate(FakeLLM({"ideas": []}), "default", [], count=3)
