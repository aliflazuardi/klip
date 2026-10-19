"""Generate a placeholder ambient pad (synthesized, no copyright) for testing music ducking.

Usage: uv run python scripts/make_test_music.py [out.mp3]
Default output: assets/music/calm/klip-test-pad.mp3 (gitignored). Replace it with real
royalty-free tracks for actual videos.
"""

import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
out = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "assets/music/calm/klip-test-pad.mp3"
out.parent.mkdir(parents=True, exist_ok=True)

# Cmaj7 - Am7 - Fmaj7 - G6, 4 s each, gentle tremolo
CHORDS = [(130.81, 164.81, 196.0, 246.94), (110.0, 130.81, 164.81, 196.0),
          (87.31, 130.81, 164.81, 220.0), (98.0, 123.47, 146.83, 164.81)]
with tempfile.TemporaryDirectory() as tmp:
    parts = []
    for i, freqs in enumerate(CHORDS):
        tone = "+".join(f"sin(2*PI*{f}*t)+0.3*sin(2*PI*{2 * f}*t)" for f in freqs)
        expr = f"0.06*({tone})*(0.75+0.25*sin(2*PI*0.25*t))"
        p = Path(tmp) / f"c{i}.wav"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                        f"aevalsrc='{expr}':s=48000:d=4", "-af",
                        "afade=t=in:d=0.4,afade=t=out:st=3.5:d=0.5,aecho=0.8:0.7:120:0.35",
                        str(p)], check=True)
        parts.append(p)
    lst = Path(tmp) / "list.txt"
    lst.write_text("".join(f"file '{p}'\n" for p in parts))
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-stream_loop", "3", "-f", "concat", "-safe", "0",
                    "-i", str(lst), "-ac", "2", "-c:a", "libmp3lame", "-b:a", "160k", str(out)], check=True)
print(f"wrote {out}")
