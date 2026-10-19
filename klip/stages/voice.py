"""Stage 2 — Voice: per-scene TTS, word timings, timeline, voice.wav.

Writes into the project dir:
  audio/<scene>.mp3   per-scene audio (copied from cache)
  words.json          [{text, startMs, endMs, sceneId}] absolute times, display tokens
  timeline.json       scene start/duration in the final video
  voice.wav           all scene audio placed on the timeline
"""

from __future__ import annotations

import hashlib
import json
import re
import logging
import shutil
from pathlib import Path

from klip import config, ffmpeg, prosody
from klip.captions import align, tokenize
from klip.engines.tts.base import TTSEngine, Word
from klip.engines.tts.edge import EdgeTTS
from klip.lexicon import apply_lexicon
from klip.paths import CACHE_DIR
from klip.spec import Spec

log = logging.getLogger(__name__)

GAP_MS = config.get("timeline.gap_ms", 150)            # silence between scenes
TAIL_MS = config.get("timeline.tail_ms", 1000)         # hold after the last scene
MIN_SCENE_MS = config.get("timeline.min_scene_ms", 1500)
HOOK_LEAD_MS = config.get("timeline.hook_lead_ms", 60)  # first word starts this soon after frame 0


def get_engine(name: str) -> TTSEngine:
    if name == "edge":
        return EdgeTTS()
    raise ValueError(f"unknown TTS engine {name!r}")


def _cache_key(engine: str, voice_id: str, rate: str, text: str,
               pitch: str = "+0Hz", volume: str = "+0%") -> str:
    parts = [1, engine, voice_id, rate, text]
    if (pitch, volume) != ("+0Hz", "+0%"):   # neutral keeps its old key, so existing caches stay valid
        parts += [pitch, volume]
    payload = json.dumps(parts, ensure_ascii=False)
    return hashlib.sha256(payload.encode()).hexdigest()[:20]


def synthesize_cached(engine: TTSEngine, text: str, voice_id: str, rate: str,
                      pitch: str = "+0Hz", volume: str = "+0%") -> tuple[Path, list[Word]]:
    cache = CACHE_DIR / "tts"
    cache.mkdir(parents=True, exist_ok=True)
    key = _cache_key(engine.name, voice_id, rate, text, pitch, volume)
    mp3, meta = cache / f"{key}.mp3", cache / f"{key}.json"
    if mp3.exists() and meta.exists():
        return mp3, [Word.from_dict(d) for d in json.loads(meta.read_text())]
    words = engine.synthesize(text, voice_id, rate, mp3, pitch=pitch, volume=volume)
    meta.write_text(json.dumps([w.to_dict() for w in words], ensure_ascii=False))
    return mp3, words


def merge_breaths(pauses: list[tuple[float, float]], max_blip_ms: float = 140) -> list[tuple[float, float]]:
    """Join pauses separated by a blip shorter than a word (an audible breath before speaking)."""
    merged: list[tuple[float, float]] = []
    for a, b in pauses:
        if merged and a - merged[-1][1] < max_blip_ms:
            merged[-1] = (merged[-1][0], b)
        else:
            merged.append((a, b))
    return merged


def silences(audio: Path, min_ms: int = 120, noise_db: int = -35) -> list[tuple[float, float]]:
    """Pauses in a clip as (start_ms, end_ms), with breaths folded into the pause around them."""
    err = ffmpeg.run(["-i", str(audio), "-af", f"silencedetect=noise={noise_db}dB:d={min_ms / 1000}",
                      "-f", "null", "-"]).stderr
    starts = [float(x) * 1000 for x in re.findall(r"silence_start: (-?[\d.]+)", err)]
    ends = [float(x) * 1000 for x in re.findall(r"silence_end: ([\d.]+)", err)]
    return merge_breaths(list(zip(starts, ends)))


def snap_to_speech(words: list[Word], pauses: list[tuple[float, float]]) -> list[Word]:
    """edge-tts times the first word after a sentence break from the start of the pause, so its
    caption (and anything keyed to it) fires ~0.3 s early. Move such starts to where sound resumes."""
    out = []
    for w in words:
        start = w.start_ms
        for a, b in pauses:
            if a <= start < b - 20:
                start = b
                break
        out.append(Word(w.text, start, max(w.end_ms, start)))
    return out


