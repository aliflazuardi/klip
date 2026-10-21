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
from klip import mascot, motion
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
    if mascot.shown(scene, style):            # the props end above the mascots
        bottom = min(bottom, mascot.top(style, cap_top, mascot.scale(scene)) - float(mascot.settings(style)["clear_px"]))
    area = (stage_title_bottom(scene) + 24, bottom)
    boxes = stage_mod.layout(scene.id, els, rows, area)
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
    title_style = (backdrop or {}).get("title") or config.get("stage.title.style")
    return {"bg": bg, "builtin": stage_mod.is_builtin(bg), "image": image, "backdrop": backdrop, "elements": out,
            "tone": tone, "area": area, "title_style": title_style,
            "title": _headline(scene.on_screen_text, scene.emphasis), "list_no": list_no,
            "hook": scene.template == "hook", "continues": False, "next_same": False, "bg_from": 0.0, "bg_to": 0.0}


def _backdrop_ctx(scene: Scene, media: dict, warnings: list[str]) -> dict | None:
    """Template context for a scene's backdrop: kind, darkening, tint, title style, and the prepared
    image (photo/screenshot), the board's cells or the phone's header. None when its file is missing."""
    v = scene.visual
    b = v.backdrop
    d = stage_mod.backdrop_settings(v)
    out = {"kind": b.kind, "dim": float(d.get("dim") or 0), "tint": b.tint, "title": d.get("title"),
           "header": b.title, "cfg": d}
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


def stage_title_bottom(scene: Scene) -> float:
    """Bottom edge (px) of a stage scene's title, estimating how many lines the text wraps to."""
    t = config.get("stage.title")
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


def _scene_ctx(scene: Scene, idx: int, t: dict, style: dict, warnings: list[str],
               media: dict | None, words: list[dict], numbers: dict) -> dict:
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

    return {
        "id": scene.id, "idx": idx, "template": template, "hidden": False,
        "start": _s(t["start_ms"]), "dur": _s(t["duration_ms"]),
        "end": _s(t["start_ms"] + t["duration_ms"]),
        "c1": c1, "c2": c2, "icon": icon, "headline": headline,
        "media": {"kind": media["kind"], "src": media["file"].replace("\\", "/")} if media.get("kind") else None,
        "shots": _shots_ctx(scene.id, t, media),
        "t": _template_ctx(scene, t, words, numbers, style) if template == scene.template else {},
        "stage": _stage_ctx(scene, t, words, media, style, warnings, numbers.get(scene.id))
                 if v.type == "stage" else None,
    }


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
    scenes = [_scene_ctx(s, i, tmap[s.id], style, warnings, media.get(s.id), by_scene.get(s.id, []), numbers)
              for i, s in enumerate(spec.scenes)]
    outro = fold_outro(spec, scenes, style)
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
        ws = by_scene.get(s.id, [])
        mask = emphasis_mask([w["text"].strip() for w in ws], s.emphasis)
        scene_words.append((s.id, [CaptionWord(w["text"].strip(), w["startMs"], w["endMs"], e)
                                   for w, e in zip(ws, mask)]))
    cap = caption_style(style, False)
    staged = {s.id for s in spec.scenes if s.visual.type == "stage"}
    tones = {s["id"]: s["stage"]["tone"] for s in scenes if s.get("stage")}
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
    stage_bgs = sorted({s["stage"]["bg"] for s in scenes if s.get("stage") and s["stage"]["builtin"]})
    ctx = {
        "total": total, "style": style, "scenes": scenes, "pages": page_ctx, "brand": brand, "mascots": mascots,
        "cap": {"base": cap, "stage": caption_style(style, True)},
        "stage": {"cfg": config.get("stage"),
                  "bgs": [{"key": b, "css": stage_mod.background_css(b), "grain": stage_mod.grain_css(b)}
                          for b in stage_bgs]} if any(s.get("stage") for s in scenes) else None,
        "font_files": FONT_FILES, "slug": spec.slug, "cut_zoom": config.get("cuts.cut_zoom", 1.12),
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
            add("scene_cut", s["start"] - WHOOSH_PEAK_S)
        for e in (s.get("stage") or {}).get("elements", []):
            add({"number": "stage_number", "highlight": "stage_highlight", "stamp": "stage_stamp"}.get(e["kind"], "stage_pop"), e["start"])
            comp = e.get("comp")
            for st in (comp or {}).get("steps", []):
                if comp["kind"] == "reel":
                    continue
                add("stage_number" if st["count"] and comp["kind"] in ("meter", "funnel") else "stage_pop", st["t"])
            if comp and comp["kind"] == "reel":
                add("stage_number", round(comp["from"] + comp["dur"], 3))
        if s["template"] == "list_item":
            add("list_badge", s["start"] + 0.05)
        elif s["template"] == "myth_fact":
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
    for s in ctx["scenes"]:
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
