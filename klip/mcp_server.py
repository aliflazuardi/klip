"""Klip MCP server: lets Claude (Desktop or Code) go from a prompt to a rendered video.

Run: `uv run klip mcp` (stdio). Claude writes the spec itself; this server validates,
renders in the background, and reports status. Logs go to stderr / job.log, never stdout
(stdout is the MCP channel).
"""

from __future__ import annotations

import json
import logging
import re
import sys
from pathlib import Path
from typing import Any

from mcp.server.mcpserver import Image, MCPServer
from mcp_types import TextContent
from pydantic import ValidationError

from klip import config, env
from klip.jobs import JobRunner
from klip.lint import errors, lint
from klip.paths import ROOT
from klip.spec import Spec, export_schema

INSTRUCTIONS = """Klip turns an Indonesian topic into a TikTok video (1080x1920 MP4 with voiceover,
word-synced captions, b-roll, music).
GUIDED FLOW: for a new video, guide the user step by step in Indonesian before writing, one short
message per step with a recommended option first (they can just say "ok"); never ask what the brand
guide fixes. Skip to step 5 if they say "langsung aja" or already gave everything.
  0 Channel: which brand (list_styles); call get_brand_guide and follow its "Guided flow" section.
  1 Topik: the topic as one core question, the series, 2-3 hook angles (one recommended).
  2 Gaya video: call video_styles; offer 2-4 styles the brand allows, each with what it looks like for
    this topic and the make time, the recommended one first with the reason.
  3 Bahan: what Klip fetches itself vs what the user may send (product/place photos, screenshots,
    own footage); optional, never block on it.
  4 Detail (max 4 questions): mascots, voice (only if the brand doesn't fix it), duration, CTA type.
  5 Ringkasan produksi: one card with every choice; ask to go on. Then the workflow below.
Workflow:
1. Call get_spec_schema once: it returns the JSON Schema, the writing guide, and an example spec.
   BRAND: if the user names a channel or brand (e.g. "Warga Nalar", "/warga-nalar") or a style from
   list_styles, call get_brand_guide(style) BEFORE writing and follow it: it sets the voice, series,
   visual rules and the mascot cast (who speaks, which voice, which role). Never ask the user who the
   mascots are or which voice they use; the brand guide and list_styles already say.
2. Research the facts for the topic (cite real sources in facts[]), then write the spec yourself.
   Voice: "suara cowok" = male, "suara cewek" = female (default female).
   Look: if the user asks for the stage / illustrated / collage / 90secondslab look ("pakai stage",
   "gaya ilustrasi"), set "look": "stage" and build most scenes with visual.type "stage";
   validate_spec enforces the share.
3. Call validate_spec and fix every error. Adjust the word count until the duration is in range.
   PREVIEW: call preview_spec and look at the contact sheets (stills at each scene's key moments) before
   rendering; fix what looks wrong and preview again. Required for code scenes (visual.type "code":
   send their HTML files in scene_files), useful for stage scenes.
4. REVIEW GATE: show the user each scene's narration and on-screen text, the estimated duration
   and the facts with sources. Wait for their approval before rendering (unless they said not to).
5. If the spec has stage photo props, call photo_brief and show the user which photos they could
   provide (files go in the photo folder it names). Then call render_spec. Rendering takes about
   2-3 minutes; poll job_status every ~30 s.
   For A/B hook tests, put 2-3 alternative hooks in hook_variants and pass variants=true.
6. Report the final.mp4 path, the QA result and the TikTok caption, and remind the user to turn
   on TikTok's AI-generated content label."""

