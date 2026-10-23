"""Thin wrappers around ffmpeg / ffprobe."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path


class FFmpegError(RuntimeError):
    pass


def run(args: list[str], binary: bool = False) -> subprocess.CompletedProcess:
    """Run ffmpeg; binary=True keeps stdout as bytes (raw frames piped out)."""
    cmd = ["ffmpeg", "-hide_banner", "-nostdin", "-y", *args]
    proc = subprocess.run(cmd, capture_output=True, text=not binary)
    if proc.returncode != 0:
        err = proc.stderr if not binary else proc.stderr.decode(errors="replace")
        raise FFmpegError(f"ffmpeg failed ({proc.returncode}): {' '.join(cmd)}\n{err[-2000:]}")
    return proc


def probe(path: str | Path) -> dict:
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise FFmpegError(f"ffprobe failed on {path}: {proc.stderr}")
    return json.loads(proc.stdout)


def duration_ms(path: str | Path) -> float:
    return float(probe(path)["format"]["duration"]) * 1000
