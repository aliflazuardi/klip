"""Motion components for stage scenes: geometry and step data for the animated diagrams
(kinetic, split, flow, meter, cycle, timeline, funnel, reel). Pure layout; the templates in
templates/default/scenes/components.*.j2 draw and animate them (klip.yaml stage.components).
"""

from __future__ import annotations

import math
from typing import Callable

from klip import config
from klip.spec import StageElement
from klip.stage import count_up


def cfg(key: str):
    return config.get(f"stage.components.{key}")


def _fmt(v: float) -> str:
    from klip.stages.compose import format_number
    return format_number(v, 0 if abs(v) >= 100 or float(v).is_integer() else 1 if abs(v) >= 10 else 2)


def _count(show: str | None) -> dict | None:
    """Count-up data for a shown value; small whole numbers (0-4) just appear (counting 0→1 reads as a glitch)."""
    c = count_up(show)
    return c if c and (c["value"] >= 5 or c["decimals"]) else None


def _steps(e: StageElement, times: list[float], icon: Callable[[str], str], default_show=None) -> list[dict]:
    out = []
    for k, (st, t) in enumerate(zip(e.steps, times)):
        show = st.show or (default_show(st) if default_show else None)
        out.append({"k": k, "t": t, "text": st.text, "label": st.label, "show": show, "count": _count(show),
                    "accent": st.accent, "value": st.value, "svg": icon(st.name) if st.name else None})
    return out


def _kinetic(e, w, h, steps):
    longest = max(len(s["text"]) for s in steps)
    fs = min(h / (len(steps) * 1.2), w / (max(longest, 4) * 0.68), float(cfg("kinetic.max_px")))
    for s in steps:
        s["words"] = s["text"].split()
    return {"fs": round(fs, 1)}


def _split(e, w, h, steps, palette):
    total = sum(s["value"] for s in steps) or 1
    shares = [max(s["value"] / total * 100, 2.5) for s in steps]
    norm = sum(shares)
    for k, (s, sh) in enumerate(zip(steps, shares)):
        s["pct"] = round(100 * s["value"] / total, 1)
        s["width"] = round(100 * sh / norm, 2)
        s["color"] = "var(--accent)" if s["accent"] else palette[k % len(palette)]
        if not s["show"]:
            s["show"] = (_fmt(s["pct"]) if s["pct"] >= 1 else _fmt(round(s["pct"], 1))) + "%"
            s["count"] = _count(s["show"])
    bar_h = round(h * 0.22, 1)
    return {"bar_h": bar_h, "fs": round(min(w * 0.072, (h - bar_h) / (len(steps) * 1.9 + 1.6)), 1)}


def _bezier_len(p0, p1, p2, p3, n=24) -> float:
    def at(t):
        u = 1 - t
        return (u ** 3 * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t ** 3 * p3[0],
                u ** 3 * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t ** 3 * p3[1])
    pts = [at(i / n) for i in range(n + 1)]
    return sum(math.dist(a, b) for a, b in zip(pts, pts[1:]))


def _flow(e, w, h, steps):
    n = len(steps)
    r = round(min(w / (n * 2.4), h * 0.12), 1)
    sx, sy = w / 2, h * 0.07 + r
    dy = h * 0.66
    top = max(s["value"] for s in steps) or 1
    lo, hi = cfg("flow.min_px"), cfg("flow.max_px")
    for k, s in enumerate(steps):
        dx = w * (k + 0.5) / n
        p0, p3 = (sx, sy + r), (dx, dy - r)
        p1, p2 = (sx, (p0[1] + p3[1]) / 2), (dx, (p0[1] + p3[1]) / 2)
        s.update(x=round(dx, 1), y=round(dy, 1), stroke=round(lo + (hi - lo) * s["value"] / top, 1),
                 path=f"M{p0[0]:.1f},{p0[1]:.1f} C{p1[0]:.1f},{p1[1]:.1f} {p2[0]:.1f},{p2[1]:.1f} {p3[0]:.1f},{p3[1]:.1f}",
                 len=round(_bezier_len(p0, p1, p2, p3) + 2, 1))
        if not s["show"]:
            s["show"] = _fmt(s["value"])
            s["count"] = _count(s["show"])
    return {"r": r, "sx": round(sx, 1), "sy": round(sy, 1), "fs": round(min(r * 0.7, w * 0.062), 1),
            "dash": cfg("flow.dash"), "gap": cfg("flow.gap")}


def _meter(e, w, h, steps):
    """A tube on the right fills level by level; on the left a counter shows each step's value
    (counting up from the previous one) over its caption."""
    tube_w, top, bottom = round(w * 0.22, 1), round(h * 0.03, 1), round(h * 0.97, 1)
    prev = None
    for s in steps:
        s["pct"] = round(100 * s["value"] / e.max, 2)
        s["y"] = round(bottom - (bottom - top) * s["pct"] / 100, 1)
        s["from"] = prev["count"]["value"] if prev and prev["count"] and s["count"] else 0
        prev = s
    longest = max(len(s["show"] or "") for s in steps) or 4
    col = w * 0.66
    return {"tube_w": tube_w, "top": top, "bottom": bottom, "x": round(w - tube_w, 1), "col": round(col, 1),
            "fs": round(min(col / (longest * 0.6), h * 0.2), 1), "small": round(min(w * 0.05, h * 0.06), 1)}


