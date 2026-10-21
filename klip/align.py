"""Forced alignment for TTS engines that return no word timings (Gemini): transcribe the audio
with faster-whisper (word timestamps), then map the transcript onto the script's own tokens
(captions.align), so mis-heard words still get the script's spelling. Optional dependency:
`uv sync --extra align`. Results are cached by audio hash + text.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from functools import cache

from klip import config, paths
from klip.captions import align as align_tokens, tokenize
from klip.engines.tts.base import Word


class AlignError(RuntimeError):
    pass


@cache
def _model():
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        raise AlignError("this TTS engine needs the aligner: run `uv sync --extra align`") from None
    c = config.get("align")
    return WhisperModel(c["model"], device=c["device"], compute_type=c["compute_type"])


def _samples(path):
    """16 kHz mono float32 via ffmpeg (faster-whisper's own decoder breaks with newer PyAV)."""
    import numpy as np
    pcm = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-ac", "1", "-ar", "16000", "-f", "s16le", "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(pcm, np.int16).astype(np.float32) / 32768


def transcribe(path) -> list[Word]:
    segs, _ = _model().transcribe(_samples(path), language=config.get("align.language"), word_timestamps=True,
                                  vad_filter=False, condition_on_previous_text=False)
    return [Word(w.word.strip(), w.start * 1000, w.end * 1000) for s in segs for w in (s.words or []) if w.word.strip()]


def align_audio(path, text: str) -> list[Word]:
    """Word timings for `text` as spoken in `path` (one Word per token of `text`)."""
    key = hashlib.sha256(path.read_bytes() + text.encode() + json.dumps(
        [config.get("align.model"), config.get("align.offset_ms")]).encode()).hexdigest()[:24]
    cached = paths.CACHE_DIR / "align" / f"{key}.json"
    if cached.exists():
        return [Word.from_dict(d) for d in json.loads(cached.read_text())]
    heard = transcribe(path)
    if not heard:
        raise AlignError(f"the aligner heard no words in {path.name}")
    off = float(config.get("align.offset_ms") or 0)
    heard = [Word(w.text, w.start_ms + off, w.end_ms + off) for w in heard]
    words = align_tokens(tokenize(text), heard)
    cached.parent.mkdir(parents=True, exist_ok=True)
    cached.write_text(json.dumps([w.to_dict() for w in words], ensure_ascii=False))
    return words
