"""`klip batch topics.yaml`: many videos in one go; one failure never stops the rest.

topics.yaml:
    defaults: {voice: female, duration: 45, style: default}   # also progress_bar: true/false
    items:
      - "Kenapa kita cegukan?"                       # topic, defaults apply
      - {topic: "Kenapa bawang bikin nangis?", voice: male, duration: 40}
      - {spec: specs/kenapa-langit-biru.json, voice: male}   # render an existing spec

With --scripts-only, specs are written and a <name>.specs.yaml is produced listing them, so
you can review everything, then render with `klip batch <name>.specs.yaml`.
"""

from __future__ import annotations

import json
import logging
import time
import traceback
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

import yaml

from klip import pipeline
from klip.paths import PROJECTS_DIR, ROOT

log = logging.getLogger(__name__)


@dataclass
class Item:
    label: str
    topic: str | None = None
    spec: str | None = None
    voice: str | None = None
    duration: int = 45
    style: str = "default"
    hooks: int = 1
    progress_bar: bool | None = None      # None = the spec's / style's setting


@dataclass
class ItemResult:
    label: str
    status: str                      # ok | qa_failed | failed | scripted
    spec_path: str | None = None
    final: str | None = None
    duration_s: float | None = None
    detail: str = ""
    seconds: float = 0.0


def load(path: Path) -> list[Item]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    raw_items = data.get("items") if isinstance(data, dict) else data
    if not raw_items:
        raise ValueError(f"{path}: no items")
    d = (data.get("defaults") if isinstance(data, dict) else None) or {}
    items = []
    for i, raw in enumerate(raw_items, 1):
        if isinstance(raw, str):
            raw = {"topic": raw}
        if not isinstance(raw, dict) or not (raw.get("topic") or raw.get("spec")):
            raise ValueError(f"{path}: item {i} needs a topic or a spec")
        spec = raw.get("spec")
        if spec and not Path(spec).is_absolute():
            # relative to the batch file first, then the repo root
            spec = str(p if (p := path.parent / spec).exists() else ROOT / spec)
        items.append(Item(label=raw.get("topic") or Path(spec).stem, topic=raw.get("topic"), spec=spec,
                          voice=raw.get("voice", d.get("voice")),
                          duration=int(raw.get("duration", d.get("duration", 45))),
                          style=raw.get("style", d.get("style", "default")),
                          hooks=int(raw.get("hooks", d.get("hooks", 1))),
                          progress_bar=raw.get("progress_bar", d.get("progress_bar"))))
    return items


def run(path: Path, scripts_only: bool = False,
        on_item: Callable[[int, int, Item, str], None] | None = None) -> tuple[list[ItemResult], Path]:
    from klip.stages import script

    items = load(path)
    results: list[ItemResult] = []
    for n, item in enumerate(items, 1):
        t0 = time.monotonic()
        stage = "script"
        try:
            spec_path = Path(item.spec) if item.spec else None
            if spec_path is None:
                if on_item:
                    on_item(n, len(items), item, "writing script")
                res = script.generate(item.topic, item.voice or "female", item.duration, item.style,
                                      script.get_provider(), hooks=item.hooks)
                gen = res.spec if item.progress_bar is None else \
                    res.spec.model_copy(update={"progress_bar": item.progress_bar})
                spec_path = script.save(gen)
            if scripts_only:
                results.append(ItemResult(item.label, "scripted", str(spec_path)))
                continue
            stage = "render"
            if on_item:
                on_item(n, len(items), item, "rendering")
            spec, project_dir = pipeline.resolve(spec_path, item.voice, progress_bar=item.progress_bar)
            out = pipeline.run_all(spec, project_dir)
            if spec.hook_variants:
                pipeline.run_variants(spec, project_dir, out)
            qa = out["qa"]
            failed = [c["name"] for c in qa["checks"] if not c["ok"]]
            results.append(ItemResult(
                item.label, "ok" if qa["passed"] else "qa_failed", str(spec_path),
                out["post"]["final"], out["post"]["duration_s"],
                "" if qa["passed"] else "QA failed: " + ", ".join(failed)))
        except Exception as e:
            log.error("batch item %d (%s) failed during %s: %s\n%s", n, item.label, stage, e, traceback.format_exc())
            results.append(ItemResult(item.label, "failed", str(item.spec or ""),
                                      detail=f"{stage}: {type(e).__name__}: {e}"[:300]))
        finally:
            if results and results[-1].label == item.label:
                results[-1].seconds = round(time.monotonic() - t0, 1)

    out_dir = PROJECTS_DIR / "_batch"
    out_dir.mkdir(parents=True, exist_ok=True)
    report = out_dir / f"{path.stem}-{time.strftime('%Y%m%d-%H%M%S')}.json"
    report.write_text(json.dumps([asdict(r) for r in results], indent=2, ensure_ascii=False))
    if scripts_only:
        follow = path.with_name(f"{path.stem}.specs.yaml")
        follow.write_text(yaml.safe_dump(
            {"items": [{"spec": r.spec_path} for r in results if r.spec_path]}, allow_unicode=True, sort_keys=False))
    return results, report
