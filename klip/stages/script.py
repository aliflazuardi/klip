"""Stage 1 — Script (standalone mode): topic -> spec JSON via an LLM, validated, with retries.

In Claude Code the agent writes the spec itself (see the /klip skill). This stage is for
`klip new` / `klip script` without an agent. The writing guide is read from the skill file
so both paths follow the same rules.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import ValidationError

from klip import config
from klip.engines.llm.base import LLMError, LLMProvider
from klip.engines.llm.claude_cli import ClaudeCLI
from klip.engines.llm.openai_compat import OpenAICompat
from klip.lint import Issue, errors, lint
from klip.paths import ROOT
from klip.spec import Spec, export_schema

log = logging.getLogger(__name__)

SKILL_PATH = ROOT / ".claude" / "skills" / "klip" / "SKILL.md"
EXAMPLE_PATH = ROOT / "examples" / "tidur-siang.json"
SPECS_DIR = ROOT / "specs"
GUIDE_SECTIONS = ("What this build can render", "Writing guide")


class ScriptError(RuntimeError):
    def __init__(self, msg: str, attempts: list[dict] | None = None):
        super().__init__(msg)
        self.attempts = attempts or []


@dataclass
class ScriptResult:
    spec: Spec
    issues: list[Issue]
    attempts: list[dict] = field(default_factory=list)
    provider: str = ""


def get_provider(name: str | None = None) -> LLMProvider:
    name = name or config.get("llm.provider", "auto")
    if name == "claude":
        return ClaudeCLI()
    if name == "openai":
        return OpenAICompat()
    if name == "auto":
        if (c := ClaudeCLI()).available():
            return c
        if (o := OpenAICompat()).available():
            return o
        raise LLMError("no LLM available: install Claude Code (`claude`) or set LLM_BASE_URL and "
                       "LLM_MODEL in .env (e.g. Ollama: http://localhost:11434/v1)")
    raise LLMError(f"unknown llm.provider {name!r} (auto | claude | openai)")


def writing_guide() -> str:
    """The skill's 'What this build can render' + 'Writing guide' sections."""
    text = SKILL_PATH.read_text(encoding="utf-8")
    parts = re.split(r"^## ", text, flags=re.M)
    keep = ["## " + p.strip() for p in parts if p.startswith(GUIDE_SECTIONS)]
    if not keep:
        raise ScriptError(f"writing guide sections not found in {SKILL_PATH}")
    return "\n\n".join(keep)


def word_budget(voice: str, duration_s: int, scenes: int = 6) -> int:
    from klip.pipeline import words_per_second
    return round((duration_s - 0.15 * scenes - 1.0) * words_per_second(voice, None))


def build_prompts(topic: str, voice: str, duration_s: int, style: str, allow_web: bool,
                  hooks: int = 1) -> tuple[str, str]:
    example = EXAMPLE_PATH.read_text(encoding="utf-8")
    research = ("Use web search to check each factual claim and cite the page you used."
                if allow_web else
                "You cannot browse: only cite sources you are certain exist (official health/science "
                "organizations, well-known papers). Never invent URLs; leave a claim out instead.")
    system = f"""You write scene specs for Klip, a pipeline that turns an Indonesian topic into a
TikTok video (1080x1920, voiceover, word-synced captions). Your entire answer is ONE JSON
object that validates against the Klip spec JSON Schema. No prose, no markdown.

{writing_guide()}

## Facts
Every factual claim (health, science, finance, history) goes in `facts[]` as
{{"claim": "...", "source": "Publisher — https://..."}}. {research}
The user reviews the spec before rendering, so flag uncertainty in the claim text rather than
overstating it.

## Example of a good spec
{example}
"""
    user = (f"Topik: {topic}\n"
            f"Voice: {voice}\nTarget duration: {duration_s} s "
            f"(about {word_budget(voice, duration_s)} words of narration in total)\n"
            f"Style: {style}\n"
            + (f"A/B hooks: also write exactly {hooks - 1} alternative hook(s) in `hook_variants`, each a "
               f"different hook type, same payoff.\n" if hooks > 1 else "")
            + "Write the spec JSON now. Indonesian narration, English stock queries.")
    return system, user


def extract_json(answer: str | dict) -> dict:
    if isinstance(answer, dict):
        return answer
    text = answer.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    if fence:
        text = fence.group(1)
    else:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            raise ValueError("no JSON object in the answer")
        text = text[start:end + 1]
    return json.loads(text)


def _validate(data: dict, voice: str, duration_s: int, style: str,
              hooks: int = 1) -> tuple[Spec | None, list[str], list[Issue]]:
    # The caller's choices win over whatever the model wrote.
    data = {**data, "voice": voice, "target_duration_s": duration_s, "style": style}
    data.pop("speech_rate", None)
    try:
        spec = Spec.model_validate(data)
    except ValidationError as e:
        msgs = [f"{'.'.join(str(x) for x in err['loc'])}: {err['msg']}" for err in e.errors()]
        return None, msgs, []
    issues = lint(spec)
    problems = [str(i) for i in errors(issues)]
    if hooks > 1 and len(spec.hook_variants) < hooks - 1:
        problems.append(f"hook_variants has {len(spec.hook_variants)} item(s); write exactly {hooks - 1}")
    return spec, problems, issues


def generate(topic: str, voice: str = "female", duration_s: int = 45, style: str = "default",
             provider: LLMProvider | None = None, hooks: int = 1) -> ScriptResult:
    provider = provider or get_provider()
    allow_web = provider.name == "claude" and (config.get("llm.claude", {}) or {}).get("allow_web", True)
    system, user = build_prompts(topic, voice, duration_s, style, allow_web, hooks)
    schema = export_schema()
    max_tries = 1 + int(config.get("llm.max_retries", 2))
    attempts: list[dict] = []
    prompt = user
    for n in range(1, max_tries + 1):
        log.info("script: asking %s (attempt %d/%d)", provider.name, n, max_tries)
        answer = provider.complete(system, prompt, schema)
        try:
            data = extract_json(answer)
        except (ValueError, json.JSONDecodeError) as e:
            problems, spec, issues, data = [f"answer was not valid JSON: {e}"], None, [], None
        else:
            spec, problems, issues = _validate(data, voice, duration_s, style, hooks)
        attempts.append({"attempt": n, "problems": problems})
        if spec and not problems:
            return ScriptResult(spec, issues, attempts, provider.name)
        log.warning("script: attempt %d had %d problem(s): %s", n, len(problems), "; ".join(problems[:3]))
        previous = json.dumps(data, ensure_ascii=False) if data else str(answer)[:4000]
        prompt = (f"{user}\n\nYour previous answer:\n{previous}\n\n"
                  f"It has these problems; fix all of them and answer with the corrected JSON only:\n- "
                  + "\n- ".join(problems))
    raise ScriptError(f"no valid spec after {max_tries} attempts; last problems: {'; '.join(problems[:5])}",
                      attempts)


def save(spec: Spec, out: Path | None = None) -> Path:
    """Write to specs/<slug>.json (or `out`), never overwriting an existing spec."""
    if out is None:
        SPECS_DIR.mkdir(exist_ok=True)
        out, n = SPECS_DIR / f"{spec.slug}.json", 2
        while out.exists():
            out, n = SPECS_DIR / f"{spec.slug}-{n}.json", n + 1
    out.parent.mkdir(parents=True, exist_ok=True)
    # exclude_unset (not exclude_none): an explicit null like music.mood must survive a reload
    data = spec.model_dump(mode="json", exclude_unset=True)
    out.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return out
