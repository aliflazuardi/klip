"""Cut-outs for stage scenes: a photo with its background removed, as a sticker with a white outline.

Backends (klip.yaml stage.cutout.backend): `apple` (macOS Vision subject lift, via a small Swift
helper built once into the cache), `rembg` (optional Python package), `auto` (apple, then rembg).
Results are cached by the source file's content, the backend and the settings.
"""

from __future__ import annotations

import hashlib
import json
import logging
import platform
import shutil
import subprocess
from pathlib import Path

from PIL import Image, ImageFilter

from klip import config
from klip.paths import CACHE_DIR

log = logging.getLogger(__name__)

CUTOUT_VERSION = 1
LIFT_SRC = Path(__file__).parent / "tools" / "lift.swift"


class CutoutError(RuntimeError):
    pass


def _cfg() -> dict:
    return config.get("stage.cutout", {}) or {}


def _cache_dir() -> Path:
    d = CACHE_DIR / "cutout"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ---- backends: each returns an RGBA image the size of the input (transparent background)

def _lift_binary() -> Path | None:
    """The compiled Vision helper (built on first use, ~1 min), or None off macOS / without swiftc."""
    if platform.system() != "Darwin" or not shutil.which("swiftc"):
        return None
    out = _cache_dir() / f"klip-lift-{_sha(LIFT_SRC)[:12]}"
    if out.exists():
        return out
    log.info("cutout: building the Vision subject-lift helper (once, ~1 min)")
    proc = subprocess.run(["swiftc", "-O", str(LIFT_SRC), "-o", str(out)], capture_output=True, text=True)
    if proc.returncode != 0:
        log.warning("cutout: building the Vision helper failed: %s", proc.stderr.strip()[-300:])
        return None
    return out


def _apple(src: Path, out: Path) -> bool:
    exe = _lift_binary()
    if not exe:
        return False
    proc = subprocess.run([str(exe), str(src), str(out)], capture_output=True, text=True, timeout=120)
    if proc.returncode == 3:
        log.info("cutout: Vision found no subject in %s", src.name)
    elif proc.returncode:
        log.warning("cutout: Vision lift failed for %s: %s", src.name, proc.stderr.strip()[-200:])
    return proc.returncode == 0 and out.exists()


def _rembg(src: Path, out: Path) -> bool:
    try:
        from rembg import remove  # type: ignore[import-not-found]
    except ImportError:
        return False
    with Image.open(src) as im:
        remove(im.convert("RGB")).save(out)
    return True


BACKENDS = {"apple": _apple, "rembg": _rembg}


def backends() -> list[str]:
    name = _cfg().get("backend", "auto")
    if name == "auto":
        return list(BACKENDS)
    if name not in BACKENDS:
        raise CutoutError(f"unknown stage.cutout.backend {name!r} (auto, apple, rembg)")
    return [name]


# ---- post-processing

def coverage(im: Image.Image) -> float:
    """Share of the image that is (mostly) opaque."""
    alpha = im.getchannel("A")
    hist = alpha.histogram()
    return sum(hist[128:]) / max(im.width * im.height, 1)


def has_transparency(path: Path) -> bool:
    with Image.open(path) as im:
        return im.mode in ("RGBA", "LA", "PA") and coverage(im.convert("RGBA")) < 0.98


def sticker(im: Image.Image, outline_px: int, max_px: int) -> Image.Image:
    """Crop to the subject, scale to max_px and add a white outline (the 'cut out with scissors' look)."""
    im = im.convert("RGBA")
    box = im.getchannel("A").point(lambda a: 255 if a > 24 else 0).getbbox()
    if box:
        im = im.crop(box)
    scale = min(1.0, (max_px - 2 * outline_px) / max(im.width, im.height))
    if scale < 1:
        im = im.resize((max(1, round(im.width * scale)), max(1, round(im.height * scale))), Image.LANCZOS)
    pad = outline_px + 2
    canvas = Image.new("RGBA", (im.width + 2 * pad, im.height + 2 * pad), (0, 0, 0, 0))
    canvas.paste(im, (pad, pad))
    if outline_px > 0:
        alpha = canvas.getchannel("A").point(lambda a: 255 if a > 96 else 0)
        # grow the mask in steps (one huge MaxFilter is slow), then soften its edge a little
        grown = alpha
        left = outline_px
        while left > 0:
            step = min(left, 4)
            grown = grown.filter(ImageFilter.MaxFilter(2 * step + 1))
            left -= step
        grown = grown.filter(ImageFilter.GaussianBlur(1.2))
        white = Image.new("RGBA", canvas.size, (255, 255, 255, 255))
        white.putalpha(grown)
        canvas = Image.alpha_composite(white, canvas)
    return canvas


def cut_out(src: Path) -> tuple[Path | None, str]:
    """A sticker PNG for `src` (cached), or (None, reason) when no backend gave a usable subject."""
    cfg = _cfg()
    outline, max_px = int(cfg.get("outline_px", 12)), int(cfg.get("max_px", 900))
    lo, hi = float(cfg.get("min_coverage", 0.04)), float(cfg.get("max_coverage", 0.92))
    key = hashlib.sha256(json.dumps([CUTOUT_VERSION, _sha(src), outline, max_px, lo, hi]).encode()).hexdigest()[:20]
    if has_transparency(src):           # already a cut-out (your own PNG): just outline it
        names = ["given"]
    else:
        names = backends()
    reasons = []
    for name in names:
        out = _cache_dir() / f"{key}-{name}.png"
        if out.exists():
            return out, name
        raw = _cache_dir() / f"{key}-{name}.raw.png"
        if name == "given":
            shutil.copyfile(src, raw)
        else:
            try:
                ok = BACKENDS[name](src, raw)
            except Exception as e:      # a backend crashing must not stop the render
                log.warning("cutout: %s failed on %s: %s", name, src.name, e)
                ok = False
            if not ok:
                reasons.append(f"{name} unavailable or found no subject")
                continue
        with Image.open(raw) as im:
            im = im.convert("RGBA")
            cov = coverage(im)
            if not lo <= cov <= hi:
                reasons.append(f"{name} mask covers {cov:.0%} of the photo")
                raw.unlink(missing_ok=True)
                continue
            sticker(im, outline, max_px).save(out)
        raw.unlink(missing_ok=True)
        return out, name
    return None, "; ".join(reasons) or "no backend"


def card(src: Path) -> Path:
    """A photo resized for a stage photo card (cached JPEG; the white frame is drawn in CSS)."""
    max_px = int(_cfg().get("max_px", 900))
    out = _cache_dir() / f"card-{_sha(src)[:20]}-{max_px}.jpg"
    if not out.exists():
        with Image.open(src) as im:
            im = im.convert("RGB")
            im.thumbnail((max_px, max_px), Image.LANCZOS)
            im.save(out, quality=88)
    return out


def fit(src: Path, max_px: int) -> Path:
    """An image resized to fit max_px, transparency kept (logos, screenshots); cached PNG."""
    out = _cache_dir() / f"fit-{_sha(src)[:20]}-{max_px}.png"
    if not out.exists():
        with Image.open(src) as im:
            im = im.convert("RGBA")
            im.thumbnail((max_px, max_px), Image.LANCZOS)
            im.save(out, optimize=True)
    return out
