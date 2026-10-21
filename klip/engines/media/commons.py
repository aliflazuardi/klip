"""Wikimedia Commons file search (photos, no key): real objects, places and Indonesian things that
stock libraries show badly. Only free licences are kept (klip.yaml commons.licenses); the author and
licence go into credits.json and post.txt like every other source.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from urllib.parse import quote

from klip import config, http
from klip.engines.media.base import Candidate, Kind, Rendition
from klip.engines.media.wikimedia import _strip

API = "https://commons.wikimedia.org/w/api.php"
THUMB_PX = 330                                # preview for the vision check


def _cfg(key: str, default=None):
    return config.get(f"commons.{key}", default)


def license_ok(name: str) -> bool:
    """Free licences only: CC0, public domain, CC BY (and CC BY-SA when commons.allow_sharealike)."""
    n = name.strip().lower()
    if not n:
        return False
    if n.startswith(("cc0", "public domain", "pd")) or "public domain" in n:
        return True
    if re.match(r"cc[ -]by[ -]sa\b", n):
        return bool(_cfg("allow_sharealike", False))
    return bool(re.match(r"cc[ -]by\b(?![ -]nc)(?![ -]nd)", n))


class Commons:
    name = "commons"

    def enabled(self) -> bool:
        return True

    def search(self, query: str, kind: Kind, per_page: int = 15, shape: str = "portrait") -> list[Candidate]:
        if kind != "photo":
            return []
        width = int(_cfg("photo_px", 1600))
        params = {"action": "query", "generator": "search", "gsrnamespace": 6, "gsrlimit": min(per_page * 2, 40),
                  "gsrsearch": f"{query} filetype:bitmap", "prop": "imageinfo", "iiprop": "url|size|extmetadata|mime",
                  "iiurlwidth": width, "format": "json",
                  "iiextmetadatafilter": "LicenseShortName|LicenseUrl|Artist|Credit|NonFree|ImageDescription|ObjectName"}
        qs = "&".join(f"{k}={quote(str(v), safe='|')}" for k, v in params.items())
        data = http.get_json(f"{API}?{qs}", cache_key=f"commons:{query}:{per_page}:{width}")
        pages = sorted((data.get("query") or {}).get("pages", {}).values(), key=lambda p: p.get("index", 0))
        out: list[Candidate] = []
        for p in pages:
            info = (p.get("imageinfo") or [None])[0]
            if not info or info.get("mime") not in ("image/jpeg", "image/png", "image/webp"):
                continue
            meta = {k: v.get("value", "") for k, v in (info.get("extmetadata") or {}).items()}
            lic = _strip(meta.get("LicenseShortName", ""))
            if str(meta.get("NonFree", "")).lower() in ("true", "1", "yes") or not license_ok(lic):
                continue
            w = info.get("thumbwidth") or info.get("width") or 0
            h = info.get("thumbheight") or info.get("height") or 0
            if min(w, h) < int(_cfg("min_px", 600)):
                continue
            if shape == "portrait" and h < w:
                continue
            title = re.sub(r"\.\w+$", "", p.get("title", "").removeprefix("File:")).replace("_", " ")
            desc = _strip(meta.get("ObjectName", "")) + " " + _strip(meta.get("ImageDescription", ""))[:300]
            out.append(Candidate(
                provider=self.name, id=p.get("title", "").removeprefix("File:"), kind="photo", rank=len(out),
                renditions=[Rendition(info.get("thumburl") or info["url"], int(w), int(h))],
                creator=_strip(meta.get("Artist", "")) or _strip(meta.get("Credit", "")) or "Wikimedia Commons",
                page_url=info.get("descriptionurl", ""), license=lic, license_url=meta.get("LicenseUrl", ""),
                title=title, tags=[t for t in re.split(r"[^\w]+", desc) if len(t) > 2][:40],
                thumb_url=re.sub(r"/\d+px-", f"/{THUMB_PX}px-", info.get("thumburl") or info["url"])))
            if len(out) >= per_page:
                break
        return out

    def fetch(self, c: Candidate) -> Path:
        url = c.renditions[0].url
        ext = Path(url.split("?")[0]).suffix.lower() or ".jpg"
        return http.download(url, f"commons-{hashlib.sha256(url.encode()).hexdigest()[:20]}{ext}")
