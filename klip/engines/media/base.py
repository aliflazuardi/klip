"""Media provider interface and candidate scoring."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal, Protocol

from klip import config

Kind = Literal["video", "photo"]

TARGET_W, TARGET_H = 1080, 1920


@dataclass
class Rendition:
    url: str
    width: int
    height: int
    size: int = 0  # bytes, 0 if unknown


@dataclass
class Candidate:
    provider: str
    id: str
    kind: Kind
    renditions: list[Rendition]
    duration_s: float = 0.0          # videos only
    rank: int = 0                    # provider's own relevance order (0 = best)
    creator: str = ""
    creator_url: str = ""
    page_url: str = ""
    license: str = ""
    license_url: str = ""
    title: str = ""
    local_path: str | None = None    # set for the local provider
    tags: list[str] = field(default_factory=list)
    thumb_url: str = ""              # small preview image (for the vision relevance check)
    nonfree: bool = False            # Wikipedia marks the file non-free (fair use, e.g. a corporate logo)

    @property
    def key(self) -> str:
        return f"{self.provider}:{self.id}"

    def best_rendition(self) -> Rendition:
        """Smallest rendition whose center crop covers >= 74% of 1080x1920 (e.g. 1440p landscape),
        else the largest. Keeps downloads ~half the size of 4K at a small sharpness cost."""
        def fills(r: Rendition) -> bool:
            return fill_ratio(r) >= config.get("assets.rendition_min_fill", 0.74)
        ok = [r for r in self.renditions if fills(r)]
        if ok:
            return min(ok, key=lambda r: r.width * r.height)
        return max(self.renditions, key=lambda r: r.width * r.height)

    def credit(self) -> dict:
        d = asdict(self)
        for k in ("renditions", "rank", "tags", "local_path", "thumb_url"):
            d.pop(k)
        return d


class MediaProvider(Protocol):
    name: str

    def enabled(self) -> bool: ...

    def search(self, query: str, kind: Kind, per_page: int = 15, shape: str = "portrait") -> list[Candidate]:
        """`shape`: "portrait" for full-screen b-roll, "any" for stage props (cut out or framed)."""
        ...

    def fetch(self, c: Candidate) -> Path:
        """Return a local file for the candidate (downloading into the cache if needed)."""
        ...


def fill_ratio(r: Rendition) -> float:
    """How much of 1080x1920 a center crop of this rendition covers at native resolution (<=1)."""
    crop_w = min(r.width, r.height * TARGET_W / TARGET_H)
    crop_h = crop_w * TARGET_H / TARGET_W
    return min(crop_w / TARGET_W, crop_h / TARGET_H, 1.0)


_STOP = {"a", "an", "the", "of", "in", "on", "at", "with", "and", "or", "to", "up", "close",
         "closeup", "shot", "view", "video", "photo", "stock", "footage"}


def _stem(word: str) -> str:
    w = word.lower()
    for suf in ("ies", "es", "s"):
        if w.endswith(suf) and len(w) - len(suf) >= 3:
            return w[: -len(suf)] + ("y" if suf == "ies" else "")
    return w


def keywords(text: str) -> set[str]:
    import re
    return {_stem(t) for t in re.split(r"[^a-zA-Z0-9]+", text) if t and t.lower() not in _STOP}


def relevance(c: Candidate, query: str) -> float | None:
    """Share of the query's keywords found in the candidate's tags/title (None = can't tell)."""
    want = keywords(query)
    have = keywords(" ".join(c.tags) + " " + c.title)
    if not want or not have:
        return None
    return len(want & have) / len(want)


def score(c: Candidate, need_s: float, query: str = "") -> float:
    """Higher is better. Resolution after crop (0-3), portrait bonus (0-1.5),
    duration fit for videos (0-2), provider rank (0-1), tag relevance (0-3)."""
    r = c.best_rendition()
    s = 3.0 * fill_ratio(r)
    rel = relevance(c, query) if query else None
    s += 3.0 * rel if rel is not None else 1.5
    s += 1.5 if r.height >= r.width * 1.3 else 0.0
    if c.kind == "video":
        s += 2.0 if c.duration_s >= need_s else 2.0 * (c.duration_s / need_s if need_s else 0)
    s += 1.0 / (1 + c.rank * 0.25)
    return round(s, 3)
