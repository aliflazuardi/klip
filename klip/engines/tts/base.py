from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol


@dataclass
class Word:
    """A timed word. Times are milliseconds relative to the start of its audio clip."""

    text: str
    start_ms: float
    end_ms: float

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> Word:
        return cls(d["text"], float(d["start_ms"]), float(d["end_ms"]))


class TTSError(RuntimeError):
    pass


class TTSEngine(Protocol):
    name: str

    def synthesize(self, text: str, voice_id: str, rate: str, out_path: Path,
                   pitch: str = "+0Hz", volume: str = "+0%") -> list[Word]:
        """Write audio to `out_path` (mp3) and return word timings."""
        ...
