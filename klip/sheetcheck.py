"""Preview review: Claude looks at `klip preview`'s contact sheets and lists what's wrong in each scene.

The checks a person makes by eye on a sheet: text over a busy picture, overlaps with the mascots or
captions, things outside the safe area, empty frames, a still that doesn't show what the voice says,
a scene that breaks the look bible, a red error box. One `claude -p` call reviews every sheet of the
video (Read tool only, in a temp dir holding just the sheets), on the user's Claude plan. Results go
to projects/<slug>/preview/review.json; `klip render`'s qa.json carries them (informational: taste
doesn't fail a render) and marks them stale when a scene file changed since.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from klip import config
from klip.engines.llm.base import LLMError
from klip.engines.llm.claude_cli import parse_output
from klip.spec import Spec

KINDS = ("unreadable_text", "overlap", "outside_safe", "empty_frame", "off_script", "off_style", "broken")

SYSTEM = """You review preview stills of a vertical (1080x1920) short video for TikTok/Reels/Shorts,
before it is rendered. Each scene was hand-coded; its contact sheet shows stills at its start, at the
words its animation is timed to (the label under each still: time and the cue word), the middle and
the end. Word-synced captions sit near the bottom (white bold text); a brand watermark and a series
pill may sit at the very top; the brand's mascots may stand just above the captions. Read every sheet
image file, then judge each scene as a demanding motion designer would:
  unreadable_text  headline, labels or captions hard to read (busy picture behind, low contrast, too small)
  overlap          elements colliding: text over text, props covering mascots or captions, cut-off type
  outside_safe     key text or faces in the top ~230 px or bottom ~470 px, or off the frame edge
  empty_frame      a still with little or nothing to look at, or the main picture tiny in a big empty frame
  off_script       the still doesn't show what the voice is saying at that moment
  off_style        breaks the video's look bible (colours, type, drawing style) or looks unfinished
  broken           a red error box, missing images, garbled shapes
