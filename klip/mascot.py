"""Mascots: brand-pack characters who stand above the stage captions and "explain" the video.

A style's `mascot.cast` lists the characters; each is a folder of pose SVGs (`netral.svg` required).
This module turns a composed video (scene contexts + word timings) into a plan per mascot: when
it's visible, which pose shows when, when its mouth moves (the scene's speaker, per spoken word),
and when it blinks. Pure data; templates/default/index.html.j2 draws and animates it.
"""

from __future__ import annotations

import hashlib
import re
from functools import cache
from pathlib import Path

from klip import shots
from klip.spec import Scene, Spec

SAFE_X = (60, 960)


class MascotError(RuntimeError):
    pass


def settings(style: dict) -> dict:
    return style.get("mascot") or {}


def names(style: dict) -> list[str]:
    return [m["name"] for m in settings(style).get("cast") or []]


@cache
def _poses(folder: str) -> dict[str, str]:
    d = Path(folder)
    if not d.is_dir():
        raise MascotError(f"mascot folder not found: {d}")
    out = {p.stem: p.read_text(encoding="utf-8") for p in sorted(d.glob("*.svg"))}
    if "netral" not in out:
        raise MascotError(f"mascot folder {d} needs a netral.svg (the neutral pose)")
    return out


def poses(style: dict, who: str) -> list[str]:
    m = next((m for m in settings(style).get("cast") or [] if m["name"] == who), None)
    return sorted(_poses(m["dir"])) if m else []


def _scoped(svg: str, prefix: str) -> str:
    """Make a pose's ids unique in the page (clip paths etc.): id="x" → id="<prefix>-x", url(#x) too."""
    svg = re.sub(r"<\?xml[^>]*\?>", "", svg).strip()
    ids = set(re.findall(r'\bid="([^"]+)"', svg))
    for i in ids:
        svg = re.sub(rf'\bid="{re.escape(i)}"', f'id="{prefix}-{i}"', svg)
        svg = svg.replace(f"url(#{i})", f"url(#{prefix}-{i})").replace(f'href="#{i}"', f'href="#{prefix}-{i}"')
    return re.sub(r"<svg\b", '<svg width="100%" height="100%" preserveAspectRatio="xMidYMax meet"', svg, count=1)


def _aspect(svg: str) -> float:
    m = re.search(r'viewBox="\s*[-\d.]+\s+[-\d.]+\s+([\d.]+)\s+([\d.]+)', svg)
    return float(m.group(1)) / float(m.group(2)) if m else 1.0


def _h(*parts) -> float:
    return int(hashlib.sha256(":".join(map(str, parts)).encode()).hexdigest()[:8], 16) / 0xFFFFFFFF


def active(scene: Scene, style: dict) -> bool:
    """Mascots show on stage scenes of a style with a cast, unless the scene hides them."""
    return bool(settings(style).get("cast")) and scene.visual.type == "stage" and not (scene.mascot and scene.mascot.hide)


def top(style: dict, caption_top: float, scale: float = 1.0) -> float:
    """y of the mascots' top edge (they stand on the captions), at a scene's mascot scale."""
    c = settings(style)
    return caption_top - float(c["gap_px"]) - float(c["height"]) * scale


def shown(scene: Scene, style: dict) -> list[str]:
    """The mascots visible in a scene (its `show`, within the video's cast)."""
    if not active(scene, style):
        return []
    cast = names(style)
    pick = scene.mascot.show if scene.mascot and scene.mascot.show is not None else None
    return [n for n in cast if pick is None or n in pick]


def scale(scene: Scene) -> float:
    return scene.mascot.scale if scene.mascot else 1.0


def with_cast(style: dict, spec: Spec) -> dict:
    """The style with its mascot cast narrowed to the spec's choice (`mascots`: unset/true = all,
    false = none, a list = those names)."""
    pick = spec.mascots
    if pick is None or pick is True or not settings(style).get("cast"):
        return style
    keep = [m for m in settings(style)["cast"] if pick and m["name"] in pick]
    return {**style, "mascot": {**settings(style), "cast": keep}}


def video_style(spec: Spec) -> dict:
    from klip import config
    return with_cast(config.style(spec.style), spec)


def _voice_of(style: dict, who: str | None) -> str | None:
    return next((m.get("voice") for m in settings(style).get("cast") or [] if m["name"] == who), None)


