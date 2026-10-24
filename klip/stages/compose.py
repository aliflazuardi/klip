"""Stage 4 — Compose: spec + timeline + words -> HyperFrames composition (index.html).

Writes composition/ in the project dir: index.html, gsap.min.js, fonts/, and
compose.json (warnings + content hash used by the render cache).
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import shutil
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from klip import config
from klip import beats as beats_mod
from klip import codescene, ffmpeg, mascot, motion, shots, transitions
from klip import stage as stage_mod
from klip.captions import CaptionWord, emphasis_mask, norm, paginate, tokenize
from klip.paths import RENDERER_DIR, ROOT, TEMPLATES_DIR
from klip.spec import COMPONENTS, IMPLEMENTED_TEMPLATES, IMPLEMENTED_VISUALS, Scene, Spec

log = logging.getLogger(__name__)

NODE_MODULES = RENDERER_DIR / "node_modules"
FONT_FILES = {
    600: "plus-jakarta-sans-latin-600-normal.woff2",
    700: "plus-jakarta-sans-latin-700-normal.woff2",
    800: "plus-jakarta-sans-latin-800-normal.woff2",
}


class ComposeError(RuntimeError):
    pass


def _s(ms: float) -> float:
    return round(ms / 1000, 3)


def rgba(color: str, alpha: float) -> str:
    """'#12213B', 0.6 -> 'rgba(18,33,59,0.6)' (style colors are hex; CSS needs alpha variants)."""
    h = color.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return f"rgba({r},{g},{b},{alpha})"


def icon_svg(name: str) -> str:
    path = NODE_MODULES / "lucide-static" / "icons" / f"{name}.svg"
    if not path.exists():
        raise ComposeError(f"unknown Lucide icon {name!r} (see https://lucide.dev/icons)")
    svg = path.read_text(encoding="utf-8")
    svg = re.sub(r"<!--.*?-->", "", svg, flags=re.S)
    svg = re.sub(r'\s(width|height|class)="[^"]*"', "", svg, count=3)
    return svg.strip()


def format_number(value: float, decimals: int = 0) -> str:
    """Indonesian number format: 1.234.567,5"""
    whole, _, frac = f"{abs(value):,.{decimals}f}".partition(".")
    out = whole.replace(",", ".") + ("," + frac if frac else "")
    return ("-" if value < 0 else "") + out


def _headline(text: str | None, emphasis: list[str]) -> list[dict]:
    if not text:
        return []
    toks = tokenize(text)
    return [{"text": tok, "emph": e} for tok, e in zip(toks, emphasis_mask(toks, emphasis))]


def title_slams(title: list[dict], words: list[dict], scene_id: str) -> None:
    """Mark a title's keywords (emphasis, or ALL-CAPS in a mixed-case title) with `slam`: the time (s) the
    narration says that word, else None (the keyword then lands with the rest). In place."""
    from klip.captions import norm
    caps_title = all(h["text"].upper() == h["text"] for h in title)
    said = [(norm(w["text"]), w["startMs"] / 1000) for w in words if w.get("sceneId") == scene_id]
    for h in title:
        key = h["emph"] or (not caps_title and len(norm(h["text"])) > 1 and h["text"].upper() == h["text"]
                            and any(c.isalpha() for c in h["text"]))
        n = norm(h["text"])
        h["slam"] = next((t for w, t in said if n and (w == n or (len(n) > 3 and w.startswith(n)))), None) if key else None
        h["key"] = bool(key)


def _list_numbers(spec: Spec) -> dict[str, tuple[int, int]]:
    """Auto-number runs of consecutive list_item scenes (explicit list_index/list_total win)."""
    out: dict[str, tuple[int, int]] = {}
    run: list[Scene] = []

    def flush() -> None:
        for i, s in enumerate(run, 1):
            out[s.id] = (s.list_index or i, s.list_total or len(run))
        run.clear()

    for s in spec.scenes:
        if s.template == "list_item":
            run.append(s)
        else:
            flush()
    flush()
    return out


def _reveal_time(scene: Scene, t: dict, words: list[dict]) -> float:
    start, dur = t["start_ms"], t["duration_ms"]
    if scene.reveal_at:
        target = norm(scene.reveal_at.split()[0])
        for w in words:
            if norm(w["text"]) == target:
                return _s(max(w["startMs"], start + 600))
    return _s(start + dur * 0.45)


def _cta_ctx(scene: Scene, style: dict) -> dict:
    """cta: the action chip for cta_type (icon + label from the style) and whether the headline is a question."""
    c = style["cta"]
    chip = None
    if scene.cta_type:
        ty = c["types"][scene.cta_type]
        chip = {"type": scene.cta_type, "icon": icon_svg(ty["icon"]), "label": ty["label"]}
    return {"chip": chip, "question": scene.cta_type == "comment", "chip_at": c["chip_at_s"],
            "chip_size": c["chip_font_size"], "question_size": c["question_font_size"],
            "compact_disc": c["compact_disc"], "compact_word": c["compact_word"]}


def _template_ctx(scene: Scene, t: dict, words: list[dict], numbers: dict, style: dict | None = None) -> dict:
    if scene.template == "cta":
        return _cta_ctx(scene, style or config.style())
    if scene.template == "list_item":
        index, total = numbers[scene.id]
        return {"index": index, "total": total}
    if scene.template == "myth_fact":
        return {"myth": scene.myth, "fact": scene.fact, "reveal": _reveal_time(scene, t, words),
                "x_icon": icon_svg("x"), "check_icon": icon_svg("check")}
    if scene.template == "stat":
        st = scene.stat
        final = format_number(st.value, st.decimals)
        chars = len(st.prefix) + len(final)
        return {"value": st.value, "decimals": st.decimals, "prefix": st.prefix, "suffix": st.suffix,
                "zero": format_number(0, st.decimals), "final": final,
                "font_size": int(min(300, 1500 / max(chars, 1))),
                "label": _headline(st.label or scene.on_screen_text, scene.emphasis)}
    if scene.template == "compare":
        def side(sd):
            return {"label": sd.label, "text": sd.text, "icon": icon_svg(sd.icon) if sd.icon else None}
        return {"left": side(scene.compare.left), "right": side(scene.compare.right)}
    return {}


def _quiz_ctx(scene: Scene, t: dict, words: list[dict], style: dict, box: tuple[float, float]) -> dict:
    """A quiz panel in `box` (top, bottom px): each option's entry (on its word, else staggered), the
    countdown ring and the reveal (s), and the geometry of the stack."""
    q, c = scene.quiz, config.get("quiz")
    start, end = t["start_ms"] / 1000, (t["start_ms"] + t["duration_ms"]) / 1000
    mine = [w for w in words if start - 0.01 <= w["startMs"] / 1000 < end]
    found = shots.anchor_times(mine, q.options)
    reveal = next(iter(shots.anchor_times(mine, [q.reveal_at])), None) if q.reveal_at else None
    reveal = round(reveal / 1000, 3) if reveal is not None else None
    t_ring = next(iter(shots.anchor_times(mine, [q.countdown_at])), None) if q.countdown_at else None
    ring = None
    if t_ring is not None:
        t0 = t_ring / 1000
        stop = min(x for x in (reveal, end - 0.1) if x is not None)
        if stop - t0 > 0.4:
            ring = {"t": round(t0, 3), "dur": round(min(float(c["countdown_s"]), stop - t0), 3)}
    latest = min(x for x in (ring and ring["t"], reveal, end - 0.3) if x is not None)
    opts = []
    for k, (text, ms) in enumerate(zip(q.options, found)):
        at = ms / 1000 if ms is not None else start + float(c["first_s"]) + k * float(c["stagger_s"])
        opts.append({"letter": "ABCD"[k], "text": text, "t": round(min(max(at, start + 0.05), latest), 3),
                     "right": k == q.answer - 1})
    top, bottom = box                          # the ring (if any) stands right of the options
    n, gap = len(opts), float(c["option_gap"])
    oh = max(float(c["option_min_h"]), min(float(c["option_h"]), (bottom - top - gap * (n - 1)) / n))
    stack = max(n * oh + gap * (n - 1), float(c["ring_px"]) if ring else 0)
    y0 = top + max(0.0, (bottom - top - stack) / 2)
    return {"options": opts, "ring": ring, "reveal": reveal, "top": round(y0, 1),
            "oh": round(oh, 1), "gap": gap, "font": round(min(float(c["font_px"]), oh * 0.4), 1),
            "letter": c["letter"] or style["accent_color"], "right": c["right"] or style["fact_color"],
            "wrong": c["wrong"] or style["myth_color"], "check": icon_svg("check"), "x": icon_svg("x")}


def _shots_ctx(scene_id: str, t: dict, media: dict) -> list[dict]:
    """B-roll shots for a scene (seconds). Older assets.json without `shots` → one shot."""
    if not media.get("kind"):
        return []
    rows = media.get("shots") or [{"file": media["file"], "kind": media["kind"],
                                   "start_ms": t["start_ms"], "dur_ms": t["duration_ms"]}]
    return [{"id": f"m-{scene_id}-{k}", "k": k, "kind": r["kind"], "src": r["file"].replace("\\", "/"),
             "start": _s(r["start_ms"]), "dur": _s(r["dur_ms"])} for k, r in enumerate(rows)]


def _stage_ctx(scene: Scene, t: dict, words: list[dict], media: dict, style: dict, warnings: list[str],
               list_no: tuple[int, int] | None) -> dict:
    """Template context for a stage scene: background, title strip and elements (with times and boxes)."""
    v = scene.visual
    bg = stage_mod.background_key(v)
    rows = {r["el"]: r for r in (media.get("stage") or [])}
    # a cutout/photo with no photo becomes its fallback icon (`name`); other elements whose file
    # couldn't be had are left out (and highlights pointing at them)
    els = [e.model_copy(update={"kind": "icon"}) if e.kind in ("cutout", "photo") and e.name and i not in rows
           else e for i, e in enumerate(v.elements)]
    for i, (a, b) in enumerate(zip(v.elements, els)):
        if a.kind != b.kind:
            warnings.append(f"{scene.id}: no photo for stage element at {a.at!r}; showing its icon {a.name!r}")
    missing = {i for i, e in enumerate(els) if stage_mod.needs_row(e) and i not in rows}
    missing |= {i for i, e in enumerate(els) if e.kind == "highlight" and e.target - 1 in missing}
    for i in sorted(missing):
        if stage_mod.needs_row(els[i]):
            warnings.append(f"{scene.id}: no {'data' if els[i].kind == 'chart' else 'image'} for stage element "
                            f"at {els[i].at!r}; left out")
    times = stage_mod.entry_times(els, words, t["start_ms"], t["duration_ms"], warnings, scene.id)
    cap_top = caption_style(style, True)["top"]
    bottom = cap_top - float(config.get("stage.caption_gap_px"))
    k, cx, xr = None, None, stage_mod.SAFE_X
    if mascot.shown(scene, style):            # the props end above the mascots
        clear = float(mascot.settings(style)["clear_px"])
        k = mascot.scale(scene, style)
        if scene.mascot and scene.mascot.focus:
            fc = mascot.settings(style)["focus"]
            if any(e.kind in mascot.BIG for e in els):
                # a spotlit star with pictures to show stands left of centre; they get the right column
                k = float(fc["side"]["height"]) / float(mascot.settings(style)["height"])
                cx, xr = float(fc["side"]["cx"]), tuple(fc["side"]["props_x"])
            else:                             # labels only: centred, shrunk to leave them a strip
                k = mascot.focus_scale(style, cap_top, stage_title_bottom(scene) + 24)
                bottom = min(bottom, mascot.top(style, cap_top, k) - clear)
        else:
            bottom = min(bottom, mascot.top(style, cap_top, k) - clear)
    area = (stage_title_bottom(scene) + 24, bottom)
    quiz_box = None
    if scene.quiz:                            # the options take the bottom of the props area...
        qc, n = config.get("quiz"), len(scene.quiz.options)
        need = n * float(qc["option_min_h"]) + (n - 1) * float(qc["option_gap"])
        split = area[0] + (area[1] - area[0]) * float(qc["stage_props_share"])
        split = max(area[0], min(split, area[1] - need - 16))     # ...and never get too small to read
        quiz_box, area = (split + 16, area[1]), (area[0], split)
    boxes = stage_mod.layout(scene.id, els, rows, area, xr)
    exits: dict[int, float] = {}
    pgs = stage_mod.pages(els)
    exit_s = config.get("stage.exit_s")
    for page, nxt in zip(pgs, pgs[1:]):
        for i in page:
            exits[i] = round(times[nxt[0]] - exit_s, 3)
    c = config.get("stage")
    out = []
    for i, e in enumerate(els):
        if i in missing or i not in boxes:
            continue
        b = boxes[i]
        # a text prop whose box the layout shrank (to fit or to clear its neighbours) shrinks its type too
        fit = min(1.0, b["h"] / stage_mod.box_size(e, b["size"], rows.get(i))[1])
        el = {"id": f"st-{scene.id}-{i}", "i": i, "kind": e.kind, "start": times[i], "exit": exits.get(i),
              "col": b["slot"][1], **b, "label": e.label, "label_font": None, "text": e.text, "page": next(k for k, pg in enumerate(pgs) if i in pg)}
        if e.kind == "chart":
            pts = rows[i]["data"] if i in rows else [[p.x, p.y] for p in e.points]
            el["chart"] = stage_mod.chart_geometry(pts, [bd.model_dump() for bd in e.bands], b["w"], b["h"],
                                                   e.tone, bool(e.text))
            el["fs"] = round(b["w"] * 0.048, 1)
        elif e.kind == "unit":
            legend = 60 if e.text else 0
            el["unit"] = stage_mod.unit_grid(e.total, e.total if e.filled is None else e.filled, b["w"], b["h"] - legend)
            el["fs"] = round(min(34.0, b["w"] * 0.055), 1)
        elif e.kind == "news":
            el.update(fs=round(b["w"] * 0.07, 1), outlet=e.outlet, date=e.date)
        elif e.kind == "notif":
            el.update(fs=round(b["w"] * 0.045, 1), outlet=e.outlet, date=e.date, stat=e.stat)
        elif e.kind == "bubble":
            el.update(sender=None if e.me else e.sender, color=stage_mod.sender_color(e.sender), me=e.me,
                      forwarded=e.forwarded, date=e.date)
        elif e.kind in COMPONENTS:
            end = exits.get(i) or (t["start_ms"] + t["duration_ms"]) / 1000
            st_times = stage_mod.step_times(e, times[i], end, words)
            el["comp"] = motion.build(e, b["w"], b["h"], st_times, times[i], end, icon_svg, style["accent_color"])
        elif stage_mod.is_media(e) or e.kind == "screenshot":
            r = rows[i]
            el.update(kind=r["render"], src=r["file"].replace("\\", "/"))
            if e.kind == "person":
                el.update(kind="person", name=e.label or (e.who or "").split(" (")[0], stat=e.stat,
                          stat_color=c["number"][e.tone], fs=round(b["w"] * 0.13, 1))
            if e.kind == "screenshot":
                el["host"] = (e.url or "").split("//", 1)[-1].rstrip("/")
        elif e.kind in ("icon", "stack"):
            el["svg"] = icon_svg(e.name)
            if e.kind == "stack":
                el["n"] = e.count or c["stack_count"]
                el["d"] = round(c["icon_px"][b["size"]] * 0.62, 1)
        elif e.kind == "number":
            el["font"] = round(c["number_px"][b["size"]] * fit, 1)
            el["color"] = c["number"][e.tone]
        elif e.kind == "label":
            el["font"] = round(c["label_px"][b["size"]] * fit, 1)
        elif e.kind == "stamp":
            el["font"] = round(c["stamp_px"][b["size"]] * fit, 1)
            el["color"] = c["stamp"][e.tone]
        elif e.kind == "bar":
            top = max(x.value for x in e.bars) or 1
            el["bars"] = [{"label": x.label, "text": x.text, "pct": round(100 * x.value / top, 1),
                           "color": c["bar"]["colors"][k % len(c["bar"]["colors"])]} for k, x in enumerate(e.bars)]
        if e.label and e.kind in ("cutout", "photo", "icon", "logo", "screenshot"):
            el["label_font"] = c["label_px"]["s" if b["size"] == "s" else "m"]
        out.append(el)
    chat = []                                  # chat pages scroll up as their bubbles come
    for n, page in enumerate(pgs):
        if stage_mod.is_chat_page(els, page):
            scroll = stage_mod.chat_scroll([el for el in out if el["page"] == n], area[1], float(c["chat"]["typing_s"]))
            if scroll:
                chat.append({"page": n, "scroll": scroll})
    image, backdrop = None, None
    if v.backdrop:
        backdrop = _backdrop_ctx(scene, media, warnings)
        if backdrop is None:                  # its photo/page couldn't be had: the default set
            bg = config.get("stage.default_background")
        elif backdrop.get("image"):
            image = backdrop["image"]
    elif not stage_mod.is_builtin(bg):
        path = ROOT / bg
        if not path.is_file():
            raise ComposeError(f"{scene.id}: stage background {bg!r} is neither a built-in "
                               f"({', '.join(config.get('stage.backgrounds'))}) nor an image file")
        image = {"src": f"stage/{path.name}", "path": str(path)}
    tone = stage_mod.tone(bg, v if backdrop else None)
    if tone == "dark":                         # a dark neutral stamp would vanish on a dark set
        for el in out:
            if el["kind"] == "stamp" and els[el["i"]].tone == "neutral":
                el["color"] = c["stamp"]["neutral_dark"]
    title_style = (backdrop or {}).get("title") or config.get("stage.title.style")
    title = _headline(scene.on_screen_text, scene.emphasis)
    title_slams(title, words, scene.id)
    return {"bg": bg, "builtin": stage_mod.is_builtin(bg), "image": image, "backdrop": backdrop, "elements": out,
            "tone": tone, "area": area, "title_style": title_style, "chat": chat, "quiz_box": quiz_box,
            "title_top": stage_title_top(scene), "mask": area[0] if v.backdrop and v.backdrop.kind == "chat" else None, "mascot_scale": k, "mascot_cx": cx,
            "title": title, "list_no": list_no,
            "hook": scene.template == "hook", "continues": False, "next_same": False, "bg_from": 0.0, "bg_to": 0.0}


def _backdrop_ctx(scene: Scene, media: dict, warnings: list[str]) -> dict | None:
    """Template context for a scene's backdrop: kind, darkening, tint, title style, and the prepared
    image (photo/screenshot), the board's cells or the phone's header. None when its file is missing."""
    v = scene.visual
    b = v.backdrop
    d = stage_mod.backdrop_settings(v)
    out = {"kind": b.kind, "dim": float(d.get("dim") or 0), "tint": b.tint, "title": d.get("title"),
           "header": b.title, "info": b.info, "cfg": d}
    if b.kind in ("photo", "screenshot"):
        row = media.get("backdrop")
        if not row:
            warnings.append(f"{scene.id}: no {b.kind} for the backdrop; using the default background")
            return None
        out["image"] = {"src": row["file"].replace("\\", "/"), "path": None}
    elif b.kind == "board":
        w, h = (int(x) for x in config.get("stage.backdrop.size"))
        n_rows = int(h // float(d["row_px"])) + 1
        out["rows"] = stage_mod.board_rows(b.items, int(d["cols"]), n_rows,
                                           int(hashlib.sha256(scene.id.encode()).hexdigest()[:4], 16) % len(b.items))
    return out


def stage_title_top(scene: Scene) -> float:
    """Top edge (px) of a stage scene's title: its backdrop's title_top (a chat's header sits above it),
    else stage.title.top."""
    if scene.visual.type == "stage" and scene.visual.backdrop:
        if (top := stage_mod.backdrop_settings(scene.visual).get("title_top")) is not None:
            return float(top)
    return float(config.get("stage.title.top"))


def stage_title_bottom(scene: Scene) -> float:
    """Bottom edge (px) of a stage scene's title, estimating how many lines the text wraps to."""
    t = {**config.get("stage.title"), "top": stage_title_top(scene)}
    font = t["hook_font_size"] if scene.template == "hook" else t["font_size"]
    text = (scene.on_screen_text or "") + (" 1/3 " if scene.template == "list_item" else "")
    if not text.strip():
        return t["top"]
    style = t["style"]
    if scene.visual.type == "stage" and scene.visual.backdrop:
        style = stage_mod.backdrop_settings(scene.visual).get("title") or style
    width = 900 if style in ("plain", "box") else 840
    per_char = 0.68 if style == "box" else 0.56       # ~em per character (box is all caps)
    lines = max(1, -(-len(text) * per_char * font // width))
    return t["top"] + lines * font * (1.28 if style == "box" else 1.1) + (8 if style == "plain" else 28)


def caption_style(style: dict, stage: bool) -> dict:
    """Caption settings for a page: the style's caption, with caption.stage on top for stage scenes."""
    cap = {k: v for k, v in style["caption"].items() if k != "stage"}
    return {**cap, **(style["caption"].get("stage") or {})} if stage else cap


def _link_stages(scenes: list[dict]) -> None:
    """Consecutive stage scenes on the same background: keep the background (no whoosh or entrance),
    sweep the props off before the cut, and pan the background continuously across the run."""
    drift = float(config.get("stage.bg_drift_px"))
    exit_s = float(config.get("stage.exit_s"))
    i = 0
    while i < len(scenes):
        if not scenes[i].get("stage"):
            i += 1
            continue
        j = i
        while j + 1 < len(scenes) and scenes[j + 1].get("stage") and scenes[j + 1]["stage"]["bg"] == scenes[i]["stage"]["bg"]:
            j += 1
        t0, t1 = scenes[i]["start"], scenes[j]["end"]
        for k in range(i, j + 1):
            st = scenes[k]["stage"]
            st["continues"], st["next_same"] = k > i, k < j
            st["bg_from"] = round(-drift + 2 * drift * (scenes[k]["start"] - t0) / max(t1 - t0, 0.001), 1)
            st["bg_to"] = round(-drift + 2 * drift * (scenes[k]["end"] - t0) / max(t1 - t0, 0.001), 1)
            if st["next_same"]:
                last = max((e["page"] for e in st["elements"]), default=0)
                for e in st["elements"]:
                    if e["page"] == last:
                        e["exit"] = round(max(scenes[k]["end"] - exit_s, e["start"] + 0.3), 3)
        i = j + 1


def _scene_ctx(spec: Spec, scene: Scene, idx: int, t: dict, style: dict, warnings: list[str],
               media: dict | None, words: list[dict], numbers: dict, look: dict | None = None) -> dict:
    template = scene.template
    if template not in IMPLEMENTED_TEMPLATES:
        warnings.append(f"{scene.id}: template {template!r} not implemented yet; using 'explain'")
        template = "explain"

    v = scene.visual
    media = media or {}
    icon = None
    if v.type == "icon" or (media.get("fallback") == "icon" and v.name):
        icon = icon_svg(v.name)
    elif v.type not in IMPLEMENTED_VISUALS and not media.get("kind"):
        warnings.append(f"{scene.id}: visual {v.type!r} not implemented yet; using solid background")

    palette = style["palette"]
    c1, c2 = palette[idx % len(palette)]
    if v.bg == "solid":
        c2 = c1

    headline = _headline(scene.on_screen_text, scene.emphasis)
    stage = _stage_ctx(scene, t, words, media, style, warnings, numbers.get(scene.id)) if v.type == "stage" else None
    quiz = None
    if scene.quiz and v.type != "code":       # a code scene draws its own (starter quiz.html)
        box = stage["quiz_box"] if stage else (float(config.get("quiz.top_px")),
                                               caption_style(style, True)["top"] - float(config.get("stage.caption_gap_px")))
        quiz = _quiz_ctx(scene, t, words, style, box)

    return {
        "id": scene.id, "idx": idx, "template": template, "hidden": False,
        "start": _s(t["start_ms"]), "dur": _s(t["duration_ms"]),
        "end": _s(t["start_ms"] + t["duration_ms"]),
        "c1": c1, "c2": c2, "icon": icon, "headline": headline,
        "media": {"kind": media["kind"], "src": media["file"].replace("\\", "/")} if media.get("kind") else None,
        "shots": _shots_ctx(scene.id, t, media),
        "t": _template_ctx(scene, t, words, numbers, style) if template == scene.template else {},
        "stage": stage, "quiz": quiz,
        "code": _code_ctx(spec, scene, t, words, look, style) if v.type == "code" else None,
    }


def _code_ctx(spec: Spec, scene: Scene, t: dict, words: list[dict], look: dict, style: dict) -> dict:
    try:
        ctx = codescene.scene_ctx(scene, t, words, look, caption_style(style, True)["top"])
    except codescene.CodeSceneError as e:
        raise ComposeError(str(e)) from None
    ctx["sfx"] = codescene.sfx_cues(scene, words)
    if codescene.uses_mascots(str(ctx["js"])) and mascot.names(style):
        ctx["meta"]["mascots"] = codescene.mascot_meta(spec, scene, style, words, t["start_ms"])
    return ctx


def music_beats(spec: Spec, total_s: float, warnings: list[str]) -> dict:
    """The music track's beats over the video (k.beats), or none when there's no music or no steady pulse."""
    from klip.stages.post import pick_track
    none = {"bpm": None, "period": None, "beats": []}
    try:
        track = pick_track(spec)
    except FileNotFoundError:
        return none                           # post reports a missing track
    if not track or not spec.music.beats:
        return none
    try:
        out = beats_mod.for_video(track, total_s)
    except ffmpeg.FFmpegError as e:
        warnings.append(f"music beats: couldn't read {track.name}: {str(e).splitlines()[0]}")
        return none
    if not out["beats"]:
        log.info("music: no beat in %s (it only swells); k.beats is empty", track.name)
    elif out["confidence"] < float(beats_mod.cfg("warn_confidence")):
        warnings.append(f"music beats: {track.name} has no clear beat (confidence {out['confidence']}, "
                        f"{out['bpm']} BPM); watch that pulses land, or set music.beats: false")
    else:
        log.info("music: %s BPM in %s (confidence %s)", out["bpm"], track.name, out["confidence"])
    return out


def _world_ctx(spec: Spec, scenes: list[dict], by_scene: dict, look: dict, style: dict) -> dict | None:
    """The world layer (spec.world): one code section spanning its run of scenes, which turn transparent
    over it. Its k.words cover the whole run; k.scenes = [{id, start, end}] in world seconds."""
    if not spec.world:
        return None
    try:
        run, ws = codescene.world_run(spec), codescene.world_scene(spec)
    except codescene.CodeSceneError as e:
        raise ComposeError(str(e)) from None
    ids = [s.id for s in run]
    covered = [s for s in scenes if s["id"] in ids]
    start, end = covered[0]["start"], covered[-1]["start"] + covered[-1]["dur"]
    words = [w for i in ids for w in by_scene.get(i, [])]
    try:
        ctx = codescene.scene_ctx(ws, {"start_ms": start * 1000, "duration_ms": (end - start) * 1000}, words, look,
                                  caption_style(style, True)["top"])
    except codescene.CodeSceneError as e:
        raise ComposeError(str(e)) from None
    ctx.update(texture="none", texture_css=codescene.texture_css("none", 0), sfx=[])
    ctx["meta"].update(texture="none", hook=False, text="",
                       scenes=[{"id": s["id"], "start": round(s["start"] - start, 3), "end": round(s["start"] + s["dur"] - start, 3)}
                               for s in covered])
    for s in covered:
        s["on_world"] = True
    return ctx


def code_ctx(look: dict | None, scenes: list[dict], style: dict, world: dict | None = None) -> dict | None:
    """Head context for code scenes: look-bible CSS vars, @font-face rows, caption font, three.js."""
    if not look:
        return None
    return {"vars": codescene.css_vars(look), "faces": codescene.font_faces(), "kit": codescene.cfg("kit"),
            "caption_font": look["families"].get("caption"),
            "three": any("three" in c["libs"] for c in [*(s["code"] for s in scenes if s.get("code")), *([world] if world else [])]),
            "cast": codescene.cast_ctx(style) if any((s.get("code") or {}).get("meta", {}).get("mascots")
                                                      for s in scenes) else None}


def build_context(spec: Spec, timeline: dict, words: list[dict],
                  assets: dict | None = None) -> tuple[dict, list[str]]:
    style = mascot.with_cast(config.style(spec.style), spec)
    warnings: list[str] = []
    tmap = {s["id"]: s for s in timeline["scenes"]}
    if [s.id for s in spec.scenes] != [s["id"] for s in timeline["scenes"]]:
        raise ComposeError("timeline.json doesn't match the spec's scenes; re-run the voice stage")

    by_scene: dict[str, list[dict]] = {}
    for w in words:
        by_scene.setdefault(w["sceneId"], []).append(w)

    media = (assets or {}).get("scenes", {})
    numbers = _list_numbers(spec)
    look = None
    if any(s.visual.type == "code" for s in spec.scenes):
        try:
            look = codescene.look(spec, style)
        except codescene.CodeSceneError as e:
            raise ComposeError(str(e)) from None
    scenes = [_scene_ctx(spec, s, i, tmap[s.id], style, warnings, media.get(s.id), by_scene.get(s.id, []), numbers, look)
              for i, s in enumerate(spec.scenes)]
    outro = fold_outro(spec, scenes, style)
    for s in scenes:
        if s.get("code"):                     # the outro may have stretched the scene before the cta
            s["code"]["meta"]["dur"] = s["dur"]
    world = None
    if look:
        music = music_beats(spec, _s(timeline["total_ms"]), warnings)
        world = _world_ctx(spec, scenes, by_scene, look, style)
        for s in scenes + ([{"code": world, "start": world["meta"]["start"], "dur": world["meta"]["dur"]}] if world else []):
            if s.get("code"):
                s["code"]["meta"]["beats"] = beats_mod.in_scene(music, s["start"], s["dur"])
                s["code"]["meta"]["bpm"], s["code"]["meta"]["period"] = music["bpm"], music["period"]
    if outro and outro["mode"] != "card" and (prev := scenes[-2].get("code")) and prev["meta"].get("mascots"):
        cta = spec.scenes[-1]                 # the cta's speaker says the closing line over that scene
        if who := mascot.speaker(spec, cta, style):
            m = prev["meta"]["mascots"]["mouth"]
            m[who] = m.get(who, []) + codescene.flaps(style, by_scene.get(cta.id, []), scenes[-2]["start"])
    _link_stages(scenes)
    for s in scenes:
        if s.get("stage"):
            stage_mod.add_motion(s)
    mascots = mascot.plan(spec, scenes, words, style, caption_style(style, True)["top"])

    # Caption words per scene, with emphasis flags from the spec.
    scene_words = []
    for s in spec.scenes:
        if outro and s.id == outro["scene"] and not outro["captions"]:
            continue                          # the outro's words are already on screen
        if s.visual.type == "code" and not s.visual.code.captions:
            continue                          # the scene shows its own words
        ws = by_scene.get(s.id, [])
        mask = emphasis_mask([w["text"].strip() for w in ws], s.emphasis)
        scene_words.append((s.id, [CaptionWord(w["text"].strip(), w["startMs"], w["endMs"], e)
                                   for w, e in zip(ws, mask)]))
    cap = caption_style(style, False)
    staged = {s.id for s in spec.scenes if s.visual.type in ("stage", "code")}
    tones = {s["id"]: s["stage"]["tone"] for s in scenes if s.get("stage")}
    tones |= {s["id"]: look["tone"] for s in scenes if s.get("code")}
    per_scene = {sid: {k: caption_style(style, True)[k] for k in ("max_words", "max_page_ms", "hide_gap_ms")}
                 for sid in staged}
    scene_ends = {s["id"]: s["start_ms"] + s["duration_ms"] for s in timeline["scenes"]}
    pages = paginate(scene_words, cap["max_words"], cap["max_page_ms"], scene_ends=scene_ends,
                     hide_gap_ms=cap.get("hide_gap_ms"), per_scene=per_scene)

    # The first caption page is on screen from frame 0 (no blank first beat before word one).
    if pages and pages[0].scene_id == spec.scenes[0].id:
        pages[0].start_ms = 0.0

    page_ctx = []
    for pi, p in enumerate(pages):
        wctx = []
        for wi, w in enumerate(p.words):
            base = "w emph" if w.emphasis else "w"
            off = p.words[wi + 1].start_ms if wi + 1 < len(p.words) else p.end_ms
            wctx.append({"id": f"p{pi}w{wi}", "text": w.text, "cls": base,
                         "on": _s(w.start_ms), "off": _s(off)})
        st = p.scene_id in staged
        page_ctx.append({"id": f"p{pi}", "start": _s(p.start_ms), "stage": st,
                         "light": st and tones.get(p.scene_id) == "light",
                         "highlight": caption_style(style, st)["highlight"],
                         "dur": round(_s(p.end_ms) - _s(p.start_ms), 3), "words": wctx})

    total = _s(timeline["total_ms"])
    brand = branding(spec, style, scenes, total)
    brand["outro"] = outro_badge(outro, brand, scenes)
    for s in scenes:
        if s.get("code"):
            s["code"]["meta"]["layout"] = codescene.layout(style, s, brand, caption_style(style, True)["top"])
    transitions.plan(spec, scenes, style)
    stage_bgs = sorted({s["stage"]["bg"] for s in scenes if s.get("stage") and s["stage"]["builtin"]})
    ctx = {
        "total": total, "style": style, "scenes": scenes, "pages": page_ctx, "brand": brand, "mascots": mascots,
        "cap": {"base": cap, "stage": caption_style(style, True)},
        "stage": {"cfg": config.get("stage"),
                  "bgs": [{"key": b, "css": stage_mod.background_css(b), "grain": stage_mod.grain_css(b)}
                          for b in stage_bgs]} if any(s.get("stage") for s in scenes) else None,
        "code": code_ctx(look, scenes, style, world), "code_look": look, "world": world,
        "font_files": FONT_FILES, "slug": spec.slug, "fx": config.get("fx"), "quiz": config.get("quiz"), "cut_zoom": config.get("cuts.cut_zoom", 1.12),
        "sfx": sfx_events(scenes, page_ctx, end_card=bool(brand["end_card"]), nudge=brand["save_nudge"],
                          outro=brand["outro"])
               if spec.sfx else [],
    }
    return ctx, warnings


def fold_outro(spec: Spec, scenes: list[dict], style: dict) -> dict | None:
    """Apply the style's outro to a final cta scene. card: it stays a scene (the end card). overlay / none:
    the scene before it keeps playing over the cta narration (its last shot is held) and the cta scene is
    hidden; overlay adds a badge on top. Returns the outro settings, or None without a final cta."""
    o = style["outro"]
    last = scenes[-1] if scenes else None
    if not last or last["template"] != "cta":
        return None
    out = {"mode": o["mode"], "scene": last["id"], "captions": o["captions"]}
    if o["mode"] == "card" or len(scenes) < 2:
        out["mode"] = "card"
        return out
    prev = scenes[-2]
    prev["dur"], prev["end"] = round(last["end"] - prev["start"], 3), last["end"]
    if prev["shots"]:
        sh = prev["shots"][-1]
        sh["dur"] = round(last["end"] - sh["start"], 3)
    last["hidden"] = True
    scene = spec.scenes[-1]
    text = o.get("text") if o.get("text") and scene.cta_type != "comment" else scene.on_screen_text
    out.update(start=last["start"], dur=last["dur"], chip=last["t"].get("chip") if o["chip"] else None,
               chip_at=round(last["start"] + last["t"]["chip_at"], 3), text=_headline(text, scene.emphasis),
               logo=o["logo"], top=o["badge_top"], font_size=o["font_size"],
               lift=prev["id"] if prev.get("stage") else None, lift_px=o["lift_px"], shrink=o["shrink"],
               bg=rgba(style["shade_color"], o["bg_opacity"]))
    return out


def outro_badge(outro: dict | None, brand: dict, scenes: list[dict]) -> dict | None:
    """The overlay badge (None for card / none / no outro): logo from the end card, else the watermark."""
    if not outro or outro["mode"] != "overlay":
        return None
    ec, wm = brand["end_card"] or {}, brand["watermark"] or {}
    logo = (ec.get("logo") or wm.get("img")) if outro["logo"] else None
    return {**outro, "logo": logo, "disc": ec.get("disc")}


def _brand_file(path: str | None) -> dict | None:
    """A brand image (repo-relative or absolute) -> {src (in composition/), path (on disk)}."""
    if not path:
        return None
    p = ROOT / path
    if not p.is_file():
        raise ComposeError(f"brand file not found: {path} (check the style in klip.yaml or its brand.yaml)")
    return {"src": f"brand/{p.name}", "path": str(p)}


def _spans(scenes: list[dict], total: float, show) -> list[dict]:
    """Merged time spans covering the scenes where show(scene) is true (a scene lasts until the next starts)."""
    out: list[dict] = []
    scenes = [s for s in scenes if not s.get("hidden")]
    for i, s in enumerate(scenes):
        if not show(s):
            continue
        start = 0.0 if i == 0 else s["start"]
        end = scenes[i + 1]["start"] if i + 1 < len(scenes) else total
        if out and abs(out[-1]["end"] - start) < 1e-6:
            out[-1]["end"] = end
        else:
            out.append({"start": start, "end": end})
    for k, sp in enumerate(out):
        sp["k"], sp["dur"] = k, round(sp["end"] - sp["start"], 3)
    return out


def series_label(spec: Spec, style: dict) -> str | None:
    """'KENAPA? #12': the style's label for spec.series (else the key in capitals) + episode."""
    if not spec.series:
        return None
    label = (style["series_pill"].get("labels") or {}).get(spec.series) or spec.series.replace("-", " ").upper()
    return f"{label} #{spec.episode}" if spec.episode else label


def branding(spec: Spec, style: dict, scenes: list[dict], total: float) -> dict:
    """Progress bar, watermark, series pill and end card for this video (all driven by the style)."""
    pb, wm, pill, ec = style["progress_bar"], style["watermark"], style["series_pill"], style["end_card"]
    hidden = set(wm.get("hide_on") or [])

    progress = None
    if spec.progress_bar if spec.progress_bar is not None else pb["enabled"]:
        logo_room = wm["size"] + 24 if wm.get("file") else 0
        right = (1080 - wm["right"] - logo_room) if logo_room else 960
        progress = {"left": 60, "width": right - 60, "top": pb["top"], "height": pb["height"],
                    "color": pb.get("color") or style["accent_color"],
                    "track": rgba(style["text_color"], pb["track_opacity"]),
                    "ticks": [round((right - 60) * s["start"] / total, 1) for s in scenes[1:] if not s.get("hidden")]
                             if pb.get("scene_ticks") else []}

    watermark = None
    if wm.get("file") or wm.get("text"):
        watermark = {"img": _brand_file(wm.get("file")), "text": wm.get("text"), "size": wm["size"],
                     "top": wm["top"], "right": wm["right"], "opacity": wm["opacity"],
                     "spans": _spans(scenes, total, lambda s: s["template"] not in hidden)}

    series = None
    if label := series_label(spec, style):
        if pill["scenes"] == "all":
            show = lambda s: s["template"] not in hidden  # noqa: E731
        else:
            show = lambda s: s["idx"] == 0  # noqa: E731
        series = {"label": label, "left": pill["left"], "top": pill["top"], "font_size": pill["font_size"],
                  "font_weight": pill["font_weight"], "bg": pill.get("bg") or style["accent_color"],
                  "color": pill.get("color") or style["stroke_color"], "spans": _spans(scenes, total, show)}

    end_card = None
    if ec and (ec.get("logo") or ec.get("wordmark")):
        end_card = {"logo": _brand_file(ec.get("logo")), "wordmark": _brand_file(ec.get("wordmark")),
                    "tagline": ec.get("tagline"), "disc": ec.get("disc_color")}

    return {"progress": progress, "watermark": watermark, "series": series, "end_card": end_card,
            "save_nudge": save_nudge(spec, style, scenes)}


def save_nudge(spec: Spec, style: dict, scenes: list[dict]) -> dict | None:
    """'Simpan dulu' pill when item `at_item` of the first list_item run starts; None if off or no such item."""
    sn = style["save_nudge"]
    if not (spec.save_nudge if spec.save_nudge is not None else sn["enabled"]):
        return None
    pos = 0
    for s in scenes:
        if s["template"] != "list_item":
            if pos:
                return None                      # first run ended before item at_item
            continue
        pos += 1
        if pos == sn["at_item"]:
            start = round(s["start"] + sn["delay_s"], 3)
            dur = round(min(sn["duration_s"], s["end"] - 0.1 - start), 3)
            if dur < sn["min_s"]:
                return None
            return {"text": sn["text"], "icon": icon_svg(sn["icon"]), "start": start, "dur": dur,
                    "top": sn["top"], "font_size": sn["font_size"],
                    "bg": rgba(style["shade_color"], sn["bg_opacity"])}
    return None


# Offsets so each effect's audible peak lands on its visual moment (seconds).
WHOOSH_PEAK_S = 0.22
RISER_LEN_S = 1.0


def sfx_events(scenes: list[dict], pages: list[dict], end_card: bool = False,
               nudge: dict | None = None, outro: dict | None = None) -> list[dict]:
    """Sound-effect cues from the composed timeline: [{t, moment, sfx}], sorted by time."""
    names = config.get("sfx.events", {}) or {}
    out: list[dict] = []

    def add(moment: str, t: float) -> None:
        if names.get(moment):
            out.append({"t": round(max(t, 0.0), 3), "moment": moment, "sfx": names[moment]})

    for s in scenes:
        if s.get("hidden"):
            continue
        if s["idx"] == 0 and s["template"] == "hook":
            add("hook_start", 0.0)
        if s["idx"] > 0 and not (s.get("stage") and s["stage"]["continues"]):
            if (tr := s.get("tr_in")) and tr.get("sfx"):          # the transition's own sound
                out.append({"t": round(max(s["start"] - (WHOOSH_PEAK_S if tr["sfx"] in ("whoosh", "swish") else 0), 0), 3),
                            "moment": "transition", "sfx": tr["sfx"]})
            else:
                add("scene_cut", s["start"] - WHOOSH_PEAK_S)
        for e in (s.get("stage") or {}).get("elements", []):
            add({"number": "stage_number", "highlight": "stage_highlight", "stamp": "stage_stamp",
                 "bubble": "stage_bubble"}.get(e["kind"], "stage_pop"), e["start"])
            comp = e.get("comp")
            for st in (comp or {}).get("steps", []):
                if comp["kind"] == "reel":
                    continue
                add("stage_number" if st["count"] and comp["kind"] in ("meter", "funnel") else "stage_pop", st["t"])
            if comp and comp["kind"] == "reel":
                add("stage_number", round(comp["from"] + comp["dur"], 3))
        for cue in (s.get("code") or {}).get("sfx", []):     # a code scene's own beats
            out.append({"t": cue["t"], "moment": "code_cue", "sfx": cue["sfx"]})
        if s["template"] == "list_item":
            add("list_badge", s["start"] + 0.05)
        if q := s.get("quiz"):
            for o in q["options"]:
                add("quiz_option", o["t"])
            if q["ring"]:
                add("quiz_countdown", q["ring"]["t"] + q["ring"]["dur"] - RISER_LEN_S)
            if q["reveal"] is not None:
                add("quiz_reveal", q["reveal"])
        if s["template"] == "myth_fact":
            add("myth_riser", s["t"]["reveal"] - RISER_LEN_S)
            add("fact_reveal", s["t"]["reveal"])
        elif s["template"] == "stat":
            add("stat_land", s["start"] + 0.15 + 1.3 - 0.05)   # counter tween: starts +0.15 s, lasts 1.3 s
        elif s["template"] == "compare":
            add("compare_vs", s["start"] + 0.7)
        elif s["template"] == "cta" and (s["icon"] or end_card):
            add("cta_icon", s["start"])
        if s["template"] == "cta" and s["t"].get("chip"):
            add("cta_ask", s["start"] + s["t"]["chip_at"])
    if nudge:
        add("save_nudge", nudge["start"])
    if outro:
        add("cta_icon", outro["start"])
        if outro["chip"]:
            add("cta_ask", outro["chip_at"])
    for p in pages:
        add("caption_page", p["start"])
    return sorted(out, key=lambda e: e["t"])


def _hash_dir(d: Path) -> str:
    h = hashlib.sha256()
    for p in sorted(d.rglob("*")):
        if p.is_file() and p.name != "compose.json":
            h.update(str(p.relative_to(d)).encode())
            h.update(p.read_bytes())
    return h.hexdigest()[:20]


def run(spec: Spec, project_dir: Path) -> dict:
    if not NODE_MODULES.exists():
        raise ComposeError("renderer/node_modules missing; run `npm install` in renderer/ (see README)")
    timeline = json.loads((project_dir / "timeline.json").read_text())
    words = json.loads((project_dir / "words.json").read_text())
    assets_path = project_dir / "assets.json"
    assets = json.loads(assets_path.read_text()) if assets_path.exists() else None
    ctx, warnings = build_context(spec, timeline, words, assets)
    for w in warnings:
        log.warning(w)

    # A style can ship its own templates in templates/<style>/; otherwise it restyles the default ones.
    tdir = TEMPLATES_DIR / spec.style
    env = Environment(loader=FileSystemLoader(tdir if tdir.is_dir() else TEMPLATES_DIR / "default"),
                      undefined=StrictUndefined, autoescape=True, trim_blocks=True, lstrip_blocks=True)
    env.filters["rgba"] = rgba
    html = env.get_template("index.html.j2").render(**ctx)

    out = project_dir / "composition"
    if out.exists():
        shutil.rmtree(out)
    (out / "fonts").mkdir(parents=True)
    (out / "index.html").write_text(html, encoding="utf-8")
    shutil.copyfile(NODE_MODULES / "gsap" / "dist" / "gsap.min.js", out / "gsap.min.js")
    font_src = NODE_MODULES / "@fontsource" / "plus-jakarta-sans" / "files"
    for f in FONT_FILES.values():
        shutil.copyfile(font_src / f, out / "fonts" / f)
    b = ctx["brand"]
    for f in [(b["watermark"] or {}).get("img"), *((b["end_card"] or {}).get(k) for k in ("logo", "wordmark")),
              (b["outro"] or {}).get("logo")]:
        if f:
            (out / "brand").mkdir(exist_ok=True)
            shutil.copyfile(f["path"], out / f["src"])
    if ctx["code"]:
        for f in ctx["code"]["faces"]:
            shutil.copyfile(f["src"], out / "fonts" / f["file"])
        if ctx["code"]["three"]:
            (out / "three.min.js").write_text(codescene.three_script(), encoding="utf-8")
    for a in (ctx["world"] or {}).get("assets", []):
        (out / a["src"]).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(a["path"], out / a["src"])
    for s in ctx["scenes"]:
        for a in (s.get("code") or {}).get("assets", []):
            (out / a["src"]).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(a["path"], out / a["src"])
        st = s.get("stage") or {}
        files = [(project_dir / e["src"], out / e["src"]) for e in st.get("elements", []) if e.get("src")]
        if st.get("image"):
            src = Path(st["image"]["path"]) if st["image"]["path"] else project_dir / st["image"]["src"]
            files.append((src, out / st["image"]["src"]))
        for src, dst in files:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst)
        for shot in s["shots"]:
            dst = out / shot["src"]
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(project_dir / shot["src"], dst)

    (project_dir / "sfx.json").write_text(json.dumps(ctx["sfx"], indent=1))
    (project_dir / "captions.json").write_text(json.dumps(
        [{"start": p["start"], "dur": p["dur"], "words": [w["text"] for w in p["words"]]} for p in ctx["pages"]],
        indent=1, ensure_ascii=False))
    info = {"hash": _hash_dir(out), "warnings": warnings, "pages": len(ctx["pages"]), "total_s": ctx["total"]}
    (out / "compose.json").write_text(json.dumps(info, indent=2, ensure_ascii=False))
    return info
