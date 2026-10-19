"""Stage 3 — Assets: pick, download and normalize b-roll per scene.

Two steps, so searching/downloading can run while the voice stage synthesizes:
  fetch()   search providers, score, download  -> assets.fetch.json (+ credits.json)
  prepare() normalize to 1080x1920 at the scene's real duration -> media/<scene>.mp4|.jpg,
            assets.json (read by compose)

Provider order: local library, then Pexels (if keyed), then Pixabay (if keyed), then
Openverse (photos, no key). stock_video falls back to photos, then to the scene's icon
(visual.name) or a gradient background.
"""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
import time
from pathlib import Path

from klip import config, cutout, ffmpeg, http, shots
from klip import stage as stage_mod
from klip.engines.media.base import Candidate, Kind, MediaProvider, TARGET_H, TARGET_W, relevance, score
from klip.engines.media.local import LocalLibrary, candidate_for_file
from klip.engines.media.openverse import Openverse
from klip.engines.media.pexels import Pexels
from klip.engines.media.pixabay import Pixabay
from klip.paths import CACHE_DIR, ROOT
from klip.spec import Scene, Spec, Visual

log = logging.getLogger(__name__)

NORMALIZE_VERSION = 2                                        # 2: hold the last frame instead of looping
MIN_SPEED = float(config.get("cuts.min_speed", 0.6))         # slowest playback for a short clip
COVER_MIN_FILL = config.get("assets.cover_min_fill", 0.6)   # below: blurred-background fill
DOWNLOAD_TRIES = config.get("assets.download_tries", 3)     # candidates per provider
MIN_RELEVANCE = config.get("assets.min_relevance", 0.5)     # share of query words in the tags


class AssetsError(RuntimeError):
    pass


PROVIDERS = {"local": LocalLibrary, "pexels": Pexels, "pixabay": Pixabay, "openverse": Openverse}


def default_providers() -> list[MediaProvider]:
    names = config.get("assets.providers", list(PROVIDERS))
    unknown = [n for n in names if n not in PROVIDERS]
    if unknown:
        raise AssetsError(f"unknown providers in klip.yaml assets.providers: {unknown}")
    return [PROVIDERS[n]() for n in names]


def kinds_for(scene: Scene) -> list[Kind]:
    return {"stock_video": ["video", "photo"], "stock_photo": ["photo"], "ai_image": ["photo"]}.get(
        scene.visual.type, [])


def query_for(scene: Scene) -> str:
    return (scene.visual.query or scene.visual.prompt or "").strip()


def estimate_scene_s(scene: Scene, voice: str, rate: str) -> float:
    from klip.pipeline import words_per_second
    return len(scene.narration.split()) / words_per_second(voice, rate) + 0.3


def queries_for(scene: Scene) -> list[str]:
    """The scene's queries in shot order: main query, then each beat's (or the legacy `queries`)."""
    later = [b.query for b in scene.visual.beats] or scene.visual.queries
    return [q for q in [query_for(scene), *later] if q.strip()]


Pool = tuple[str, MediaProvider, list[Candidate]]       # (query, provider, ranked candidates)


def _pool(scene: Scene, query: str, kind: Kind, need_s: float, used: set[str],
          providers: list[MediaProvider], warnings: list[str],
          extra: int = 0, gate: str | None = None) -> tuple[MediaProvider, list[Candidate]] | None:
    """Ranked, relevant, unused candidates for one query from the first provider that has any.
    `gate`: judge relevance against this instead of the search query (a search that adds words
    such as 'isolated' must still match the subject).
    `extra` > 0 also appends that many top-ranked results the tag gate dropped (for the vision
    check to rescue; they're marked with `vision_only`)."""
    for p in providers:
        if not p.enabled():
            continue
        try:
            cands = [c for c in p.search(query, kind) if c.key not in used]
        except http.HTTPError as e:
            warnings.append(f"{scene.id}: {p.name} search failed ({e})")
            continue
        # Relevance gate: drop results whose tags share too few of the query's words
        # (e.g. "food container refrigerator" → a shipping-container port). Untagged → kept.
        relevant = [c for c in cands if (rel := relevance(c, gate or query)) is None or rel >= MIN_RELEVANCE]
        if cands and not relevant:
            log.info("assets: %s: %d %s %s result(s) off-topic for %r", scene.id, len(cands), p.name, kind, query)
        ranked = sorted(relevant, key=lambda c: score(c, need_s, gate or query), reverse=True)
        if extra:
            dropped = [c for c in sorted(cands, key=lambda c: c.rank) if c not in relevant][:extra]
            for c in dropped:
                c.vision_only = True   # type: ignore[attr-defined]
            ranked += dropped
        if ranked:
            return p, ranked
    return None


