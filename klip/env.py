"""Minimal .env loader (KEY=VALUE lines). Existing environment variables win."""

from __future__ import annotations

import os

from klip.paths import ROOT

_loaded = False


def load_dotenv(path=None) -> None:
    global _loaded
    if _loaded and path is None:
        return
    path = path or ROOT / ".env"
    _loaded = True
    try:
        lines = open(path, encoding="utf-8").read().splitlines()
    except FileNotFoundError:
        return
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip().removeprefix("export ").strip(), value.strip().strip("'\"")
        if value:
            os.environ.setdefault(key, value)


def get(name: str) -> str | None:
    load_dotenv()
    return os.environ.get(name) or None
