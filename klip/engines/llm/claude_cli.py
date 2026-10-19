"""Claude via the Claude Code CLI (`claude -p`). Uses your existing Claude plan; no API key.

Structured output is enforced with --json-schema. Runs in a temp dir so this repo's
CLAUDE.md and skills don't leak into the prompt. Web tools are optional (llm.claude.allow_web).
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile

from klip import config
from klip.engines.llm.base import LLMError

AUTH_HINT = ("The Claude Code CLI isn't logged in. Run `claude` in a terminal and use /login, "
             "then try again (or set llm.provider: openai in klip.yaml).")


class ClaudeCLI:
    name = "claude"

    def __init__(self, binary: str | None = None):
        self.binary = binary or shutil.which("claude")

    def available(self) -> bool:
        return bool(self.binary)

    def complete(self, system: str, user: str, schema: dict) -> str | dict:
        if not self.binary:
            raise LLMError("`claude` CLI not found on PATH")
        cfg = config.get("llm.claude", {}) or {}
        # the CLI's validator rejects the draft-2020-12 "$schema" meta key; the schema itself is fine
        schema = {k: v for k, v in schema.items() if k != "$schema"}
        cmd = [self.binary, "-p", "--output-format", "json", "--no-session-persistence",
               "--system-prompt", system, "--json-schema", json.dumps(schema)]
        if cfg.get("allow_web", True):
            cmd += ["--tools", "WebSearch,WebFetch", "--allowedTools", "WebSearch,WebFetch"]
        else:
            cmd += ["--tools", ""]
        if cfg.get("model"):
            cmd += ["--model", str(cfg["model"])]
        with tempfile.TemporaryDirectory() as cwd:
            try:
                proc = subprocess.run(cmd, input=user, capture_output=True, text=True, cwd=cwd,
                                      timeout=cfg.get("timeout_s", 600))
            except subprocess.TimeoutExpired:
                raise LLMError(f"claude -p timed out after {cfg.get('timeout_s', 600)}s") from None
        return parse_output(proc.stdout, proc.stderr, proc.returncode)


def parse_output(stdout: str, stderr: str = "", returncode: int = 0) -> str | dict:
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        raise LLMError(f"claude -p returned non-JSON output (exit {returncode}): "
                       f"{(stdout or stderr).strip()[:500]}") from None
    if data.get("is_error") or data.get("subtype") not in (None, "success"):
        msg = str(data.get("result") or data.get("subtype") or "unknown error")
        hint = f"\n{AUTH_HINT}" if any(w in msg.lower() for w in ("auth", "login", "oauth", "credential")) else ""
        raise LLMError(f"claude -p failed: {msg}{hint}")
    if isinstance(data.get("structured_output"), dict):
        return data["structured_output"]
    return data.get("result") or ""
