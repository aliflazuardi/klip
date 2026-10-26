"""HyperFrames renderer (heygen-com/hyperframes, Apache-2.0). Requires Node >= 22."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

from klip import config
from klip.engines.render.base import RenderError
from klip.paths import RENDERER_DIR

MIN_NODE_MAJOR = 22


def _node_major(node: str) -> int | None:
    try:
        out = subprocess.run([node, "--version"], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    m = re.match(r"v(\d+)", out.strip())
    return int(m.group(1)) if m else None


def find_node() -> str:
    """KLIP_NODE, else `node` on PATH if new enough, else the newest nvm install >= 22."""
    candidates: list[str] = []
    if env := os.environ.get("KLIP_NODE"):
        candidates.append(env)
    if on_path := shutil.which("node"):
        candidates.append(on_path)
    nvm = Path(os.environ.get("NVM_DIR", Path.home() / ".nvm")) / "versions" / "node"
    if nvm.is_dir():
        def ver(p: Path) -> tuple[int, ...]:
            return tuple(int(x) for x in re.findall(r"\d+", p.name))
        candidates += [str(p / "bin" / "node") for p in sorted(nvm.iterdir(), key=ver, reverse=True)]
    for c in candidates:
        major = _node_major(c)
        if major is not None and major >= MIN_NODE_MAJOR:
            return c
    raise RenderError(f"Node >= {MIN_NODE_MAJOR} not found. Install it (e.g. `nvm install 22`) or set KLIP_NODE.")


def resolve_workers(workers: str) -> str:
    """'cores' = one Chrome per CPU core but one (capped by render.max_workers); else as given."""
    if workers != "cores":
        return workers
    return str(max(1, min(int(config.get("render.max_workers")), (os.cpu_count() or 2) - 1)))


class HyperFramesRenderer:
    name = "hyperframes"

    def __init__(self, quality: str | None = None, workers: str | None = None):
        self.quality = quality or config.get("render.quality", "looks")
        self.workers = resolve_workers(str(workers or config.get("render.workers", "auto")))

    @property
    def settings(self) -> dict:
        """What decides the raw video besides the composition (a change re-renders)."""
        return {"quality": self.quality, "crf": config.get("render.crf")}

    @property
    def cli(self) -> Path:
        return RENDERER_DIR / "node_modules" / "hyperframes" / "bin" / "hyperframes.mjs"

    def _run(self, command: str, args: list[str], expect: Path) -> None:
        if not self.cli.exists():
            raise RenderError("HyperFrames not installed; run `npm install` in renderer/")
        node = find_node()
        env = {**os.environ, "HYPERFRAMES_NO_TELEMETRY": "1", "DO_NOT_TRACK": "1",
               "HYPERFRAMES_SKIP_SKILLS": "1",
               # put the chosen node first so any child `node` calls match
               "PATH": f"{Path(node).parent}{os.pathsep}{os.environ.get('PATH', '')}"}
        proc = subprocess.run([node, str(self.cli), command, *args], capture_output=True, text=True,
                              env=env, cwd=RENDERER_DIR)
        if proc.returncode != 0 or not expect.exists():
            tail = (proc.stdout[-1500:] + "\n" + proc.stderr[-2500:]).strip()
            raise RenderError(f"hyperframes {command} failed ({proc.returncode}):\n{tail}")

    def render(self, composition_dir: Path, out_path: Path, fps: int = 30) -> Path:
        args = [str(composition_dir.resolve()), "-o", str(out_path.resolve()), "--fps", str(fps),
                "--quality", self.quality, "--workers", self.workers, "--quiet", "--strict"]
        if (crf := config.get("render.crf")) is not None:
            args += ["--crf", str(crf)]           # encode once at the final quality; post copies this stream
        if not config.get("render.fast_capture"):
            args.append("--experimental-fast-capture=false")
        self._run("render", args, out_path)
        return out_path

    def still(self, composition_dir: Path, out_png: Path, at: float = 0.0) -> Path:
        """One full-size PNG of the composition at `at` seconds (`hyperframes snapshot`)."""
        shots = composition_dir / ".snapshot"
        png = shots / f"at-{at:g}s.png"
        png.unlink(missing_ok=True)
        self._run("snapshot", [str(composition_dir.resolve()), "--at", f"{at:g}", "--no-end", "--keep",
                               "--describe", "false", "-o", str(shots.resolve())], png)
        png.replace(out_png)
        return out_png

    def stills(self, composition_dir: Path, out_dir: Path, times: list[float]) -> dict[float, Path]:
        """Full-size PNGs of the composition at each time (one `hyperframes snapshot` run): {time: png}."""
        out_dir.mkdir(parents=True, exist_ok=True)
        for old in out_dir.glob("at-*.png"):
            old.unlink()
        times = sorted({round(t, 3) for t in times})
        self._run("snapshot", [str(composition_dir.resolve()), "--at", ",".join(f"{t:g}" for t in times), "--no-end",
                               "--keep", "--describe", "false", "--timeout", "20000", "-o", str(out_dir.resolve())],
                  out_dir)
        found = {round(float(p.stem[3:-1]), 3): p for p in out_dir.glob("at-*s.png")}
        missing = [t for t in times if t not in found]
        if missing:
            raise RenderError(f"hyperframes snapshot wrote no still for {missing}")
        return {t: found[t] for t in times}