def build_pools(scene: Scene, need_s: float, used: set[str], providers: list[MediaProvider],
                warnings: list[str], extra: int = 0, all_kinds: bool = False) -> list[Pool]:
    """Candidate pools per query for the first media kind (video, then photo) that has any.
    `all_kinds` (vision check): pools for every kind, so Claude can prefer a fitting photo."""
    if all_kinds:
        return [(q, *found) for kind in kinds_for(scene) for q in queries_for(scene)
                if (found := _pool(scene, q, kind, need_s, used, providers, warnings, extra))]
    for kind in kinds_for(scene):
        pools = [(q, *found) for q in queries_for(scene)
                 if (found := _pool(scene, q, kind, need_s, used, providers, warnings, extra))]
        if any(not getattr(c, "vision_only", False) for _, _, cands in pools for c in cands) or (extra and pools):
            return pools
    return []


def _content_key(path: Path) -> str | None:
    """Hash of the downloaded file: the same footage can come back under different ids/providers."""
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return "sha:" + h.hexdigest()
    except OSError:
        return None


def _take(scene: Scene, q: str, p: MediaProvider, cands: list[Candidate], used: set[str],
          warnings: list[str], failures: dict[str, int]) -> tuple[Candidate, Path, str] | None:
    """Download the best unused candidate from `cands` (consumed in place). Every source is used
    once per video: by provider id and by file content."""
    while cands:
        c = cands.pop(0)
        if c.key in used:
            continue
        try:
            path = p.fetch(c)
        except http.HTTPError as e:
            warnings.append(f"{scene.id}: {p.name} download failed ({e}); trying next")
            failures[q] = failures.get(q, 0) + 1
            if failures[q] >= DOWNLOAD_TRIES:
                cands.clear()
            continue
        used.add(c.key)
        ck = _content_key(path)
        if ck and ck in used:
            log.info("assets: %s: %s %s is a duplicate of a clip already used; skipping", scene.id, p.name, c.id)
            continue
        if ck:
            used.add(ck)
        return c, path, q
    return None


def pick(scene: Scene, pools: list[Pool], used: set[str], warnings: list[str],
         n: int) -> list[tuple[Candidate, Path, str]]:
    """Round-robin over the pools (main query first), best remaining candidate per pool each round."""
    pools = [(q, p, list(cands)) for q, p, cands in pools]
    picked: list[tuple[Candidate, Path, str]] = []
    failures: dict[str, int] = {}
    while len(picked) < n and any(cands for _, _, cands in pools):
        for q, p, cands in pools:
            if len(picked) < n and (got := _take(scene, q, p, cands, used, warnings, failures)):
                picked.append(got)
    return picked


def pick_beats(scene: Scene, pools: list[Pool], used: set[str],
               warnings: list[str]) -> list[tuple[Candidate, Path, str, int]]:
    """One clip per beat from that beat's own query (beat 0 = the main query). A beat with no
    usable result gets no clip; prepare() lets the previous shot run on instead of repeating one."""
    pools = [(q, p, list(cands)) for q, p, cands in pools]
    picked = []
    failures: dict[str, int] = {}
    for k, q in enumerate(queries_for(scene)):
        got = next((g for pq, p, cands in pools if pq == q
                    and (g := _take(scene, q, p, cands, used, warnings, failures))), None)
        if got:
            picked.append((*got, k))
        elif k:
            at = scene.visual.beats[k - 1].at
            warnings.append(f"{scene.id}: no clip for beat {at!r} ({q!r}); the previous shot runs on")
    return picked


def select_many(scene: Scene, need_s: float, used: set[str], providers: list[MediaProvider],
                warnings: list[str], n: int = 1) -> list[tuple[Candidate, Path, str]]:
    """Up to n distinct clips for a scene (no vision check). Falls back from video to photos."""
    for kind in kinds_for(scene):
        pools = [(q, *found) for q in queries_for(scene)
                 if (found := _pool(scene, q, kind, need_s, used, providers, warnings))]
        if picked := pick(scene, pools, used, warnings, n):
            return picked
    return []


