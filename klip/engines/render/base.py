from __future__ import annotations

from pathlib import Path
from typing import Protocol


class RenderError(RuntimeError):
    pass


class Renderer(Protocol):
    name: str

    def render(self, composition_dir: Path, out_path: Path, fps: int = 30) -> Path:
        """Render the composition to a video-only MP4 at out_path."""
        ...
