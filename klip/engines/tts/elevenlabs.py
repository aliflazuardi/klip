"""ElevenLabs engine: the with-timestamps endpoint returns MP3 plus per-character timings,
which become word timings (no aligner needed). Needs ELEVENLABS_API_KEY.
"""

from __future__ import annotations

import base64
import json
import logging
import time
import urllib.error
import urllib.request
from pathlib import Path

from klip import config, env
from klip.engines.tts.base import TTSError, Word

log = logging.getLogger(__name__)

URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice}/with-timestamps?output_format=mp3_44100_128"


def chars_to_words(chars: list[str], starts: list[float], ends: list[float]) -> list[Word]:
    """Per-character alignment → words (split on whitespace), times in ms."""
    words: list[Word] = []
    cur, t0, t1 = "", 0.0, 0.0
    for ch, a, b in zip(chars, starts, ends):
        if ch.isspace():
            if cur:
                words.append(Word(cur, t0 * 1000, t1 * 1000))
            cur = ""
            continue
        if not cur:
            t0 = a
        cur, t1 = cur + ch, b
    if cur:
        words.append(Word(cur, t0 * 1000, t1 * 1000))
    return words


def speed_for(rate: str) -> float:
    """Edge-style rate ('+8%') → ElevenLabs speed, clamped to elevenlabs.speed_range."""
    lo, hi = config.get("elevenlabs.speed_range")
    return round(min(max(1 + int(rate.rstrip("%")) / 100, lo), hi), 3)


class ElevenLabsTTS:
    name = "elevenlabs"
    ext = ".mp3"

    def __init__(self, retries: int = 3):
        self.retries = retries
        self.key = env.get("ELEVENLABS_API_KEY")
        c = config.get("elevenlabs")
        self.cache_tag = json.dumps([c["model"], c["stability"], c["similarity_boost"], c["style"]])

    def synthesize(self, text: str, voice_id: str, rate: str, out_path: Path,
                   pitch: str = "+0Hz", volume: str = "+0%") -> list[Word]:
        if not self.key:
            raise TTSError("ELEVENLABS_API_KEY is not set (add it to .env)")
        c = config.get("elevenlabs")
        body = {"text": text, "model_id": c["model"],
                "voice_settings": {"stability": c["stability"], "similarity_boost": c["similarity_boost"],
                                   "style": c["style"], "use_speaker_boost": True, "speed": speed_for(rate)}}
        if c.get("language_code"):
            body["language_code"] = c["language_code"]
        req = urllib.request.Request(URL.format(voice=voice_id), data=json.dumps(body).encode(), method="POST",
                                     headers={"xi-api-key": self.key, "Content-Type": "application/json"})
        last = None
        for attempt in range(self.retries):
            try:
                with urllib.request.urlopen(req, timeout=180) as r:
                    data = json.load(r)
                break
            except urllib.error.HTTPError as e:
                detail = e.read().decode(errors="replace")[:300]
                if e.code in (429, 500, 502, 503) and attempt + 1 < self.retries:
                    time.sleep(2 * 2 ** attempt)
                    continue
                raise TTSError(f"ElevenLabs HTTP {e.code}: {detail}") from None
            except (urllib.error.URLError, TimeoutError) as e:
                last = e
                time.sleep(2 * 2 ** attempt)
        else:
            raise TTSError(f"ElevenLabs unreachable: {last}")
        audio = base64.b64decode(data.get("audio_base64") or "")
        if not audio:
            raise TTSError("ElevenLabs returned no audio")
        Path(out_path).write_bytes(audio)
        al = data.get("alignment") or data.get("normalized_alignment")
        if not al:
            return []                      # no timings: the voice stage aligns the audio instead
        return chars_to_words(al["characters"], al["character_start_times_seconds"], al["character_end_times_seconds"])