# ---- vision relevance check

def _thumb(c: Candidate) -> Path | None:
    try:
        if c.local_path:
            out = CACHE_DIR / "media" / f"thumb-local-{hashlib.sha256(c.local_path.encode()).hexdigest()[:16]}.jpg"
            if not out.exists():
                ffmpeg.run(["-ss", "1" if c.kind == "video" else "0", "-i", c.local_path, "-frames:v", "1",
                            "-vf", "scale=360:-2", str(out)])
            return out
        if c.thumb_url:
            return http.download(c.thumb_url, f"thumb-{c.provider}-{c.kind}-{c.id}.jpg")
    except (http.HTTPError, ffmpeg.FFmpegError):
        pass
    return None


def prop_key(scene_id: str, el: int) -> str:
    """Plan/sheet id of a stage scene's cutout/photo element."""
    return f"{scene_id}-el{el}"


def stage_queries(e) -> list[str]:
    """Searches for a stage prop: cut-outs try stage.cutout.query_suffix first ('tempeh isolated'),
    since plain backgrounds lift cleanly."""
    suffix = (config.get("stage.cutout.query_suffix") or "").strip()
    return [f"{e.query} {suffix}", e.query] if suffix and e.kind == "cutout" else [e.query]


def stage_pools(scene: Scene, used: set[str], providers: list[MediaProvider], warnings: list[str],
                extra: int = 0) -> dict[str, list[Pool]]:
    """Candidate pools per cutout/photo element (by prop_key), for the vision check. Relevance is
    gated on the plain query: the suffix word alone must never let a photo in."""
    plans = {}
    for i, e in enumerate(scene.visual.elements):
        if stage_mod.is_media(e) and not e.path:
            plans[prop_key(scene.id, i)] = [(q, *found) for q in stage_queries(e) if (
                found := _pool(scene, q, "photo", 3.0, used, providers, warnings, extra, gate=e.query))]
    return plans


