"""Designed cover.png: a single-frame HTML composition, snapshotted with HyperFrames.

Two layouts, both inside the centre 3:4 band (y 240–1680) that profile grids show:
- hero (whenever there's a subject): series pill, a short title whose last line is the keyword
  (on an accent block), then one big subject — a cut-out photo and/or a mascot pulling a face —
  with an arrow from the keyword to it, an optional badge and the subtitle as a tag.
- text: pill, title + keyword, subtitle, centred.
Both sit over a darkened still from the hook (b-roll or stage backdrop), else the style's first
palette gradient with a faint sunburst; logo + wordmark at the bottom. Brand parts come from the
style (klip.yaml or a brand pack).

Writes cover/ in the project dir (index.html, fonts/, brand/, bg.jpg, hero.*) and cover.png.
"""

from __future__ import annotations

import hashlib
import logging
import re
import shutil
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from PIL import Image

from klip import brief, config, cutout, ffmpeg, mascot
from klip.engines.render.hyperframes import HyperFramesRenderer
from klip.paths import ROOT, TEMPLATES_DIR
from klip.spec import Spec
from klip.stages import compose

log = logging.getLogger(__name__)

MAX_KEYWORD_WORDS = 3
LINE_H = {"title": 1.06, "keyword": 1.04}


def _norm(text: str) -> str:
    return " ".join(re.sub(r"[^\w\s]", "", text).casefold().split())


def split_title(text: str, emphasis: list[str]) -> tuple[str, str]:
    """'Madu awet ribuan tahun?' + emphasis ['ribuan tahun?'] -> ('Madu awet', 'ribuan tahun?').
    The keyword is the longest emphasised phrase the text ends with (max 3 words), else the last word."""
    words = text.split()
    targets = {_norm(e) for e in emphasis}
    k = next((k for k in range(min(MAX_KEYWORD_WORDS, len(words)), 0, -1)
              if _norm(" ".join(words[-k:])) in targets), 1)
    return " ".join(words[:-k]), " ".join(words[-k:])


def title_parts(spec: Spec) -> dict:
    """{lead: [explicit lines] | None, title: str, keyword: str, subtitle: str | None}."""
    c = spec.cover
    if c and c.lines:
        return {"lead": c.lines[:-1], "title": " ".join(c.lines[:-1]), "keyword": c.lines[-1],
                "subtitle": c.subtitle}
    if c and (c.title or c.keyword):
        if c.keyword:
            title, keyword = c.title or "", c.keyword
        else:
            title, keyword = split_title(c.title, [])
        return {"lead": None, "title": title, "keyword": keyword, "subtitle": c.subtitle}
    hook = spec.scenes[0]
    title, keyword = split_title(hook.on_screen_text or hook.narration, hook.emphasis)
    return {"lead": None, "title": title, "keyword": keyword, "subtitle": c.subtitle if c else None}


def wrap_count(text: str, size: float, width: float, em: float) -> int:
    """Lines `text` needs at `size` px in `width` px (greedy word wrap, average glyph width em)."""
    lines, used = 1, 0.0
    for w in text.split():
        ww = len(w) * em * size
        gap = 0.25 * size if used else 0.0
        if used and used + gap + ww > width:
            lines, used = lines + 1, ww
        else:
            used += gap + ww
    return lines


def fit_size(texts: list[str], size: int, min_size: int, width: float, em: float, max_lines: int = 1) -> int:
    """Largest px size ≤ size (≥ min_size) at which each text takes ≤ max_lines lines."""
    s = size
    while s > min_size and any(wrap_count(t, s, width, em) > max_lines for t in texts if t):
        s -= 2
    return max(s, min_size)


def _flip(slug: str) -> int:
    """+1 or -1, fixed per video: which way the stickers lean."""
    return 1 if int(hashlib.sha256(slug.encode()).hexdigest()[:2], 16) % 2 else -1


def text_block(parts: dict, keyword: str, cv: dict, title_size: int, title_min: int, kw_size: int, kw_min: int) -> dict:
    """Fitted sizes for the title + keyword, and the block's height in px."""
    width = cv["width"]
    kw_em = cv["caps_em"] if cv["keyword_uppercase"] else cv["char_em"]
    boxed = cv["keyword_style"] == "box"
    pad_v, pad_h = cv["keyword_pad_em"] if boxed else (0, 0)
    if parts["lead"]:
        t_size = fit_size(parts["lead"], title_size, title_min, width, cv["char_em"])
        t_lines = len(parts["lead"])
    else:
        t_size = fit_size([parts["title"]], title_size, title_min, width, cv["char_em"], cv["title_max_lines"])
        t_lines = wrap_count(parts["title"], t_size, width, cv["char_em"]) if parts["title"] else 0
    # keyword stays on one line: shrink (the block's side padding counts), and only wrap at the minimum
    k_size = kw_size
    while k_size > kw_min and wrap_count(keyword, k_size, width - 2 * pad_h * k_size, kw_em) > 1:
        k_size -= 2
    k_lines = wrap_count(keyword, k_size, width - 2 * pad_h * k_size, kw_em)
    height = t_lines * t_size * LINE_H["title"] + k_lines * k_size * LINE_H["keyword"] + 2 * pad_v * k_size \
        + (0.18 * k_size if t_lines else 0)
    return {"title_size": t_size, "keyword_size": k_size, "height": round(height)}


