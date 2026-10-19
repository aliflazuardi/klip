"""Designed cover.png: a single-frame HTML composition, snapshotted with HyperFrames.

Layout: series pill, title whose last line is the keyword (bigger, accent colour), subtitle,
logo + wordmark, over a darkened b-roll still from the hook (else the style's first palette gradient). Everything sits in the centre 3:4 band
(y 240–1680) that profile grids show. Brand parts come from the style (klip.yaml or a brand pack).

Writes cover/ in the project dir (index.html, fonts/, brand/, bg.jpg) and cover.png.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from klip import config, ffmpeg
from klip.engines.render.hyperframes import HyperFramesRenderer
from klip.paths import TEMPLATES_DIR
from klip.spec import Spec
from klip.stages import compose

MAX_KEYWORD_WORDS = 3


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


def cover_context(spec: Spec, style: dict, has_media: bool) -> dict:
    cv = style["cover"]
    parts = title_parts(spec)
    keyword = parts["keyword"].upper() if cv["keyword_uppercase"] else parts["keyword"]
    width = cv["width"]
    if parts["lead"]:
        title_size = fit_size(parts["lead"], cv["title_size"], cv["title_min_size"], width, cv["char_em"])
    else:
        title_size = fit_size([parts["title"]], cv["title_size"], cv["title_min_size"], width, cv["char_em"],
                              cv["title_max_lines"])
    kw_em = cv["caps_em"] if cv["keyword_uppercase"] else cv["char_em"]
    # keyword stays on one line: shrink, and only wrap once it hits the minimum size
    keyword_size = fit_size([keyword], cv["keyword_size"], cv["keyword_min_size"], width, kw_em)

    ec, wm, pill = style["end_card"] or {}, style["watermark"], style["series_pill"]
    label = compose.series_label(spec, style)
    c1, c2 = style["palette"][0]
    return {
        "style": style, "cv": cv, "font_files": compose.FONT_FILES, "slug": spec.slug,
        "lead": parts["lead"], "title": parts["title"], "keyword": keyword, "subtitle": parts["subtitle"],
        "title_size": title_size, "keyword_size": keyword_size, "c1": c1, "c2": c2,
        "media": has_media,
        "pill": {"label": label, "bg": pill.get("bg") or style["accent_color"],
                 "color": pill.get("color") or style["stroke_color"]} if label else None,
        "logo": compose._brand_file(ec.get("logo")), "wordmark": compose._brand_file(ec.get("wordmark")),
        "disc": ec.get("disc_color"),
        # without a wordmark image, the style's handle text (watermark.text) stands in
        "handle": None if ec.get("wordmark") else wm.get("text"),
    }


def hook_still(spec: Spec, project_dir: Path, assets: dict | None, out: Path, at_s: float) -> bool:
    """The hook's first b-roll shot as a 1080x1920 still at `out`. False if the hook has no media."""
    media = ((assets or {}).get("scenes") or {}).get(spec.scenes[0].id) or {}
    if not media.get("kind"):
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


def build(spec: Spec, project_dir: Path, assets: dict | None) -> Path:
    """Write cover/ (index.html + files) for this spec; returns the directory."""
    style = config.style(spec.style)
    out = project_dir / "cover"
    if out.exists():
        shutil.rmtree(out)
    (out / "fonts").mkdir(parents=True)
    has_media = hook_still(spec, project_dir, assets, out / "bg.jpg", style["cover"]["still_at_s"])
    ctx = cover_context(spec, style, has_media)

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