def vision_review(spec: Spec, plans: dict[str, list[Pool]], project_dir: Path, warnings: list[str],
                  reviewer=None) -> tuple[dict[str, list[Pool]], dict]:
    """Show Claude each scene's (and stage prop's) candidates; keep and reorder what it approves.
    On failure, fall back to the tag-gated pools (dropping the vision-only extras).
    A stage prop's result is one single-candidate pool per kept photo, best first, so the
    top-rated photo wins whichever query found it."""
    from klip.engines.media.vision import SceneSheet, VisionReviewer, contact_sheet
    cfg = config.get("assets.vision_check", {}) or {}
    reviewer = reviewer or VisionReviewer()
    max_c = int(cfg.get("candidates_per_scene", 8))
    min_score = int(cfg.get("min_score", 2))
    scenes = {s.id: s for s in spec.scenes}
    props = {prop_key(s.id, i): (s, e) for s in spec.scenes if s.visual.type == "stage"
             for i, e in enumerate(s.visual.elements)}
    order: dict[str, list[str]] = {}     # scene → candidate keys in sheet order
    sheets = []
    sheet_dir = project_dir / "vision"
    sheet_dir.mkdir(exist_ok=True)
    photo_slots = int(cfg.get("photo_slots", 3))
    for sid, pools in plans.items():
        seen: list[Candidate] = []
        n_max = int(cfg.get("candidates_per_prop", 6)) if sid in props else max_c
        # interleave the pools so every query is represented; reserve some slots for photos
        for kind, cap in (("video", n_max - photo_slots), ("photo", n_max)):
            kp = [c for _, _, c in pools if c and c[0].kind == kind]
            for i in range(max((len(c) for c in kp), default=0)):
                for cands in kp:
                    if i < len(cands) and cands[i].key not in {x.key for x in seen} and len(seen) < cap:
                        seen.append(cands[i])
        if not seen:
            continue
        order[sid] = [c.key for c in seen]
        sheet = contact_sheet([_thumb(c) for c in seen], sheet_dir / f"{sid}.jpg")
        if sid in props:
            sc, e = props[sid]
            prop = f"{e.kind}, pops in on the word {e.at!r}" + (f", labelled {e.label!r}" if e.label else "")
            sheets.append(SceneSheet(sid, sc.narration, sc.on_screen_text or "", e.query, sheet, len(seen), prop))
        else:
            sc = scenes[sid]
            sheets.append(SceneSheet(sid, sc.narration, sc.on_screen_text or "", " | ".join(queries_for(sc)),
                                     sheet, len(seen)))

    def without_extras(pools: list[Pool]) -> list[Pool]:
        return [(q, p, [c for c in cands if not getattr(c, "vision_only", False)]) for q, p, cands in pools]

    report = {"scenes": sum(s.id not in props for s in sheets), "props": sum(s.id in props for s in sheets),
              "kept": 0, "rejected": 0, "ok": False}
    if not sheets:
        return {sid: without_extras(p) for sid, p in plans.items()}, report
    t0 = time.monotonic()
    try:
        verdicts = reviewer.review(sheets)
    except Exception as e:
        warnings.append(f"vision check unavailable ({e}); using tag-based selection")
        return {sid: without_extras(p) for sid, p in plans.items()}, report
    report.update(ok=True, seconds=round(time.monotonic() - t0, 1), verdicts={})
    out: dict[str, list[Pool]] = {}
    for sid, pools in plans.items():
        if sid not in order:
            out[sid] = without_extras(pools)
            continue
        if sid not in verdicts:   # model skipped the scene: don't punish it
            warnings.append(f"{sid}: vision check returned no verdict; using tag-based selection")
            out[sid] = without_extras(pools)
            continue
        ratings = verdicts[sid]
        # keep candidates rated >= min_score, best rating first (sheet order breaks ties)
        keep = sorted((i for i, r in enumerate(ratings) if r >= min_score), key=lambda i: (-ratings[i], i))
        keep_keys = [order[sid][i] for i in keep]
        rank = {k: i for i, k in enumerate(keep_keys)}
        if sid in props:
            first = {}
            for q, p, cands in pools:
                for c in cands:
                    first.setdefault(c.key, (q, p, c))
            out[sid] = [(q, p, [c]) for q, p, c in (first[k] for k in keep_keys)]
        else:
            out[sid] = [(q, p, sorted([c for c in cands if c.key in rank], key=lambda c: rank[c.key]))
                        for q, p, cands in pools]
        report["kept"] += len(keep_keys)
        report["rejected"] += len(order[sid]) - len(keep_keys)
        report["verdicts"][sid] = {"ratings": ratings, "kept": len(keep_keys)}
        if not keep_keys:
            warnings.append(f"{sid}: vision check rejected all {len(order[sid])} candidates")
    return out, report


def select(scene: Scene, need_s: float, used: set[str], providers: list[MediaProvider],
           warnings: list[str]) -> tuple[Candidate, Path] | None:
    picked = select_many(scene, need_s, used, providers, warnings, 1)
    return (picked[0][0], picked[0][1]) if picked else None


def _local_path(scene: Scene, path: str | None = None) -> Path:
    p = Path(path or scene.visual.path).expanduser()
    p = p if p.is_absolute() else ROOT / p
    if not p.exists():
        raise AssetsError(f"{scene.id}: {'stage element path' if path else 'visual.path'} not found: {p}")
    return p


def fetch_stage(scene: Scene, used: set[str], providers: list[MediaProvider], warnings: list[str],
                plans: dict[str, list[Pool]] | None = None) -> list[dict]:
    """One photo per cutout/photo element of a stage scene (never one already used in the video).
    With `plans` (from the vision check, by prop_key) the best approved candidate is taken;
    otherwise the first tag-relevant result of stage_queries()."""
    rows = []
    for i, e in enumerate(scene.visual.elements):
        if not stage_mod.is_media(e):
            continue
        if e.path:
            c = candidate_for_file(_local_path(scene, e.path))
            rows.append({"el": i, "src": c.local_path, "credit": c.credit(), "query": None})
            continue
        got = None
        if plans is not None and (key := prop_key(scene.id, i)) in plans:
            failures: dict[str, int] = {}
            got = next((g for q, p, cands in plans[key]
                        if (g := _take(scene, q, p, list(cands), used, warnings, failures))), None)
        else:
            for q in stage_queries(e):
                if (found := _pool(scene, q, "photo", 3.0, used, providers, warnings, gate=e.query)) and \
                        (got := _take(scene, q, *found, used, warnings, {})):
                    break
        if got:
            c, path, q = got
            rows.append({"el": i, "src": str(path), "credit": c.credit(), "query": q,
                         "vision_rescued": bool(getattr(c, "vision_only", False))})
            log.info("assets: %s el %d ← %s photo %s", scene.id, i, c.provider, c.id)
        else:
            warnings.append(f"{scene.id}: no photo for stage element at {e.at!r} ({e.query!r}); it is left out")
    return rows