TEMPLATES = {
    "hook": {"use": "first scene: big question or surprising claim", "fields": ["on_screen_text"]},
    "explain": {"use": "narration over b-roll/icon with a short headline", "fields": ["on_screen_text"]},
    "list_item": {"use": "numbered tip; consecutive list_items are auto-numbered 1/3, 2/3…",
                  "fields": ["on_screen_text", "list_index?", "list_total?"]},
    "myth_fact": {"use": "myth card struck through, then fact card on the reveal word",
                  "fields": ["myth", "fact", "reveal_at?"]},
    "stat": {"use": "big number counting up + label", "fields": ["stat{value,prefix?,suffix?,decimals?,label?}"]},
    "compare": {"use": "two columns, A vs B", "fields": ["compare{left{label,text?,icon?},right{…}}", "on_screen_text?"]},
    "cta": {"use": "last scene: follow / save prompt", "fields": ["on_screen_text"]},
}

server = MCPServer("klip", instructions=INSTRUCTIONS)
runner = JobRunner()


def _parse(spec: dict | str) -> dict:
    return json.loads(spec) if isinstance(spec, str) else spec


SCENE_FILE_EXT = (".html", ".js", ".svg")


def _write_scene_files(spec_data: dict, files: dict[str, str] | None) -> list[str]:
    """Save code-scene files sent with the spec (Claude Desktop can't write files) under
    specs/<slug>/. Keys are 'specs/<slug>/s1.html' or just 's1.html'. Returns errors."""
    if not files:
        return []
    slug = str(spec_data.get("slug", ""))
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", slug):
        return ["scene_files: the spec needs a valid slug first"]
    base = (ROOT / "specs" / slug).resolve()
    errs = []
    for name, text in files.items():
        path = (ROOT / name if "/" in name else base / name).resolve()
        if not path.is_relative_to(base) or path.suffix not in SCENE_FILE_EXT:
            errs.append(f"scene_files: {name!r} must be a {'/'.join(SCENE_FILE_EXT)} file in specs/{slug}/")
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return errs


def _check(spec_data: dict, voice: str | None) -> tuple[Spec | None, dict]:
    from klip.pipeline import estimate_duration_s
    if voice:
        spec_data = {**spec_data, "voice": voice}
    try:
        spec = Spec.model_validate(spec_data)
    except ValidationError as e:
        return None, {"valid": False, "errors": [f"{'.'.join(map(str, x['loc']))}: {x['msg']}" for x in e.errors()],
                      "warnings": []}
    issues = lint(spec)
    return spec, {
        "valid": not errors(issues),
        "errors": [str(i) for i in issues if i.level == "error"],
        "warnings": [str(i) for i in issues if i.level == "warning"],
        "word_count": spec.word_count,
        "estimated_duration_s": round(estimate_duration_s(spec), 1),
        "target_duration_s": spec.target_duration_s,
        "facts_to_verify": [f.model_dump() for f in spec.facts],
    }


@server.tool()
def get_spec_schema() -> dict[str, Any]:
    """The spec JSON Schema, the writing guide (templates, visuals, word budgets), and an example spec."""
    from klip.stages.script import EXAMPLE_PATH, writing_guide
    return {"schema": export_schema(), "writing_guide": writing_guide(),
            "example_spec": json.loads(EXAMPLE_PATH.read_text(encoding="utf-8"))}


@server.tool()
def list_voices() -> dict[str, Any]:
    """Available voices with their default speech rate and measured words/second."""
    from klip.pipeline import words_per_second
    engine = config.get("voices.engine", "edge")
    return {v: {"voice_id": vid, "default_rate": config.default_rate(v),
                "words_per_second": round(words_per_second(v, None), 2)}
            for v, vid in config.get(f"voices.ids.{engine}", {}).items()}


@server.tool()
def list_templates() -> dict[str, Any]:
    """Scene templates, what each is for, and their extra fields."""
    return TEMPLATES


@server.tool()
def list_styles() -> dict[str, Any]:
    """Visual styles a spec can pick with "style", with each brand's mascot cast (name, voice, side)."""
    out = {}
    for name in config.styles():
        st = config.style(name)
        info = {k: st.get(k) for k in ("accent_color", "emphasis_color", "transition")}
        cast = (st.get("mascot") or {}).get("cast") or []
        if cast:
            info["mascots"] = [{k: m.get(k) for k in ("name", "voice", "side")} for m in cast]
        info["has_brand_guide"] = (ROOT / "brands" / name / "skill" / "SKILL.md").is_file()
        out[name] = info
    return out


