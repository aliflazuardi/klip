"""Spot-check caption sync: compare speech onsets after pauses with caption word starts.

Usage: uv run python scripts/check_sync.py projects/<slug>
Positive diff = speech starts after the caption highlights the word. -35 dB so breaths
before a word are not counted as speech.
"""

import json
import sys
from pathlib import Path

project = Path(sys.argv[1])
words = json.loads((project / "words.json").read_text())
starts = [w["startMs"] for w in words]
last_end = words[-1]["endMs"]
# voice.wav, not final.mp4: the final mix has music and SFX, whose onsets aren't speech.
# Same pause detection as the voice stage (breaths before a word are not speech onsets).
from klip.stages.voice import silences  # noqa: E402
onsets = [b for _, b in silences(project / "voice.wav")]
diffs = []
for o in onsets:
    if o > last_end:
        continue  # trailing silence
    nearest = min(starts, key=lambda s: abs(s - o))
    diffs.append(o - nearest)
    print(f"onset {o:8.0f} ms   word start {nearest:8.0f} ms   diff {o - nearest:+5.0f} ms")
worst = max(diffs, key=abs)
mean = sum(diffs) / len(diffs)
print(f"\n{len(diffs)} onsets · mean {mean:+.0f} ms · worst {worst:+.0f} ms · "
      f"{'PASS' if abs(worst) <= 100 else 'CHECK'} (±100 ms)")
