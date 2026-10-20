"""Stage scenes: a collage that builds up on a persistent background (visual.type "stage").

Pure layout and timing: which slot and size each element gets, when it enters and leaves, and the
background texture CSS. compose.py turns this into template context; assets.py prepares the
cut-out and photo files.
"""

from __future__ import annotations

import hashlib
from urllib.parse import quote

from markupsafe import Markup

from klip import config, shots
from klip.spec import StageElement, Visual

BUILTIN_BACKGROUNDS = ("desk", "paper", "kraft", "board")
PHOTO_FRAME = (14, 14, 14, 54)      # photo card white frame: left, top, right, bottom (px)
SAFE_X = (60, 960)                  # TikTok safe zone (right-side buttons beyond x 960)


def cfg(key: str):
    return config.get(f"stage.{key}")


def is_media(e: StageElement) -> bool:
    return e.kind in ("cutout", "photo")


def background_key(v: Visual) -> str:
    return v.background or cfg("default_background")


def is_builtin(bg: str) -> bool:
    return bg in (cfg("backgrounds") or {})


def _noise_svg(freq: str, octaves: int = 3) -> str:
    svg = ("<svg xmlns='http://www.w3.org/2000/svg' width='1200' height='2040'>"
           "<filter id='n'><feTurbulence type='fractalNoise' baseFrequency='" + freq + "' "
           f"numOctaves='{octaves}' seed='7' stitchTiles='stitch'/>"
           "<feColorMatrix values='0 0 0 0 0  0 0 0 0 0  0 0 0 0 0  1.5 0 0 0 -0.45'/></filter>"
           "<rect width='100%' height='100%' filter='url(#n)'/></svg>")
    return "data:image/svg+xml," + quote(svg)


def tone(bg: str) -> str:
    """'light' or 'dark' surface: picks title, tag and shadow colours (image backgrounds count as dark)."""
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


# ---- layout

def tilt(scene_id: str, i: int, kind: str) -> float:
    h = int(hashlib.sha256(f"{scene_id}:{i}".encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
    damp = {"number": 0.5, "label": 0.6, "bar": 0.3, "highlight": 0.0, "stamp": 0.0}.get(kind, 1.0)
    if kind == "stamp":
        return -7.0 if h < 0.5 else 6.0
    return round((h * 2 - 1) * float(cfg("tilt_deg")) * damp, 2)


BIG = ("cutout", "photo", "bar")          # kinds that can carry a composition as its hero


def composition(elements: list[StageElement], placed: list[int]) -> str:
    """Composition name for the props sharing one stage page (see klip.yaml stage.compositions)."""
    kinds = [elements[i].kind for i in placed]
    n = len(kinds)
    if n <= 1:
        return "hero"
    if n == 2:
        return "hero_tag" if kinds[0] in BIG and kinds[1] not in BIG else "pair"
    if n == 3:
        return "hero_two" if kinds[0] in BIG and not any(k in BIG for k in kinds[1:]) else "trio"
    return "grid4" if n == 4 else "scatter5" if n == 5 else "scatter6"


def assign_places(elements: list[StageElement], page: list[int]) -> dict[int, tuple[float, float, str, str]]:
    """(x share, y share, size, slot) per element on one page: explicit `pos` first, the rest from the
    page's composition, in order. A `pos` takes the composition place nearest to it out of the pool."""
    placed = [i for i in page if elements[i].kind != "highlight"]
    places = [tuple(p) for p in cfg("compositions")[composition(elements, placed)]]
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
    if e.kind in ("cutout", "photo"):
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
        return len(e.text) * (0.68 if cfg("label.uppercase") else 0.56) * f + 56, f * 1.65
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
        for i in page:
            e = elements[i]
            if e.kind == "highlight" and (tb := out.get(e.target - 1)):
                pad = float(cfg("highlight.pad"))
                out[i] = {**tb, "w": tb["w"] + 2 * pad, "h": tb["h"] + 2 * pad, "size": tb["size"], "slot": tb["slot"]}
    return {i: {k: round(v, 1) if isinstance(v, float) else v for k, v in b.items()} for i, b in out.items()}
