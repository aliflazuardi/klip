"""Stage 2 — Voice: TTS, word timings, timeline, voice.wav.

Two ways to record (klip.yaml voices.take):
  scene  one TTS call per scene (per-scene delivery presets; intonation restarts at each scene)
  whole  the whole script in one call, then cut into scenes at the pauses between them: one
         continuous read, as a narrator would. Engines without word timings (Gemini) are aligned
         with klip/align.py.

Writes into the project dir:
  audio/<scene>.mp3|wav  per-scene audio
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
from klip.spec import Scene, Spec

log = logging.getLogger(__name__)

GAP_MS = config.get("timeline.gap_ms", 150)            # silence between scenes
TAIL_MS = config.get("timeline.tail_ms", 1000)         # hold after the last scene
MIN_SCENE_MS = config.get("timeline.min_scene_ms", 1500)
HOOK_LEAD_MS = config.get("timeline.hook_lead_ms", 60)  # first word starts this soon after frame 0
TURN_GAP_MS = config.get("timeline.turn_gap_ms", 250)   # whole takes: pause when the narrator changes


ENGINES = ("edge", "elevenlabs", "gemini")


def get_engine(name: str) -> TTSEngine:
    if name == "edge":
        return EdgeTTS()
    if name == "elevenlabs":
        from klip.engines.tts.elevenlabs import ElevenLabsTTS
        return ElevenLabsTTS()
    if name == "gemini":
        from klip.engines.tts.gemini import GeminiTTS
        return GeminiTTS()
    raise ValueError(f"unknown TTS engine {name!r} (one of {', '.join(ENGINES)})")


def _cache_key(engine: str, voice_id: str, rate: str, text: str,
               pitch: str = "+0Hz", volume: str = "+0%", tag: str | None = None) -> str:
    parts = [1, engine, voice_id, rate, text]
    if (pitch, volume) != ("+0Hz", "+0%"):   # neutral keeps its old key, so existing caches stay valid
        parts += [pitch, volume]
    if tag:                                  # engine settings (model, style prompt...)
        parts.append(tag)
    payload = json.dumps(parts, ensure_ascii=False)
    return hashlib.sha256(payload.encode()).hexdigest()[:20]


def synthesize_cached(engine: TTSEngine, text: str, voice_id: str, rate: str,
                      pitch: str = "+0Hz", volume: str = "+0%") -> tuple[Path, list[Word]]:
    cache = CACHE_DIR / "tts"
    cache.mkdir(parents=True, exist_ok=True)
    key = _cache_key(engine.name, voice_id, rate, text, pitch, volume, getattr(engine, "cache_tag", None))
    audio, meta = cache / f"{key}{getattr(engine, 'ext', '.mp3')}", cache / f"{key}.json"
    if audio.exists() and meta.exists():
        return audio, [Word.from_dict(d) for d in json.loads(meta.read_text())]
    words = engine.synthesize(text, voice_id, rate, audio, pitch=pitch, volume=volume)
    if not words:                            # no timings from the engine: align the audio
        from klip.align import align_audio
        words = align_audio(audio, text)
    meta.write_text(json.dumps([w.to_dict() for w in words], ensure_ascii=False))
    return audio, words


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


def snap_to_speech(words: list[Word], pauses: list[tuple[float, float]], late_ms: float | None = None) -> list[Word]:
    """Put the first word after each pause where the sound resumes. edge-tts times it from the start
    of the pause (its caption fired ~0.3 s early); aligned timings (Whisper) often start it a little
    after the sound resumes (~0.1-0.2 s late). Words starting inside a pause, or up to late_ms
    (voices.snap_late_ms) after it ends with no other word in between, move to the pause's end."""
    late = float(config.get("voices.snap_late_ms", 0) if late_ms is None else late_ms)
    out: list[Word] = []
    for w in words:
        start = w.start_ms
        prev = out[-1].start_ms if out else float("-inf")
        for a, b in pauses:
            if a <= start < b - 20 or (b <= start <= b + late and prev < a):
                start = b
                break
        out.append(Word(w.text, start, max(w.end_ms, start)))
    return out