def scene_voice(spec: Spec, scene: Scene, style: dict | None = None) -> str:
    """Who narrates a scene: its own `voice`, else the voice of its explicit mascot speaker (a cast
    member's `voice`), else the video's voice."""
    if scene.voice:
        return scene.voice
    style = style if style is not None else video_style(spec)
    if scene.mascot and scene.mascot.speaker and (v := _voice_of(style, scene.mascot.speaker)):
        return v
    return spec.voice


def speaker(spec: Spec, scene: Scene, style: dict) -> str | None:
    """The mascot who mouths a scene: the scene's explicit speaker; else the one cast member whose
    `voice` is the scene's voice; else the style's speaker for the template (if in the cast); else
    the only mascot. None = nobody."""
    cast = names(style)
    if scene.mascot and scene.mascot.speaker:
        return None if scene.mascot.speaker == "none" or scene.mascot.speaker not in cast else scene.mascot.speaker
    v = scene_voice(spec, scene, style)
    by_voice = [m["name"] for m in settings(style).get("cast") or [] if m.get("voice") == v]
    if len(by_voice) == 1:
        return by_voice[0]
    sp = settings(style).get("speaker") or {}
    who = sp.get(scene.template, sp.get("default"))
    if who in cast:
        return who
    return cast[0] if len(cast) == 1 else None


def plan(spec: Spec, scenes: list[dict], words: list[dict], style: dict, caption_top: float) -> list[dict] | None:
    """Per mascot: geometry, pose SVGs, pose segments [(t, pose)], visible spans, mouth flaps, blinks."""
    c = settings(style)
    cast = c.get("cast") or []
    if not cast:
        return None
    by_id = {s.id: s for s in spec.scenes}
    auto = c.get("auto") or {}
    h = float(c["height"])
    y = top(style, caption_top)
    events: dict[str, list[tuple[float, str, float | None]]] = {m["name"]: [] for m in cast}
    mouth: dict[str, list[tuple[float, float]]] = {m["name"]: [] for m in cast}
    spans: dict[str, list[tuple[float, float]]] = {m["name"]: [] for m in cast}
    sizes: dict[str, list[tuple[float, float]]] = {m["name"]: [] for m in cast}
    for sc in scenes:
        scene = by_id.get(sc["id"])
        if not scene or sc.get("hidden") or not (here := shown(scene, style)):
            continue
        t0, t1 = sc["start"], sc["end"]
        for name in here:
            spans[name].append((t0, t1))
            sizes[name].append((t0, scale(scene)))
        sw = [w for w in words if w["sceneId"] == scene.id]
        who = speaker(spec, scene, style)
        if who in mouth:
            mouth[who] += _flaps(sw, c["mouth"])
        if scene.template == "hook":
            for name, pose in (auto.get("hook") or {}).items():
                if name in events:
                    events[name].append((t0, pose, None))
        els = (sc.get("stage") or {}).get("elements", [])
        last_point = -1e9
        if auto.get("point") and who in events:
            for e in els:
                if (e["kind"] in _BIG or e.get("comp")) and e["start"] - last_point >= float(auto["point_gap_s"]):
                    events[who].append((e["start"], auto["point"], float(auto["point_hold_s"])))
                    last_point = e["start"]
        stamp = auto.get("stamp") or {}
        for e in els:
            if e["kind"] == "stamp" and (pose := stamp.get(scene.visual.elements[e["i"]].tone)):
                for name in events:
                    events[name].append((e["start"], pose, float(auto["stamp_hold_s"])))
        if scene.mascot:
            want = [p for p in scene.mascot.poses if p.at]
            found = dict(zip((id(p) for p in want), shots.anchor_times(sw, [p.at for p in want])))
            for p in scene.mascot.poses:
                t = found.get(id(p)) if p.at else None
                t = t / 1000 if t is not None else t0
                if p.who in events:
                    events[p.who].append((t, p.pose, p.hold_s))
    if not any(spans.values()):
        return None
    spans = {name: _merge_spans(v) for name, v in spans.items()}
    every = _merge_spans([x for v in spans.values() for x in v])
    # an outro overlay folds the cta into the scene before it: its speaker still says the closing line
    for sc in scenes:
        scene = by_id.get(sc["id"])
        if not (scene and sc.get("hidden") and scene.template == "cta"):
            continue
        if not any(a <= sc["start"] < b for a, b in every) or (scene.mascot and scene.mascot.hide):
            continue
        sw = [w for w in words if w["sceneId"] == scene.id]
        if (who := speaker(spec, scene, style)) in mouth:
            mouth[who] += _flaps(sw, c["mouth"])
        for name, pose in (auto.get("cta") or {}).items():
            if name in events:
                events[name].append((sc["start"], pose, SOFT))
    out = []
    for k, m in enumerate(cast):
        name = m["name"]
        svgs = _poses(m["dir"])
        w = round(h * _aspect(svgs["netral"]), 1)
        inset = float(c["inset_px"])
        x = SAFE_X[0] + inset if m.get("side", "left") == "left" else SAFE_X[1] - inset - w
        segs = _segments(events[name], set(svgs))
        side = m.get("side", "left")
        # scale changes per scene (grow/shrink from the outer bottom corner, so it stays on screen)
        steps = [(t, k) for i, (t, k) in enumerate(sizes[name]) if i == 0 or k != sizes[name][i - 1][1]]
        out.append({"name": name, "id": f"ms-{name}", "x": round(x, 1), "y": round(y, 1), "w": w, "h": h,
                    "mirror": side == "right", "origin": "0% 100%" if side == "left" else "100% 100%",
                    "scale0": steps[0][1] if steps else 1.0,
                    "scales": [{"t": round(t, 3), "s": k} for t, k in steps[1:]],
                    "poses": [{"name": p, "svg": _scoped(svg, f"ms-{name}-{p}")} for p, svg in svgs.items()],
                    "segments": segs, "spans": [{"start": a, "end": b} for a, b in spans[name]],
                    "mouth": mouth[name], "blinks": _blinks(spans[name], name, c["blink_s"]),
                    "bob_delay": round(_h(name, "bob") * float(c["bob_s"]), 3)})
    return out


