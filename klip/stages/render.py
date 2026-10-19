"""Stage 5 — Render: composition/ -> raw.mp4 (video only). Skips when the composition is unchanged."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from klip import config
from klip.engines.render.base import Renderer
from klip.engines.render.hyperframes import HyperFramesRenderer

log = logging.getLogger(__name__)


def run(project_dir: Path, renderer: Renderer | None = None, force: bool = False) -> Path:
    renderer = renderer or HyperFramesRenderer()
    comp = project_dir / "composition"
    comp_hash = json.loads((comp / "compose.json").read_text())["hash"]
    raw, stamp = project_dir / "raw.mp4", project_dir / "render.json"
    if not force and raw.exists() and stamp.exists():
        if json.loads(stamp.read_text()).get("hash") == comp_hash:
            log.info("render: composition unchanged, reusing raw.mp4")
            return raw
    renderer.render(comp, raw, fps=config.get("render.fps", 30))
    stamp.write_text(json.dumps({"hash": comp_hash, "renderer": renderer.name}))
    return raw