@server.tool()
def video_styles() -> dict[str, Any]:
    """The production styles Klip can make (stock, stage, chat, motion graphic, cinematic 3D, one world, mixed):
    what each looks like, what it needs from the user, which topics it suits. Step 2 of the guided flow."""
    return {"guide": (ROOT / "docs" / "VIDEO-STYLES.md").read_text(encoding="utf-8")}


@server.tool()
def get_brand_guide(style: str) -> dict[str, Any]:
    """A brand's writing and visual guide (its SKILL.md: voice, series, mascots and their roles, fact rules).
    Call this before writing any spec for a branded channel, e.g. style="warga-nalar"."""
    path = ROOT / "brands" / style / "skill" / "SKILL.md"
    if not path.is_file():
        return {"style": style, "found": False,
                "available": sorted(d.name for d in (ROOT / "brands").iterdir()
                                    if (d / "skill" / "SKILL.md").is_file())}
    st = config.style(style) if style in config.styles() else {}
    return {"style": style, "found": True, "guide": path.read_text(encoding="utf-8"),
            "mascot": st.get("mascot")}


@server.tool()
def validate_spec(spec: dict[str, Any] | str, voice: str | None = None,
                  scene_files: dict[str, str] | None = None) -> dict[str, Any]:
    """Validate a spec (schema + lint). Returns errors to fix, warnings, estimated duration, facts to verify.
    scene_files: code-scene files ({"s1.html": "<markup, style, script>"}), saved to specs/<slug>/ first."""
    try:
        data = _parse(spec)
    except json.JSONDecodeError as e:
        return {"valid": False, "errors": [f"spec is not valid JSON: {e}"], "warnings": []}
    if errs := _write_scene_files(data, scene_files):
        return {"valid": False, "errors": errs, "warnings": []}
    return _check(data, voice)[1]


@server.tool()
def render_spec(spec: dict[str, Any] | str, voice: str | None = None, variants: bool = False,
                progress_bar: bool | None = None, mascots: bool | list[str] | None = None,
                scene_files: dict[str, str] | None = None) -> dict[str, Any]:
    """Save the spec to specs/<slug>.json and start rendering in the background.
    Only call after the user approved the script. Returns a job_id for job_status.
    variants=true also renders every hook_variants entry (A/B hook test; ~2 min extra each).
    progress_bar=true/false shows or hides the progress bar at the top (saved into the spec);
    omit it to keep the spec's value (unset = the style's default).
    mascots=false hides the style's mascots, a list of names keeps only those (saved into the spec).
    scene_files: code-scene files, as in validate_spec."""
    try:
        data = _parse(spec)
    except json.JSONDecodeError as e:
        return {"started": False, "errors": [f"spec is not valid JSON: {e}"]}
    if errs := _write_scene_files(data, scene_files):
        return {"started": False, "errors": errs}
    if progress_bar is not None:
        data = {**data, "progress_bar": progress_bar}
    if mascots is not None:
        data = {**data, "mascots": mascots}
    parsed, report = _check(data, voice)
    if not parsed or not report["valid"]:
        return {"started": False, **report}
    path = ROOT / "specs" / f"{parsed.slug}.json"
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    job = runner.submit(path, voice, variants)
    return {"started": True, "job_id": job.id, "spec_path": str(path),
            "project_dir": str(ROOT / "projects" / parsed.slug),
            "note": "Rendering takes ~2-3 min. Poll job_status every ~30 s."}