def fetch(spec: Spec, project_dir: Path, providers: list[MediaProvider] | None = None, reviewer=None) -> dict:
    providers = providers if providers is not None else default_providers()
    http.stats.reset()
    rate = spec.speech_rate or config.default_rate(spec.voice)
    used: set[str] = set()
    warnings: list[str] = []
    scenes: dict[str, dict] = {}
    vcfg = config.get("assets.vision_check", {}) or {}
    use_vision = bool(vcfg.get("enabled", False)) and (reviewer is not None or shutil.which("claude"))
    extra = int(vcfg.get("extra_untagged", 2)) if use_vision else 0
    cut = shots.settings()

    # 1. candidate pools per stock scene
    plans: dict[str, list[Pool]] = {}
    wanted: dict[str, tuple[int, float]] = {}
    for scene in spec.scenes:
        v = scene.visual
        if v.type == "ai_image":
            warnings.append(f"{scene.id}: ai_image backend not configured; using a stock photo")
        if v.type == "stage":
            if use_vision:
                plans.update(stage_pools(scene, used, providers, warnings, extra))
            continue
        if v.type in ("local", "icon", "solid"):
            continue
        est = estimate_scene_s(scene, spec.voice, rate)
        if v.beats:
            n = len(queries_for(scene))          # one clip per beat
        else:
            n = min(int(config.get("cuts.clips_per_scene", 3)),
                    shots.shot_count(est * 1000, cut["target_ms"], cut["max_shots"], v.max_shots))
        wanted[scene.id] = (n, est)
        plans[scene.id] = build_pools(scene, est / n, used, providers, warnings, extra, all_kinds=use_vision)

    # 2. vision relevance check (one Claude call for the whole video)
    vision_report = None
    if use_vision and plans:
        plans, vision_report = vision_review(spec, plans, project_dir, warnings, reviewer)
        if vision_report.get("ok"):
            log.info("assets: vision check kept %d, rejected %d candidates in %.0fs",
                     vision_report["kept"], vision_report["rejected"], vision_report.get("seconds", 0))

    # 3. pick + download
    for scene in spec.scenes:
        v = scene.visual
        if v.type == "local":
            c = candidate_for_file(_local_path(scene))
            clip = {"kind": c.kind, "src": c.local_path, "credit": c.credit()}
            scenes[scene.id] = {**clip, "clips": [clip]}
            continue
        if v.type in ("icon", "solid"):
            scenes[scene.id] = {"kind": None}
            continue
        if v.type == "stage":
            scenes[scene.id] = {"kind": None, "stage": fetch_stage(scene, used, providers, warnings,
                                                                   plans if use_vision else None)}
            continue
        n, est = wanted[scene.id]
        if v.beats:
            picked = pick_beats(scene, plans.get(scene.id, []), used, warnings)
        else:
            picked = [(*x, None) for x in pick(scene, plans.get(scene.id, []), used, warnings, n)]
        if picked:
            clips = [{"kind": c.kind, "src": str(path), "credit": c.credit(), "query": q, "beat": b,
                      "score": score(c, est / n, q), "relevance": relevance(c, q),
                      "vision_rescued": bool(getattr(c, "vision_only", False))} for c, path, q, b in picked]
            scenes[scene.id] = {"kind": clips[0]["kind"], "src": clips[0]["src"], "credit": clips[0]["credit"],
                                "clips": clips}
            log.info("assets: %s ← %s", scene.id, ", ".join(f"{c.provider} {c.kind} {c.id}" for c, _, _ in picked))
        else:
            fallback = "icon" if v.name else "solid"
            warnings.append(f"{scene.id}: no media found for {query_for(scene)!r}; using {fallback}")
            scenes[scene.id] = {"kind": None, "fallback": fallback}

    result = {"scenes": scenes, "warnings": warnings, "http": vars(http.stats).copy(), "vision": vision_report}
    (project_dir / "assets.fetch.json").write_text(json.dumps(result, indent=2, ensure_ascii=False))
    credits = [{"scene": sid, **clip["credit"]} for sid, sc in scenes.items()
               for clip in [*sc.get("clips", []), *sc.get("stage", [])] if clip["credit"]["provider"] != "local"]
    (project_dir / "credits.json").write_text(json.dumps(credits, indent=2, ensure_ascii=False))
    for w in warnings:
        log.warning(w)
    return result


