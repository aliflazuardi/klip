"""Stage scenes: a collage that builds up on a persistent background (visual.type "stage").

Pure layout and timing: which slot and size each element gets, when it enters and leaves, and the
background texture CSS. compose.py turns this into template context; assets.py prepares the
cut-out and photo files.
"""

from __future__ import annotations

import hashlib
import re
from urllib.parse import quote

from markupsafe import Markup

from klip import config, shots
from klip.spec import COMPONENTS, MEDIA, StageElement, Visual

BUILTIN_BACKGROUNDS = ("desk", "paper", "kraft", "board")
PHOTO_FRAME = (14, 14, 14, 54)      # photo card white frame: left, top, right, bottom (px)
SAFE_X = (60, 960)                  # TikTok safe zone (right-side buttons beyond x 960)


def cfg(key: str):
    return config.get(f"stage.{key}")


MEDIA_KINDS = MEDIA                                     # an image from stock, Wikipedia or a file


def is_media(e: StageElement) -> bool:
    return e.kind in MEDIA_KINDS


def needs_row(e: StageElement) -> bool:
    """Elements that need something from the assets stage (a file or chart data)."""
    return is_media(e) or e.kind == "screenshot" or (e.kind == "chart" and not e.points)


def background_key(v: Visual) -> str:
    """The scene's set: a built-in name, an image path, or `bd-<hash>` for a backdrop (equal
    backdrops share a key, so consecutive scenes on one carry the set across the cut)."""
    if v.backdrop:
        return "bd-" + hashlib.sha256(v.backdrop.model_dump_json().encode()).hexdigest()[:10]
    return v.background or cfg("default_background")


def backdrop_settings(v: Visual) -> dict:
    """A backdrop's look: klip.yaml stage.backdrop.<kind>, with the spec's dim/blur/tone on top."""
    b = v.backdrop
    d = dict(cfg(f"backdrop.{b.kind}") or {})
    for k in ("dim", "blur", "tone"):
        if getattr(b, k) is not None:
            d[k] = getattr(b, k)
    return d


def backdrop_needs_file(v: Visual) -> bool:
    return bool(v.backdrop) and v.backdrop.kind in ("photo", "screenshot")


_SIGNED = re.compile(r"(^|\s)([+\-−])\s?\d")


def board_rows(items: list[str], cols: int, n_rows: int, offset: int = 0) -> list[list[dict]]:
    """Cells for a board backdrop: the items repeated row by row (shifted per row so columns don't
    line up into stripes), each coloured by the sign of its number."""
    out = []
    for r in range(n_rows):
        k = offset + r * (cols + 1) + r * r              # a growing skip, so rows rarely line up
        row = []
        for c in range(cols):
            text = items[(k + c) % len(items)]
            m = _SIGNED.search(text)
            row.append({"text": text, "tone": "neutral" if not m else ("up" if m.group(2) == "+" else "down")})
        out.append(row)
    return out


def is_builtin(bg: str) -> bool:
    return bg in (cfg("backgrounds") or {})


def _noise_svg(freq: str, octaves: int = 3) -> str:
    svg = ("<svg xmlns='http://www.w3.org/2000/svg' width='1200' height='2040'>"
           "<filter id='n'><feTurbulence type='fractalNoise' baseFrequency='" + freq + "' "
           f"numOctaves='{octaves}' seed='7' stitchTiles='stitch'/>"
           "<feColorMatrix values='0 0 0 0 0  0 0 0 0 0  0 0 0 0 0  1.5 0 0 0 -0.45'/></filter>"
           "<rect width='100%' height='100%' filter='url(#n)'/></svg>")
    return "data:image/svg+xml," + quote(svg)


def tone(bg: str, v: Visual | None = None) -> str:
    """'light' or 'dark' surface: picks title, tag and shadow colours (image backgrounds count as dark)."""
    if v is not None and v.backdrop:
        return backdrop_settings(v).get("tone", "dark")
    return (cfg("backgrounds").get(bg) or {}).get("tone", "dark")


