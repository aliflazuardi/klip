"""Keyframe preview (`klip preview`): stills of scenes at the moments that matter, as contact sheets.

The director-mode loop: write a code scene, preview it, look at the sheet, fix the file, preview
again. The voice is a draft (klip.yaml voices.preview_engine) unless the final engine's takes are
already cached, so previews never spend Gemini/ElevenLabs quota; voice and assets come from cache, so
a re-preview costs a compose and one snapshot run.
Per scene: its start, each k.at cue (code scenes) or stage element entry, the middle and the end
(klip.yaml code.preview).
"""

from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from klip import codescene, config
from klip.engines.render.hyperframes import HyperFramesRenderer
from klip.pipeline import run_stage
from klip.spec import Spec


def cfg(key: str):
    return config.get(f"code.preview.{key}")


def moments(scene, t: dict, words: list[dict]) -> list[tuple[float, str]]:
    """(seconds, label) to capture for one scene, at least code.preview.min_gap_s apart."""
    start, end = t["start_ms"] / 1000, (t["start_ms"] + t["duration_ms"]) / 1000
    cand = [(start + 0.15, "start")]
    if scene.visual.type == "code":
        cand += [(c + 0.25, f"“{p}”") for c, p in codescene.cue_times(scene, words)]
    cand += [((start + end) / 2, "mid"), (end - 0.12, "end")]
    out: list[tuple[float, str]] = []
    for at, label in sorted(cand):
        at = round(min(max(at, start + 0.05), end - 0.05), 3)
        if out and at - out[-1][0] < cfg("min_gap_s"):
            continue
        out.append((at, label))
    if len(out) > cfg("max_frames"):          # keep the first and last, thin the middle evenly
        n = cfg("max_frames")
        out = [out[round(i * (len(out) - 1) / (n - 1))] for i in range(n)]
    return out


def sheet(frames: list[tuple[float, str, Path]], title: str, out: Path) -> Path:
    """A contact sheet: up to 4 stills per row, each labelled with its time and cue."""
    w = int(cfg("sheet_width"))
    h = round(w * 1920 / 1080)
    cols = min(4, len(frames))
    rows = -(-len(frames) // cols)
    head, lab = 56, 44
    img = Image.new("RGB", (cols * w + (cols + 1) * 8, head + rows * (h + lab + 8)), "#111")
    d = ImageDraw.Draw(img)
    big, small = ImageFont.load_default(size=30), ImageFont.load_default(size=24)
    d.text((10, 12), title, fill="#fff", font=big)
    for i, (at, label, png) in enumerate(frames):
        x, y = 8 + (i % cols) * (w + 8), head + (i // cols) * (h + lab + 8)
        with Image.open(png) as im:
            img.paste(im.convert("RGB").resize((w, h)), (x, y))
        d.text((x + 4, y + h + 8), f"{at:.2f}s  {label}", fill="#ddd", font=small)
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, quality=88)
    return out


def run(spec: Spec, project_dir: Path, scene_ids: list[str] | None = None,
        renderer: HyperFramesRenderer | None = None) -> list[dict]:
    """Voice + assets (cached) + compose, then stills of the chosen scenes (default: the code scenes,
    else all). Returns [{scene, sheet, frames: [{t, label, png}]}]."""
    from klip.stages import voice
    voice.run_preview(spec, project_dir)       # a draft voice unless the final takes are cached
    for stage in ("assets", "compose"):
        run_stage(stage, spec, project_dir)
    timeline = json.loads((project_dir / "timeline.json").read_text())
    words = json.loads((project_dir / "words.json").read_text())
    tmap = {s["id"]: s for s in timeline["scenes"]}
    by_scene: dict[str, list[dict]] = {}
    for w in words:
        by_scene.setdefault(w["sceneId"], []).append(w)
    if scene_ids:
        unknown = set(scene_ids) - set(tmap)
        if unknown:
            raise ValueError(f"no scene {', '.join(sorted(unknown))} in {spec.slug} (scenes: {', '.join(tmap)})")
        chosen = [s for s in spec.scenes if s.id in scene_ids]
    else:
        chosen = [s for s in spec.scenes if s.visual.type == "code"] or list(spec.scenes)
    plan = {s.id: moments(s, tmap[s.id], by_scene.get(s.id, [])) for s in chosen}
    stills = (renderer or HyperFramesRenderer()).stills(project_dir / "composition", project_dir / "preview" / "frames",
                                                        [at for ms in plan.values() for at, _ in ms])
    out = []
    for sid, ms in plan.items():
        frames = [(at, label, stills[round(at, 3)]) for at, label in ms]
        path = sheet(frames, f"{spec.slug} · {sid}", project_dir / "preview" / f"{sid}.jpg")
        out.append({"scene": sid, "sheet": str(path),
                    "frames": [{"t": at, "label": label, "png": str(p)} for at, label, p in frames]})
    (project_dir / "preview" / "preview.json").write_text(json.dumps(out, indent=2, ensure_ascii=False))
    return out