_BIG = ("cutout", "photo", "person", "logo", "screenshot", "chart", "bar", "unit", "news")


def _flaps(words: list[dict], m: dict) -> list[tuple[float, float]]:
    """(open, close) times of the mouth: one flap per spoken word, two for a long word."""
    out = []
    for w in words:
        a, d = w["startMs"] / 1000, (w["endMs"] - w["startMs"]) / 1000
        n = 2 if d > float(m["double_s"]) else 1
        for k in range(n):
            t = a + d * k / n
            out.append((round(t, 3), round(t + min(d / n * float(m["share"]), float(m["open_s"])), 3)))
    return out


def _merge_spans(spans: list[tuple[float, float]]) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    for a, b in sorted(spans):
        if out and a - out[-1][1] < 0.05:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


SOFT = -1.0     # hold value of an automatic closing pose: it waits for a held reaction to finish


def _segments(events: list[tuple[float, str, float | None]], have: set[str]) -> list[dict]:
    """Pose timeline [{t, pose}] from events (t, pose, hold): a held pose returns to netral unless
    another pose starts first; a SOFT pose waits until a held pose before it has ended (so the
    closing pose doesn't cut a reaction short). Unknown poses are skipped (lint reports them)."""
    evs = sorted((e for e in events if e[1] in have), key=lambda e: e[0])
    held_until = -1.0
    shifted = []
    for t, pose, hold in evs:
        if hold == SOFT:
            t, hold = max(t, held_until), None
        elif hold:
            held_until = max(held_until, t + hold)
        shifted.append((t, pose, hold))
    evs = sorted(shifted, key=lambda e: e[0])
    out = [{"t": 0.0, "pose": "netral"}]
    for i, (t, pose, hold) in enumerate(evs):
        out.append({"t": round(t, 3), "pose": pose})
        nxt = evs[i + 1][0] if i + 1 < len(evs) else None
        if hold and (nxt is None or nxt > t + hold):
            out.append({"t": round(t + hold, 3), "pose": "netral"})
    dedup: list[dict] = []
    for s in out:
        if dedup and abs(dedup[-1]["t"] - s["t"]) < 1e-6:
            dedup[-1] = s
        elif not dedup or dedup[-1]["pose"] != s["pose"]:
            dedup.append(s)
    return dedup


def _blinks(spans: list[tuple[float, float]], name: str, every: list[float]) -> list[float]:
    lo, hi = float(every[0]), float(every[1])
    out = []
    for a, b in spans:
        t, k = a + 0.8 + _h(name, a) * lo, 0
        while t < b - 0.3:
            out.append(round(t, 3))
            k += 1
            t += lo + (hi - lo) * _h(name, a, k)
    return out