@server.tool()
def photo_brief(spec: dict[str, Any] | str) -> dict[str, Any]:
    """Find photos for the spec's stage props (no voice, no render; ~1-2 min with the vision check)
    and return the photo brief: props with no photo, props marked `own`, and weak stock picks, each
    with the file name to save in the photo folder. Show it to the user at the review gate."""
    from klip.stages import assets
    try:
        data = _parse(spec)
    except json.JSONDecodeError as e:
        return {"ok": False, "errors": [f"spec is not valid JSON: {e}"]}
    parsed, report = _check(data, None)
    if not parsed or not report["valid"]:
        return {"ok": False, **report}
    project_dir = ROOT / "projects" / parsed.slug
    project_dir.mkdir(parents=True, exist_ok=True)
    b = assets.fetch(parsed, project_dir)["photo_brief"]
    return {"ok": True, **b, "markdown": Path(b["path"]).read_text(encoding="utf-8")}


@server.tool()
def preview_spec(spec: dict[str, Any] | str, scenes: list[str] | None = None, voice: str | None = None,
                 scene_files: dict[str, str] | None = None, review: bool = False) -> list[TextContent | Image]:
    """Stills of scenes at their key moments (start, each k.at cue, middle, end) as contact-sheet images,
    one per scene, to look at before rendering (~20-60 s; a free draft voice, no render quota).
    Default scenes: the code scenes, else all. Look at every sheet: does each still show what the voice
    says then, is text readable and inside the safe area, is anything empty, cut off or off-style?
    Fix the spec or scene_files and preview again (only the scenes you changed), then render_spec.
    scene_files: code-scene files, as in validate_spec. review=true also asks Claude (CLI) to score the
    sheets; you can usually judge them yourself."""
    from klip import preview as preview_mod
    from klip.engines.render.base import RenderError
    from klip.stages.compose import ComposeError

    def fail(errs: list[str], **extra) -> list[TextContent | Image]:
        return [TextContent(type="text", text=json.dumps({"ok": False, "errors": errs, **extra}, ensure_ascii=False))]
    try:
        data = _parse(spec)
    except json.JSONDecodeError as e:
        return fail([f"spec is not valid JSON: {e}"])
    if errs := _write_scene_files(data, scene_files):
        return fail(errs)
    parsed, report = _check(data, voice)
    if not parsed or not report["valid"]:
        return fail(report["errors"], warnings=report.get("warnings", []))
    project_dir = ROOT / "projects" / parsed.slug
    project_dir.mkdir(parents=True, exist_ok=True)
    try:
        res = preview_mod.run(parsed, project_dir, scenes, review=review)
    except (ValueError, ComposeError, RenderError) as e:
        return fail([f"preview failed: {e}"])
    tl = json.loads((project_dir / "timeline.json").read_text())
    summary = {"ok": True, "voice": f"draft ({tl['engine']})" if tl.get("draft") else tl["engine"],
               "scenes": [{"scene": r["scene"], "sheet": r["sheet"],
                           "stills": [f"{f['t']:.2f}s {f['label']}" for f in r["frames"]]} for r in res["rows"]],
               "warnings": report["warnings"], "review": res["review"], "review_error": res["review_error"]}
    return [TextContent(type="text", text=json.dumps(summary, ensure_ascii=False, indent=1)),
            *(Image(path=r["sheet"]) for r in res["rows"])]


@server.tool()
def job_status(job_id: str) -> dict[str, Any]:
    """Status of a render job: stage, progress (0-1), outputs (final.mp4 etc.), QA report, error."""
    job = runner.get(job_id)
    return job.to_dict() if job else {"error": f"unknown job {job_id}"}


@server.tool()
def list_jobs(limit: int = 10) -> list[dict[str, Any]]:
    """Recent render jobs, newest first."""
    return [{k: j.to_dict()[k] for k in ("id", "slug", "status", "stage", "progress", "elapsed_s")}
            for j in runner.list(limit)]


def main() -> None:
    env.load_dotenv()
    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(levelname)s %(name)s: %(message)s")
    server.run("stdio")


if __name__ == "__main__":
    main()
