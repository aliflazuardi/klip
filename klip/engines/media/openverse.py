"""Openverse image search (no API key). Only CC0 / Public Domain / CC BY are used.

CC BY requires attribution, so every credit is written to credits.json and post.txt.
"""

from __future__ import annotations

import re
import urllib.parse
from pathlib import Path

from klip import http
from klip.engines.media.base import Candidate, Kind, Rendition

API = "https://api.openverse.org/v1/images/"
LICENSES = "cc0,pdm,by"


def license_label(lic: str, version: str | None) -> str:
    lic = (lic or "").lower()
    if lic == "cc0":
        return "CC0"
    if lic == "pdm":
        return "Public Domain"
    return f"CC {lic.upper()} {version or ''}".strip()


class Openverse:
    name = "openverse"

    def enabled(self) -> bool:
        return True

    def search(self, query: str, kind: Kind, per_page: int = 15) -> list[Candidate]:
        if kind != "photo":
            return []
        params = {"q": query, "license": LICENSES, "aspect_ratio": "tall", "size": "large",
                  "page_size": min(per_page, 20), "mature": "false"}
        qs = urllib.parse.urlencode(sorted(params.items()))
        data = http.get_json(f"{API}?{qs}", cache_key=f"openverse:{qs}")
        out = []
        for rank, r in enumerate(data.get("results", [])):
            if not (r.get("url") and r.get("width") and r.get("height")):
                continue
            out.append(Candidate(
                provider=self.name, id=str(r["id"]), kind="photo", rank=rank,
                renditions=[Rendition(r["url"], int(r["width"]), int(r["height"]))],
                creator=r.get("creator") or "unknown", creator_url=r.get("creator_url") or "",
                page_url=r.get("foreign_landing_url") or "", title=r.get("title") or "",
                license=license_label(r.get("license"), r.get("license_version")),
                license_url=r.get("license_url") or "", thumb_url=r.get("thumbnail") or r["url"],
            ))
        return out

    def fetch(self, c: Candidate) -> Path:
        r = c.best_rendition()
        m = re.search(r"\.(jpe?g|png|webp)(?:$|\?)", r.url, re.I)
        ext = "." + (m.group(1).lower() if m else "jpg")
        return http.download(r.url, f"openverse-{c.id}{ext}")
