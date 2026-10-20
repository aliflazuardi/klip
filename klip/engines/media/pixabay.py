"""Pixabay API (videos + photos). Docs: https://pixabay.com/api/docs/

Terms: cache responses 24 h, download files instead of hotlinking. No attribution required,
but we credit the creator anyway.
"""

from __future__ import annotations

import urllib.parse
from pathlib import Path

from klip import env, http
from klip.engines.media.base import Candidate, Kind, Rendition

API = "https://pixabay.com/api/"


class Pixabay:
    name = "pixabay"

    def enabled(self) -> bool:
        return bool(env.get("PIXABAY_API_KEY"))

    def search(self, query: str, kind: Kind, per_page: int = 15, shape: str = "portrait") -> list[Candidate]:
        params = {"q": query[:100], "per_page": max(3, min(per_page, 200)), "safesearch": "true"}
        if kind == "video":
            url = API + "videos/"
            params["video_type"] = "film"
        else:
            url = API
            params.update(image_type="photo", orientation="vertical" if shape == "portrait" else "all")
        cache_key = f"pixabay:{kind}:{urllib.parse.urlencode(sorted(params.items()))}"
        params["key"] = env.get("PIXABAY_API_KEY")
        data = http.get_json(f"{url}?{urllib.parse.urlencode(params)}", cache_key=cache_key)
        out = []
        for rank, h in enumerate(data.get("hits", [])):
            c = self._video(h, rank) if kind == "video" else self._photo(h, rank)
            if c and c.renditions:
                out.append(c)
        return out

    def _common(self, h: dict, rank: int) -> dict:
        return dict(provider=self.name, id=str(h["id"]), rank=rank, creator=h.get("user", ""),
                    creator_url=f"https://pixabay.com/users/{h.get('user', '')}-{h.get('user_id', '')}/",
                    page_url=h.get("pageURL", ""), license="Pixabay Content License",
                    license_url="https://pixabay.com/service/license-summary/",
                    tags=[t.strip() for t in h.get("tags", "").split(",") if t.strip()])

    def _video(self, h: dict, rank: int) -> Candidate:
        rends = [Rendition(v["url"], int(v["width"]), int(v["height"]), int(v.get("size") or 0))
                 for v in h.get("videos", {}).values() if v.get("url") and v.get("width")]
        thumb = next((v.get("thumbnail") for k in ("small", "tiny", "medium")
                      if (v := h.get("videos", {}).get(k)) and v.get("thumbnail")), "")
        return Candidate(kind="video", renditions=rends, duration_s=float(h.get("duration") or 0),
                         thumb_url=thumb, **self._common(h, rank))

    def _photo(self, h: dict, rank: int) -> Candidate:
        w, hgt = int(h.get("imageWidth") or 0), int(h.get("imageHeight") or 0)
        rends = []
        if h.get("fullHDURL"):  # only with approved full API access
            s = min(1.0, 1920 / max(w, hgt)) if w and hgt else 1.0
            rends.append(Rendition(h["fullHDURL"], int(w * s), int(hgt * s)))
        if h.get("largeImageURL") and w and hgt:
            s = min(1.0, 1280 / max(w, hgt))
            rends.append(Rendition(h["largeImageURL"], int(w * s), int(hgt * s)))
        return Candidate(kind="photo", renditions=rends, thumb_url=h.get("webformatURL") or h.get("previewURL", ""),
                         **self._common(h, rank))

    def fetch(self, c: Candidate) -> Path:
        r = c.best_rendition()
        ext = ".mp4" if c.kind == "video" else ".jpg"
        return http.download(r.url, f"pixabay-{c.kind}-{c.id}-{r.width}x{r.height}{ext}")
