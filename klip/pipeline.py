"""Stage orchestration. Every stage reads/writes files inside the project dir."""

from __future__ import annotations

import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable

from klip import config
from klip.paths import PROJECTS_DIR
from klip.spec import Spec, load_spec
from klip.stages import assets, compose, post, qa, render, voice

log = logging.getLogger(__name__)

STAGES = ["voice", "assets", "compose", "render", "post", "qa"]



def words_per_second(voice_name: str, rate: str | None) -> float:
    rate = rate or config.default_rate(voice_name)
    # klip.yaml voices.base_words_per_second is measured at +0%; scales ~linearly with rate
    return config.get("voices.base_words_per_second")[voice_name] * (1 + int(rate.rstrip("%")) / 100)


def resolve(spec_path: Path, voice_override: str | None = None, out_dir: Path | None = None,
            progress_bar: bool | None = None, mascots: bool | list[str] | None = None) -> tuple[Spec, Path]:
    """Load a spec, applying overrides (None = keep the spec's value)."""
    spec = load_spec(spec_path)
    if mascots is not None:
        spec = spec.model_copy(update={"mascots": mascots})
    if voice_override:
        spec = spec.model_copy(update={"voice": voice_override})
    if progress_bar is not None:
        spec = spec.model_copy(update={"progress_bar": progress_bar})
    project_dir = (out_dir or PROJECTS_DIR / spec.slug).resolve()
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "spec.resolved.json").write_text(spec.model_dump_json(indent=2), encoding="utf-8")
    return spec, project_dir


def run_stage(stage: str, spec: Spec, project_dir: Path, force: bool = False):
    fns: dict[str, Callable] = {
        "voice": lambda: voice.run(spec, project_dir),
        "assets": lambda: assets.run(spec, project_dir),
        "compose": lambda: compose.run(spec, project_dir),
        "render": lambda: render.run(project_dir, force=force),
        "post": lambda: post.run(spec, project_dir),
        "qa": lambda: qa.run(spec, project_dir),
    }
    if stage not in fns:
        raise ValueError(f"unknown stage {stage!r}; choose from {STAGES}")
    t0 = time.monotonic()
    result = fns[stage]()
    log.info("%s done in %.1fs", stage, time.monotonic() - t0)
    return result


def run_all(spec: Spec, project_dir: Path, force: bool = False,
            on_stage: Callable[[str], None] | None = None) -> dict:
    results = {}
    # Voice and asset search/download are independent: run them in parallel.
    if on_stage:
        on_stage("voice + assets")
    t0 = time.monotonic()
    with ThreadPoolExecutor(max_workers=2) as pool:
        fut_voice = pool.submit(voice.run, spec, project_dir)
        fut_fetch = pool.submit(assets.fetch, spec, project_dir)
        results["voice"] = fut_voice.result()
        fut_fetch.result()
    results["assets"] = assets.prepare(spec, project_dir)
    log.info("voice + assets done in %.1fs", time.monotonic() - t0)
    for stage in ("compose", "render", "post", "qa"):
        if on_stage:
            on_stage(stage)
        results[stage] = run_stage(stage, spec, project_dir, force=force)
    (project_dir / "result.json").write_text(json.dumps(results, indent=2, ensure_ascii=False, default=str))
    return results


def variant_letter(i: int) -> str:
    return chr(ord("A") + i)


def run_variants(spec: Spec, project_dir: Path, main: dict,
                 on_stage: Callable[[str], None] | None = None) -> list[dict]:
    """Render each hook variant into project_dir/variants/<B, C, …>/; A is the main render.
    Voice, assets and normalization of the unchanged scenes come from cache. Writes variants.json."""
    rows = [{"variant": "A", "hook": spec.scenes[0].narration, "on_screen": spec.scenes[0].on_screen_text,
             "final": main["post"]["final"], "duration_s": main["post"]["duration_s"],
             "qa_passed": main["qa"]["passed"]}]
    for i in range(len(spec.hook_variants)):
        letter = variant_letter(i + 1)
        vspec = spec.with_hook_variant(i)
        vdir = project_dir / "variants" / letter
        vdir.mkdir(parents=True, exist_ok=True)
        (vdir / "spec.resolved.json").write_text(vspec.model_dump_json(indent=2), encoding="utf-8")
        row = {"variant": letter, "hook": vspec.scenes[0].narration, "on_screen": vspec.scenes[0].on_screen_text}
        try:
            res = run_all(vspec, vdir, on_stage=(lambda s, l=letter: on_stage(f"variant {l}: {s}")) if on_stage else None)
            row.update(final=res["post"]["final"], duration_s=res["post"]["duration_s"], qa_passed=res["qa"]["passed"])
        except Exception as e:  # one bad variant shouldn't lose the others
            log.error("variant %s failed: %s", letter, e)
            row.update(final=None, duration_s=None, qa_passed=False, error=f"{type(e).__name__}: {e}")
        rows.append(row)
    (project_dir / "variants.json").write_text(json.dumps(rows, indent=2, ensure_ascii=False))
    return rows


def estimate_duration_s(spec: Spec) -> float:
    """Per-scene word time at each scene's delivery rate + ~0.15 s gap per scene + 1 s tail."""
    from klip import prosody
    from klip.mascot import scene_voice, video_style
    style = video_style(spec)
    speech = 0.0
    for s in spec.scenes:
        v = scene_voice(spec, s, style)
        base = spec.speech_rate or config.default_rate(v)
        speech += len(s.narration.split()) / words_per_second(v, prosody.for_scene(s, base).rate)
    return speech + 0.15 * len(spec.scenes) + 1.0