def fit_box(w: float, h: float, max_w: float, max_h: float) -> tuple[int, int]:
    s = min(max_w / w, max_h / h)
    return round(w * s), round(h * s)


def hero_layout(cv: dict, hv: dict, text_bottom: float, photo: dict | None, cast: dict | None, flip: int) -> dict:
    """Boxes (x, y, w, h) for the subject(s), badge anchor and arrow, inside the hero zone."""
    z0, z1 = hv["zone"]
    z0 = max(z0, text_bottom + 60)
    zh, max_w = z1 - z0, hv["max_w"]
    out: dict = {"zone": [z0, z1], "photo": None, "mascot": None}
    if photo and cast:
        mh = round(zh * hv["mascot_share"])
        pw, ph = fit_box(photo["w"], photo["h"], max_w * 0.8, zh)
        px = round(540 - pw / 2 - flip * max_w * 0.08)
        out["photo"] = {"x": px, "y": round(z0 + (zh - ph) / 2), "w": pw, "h": ph}
        mw = round(mh * cast["aspect"])
        # the mascot peeks in from the photo's lower corner, on the side the photo leans away from
        mx = px + pw - round(mw * 0.45) if flip < 0 else px - round(mw * 0.55)
        out["mascot"] = {"x": max(40, min(1040 - mw, mx)), "y": z1 - mh, "w": mw, "h": mh,
                         "mirror": flip > 0}
    elif photo:
        pw, ph = fit_box(photo["w"], photo["h"], max_w, zh)
        out["photo"] = {"x": round(540 - pw / 2), "y": round(z0 + (zh - ph) / 2), "w": pw, "h": ph}
    elif cast:
        mh = round(zh * 0.98)
        mw = round(mh * cast["aspect"])
        if mw > max_w:
            mw, mh = max_w, round(max_w / cast["aspect"])
        out["mascot"] = {"x": round(540 - mw / 2), "y": z1 - mh, "w": mw, "h": mh, "mirror": False}
    main = out.get("photo") or out["mascot"]
    # badge on the subject's upper corner, on the side away from the arrow
    out["badge"] = {"x": main["x"] + main["w"] if flip > 0 else main["x"], "y": main["y"] + 20,
                    "side": "right" if flip > 0 else "left"}
    # arrow: from beside the keyword block down to the subject's upper edge, on the other side
    sx = 140 if flip > 0 else 940
    tx = main["x"] + main["w"] * (0.22 if flip > 0 else 0.78)
    ty = main["y"] + min(70, main["h"] * 0.15)
    sy = text_bottom + 24
    cx = sx - flip * 30
    out["arrow"] = {"d": f"M {sx} {sy:.0f} C {cx} {sy + (ty - sy) * 0.75:.0f}, {(sx + tx) / 2:.0f} {ty - 20:.0f}, "
                         f"{tx - flip * 34:.0f} {ty - 14:.0f}",
                    "tip": [round(tx - flip * 34), round(ty - 14)], "dir": flip,
                    "ok": ty - sy > 90}
    return out