def _scene_takes(scenes: list[Scene], engine: TTSEngine, voice_id: str, rate: str, lex: dict, offset: float,
                 audio_dir: Path, first: bool = True) -> list[dict]:
    """One TTS call per scene: [{scene, audio (Path), words (spoken, ms in the clip), pro}]."""
    takes = []
    for i, scene in enumerate(scenes):
        spoken = apply_lexicon(scene.tts_override or scene.narration, lex)
        pro = prosody.for_scene(scene, rate)
        src, spoken_words = synthesize_cached(engine, spoken, voice_id, pro.rate, pro.pitch, pro.volume)
        dst = audio_dir / f"{scene.id}{src.suffix}"
        shutil.copyfile(src, dst)
        audio_ms = ffmpeg.duration_ms(dst)
        spoken_words = [Word(w.text, min(w.start_ms + offset, audio_ms), min(w.end_ms + offset, audio_ms))
                        for w in spoken_words]
        if i == 0 and first and spoken_words:
            # The hook must start talking immediately: trim TTS lead-in silence before word one.
            cut = spoken_words[0].start_ms - HOOK_LEAD_MS
            if cut > 20:
                dst.unlink()
                dst = audio_dir / f"{scene.id}.wav"
                ffmpeg.run(["-ss", f"{cut / 1000:.3f}", "-i", str(src), "-c:a", "pcm_s16le", str(dst)])
                spoken_words = [Word(w.text, max(w.start_ms - cut, 0), max(w.end_ms - cut, 0)) for w in spoken_words]
        takes.append({"scene": scene, "audio": dst, "words": spoken_words, "pro": pro})
    return takes


def scene_cuts(spans: list[tuple[float, float]], pauses: list[tuple[float, float]], total_ms: float,
               lead_ms: float) -> list[float]:
    """Cut points (ms) splitting one take into scenes: before scene 0 (lead_ms before its first word),
    then in the middle of the pause between each scene's last word and the next one's first, then
    the end. spans = (first word start, last word end) per scene."""
    cuts = [max(spans[0][0] - lead_ms, 0.0)]
    for (_, end), (start, _) in zip(spans, spans[1:]):
        gap = [(max(a, end), min(b, start)) for a, b in pauses if a < start and b > end]
        a, b = max(gap, key=lambda g: g[1] - g[0]) if gap else (end, max(start, end))
        cuts.append(round((a + b) / 2, 1))
    cuts.append(total_ms)
    return cuts


def _whole_take(scenes: list[Scene], engine: TTSEngine, voice_id: str, rate: str, lex: dict, offset: float,
                audio_dir: Path, first: bool = True) -> list[dict]:
    """A run of scenes (the whole script, or one narrator's turn) in one TTS call, cut into scene
    clips at the pauses between scenes."""
    texts = [apply_lexicon(s.tts_override or s.narration, lex).strip() for s in scenes]
    src, words = synthesize_cached(engine, " ".join(texts), voice_id, rate)
    total = ffmpeg.duration_ms(src)
    words = [Word(w.text, min(w.start_ms + offset, total), min(w.end_ms + offset, total)) for w in words]
    owner = [i for i, t in enumerate(texts) for _ in tokenize(t)]
    timed = align([tok for t in texts for tok in tokenize(t)], words)
    spans = []
    for i in range(len(texts)):
        mine = [w for w, o in zip(timed, owner) if o == i]
        if not mine:
            raise ValueError(f"{scenes[i].id}: no spoken words found in the take")
        spans.append((mine[0].start_ms, mine[-1].end_ms))
    pauses = silences(src)
    if pauses and pauses[0][0] <= 50 and pauses[0][1] < spans[0][1]:   # lead-in silence: speech starts after it
        spans[0] = (max(spans[0][0], pauses[0][1]), spans[0][1])
    cuts = scene_cuts(spans, pauses, total, HOOK_LEAD_MS)
    takes = []
    for i, scene in enumerate(scenes):
        a, b = cuts[i], cuts[i + 1]
        dst = audio_dir / f"{scene.id}.wav"
        ffmpeg.run(["-ss", f"{a / 1000:.3f}", "-to", f"{b / 1000:.3f}", "-i", str(src), "-c:a", "pcm_s16le", str(dst)])
        mine = [Word(w.text, max(w.start_ms - a, 0), max(w.end_ms - a, 0)) for w, o in zip(timed, owner) if o == i]
        takes.append({"scene": scene, "audio": dst, "words": mine, "pro": prosody.for_scene(scene, rate)})
    return takes


