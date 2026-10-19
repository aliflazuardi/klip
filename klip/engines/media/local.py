"""Local b-roll library: assets/broll/**. Tags come from folder and file names.

e.g. assets/broll/food/warung-nasi-goreng-night.mp4 -> tags {food, warung, nasi, goreng, night}
"""

from __future__ import annotations

from functools import cache
from pathlib import Path

from klip import config, ffmpeg
from klip.engines.media.base import Candidate, Kind, Rendition
from klip.paths import ROOT

VIDEO_EXT = {".mp4", ".mov", ".m4v", ".webm"}
PHOTO_EXT = {".jpg", ".jpeg", ".png", ".webp"}


def tokens(text: str) -> set[str]:
    from klip.engines.media.base import keywords
    return keywords(text)


@cache
def _dims(path: str) -> tuple[int, int, float]:
    info = ffmpeg.probe(path)
    v = next(s for s in info["streams"] if s["codec_type"] == "video")
    dur = float(info["format"].get("duration") or 0)
    return int(v["width"]), int(v["height"]), dur


def candidate_for_file(path: Path, rank: int = 0, tags: set[str] | None = None) -> Candidate:
    ext = path.suffix.lower()
    kind: Kind = "video" if ext in VIDEO_EXT else "photo"
    w, h, dur = _dims(str(path))
    return Candidate(provider="local", id=str(path), kind=kind,
                     renditions=[Rendition(str(path), w, h)],
                     duration_s=dur if kind == "video" else 0.0, rank=rank,
                     title=path.stem, local_path=str(path), tags=sorted(tags or []),
                     creator="own footage", license="own")


class LocalLibrary:
    name = "local"

    def __init__(self, root: Path | None = None):
        self.root = root or ROOT / config.get("assets.local_dir", "assets/broll")

    def enabled(self) -> bool:
        return self.root.is_dir()

    def search(self, query: str, kind: Kind, per_page: int = 15) -> list[Candidate]:
        want = tokens(query)
        if not want or not self.enabled():
            return []
        exts = VIDEO_EXT if kind == "video" else PHOTO_EXT
        hits = []
        for p in self.root.rglob("*"):
            if p.suffix.lower() not in exts:
                continue
            tags = tokens(str(p.relative_to(self.root).with_suffix("")))
            overlap = len(want & tags)
            # need at least half the query terms (min 1) to count as relevant
            if overlap >= max(1, (len(want) + 1) // 2):
                hits.append((overlap, p, tags))
        hits.sort(key=lambda x: (-x[0], str(x[1])))
        return [candidate_for_file(p, i, tags) for i, (_, p, tags) in enumerate(hits[:per_page])]

    def fetch(self, c: Candidate) -> Path:
        return Path(c.local_path)