def _cycle(e, w, h, steps):
    n = len(steps)
    cx, cy = w / 2, h / 2
    r_node = min(w, h) * 0.105
    R = min(w, h) / 2 - r_node - min(w, h) * 0.06
    pad = math.asin(min(0.95, r_node * 1.35 / R))
    arcs = []
    for k, s in enumerate(steps):
        a = -math.pi / 2 + 2 * math.pi * k / n
        s.update(x=round(cx + R * math.cos(a), 1), y=round(cy + R * math.sin(a), 1))
        a0, a1 = a + pad, a + 2 * math.pi / n - pad
        p0 = (cx + R * math.cos(a0), cy + R * math.sin(a0))
        p1 = (cx + R * math.cos(a1), cy + R * math.sin(a1))
        tx, ty = -math.sin(a1), math.cos(a1)               # clockwise tangent at the arc's end
        tip = (p1[0] + tx * 12, p1[1] + ty * 12)
        b1 = (p1[0] - tx * 8 + ty * 11, p1[1] - ty * 8 - tx * 11)
        b2 = (p1[0] - tx * 8 - ty * 11, p1[1] - ty * 8 + tx * 11)
        arcs.append({"d": f"M{p0[0]:.1f},{p0[1]:.1f} A{R:.1f},{R:.1f} 0 0,1 {p1[0]:.1f},{p1[1]:.1f}",
                     "len": round(R * (a1 - a0) + 2, 1),
                     "head": " ".join(f"{x:.1f},{y:.1f}" for x, y in (tip, b1, b2))})
    return {"cx": round(cx, 1), "cy": round(cy, 1), "R": round(R, 1), "r": round(r_node, 1), "arcs": arcs,
            "fs": round(min(r_node * 0.62, w * 0.058), 1), "center_fs": round(min(R * 0.26, w * 0.08), 1)}


def _timeline(e, w, h, steps):
    n = len(steps)
    x, top, bottom = round(w * 0.1, 1), h * 0.1, h * 0.9
    for k, s in enumerate(steps):
        s["y"] = round(top + (bottom - top) * (k / (n - 1) if n > 1 else 0.5), 1)
    return {"x": x, "top": round(top, 1), "fs": round(min(w * 0.085, (bottom - top) / n * 0.42), 1)}


def _funnel(e, w, h, steps, palette):
    n = len(steps)
    gap, narrow = h * 0.025, float(cfg("funnel.narrow"))
    lh = (h - gap * (n - 1)) / n
    widths = [1 - (1 - narrow) * k / n for k in range(n + 1)]
    for k, s in enumerate(steps):
        t, b = widths[k], widths[k + 1]
        s.update(y=round(k * (lh + gap), 1), h=round(lh, 1),
                 clip=f"polygon({(1 - t) * 50:.2f}% 0, {(1 + t) * 50:.2f}% 0, {(1 + b) * 50:.2f}% 100%, {(1 - b) * 50:.2f}% 100%)",
                 color="var(--accent)" if s["accent"] else palette[k % len(palette)])
        if not s["show"]:
            s["show"] = _fmt(s["value"])
            s["count"] = _count(s["show"])
    return {"fs": round(min(lh * 0.42, w * 0.085), 1)}


def _reel(e, w, h, steps, start: float):
    n, spins = len(steps), int(cfg("reel.spins"))
    title_h = round(h * 0.17, 1) if e.text else 0.0
    rh = round((h - title_h) / 3, 1)
    land = next(k for k, s in enumerate(steps) if s["accent"])
    strip = [steps[-1]["text"]] + [s["text"] for s in steps] * (spins + 1)
    target = 1 + spins * n + land                     # strip index that ends in the middle row
    spin_from = round(start + 0.25, 3)
    stop = steps[land]["t"] if e.steps[land].at else start + float(cfg("reel.spin_s"))
    return {"title_h": title_h, "rh": rh, "strip": strip, "y_to": round(-(target - 1) * rh, 1), "land": target,
            "from": spin_from, "dur": round(max(stop - spin_from, 1.0), 3), "fs": round(min(rh * 0.42, w * 0.08), 1)}


def build(e: StageElement, w: float, h: float, times: list[float], start: float, end: float,
          icon: Callable[[str], str], accent: str) -> dict:
    """Template data for one motion component in a w×h box (on stage from `start` to `end`): its
    steps (with times) plus geometry, in the coordinates of the card's inner area."""
    palette = [accent if c == "accent" else c for c in cfg("colors")]
    steps = _steps(e, times, icon)
    kind = e.kind
    pad = 0.0 if kind == "kinetic" else round(w * float(cfg("pad")), 1)
    w, h = w - 2 * pad, h - 2 * pad
    geo = {"kinetic": lambda: _kinetic(e, w, h, steps), "split": lambda: _split(e, w, h, steps, palette),
           "flow": lambda: _flow(e, w, h, steps), "meter": lambda: _meter(e, w, h, steps),
           "cycle": lambda: _cycle(e, w, h, steps), "timeline": lambda: _timeline(e, w, h, steps),
           "funnel": lambda: _funnel(e, w, h, steps, palette), "reel": lambda: _reel(e, w, h, steps, start)}[kind]()
    for s in steps:
        if s.get("color") == "var(--accent)":
            s["color"] = accent
    return {"kind": kind, "steps": steps, "title": e.text, "svg": icon(e.name) if e.name else None, "pad": pad,
            "iw": round(w, 1), "ih": round(h, 1), "end": round(end, 3), "accent": accent,
            "run": round(max(end - (steps[-1]["t"] if steps else start), 0.1), 3), **geo}
