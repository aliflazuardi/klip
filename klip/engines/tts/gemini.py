"""Gemini TTS engine (Interactions API): natural delivery steered by a style prompt
(gemini_tts.style). Returns WAV without word timings; the voice stage aligns the audio
(klip/align.py). Needs GEMINI_API_KEY.
"""

from __future__ import annotations

import base64
import json
import re
import logging
import time
import urllib.error
import urllib.request
from pathlib import Path

from klip import config, env
from klip.engines.tts.base import TTSError, Word

log = logging.getLogger(__name__)

URL = "https://generativelanguage.googleapis.com/v1beta/interactions"


def find_audio(node) -> str | None:
    """The last base64 audio in a response (Interactions: steps[].content[] {type: audio, data};
    older generateContent: candidates[].content.parts[].inlineData.data)."""
    found = None
    if isinstance(node, dict):
        if node.get("type") == "audio" and isinstance(node.get("data"), str):
            found = node["data"]
        inline = node.get("inlineData") or node.get("inline_data")
        if isinstance(inline, dict) and isinstance(inline.get("data"), str):
            found = inline["data"]
        for v in node.values():
            found = find_audio(v) or found
    elif isinstance(node, list):
        for v in node:
            found = find_audio(v) or found
    return found


def to_wav(audio: bytes, rate: int = 24000) -> bytes:
    """WAV as-is; headerless 16-bit mono PCM gets a RIFF header."""
    if audio[:4] == b"RIFF":
        return audio
    import struct
    n = len(audio)
    return b"RIFF" + struct.pack("<I", 36 + n) + b"WAVEfmt " + struct.pack("<IHHIIHH", 16, 1, 1, rate, rate * 2, 2, 16) \
        + b"data" + struct.pack("<I", n) + audio



def retry_wait(code: int, detail: str, attempt: int) -> float:
    """Seconds to wait before retrying: a rate limit says how long ("retry in 34s"; the free tier
    allows a few requests a minute, and a dialogue video makes one per narrator turn), capped at
    gemini_tts.max_wait_s; other errors back off exponentially."""
    if code == 429 and (m := re.search(r"retry in ([\d.]+)\s*s", detail)):
        return min(float(m.group(1)) + 1.0, float(config.get("gemini_tts.max_wait_s")))
    return 3 * 2 ** attempt

class GeminiTTS:
    name = "gemini"
    ext = ".wav"

    def __init__(self, retries: int = 5):
        self.retries = retries
        self.key = env.get("GEMINI_API_KEY")
        c = config.get("gemini_tts")
        self.cache_tag = json.dumps([c["model"], c["style"]], ensure_ascii=False)

    def synthesize(self, text: str, voice_id: str, rate: str, out_path: Path,
                   pitch: str = "+0Hz", volume: str = "+0%") -> list[Word]:
        c = config.get("gemini_tts")
        body = {"model": c["model"],
                "input": [{"type": "user_input", "content": [{
                    "type": "text", "text": text,
                    "annotations": [{"type": "speech_metadata", "style": c["style"]}]}]}],
                "response_format": {"type": "audio"},
                "generation_config": {"speech_config": [{"voice": voice_id}]}}
        return self._request(body, out_path)

    def synthesize_dialogue(self, lines: list[tuple[str, str]], voices: dict[str, str], out_path: Path) -> list[Word]:
        """A two-speaker script in ONE request: lines = [(speaker, text)], voices = {speaker: voice id}.
        Each line is its own text turn annotated with its speaker (and the style); no word timings."""
        if len(voices) > 2:
            raise TTSError("Gemini multi-speaker TTS takes at most 2 speakers")
        c = config.get("gemini_tts")
        turns = [{"type": "text", "text": text,
                  "annotations": [{"type": "speech_metadata", "speaker": who, "style": c["style"]}]} for who, text in lines]
        body = {"model": c["model"], "input": [{"type": "user_input", "content": turns}],
                "response_format": {"type": "audio"},
                "generation_config": {"speech_config": [{"speaker": who, "voice": v} for who, v in voices.items()]}}
        return self._request(body, out_path)

    def _request(self, body: dict, out_path: Path) -> list[Word]:
        if not self.key:
            raise TTSError("GEMINI_API_KEY is not set (add it to .env)")
        req = urllib.request.Request(URL, data=json.dumps(body, ensure_ascii=False).encode(), method="POST",
                                     headers={"x-goog-api-key": self.key, "Content-Type": "application/json"})
        last = None
        for attempt in range(self.retries):
            try:
                with urllib.request.urlopen(req, timeout=300) as r:
                    data = json.load(r)
                break
            except urllib.error.HTTPError as e:
                detail = e.read().decode(errors="replace")[:300]
                if e.code in (429, 500, 502, 503) and attempt + 1 < self.retries:
                    time.sleep(retry_wait(e.code, detail, attempt))
                    continue
                raise TTSError(f"Gemini TTS HTTP {e.code}: {detail}") from None
            except (urllib.error.URLError, TimeoutError) as e:
                last = e
                time.sleep(3 * 2 ** attempt)
        else:
            raise TTSError(f"Gemini TTS unreachable: {last}")
        b64 = find_audio(data)
        if not b64:
            raise TTSError(f"Gemini TTS returned no audio: {json.dumps(data)[:300]}")
        Path(out_path).write_bytes(to_wav(base64.b64decode(b64)))
        return []
