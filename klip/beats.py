"""Beat times of the music track, for code scenes (`k.beats`, `k.pulse`).

Pure Python (no numpy): ffmpeg decodes the track to mono at a low rate, split into a low band
(kick, bass) and a high band (snare, hats). Onset strength is the rise in log energy per hop, the
tempo is the autocorrelation peak of that envelope (with a soft prior around a typical pop tempo
so it doesn't pick half or double time), and the beats are a grid at that tempo, phase-aligned to
the onsets and snapped to the nearest onset within `snap_s` so they follow small drifts. Downbeats
are the one-in-four phase with the most low-band energy. Results are cached by the track's
content (CACHE_DIR/beats/).

The track starts with the video and loops (stages/post.py mix_music), so beats tile by its length.
"""

from __future__ import annotations

import array
import hashlib
import json
import math
import tempfile
from pathlib import Path

from klip import config, ffmpeg
from klip.paths import CACHE_DIR


def cfg(key: str):
    return config.get(f"code.beats.{key}")


def _decode(track: Path, sr: int, split_hz: float, max_s: float) -> tuple[array.array, array.array]:
    """Low and high band samples (int16) of the track's first max_s seconds."""
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "bands.raw"
        ffmpeg.run(["-t", f"{max_s:.1f}", "-i", str(track), "-filter_complex",
                    f"[0:a]aformat=channel_layouts=mono,aresample={sr},asplit[a][b];"
                    f"[a]lowpass=f={split_hz},aformat=channel_layouts=mono[l];"
                    f"[b]highpass=f={split_hz},aformat=channel_layouts=mono[h];[l][h]amerge=inputs=2[out]",
                    "-map", "[out]", "-f", "s16le", "-acodec", "pcm_s16le", str(out)])
        both = array.array("h", out.read_bytes())
    return both[0::2], both[1::2]


def _onsets(band: array.array, hop: int) -> list[float]:
    """Rise in log energy per hop, with the local average (≈0.5 s) taken off and clipped at 0."""
    n = len(band) // hop
    loge = []
    for i in range(n):
        seg = band[i * hop:(i + 1) * hop]
        loge.append(math.log(1e-3 + sum(x * x for x in seg) / hop))
    rise = [0.0] + [max(0.0, loge[i] - loge[i - 1]) for i in range(1, n)]
    w = 16
    out, acc = [], 0.0
    for i, v in enumerate(rise):          # running mean over the last w hops
        acc += v - (rise[i - w] if i >= w else 0.0)
        out.append(max(0.0, v - acc / min(i + 1, w)))
    return out


