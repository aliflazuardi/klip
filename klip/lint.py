"""Checks beyond the JSON Schema: things that would render badly or fail QA.

Errors block generation (the LLM is asked to fix them) and make `klip validate` exit 1.
Warnings are shown in the review preview.
"""

from __future__ import annotations

from dataclasses import dataclass

from klip import config
from klip.captions import norm, tokenize
from klip.paths import RENDERER_DIR
from klip.spec import STAGE_TEMPLATES, Scene, Spec

ICONS_DIR = RENDERER_DIR / "node_modules" / "lucide-static" / "icons"


@dataclass
class Issue:
    level: str          # "error" | "warning"
    where: str          # scene id or "spec"
    message: str

    def __str__(self) -> str:
        return f"{self.where}: {self.message}"


def _icon_ok(name: str) -> bool:
    return not ICONS_DIR.exists() or (ICONS_DIR / f"{name}.svg").exists()


def _contains(tokens: list[str], phrase: str) -> bool:
    want = [norm(t) for t in phrase.split() if norm(t)]
    have = [norm(t) for t in tokens]
    return bool(want) and any(have[i:i + len(want)] == want for i in range(len(have) - len(want) + 1))


def _check_anchors(where: str, tokens: list[str], anchors: list[str], what: str, err,
                   start: int = 0) -> list[int | None]:
    """Each anchor must be a narration word after the previous anchor (the first at or after word
    `start`). Returns word indexes."""
    rest = [norm(t) for t in tokens][start:]
    offset, out = start, []
    for a in anchors:
        first = norm(a.split()[0]) if a.split() else ""
        if first not in rest:
            err(where, f"{what} at {a!r} is not a word in the narration"
                       + (f" after the previous {what}" if _contains(tokens, a.split()[0]) else ""))
            out.append(None)
            continue
        k = rest.index(first)
        out.append(offset + k)
        offset += k + 1
        rest = rest[k + 1:]
    return out


def _lint_stage(spec: Spec, s: Scene, tokens: list[str], err, warn) -> None:
    from klip.pipeline import words_per_second
    if s.template not in STAGE_TEMPLATES:
        err(s.id, f"visual.type 'stage' works with the {', '.join(sorted(STAGE_TEMPLATES))} templates, "
                  f"not {s.template!r} (its cards would cover the stage)")
    els = s.visual.elements
    # elements and the steps of motion components share one narration order; a component's first
    # steps may land on the element's own word
    idx: list[int | None] = []
    pos = 0
    for e in els:
        [k] = _check_anchors(s.id, tokens, [e.at], "stage element", err, pos)
        idx.append(k)
        if k is None:
            continue
        found = _check_anchors(s.id, tokens, [st.at for st in e.steps if st.at], f"{e.kind} step", err, k)
        idx += found
        pos = max([k, *(j for j in found if j is not None)]) + 1
    wps = words_per_second(spec.voice, spec.speech_rate)
    lo, hi = config.get("stage.lint_min_gap_s"), config.get("stage.lint_max_gap_s")
    marks = [-1] + sorted({i for i in idx if i is not None}) + [len(tokens)]
    for a, b in zip(marks, marks[1:]):
        gap = (b - max(a, 0)) / wps
        if a >= 0 and b < len(tokens) and gap < lo:
            warn(s.id, f"stage elements at {tokens[a]!r} and {tokens[b]!r} are ~{gap:.1f}s apart; "
                       f"they'll land almost together (keep ≥ {lo}s)")
        elif gap > hi:
            where = f"after {tokens[a]!r}" if a >= 0 else "at the start"
            warn(s.id, f"nothing new on the stage for ~{gap:.0f}s {where}; add an element so the picture "
                       f"changes every 1-2 s")
    for e in els:
        for st in e.steps:
            if e.kind == "kinetic" and len(st.text.split()) > 5:
                warn(s.id, f"kinetic phrase {st.text!r}: keep each line to 1-5 words")
            elif e.kind in ("split", "flow", "cycle", "funnel", "reel") and len(st.text) > 22:
                warn(s.id, f"{e.kind} step {st.text!r} is long; keep it to ~2-3 words so it fits")
        if e.kind == "label" and len(e.text.split()) > 4:
            warn(s.id, f"label {e.text!r} has {len(e.text.split())} words; keep labels to 1-4")
        if e.label and len(e.label.split()) > 3:
            warn(s.id, f"element label {e.label!r}: keep it to 1-3 words")
        if e.kind == "number" and len(e.text) > 9:
            warn(s.id, f"number {e.text!r} is long; keep it ≤ 9 characters (e.g. 'Rp12rb', '-7%')")
        if e.kind == "bar" and any(len(b.label) > 9 for b in e.bars):
            warn(s.id, "bar labels over 9 characters won't fit under the bars")
        if e.path and e.kind in ("cutout", "photo", "person", "logo"):
            from klip.paths import ROOT
            if not (ROOT / e.path).exists():
                err(s.id, f"stage element path not found: {e.path}")
        if e.csv:
            from klip.paths import ROOT
            if not (ROOT / e.csv).is_file():
                err(s.id, f"chart csv not found: {e.csv}")
        if e.kind == "person" and e.query and not (e.who or e.path):
            warn(s.id, f"person {e.query!r} has only a stock `query`: that's a stranger, not the real person; "
                       f"set `who` to their Wikipedia article title")
        if e.kind == "news":
            if not e.outlet:
                warn(s.id, f"news card {e.text[:40]!r}…: set `outlet` (and `date`) so it reads as a real headline")
            if len(e.text.split()) > 14:
                warn(s.id, "news headline over 14 words won't fit the card; shorten it")
        if e.kind == "unit" and e.total > 200:
            warn(s.id, f"unit with {e.total} squares: they get tiny; scale it ('1 kotak = 1.000 …')")
        if e.kind == "person" and e.stat and len(e.stat) > 9:
            warn(s.id, f"person stat {e.stat!r} is long; keep it ≤ 9 characters")
    pics = sum(e.kind in ("cutout", "photo", "person", "logo", "screenshot") for e in els)
    icons = sum(e.kind in ("icon", "stack") for e in els)
    need = float(config.get("stage.photos.min_share"))
    if icons and pics < need * (pics + icons):
        warn(s.id, f"{icons} icon(s) vs {pics} real picture(s) on this stage: make most object props real photos "
                   f"(cutout/photo/person/logo, ≥ {need:.0%}); keep icons for abstract ideas")
    bg = s.visual.background
    if bg and bg not in (config.get("stage.backgrounds") or {}):
        from klip.paths import ROOT
        if not (ROOT / bg).is_file():
            err(s.id, f"visual.background {bg!r} is neither a built-in "
                      f"({', '.join(config.get('stage.backgrounds'))}) nor an image file")


