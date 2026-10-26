"""Stage 6 — Post: music + ducking, loudness, final encode, no-music variant, cover (stages/cover.py), post.txt.

Outputs: final.mp4 (voice + ducked music), final_nomusic.mp4 (voice only, for adding a TikTok
sound in-app; only when music was used), cover.png, post.txt.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from pathlib import Path

import numpy as np

from klip import config, ffmpeg
from klip.engines.render.base import RenderError
from klip.paths import ROOT
from klip.spec import Spec
from klip.stages import cover
from klip.stages.compose import ComposeError

log = logging.getLogger(__name__)

HASHTAG = re.compile(r"#\w+")


def hashtags_lower(text: str) -> str:
    """Every #hashtag in lowercase when post.lowercase_hashtags is on (#WargaNalar → #warganalar)."""
    if not config.get("post.lowercase_hashtags", True):
        return text
    return HASHTAG.sub(lambda m: m.group(0).lower(), text)


ENGINE_NAMES = {"edge": "Microsoft Edge TTS", "elevenlabs": "ElevenLabs", "gemini": "Google Gemini TTS"}

TARGET_LUFS = config.get("loudness.target_lufs", -14.0)
TARGET_TP = config.get("loudness.true_peak_db", -1.5)
TARGET_LRA = config.get("loudness.lra", 11.0)
MUSIC_EXT = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac"}


def measure_loudness(path: Path) -> dict:
    proc = ffmpeg.run(["-i", str(path), "-vn", "-af",
                       f"loudnorm=I={TARGET_LUFS}:TP={TARGET_TP}:LRA={TARGET_LRA}:print_format=json",
                       "-f", "null", "-"])
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", proc.stderr, re.S)
    if not m:
        raise ffmpeg.FFmpegError("could not parse loudnorm measurement")
    return json.loads(m.group(0))


def loudnorm_filter(wav: Path) -> str:
    """Two-pass loudnorm: measure, then apply linear normalization with the measured values."""
    m = measure_loudness(wav)
    return (f"loudnorm=I={TARGET_LUFS}:TP={TARGET_TP}:LRA={TARGET_LRA}"
            f":measured_I={m['input_i']}:measured_TP={m['input_tp']}:measured_LRA={m['input_lra']}"
            f":measured_thresh={m['input_thresh']}:offset={m['target_offset']}:linear=true")


def pick_track(spec: Spec) -> Path | None:
    """spec.music.track wins; else a deterministic pick (by slug) from assets/music/<mood>/."""
    if spec.music.track:
        p = Path(spec.music.track).expanduser()
        p = p if p.is_absolute() else ROOT / p
        if not p.exists():
            raise FileNotFoundError(f"music.track not found: {p}")
        return p
    if not spec.music.mood:
        return None
    folder = ROOT / config.get("music.dir", "assets/music") / spec.music.mood
    tracks = sorted(p for p in folder.glob("*") if p.suffix.lower() in MUSIC_EXT) if folder.is_dir() else []
    if not tracks:
        log.warning("no music in %s; rendering without music", folder.relative_to(ROOT))
        return None
    return tracks[int(hashlib.sha256(spec.slug.encode()).hexdigest(), 16) % len(tracks)]


SFX_EXT = (".wav", ".mp3", ".m4a", ".ogg")


def sfx_file(name: str) -> Path | None:
    folder = ROOT / config.get("sfx.dir", "assets/sfx")
    return next((folder / f"{name}{ext}" for ext in SFX_EXT if (folder / f"{name}{ext}").exists()), None)


def build_sfx(events: list[dict], total_s: float, out_wav: Path) -> bool:
    """Render all cues into one track the length of the video. False if there's nothing to play."""
    gains = config.get("sfx.gain_db", {}) or {}
    cues = [(e, f) for e in events if (f := sfx_file(e["sfx"])) and e["t"] < total_s]
    missing = sorted({e["sfx"] for e in events} - {e["sfx"] for e, _ in cues})
    if missing:
        log.warning("sfx files not found in %s: %s (run scripts/make_sfx.py)", config.get("sfx.dir"), missing)
    if not cues:
        return False
    args, chains = [], []
    for i, (e, f) in enumerate(cues):
        args += ["-i", str(f)]
        chains.append(f"[{i}:a]aresample=48000,aformat=channel_layouts=stereo,"
                      f"adelay={int(e['t'] * 1000)}:all=1,volume={gains.get(e['sfx'], -20) + e.get('db', 0):.1f}dB[s{i}]")
    graph = ";".join(chains) + ";" + "".join(f"[s{i}]" for i in range(len(cues))) + \
        f"amix=inputs={len(cues)}:normalize=0:dropout_transition=0,apad,atrim=0:{total_s:.3f}[out]"
    ffmpeg.run([*args, "-filter_complex", graph, "-map", "[out]", "-c:a", "pcm_s16le", str(out_wav)])
    return True