def background_css(bg: str) -> Markup:
    """CSS declarations for a built-in set (the image-file case is handled by compose)."""
    b = cfg("backgrounds")[bg]
    layers = [(f"radial-gradient(ellipse at 50% 42%, rgba(0,0,0,0) 45%, rgba(0,0,0,{b['vignette']}) 100%)", "100% 100%")]
    if spot := b.get("spot"):
        layers.append((f"radial-gradient(ellipse {spot['size']} at {spot['at']}, {spot['color']}, rgba(0,0,0,0) 100%)",
                       "100% 100%"))
    if dots := b.get("dots"):
        layers.append((f"radial-gradient(circle, {dots['color']} {dots['size']}px, rgba(0,0,0,0) {dots['size'] + 0.6}px)",
                       f"{dots['gap']}px {dots['gap']}px"))
    if floor := b.get("floor"):
        at = round(float(floor["at"]) * 100, 1)
        layers.append((f"linear-gradient(180deg, rgba(0,0,0,0) {at - 6}%, rgba(0,0,0,.10) {at - 0.4}%, "
                       f"rgba(0,0,0,.22) {at}%, {floor['color']} {at}%, {floor['color']} 100%)", "100% 100%"))
    if b.get("planks"):
        p = int(b["planks"])
        layers.append((f"repeating-linear-gradient(90deg, rgba(0,0,0,0) 0 {p - 5}px, rgba(0,0,0,.28) {p - 5}px "
                       f"{p - 2}px, rgba(255,255,255,.08) {p - 2}px {p}px)", "auto"))
    css = (f"background-color: {b['base']}; background-image: {', '.join(i for i, _ in layers)}; "
           f"background-size: {', '.join(z for _, z in layers)};")
    return Markup(css)


def grain_css(bg: str) -> Markup:
    b = cfg("backgrounds")[bg]
    return Markup(f"background-image: url(\"{_noise_svg(b['grain_freq'])}\"); opacity: {b['grain']};")


# ---- timing

def entry_times(elements: list[StageElement], words: list[dict], start_ms: float, dur_ms: float,
                warnings: list[str], scene_id: str) -> list[float]:
    """Entry time (s) of each element: on its anchor word (minus lead_s), kept in order and at least
    min_gap_s apart. A missing anchor is placed between its neighbours (with a warning)."""
    lead, gap = float(cfg("lead_s")), float(cfg("min_gap_s"))
    start, end = start_ms / 1000, (start_ms + dur_ms) / 1000
    raw = shots.anchor_times(words, [e.at for e in elements])
    for e, t in zip(elements, raw):
        if t is None:
            warnings.append(f"{scene_id}: stage element at {e.at!r} not found in the spoken words; placed in between")
    known = [(i, t / 1000) for i, t in enumerate(raw) if t is not None]
    out: list[float] = []
    for i, t in enumerate(raw):
        if t is not None:
            v = t / 1000 - lead
        else:   # interpolate between the nearest known anchors (or the scene edges)
            before = next(((j, x) for j, x in reversed(known) if j < i), (-1, start))
            after = next(((j, x) for j, x in known if j > i), (len(raw), end - 0.4))
            v = before[1] + (after[1] - before[1]) * (i - before[0]) / (after[0] - before[0])
        v = max(v, start + 0.05, (out[-1] + gap) if out else 0)
        out.append(round(min(v, end - 0.3), 3))
    return out


def pages(elements: list[StageElement]) -> list[list[int]]:
    """Element indexes per stage 'page' (a clear starts a new one)."""
    out: list[list[int]] = [[]]
    for i, e in enumerate(elements):
        if e.clear and out[-1]:
            out.append([])
        out[-1].append(i)
    return out