def analyze(track: Path) -> dict:
    """{bpm, period (s), duration (s), confidence, beats: [{t, down, s}]} for one track (cached). No beats
    (bpm None) when the track is too short or has almost no attacks (a pad that only swells)."""
    sr, hop = int(cfg("sample_rate")), int(cfg("hop"))
    params = [sr, hop, cfg("split_hz"), cfg("bpm_min"), cfg("bpm_max"), cfg("bpm_prior"), cfg("snap_s"), cfg("max_track_s"),
              cfg("onset_floor"), cfg("attack_rise"), cfg("min_attacks")]
    key = hashlib.sha256(track.read_bytes() + json.dumps(params).encode()).hexdigest()[:20]
    cached = CACHE_DIR / "beats" / f"{key}.json"
    if cached.exists():
        return json.loads(cached.read_text())

    low, high = _decode(track, sr, float(cfg("split_hz")), float(cfg("max_track_s")))
    fps = sr / hop
    ol, oh = _onsets(low, hop), _onsets(high, hop)
    env = [a + 0.5 * b for a, b in zip(ol, oh)]
    n = len(env)
    duration = len(low) / sr
    result = {"bpm": None, "period": None, "duration": round(duration, 3), "beats": []}
    lag_min, lag_max = int(fps * 60 / float(cfg("bpm_max"))), int(math.ceil(fps * 60 / float(cfg("bpm_min"))))
    attacks = sum(1 for a, b in zip(ol, oh) if max(a, b) > float(cfg("attack_rise"))) / max(n, 1)
    if n < lag_max * 4 or attacks < float(cfg("min_attacks")):      # too short, or swells with no hits
        _save(cached, result)
        return result

    # tempo: autocorrelation peak, weighted by a log-normal prior around bpm_prior (one octave wide)
    prior_lag = fps * 60 / float(cfg("bpm_prior"))
    ac = {lag: sum(env[i] * env[i + lag] for i in range(n - lag)) / (n - lag) for lag in range(lag_min, lag_max + 1)}
    score = {lag: v * math.exp(-0.5 * math.log2(lag / prior_lag) ** 2) for lag, v in ac.items()}
    best = max(score, key=score.get)
    # confidence: how many standard deviations the tempo's autocorrelation stands above the other lags
    # (music with a clear beat ≈2.5-3.5, a click track ≈5). A rough guide, not a verdict: ambient
    # tracks can score like music, so a low score is a warning and spec music.beats turns beats off.
    mean = sum(ac.values()) / len(ac)
    sd = math.sqrt(sum((v - mean) ** 2 for v in ac.values()) / len(ac))
    confidence = (ac[best] - mean) / sd if sd > 0 else 0.0
    a, b, c = score.get(best - 1, score[best]), score[best], score.get(best + 1, score[best])
    den = a - 2 * b + c
    period = best + (0.5 * (a - c) / den if den < 0 else 0.0)        # parabolic refinement, in hops

    # phase: the grid offset that lands on the most onset energy
    def grid_score(ph: float) -> float:
        return sum(env[int(round(ph + k * period))] for k in range(int((n - 1 - ph) / period) + 1))
    phase = max((p for p in range(int(period) + 1)), key=grid_score)

    # beats: walk the grid, snapping each to the strongest onset within snap_s of where it's expected
    snap = max(1, int(round(float(cfg("snap_s")) * fps)))
    scale = sorted(env)[int(n * 0.95)] or max(env)      # a loud hit, not the jump in from silence
    beats, t = [], float(phase)
    while t < n - 1:
        i0 = int(round(t))
        lo, hi = max(0, i0 - snap), min(n - 1, i0 + snap)
        j = max(range(lo, hi + 1), key=lambda i: env[i])
        beats.append(j if env[j] > float(cfg("onset_floor")) * scale else i0)
        t = beats[-1] + period

    # downbeats: the one-in-four phase with the most low-band onset
    bar = max(range(4), key=lambda p: sum(ol[beats[i]] for i in range(p, len(beats), 4)))
    result = {"bpm": round(60 * fps / period, 2), "period": round(period / fps, 4), "duration": round(duration, 3),
              "confidence": round(confidence, 2),
              "beats": [{"t": round(i / fps, 3), "down": (k - bar) % 4 == 0, "s": round(min(1.0, env[i] / scale), 3)}
                        for k, i in enumerate(beats)]}
    _save(cached, result)
    return result


def _save(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))


def for_video(track: Path, total_s: float) -> dict:
    """The track's beats over the whole video (the track loops from 0), numbered: {bpm, period,
    confidence, beats: [{t, n, down, s}]}."""
    a = analyze(track)
    out, loop = [], 0.0
    while a["beats"] and loop < total_s and a["duration"] > 0:
        for b in a["beats"]:
            if (t := loop + b["t"]) < total_s:
                out.append({**b, "t": round(t, 3), "n": len(out)})
        loop += a["duration"]
    return {"bpm": a["bpm"], "period": a["period"], "confidence": a.get("confidence"), "beats": out}


def in_scene(video: dict, start: float, dur: float) -> list[dict]:
    """Beats inside a scene, scene-relative."""
    return [{**b, "t": round(b["t"] - start, 3)} for b in video["beats"] if start <= b["t"] < start + dur]
