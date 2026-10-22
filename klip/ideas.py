"""`klip ideas`: today's trending searches (and anything you paste) → video ideas → a batch file.

Signals: Google Trends' daily trending searches RSS for a country (no key; each trend comes with its
news headlines), plus an optional file of your own (one trend per line: pasted from TikTok Creative
Center, a comment section, a group chat). The LLM (klip.yaml llm.provider) reads them with the
channel's brand guide (brands/<style>/skill/SKILL.md) and the topics already made, and proposes
explainer topics: a trend is a reason to post now, the topic itself should still teach something.
Output: a `klip batch` file (specs/ideas-<date>-<style>.yaml) with each idea's angle as a comment,
so you pick, edit, and run `klip batch … --scripts-only`.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

from klip import config, http
from klip.engines.llm.base import LLMError, LLMProvider
from klip.paths import PROJECTS_DIR, ROOT

log = logging.getLogger(__name__)

HT = "{https://trends.google.com/trending/rss}"


def cfg(key: str):
    return config.get(f"ideas.{key}")


@dataclass
class Trend:
    title: str
    traffic: str = ""
    news: list[str] = field(default_factory=list)
    source: str = "google-trends"


def parse_trends_rss(xml: str) -> list[Trend]:
    """Trends from Google Trends' trending-searches RSS: title, approximate traffic, news headlines."""
    out = []
    for item in ET.fromstring(xml).iter("item"):
        title = (item.findtext("title") or "").strip()
        if title:
            out.append(Trend(title, (item.findtext(f"{HT}approx_traffic") or "").strip(),
                             [t.strip() for n in item.iter(f"{HT}news_item")
                              if (t := n.findtext(f"{HT}news_item_title"))]))
    return out


def google_trends(geo: str) -> list[Trend]:
    url = f"https://trends.google.com/trending/rss?geo={geo}"
    xml = http.get_text(url, cache_key=f"trends-rss-{geo}", ttl_s=int(cfg("cache_minutes")) * 60)
    return parse_trends_rss(xml)[: int(cfg("max_trends"))]


def pasted(path: Path) -> list[Trend]:
    """Your own signals: one per line ('#' comments and blank lines skipped)."""
    lines = [ln.strip() for ln in path.read_text(encoding="utf-8").splitlines()]
    return [Trend(ln, source="pasted") for ln in lines if ln and not ln.startswith("#")]


def made_topics() -> list[str]:
    """Topics already made or drafted (project and spec slugs), so ideas don't repeat them."""
    slugs = {p.name for p in PROJECTS_DIR.glob("*") if p.is_dir()}
    slugs |= {p.stem for p in (ROOT / "specs").glob("*.json")}
    return sorted(s.replace("-", " ") for s in slugs)


def brand_guide(style: str) -> str:
    p = ROOT / "brands" / style / "skill" / "SKILL.md"
    return p.read_text(encoding="utf-8")[: int(cfg("brand_guide_chars"))] if p.is_file() else ""


SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["ideas"],
    "properties": {"ideas": {"type": "array", "items": {
        "type": "object", "additionalProperties": False,
        "required": ["topic", "angle", "hook", "trend", "why_now", "sensitivity", "check", "score"],
        "properties": {
            "topic": {"type": "string", "description": "The video topic in Indonesian, as `klip new` takes it "
                                                       "(e.g. 'Kenapa harga tiket konser bisa semahal itu?')."},
            "angle": {"type": "string", "description": "What the video explains, in one sentence."},
            "hook": {"type": "string", "description": "A first line that stops the scroll (Indonesian)."},
            "trend": {"type": "string", "description": "The trend or signal it rides on, exactly as given."},
            "why_now": {"type": "string", "description": "Why people care this week."},
            "series": {"type": "string", "description": "The brand series it fits, if the guide has series."},
            "sensitivity": {"type": "string", "enum": ["low", "medium", "high"],
                            "description": "Risk: politics, religion, tragedy, health or money advice, minors."},
            "check": {"type": "string", "description": "The facts to verify before writing."},
            "score": {"type": "integer", "minimum": 1, "maximum": 5,
                      "description": "Fit x timeliness x how much it teaches (5 = make it today)."},
        }}}},
}

SYSTEM = """You are the content strategist for a short-video channel (TikTok, Reels, Shorts) that makes
45-second Indonesian explainers. You get today's trending searches (with news headlines) and other
signals, the channel's brand guide, and the topics it already made. Propose video ideas:
- Each idea explains something (how, why, what it costs, what's behind it), riding on a trend so it's
  timely. Skip trends with nothing to explain (match scores, gossip, a celebrity's private life) unless
  there's a real explainer angle behind them (e.g. a final's ticket prices → how dynamic pricing works).
- Fit the brand guide's voice, audience, series and its no-go topics. Never repeat a topic already made.
- Never invent facts; say in `check` what to verify. Mark sensitive topics honestly.
- Prefer fewer strong ideas to many weak ones. Return them best first."""


def generate(provider: LLMProvider, style: str, trends: list[Trend], count: int) -> list[dict]:
    if not trends:
        raise LLMError("no trends or signals to work from")
    guide = brand_guide(style)
    user = "\n\n".join([
        f"Today: {dt.date.today().isoformat()}. Propose up to {count} ideas.",
        "## Signals\n" + "\n".join(
            f"- {t.title}" + (f" ({t.traffic} searches)" if t.traffic else "") + (f" [{t.source}]" if t.source != "google-trends" else "")
            + "".join(f"\n  - news: {h}" for h in t.news[:3]) for t in trends),
        "## Brand guide\n" + (guide or f"(no brand guide; style '{style}': a general Indonesian explainer channel)"),
        "## Topics already made\n" + ("\n".join(f"- {t}" for t in made_topics()) or "(none)"),
    ])
    out = provider.complete(SYSTEM, user, SCHEMA)
    data = json.loads(out) if isinstance(out, str) else out
    ideas = [i for i in data.get("ideas", []) if i.get("topic")]
    ideas.sort(key=lambda i: -int(i.get("score", 0)))
    return ideas[:count]


def _q(text: str) -> str:
    return json.dumps(str(text), ensure_ascii=False)


def batch_yaml(ideas: list[dict], style: str, duration: int, voice: str) -> str:
    """A `klip batch` file: one item per idea, its angle, hook, trend and checks as comments."""
    lines = [f"# klip ideas, {dt.date.today().isoformat()}, style {style}. Keep the ones you like, then:",
             "#   uv run klip batch <this file> --scripts-only    (review the specs, then render)",
             "defaults:", f"  voice: {voice}", f"  duration: {duration}", f"  style: {style}", "items:"]
    for i in ideas:
        lines += [f"  # [{i.get('score')}/5] {i.get('angle', '')}",
                  f"  #   hook: {i.get('hook', '')}",
                  f"  #   trend: {i.get('trend', '')} ({i.get('why_now', '')})"]
        if i.get("series"):
            lines.append(f"  #   series: {i['series']}")
        lines.append(f"  #   check: {i.get('check', '')}" + (f"  ⚠ sensitivity: {i['sensitivity']}"
                                                              if i.get("sensitivity") in ("medium", "high") else ""))
        lines.append(f"  - topic: {_q(i['topic'])}")
    return "\n".join(lines) + "\n"


def default_out(style: str) -> Path:
    return ROOT / "specs" / f"ideas-{dt.date.today().isoformat()}-{re.sub(r'[^a-z0-9-]', '', style)}.yaml"