def _lint_mascot(spec: Spec, s: Scene, tokens: list[str], err, warn) -> None:
    """Mascot names and poses must exist in the style's cast; pose words must be in the narration."""
    from klip import mascot
    try:
        style = config.style(spec.style)
    except KeyError:
        return
    cast = mascot.names(style)
    if not cast:
        warn(s.id, f"scene has a `mascot` but style {spec.style!r} has no mascot cast; it is ignored")
        return
    m = s.mascot
    if m.speaker and m.speaker != "none" and m.speaker not in cast:
        err(s.id, f"mascot speaker {m.speaker!r} isn't in the cast ({', '.join(cast)}, or 'none')")
    for p in m.poses:
        if p.who not in cast:
            err(s.id, f"mascot {p.who!r} isn't in the cast ({', '.join(cast)})")
        elif p.pose not in (have := mascot.poses(style, p.who)):
            err(s.id, f"{p.who} has no pose {p.pose!r} ({', '.join(have)})")
    _check_anchors(s.id, tokens, [p.at for p in m.poses if p.at], "mascot pose", err)
    if s.visual.type != "stage" and s.template != "cta":
        warn(s.id, "mascots only show on stage scenes (and say a folded cta's closing line)")


def _lint_look(spec: Spec, err) -> None:
    """look "stage": most scenes that can hold a stage must use one."""
    if spec.look != "stage":
        return
    able = [s for s in spec.scenes if s.template in STAGE_TEMPLATES]
    staged = [s for s in able if s.visual.type == "stage"]
    need = config.get("stage.look_min_share")
    if able and len(staged) < need * len(able):
        others = ", ".join(s.id for s in able if s.visual.type != "stage")
        err("spec", f'look "stage": {len(staged)}/{len(able)} hook/explain/list_item scenes use visual.type '
                    f'"stage" (need ≥ {need:.0%}); convert some of {others}, or set "look": "mixed"')


