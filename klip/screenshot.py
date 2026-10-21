"""Web page captures for stage `screenshot` elements (renderer/tools/screenshot.mjs + headless Chrome).

A capture is cached by URL, Wayback date, selector and viewport, so re-renders reuse it. `wayback`
captures the Internet Archive's copy from that date instead (the `if_` form: no archive toolbar).
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path
from urllib.parse import urlparse

from klip import config, paths
from klip.paths import RENDERER_DIR

SCRIPT = RENDERER_DIR / "tools" / "screenshot.mjs"


class ScreenshotError(RuntimeError):
    pass


def cfg(key: str):
    return config.get(f"screenshot.{key}")


def target_url(url: str, wayback: str | None) -> str:
    return f"https://web.archive.org/web/{wayback}if_/{url}" if wayback else url


def find_chrome() -> str:
    """screenshot.chrome, else the newest headless Chrome HyperFrames downloaded."""
    if exe := cfg("chrome"):
        return exe
    root = Path.home() / ".cache" / "hyperframes" / "chrome"
    found = sorted(root.glob("**/chrome-headless-shell"), key=lambda p: p.stat().st_mtime, reverse=True)
    found = [p for p in found if p.is_file() and os.access(p, os.X_OK)]
    if not found:
        raise ScreenshotError(f"no headless Chrome under {root}; render one video first (HyperFrames downloads "
                              f"it) or set screenshot.chrome in klip.yaml")
    return str(found[0])


def credit(url: str, wayback: str | None) -> dict:
    host = urlparse(url).netloc
    return {"provider": "screenshot", "id": target_url(url, wayback), "kind": "photo", "duration_s": 0.0,
            "creator": f"{host} (via the Wayback Machine, {wayback})" if wayback else host, "creator_url": "",
            "page_url": target_url(url, wayback), "license": "screenshot", "license_url": "",
            "title": "", "nonfree": False}


def capture(url: str, wayback: str | None = None, selector: str | None = None) -> Path:
    from klip.engines.render.hyperframes import find_node
    w, h = cfg("viewport")
    opts = {"url": target_url(url, wayback), "width": int(w), "height": int(h), "scale": float(cfg("scale")),
            "selector": selector, "wait_ms": int(cfg("wait_ms")), "timeout_ms": int(cfg("timeout_s") * 1000)}
    key = hashlib.sha256(json.dumps(opts, sort_keys=True).encode()).hexdigest()[:20]
    out = paths.CACHE_DIR / "screens" / f"{key}.png"
    if out.exists() and out.stat().st_size:
        return out
    out.parent.mkdir(parents=True, exist_ok=True)
    opts.update(out=str(out), chrome=find_chrome())
    try:
        r = subprocess.run([find_node(), str(SCRIPT), json.dumps(opts)], cwd=RENDERER_DIR, capture_output=True,
                           text=True, timeout=cfg("timeout_s") + 60)
    except subprocess.TimeoutExpired:
        raise ScreenshotError(f"screenshot of {opts['url']} timed out") from None
    if r.returncode or not out.exists():
        out.unlink(missing_ok=True)
        msg = (r.stderr or r.stdout).strip().splitlines()
        raise ScreenshotError(f"screenshot of {opts['url']} failed: {msg[-1] if msg else 'no output'}")
    return out
