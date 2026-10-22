"""HTTP helpers with an on-disk response cache and call counters.

API responses are cached for 24 h (Pixabay requires it; it also keeps us within quotas).
Downloads are cached forever under ~/.cache/klip/media/.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from klip import __version__, config, paths

log = logging.getLogger(__name__)

USER_AGENT = f"klip/{__version__} (+https://github.com/aliflazuardi/klip)"
RESPONSE_TTL_S = int(config.get("assets.api_cache_hours", 24) * 3600)


class HTTPError(RuntimeError):
    def __init__(self, msg: str, status: int | None = None):
        super().__init__(msg)
        self.status = status


@dataclass
class Stats:
    api_calls: int = 0
    api_cache_hits: int = 0
    downloads: int = 0
    download_cache_hits: int = 0

    def reset(self) -> None:
        self.__init__()


stats = Stats()


def _cache_dir(name: str) -> Path:
    d = paths.CACHE_DIR / name
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_json(url: str, headers: dict | None = None, cache_key: str | None = None,
             ttl_s: int = RESPONSE_TTL_S, retries: int = 2) -> dict:
    """GET JSON. `cache_key` should identify the request without secrets (no API keys)."""
    return json.loads(get_text(url, headers, cache_key, ttl_s, retries, ext="json"))


def get_text(url: str, headers: dict | None = None, cache_key: str | None = None,
             ttl_s: int = RESPONSE_TTL_S, retries: int = 2, ext: str = "txt") -> str:
    """GET a text body (RSS, HTML, JSON), cached like get_json."""
    key = hashlib.sha256((cache_key or url).encode()).hexdigest()[:24]
    cached = _cache_dir("api") / f"{key}.{ext}"
    if cached.exists() and time.time() - cached.stat().st_mtime < ttl_s:
        stats.api_cache_hits += 1
        return cached.read_text(encoding="utf-8")

    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    for attempt in range(retries + 1):
        stats.api_calls += 1
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                text = r.read().decode("utf-8")
            cached.write_text(text, encoding="utf-8")
            return text
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < retries:
                wait = int(e.headers.get("Retry-After") or e.headers.get("X-RateLimit-Reset") or 5)
                log.warning("rate limited; waiting %ss", min(wait, 60))
                time.sleep(min(wait, 60))
                continue
            raise HTTPError(f"HTTP {e.code} for {cache_key or 'request'}", e.code) from None
        except (urllib.error.URLError, TimeoutError) as e:
            if attempt < retries:
                time.sleep(2 * (attempt + 1))
                continue
            raise HTTPError(f"network error for {cache_key or 'request'}: {e}") from None
    raise HTTPError("unreachable")


def download(url: str, name: str, retries: int = 4) -> Path:
    """Download `url` into the media cache as `name` (stable, provider-scoped). Cached forever.
    Backs off on HTTP 429: Pixabay rate-limits its pixabay.com/get/ image links."""
    dest = _cache_dir("media") / name
    if dest.exists() and dest.stat().st_size > 0:
        stats.download_cache_hits += 1
        return dest
    stats.downloads += 1
    tmp = dest.with_suffix(dest.suffix + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=120) as r, tmp.open("wb") as f:
                while chunk := r.read(1 << 20):
                    f.write(chunk)
            tmp.replace(dest)
            return dest
        except urllib.error.HTTPError as e:
            tmp.unlink(missing_ok=True)
            if e.code == 429 and attempt < retries:
                wait = min(int(e.headers.get("Retry-After") or 0) or 2 ** (attempt + 1), 30)
                log.info("download rate-limited (%s); waiting %ss", name, wait)
                time.sleep(wait)
                continue
            raise HTTPError(f"download failed for {name}: HTTP {e.code}", e.code) from None
        except (urllib.error.URLError, TimeoutError) as e:
            tmp.unlink(missing_ok=True)
            raise HTTPError(f"download failed for {name}: {e}") from None
    raise HTTPError(f"download failed for {name}: rate-limited")