Captions pop in page by page, so a still may catch one mid-pop (smaller or faded) or between pages:
that is not an issue. Only report real problems a viewer would notice; small nits are not issues. Each issue names the
still (1-based, left to right, top to bottom on that sheet), the kind, what is wrong and the fix in
one short sentence each. Score each scene 1-5 (5 = ready to post)."""

SCHEMA = {
    "type": "object",
    "properties": {"scenes": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "id": {"type": "string"},
            "score": {"type": "integer", "minimum": 1, "maximum": 5},
            "issues": {"type": "array", "items": {
                "type": "object",
                "properties": {"still": {"type": "integer", "minimum": 1},
                               "kind": {"type": "string", "enum": list(KINDS)},
                               "problem": {"type": "string"}, "fix": {"type": "string"}},
                "required": ["still", "kind", "problem", "fix"]}}},
        "required": ["id", "score", "issues"]}}},
    "required": ["scenes"],
}


def cfg(key: str):
    return config.get(f"code.review.{key}")


def available() -> bool:
    return bool(cfg("enabled")) and bool(shutil.which("claude"))


def spoken_around(words: list[dict], t: float, span: float = 0.9) -> str:
    """The narration words said within `span` s of t (what the still should be showing)."""
    return " ".join(w["text"].strip() for w in words if abs(w["startMs"] / 1000 - t) <= span)


def prompt(spec: Spec, rows: list[dict], words: list[dict], look: dict | None) -> str:
    by_id = {s.id: s for s in spec.scenes}
    lines = []
    if look:
        lines.append(f"Look bible: palette {look.get('palette')}, texture {look.get('texture')}, fonts "
                     f"{look.get('families')}.\nArt direction: {look.get('notes') or '-'}\n")
    for r in rows:
        s = by_id[r["scene"]]
        sw = [w for w in words if w["sceneId"] == s.id]
        stills = "\n".join(f"    {i}. {f['t']:.2f}s ({f['label']}): voice says “{spoken_around(sw, f['t'])}”"
                           for i, f in enumerate(r["frames"], 1))
        lines.append(f"- scene {s.id}: sheet ./{s.id}.jpg ({len(r['frames'])} stills)\n  narration: {s.narration}\n"
                     f"  on-screen text: {s.on_screen_text or '-'}\n  stills:\n{stills}")
    return "Review these preview sheets. Read every sheet file before answering.\n\n" + "\n".join(lines)


def _call(user: str, sheets: dict[str, Path]) -> dict:
    """One claude -p call over the sheets (copied into an empty temp dir); returns the parsed JSON."""
    with tempfile.TemporaryDirectory() as cwd:
        for sid, path in sheets.items():
            shutil.copyfile(path, Path(cwd) / f"{sid}.jpg")
        cmd = [shutil.which("claude") or "claude", "-p", "--output-format", "json", "--no-session-persistence",
               "--system-prompt", SYSTEM, "--json-schema", json.dumps(SCHEMA),
               "--tools", "Read", "--allowedTools", "Read"]
        if model := (cfg("model") or config.get("llm.claude.model")):
            cmd += ["--model", str(model)]
        try:
            proc = subprocess.run(cmd, input=user, capture_output=True, text=True, cwd=cwd, timeout=cfg("timeout_s"))
        except subprocess.TimeoutExpired:
            raise LLMError("preview review timed out") from None
    answer = parse_output(proc.stdout, proc.stderr, proc.returncode)
    return answer if isinstance(answer, dict) else json.loads(answer)


def file_hash(spec: Spec, sid: str) -> str | None:
    """The scene's code file (+ includes) hash, so a review can tell it's out of date; None for other scenes."""
    from klip.paths import ROOT
    s = next(x for x in spec.scenes if x.id == sid)
    if s.visual.type != "code":
        return None
    h = hashlib.sha256()
    for f in [s.visual.code.file, *s.visual.code.include]:
        p = ROOT / f
        h.update(p.read_bytes() if p.is_file() else b"")
    return h.hexdigest()[:16]


def parse(data: dict, rows: list[dict]) -> list[dict]:
    """The model's answer → [{scene, score, flagged, issues: [{still, t, kind, problem, fix}]}] for the
    reviewed scenes, in order (a scene it skipped gets score None)."""
    frames = {r["scene"]: r["frames"] for r in rows}
    got = {str(x.get("id", "")).removeprefix("scene ").strip(): x for x in data.get("scenes", [])}
    out = []
    for sid in frames:
        x = got.get(sid) or {}
        issues = []
        for i in x.get("issues") or []:
            k = int(i.get("still", 1))
            f = frames[sid][min(max(k, 1), len(frames[sid])) - 1]
            issues.append({"still": k, "t": f["t"], "kind": i.get("kind") if i.get("kind") in KINDS else "off_style",
                           "problem": str(i.get("problem", "")).strip(), "fix": str(i.get("fix", "")).strip()})
        score = x.get("score")
        score = max(1, min(5, int(score))) if isinstance(score, (int, float)) else None
        out.append({"scene": sid, "score": score, "flagged": score is not None and score < cfg("min_score"),
                    "issues": issues})
    return out


def run(spec: Spec, project_dir: Path, rows: list[dict], look: dict | None = None) -> dict:
    """Review the preview sheets in rows ([{scene, sheet, frames}]); writes preview/review.json."""
    words = json.loads((project_dir / "words.json").read_text())
    data = _call(prompt(spec, rows, words, look), {r["scene"]: Path(r["sheet"]) for r in rows})
    scenes = parse(data, rows)
    for s in scenes:
        s["file_hash"] = file_hash(spec, s["scene"])
    path = project_dir / "preview" / "review.json"
    if path.exists():                     # a preview of some scenes keeps the others' last review
        done = {s["scene"] for s in scenes}
        order = [s.id for s in spec.scenes]
        kept = [s for s in json.loads(path.read_text()).get("scenes", []) if s["scene"] not in done and s["scene"] in order]
        scenes = sorted(scenes + kept, key=lambda s: order.index(s["scene"]))
    out = {"scenes": scenes, "flagged": [s["scene"] for s in scenes if s["flagged"]],
           "issues": sum(len(s["issues"]) for s in scenes)}
    path.write_text(json.dumps(out, indent=2, ensure_ascii=False))
    return out


def for_qa(spec: Spec, project_dir: Path) -> dict | None:
    """The last preview review for qa.json, each scene marked stale when its file changed since."""
    p = project_dir / "preview" / "review.json"
    if not p.exists():
        return None
    rev = json.loads(p.read_text())
    ids = {s.id for s in spec.scenes}
    scenes = [{**s, "stale": s.get("file_hash") != file_hash(spec, s["scene"])} for s in rev["scenes"] if s["scene"] in ids]
    return {"scenes": scenes, "flagged": [s["scene"] for s in scenes if s["flagged"] and not s["stale"]],
            "stale": [s["scene"] for s in scenes if s["stale"]]}