def cover_context(spec: Spec, style: dict, has_media: bool, photo: dict | None = None,
                  cast: dict | None = None) -> dict:
    cv = style["cover"]
    hv = cv["hero"]
    parts = title_parts(spec)
    keyword = parts["keyword"].upper() if cv["keyword_uppercase"] else parts["keyword"]
    c = spec.cover
    want = (c.layout if c and c.layout else None)
    hero = (photo or cast) and want != "text"
    if hero:
        tb = text_block(parts, keyword, cv, hv["title_size"], hv["title_min_size"], hv["keyword_size"],
                        hv["keyword_min_size"])
        text_bottom = hv["text_top"] + tb["height"]
    else:
        tb = text_block(parts, keyword, cv, cv["title_size"], cv["title_min_size"], cv["keyword_size"],
                        cv["keyword_min_size"])
        text_bottom = None
    flip = _flip(spec.slug)

    ec, wm, pill = style["end_card"] or {}, style["watermark"], style["series_pill"]
    label = compose.series_label(spec, style)
    c1, c2 = style["palette"][0]
    return {
        "style": style, "cv": cv, "hv": hv, "font_files": compose.FONT_FILES, "slug": spec.slug,
        "lead": parts["lead"], "title": parts["title"], "keyword": keyword, "subtitle": parts["subtitle"],
        "title_size": tb["title_size"], "keyword_size": tb["keyword_size"], "c1": c1, "c2": c2,
        "media": has_media, "boxed": cv["keyword_style"] == "box", "flip": flip,
        "hero": hero_layout(cv, hv, text_bottom, photo, cast, flip) if hero else None,
        "photo": photo if hero else None, "cast": cast if hero else None,
        "badge": (c.badge if c else None) if hero else None,
        "pill": {"label": label, "bg": pill.get("bg") or style["accent_color"],
                 "color": pill.get("color") or style["stroke_color"]} if label else None,
        "logo": compose._brand_file(ec.get("logo")), "wordmark": compose._brand_file(ec.get("wordmark")),
        "disc": ec.get("disc_color"),
        # without a wordmark image, the style's handle text (watermark.text) stands in
        "handle": None if ec.get("wordmark") else wm.get("text"),
    }


def hook_still(spec: Spec, project_dir: Path, assets: dict | None, out: Path, at_s: float) -> bool:
    """The hook's first b-roll shot (else its stage backdrop) as a still at `out`. False if neither."""
    media = ((assets or {}).get("scenes") or {}).get(spec.scenes[0].id) or {}
    if not media.get("kind"):
        bd = (media.get("backdrop") or {}).get("file")
        if bd and (project_dir / bd).exists():
            ffmpeg.run(["-i", str(project_dir / bd), "-frames:v", "1", "-q:v", "2", str(out)])
            return out.exists()
        return False
    shot = (media.get("shots") or [media])[0]
    src = project_dir / shot["file"]
    if not src.exists():
        return False
    if shot["kind"] == "video":
        t = float(shot.get("offset_s") or 0) + at_s
        ffmpeg.run(["-ss", f"{t:.2f}", "-i", str(src), "-frames:v", "1", "-q:v", "2", str(out)])
        return out.exists()
    ffmpeg.run(["-i", str(src), "-frames:v", "1", "-q:v", "2", str(out)])
    return out.exists()


def _own_cover_photo(spec: Spec) -> Path | None:
    """cover.image, else <photos dir>/<slug>/cover.<ext> (or cover-<anything>.<ext>)."""
    if spec.cover and spec.cover.image:
        p = Path(spec.cover.image).expanduser()
        p = p if p.is_absolute() else ROOT / p
        if p.is_file():
            return p
        log.warning("cover.image not found: %s", p)
    folder = brief.photo_dir(spec)
    if folder.is_dir():
        hits = sorted(p for p in folder.iterdir() if p.suffix.lower() in brief.EXTS
                      and (p.stem.lower() == "cover" or p.stem.lower().startswith("cover-")))
        if hits:
            return hits[0]
    return None


def _stage_cutouts(spec: Spec, project_dir: Path, assets: dict | None) -> list[Path]:
    """The video's stage cut-outs, the hook's first, in scene order."""
    scenes = (assets or {}).get("scenes") or {}
    out = []
    for s in spec.scenes:
        for row in (scenes.get(s.id) or {}).get("stage") or []:
            if row and row.get("render") == "cutout" and row.get("file") and (project_dir / row["file"]).exists():
                out.append(project_dir / row["file"])
    return out


def hero_photo(spec: Spec, project_dir: Path, assets: dict | None, still: Path | None, hv: dict) -> dict | None:
    """The cover's subject photo: {file, kind: cutout|card, w, h}, or None."""
    own = _own_cover_photo(spec)
    if own:
        f, _ = cutout.cut_out(own)
        return _photo_row(f, "cutout") if f else _photo_row(cutout.card(own), "card")
    stage = _stage_cutouts(spec, project_dir, assets)
    if stage:
        return _photo_row(stage[0], "cutout")
    if still and hv["lift_still"]:
        f, why = cutout.cut_out(still)
        if f and not boxy(f, hv["boxy_fill"], hv["boxy_edge"]):
            return _photo_row(f, "cutout")
        log.info("cover: no clean subject lifted from the hook still (%s); using it as a photo card",
                 why if not f else "the mask is a box")
        return _photo_row(card_crop(still, hv["card_aspect"]), "card")
    return None


