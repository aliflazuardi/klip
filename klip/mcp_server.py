"""Klip MCP server: lets Claude (Desktop or Code) go from a prompt to a rendered video.

Run: `uv run klip mcp` (stdio). Claude writes the spec itself; this server validates,
renders in the background, and reports status. Logs go to stderr / job.log, never stdout
(stdout is the MCP channel).
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any

from mcp.server.mcpserver import MCPServer
from pydantic import ValidationError

from klip import config, env
from klip.jobs import JobRunner
from klip.lint import errors, lint
from klip.paths import ROOT
from klip.spec import Spec, export_schema

INSTRUCTIONS = """Klip turns an Indonesian topic into a TikTok video (1080x1920 MP4 with voiceover,
word-synced captions, b-roll, music). Workflow:
1. Call get_spec_schema once: it returns the JSON Schema, the writing guide, and an example spec.
2. Research the facts for the topic (cite real sources in facts[]), then write the spec yourself.
   Voice: "suara cowok" = male, "suara cewek" = female (default female).
3. Call validate_spec and fix every error. Adjust the word count until the duration is in range.
4. REVIEW GATE: show the user each scene's narration and on-screen text, the estimated duration
   and the facts with sources. Wait for their approval before rendering (unless they said not to).
5. Call render_spec. Rendering takes about 2-3 minutes; poll job_status every ~30 s.
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
    """Visual styles a spec can pick with "style"."""
    return {name: {k: config.style(name).get(k) for k in ("accent_color", "emphasis_color", "transition")}
            for name in config.styles()}


@server.tool()
def validate_spec(spec: dict[str, Any] | str, voice: str | None = None) -> dict[str, Any]:
    """Validate a spec (schema + lint). Returns errors to fix, warnings, estimated duration, facts to verify."""
    try:
        data = _parse(spec)
    except json.JSONDecodeError as e:
        return {"valid": False, "errors": [f"spec is not valid JSON: {e}"], "warnings": []}
    return _check(data, voice)[1]


@server.tool()
def render_spec(spec: dict[str, Any] | str, voice: str | None = None, variants: bool = False,
                progress_bar: bool | None = None) -> dict[str, Any]:
    """Save the spec to specs/<slug>.json and start rendering in the background.
    Only call after the user approved the script. Returns a job_id for job_status.
    variants=true also renders every hook_variants entry (A/B hook test; ~2 min extra each).
    progress_bar=true/false shows or hides the progress bar at the top (saved into the spec);
    omit it to keep the spec's value (unset = the style's default)."""
    try:
        data = _parse(spec)
    except json.JSONDecodeError as e:
        return {"started": False, "errors": [f"spec is not valid JSON: {e}"]}
    if progress_bar is not None:
        data = {**data, "progress_bar": progress_bar}
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