def motion_curve(video: Path, m: dict) -> np.ndarray:
    """Per frame (at m.fps): the share of pixels in the crop band that changed since the previous frame."""
    w, h = m["size"]
    proc = ffmpeg.run(["-i", str(video), "-vf", f"fps={m['fps']},scale={w}:{h},format=gray",
                       "-f", "rawvideo", "-"], binary=True)
    f = np.frombuffer(proc.stdout, np.uint8).reshape(-1, h, w).astype(np.int16)
    f = f[:, int(h * m["crop"][0]):int(h * m["crop"][1]), :]
    if len(f) < 2:
        return np.zeros(0)
    return np.concatenate([[0.0], (np.abs(np.diff(f, axis=0)) > m["pixel_diff"]).mean(axis=(1, 2))])


def motion_onsets(cov: np.ndarray, fps: float, on: float, min_s: float, smooth_s: float) -> list[tuple[float, float]]:
    """(time, peak coverage) where the smoothed curve rises over `on` and stays there for min_s."""
    k = max(1, round(smooth_s * fps))
    s = np.convolve(cov, np.ones(k) / k, mode="same") if len(cov) else cov
    out, i = [], 0
    while i < len(s):
        if s[i] >= on:
            j = i
            while j < len(s) and s[j] >= on:
                j += 1
            if (j - i) / fps >= min_s:
                out.append((i / fps, float(s[i:j].max())))
            i = j
        else:
            i += 1
    return out


def motion_cues(spec: Spec, timeline: dict, video: Path, events: list[dict]) -> list[dict]:
    """Effects on camera moves inside the scenes of sfx.motion.visual_types (see klip.yaml sfx.motion)."""
    m = config.get("sfx.motion") or {}
    if not m.get("sfx") or not spec.sfx:
        return []
    types = set(m["visual_types"])
    by_id = {s.id: s for s in spec.scenes}
    spans = [(sc["start_ms"] / 1000, (sc["start_ms"] + sc["duration_ms"]) / 1000) for sc in timeline["scenes"]
             if (s := by_id.get(sc["id"])) and s.visual.type in types]
    if not spans:
        return []
    cuts = [sc["start_ms"] / 1000 for sc in timeline["scenes"][1:]]
    taken = [e["t"] for e in events if e["sfx"] == m["sfx"]] + cuts
    out = []
    for t, peak in motion_onsets(motion_curve(video, m), float(m["fps"]), m["threshold"], m["min_s"], m["smooth_s"]):
        t = max(0.0, t - float(m["lead_s"]))
        if not any(a <= t < b for a, b in spans) or any(abs(t - x) < float(m["clear_s"]) for x in taken):
            continue
        boost = float(m["boost_db"]) * min(1.0, (peak - m["threshold"]) / max(1e-6, 1 - m["threshold"]) * 3)
        out.append({"t": round(t, 3), "moment": "camera_move", "sfx": m["sfx"], "db": round(boost, 1)})
        taken.append(t)
    return out


def mix_voice_sfx(voice_wav: Path, sfx_wav: Path, out_wav: Path) -> None:
    ffmpeg.run(["-i", str(voice_wav), "-i", str(sfx_wav), "-filter_complex",
                "[0:a]aresample=48000,aformat=channel_layouts=stereo[v];[v][1:a]amix=inputs=2:normalize=0:duration=first[out]",
                "-map", "[out]", "-c:a", "pcm_s16le", str(out_wav)])


def mix_music(voice_wav: Path, track: Path, total_s: float, out_wav: Path, music_cfg: dict,
              sfx_wav: Path | None = None) -> None:
    """Loop/trim the track, set it `under_voice_db` below the voice, duck it under speech
    (sidechain compression keyed by the voice), fade in/out, and mix (plus SFX if given)."""
    voice_i = float(measure_loudness(voice_wav)["input_i"])
    music_i = voice_i - float(music_cfg.get("under_voice_db", 16))
    fade = float(music_cfg.get("fade_out_s", 1.5))
    # Single-pass loudnorm buffers ~3 s and drops the tail of its input, so feed it 5 s extra
    # and trim to the video length afterwards (otherwise music cuts out before the fade).
    graph = (
        f"[1:a]aresample=48000,aformat=channel_layouts=stereo,atrim=0:{total_s + 5:.3f},asetpts=PTS-STARTPTS,"
        f"loudnorm=I={music_i:.1f}:TP=-3:LRA=11,aresample=48000,atrim=0:{total_s:.3f},asetpts=PTS-STARTPTS,"
        f"afade=t=in:d={music_cfg.get('fade_in_s', 0.8)},afade=t=out:st={max(total_s - fade, 0):.3f}:d={fade}[m];"
        f"[0:a]aresample=48000,aformat=channel_layouts=stereo,asplit=2[v][key];"
        f"[m][key]sidechaincompress=threshold={music_cfg.get('duck_threshold', 0.02)}"
        f":ratio={music_cfg.get('duck_ratio', 8)}:attack=20:release=450[md];"
        + (f"[v][md][2:a]amix=inputs=3:normalize=0:duration=first[out]" if sfx_wav else
           f"[v][md]amix=inputs=2:normalize=0:duration=first[out]")
    )
    ffmpeg.run(["-i", str(voice_wav), "-stream_loop", "-1", "-i", str(track),
                *(["-i", str(sfx_wav)] if sfx_wav else []),
                "-filter_complex", graph, "-map", "[out]", "-t", f"{total_s:.3f}",
                "-c:a", "pcm_s16le", str(out_wav)])