def run(spec: Spec, project_dir: Path, engine: TTSEngine | None = None) -> dict:
    engine_name = config.get("voices.engine", "edge")
    engine = engine or get_engine(engine_name)
    voice_id = config.voice_id(spec.voice, engine.name)
    lex = config.lexicon()
    rate = spec.speech_rate or config.default_rate(spec.voice)
    offset = float(config.get("voices.timing_offset_ms", {}).get(engine.name, 0))

    audio_dir = project_dir / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)

    scenes, all_words = [], []
    cursor = 0.0
    for i, scene in enumerate(spec.scenes):
        spoken = apply_lexicon(scene.tts_override or scene.narration, lex)
        pro = prosody.for_scene(scene, rate)
        src, spoken_words = synthesize_cached(engine, spoken, voice_id, pro.rate, pro.pitch, pro.volume)
        dst = audio_dir / f"{scene.id}.mp3"
        shutil.copyfile(src, dst)
        audio_ms = ffmpeg.duration_ms(dst)

        spoken_words = [Word(w.text, min(w.start_ms + offset, audio_ms), min(w.end_ms + offset, audio_ms))
                        for w in spoken_words]
        if i == 0 and spoken_words:
            # The hook must start talking immediately: trim TTS lead-in silence before word one.
            cut = spoken_words[0].start_ms - HOOK_LEAD_MS
            if cut > 20:
                dst.unlink()
                dst = audio_dir / f"{scene.id}.wav"
                ffmpeg.run(["-ss", f"{cut / 1000:.3f}", "-i", str(src), "-c:a", "pcm_s16le", str(dst)])
                audio_ms = ffmpeg.duration_ms(dst)
                spoken_words = [Word(w.text, max(w.start_ms - cut, 0), max(w.end_ms - cut, 0)) for w in spoken_words]
        spoken_words = snap_to_speech(spoken_words, silences(dst))
        words = align(tokenize(scene.narration), spoken_words)
        is_last = i == len(spec.scenes) - 1
        duration = max(audio_ms + (TAIL_MS if is_last else GAP_MS), MIN_SCENE_MS)
        scenes.append({
            "id": scene.id, "start_ms": round(cursor, 1), "duration_ms": round(duration, 1),
            "audio_ms": round(audio_ms, 1), "audio": str(dst.relative_to(project_dir)),
            "delivery": pro.delivery, "rate": pro.rate, "pitch": pro.pitch,
        })
        for w in words:
            all_words.append({
                "text": " " + w.text,  # leading space: Remotion caption convention, harmless elsewhere
                "startMs": round(cursor + w.start_ms, 1),
                "endMs": round(cursor + w.end_ms, 1),
                "sceneId": scene.id,
            })
        cursor += duration

    timeline = {
        "total_ms": round(cursor, 1), "voice": spec.voice, "voice_id": voice_id,
        "engine": engine.name, "speech_rate": rate, "scenes": scenes,
        "words_per_second": round(spec.word_count / (sum(s["audio_ms"] for s in scenes) / 1000), 3),
    }
    _mix(project_dir, scenes, cursor)
    (project_dir / "timeline.json").write_text(json.dumps(timeline, indent=2, ensure_ascii=False))
    (project_dir / "words.json").write_text(json.dumps(all_words, indent=2, ensure_ascii=False))
    log.info("voice: %d scenes, %.1fs total, %.2f words/s", len(scenes), cursor / 1000, timeline["words_per_second"])
    return timeline


def _mix(project_dir: Path, scenes: list[dict], total_ms: float) -> None:
    args: list[str] = []
    filters, labels = [], []
    for i, s in enumerate(scenes):
        args += ["-i", str(project_dir / s["audio"])]
        d = int(round(s["start_ms"]))
        filters.append(f"[{i}:a]aresample=48000,aformat=channel_layouts=mono,adelay={d}:all=1[a{i}]")
        labels.append(f"[a{i}]")
    filters.append(
        f"{''.join(labels)}amix=inputs={len(scenes)}:normalize=0:dropout_transition=0,"
        f"apad,atrim=0:{total_ms / 1000:.3f}[out]"
    )
    ffmpeg.run([*args, "-filter_complex", ";".join(filters), "-map", "[out]",
                "-c:a", "pcm_s16le", str(project_dir / "voice.wav")])
