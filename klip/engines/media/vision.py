"""Vision relevance check: Claude looks at stock thumbnails before anything is downloaded.

Tags say a clip contains "container"; only a look tells you it's a cargo port. Per scene we
build one numbered contact sheet; a single `claude -p` call reviews every scene of the video
(Read tool only, in a temp dir holding just the sheets) and returns, per scene, the suitable
candidates best-first. Stage props (cutout/photo elements) get their own sheets in the same
call. Runs on the user's Claude plan, no API key.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from klip import config
from klip.engines.llm.base import LLMError
from klip.engines.llm.claude_cli import parse_output

log = logging.getLogger(__name__)

CELL_W, CELL_H, COLS = 360, 240, 3
BADGE = 56


def _font(size: int) -> ImageFont.ImageFont:
    for path in ("/System/Library/Fonts/Supplemental/Arial Bold.ttf",
                 "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"):
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default(size=size)


def contact_sheet(images: list[Path | None], out: Path, cols: int = COLS) -> Path:
    """Grid of thumbnails, letterboxed (nothing cropped away), each with a big number 1..N.
    A missing/broken image becomes a grey cell so numbering never shifts."""
    rows = (len(images) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * CELL_W, rows * CELL_H), (24, 24, 28))
    draw = ImageDraw.Draw(sheet)
    font = _font(36)
    for i, path in enumerate(images):
        x, y = (i % cols) * CELL_W, (i // cols) * CELL_H
        try:
            im = Image.open(path).convert("RGB") if path else None
        except Exception:
            im = None
        if im:
            im.thumbnail((CELL_W - 8, CELL_H - 8))
            sheet.paste(im, (x + (CELL_W - im.width) // 2, y + (CELL_H - im.height) // 2))
        draw.rectangle([x + 4, y + 4, x + 4 + BADGE, y + 4 + BADGE], fill=(255, 212, 59))
        draw.text((x + 4 + BADGE / 2, y + 4 + BADGE / 2), str(i + 1), fill=(0, 0, 0), font=font, anchor="mm")
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out, quality=85)
    return out


@dataclass
class SceneSheet:
    id: str
    narration: str
    on_screen: str
    query: str
    sheet: Path
    count: int
    prop: str = ""        # stage prop sheets: what the element is and where it pops in


SYSTEM = """You rate b-roll for short Indonesian educational TikTok videos (vertical 9:16; footage
is center-cropped; photos get a slow zoom). For each scene you get its narration and a contact
sheet of numbered stock thumbnails (videos and photos). Read each sheet image file, then rate
EVERY candidate:
  3 = clearly shows what the narration is talking about
  2 = closely related and would feel natural behind this line
  1 = only loosely related or generic
  0 = wrong subject (e.g. shipping containers for "food container"), misleading, sensational,
      heavy text/watermarks/logos, or inappropriate for a general Indonesian audience
B-roll illustrates; it doesn't need to match every word. Judge each on its own.

Some sheets are for a stage prop instead of a scene: one photo that becomes a sticker (cutout:
its background is removed) or a small photo card, popping in as the narration says the given
word. Rate whether it shows that exact object or person (a burger plate is a 0 for "tempeh").
For cutouts, 3 needs one clear subject on a plain or simple background; the right subject in a
busy scene, cropped off, or among many other objects is a 2 at best."""

SCHEMA = {
    "type": "object",
    "properties": {"scenes": {"type": "array", "items": {
        "type": "object",
        "properties": {"id": {"type": "string"},
                       "ratings": {"type": "array", "items": {"type": "integer", "minimum": 0, "maximum": 3},
                                   "description": "one 0-3 rating per candidate, in sheet order (1, 2, …)"}},
        "required": ["id", "ratings"]}}},
    "required": ["scenes"],
}


class VisionReviewer:
    def __init__(self, binary: str | None = None):
        self.binary = binary or shutil.which("claude")

    def available(self) -> bool:
        return bool(self.binary)

    def review(self, sheets: list[SceneSheet]) -> dict[str, list[int]]:
        """scene id → 0-3 rating per candidate, in sheet order."""
        if not sheets:
            return {}
        cfg = config.get("assets.vision_check", {}) or {}
        with tempfile.TemporaryDirectory() as cwd:
            lines = []
            for s in sheets:
                name = f"{s.id}.jpg"
                shutil.copyfile(s.sheet, Path(cwd) / name)
                what = f"prop {s.id}: sheet ./{name} ({s.count} candidates)\n  prop: {s.prop}" if s.prop \
                    else f"scene {s.id}: sheet ./{name} ({s.count} candidates)"
                lines.append(f"- {what}\n  narration: {s.narration}\n  on-screen: {s.on_screen or '-'}\n"
                             f"  search query: {s.query}")
            user = "Review these sheets. Read every sheet file before answering.\n\n" + "\n".join(lines)
            cmd = [self.binary, "-p", "--output-format", "json", "--no-session-persistence",
                   "--system-prompt", SYSTEM, "--json-schema", json.dumps(SCHEMA),
                   "--tools", "Read", "--allowedTools", "Read"]
            if model := (cfg.get("model") or config.get("llm.claude.model")):
                cmd += ["--model", str(model)]
            try:
                proc = subprocess.run(cmd, input=user, capture_output=True, text=True, cwd=cwd,
                                      timeout=cfg.get("timeout_s", 300))
            except subprocess.TimeoutExpired:
                raise LLMError("vision check timed out") from None
        answer = parse_output(proc.stdout, proc.stderr, proc.returncode)
        data = answer if isinstance(answer, dict) else json.loads(answer)
        counts = {s.id: s.count for s in sheets}
        out = {}
        for row in data.get("scenes", []):
            sid = str(row.get("id", "")).removeprefix("scene ").removeprefix("prop ").strip()
            if sid in counts:
                r = [max(0, min(3, int(x))) if isinstance(x, (int, float)) else 0 for x in row.get("ratings", [])]
                out[sid] = (r + [0] * counts[sid])[:counts[sid]]   # missing ratings count as 0
        return out
