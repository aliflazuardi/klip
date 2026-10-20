"""Unsplash API (photos). Enabled only when UNSPLASH_ACCESS_KEY is set. Docs: https://unsplash.com/documentation

Guidelines: credit the photographer and Unsplash, and report each use by calling the photo's
download_location (done in fetch). Demo apps get 50 requests an hour; responses are cached 24 h.
"""

from __future__ import annotations

import urllib.parse
from pathlib import Path

from klip import config, env, http
from klip.engines.media.base import Candidate, Kind, Rendition

API = "https://api.unsplash.com/"
UTM = "utm_source=klip&utm_medium=referral"


class Unsplash:
    name = "unsplash"

    def enabled(self) -> bool:
        return bool(env.get("UNSPLASH_ACCESS_KEY"))

    def _headers(self) -> dict:
        return {"Authorization": f"Client-ID {env.get('UNSPLASH_ACCESS_KEY')}", "Accept-Version": "v1"}

    def search(self, query: str, kind: Kind, per_page: int = 15, shape: str = "portrait") -> list[Candidate]:
        if kind != "photo":
            return []
        params = {"query": query, "per_page": min(per_page, 30), "content_filter": "high"}
        if shape == "portrait":
            params["orientation"] = "portrait"
        qs = urllib.parse.urlencode(sorted(params.items()))
        data = http.get_json(f"{API}search/photos?{qs}", headers=self._headers(), cache_key=f"unsplash:{qs}")
        width = int(config.get("assets.unsplash_px", 1600))
        out = []
        for rank, p in enumerate(data.get("results", [])):
            w, h, raw = int(p.get("width") or 0), int(p.get("height") or 0), (p.get("urls") or {}).get("raw")
            if not (w and h and raw):
                continue
            s = min(1.0, width / max(w, h))
            user = p.get("user") or {}
            tags = [t.get("title", "") for t in p.get("tags") or [] if t.get("title")]
            c = Candidate(
                provider=self.name, id=p["id"], kind="photo", rank=rank,
                renditions=[Rendition(f"{raw}&fm=jpg&q=85&w={round(w * s)}", round(w * s), round(h * s))],
                creator=user.get("name", ""), creator_url=f"{(user.get('links') or {}).get('html', '')}?{UTM}",
                page_url=f"{(p.get('links') or {}).get('html', '')}?{UTM}", license="Unsplash License",
                license_url="https://unsplash.com/license",
                title=p.get("alt_description") or p.get("description") or "", tags=tags,
                thumb_url=(p.get("urls") or {}).get("small", ""))
            c.download_location = (p.get("links") or {}).get("download_location", "")  # type: ignore[attr-defined]
            out.append(c)
        return out

    def fetch(self, c: Candidate) -> Path:
        r = c.best_rendition()
        path = http.download(r.url, f"unsplash-{c.id}-{r.width}x{r.height}.jpg")
        if loc := getattr(c, "download_location", ""):
            try:     # the guidelines ask to report each use; a failure must not stop the render
                http.get_json(loc, headers=self._headers(), cache_key=f"unsplash-dl:{c.id}")
            except http.HTTPError:
                pass
        return path