def _copyable(raw: Path) -> bool:
    """raw.mp4 is already TikTok-ready video (H.264, yuv420p, the render fps): copy it, don't re-encode."""
    v = next((s for s in ffmpeg.probe(raw)["streams"] if s.get("codec_type") == "video"), {})
    return (v.get("codec_name") == "h264" and v.get("pix_fmt") == "yuv420p"
            and v.get("r_frame_rate") == f"{config.get('render.fps', 30)}/1")


def encode(raw: Path, audio_wav: Path, out: Path) -> None:
    """raw video + the mixed audio (loudness-normalised) → out. The renderer already encoded the video at
    render.crf, so it's copied; render.reencode (or a raw that isn't H.264 yuv420p) encodes it again."""
    if not config.get("render.reencode") and _copyable(raw):
        video = ["-c:v", "copy"]
    else:
        video = ["-c:v", "libx264", "-profile:v", "high", "-pix_fmt", "yuv420p", "-crf", str(config.get("render.crf", 19)),
                 "-preset", str(config.get("render.preset")), "-r", str(config.get("render.fps", 30))]
    ffmpeg.run([
        "-i", str(raw), "-i", str(audio_wav), "-map", "0:v:0", "-map", "1:a:0",
        "-af", f"{loudnorm_filter(audio_wav)},aresample=48000,apad", *video,
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-shortest", "-movflags", "+faststart", str(out),
    ])


def remux_audio(video_src: Path, audio_wav: Path, out: Path) -> None:
    """Same video stream (copied, no re-encode), different audio."""
    ffmpeg.run([
        "-i", str(video_src), "-i", str(audio_wav), "-map", "0:v:0", "-map", "1:a:0",
        "-af", f"{loudnorm_filter(audio_wav)},aresample=48000,apad", "-c:v", "copy",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-shortest", "-movflags", "+faststart", str(out),
    ])


def frame_grab_cover(timeline: dict, final: Path, out: Path) -> None:
    """A frame from the hook scene, after its intro animation has landed."""
    first = timeline["scenes"][0]
    t = min(1.2, first["duration_ms"] / 1000 * 0.6)
    ffmpeg.run(["-ss", f"{t:.2f}", "-i", str(final), "-frames:v", "1", str(out)])


def make_cover(spec: Spec, project_dir: Path, timeline: dict, final: Path) -> str:
    """cover.png: the designed cover (stages/cover.py), else a frame grab. Returns which one."""
    out = project_dir / "cover.png"
    if config.style(spec.style)["cover"]["enabled"]:
        assets_path = project_dir / "assets.json"
        try:
            cover.run(spec, project_dir, json.loads(assets_path.read_text()) if assets_path.exists() else None)
            return "designed"
        except (RenderError, ComposeError, ffmpeg.FFmpegError) as e:
            log.warning("designed cover failed, using a frame grab instead: %s", e)
    frame_grab_cover(timeline, final, out)
    return "frame"


