"""Pace of a finished video: cuts per minute, average shot length, how much the picture moves, and how
much of it is dead air or too busy. `klip measure` runs it on reference videos you like and can save
their median as targets; QA compares every render with those targets (informational, never fails).
"""

from __future__ import annotations

import re
import statistics
from pathlib import Path

import yaml

from klip import config, ffmpeg
from klip.paths import ROOT

METRICS = ("cuts_per_min", "beats_per_min", "avg_shot_s", "motion_mean", "dead_share", "busy_share")


def cut_times(video: Path, threshold: float, merge_s: float = 0.5) -> list[float]:
    """Times (s) of cuts: frames whose scene-change score is over `threshold`; a blended transition
    spans several frames, so changes closer than merge_s count once."""
    proc = ffmpeg.run(["-i", str(video), "-an", "-vf", f"select='gt(scene,{threshold})',showinfo",
                       "-f", "null", "-"])
    out: list[float] = []
    for t in (float(m.group(1)) for m in re.finditer(r"pts_time:([\d.]+)", proc.stderr)):
        if not out or t - out[-1] >= merge_s:
            out.append(t)
    return out


def beat_times(cov, fps: float, level: float, gap_s: float) -> list[float]:
    """Times (s) the picture visibly changes (the motion curve rises over `level`), gap_s apart at least:
    cuts, props popping in, camera moves, type landing."""
    out: list[float] = []
    for i in range(1, len(cov)):
        if cov[i] >= level > cov[i - 1] and (not out or i / fps - out[-1] >= gap_s):
            out.append(i / fps)
    return out


def measure(video: Path) -> dict:
    """{duration_s, cuts, cuts_per_min, beats_per_min, avg_shot_s, motion_mean, dead_share, busy_share}."""
    import numpy as np

    from klip.stages.post import motion_curve
    p = config.get("qa.pace")
    q, m = config.get("qa.motion"), config.get("sfx.motion")
    dur = float(ffmpeg.probe(video)["format"]["duration"])
    cuts = cut_times(video, float(p["cut_threshold"]), float(p["merge_s"]))
    cov = motion_curve(video, m)
    fps = float(m["fps"])
    k = max(1, round(q["smooth_s"] * fps))
    s = np.convolve(cov, np.ones(k) / k, mode="same") if len(cov) else cov
    n = max(len(s), 1)
    kb = max(1, round(0.2 * fps))
    beats = beat_times(np.convolve(cov, np.ones(kb) / kb, mode="same") if len(cov) else cov, fps,
                       float(p["beat_level"]), float(p["merge_s"]))
    return {"duration_s": round(dur, 1), "cuts": len(cuts),
            "cuts_per_min": round(len(cuts) / dur * 60, 1) if dur else 0.0,
            "beats_per_min": round(len(beats) / dur * 60, 1) if dur else 0.0,
            "avg_shot_s": round(dur / (len(cuts) + 1), 2),
            "motion_mean": round(float(s.mean()) if len(s) else 0.0, 4),
            "dead_share": round(float((s < q["dead_level"]).sum()) / n, 3),
            "busy_share": round(float((s > q["busy_level"]).sum()) / n, 3)}


def targets() -> dict:
    """{metric: [low, high]}: klip.yaml qa.pace.targets, overridden by the saved reference targets."""
    t = dict(config.get("qa.pace.targets") or {})
    f = ROOT / config.get("qa.pace.targets_file")
    if f.is_file():
        t.update((yaml.safe_load(f.read_text()) or {}).get("targets") or {})
    return {k: v for k, v in t.items() if v}


def from_references(rows: list[dict], spread: float) -> dict:
    """Targets from measured references: the median of each metric, ± spread (a share of the median)."""
    out = {}
    for k in METRICS:
        med = statistics.median(r[k] for r in rows)
        lo, hi = med * (1 - spread), med * (1 + spread)
        nd = 3 if k in ("motion_mean", "dead_share", "busy_share") else 1
        out[k] = [round(lo, nd), round(hi, nd)] if k not in ("dead_share", "busy_share") else [0, round(max(hi, 0.02), 3)]
    return out


def save_targets(rows: list[dict], names: list[str]) -> Path:
    p = config.get("qa.pace")
    f = ROOT / p["targets_file"]
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(yaml.safe_dump({"references": names, "measured": rows,
                                 "targets": from_references(rows, float(p["spread"]))},
                                sort_keys=False, allow_unicode=True), encoding="utf-8")
    return f


def compare(row: dict, tg: dict) -> list[dict]:
    """[{metric, value, low, high, ok}] for the metrics that have a target."""
    return [{"metric": k, "value": row[k], "low": lo, "high": hi, "ok": lo <= row[k] <= hi}
            for k, (lo, hi) in tg.items() if k in row]