def _norm_key(src: Path, duration_s: float, kind: str) -> str:
    st = src.stat()
    raw = json.dumps([NORMALIZE_VERSION, str(src), st.st_size, int(st.st_mtime), round(duration_s, 2), kind])
    return hashlib.sha256(raw.encode()).hexdigest()[:20]


def fill_mode(width: int, height: int) -> str:
    crop_w = min(width, height * TARGET_W / TARGET_H)
    return "cover" if crop_w / TARGET_W >= COVER_MIN_FILL else "blur"


def _video_filter(mode: str, speed: float, hold_s: float = 0.0) -> str:
    slow = f"setpts={speed:.4f}*PTS," if speed > 1.001 else ""
    if hold_s > 0:
        slow += f"tpad=stop_mode=clone:stop_duration={hold_s + 0.1:.3f},"
    cover = (f"scale={TARGET_W}:{TARGET_H}:force_original_aspect_ratio=increase:flags=lanczos,"
             f"crop={TARGET_W}:{TARGET_H}")
    if mode == "cover":
        return f"[0:v]{slow}fps=30,{cover},setsar=1,format=yuv420p[v]"
    return (f"[0:v]{slow}fps=30,split=2[a][b];"
            f"[a]{cover},gblur=sigma=40,eq=brightness=-0.12[bg];"
            f"[b]scale={TARGET_W}:-2:flags=lanczos[fg];"
            f"[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1,format=yuv420p[v]")


def normalize(src: Path, kind: str, duration_s: float) -> tuple[Path, str]:
    """Return (cached normalized file, mode). Videos: 1080x1920, 30 fps, no audio, exact length,
    from the start of the source. A clip that is too short is slowed down (to cuts.min_speed
    at most), then holds its last frame: it never loops, since repeated footage reads as cheap.
    Photos: one 1080x1920 JPEG."""
    w, h, src_dur = _probe(src)
    mode = fill_mode(w, h)
    out_dir = CACHE_DIR / "norm"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{_norm_key(src, duration_s, kind)}{'.mp4' if kind == 'video' else '.jpg'}"
    if out.exists() and out.stat().st_size > 0:
        return out, mode
    if kind == "video":
        speed, hold = 1.0, 0.0
        if src_dur and src_dur < duration_s:
            speed = min(duration_s / src_dur, 1 / MIN_SPEED)
            hold = duration_s - src_dur * speed
        ffmpeg.run(["-i", str(src), "-t", f"{duration_s:.3f}", "-an",
                    "-filter_complex", _video_filter(mode, speed, hold), "-map", "[v]",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-g", "30",
                    "-movflags", "+faststart", str(out)])
    else:
        ffmpeg.run(["-i", str(src), "-filter_complex", _video_filter(mode, 1.0), "-map", "[v]",
                    "-frames:v", "1", "-q:v", "3", str(out)])
    return out, mode


def _probe(src: Path) -> tuple[int, int, float]:
    info = ffmpeg.probe(src)
    v = next(s for s in info["streams"] if s["codec_type"] == "video")
    return int(v["width"]), int(v["height"]), float(info["format"].get("duration") or 0)