def loop_seam(spec: Spec, project_dir: Path, raw: Path, total_s: float) -> Path:
    """raw.mp4 whose last frames turn into its first frame (the style's loop settings), or raw itself when
    the loop is off or there's no room after the last word. Writes raw_loop.mp4."""
    lp = config.style(spec.style)["loop"]
    if not (spec.loop if spec.loop is not None else lp["enabled"]):
        return raw
    words_path = project_dir / "words.json"
    words = json.loads(words_path.read_text()) if words_path.exists() else []
    last = max((w["endMs"] for w in words), default=0) / 1000
    seam = min(float(lp["seam_s"]), total_s - last - float(lp["after_voice_s"]))
    if seam < 0.15:
        log.warning("loop: only %.2f s after the last word; no seam (raise timeline.tail_ms)", total_s - last)
        return raw
    fps = int(config.get("render.fps", 30))
    first, out = project_dir / "loop_first.png", project_dir / "raw_loop.mp4"
    ffmpeg.run(["-i", str(raw), "-frames:v", "1", str(first)])
    norm = f"fps={fps},format=yuv420p,settb=AVTB"
    ffmpeg.run([
        "-i", str(raw), "-loop", "1", "-t", f"{seam + 0.1:.3f}", "-i", str(first),
        "-filter_complex", f"[0:v]{norm}[a];[1:v]{norm}[b];"
                           # the blend completes 2 frames early, so the last frames are the first frame exactly
                           f"[a][b]xfade=transition={lp['transition']}:duration={seam - 2 / fps:.3f}:offset={total_s - seam:.3f},"
                           f"trim=duration={total_s:.3f}[v]",
        "-map", "[v]", "-an", "-c:v", "libx264", "-profile:v", "high", "-pix_fmt", "yuv420p",
        "-crf", str(config.get("render.crf", 19)), "-preset", str(config.get("render.preset")), "-r", str(fps),
        "-movflags", "+faststart", str(out),
    ])
    return out


def run(spec: Spec, project_dir: Path) -> dict:
    raw, voice_wav = project_dir / "raw.mp4", project_dir / "voice.wav"
    final, nomusic = project_dir / "final.mp4", project_dir / "final_nomusic.mp4"
    timeline = json.loads((project_dir / "timeline.json").read_text())
    total_s = timeline["total_ms"] / 1000
    music_cfg = config.get("music", {})
    raw = loop_seam(spec, project_dir, raw, total_s)

    # Sound effects (cues written by compose); "voice bed" = voice + SFX, no music.
    sfx_path = project_dir / "sfx.json"
    events = json.loads(sfx_path.read_text()) if spec.sfx and sfx_path.exists() else []
    moves = motion_cues(spec, timeline, raw, events)
    if moves:
        log.info("sfx: %d camera move(s): %s", len(moves), ", ".join(f"{e['t']:.1f}s" for e in moves))
    events = sorted(events + moves, key=lambda e: e["t"])
    sfx_wav = project_dir / "sfx.wav"
    has_sfx = build_sfx(events, total_s, sfx_wav)
    voice_bed = voice_wav
    if has_sfx:
        voice_bed = project_dir / "voice_sfx.wav"
        mix_voice_sfx(voice_wav, sfx_wav, voice_bed)

    track = pick_track(spec)
    if track:
        mix = project_dir / "mix.wav"
        mix_music(voice_wav, track, total_s, mix, music_cfg, sfx_wav if has_sfx else None)
        encode(raw, mix, final)
        remux_audio(final, voice_bed, nomusic)
    else:
        encode(raw, voice_bed, final)
        nomusic.unlink(missing_ok=True)

    cover_kind = make_cover(spec, project_dir, timeline, final)

    caption = hashtags_lower(spec.post.caption.strip())
    in_caption = {t.lower() for t in re.findall(r"#\w+", caption)}
    tags = hashtags_lower(" ".join(t for t in spec.post.hashtags if t.lower() not in in_caption).strip())
    lines = [caption, ""] + ([tags, ""] if tags else []) + [
             f"Suara: AI ({ENGINE_NAMES.get(timeline.get('engine', 'edge'), timeline.get('engine'))}, "
             f"{', '.join(dict.fromkeys((timeline.get('voices') or {}).values())) or timeline['voice_id']})."]
    if track:
        lines.append(f"Musik: {track.stem}")
    credits_path = project_dir / "credits.json"
    credits = json.loads(credits_path.read_text()) if credits_path.exists() else []
    if credits:
        lines += ["", "Kredit visual:"]
        for c in credits:
            src = {"pixabay": "Pixabay", "pexels": "Pexels", "openverse": "via Openverse"}.get(c["provider"], c["provider"])
            title = f"“{c['title']}” " if c.get("title") else ""
            lines.append(f"- {title}{c['creator']} / {src} ({c['license']}) {c['page_url']}".rstrip())
    if spec.facts:
        lines += ["", "Sumber:"] + [f"- {f.claim}: {f.source}" for f in spec.facts]
    (project_dir / "post.txt").write_text("\n".join(lines).strip() + "\n", encoding="utf-8")

    info = ffmpeg.probe(final)
    v = next(s for s in info["streams"] if s["codec_type"] == "video")
    return {"final": str(final), "nomusic": str(nomusic) if track else None, "sfx_cues": len(events) if has_sfx else 0,
            "cover": cover_kind,
            "music": str(track.relative_to(ROOT) if track.is_relative_to(ROOT) else track) if track else None,
            "width": v["width"], "height": v["height"], "fps": v["r_frame_rate"],
            "duration_s": round(float(info["format"]["duration"]), 2)}
