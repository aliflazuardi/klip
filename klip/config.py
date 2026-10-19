"""Settings from klip.yaml (the single config file). Secrets come from .env, not here.

klip.local.yaml (gitignored), if present, is deep-merged over klip.yaml for personal overrides.
Brand packs (brands/<name>/brand.yaml) add styles on top of the ones in klip.yaml.
"""

from __future__ import annotations

import copy
import os
from functools import cache
from pathlib import Path
from typing import Any

import yaml

from klip.paths import ROOT


def config_path() -> Path:
    return Path(os.environ.get("KLIP_CONFIG", ROOT / "klip.yaml"))


def local_path() -> Path:
    return Path(os.environ.get("KLIP_LOCAL_CONFIG", ROOT / "klip.local.yaml"))


def _read(path: Path) -> dict:
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


@cache
def load() -> dict:
    data = _read(config_path())
    local = local_path()
    return _merge(data, _read(local)) if local.is_file() else data


def get(path: str, default: Any = None) -> Any:
    """Dotted lookup, e.g. get("qa.max_still_s")."""
    node: Any = load()
    for key in path.split("."):
        if not isinstance(node, dict) or key not in node:
            return default
        node = node[key]
    return node


def voice_id(voice: str, engine: str | None = None) -> str:
    engine = engine or get("voices.engine", "edge")
    vid = get(f"voices.ids.{engine}", {}).get(voice)
    if not vid:
        raise KeyError(f"no voice {voice!r} for engine {engine!r} in klip.yaml (voices.ids)")
    return vid


def default_rate(voice: str) -> str:
    return get("voices.default_rate", {}).get(voice, "+0%")


@cache
def lexicon() -> dict[str, str]:
    return {str(k): str(v) for k, v in (get("lexicon") or {}).items()}


def _merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in over.items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def brands_dir() -> Path:
    return ROOT / get("brands.dir", "brands")  # an absolute path stays absolute


# Style keys holding image paths; in a brand pack they're relative to the pack's folder.
_BRAND_FILES = (("watermark", "file"), ("end_card", "logo"), ("end_card", "wordmark"))


def _brand_style(pack: Path) -> dict:
    data = _read(pack / "brand.yaml")
    st = copy.deepcopy(data.get("style") or {})
    for section, key in _BRAND_FILES:
        node = st.get(section)
        if isinstance(node, dict) and node.get(key):
            node[key] = str((pack / node[key]).resolve())
    return st


@cache
def styles() -> dict[str, dict]:
    """Unmerged styles: klip.yaml's, then one per brand pack (a pack can't shadow `default`)."""
    out = dict(get("styles", {}))
    d = brands_dir()
    if d.is_dir():
        for pack in sorted(p for p in d.iterdir() if (p / "brand.yaml").is_file()):
            if pack.name != "default":
                out[pack.name] = _brand_style(pack)
    return out


@cache
def style(name: str = "default") -> dict:
    all_styles = styles()
    if name not in all_styles:
        raise KeyError(f"unknown style {name!r}; available: {', '.join(all_styles)} "
                       f"(klip.yaml styles or {brands_dir()}/<name>/brand.yaml)")
    return all_styles["default"] if name == "default" else _merge(all_styles["default"], all_styles[name] or {})
