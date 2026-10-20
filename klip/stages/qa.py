"""Stage 7 — QA: automated checks on the finished video. Writes qa.json.

Each check returns {name, ok, detail}. `passed` is false if any check fails; the CLI exits
non-zero so batch runs and agents notice.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from klip import config, ffmpeg
from klip.captions import tokenize
from klip.spec import Spec

DURATION_TOLERANCE = config.get("qa.duration_tolerance", 0.15)
MAX_DURATION_S = float(config.get("qa.max_duration_s", 120))
LOUDNESS_RANGE = tuple(config.get("qa.loudness_range", [-15.5, -12.5]))
MAX_TRUE_PEAK = config.get("qa.max_true_peak_db", -1.0)
MIN_SCENE_VOICE_DB = config.get("qa.min_scene_voice_db", -45.0)
MAX_STILL_S = config.get("qa.max_still_s", 1.0)
MAX_SHOT_S = float(config.get("cuts.max_shot_s", 6.0))


def check(name: str, ok: bool, detail: str) -> dict:
    return {"name": name, "ok": bool(ok), "detail": detail}


def check_format(info: dict) -> dict:
    v = next((s for s in info["streams"] if s["codec_type"] == "video"), None)
    a = next((s for s in info["streams"] if s["codec_type"] == "audio"), None)
    problems = []
    if not v:
        problems.append("no video stream")
    else:
        if (v["width"], v["height"]) != (1080, 1920):
            problems.append(f"size {v['width']}×{v['height']} (want 1080×1920)")
        if v.get("r_frame_rate") != "30/1":
            problems.append(f"fps {v.get('r_frame_rate')} (want 30)")
        if v.get("codec_name") != "h264":
            problems.append(f"video codec {v.get('codec_name')}")
    if not a:
        problems.append("no audio stream")
    elif a.get("codec_name") != "aac":
        problems.append(f"audio codec {a.get('codec_name')}")
    return check("format", not problems, "; ".join(problems) or "1080×1920, 30 fps, H.264/AAC")


def check_duration(duration_s: float, target_s: float) -> dict:
    lo, hi = target_s * (1 - DURATION_TOLERANCE), target_s * (1 + DURATION_TOLERANCE)
    ok = lo <= duration_s <= hi and duration_s <= MAX_DURATION_S
    detail = f"{duration_s:.1f}s (target {target_s}s ±15% = {lo:.1f}–{hi:.1f}s, max {MAX_DURATION_S:.0f}s)"
    if not ok:
        detail += ": adjust the word count or target_duration_s"
    return check("duration", ok, detail)


def detect_still(final: Path) -> tuple[list[tuple[float, float]], list[tuple[float, float]]]:
    """(black spans, frozen spans) longer than MAX_STILL_S, in seconds."""
    proc = ffmpeg.run(["-i", str(final), "-an", "-vf",
                       f"scale=270:-2,blackdetect=d={MAX_STILL_S}:pix_th=0.10,"
                       f"freezedetect=n=-60dB:d={MAX_STILL_S}", "-f", "null", "-"])
    err = proc.stderr
    black = [(float(a), float(b)) for a, b in re.findall(r"black_start:([\d.]+) black_end:([\d.]+)", err)]
    starts = [float(x) for x in re.findall(r"freeze_start: ([\d.]+)", err)]
    ends = [float(x) for x in re.findall(r"freeze_end: ([\d.]+)", err)]
    frozen = [(s, ends[i] if i < len(ends) else float("inf")) for i, s in enumerate(starts)]
    return black, frozen


def check_still(black: list, frozen: list) -> list[dict]:
    def fmt(spans):
        return ", ".join(f"{a:.1f}–{b:.1f}s" for a, b in spans)
    return [check("no_black", not black, fmt(black) or "no black stretches > 1 s"),
            check("no_freeze", not frozen, fmt(frozen) or "no frozen stretches > 1 s")]


def check_loudness(measured: dict) -> dict:
    i, tp = float(measured["input_i"]), float(measured["input_tp"])
    ok = LOUDNESS_RANGE[0] <= i <= LOUDNESS_RANGE[1] and tp <= MAX_TRUE_PEAK
    return check("loudness", ok, f"{i:.1f} LUFS (want {LOUDNESS_RANGE[0]}–{LOUDNESS_RANGE[1]}), "
                                 f"true peak {tp:.1f} dBTP (max {MAX_TRUE_PEAK})")


def scene_voice_levels(voice_wav: Path, timeline: dict) -> dict[str, float]:
    levels = {}
    for s in timeline["scenes"]:
        proc = ffmpeg.run(["-ss", f"{s['start_ms'] / 1000:.3f}", "-t", f"{max(s['audio_ms'], 100) / 1000:.3f}",
                           "-i", str(voice_wav), "-af", "volumedetect", "-f", "null", "-"])
        m = re.search(r"mean_volume: (-?[\d.]+|-inf) dB", proc.stderr)
        levels[s["id"]] = float(m.group(1)) if m and m.group(1) != "-inf" else float("-inf")
    return levels


def check_voice(levels: dict[str, float]) -> dict:
    silent = [f"{sid} ({db:.0f} dB)" for sid, db in levels.items() if db < MIN_SCENE_VOICE_DB]
    return check("voice_every_scene", not silent,
                 f"silent scenes: {', '.join(silent)}" if silent else f"{len(levels)} scenes have voice")


def check_captions(spec: Spec, words: list[dict], pages: list[dict], max_words: int) -> dict:
    problems = []
    by_scene: dict[str, int] = {}
    for w in words:
        by_scene[w["sceneId"]] = by_scene.get(w["sceneId"], 0) + 1
        if w["endMs"] < w["startMs"]:
            problems.append(f"bad timing for {w['text'].strip()!r}")
    for s in spec.scenes:
        want, got = len(tokenize(s.narration)), by_scene.get(s.id, 0)
        if want != got:
            problems.append(f"{s.id}: {got}/{want} words timed")
    long_pages = [i for i, p in enumerate(pages) if len(p["words"]) > max_words]
    if long_pages:
        problems.append(f"{len(long_pages)} caption page(s) > {max_words} words")
    return check("captions", not problems,
                 "; ".join(problems[:5]) or f"{len(words)} words timed, {len(pages)} pages ≤ {max_words} words")


def check_credits(assets: dict | None, credits: list[dict]) -> dict:
    if not assets:
        return check("credits", True, "no stock media")
    credited = {c["scene"] for c in credits}
    def stock_props(a: dict) -> int:
        return sum(1 for r in a.get("stage") or [] if not r.get("source", "").startswith("local:"))

    missing = [sid for sid, a in assets["scenes"].items()
               if ((a.get("kind") and a.get("provider") not in (None, "local")) or stock_props(a))
               and sid not in credited]
    n = sum(1 for a in assets["scenes"].values() if a.get("kind") and a.get("provider") != "local") + \
        sum(stock_props(a) for a in assets["scenes"].values())
    return check("credits", not missing, f"missing for {', '.join(missing)}" if missing else f"{n} stock asset(s) credited")


def check_footage(assets: dict | None) -> dict:
    """Every b-roll source on screen once: a clip shown twice (or re-cut) reads as looping.
    Shots longer than cuts.max_shot_s are named in the detail (not a failure)."""
    rows = [(sid, r) for sid, a in ((assets or {}).get("scenes") or {}).items() for r in a.get("shots") or []]
    props = [(sid, r) for sid, a in ((assets or {}).get("scenes") or {}).items() for r in a.get("stage") or []]
    seen: dict[str, str] = {}
    reused = []
    for sid, r in rows + props:
        src = r.get("source")
        if not src:
            continue
        if src in seen:
            reused.append(f"{src} ({seen[src]} and {sid})")
        else:
            seen[src] = sid
    long = [f"{sid} {r['dur_ms'] / 1000:.1f}s" for sid, r in rows if r["dur_ms"] / 1000 > MAX_SHOT_S]
    detail = f"reused: {', '.join(reused)}" if reused else f"{len(rows)} shots, {len(seen)} distinct sources"
    if props and not reused:
        detail += f" (incl. {len(props)} stage props)"
    if long:
        detail += f"; long shots (> {MAX_SHOT_S:.0f}s, add visual.beats): {', '.join(long)}"
    return check("fresh_footage", not reused, detail)


def run(spec: Spec, project_dir: Path) -> dict:
    final = project_dir / "final.mp4"
    if not final.exists():
        raise FileNotFoundError(f"{final} not found; run the post stage first")
    timeline = json.loads((project_dir / "timeline.json").read_text())

    def load(name, default=None):
        p = project_dir / name
        return json.loads(p.read_text()) if p.exists() else default

    info = ffmpeg.probe(final)
    from klip.stages.post import measure_loudness
    checks = [
        check_format(info),
        check_duration(float(info["format"]["duration"]), spec.target_duration_s),
        *check_still(*detect_still(final)),
        check_loudness(measure_loudness(final)),
        check_voice(scene_voice_levels(project_dir / "voice.wav", timeline)),
        check_captions(spec, load("words.json", []), load("captions.json", []),
                       config.style(spec.style)["caption"]["max_words"]),
        check_credits(load("assets.json"), load("credits.json", [])),
        check_footage(load("assets.json")),
    ]
    report = {"passed": all(c["ok"] for c in checks), "checks": checks}
    (project_dir / "qa.json").write_text(json.dumps(report, indent=2, ensure_ascii=False))
    return report