def plan_shots(scene_visual: Visual, t: dict, words: list[dict], clips: list[dict], cut: dict) -> list[tuple[shots.Shot, int]]:
    """(shot, clip index) for a scene. Every shot gets its own clip: beats cut on their anchor words
    (a beat without a clip is dropped), timed cuts are capped at the number of clips."""
    if scene_visual.beats:
        by_beat = {c["beat"]: i for i, c in enumerate(clips) if c.get("beat") is not None}
        if by_beat:
            # beats with a clip; if the main query found nothing, the first of them opens the scene
            have = sorted(by_beat)
            anchors = [scene_visual.beats[k - 1].at for k in have[1:]]
            planned = shots.plan_beats(t["start_ms"], t["duration_ms"], words, anchors, cut["min_ms"])
            return [(sh, by_beat[have[j]]) for sh, j in planned]
    plan = shots.plan(t["start_ms"], t["duration_ms"], words, cut["target_ms"], cut["min_ms"],
                      cut["max_shots"], min(len(clips), scene_visual.max_shots or len(clips)))
    return [(sh, k) for k, sh in enumerate(plan)]


def prepare_stage(sid: str, visual: Visual, rows: list[dict], media_dir: Path, project_dir: Path,
                  warnings: list[str]) -> list[dict]:
    """Cut-outs (background removed, white outline) and photo cards for a stage scene's elements.
    A cut-out whose subject can't be lifted becomes a photo card."""
    from PIL import Image
    out = []
    for r in rows:
        e = visual.elements[r["el"]]
        src = Path(r["src"])
        render, file = "photo", None
        if e.kind == "cutout":
            file, why = cutout.cut_out(src)
            if file:
                render = "cutout"
            else:
                warnings.append(f"{sid}: couldn't cut out {e.query or e.path!r} ({why}); shown as a photo card")
        if not file:
            file = cutout.card(src)
        dst = media_dir / f"{sid}_el{r['el']}{file.suffix}"
        shutil.copyfile(file, dst)
        with Image.open(dst) as im:
            w, h = im.size
        cr = r["credit"]
        out.append({"el": r["el"], "render": render, "file": str(dst.relative_to(project_dir)), "w": w, "h": h,
                    "source": f"{cr['provider']}:{cr.get('id') or r['src']}"})
    return out


def prepare(spec: Spec, project_dir: Path) -> dict:
    fetched = json.loads((project_dir / "assets.fetch.json").read_text())
    timeline = json.loads((project_dir / "timeline.json").read_text())
    words = json.loads((project_dir / "words.json").read_text())
    tmap = {s["id"]: s for s in timeline["scenes"]}
    visuals = {s.id: s.visual for s in spec.scenes}
    cut = shots.settings()
    media_dir = project_dir / "media"
    if media_dir.exists():
        shutil.rmtree(media_dir)
    media_dir.mkdir()
    out = {}
    warnings = list(fetched["warnings"])
    for sid, a in fetched["scenes"].items():
        if a.get("stage") is not None:
            out[sid] = {"kind": None, "stage": prepare_stage(sid, visuals[sid], a["stage"], media_dir, project_dir,
                                                             warnings)}
            continue
        if not a.get("kind"):
            out[sid] = {"kind": None, "fallback": a.get("fallback")}
            continue
        clips = a.get("clips") or [{"kind": a["kind"], "src": a["src"], "credit": a["credit"]}]
        plan = plan_shots(visuals[sid], tmap[sid], [w for w in words if w["sceneId"] == sid], clips, cut)
        shot_rows = []
        for k, (sh, ci) in enumerate(plan):
            clip = clips[ci]
            norm, mode = normalize(Path(clip["src"]), clip["kind"], sh.dur_ms / 1000)
            dst = media_dir / f"{sid}_{k}{norm.suffix}"
            shutil.copyfile(norm, dst)
            cr = clip["credit"]
            shot_rows.append({"file": str(dst.relative_to(project_dir)), "kind": clip["kind"], "mode": mode,
                              "start_ms": round(sh.start_ms, 1), "dur_ms": round(sh.dur_ms, 1),
                              "clip": ci, "source": f"{cr['provider']}:{cr.get('id') or clip['src']}"})
        out[sid] = {"kind": shot_rows[0]["kind"], "file": shot_rows[0]["file"], "mode": shot_rows[0]["mode"],
                    "provider": clips[0]["credit"]["provider"], "shots": shot_rows}
    result = {"scenes": out, "warnings": warnings, "http": fetched["http"]}
    (project_dir / "assets.json").write_text(json.dumps(result, indent=2, ensure_ascii=False))
    return result


def run(spec: Spec, project_dir: Path) -> dict:
    fetch(spec, project_dir)
    return prepare(spec, project_dir)
