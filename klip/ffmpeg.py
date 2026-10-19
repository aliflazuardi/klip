"""Thin wrappers around ffmpeg / ffprobe."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path


class FFmpegError(RuntimeError):
    pass


def run(args: list[str]) -> subprocess.CompletedProcess:
    cmd = ["ffmpeg", "-hide_banner", "-nostdin", "-y", *args]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise FFmpegError(f"ffmpeg failed ({proc.returncode}): {' '.join(cmd)}\n{proc.stderr[-2000:]}")
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
