"""edge-tts engine (Microsoft Edge online voices).

Notes:
- edge-tts 7.x defaults to SentenceBoundary; we must pass boundary="WordBoundary".
- Offsets/durations are in 100-nanosecond ticks.
- 7.2.7 started returning 403 in Oct 2026; 7.3.1 works. Keep the version pinned.
"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path

import edge_tts

from klip.engines.tts.base import TTSError, Word

log = logging.getLogger(__name__)

TICKS_PER_MS = 10_000


def ticks_to_ms(ticks: int | float) -> float:
    return ticks / TICKS_PER_MS


class EdgeTTS:
    name = "edge"
    ext = ".mp3"

    def __init__(self, retries: int = 3, backoff_s: float = 1.5):
        self.retries = retries
        self.backoff_s = backoff_s

    def synthesize(self, text: str, voice_id: str, rate: str, out_path: Path,
                   pitch: str = "+0Hz", volume: str = "+0%") -> list[Word]:
        last: Exception | None = None
        for attempt in range(self.retries):
            try:
                return asyncio.run(self._synthesize(text, voice_id, rate, Path(out_path), pitch, volume))
            except Exception as e:  # network / auth / empty audio
                last = e
                if attempt + 1 < self.retries:
                    delay = self.backoff_s * 2**attempt
                    log.warning("edge-tts attempt %d failed (%s); retrying in %.1fs", attempt + 1, e, delay)
                    time.sleep(delay)
        raise TTSError(f"edge-tts failed after {self.retries} attempts: {last}") from last

    async def _synthesize(self, text: str, voice_id: str, rate: str, out_path: Path,
                          pitch: str = "+0Hz", volume: str = "+0%") -> list[Word]:
        communicate = edge_tts.Communicate(text, voice_id, rate=rate, pitch=pitch, volume=volume,
                                           boundary="WordBoundary")
        words: list[Word] = []
        tmp = out_path.with_suffix(".part")
        size = 0
        with tmp.open("wb") as f:
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    f.write(chunk["data"])
                    size += len(chunk["data"])
                elif chunk["type"] == "WordBoundary":
                    start = ticks_to_ms(chunk["offset"])
                    words.append(Word(chunk["text"], start, start + ticks_to_ms(chunk["duration"])))
        if size == 0:
            tmp.unlink(missing_ok=True)
            raise TTSError("edge-tts returned no audio")
        tmp.replace(out_path)
        return words
