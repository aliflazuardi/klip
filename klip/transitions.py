"""Scene transitions: which cut gets which move (whip, zoom, wipe, flash), so a video varies its cuts.

Scenes are back-to-back clips, never overlapping, so a transition is two halves: the outgoing scene
animates out over its last `out_s`, the incoming one animates in over its first `in_s`, and the wipe /
flash overlays cover the seam. Pure data; templates/default/index.html.j2 draws it (style.transitions).
"""

from __future__ import annotations

import hashlib

from klip.spec import Spec

KINDS = ("whip", "zoom", "wipe", "flash", "none")


def _h(*parts) -> int:
    return int(hashlib.sha256(":".join(map(str, parts)).encode()).hexdigest()[:8], 16)


def is_cut(prev: dict, s: dict) -> bool:
    """A real picture change: not the first scene, not a stage set that carries on, not inside a world."""
    if s.get("hidden") or s["idx"] == 0:
        return False
    if s.get("stage") and s["stage"]["continues"]:
        return False
    return not (prev.get("on_world") and s.get("on_world"))


def plan(spec: Spec, scenes: list[dict], style: dict) -> None:
    """Set s["tr_in"] / prev["tr_out"] = {kind, dir, sel, d, sfx} on each cut (in place)."""
    cfg = style.get("transitions") or {}
    pool = [k for k in cfg.get("pool") or [] if k in KINDS]
    by_id = {s.id: s for s in spec.scenes}
    for s in scenes:
        s["tr_in"] = s["tr_out"] = None
    shown = [s for s in scenes if not s.get("hidden")]
    last, n = None, 0
    for prev, s in zip(shown, shown[1:]):
        if not is_cut(prev, s):
            continue
        want = getattr(by_id.get(s["id"]), "transition", None)
        if want:
            kind = want
        elif prev["idx"] == 0 and cfg.get("hook"):
            kind = cfg["hook"]
        elif pool:
            options = [k for k in pool if k != last] or pool
            # keyed on the scene, not the slug: A/B variants of one script get the same cuts
            kind = options[_h(s["id"], getattr(by_id.get(s["id"]), "narration", "")) % len(options)]
        else:
            kind = "none"
        last = kind
        if kind == "none":
            continue
        n += 1
        tr = {"kind": kind, "dir": 1 if n % 2 else -1, "sfx": (cfg.get("sfx") or {}).get(kind)}
        prev["tr_out"] = {**tr, "d": float(cfg["out_s"]), "at": round(prev["start"] + prev["dur"] - float(cfg["out_s"]), 3),
                          "sel": _sel(prev)}
        s["tr_in"] = {**tr, "d": float(cfg["in_s"]), "at": s["start"], "sel": _sel(s)}


def _sel(s: dict) -> str:
    """The section(s) a transition moves: the scene, plus the world under it."""
    return f"#sc-{s['id']}" + (", #sc-world" if s.get("on_world") else "")