def lint(spec: Spec) -> list[Issue]:
    from klip.pipeline import estimate_duration_s

    issues: list[Issue] = []
    err = lambda where, msg: issues.append(Issue("error", where, msg))      # noqa: E731
    warn = lambda where, msg: issues.append(Issue("warning", where, msg))   # noqa: E731
    _lint_look(spec, err)
    if config.get("post.lowercase_hashtags", True):
        import re
        caps = sorted({t for t in re.findall(r"#\w+", spec.post.caption + " " + " ".join(spec.post.hashtags))
                       if t != t.lower()})
        if caps:
            warn("post", f"hashtags must be all lowercase: {', '.join(caps)} "
                         f"(post.txt writes {', '.join(t.lower() for t in caps)})")

    est = estimate_duration_s(spec)
    tol = config.get("qa.duration_tolerance", 0.15)
    lo, hi = spec.target_duration_s * (1 - tol), spec.target_duration_s * (1 + tol)
    max_s = config.get("qa.max_duration_s", 120)
    if est > max_s:
        err("spec", f"estimated {est:.0f}s exceeds the {max_s}s maximum; cut narration")
    elif not lo <= est <= hi:
        from klip.pipeline import words_per_second
        wps = words_per_second(spec.voice, spec.speech_rate)
        target_words = round((spec.target_duration_s - 0.15 * len(spec.scenes) - 1) * wps)
        err("spec", f"estimated {est:.0f}s is outside {lo:.0f}–{hi:.0f}s for target {spec.target_duration_s}s; "
                    f"narration has {spec.word_count} words, aim for ~{target_words}")

    if spec.scenes[0].template != "hook":
        warn(spec.scenes[0].id, "the first scene should use the 'hook' template")
    hooks = [("hook", spec.scenes[0].narration, spec.scenes[0].on_screen_text)] + \
        [(f"hook_variants[{i}]", v.narration, v.on_screen_text) for i, v in enumerate(spec.hook_variants)]
    for where, narration, on_screen in hooks:
        if len(narration.split()) > 14:
            warn(where, f"hook narration has {len(narration.split())} words; keep it ≤ 12 so it lands in ~3 s")
        if on_screen and len(on_screen.split()) > 5:
            warn(where, f"hook on-screen text has {len(on_screen.split())} words; keep it ≤ 5")
    if spec.scenes[-1].template != "cta":
        warn(spec.scenes[-1].id, "the last scene should use the 'cta' template")

    for i, s in enumerate(spec.scenes):
        icons = [s.visual.name] if s.visual.name else []
        icons += [e.name for e in s.visual.elements if e.name]
        if s.compare:
            icons += [x.icon for x in (s.compare.left, s.compare.right) if x.icon]
        for name in icons:
            if not _icon_ok(name):
                err(s.id, f"unknown Lucide icon {name!r} (see https://lucide.dev/icons)")

        if s.visual.type in ("stock_video", "stock_photo") and not s.visual.name:
            warn(s.id, "add visual.name (a Lucide icon) as a fallback in case no stock media is found")
        if s.on_screen_text and len(s.on_screen_text.split()) > 8:
            warn(s.id, f"on_screen_text has {len(s.on_screen_text.split())} words; keep it ≤ 6")
        for field in ("myth", "fact"):
            text = getattr(s, field)
            if text and len(text.split()) > 10:
                warn(s.id, f"{field} has {len(text.split())} words; keep it ≤ 8 so the card fits")

        visible = tokenize(s.narration) + tokenize(s.on_screen_text or "") + \
            tokenize((s.stat.label if s.stat and s.stat.label else "") or "")
        for phrase in s.emphasis:
            if not _contains(visible, phrase):
                warn(s.id, f"emphasis {phrase!r} doesn't appear in the narration or on-screen text")
        tokens = tokenize(s.narration)
        _check_anchors(s.id, tokens, [b.at for b in s.visual.beats], "beat", err)
        if s.visual.type == "stage":
            _lint_stage(spec, s, tokens, err, warn)
        if s.mascot:
            _lint_mascot(spec, s, tokens, err, warn)
        if s.visual.type in ("stock_video", "stock_photo") and s.visual.max_shots != 1:
            from klip.pipeline import words_per_second
            shots_n = len(s.visual.beats or s.visual.queries) + 1
            per_shot = len(s.narration.split()) / words_per_second(spec.voice, spec.speech_rate) / shots_n
            if per_shot > config.get("cuts.max_shot_s", 6.0):
                warn(s.id, f"~{per_shot:.0f}s per clip; add visual.beats so a new clip cuts in every ~2-3 s "
                           f"(clips are never repeated)")
        if s.visual.queries and not s.visual.beats:
            warn(s.id, "visual.queries cut on a timer; use visual.beats to cut each clip on the word it shows")
        if s.reveal_at and not _contains(tokenize(s.narration), s.reveal_at.split()[0]):
            err(s.id, f"reveal_at {s.reveal_at!r} is not a word in the narration")

        if s.template == "list_item":
            prev_li = i > 0 and spec.scenes[i - 1].template == "list_item"
            next_li = i + 1 < len(spec.scenes) and spec.scenes[i + 1].template == "list_item"
            if not (prev_li or next_li):
                warn(s.id, "a single list_item shows '1/1'; use 2–4 consecutive list items or 'explain'")

        if s.cta_type == "comment" and not (s.on_screen_text or "").rstrip().endswith("?"):
            warn(s.id, "a comment cta shows on_screen_text as the headline: make it the two-sided question "
                       "(\"Kamu tim kulkas atau freezer?\")")
        if s.template == "cta" and s.on_screen_text and len(s.on_screen_text.split()) > 10:
            warn(s.id, "cta on_screen_text over 10 words won't fit above the captions")

    if not spec.facts:
        warn("spec", "no facts[] listed; add sources for any factual claims")
    return issues


def errors(issues: list[Issue]) -> list[Issue]:
    return [i for i in issues if i.level == "error"]
