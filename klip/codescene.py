"""Code scenes (visual.type "code", director mode): a scene whose look and motion are a file Claude writes.

The file (repo-relative, usually specs/<slug>/<scene-id>.html) holds markup, any <style> blocks and
one <script>. Compose scopes the CSS to the scene, rewrites '@asset/' paths, and runs the script with
the scene kit `k` (templates/default/scenes/code_kit.js.j2; the contract is docs/CODE-SCENES.md).
The look bible (palette, fonts, texture, motion) is resolved here: klip.yaml code.look, then the
style's look_bible, then the spec's.
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from pathlib import Path

from markupsafe import Markup

from klip import config
from klip.captions import norm, tokenize
from klip.paths import RENDERER_DIR, ROOT
from klip.spec import Scene, Spec
from klip.stage import _noise_svg

STYLE_RE = re.compile(r"<style\b[^>]*>(.*?)</style>", re.S | re.I)
SCRIPT_RE = re.compile(r"<script\b([^>]*)>(.*?)</script>", re.S | re.I)
CUE_RE = re.compile(r"""\bk\.at\(\s*(["'`])(.+?)\1""")
MASCOT_RE = re.compile(r"""\bk\.(?:mascot|spotlight)\(\s*(["'`])(.+?)\1""")
POSE_RE = re.compile(r"""(?:\.pose\(\s*|\bpose:\s*)(["'`])(.+?)\1""")
ASSET = "@asset/"

# Script patterns that break frame-exact rendering (every frame is a seek of the timeline).
FORBIDDEN = [
    (r"\bMath\.random\b", "Math.random (use k.rand(seed))"),
    (r"\bDate\b", "Date (time comes from the timeline)"),
    (r"\bperformance\.now\b", "performance.now (time comes from the timeline)"),
    (r"\brequestAnimationFrame\b", "requestAnimationFrame (use k.frame(fn))"),
    (r"\bset(Timeout|Interval)\b", "setTimeout / setInterval (put it on k.tl)"),
    (r"\bfetch\s*\(|\bXMLHttpRequest\b|\bWebSocket\b", "network access (bundle files with visual.code.assets)"),
    (r"\bimport\s*\(|^\s*import\s", "imports (use visual.code.libs)"),
    (r"window\.__timelines", "registering timelines (use k.tl)"),
    (r"\bdocument\.write\b", "document.write"),
    (r"querySelector(All)?\(\s*`[^`]*\$\{", "template literals in querySelector (HyperFrames' render lint rejects "
                                              "them; build the selector with + or use k.$)"),
]
# CSS that animates on wall-clock time instead of the timeline.
CSS_WARN = [(r"@keyframes|\banimation\s*:", "CSS animations (animate on k.tl instead)"),
            (r"\btransition\s*:", "CSS transitions (animate on k.tl instead)")]
URL_RE = re.compile(r"https?://(?!www\.w3\.org/)[^\s\"')]+")


class CodeSceneError(RuntimeError):
    pass


def cfg(key: str):
    return config.get(f"code.{key}")


@dataclass
class Fragment:
    markup: str
    css: str
    js: str


def path_of(scene: Scene) -> Path:
    return ROOT / scene.visual.code.file


def parse(text: str) -> Fragment:
    """Split a scene file into markup, CSS (all <style> blocks) and the script body."""
    scripts = SCRIPT_RE.findall(text)
    if len(scripts) != 1:
        raise CodeSceneError(f"a code scene needs exactly one <script> (found {len(scripts)})")
    attrs, js = scripts[0]
    if "src=" in attrs:
        raise CodeSceneError("the <script> must be inline (no src=)")
    css = "\n".join(STYLE_RE.findall(text))
    markup = SCRIPT_RE.sub("", STYLE_RE.sub("", text)).strip()
    return Fragment(markup, css, js)


def load(scene: Scene) -> Fragment:
    """The scene file, with its `include` scripts in front of its own script."""
    p = path_of(scene)
    if not p.is_file():
        raise CodeSceneError(f"{scene.id}: code scene file not found: {scene.visual.code.file}")
    frag = parse(p.read_text(encoding="utf-8"))
    libs = []
    for inc in scene.visual.code.include:
        if not (ROOT / inc).is_file():
            raise CodeSceneError(f"{scene.id}: include not found: {inc}")
        libs.append(f"// ---- {inc}\n" + (ROOT / inc).read_text(encoding="utf-8"))
    return Fragment(frag.markup, frag.css, "\n".join([*libs, frag.js]))


def cues(js: str) -> list[str]:
    """The phrases a script times itself on: every literal k.at("…")."""
    return [m.group(2) for m in CUE_RE.finditer(js)]


def _phrase_at(tokens: list[str], phrase: str) -> int | None:
    want = [norm(t) for t in phrase.split() if norm(t)]
    have = [norm(t) for t in tokens]
    for i in range(len(have) - len(want) + 1):
        if want and have[i:i + len(want)] == want:
            return i
    return None


def lint_scene(scene: Scene, spec: Spec | None = None) -> list[tuple[str, str]]:
    """[(level, message)] for one code scene: the file parses, uses no time/network APIs, times itself
    on words the narration says, stays under code.max_kb, and its assets and fonts exist."""
    c = scene.visual.code
    out: list[tuple[str, str]] = []
    p = path_of(scene)
    if not p.is_file():
        return [("error", f"code scene file not found: {c.file}")]
    text = p.read_text(encoding="utf-8")
    if len(text.encode()) > cfg("max_kb") * 1024:
        out.append(("error", f"{c.file} is {len(text.encode()) // 1024} KB; keep a scene under {cfg('max_kb')} KB"))
    try:
        frag = parse(text)
    except CodeSceneError as e:
        return out + [("error", f"{c.file}: {e}")]
    for inc in c.include:
        if not inc.endswith(".js") or not (ROOT / inc).is_file():
            out.append(("error", f"visual.code.include: {inc} is not a .js file in the repo"))
        else:
            frag = Fragment(frag.markup, frag.css, (ROOT / inc).read_text(encoding="utf-8") + "\n" + frag.js)
    js = re.sub(r"//[^\n]*|/\*.*?\*/", "", frag.js, flags=re.S)
    for pat, what in FORBIDDEN:
        if re.search(pat, js, flags=re.M):
            out.append(("error", f"{c.file}: no {what}"))
    for pat, what in CSS_WARN:
        if re.search(pat, frag.css):
            out.append(("warning", f"{c.file}: {what}"))
    for u in sorted(set(URL_RE.findall(text))):
        out.append(("error", f"{c.file}: remote URL {u} (renders are offline; add the file to visual.code.assets)"))
    tokens = tokenize(scene.narration)
    for phrase in cues(frag.js):
        if _phrase_at(tokens, phrase) is None:
            out.append(("error", f"{c.file}: k.at({phrase!r}) is not in the narration"))
    sfx_dir = ROOT / config.get("sfx.dir")
    for cue in c.sfx:
        if _phrase_at(tokens, cue.at) is None:
            out.append(("error", f"visual.code.sfx: {cue.at!r} is not in the narration"))
        if not any((sfx_dir / f"{cue.sfx}{ext}").is_file() for ext in (".wav", ".mp3")):
            have = sorted({p.stem for p in sfx_dir.glob("*.*")}) if sfx_dir.is_dir() else []
            out.append(("error", f"visual.code.sfx: no effect {cue.sfx!r} in {config.get('sfx.dir')} "
                                 f"({', '.join(have) or 'empty'})"))
    names = {Path(a).name for a in c.assets}
    for a in c.assets:
        if not (ROOT / a).is_file():
            out.append(("error", f"visual.code.assets: {a} not found"))
    for ref in sorted(set(re.findall(re.escape(ASSET) + r"([\w.\-]+)", text))):
        if ref not in names:
            out.append(("error", f"{c.file}: {ASSET}{ref} is not in visual.code.assets"))
    if MASCOT_RE.search(js):
        from klip import mascot
        style = mascot.video_style(spec) if spec else config.style()
        cast = {m["name"]: m for m in mascot.settings(style).get("cast") or []}
        for _, name in MASCOT_RE.findall(js):
            if name not in cast:
                out.append(("error", f"{c.file}: mascot {name!r}: not in the style's mascot cast "
                                     f"({', '.join(cast) or 'none'})"))
        poses = {p for m in cast.values() for p in mascot._poses(m["dir"])}
        for _, pose in POSE_RE.findall(js):
            if cast and pose not in poses:
                out.append(("error", f"{c.file}: pose {pose!r} is not a mascot pose ({', '.join(sorted(poses))})"))
    if "three" in c.libs and not (RENDERER_DIR / "node_modules" / "three").is_dir():
        out.append(("error", "libs ['three'] needs three in renderer/ (run npm ci there)"))
    return out


# ---- world: one code layer under a run of code scenes

WORLD_ID = "world"


def world_run(spec: Spec) -> list[Scene]:
    """The consecutive code scenes the world runs under (spec.world.scenes, else every code scene)."""
    w = spec.world
    ids = [s.id for s in spec.scenes]
    picked = w.scenes or [s.id for s in spec.scenes if s.visual.type == "code"]
    if not picked:
        raise CodeSceneError("a world needs code scenes to run under")
    if missing := [i for i in picked if i not in ids]:
        raise CodeSceneError(f"world.scenes: no scene {', '.join(missing)}")
    if WORLD_ID in ids:
        raise CodeSceneError(f"a scene can't be called {WORLD_ID!r} when the spec has a world")
    idx = sorted(ids.index(i) for i in picked)
    if idx != list(range(idx[0], idx[-1] + 1)):
        raise CodeSceneError("world.scenes must be consecutive scenes")
    run = [spec.scenes[i] for i in idx]
    if not_code := [s.id for s in run if s.visual.type != "code"]:
        raise CodeSceneError(f"world.scenes must be code scenes ({', '.join(not_code)} isn't)")
    return run


def world_scene(spec: Spec) -> Scene:
    """The world as a code scene (for lint and compose): its narration is the whole run's."""
    w, run = spec.world, world_run(spec)
    return Scene.model_validate({"id": WORLD_ID, "template": "explain", "narration": " ".join(s.narration for s in run),
                                 "visual": {"type": "code", "code": {"file": w.file, "assets": w.assets,
                                                                     "include": w.include, "libs": w.libs}}})


# ---- look bible

def look(spec: Spec, style: dict) -> dict:
    """The resolved look bible: palette, fonts {role: family}, texture + strength, line, ease, tone."""
    out = copy.deepcopy(cfg("look"))
    out["palette"] = {**out["palette"], "accent": style["accent_color"], "emph": style["emphasis_color"]}
    own = spec.look_bible.model_dump(exclude_none=True) if spec.look_bible else {}
    layers = [style.get("look_bible") or {}]
    mine = style.get("looks") or {}                 # the style's own take on a preset (its palette), or its own looks
    if preset := own.pop("preset", None) or layers[0].get("preset"):
        if preset not in cfg("looks") and preset not in mine:
            raise CodeSceneError(f"look_bible.preset: unknown look {preset!r} (klip.yaml code.looks: "
                                 f"{', '.join(sorted({*cfg('looks'), *mine}))})")
        layers += [cfg("looks").get(preset) or {}, mine.get(preset) or {}]
    layers.append(own)
    for layer in layers:
        for k, v in layer.items():
            if k in ("palette", "fonts"):
                out[k] = {**out[k], **{a: b for a, b in (v or {}).items() if b is not None}}
            elif v is not None and k != "preset":
                out[k] = v
    fonts = cfg("fonts")
    for role, key in out["fonts"].items():
        if key is not None and key not in fonts:
            raise CodeSceneError(f"look_bible.fonts.{role}: unknown font {key!r} (klip.yaml code.fonts: "
                                 f"{', '.join(fonts)})")
    out["families"] = {role: fonts[key]["family"] for role, key in out["fonts"].items() if key}
    if out.get("texture_strength") is None:
        out["texture_strength"] = cfg("textures")[out["texture"]]
    out["ease"] = cfg("eases")[out["motion"]]
    out["tone"] = "light" if luminance(out["palette"]["bg"]) >= 0.5 else "dark"
    pal = out["palette"]           # text on a paper card: ink if it contrasts with paper, else the bg colour
    if "paper-ink" not in pal and "paper" in pal:
        pal["paper-ink"] = pal["ink"] if abs(luminance(pal["paper"]) - luminance(pal["ink"])) >= 0.4 else pal["bg"]
    return out


def luminance(hex_color: str) -> float:
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def font_faces() -> list[dict]:
    """@font-face rows for every font in code.fonts: {family, weight, style, file, src}."""
    rows = []
    for f in cfg("fonts").values():
        for w in f["weights"]:
            for st in ("normal", "italic") if f["italic"] else ("normal",):
                name = f"{f['package']}-latin-{w}-{st}.woff2"
                rows.append({"family": f["family"], "weight": w, "style": st, "file": name,
                             "src": RENDERER_DIR / "node_modules" / "@fontsource" / f["package"] / "files" / name})
    return rows


def css_vars(lk: dict) -> Markup:
    """:root custom properties for the look: --k-<colour>, --k-display/body/mono, --k-font-<key>, --k-line."""
    out = [f"--k-{k}: {v};" for k, v in lk["palette"].items()]
    for role in ("display", "body", "mono"):
        if fam := lk["families"].get(role):
            out.append(f'--k-{role}: "{fam}", system-ui, sans-serif;')
    out += [f'--k-font-{k}: "{f["family"]}", system-ui, sans-serif;' for k, f in cfg("fonts").items()]
    out.append(f"--k-line: {lk['line']}px;")
    return Markup(" ".join(out))


def texture_css(name: str, strength: float) -> Markup:
    """Declarations for a .k-tex overlay of this texture (drawn above the scene, under the captions)."""
    s = round(float(strength), 3)
    if name == "none" or s <= 0:
        return Markup("display: none;")
    fine, coarse = _noise_svg("0.85 0.85", 3), _noise_svg("0.006 0.009", 2)
    vignette = f"radial-gradient(ellipse at 50% 45%, rgba(0,0,0,0) 55%, rgba(40,25,10,{round(0.45 * s, 3)}) 100%)"
    css = {
        "paper": f"background-image: {vignette}, url(\"{fine}\"); mix-blend-mode: multiply; opacity: {min(1, s * 0.9)};",
        "watercolor": f"background-image: {vignette}, url(\"{coarse}\"), url(\"{fine}\"); background-size: 100% 100%, "
                      f"140% 140%, auto; mix-blend-mode: multiply; opacity: {min(1, s * 0.8)};",
        "halftone": "background-image: radial-gradient(circle at center, rgba(0,0,0,.55) 0 1.6px, rgba(0,0,0,0) 2.2px); "
                    f"background-size: 7px 7px; mix-blend-mode: multiply; opacity: {s};",
        "grain": f"background-image: url(\"{fine}\"); background-size: 600px 1020px; mix-blend-mode: overlay; "
                 f"opacity: {s};",
        "hud": "background-image: repeating-linear-gradient(0deg, rgba(255,255,255,.05) 0 1px, rgba(0,0,0,0) 1px 4px), "
               f"radial-gradient(ellipse at 50% 50%, rgba(0,0,0,0) 50%, rgba(0,0,0,.85) 100%); opacity: {s};",
        "riso": f"background-image: url(\"{fine}\"), url(\"{coarse}\"); mix-blend-mode: multiply; "
                f"filter: sepia(.4) saturate(2); opacity: {min(1, s * 0.8)};",
        "film": f"background-image: radial-gradient(ellipse at 50% 48%, rgba(0,0,0,0) 40%, rgba(0,0,0,.75) 100%), "
                f"url(\"{fine}\"); background-size: 100% 100%, 1200px 2040px; mix-blend-mode: hard-light; "
                f"opacity: {s};",
    }[name]
    return Markup(css)


# ---- compose

def safe_area(caption_top: float) -> dict:
    top = float(cfg("safe_top"))
    bottom = caption_top - float(cfg("safe_gap"))
    return {"x": 60, "y": top, "w": 900, "h": round(bottom - top, 1), "captionTop": caption_top}


def scoped_css(scene_id: str, css: str) -> Markup:
    css = css.replace(ASSET, f"code/{scene_id}/")
    return Markup(f"@scope (#sc-{scene_id}) {{\n{css}\n}}") if css.strip() else Markup("")


def scene_ctx(scene: Scene, t: dict, words: list[dict], lk: dict, caption_top: float) -> dict:
    """Template context for a code scene: its markup, scoped CSS, script, texture and kit metadata."""
    c = scene.visual.code
    frag = load(scene)
    sid = scene.id
    start, dur = t["start_ms"], t["duration_ms"]
    rel = [{"text": w["text"].strip(), "t": round((w["startMs"] - start) / 1000, 3),
            "end": round((w["endMs"] - start) / 1000, 3)} for w in words]
    texture = c.texture or lk["texture"]
    strength = lk["texture_strength"] if c.texture is None else cfg("textures")[texture]
    return {
        "markup": Markup(frag.markup.replace(ASSET, f"code/{sid}/")),
        "css": scoped_css(sid, frag.css),
        "js": Markup(frag.js.replace(ASSET, f"code/{sid}/")),
        "texture": texture, "texture_css": texture_css(texture, strength),
        "captions": c.captions, "libs": list(c.libs),
        "assets": [{"path": str(ROOT / a), "src": f"code/{sid}/{Path(a).name}"} for a in c.assets],
        "meta": {"id": sid, "start": round(start / 1000, 3), "dur": round(dur / 1000, 3), "words": rel,
                 "fps": config.get("render.fps", 30),
                 "text": scene.on_screen_text or "", "emphasis": scene.emphasis, "hook": scene.template == "hook", "texture": texture,
                 "safe": safe_area(caption_top)},
    }


def layout(style: dict, sc: dict, brand: dict, caption_top: float) -> dict:
    """Where the kit puts things in this scene: the headline's top (below the series pill when it shows
    here), the scrims, each mascot's spot (as on stage scenes) and the outro badge if it lands here."""
    from klip import mascot
    kit = cfg("kit")
    top = float(kit["headline"]["top"])
    pill = brand.get("series")
    if pill and any(sp["start"] < sc["end"] - 1e-3 and sp["end"] > sc["start"] + 1e-3 for sp in pill["spans"]):
        top = max(top, pill["top"] + pill["font_size"] * 1.25 + 20 + float(kit["headline"]["pill_gap"]))
    c = mascot.settings(style)
    cast = []
    if c.get("cast"):
        h, y = float(c["height"]), mascot.top(style, caption_top)
        for m in c["cast"]:
            w = round(h * mascot._aspect(mascot._poses(m["dir"])["netral"]), 1)
            x = mascot.SAFE_X[0] + float(c["inset_px"]) if m.get("side", "left") == "left" \
                else mascot.SAFE_X[1] - float(c["inset_px"]) - w
            cast.append({"name": m["name"], "x": round(x, 1), "y": round(y, 1), "w": w, "h": h})
    out = {"headlineTop": round(top, 1), "cast": cast,
           "scrim": {"top": kit["scrim"]["top_px"], "bottomFrom": caption_top - kit["scrim"]["bottom_above"],
                     "bottom": kit["scrim"]["bottom_px"]}}
    o = brand.get("outro")
    if o and sc["start"] <= o["start"] < sc["end"]:
        out["outro"] = {"t": round(o["start"] - sc["start"], 3), "top": o["top"]}
    return out


def scene_uses_mascots(scene: Scene) -> bool:
    """The scene's code file (with its includes) places the mascots; False when it can't be read."""
    c = scene.visual.code
    p = ROOT / c.file if c else None
    if not p or not p.is_file():
        return False
    js = "".join((ROOT / i).read_text(encoding="utf-8") for i in c.include if (ROOT / i).is_file())
    try:
        return uses_mascots(js + parse(p.read_text(encoding="utf-8")).js)
    except CodeSceneError:
        return False


def uses_mascots(js: str) -> bool:
    """The script places mascots: k.mascot("…"), k.spotlight("…") or the kit's k.cast()."""
    return bool(MASCOT_RE.search(js) or re.search(r"\bk\.cast\(", js))


def tag_feet(svg: str) -> str:
    """Mark a pose's two feet for the walk cycle: class k-foot + k-foot-l / k-foot-r on the two lowest
    ellipses (centre in the bottom 12% of the viewBox), unless the SVG already marks them (foot-l /
    foot-r). An SVG with another foot count is left as it is (the rig then walks with its body only)."""
    if "foot-l" in svg:
        return svg.replace('class="foot-l', 'class="k-foot k-foot-l').replace('class="foot-r', 'class="k-foot k-foot-r')
    m = re.search(r'viewBox="\s*[-\d.]+\s+[-\d.]+\s+[\d.]+\s+([\d.]+)', svg)
    if not m:
        return svg
    h = float(m.group(1))
    feet = [x for x in re.finditer(r'<ellipse\b([^>]*)>', svg)
            if (cy := re.search(r'\bcy="([\d.]+)"', x.group(1))) and float(cy.group(1)) >= 0.88 * h
            and "class=" not in x.group(1)]
    if len(feet) != 2:
        return svg
    feet.sort(key=lambda x: float(re.search(r'\bcx="([\d.]+)"', x.group(1)).group(1)))
    for side, x in sorted(zip("lr", feet), key=lambda p: -p[1].start()):     # back to front: offsets hold
        svg = svg[:x.start()] + f'<ellipse class="k-foot k-foot-{side}"' + x.group(1) + ">" + svg[x.end():]
    return svg


def cast_ctx(style: dict) -> dict:
    """The style's mascot cast for k.mascot: {name: {poses: {pose: svg}, aspect, mirror, voice}, outline}."""
    from klip import mascot
    c = mascot.settings(style)
    out = {}
    for m in c.get("cast") or []:
        svgs = mascot._poses(m["dir"])
        out[m["name"]] = {"poses": {p: tag_feet(mascot._scoped(svg, f"ms-{m['name']}-{p}")) for p, svg in svgs.items()},
                          "aspect": round(mascot._aspect(svgs["netral"]), 4), "mirror": m.get("side") == "right",
                          "voice": m.get("voice")}
    return {"cast": out, "outline": c.get("outline"), "bob_px": c["bob_px"], "bob_s": c["bob_s"]}


def mascot_meta(spec: Spec, scene: Scene, style: dict, words: list[dict], start_ms: float) -> dict:
    """Per scene: who mouths the narration, their mouth flaps and everyone's blinks (scene seconds)."""
    from klip import mascot
    c = mascot.settings(style)
    s0 = start_ms / 1000
    who = mascot.speaker(spec, scene, style)
    end = max([w["endMs"] / 1000 - s0 for w in words], default=0) + 1
    blinks = {n: [round(t, 3) for t in mascot._blinks([(0.0, end)], f"{n}-{scene.id}", c["blink_s"])]
              for n in mascot.names(style)}
    return {"speaker": who, "mouth": {who: flaps(style, words, s0)} if who else {}, "blinks": blinks}


def flaps(style: dict, words: list[dict], s0: float) -> list[list[float]]:
    """Mouth (open, close) pairs for these words, in seconds from s0."""
    from klip import mascot
    return [[round(a - s0, 3), round(b - s0, 3)] for a, b in mascot._flaps(words, mascot.settings(style)["mouth"])]


def sfx_cues(scene: Scene, words: list[dict]) -> list[dict]:
    """[{t (absolute s), sfx}] for the scene's visual.code.sfx, from the voice's word times."""
    tokens = [w["text"].strip() for w in words]
    out = []
    for cue in scene.visual.code.sfx:
        i = _phrase_at(tokens, cue.at)
        if i is not None:
            out.append({"t": round(max(words[i]["startMs"] / 1000 + cue.offset_s, 0.0), 3), "sfx": cue.sfx})
    return out


def cue_times(scene: Scene, words: list[dict]) -> list[tuple[float, str]]:
    """(absolute seconds, phrase) for each k.at cue in the scene's script, from the voice's word times."""
    tokens = [w["text"].strip() for w in words]
    out = []
    for phrase in cues(load(scene).js):
        i = _phrase_at(tokens, phrase)
        if i is not None:
            out.append((round(words[i]["startMs"] / 1000, 3), phrase))
    return out


# ---- libraries

_EXPORT_RE = re.compile(r"^export\s*\{([^}]*)\}\s*(?:from\s*['\"]([^'\"]+)['\"])?\s*;?\s*$", re.M)
_IMPORT_RE = re.compile(r"^import\s*\{([^}]*)\}\s*from\s*['\"]\./three\.core\.js['\"]\s*;?\s*$", re.M)


def _pairs(names: str) -> list[tuple[str, str]]:
    out = []
    for item in names.split(","):
        if item := item.strip():
            a, _, b = item.partition(" as ")
            out.append((a.strip(), (b or a).strip()))
    return out


def three_script() -> str:
    """Three.js (ESM-only) as a classic script that sets window.THREE, so it loads before the
    timeline is built. A two-file "bundle": three.core.js wrapped as an object, three.module.js on it."""
    build = RENDERER_DIR / "node_modules" / "three" / "build"
    core, module = (build / "three.core.js").read_text(encoding="utf-8"), (build / "three.module.js").read_text(encoding="utf-8")
    core_exports: list[tuple[str, str]] = []
    for m in _EXPORT_RE.finditer(core):
        core_exports += _pairs(m.group(1))
    core = _EXPORT_RE.sub("", core)
    result: list[str] = []
    for m in _EXPORT_RE.finditer(module):
        if m.group(2):
            result += [f"{b}: __core.{a}" for a, b in _pairs(m.group(1))]
        else:
            result += [f"{b}: {a}" for a, b in _pairs(m.group(1))]
    module = _EXPORT_RE.sub("", module)
    module = _IMPORT_RE.sub(lambda m: "const { " + ", ".join(f"{a}: {b}" for a, b in _pairs(m.group(1))) + " } = __core;",
                            module)
    if re.search(r"^\s*(import|export)\s", core + module, flags=re.M):
        raise CodeSceneError("three.js build has imports/exports Klip can't flatten; pin another three version")
    core_obj = ", ".join(f"{b}: {a}" for a, b in core_exports)
    return ("window.THREE = (function () {\n\"use strict\";\nconst __core = (function () {\n\"use strict\";\n"
            f"{core}\nreturn {{ {core_obj} }};\n}})();\n{module}\nreturn {{ {', '.join(result)} }};\n}})();\n")