def turns(spec: Spec) -> list[tuple[str, list[Scene]]]:
    """Consecutive scenes with the same narrator: [(voice, scenes)]. One turn = the whole video
    unless scenes set their own voice (or a mascot speaker with one)."""
    from klip.mascot import scene_voice, video_style
    style = video_style(spec)
    out: list[tuple[str, list[Scene]]] = []
    for scene in spec.scenes:
        v = scene_voice(spec, scene, style)
        if out and out[-1][0] == v:
            out[-1][1].append(scene)
        else:
            out.append((v, [scene]))
    return out


def run(spec: Spec, project_dir: Path, engine: TTSEngine | None = None) -> dict:
    engine_name = config.get("voices.engine", "edge")
    engine = engine or get_engine(engine_name)
    lex = config.lexicon()
    offset = float(config.get("voices.timing_offset_ms", {}).get(engine.name, 0))
    whole = config.get("voices.take") == "whole"

    audio_dir = project_dir / "audio"
    if audio_dir.exists():
        shutil.rmtree(audio_dir)
    audio_dir.mkdir(parents=True)
    # each narrator's turn is recorded on its own (a whole take per turn keeps the intonation
    # flowing within it); the voice and its default rate follow the turn
    takes, voices = [], {}
    for k, (v, scenes) in enumerate(turns(spec)):
        voices[v] = config.voice_id(v, engine.name)
        rate = spec.speech_rate or config.default_rate(v)
        got = (_whole_take if whole else _scene_takes)(scenes, engine, voices[v], rate, lex, offset, audio_dir, k == 0)
        takes += [{**tk, "voice": v, "turn_end": j == len(got) - 1} for j, tk in enumerate(got)]
    rate = spec.speech_rate or config.default_rate(spec.voice)

    scenes, all_words = [], []
    cursor = 0.0
    for i, tk in enumerate(takes):
        scene, dst, pro = tk["scene"], tk["audio"], tk["pro"]
        audio_ms = ffmpeg.duration_ms(dst)
        spoken_words = snap_to_speech(tk["words"], silences(dst))
        words = align(tokenize(scene.narration), spoken_words)
        is_last = i == len(takes) - 1
        # a whole take already has its natural pauses between scenes; a change of narrator gets a gap
        gap = TAIL_MS if is_last else (TURN_GAP_MS if tk["turn_end"] else 0) if whole else GAP_MS
        duration = max(audio_ms + gap, MIN_SCENE_MS)
        scenes.append({
            "id": scene.id, "start_ms": round(cursor, 1), "duration_ms": round(duration, 1),
            "audio_ms": round(audio_ms, 1), "audio": str(dst.relative_to(project_dir)),
            "voice": tk["voice"], "delivery": None if whole else pro.delivery, "rate": pro.rate if not whole else
            (spec.speech_rate or config.default_rate(tk["voice"])),
            "pitch": None if whole else pro.pitch,
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
        "total_ms": round(cursor, 1), "voice": spec.voice, "voice_id": voices.get(spec.voice) or next(iter(voices.values())),
        "voices": voices,
        "engine": engine.name, "take": "whole" if whole else "scene", "speech_rate": rate, "scenes": scenes,
        "words_per_second": round(spec.word_count / (sum(s["audio_ms"] for s in scenes) / 1000), 3),
    }
    _mix(project_dir, scenes, cursor)
    (project_dir / "timeline.json").write_text(json.dumps(timeline, indent=2, ensure_ascii=False))
    (project_dir / "words.json").write_text(json.dumps(all_words, indent=2, ensure_ascii=False))
    log.info("voice: %s (%s take), %d scenes, %.1fs total, %.2f words/s", engine.name, timeline["take"],
             len(scenes), cursor / 1000, timeline["words_per_second"])
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