def boxy(sticker: Path, max_fill: float, max_edge: float, inset: int = 16) -> bool:
    """True when a lifted 'subject' looks like a slab of the frame: it fills most of its own box, or
    two of its sides run straight along the box (a line `inset` px in is mostly opaque)."""
    with Image.open(sticker) as im:
        im = im.convert("RGBA")
        if cutout.coverage(im) > max_fill:
            return True
        a, (w, h) = im.getchannel("A"), im.size
        lines = [a.crop((0, inset, w, inset + 1)), a.crop((0, h - 1 - inset, w, h - inset)),
                 a.crop((inset, 0, inset + 1, h)), a.crop((w - 1 - inset, 0, w - inset, h))]
        straight = sum(1 for ln in lines if sum(ln.histogram()[129:]) / max(ln.width * ln.height, 1) > max_edge)
        return straight >= 2


def card_crop(src: Path, aspect: float) -> Path:
    """A centre crop of `src` at width/height `aspect` (a photo card), next to it as card.jpg."""
    out = src.with_name("card.jpg")
    with Image.open(src) as im:
        im = im.convert("RGB")
        w = min(im.width, round(im.height * aspect))
        h = round(w / aspect)
        x, y = (im.width - w) // 2, max(0, round((im.height - h) * 0.4))
        im.crop((x, y, x + w, y + h)).save(out, quality=90)
    return out


def _photo_row(f: Path, kind: str) -> dict:
    with Image.open(f) as im:
        return {"file": f, "kind": kind, "w": im.width, "h": im.height}


def hero_mascot(spec: Spec, style: dict, hv: dict) -> dict | None:
    """{who, pose, svg, aspect} for the cover's mascot, or None (no cast, or cover.mascot 'none')."""
    pose = (spec.cover.mascot if spec.cover and spec.cover.mascot else None) or hv["mascot_pose"]
    if not pose or pose == "none":
        return None
    st = mascot.with_cast(style, spec)
    cast = mascot.names(st)
    if not cast:
        return None
    who = spec.cover.who if spec.cover and spec.cover.who in cast else None
    who = who or mascot.speaker(spec, spec.scenes[0], st) or cast[0]
    if who not in cast:
        who = cast[0]
    m = next(m for m in mascot.settings(st)["cast"] if m["name"] == who)
    poses = mascot._poses(m["dir"])
    pose = pose if pose in poses else "netral"
    svg = poses[pose]
    return {"who": who, "pose": pose, "svg": mascot._scoped(svg, f"cv-{who}"), "aspect": mascot._aspect(svg),
            "outline": mascot.settings(st).get("outline")}


def build(spec: Spec, project_dir: Path, assets: dict | None) -> Path:
    """Write cover/ (index.html + files) for this spec; returns the directory."""
    style = config.style(spec.style)
    cv = style["cover"]
    out = project_dir / "cover"
    if out.exists():
        shutil.rmtree(out)
    (out / "fonts").mkdir(parents=True)
    has_media = hook_still(spec, project_dir, assets, out / "bg.jpg", cv["still_at_s"])
    layout = spec.cover.layout if spec.cover else None
    photo = cast = None
    if layout != "text":
        photo = hero_photo(spec, project_dir, assets, out / "bg.jpg" if has_media else None, cv["hero"])
        cast = hero_mascot(spec, style, cv["hero"])
    if photo:
        name = "hero" + photo["file"].suffix.lower()
        shutil.copyfile(photo["file"], out / name)
        photo = {**photo, "src": name}
    ctx = cover_context(spec, style, has_media, photo, cast)

    tdir = TEMPLATES_DIR / spec.style
    env = Environment(loader=FileSystemLoader(tdir if (tdir / "cover.html.j2").is_file() else TEMPLATES_DIR / "default"),
                      undefined=StrictUndefined, autoescape=True, trim_blocks=True, lstrip_blocks=True)
    env.filters["rgba"] = compose.rgba
    (out / "index.html").write_text(env.get_template("cover.html.j2").render(**ctx), encoding="utf-8")
    shutil.copyfile(compose.NODE_MODULES / "gsap" / "dist" / "gsap.min.js", out / "gsap.min.js")
    font_src = compose.NODE_MODULES / "@fontsource" / "plus-jakarta-sans" / "files"
    for f in compose.FONT_FILES.values():
        shutil.copyfile(font_src / f, out / "fonts" / f)
    for f in (ctx["logo"], ctx["wordmark"]):
        if f:
            (out / "brand").mkdir(exist_ok=True)
            shutil.copyfile(f["path"], out / f["src"])
    return out


def run(spec: Spec, project_dir: Path, assets: dict | None, renderer: HyperFramesRenderer | None = None) -> Path:
    comp = build(spec, project_dir, assets)
    return (renderer or HyperFramesRenderer()).still(comp, project_dir / "cover.png")
