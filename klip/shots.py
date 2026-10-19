"""Shot planning: split a scene into ~2.5 s shots, cutting on word boundaries.

Fast-paced short-form cuts every ~1.5–3 s. A cut lands on the start of a word (preferably
right after punctuation, where the voice pauses) so picture changes ride the speech rhythm.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from klip import config

_PUNCT = re.compile(r"[.,!?;:…]$")
PAUSE_BONUS_MS = 600   # how far we'll move a cut to land it after punctuation (mid-phrase cuts jar)


@dataclass
class Shot:
    start_ms: float
    end_ms: float

    @property
    def dur_ms(self) -> float:
        return self.end_ms - self.start_ms


def settings() -> dict:
    c = config.get("cuts", {}) or {}
    return {"target_ms": float(c.get("target_shot_s", 2.5)) * 1000,
            "min_ms": float(c.get("min_shot_s", 1.4)) * 1000,
            "max_shots": int(c.get("max_shots_per_scene", 4))}


def shot_count(dur_ms: float, target_ms: float, max_shots: int, cap: int | None = None) -> int:
    n = max(1, min(round(dur_ms / target_ms), max_shots))
    return max(1, min(n, cap)) if cap else n


def plan(start_ms: float, dur_ms: float, words: list[dict], target_ms: float = 2500, min_ms: float = 1400,
         max_shots: int = 4, cap: int | None = None) -> list[Shot]:
    """Shots covering [start, start+dur). `words` are this scene's {text, startMs} (absolute ms).
    `cap` limits the count (e.g. visual.max_shots)."""
    end_ms = start_ms + dur_ms
    n = shot_count(dur_ms, target_ms, max_shots, cap)
    if n == 1 or len(words) < 2:
        return [Shot(start_ms, end_ms)]

    # candidate cut points: starts of words 2..n, with a bonus after punctuation
    cands = [(w["startMs"], bool(_PUNCT.search(words[i - 1]["text"].strip())))
             for i, w in enumerate(words) if i > 0]
    cuts: list[float] = []
    for k in range(1, n):
        ideal = start_ms + dur_ms * k / n
        best = min(cands, key=lambda c: abs(c[0] - ideal) - (PAUSE_BONUS_MS if c[1] else 0))
        t = best[0]
        prev = cuts[-1] if cuts else start_ms
        if t - prev >= min_ms and end_ms - t >= min_ms and t not in cuts:
            cuts.append(t)
    bounds = [start_ms, *cuts, end_ms]
    return [Shot(a, b) for a, b in zip(bounds, bounds[1:])]


def anchor_times(words: list[dict], anchors: list[str]) -> list[float | None]:
    """Start (ms) of each anchor word, searched in order after the previous anchor; None if absent.
    A phrase anchors on its first word."""
    from klip.captions import norm
    out: list[float | None] = []
    i = 0
    for a in anchors:
        target = norm(a.split()[0]) if a.split() else ""
        hit = next((j for j in range(i, len(words)) if target and norm(words[j]["text"]) == target), None)
        if hit is None:
            out.append(None)
            continue
        out.append(words[hit]["startMs"])
        i = hit + 1
    return out


def plan_beats(start_ms: float, dur_ms: float, words: list[dict], anchors: list[str],
               min_ms: float = 1400) -> list[tuple[Shot, int]]:
    """Shots cut on beat anchors: (shot, beat index), beat 0 = the scene's first shot. A beat whose
    anchor is missing or would leave a shot shorter than `min_ms` is dropped (the previous shot runs on)."""
    end_ms = start_ms + dur_ms
    cuts: list[tuple[float, int]] = []
    for k, t in enumerate(anchor_times(words, anchors), 1):
        prev = cuts[-1][0] if cuts else start_ms
        if t is not None and t - prev >= min_ms and end_ms - t >= min_ms:
            cuts.append((t, k))
    bounds = [(start_ms, 0), *cuts, (end_ms, -1)]
    return [(Shot(a, b), k) for (a, k), (b, _) in zip(bounds, bounds[1:])]
