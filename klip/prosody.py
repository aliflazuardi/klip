"""Per-scene delivery: rate/pitch/volume presets layered on the voice's base rate."""

from __future__ import annotations

import re
from dataclasses import dataclass

from klip import config
from klip.spec import Scene

NEUTRAL = {"rate": "+0%", "pitch": "+0Hz", "volume": "+0%"}


@dataclass(frozen=True)
class Prosody:
    delivery: str
    rate: str
    pitch: str
    volume: str


def _pct(value: str) -> int:
    m = re.fullmatch(r"([+-]?\d+)%", value.strip())
    if not m:
        raise ValueError(f"bad percentage {value!r} (expected e.g. '+6%')")
    return int(m.group(1))


def combine_rate(base: str, delta: str) -> str:
    """'+15%' + '+6%' → '+21%' (edge-tts rates are relative to the voice's normal speed)."""
    return f"{_pct(base) + _pct(delta):+d}%"


def delivery_name(scene: Scene) -> str:
    if scene.delivery:
        return scene.delivery
    if not config.get("prosody.enabled", True):
        return "neutral"
    return (config.get("prosody.by_template", {}) or {}).get(scene.template) or config.get("prosody.default", "neutral")


def for_scene(scene: Scene, base_rate: str) -> Prosody:
    name = delivery_name(scene)
    preset = {**NEUTRAL, **((config.get("prosody.presets", {}) or {}).get(name) or {})}
    return Prosody(name, combine_rate(base_rate, preset["rate"]), preset["pitch"], preset["volume"])