def step_times(e: StageElement, start: float, end: float, words: list[dict]) -> list[float]:
    """When each step of a motion component plays (s): on its `at` word, searched after the element's
    own word; a step without one (or not found) comes stage.components.step_gap_s after the previous.
    Kept in order, at least min_step_s apart, and before `end`."""
    c = cfg("components")
    gap, min_gap = float(c["step_gap_s"]), float(c["min_step_s"])
    after = [w for w in words if w["startMs"] / 1000 >= start - 0.01]
    want = [(i, st.at) for i, st in enumerate(e.steps) if st.at]
    found = dict(zip((i for i, _ in want), shots.anchor_times(after, [a for _, a in want])))
    out: list[float] = []
    for i in range(len(e.steps)):
        t = found.get(i)
        prev = out[-1] if out else start + float(c["first_step_s"]) - gap
        v = t / 1000 - float(cfg("lead_s")) if t is not None else prev + gap
        v = max(v, prev + min_gap if out else start + 0.05)
        out.append(round(min(v, end - 0.2), 3))
    return out


# ---- layout

def tilt(scene_id: str, i: int, kind: str) -> float:
    h = int(hashlib.sha256(f"{scene_id}:{i}".encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
    damp = {"number": 0.5, "label": 0.6, "bar": 0.3, "highlight": 0.0, "stamp": 0.0, "chart": 0.0, "unit": 0.0,
            "news": 0.3, "notif": 0.0, "screenshot": 0.2, "person": 0.5, "logo": 0.4,
            **{k: 0.0 for k in COMPONENTS}}.get(kind, 1.0)
    if kind == "stamp":
        return -7.0 if h < 0.5 else 6.0
    return round((h * 2 - 1) * float(cfg("tilt_deg")) * damp, 2)


BIG = ("cutout", "photo", "bar", "chart", "unit", "person", "news", "notif", "logo", "screenshot", *COMPONENTS)   # can be a hero


def composition(elements: list[StageElement], placed: list[int]) -> str:
    """Composition name for the props sharing one stage page (see klip.yaml stage.compositions)."""
    kinds = [elements[i].kind for i in placed]
    n = len(kinds)
    if n <= 1:
        return "hero"
    big = sum(k in BIG for k in kinds)
    if n == 2:
        return "hero_tag" if big == 1 else "pair"
    if n == 3:
        return "hero_two" if big == 1 else "trio"
    return "grid4" if n == 4 else "scatter5" if n == 5 else "scatter6"


def assign_places(elements: list[StageElement], page: list[int]) -> dict[int, tuple[float, float, str, str]]:
    """(x share, y share, size, slot) per element on one page: explicit `pos` first, the rest from the
    page's composition, in order. A `pos` takes the composition place nearest to it out of the pool."""
    placed = [i for i in page if elements[i].kind != "highlight"]
    if placed and all(elements[i].kind == "notif" for i in placed):     # notifications stack down the screen
        n = len(placed)
        return {i: (0.5, (k + 0.5) / n, "l", _slot(0.5, (k + 0.5) / n)) for k, i in enumerate(placed)}
    places = [tuple(p) for p in cfg("compositions")[composition(elements, placed)]]
    placed.sort(key=lambda i: elements[i].kind not in BIG)      # the one big prop takes the hero place
    cols, rows = cfg("columns"), cfg("rows")
    out: dict[int, tuple[float, float, str, str]] = {}
    for i in placed:
        if pos := elements[i].pos:
            x, y = (float(cols[pos[1]]) - SAFE_X[0]) / (SAFE_X[1] - SAFE_X[0]), float(rows[pos[0]])
            near = min(places, key=lambda p: (p[0] - x) ** 2 + (p[1] - y) ** 2)
            places.remove(near)
            out[i] = (x, y, near[2], pos)
    for i in placed:
        if i not in out:
            x, y, size = places.pop(0)
            out[i] = (float(x), float(y), str(size), _slot(float(x), float(y)))
    return out


def _slot(x: float, y: float) -> str:
    """Nearest t/m/b + l/c/r slot name for a place (drives the entrance direction)."""
    return ("t" if y < 0.34 else "m" if y < 0.67 else "b") + ("l" if x < 0.4 else "r" if x > 0.6 else "c")


def box_size(e: StageElement, size: str, media: dict | None) -> tuple[float, float]:
    """(w, h) of an element's box in px."""
    bw, bh = cfg("sizes")[size]
    if e.kind in COMPONENTS:                   # a component spans the width its size allows
        c = cfg("components")
        w = float(c["width"][size])
        return w, w * float(c[e.kind]["aspect"])
    if e.kind == "chart":
        return bw, bw * float(cfg("chart.aspect"))
    if e.kind == "unit":
        d = min(bw, bh)
        return d, d * 0.86 + (60 if e.text else 0)
    if e.kind == "person":                      # portrait cards run taller than the size box
        a, h = float(cfg("person.aspect")), bh * float(cfg("person.grow"))
        return min(bw, h / a), min(bw, h / a) * a
    if e.kind == "news":
        return bw, bw * float(cfg("news.aspect"))
    if e.kind == "notif":                       # a phone notification spans the screen's width
        w = float(cfg("components.width")["l"])
        return w, w * float(cfg("notif.aspect")) * (1.0 if e.stat else 0.62)    # no amount: a short card
    if e.kind == "logo":
        iw, ih = (media or {}).get("w") or 2, (media or {}).get("h") or 1
        s = min(bw * 0.8 / iw, bh * 0.45 / ih)
        pad = bw * 0.8 * float(cfg("logo.pad"))
        return iw * s + 2 * pad, ih * s + 2 * pad
    if e.kind == "screenshot":
        iw, ih = (media or {}).get("w") or 1, (media or {}).get("h") or 1
        bar = float(cfg("screenshot.bar_px"))
        s = min(bw / iw, (bh - bar) / ih)
        return iw * s, ih * s + bar
    if e.kind in ("cutout", "photo"):
        g = float(cfg("photos.grow"))              # real photos are the heroes: a bigger box
        bw, bh = bw * g, bh * g
        iw, ih = (media or {}).get("w") or 1, (media or {}).get("h") or 1
        fl, ft, fr, fb = PHOTO_FRAME if media and media.get("render") == "photo" else (0, 0, 0, 0)
        s = min((bw - fl - fr) / iw, (bh - ft - fb) / ih)
        return iw * s + fl + fr, ih * s + ft + fb
    if e.kind == "icon":
        d = cfg("icon_px")[size]
        return d, d
    if e.kind == "number":
        f = cfg("number_px")[size]
        return len(e.text) * 0.62 * f + 30, f * 1.15
    if e.kind == "label":
        f = cfg("label_px")[size]
        return len(e.text) * (0.78 if cfg("label.uppercase") else 0.6) * f + 56, f * 1.65
    if e.kind == "stamp":
        f = cfg("stamp_px")[size]
        return len(e.text) * 0.74 * f + 2.4 * f, f * 1.9
    if e.kind == "stack":
        d = cfg("icon_px")[size] * 0.62
        n = e.count or int(cfg("stack_count"))
        return d * 1.25, d + d * 0.42 * (n - 1)
    return bw, bh                                   # bar


def fit(x: float, y: float, w: float, h: float, top: float, bottom: float) -> tuple[float, float, float, float]:
    """Shrink a box to fit the stage area, then shift it inside."""
    s = min(1.0, (SAFE_X[1] - SAFE_X[0]) / w, (bottom - top) / h)
    w, h = w * s, h * s
    x = min(max(x, SAFE_X[0] + w / 2), SAFE_X[1] - w / 2)
    y = min(max(y, top + h / 2), bottom - h / 2)
    return x, y, w, h


def separate(boxes: dict[int, dict], below: dict[int, float], top: float, bottom: float) -> None:
    """Push overlapping boxes apart (in place) along the axis that overlaps least, keeping them in the
    stage area; if some still overlap after that, shrink the bigger box of each such pair and try again.
    `below`: extra px a box needs under it (its hanging label tag)."""
    from itertools import combinations
    gap, keys = float(cfg("layout_gap_px")), sorted(boxes)

    def clamp(b: dict) -> None:
        w, h = b["w"], b["h"] + below.get(b["_i"], 0)
        b["x"] = min(max(b["x"], SAFE_X[0] + w / 2), SAFE_X[1] - w / 2)
        b["y"] = min(max(b["y"], top + b["h"] / 2), bottom - h + b["h"] / 2)

    def overlap(a: dict, b: dict) -> tuple[float, float]:
        ay, by = a["y"] + below.get(a["_i"], 0) / 2, b["y"] + below.get(b["_i"], 0) / 2
        ah, bh = a["h"] + below.get(a["_i"], 0), b["h"] + below.get(b["_i"], 0)
        return (a["w"] + b["w"]) / 2 + gap - abs(a["x"] - b["x"]), (ah + bh) / 2 + gap - abs(ay - by)

    for i in keys:
        boxes[i]["_i"] = i
    for _ in range(8):
        for _ in range(40):
            moved = False
            for i, j in combinations(keys, 2):
                a, b = boxes[i], boxes[j]
                ox, oy = overlap(a, b)
                if ox <= 0 or oy <= 0:
                    continue
                moved = True
                axis, d = ("x", ox) if ox < oy else ("y", oy)
                sign = 1.0 if a[axis] > b[axis] or (a[axis] == b[axis] and i > j) else -1.0
                a[axis] += sign * d / 2
                b[axis] -= sign * d / 2
                clamp(a)
                clamp(b)
            if not moved:
                break
        clashes = [(i, j) for i, j in combinations(keys, 2) if min(overlap(boxes[i], boxes[j])) > 0]
        if not clashes:
            break
        # shrink the bigger box of each clashing pair (a photo gives way before a tag's text does)
        for i in {max(pair, key=lambda k: boxes[k]["w"] * boxes[k]["h"]) for pair in clashes}:
            boxes[i]["w"] *= 0.88
            boxes[i]["h"] *= 0.88
            clamp(boxes[i])
    for i in keys:
        boxes[i].pop("_i")


def layout(scene_id: str, elements: list[StageElement], media: dict[int, dict],
           area: tuple[float, float]) -> dict[int, dict]:
    """Box (x, y = centre; w, h; rot; size; slot) per element, highlights boxing their target."""
    top, bottom = area
    out: dict[int, dict] = {}
    for page in pages(elements):
        for i, (px, py, size, slot) in assign_places(elements, page).items():
            e = elements[i]
            size = e.size or size
            w, h = box_size(e, size, media.get(i))
            cx, cy = SAFE_X[0] + px * (SAFE_X[1] - SAFE_X[0]), top + py * (bottom - top)
            x, y, w, h = fit(cx, cy, w, h, top, bottom)
            out[i] = {"x": x, "y": y, "w": w, "h": h, "rot": tilt(scene_id, i, e.kind), "size": size, "slot": slot}
        # stamps slap over what they judge; everything else gets its own space
        solid = [i for i in page if i in out and elements[i].kind != "stamp"]
        below = {i: float(cfg("label_px")["s" if out[i]["size"] == "s" else "m"]) * 0.9
                 for i in solid if elements[i].label}
        separate({i: out[i] for i in solid}, below, top, bottom)
        for i in page:
            e = elements[i]
            if e.kind == "highlight" and (tb := out.get(e.target - 1)):
                pad = float(cfg("highlight.pad"))
                out[i] = {**tb, "w": tb["w"] + 2 * pad, "h": tb["h"] + 2 * pad, "size": tb["size"], "slot": tb["slot"]}
    return {i: {k: round(v, 1) if isinstance(v, float) else v for k, v in b.items()} for i, b in out.items()}


# ---- real-data elements

MONTHS_ID = ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des"]
_ISO = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")


def x_label(x: str, span_days: float | None) -> str:
    """'2024-10-16' → '2024' over long spans, '16 Okt' over short ones; other labels as they are."""
    m = _ISO.match(x)
    if not m:
        return x
    y, mo, d = (int(g) for g in m.groups())
    return str(y) if span_days is None or span_days > 400 else f"{d} {MONTHS_ID[mo - 1]}"


def _span_days(a: str, b: str) -> float | None:
    from datetime import date
    ma, mb = _ISO.match(a), _ISO.match(b)
    if not (ma and mb):
        return None
    return abs((date(*map(int, mb.groups())) - date(*map(int, ma.groups()))).days)


def fmt_value(v: float, ref: float) -> str:
    """Indonesian number format, decimals only for small values (5.134 / 12,5 / 0,85)."""
    from klip.stages.compose import format_number
    return format_number(v, 0 if abs(ref) >= 100 else 1 if abs(ref) >= 10 else 2)


def chart_geometry(points: list, bands: list, w: float, h: float, tone: str, has_title: bool) -> dict:
    """SVG geometry for a line chart in a w×h px card: line/area paths, the line's length (for the
    draw-on), shaded bands, axis labels and the last value."""
    xs = [str(p[0]) for p in points]
    ys = [float(p[1]) for p in points]
    pad_l, pad_r = w * 0.05, w * 0.05
    top = h * (0.2 if has_title else 0.1)
    bottom = h - h * 0.17
    lo, hi = min(ys), max(ys)
    rng = (hi - lo) or abs(hi) or 1.0
    lo, hi = lo - rng * 0.08, hi + rng * 0.12
    n = len(ys)

    def px(i: int) -> float:
        return pad_l + (w - pad_l - pad_r) * i / (n - 1)

    def py(v: float) -> float:
        return bottom - (bottom - top) * (v - lo) / (hi - lo)

    pts = [(round(px(i), 1), round(py(v), 1)) for i, v in enumerate(ys)]
    line = "M" + " L".join(f"{x},{y}" for x, y in pts)
    area = f"{line} L{pts[-1][0]},{bottom} L{pts[0][0]},{bottom} Z"
    length = sum(((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5 for (x1, y1), (x2, y2) in zip(pts, pts[1:]))
    if tone == "neutral":
        tone = "up" if ys[-1] > ys[0] else "down" if ys[-1] < ys[0] else "neutral"
    out_bands = []
    for k, b in enumerate(bands):
        idx = [i for i, x in enumerate(xs) if b["start"] <= x <= b["end"]]
        if not idx:
            continue
        x0 = px(idx[0]) if idx[0] > 0 else pad_l
        x1 = px(min(idx[-1] + 1, n - 1))           # a band runs until the next point
        out_bands.append({"x": round(x0, 1), "w": round(max(x1 - x0, 2), 1), "label": b.get("label"), "k": k})
    span = _span_days(xs[0], xs[-1])
    return {"line": line, "area": area, "len": round(length + 2, 1), "top": round(top, 1), "bottom": round(bottom, 1),
            "tone": tone, "bands": out_bands, "x0": x_label(xs[0], span), "x1": x_label(xs[-1], span),
            "last": {"x": pts[-1][0], "y": pts[-1][1], "text": fmt_value(ys[-1], max(abs(v) for v in ys))},
            "first_text": fmt_value(ys[0], max(abs(v) for v in ys))}


def unit_grid(total: int, filled: int, w: float, h: float) -> dict:
    """Square size and columns for a waffle of `total` squares in a w×h px box."""
    import math
    best = None
    for cols in range(1, total + 1):
        rows = math.ceil(total / cols)
        cell = min(w / cols, h / rows)
        if not best or cell > best[0]:
            best = (cell, cols, rows)
    cell, cols, rows = best
    return {"cell": round(cell, 2), "cols": cols, "rows": rows, "total": total, "filled": filled,
            "gw": round(cell * cols, 1), "gh": round(cell * rows, 1)}


# ---- motion (after compose has linked the stage scenes, so every exit time is known)

FLOAT_GROUP = {"cutout": "media", "photo": "media", "person": "media", "logo": "media", "icon": "icon", "stack": "icon",
               "label": "tag", "number": "tag", "news": "data", "notif": "data", "screenshot": "data", "chart": "data",
               "bar": "data", "unit": "data", **{k: "data" for k in COMPONENTS}}
_COUNT = re.compile(r"^([^\d]*?)(\d{1,3}(?:\.\d{3})+|\d+)(?:,(\d+))?([^\d]*)$")


def _h(*parts) -> float:
    """Deterministic 0-1 from the parts (same spec → same motion)."""
    return int(hashlib.sha256(":".join(map(str, parts)).encode()).hexdigest()[:8], 16) / 0xFFFFFFFF


def count_up(text: str | None) -> dict | None:
    """'Rp12.000' → {prefix 'Rp', value 12000, decimals 0, suffix ''}; None when it isn't one number."""
    m = _COUNT.match((text or "").strip())
    if not m:
        return None
    pre, whole, frac, suf = m.groups()
    value = float(whole.replace(".", "") + (f".{frac}" if frac else ""))
    if value == 0 or (not pre.strip() and not suf.strip() and len(whole) == 4 and 1800 <= value <= 2100):
        return None                                 # nothing to count, or a year
    return {"prefix": pre, "value": value, "decimals": len(frac or ""), "suffix": suf}


def _float(e: dict, scene_id: str, end: float, m: dict) -> dict | None:
    """An idle sway for a prop that has landed: y and rotation ease back and forth (an odd number of
    half cycles, so it ends where it started) until its exit or the scene's end."""
    amp = (m["float_px"] or {}).get(FLOAT_GROUP.get(e["kind"], ""), 0)
    if not amp:
        return None
    lo, hi = m["float_period_s"]
    half = round((lo + (hi - lo) * _h(scene_id, e["i"], "p")) / 2, 3)
    t0 = round(e["start"] + m["settle_s"], 3)
    n = int((end - t0) / half)
    if n % 2 == 0:
        n -= 1
    if n < 1:
        return None
    sign = 1 if _h(scene_id, e["i"], "s") < 0.5 else -1
    deg = float(m["float_deg"]) * (1 if FLOAT_GROUP[e["kind"]] in ("media", "icon") else 0.4)
    return {"t": t0, "half": half, "repeat": n - 1, "y": -amp * sign, "rot": round(deg * sign, 2)}


def _camera(st: dict, end: float, m: dict) -> list[dict]:
    """Camera moves (x, y and when/how long) for a stage scene: on each prop's entry the camera eases
    part of the way toward the props on stage (the newest counts double). The push-in (stage.zoom)
    is a separate linear tween on the same layer."""
    top, bottom = st["area"]
    cx, cy, follow = 540.0, (top + bottom) / 2, float(m["camera_follow"])
    els = sorted((e for e in st["elements"] if e["kind"] not in ("highlight", "stamp")), key=lambda e: e["start"])
    moves = []
    for k, e in enumerate(els):
        t = e["start"]
        on = [x for x in els if x["start"] <= t and (x["exit"] is None or x["exit"] > t)]
        wts = [x["w"] * x["h"] * (2 if x is e else 1) for x in on]
        fx = sum(x["x"] * w for x, w in zip(on, wts)) / sum(wts)
        fy = sum(x["y"] * w for x, w in zip(on, wts)) / sum(wts)
        nxt = els[k + 1]["start"] if k + 1 < len(els) else end
        moves.append({"t": round(t, 3), "dur": round(max(min(float(m["camera_move_s"]), nxt - t), 0.05), 3),
                      "x": round((cx - fx) * follow, 1), "y": round((cy - fy) * follow, 1)})
    return moves


def add_motion(scene: dict) -> None:
    """Fill in the motion of a stage scene's context: idle float, count-ups, entrance and exit
    styles, camera keyframes (klip.yaml stage.motion)."""
    st, m = scene["stage"], cfg("motion")
    for e in st["elements"]:
        end = e["exit"] if e["exit"] is not None else scene["end"]
        e["float"] = _float(e, scene["id"], end, m)
        e["count"] = count_up(e.get("text")) if e["kind"] == "number" and m["count_up"] else None
        r = _h(scene["id"], e["i"], "enter")
        if e["kind"] == "cutout":
            e["enter"] = "slide" if e["col"] in ("l", "r") and r < 0.5 else "drop"
        elif e["kind"] == "notif":                    # slides down like a phone notification
            e["enter"] = "notify"
        elif e["kind"] in ("photo", "person", "logo", "screenshot", "news"):
            e["enter"] = "slide" if e["col"] in ("l", "r") and r < 0.4 else "toss"
        else:
            e["enter"] = None
        side = {"l": -1, "r": 1}.get(e["col"], -1 if r < 0.5 else 1)
        e["exit_to"] = {"x": side * 1100, "rot": side * 18} if m["exit"] == "sweep" else None
    st["camera"] = _camera(st, scene["end"], m) if m["camera_follow"] else []
