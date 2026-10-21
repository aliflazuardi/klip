"""Real people and organisations from Wikipedia / Wikimedia Commons.

`lookup(title)` finds the lead image of a Wikipedia article (a person's portrait) and
`lookup(title, logo=True)` the organisation's logo (Wikidata P154). Each result carries the file's
licence and author from Commons' extmetadata, so it lands in credits.json and post.txt. Files that
Wikipedia marks non-free (most corporate logos hosted on enwiki itself) are flagged `nonfree`.
"""

from __future__ import annotations

import hashlib
import html
import logging
import re
from pathlib import Path
from urllib.parse import quote

from klip import config, http
from klip.engines.media.base import Candidate, Rendition

log = logging.getLogger(__name__)

WIKIDATA_API = "https://www.wikidata.org/w/api.php"


def _api(lang: str) -> str:
    return f"https://{lang}.wikipedia.org/w/api.php"


def _cfg(key: str, default=None):
    return config.get(f"wikimedia.{key}", default)


def _strip(text: str) -> str:
    """extmetadata values are HTML snippets: plain text, one line."""
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", text or ""))).strip()


def _q(params: dict) -> str:
    return "&".join(f"{k}={quote(str(v), safe='|')}" for k, v in {**params, "format": "json"}.items())


def page_image(title: str, lang: str) -> str | None:
    """File name of an article's lead image (None if the article or its image doesn't exist)."""
    d = http.get_json(f"{_api(lang)}?{_q({'action': 'query', 'titles': title, 'prop': 'pageimages', 'piprop': 'name', 'redirects': 1})}",
                      cache_key=f"wiki-pageimage:{lang}:{title}")
    for p in (d.get("query") or {}).get("pages", {}).values():
        if p.get("pageimage"):
            return p["pageimage"]
    return None


def logo_file(title: str, lang: str) -> str | None:
    """The organisation's logo file from Wikidata (P154), preferring the one named after it."""
    d = http.get_json(f"{WIKIDATA_API}?{_q({'action': 'wbgetentities', 'sites': f'{lang}wiki', 'titles': title, 'props': 'claims'})}",
                      cache_key=f"wikidata-logo:{lang}:{title}")
    for ent in (d.get("entities") or {}).values():
        claims = [c for c in (ent.get("claims") or {}).get("P154", []) if c["mainsnak"].get("datavalue")]
        if not claims:
            continue
        words = {w.lower() for w in re.findall(r"\w+", title) if len(w) > 2}
        def rank(c):
            name = c["mainsnak"]["datavalue"]["value"]
            return (c.get("rank") == "preferred", len(words & {w.lower() for w in re.findall(r"\w+", name)}))
        return max(claims, key=rank)["mainsnak"]["datavalue"]["value"]
    return None


def file_info(name: str, lang: str, width: int) -> Candidate | None:
    """A Candidate for File:<name> (a `width` px rendition) with its licence and author."""
    params = {"action": "query", "titles": f"File:{name}", "prop": "imageinfo", "iiprop": "url|extmetadata|size",
              "iiurlwidth": width,
              "iiextmetadatafilter": "LicenseShortName|LicenseUrl|Artist|Credit|NonFree|AttributionRequired"}
    d = http.get_json(f"{_api(lang)}?{_q(params)}", cache_key=f"wiki-fileinfo:{lang}:{name}:{width}")
    for p in (d.get("query") or {}).get("pages", {}).values():
        info = (p.get("imageinfo") or [None])[0]
        if not info:
            continue
        meta = {k: v.get("value", "") for k, v in (info.get("extmetadata") or {}).items()}
        url = info.get("thumburl") or info["url"]
        w, h = info.get("thumbwidth") or info.get("width", 0), info.get("thumbheight") or info.get("height", 0)
        c = Candidate(provider="wikimedia", id=f"{lang}:{name}", kind="photo", renditions=[Rendition(url, w, h)],
                      creator=_strip(meta.get("Artist", "")) or _strip(meta.get("Credit", "")) or "Wikimedia",
                      page_url=info.get("descriptionurl", ""), license=_strip(meta.get("LicenseShortName", "")),
                      license_url=meta.get("LicenseUrl", ""), title=Path(name).stem.replace("_", " "))
        c.nonfree = str(meta.get("NonFree", "")).lower() in ("true", "1", "yes")
        return c
    return None


def lookup(title: str, logo: bool = False) -> Candidate | None:
    """The image for a Wikipedia article title in the first language (wikimedia.langs) that has one."""
    width = int(_cfg("logo_px" if logo else "photo_px", 900))
    for lang in _cfg("langs", ["en", "id"]):
        try:
            name = logo_file(title, lang) if logo else page_image(title, lang)
            if not name and logo:            # no Wikidata logo: a lead image that is a logo will do
                name = page_image(title, lang)
                name = name if name and "logo" in name.lower() else None
            if name and (c := file_info(name, lang, width)):
                return c
        except http.HTTPError as e:
            log.warning("wikimedia: %s (%s): %s", title, lang, e)
    return None


def fetch(c: Candidate) -> Path:
    url = c.renditions[0].url
    ext = Path(url.split("?")[0]).suffix.lower() or ".jpg"
    if ext == ".svg":                         # thumbnails of SVGs are PNG renders
        ext = ".png"
    return http.download(url, f"wikimedia-{hashlib.sha256(url.encode()).hexdigest()[:20]}{ext}")
