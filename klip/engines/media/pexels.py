"""Pexels API (videos + photos). Enabled only when PEXELS_API_KEY is set.

Video search lives at https://api.pexels.com/v1/videos/ (the old /videos/ path is deprecated).
Attribution expected: credit the creator and Pexels.
"""

from __future__ import annotations

import urllib.parse
from pathlib import Path

from klip import env, http
from klip.engines.media.base import Candidate, Kind, Rendition

API = "https://api.pexels.com/v1/"


class Pexels:
    name = "pexels"

    def enabled(self) -> bool:
        return bool(env.get("PEXELS_API_KEY"))

    def search(self, query: str, kind: Kind, per_page: int = 15) -> list[Candidate]:
        params = {"query": query, "orientation": "portrait", "per_page": min(per_page, 80)}
        url = API + ("videos/search" if kind == "video" else "search")
        cache_key = f"pexels:{kind}:{urllib.parse.urlencode(sorted(params.items()))}"
        data = http.get_json(f"{url}?{urllib.parse.urlencode(params)}", cache_key=cache_key,
                             headers={"Authorization": env.get("PEXELS_API_KEY")})
        items = data.get("videos" if kind == "video" else "photos", [])
        return [c for rank, item in enumerate(items)
                if (c := (self._video if kind == "video" else self._photo)(item, rank)).renditions]

    def _video(self, v: dict, rank: int) -> Candidate:
        rends = [Rendition(f["link"], int(f["width"]), int(f["height"]))
                 for f in v.get("video_files", [])
                 if f.get("link") and f.get("width") and f.get("file_type") == "video/mp4"]
        user = v.get("user") or {}
        return Candidate(provider=self.name, id=str(v["id"]), kind="video", renditions=rends,
                         duration_s=float(v.get("duration") or 0), rank=rank,
                         creator=user.get("name", ""), creator_url=user.get("url", ""),
                         page_url=v.get("url", ""), license="Pexels License",
                         license_url="https://www.pexels.com/license/", thumb_url=v.get("image", ""))

    def _photo(self, p: dict, rank: int) -> Candidate:
        w, h = int(p.get("width") or 0), int(p.get("height") or 0)
        src = p.get("src") or {}
        rends = []
        if src.get("original") and w and h:
            rends.append(Rendition(src["original"], w, h))
            if h > 1920:  # Pexels serves resized originals via imgix-style params
                rends.append(Rendition(f"{src['original']}?auto=compress&cs=tinysrgb&h=1920",
                                       round(w * 1920 / h), 1920))
        return Candidate(provider=self.name, id=str(p["id"]), kind="photo", renditions=rends, rank=rank,
                         creator=p.get("photographer", ""), creator_url=p.get("photographer_url", ""),
                         page_url=p.get("url", ""), license="Pexels License",
                         license_url="https://www.pexels.com/license/", thumb_url=src.get("medium", ""))

    def fetch(self, c: Candidate) -> Path:
        r = c.best_rendition()
        ext = ".mp4" if c.kind == "video" else ".jpg"
        return http.download(r.url, f"pexels-{c.kind}-{c.id}-{r.width}x{r.height}{ext}")
