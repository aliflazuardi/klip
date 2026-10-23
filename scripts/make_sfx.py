"""Synthesize Klip's default sound effects with FFmpeg (no samples, no copyright).

Usage: uv run python scripts/make_sfx.py [out_dir]    (default: assets/sfx/)
Writes whoosh/swish/pop/ding/riser/hit .wav, peak-normalized to -1 dBFS. To use your own effects,
drop files with the same names (any of .wav/.mp3/.m4a/.ogg) into assets/sfx/; they win.
"""

import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "assets" / "sfx"

# name: (ffmpeg lavfi source(s) + filter graph producing [out])
SFX = {
    # filtered pink-noise swell: the classic transition swoosh
    "whoosh": ("anoisesrc=d=0.5:c=pink:a=0.8:seed=7",
               "highpass=f=500,lowpass=f=6000,afade=t=in:d=0.22:curve=exp,afade=t=out:st=0.22:d=0.28:curve=log"),
    # soft air push with a low body: the scene cut / camera move (no hiss: everything over ~1.4 kHz is cut)
    "swish": ("aevalsrc='0.55*(random(0)*2-1)+0.45*sin(2*PI*(150*t-110*t*t))':s=48000:d=0.45",
              "highpass=f=70,lowpass=f=1400,lowpass=f=1400,afade=t=in:d=0.17:curve=exp,afade=t=out:st=0.17:d=0.28:curve=log"),
    # short sine blip with a falling pitch: badges, icons
    "pop": ("aevalsrc='sin(2*PI*(520*t-1800*t*t))*exp(-38*t)':s=48000:d=0.14", "afade=t=out:st=0.1:d=0.04"),
    # bell-like partials with exponential decay: a stat lands
    "ding": ("aevalsrc='(sin(2*PI*1320*t)*exp(-5*t)+0.5*sin(2*PI*2640*t)*exp(-7*t)"
             "+0.25*sin(2*PI*3960*t)*exp(-9*t))':s=48000:d=1.0", "afade=t=out:st=0.85:d=0.15"),
    # rising noise + upward sine sweep: tension before the myth→fact reveal
    "riser": ("anoisesrc=d=1.0:c=pink:a=0.5:seed=3",
              "highpass=f=900,afade=t=in:d=1.0:curve=exp,afade=t=out:st=0.95:d=0.05"),
    # low thump + click: the reveal / hook impact
    "hit": ("aevalsrc='sin(2*PI*(95*t-40*t*t))*exp(-8*t)+0.3*sin(2*PI*1800*t)*exp(-60*t)':s=48000:d=0.6",
            "afade=t=out:st=0.5:d=0.1"),
}


def run(args: list[str]) -> str:
    return subprocess.run(["ffmpeg", "-hide_banner", "-y", *args], check=True, capture_output=True, text=True).stderr


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        for name, (src, filt) in SFX.items():
            raw = Path(tmp) / f"{name}.wav"
            run(["-f", "lavfi", "-i", src, "-af", f"{filt},aformat=sample_rates=48000:channel_layouts=mono", str(raw)])
            peak = float(re.search(r"max_volume: (-?[\d.]+) dB", run(["-i", str(raw), "-af", "volumedetect", "-f", "null", "-"])).group(1))
            out = OUT / f"{name}.wav"
            run(["-i", str(raw), "-af", f"volume={-1 - peak:.2f}dB", "-c:a", "pcm_s16le", str(out)])
            print(f"wrote {out.relative_to(ROOT) if out.is_relative_to(ROOT) else out}")


if __name__ == "__main__":
    main()
