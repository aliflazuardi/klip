"""Config file, linter, script generation (providers mocked), and the new CLI commands."""

import json
import re
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest
from typer.testing import CliRunner

from klip import config
from klip.engines.llm import claude_cli
from klip.engines.llm.base import LLMError
from klip.engines.llm.openai_compat import OpenAICompat
from klip.lint import errors, lint
from klip.paths import ROOT
from klip.spec import Spec, load_spec
from klip.stages import script

GOOD = json.loads((ROOT / "examples" / "tidur-siang.json").read_text())
needs_icons = pytest.mark.skipif(not (ROOT / "renderer/node_modules/lucide-static").exists(),
                                 reason="renderer/node_modules not installed")


# ---- config

def test_every_config_key_used_in_code_exists():
    used = set()
    for py in (ROOT / "klip").rglob("*.py"):
        used |= set(re.findall(r'config\.get\("([a-z_.]+)"', py.read_text()))
    missing = [k for k in sorted(used) if config.get(k) is None and not k.endswith(".model")]
    assert not missing, f"keys read in code but missing from klip.yaml: {missing}"


def test_styles_inherit_from_default():
    bold, default = config.style("bold"), config.style("default")
    assert bold["accent_color"] != default["accent_color"]
    assert bold["palette"] == default["palette"]
    assert bold["caption"]["font_size"] == 88 and bold["caption"]["top"] == default["caption"]["top"]
    with pytest.raises(KeyError, match="unknown style"):
        config.style("nope")


def test_brand_pack_adds_a_style_with_paths_relative_to_its_folder():
    st = config.style("example")
    assert "example" in config.styles() and st["accent_color"] == "#38BDF8"
    assert st["caption"]["top"] == config.style("default")["caption"]["top"]      # inherits default
    assert st["end_card"]["logo"] == str(ROOT / "brands" / "example" / "assets" / "logo.svg")


def test_local_config_overlays_klip_yaml(tmp_path, monkeypatch):
    local = tmp_path / "klip.local.yaml"
    local.write_text("lexicon:\n  Klip: klip\nqa:\n  max_still_s: 9\n")
    monkeypatch.setenv("KLIP_LOCAL_CONFIG", str(local))
    config.load.cache_clear()
    try:
        assert config.get("qa.max_still_s") == 9 and config.get("lexicon.Klip") == "klip"
        assert config.get("lexicon.vs") == "versus"                               # merged, not replaced
    finally:
        monkeypatch.delenv("KLIP_LOCAL_CONFIG")
        config.load.cache_clear()


# ---- lint

def spec_from(**over) -> Spec:
    return Spec.model_validate({**GOOD, **over})


def test_examples_lint_clean():
    for p in (ROOT / "examples").glob("*.json"):
        assert not errors(lint(load_spec(p))), p.name


def test_lint_duration_error_suggests_word_count():
    issues = errors(lint(spec_from(target_duration_s=20)))
    assert any("outside" in i.message and "aim for ~" in i.message for i in issues)


def test_lint_reveal_at_and_emphasis_and_single_list_item():
    scenes = json.loads(json.dumps(GOOD["scenes"]))
    scenes[2]["reveal_at"] = "Sebenarnya"            # not in narration
    scenes[0]["emphasis"] = ["tidak ada"]            # not anywhere
    del scenes[4:6]                                  # leave one list_item
    msgs = [str(i) for i in lint(spec_from(scenes=scenes, target_duration_s=38))]
    assert any("reveal_at" in m for m in msgs)
    assert any("emphasis 'tidak ada'" in m for m in msgs)
    assert any("single list_item" in m for m in msgs)


@needs_icons
def test_lint_unknown_icon_is_error():
    scenes = json.loads(json.dumps(GOOD["scenes"]))
    scenes[1]["visual"]["name"] = "not-an-icon"
    assert any("not-an-icon" in str(i) for i in errors(lint(spec_from(scenes=scenes))))


# ---- script generation

class FakeLLM:
    name = "fake"

    def __init__(self, answers):
        self.answers, self.prompts = list(answers), []

    def complete(self, system, user, schema):
        self.prompts.append(user)
        return self.answers.pop(0)


def test_writing_guide_and_prompt():
    guide = script.writing_guide()
    assert "## Writing guide" in guide and "## What this build can render" in guide
    system, user = script.build_prompts("Kenapa langit biru?", "male", 45, "default", allow_web=False)
    assert "Never invent URLs" in system and '"slug": "tidur-siang-ideal"' in system
    assert "Kenapa langit biru?" in user and "words of narration" in user


@pytest.mark.parametrize("answer", [json.dumps(GOOD), f"Here you go:\n```json\n{json.dumps(GOOD)}\n```", GOOD])
def test_extract_json(answer):
    assert script.extract_json(answer)["slug"] == GOOD["slug"]


def test_generate_retries_with_feedback_then_succeeds(monkeypatch):
    broken = json.loads(json.dumps(GOOD))
    del broken["scenes"][2]["myth"]
    llm = FakeLLM(["not json at all", broken, GOOD])
    res = script.generate("Tidur siang", "female", 45, provider=llm)
    assert res.spec.slug == GOOD["slug"] and len(res.attempts) == 3
    assert "not valid JSON" in llm.prompts[1]
    assert "requires: myth" in llm.prompts[2] and "Your previous answer" in llm.prompts[2]


def test_generate_forces_caller_choices():
    # male reads faster: the same 82 words are ~37 s, so target 40 s keeps the duration lint happy
    res = script.generate("x", "male", 40, style="bold", provider=FakeLLM([{**GOOD, "voice": "female"}]))
    assert (res.spec.voice, res.spec.target_duration_s, res.spec.style) == ("male", 40, "bold")


def test_generate_gives_up(monkeypatch):
    real_get = config.get
    monkeypatch.setattr(config, "get", lambda k, d=None: 1 if k == "llm.max_retries" else real_get(k, d))
    with pytest.raises(script.ScriptError, match="after 2 attempts") as e:
        script.generate("x", provider=FakeLLM(["{}", "{}"]))
    assert len(e.value.attempts) == 2


def test_save_never_overwrites_and_keeps_explicit_null(tmp_path, monkeypatch):
    monkeypatch.setattr(script, "SPECS_DIR", tmp_path)
    spec = Spec.model_validate({**GOOD, "music": {"mood": None}})
    a, b = script.save(spec), script.save(spec)
    assert a.name == "tidur-siang-ideal.json" and b.name == "tidur-siang-ideal-2.json"
    assert load_spec(b).music.mood is None


# ---- providers

def test_claude_parse_output():
    ok = json.dumps({"type": "result", "subtype": "success", "is_error": False, "result": "",
                     "structured_output": {"slug": "x"}})
    assert claude_cli.parse_output(ok) == {"slug": "x"}
    text = json.dumps({"subtype": "success", "is_error": False, "result": '{"slug": "y"}'})
    assert claude_cli.parse_output(text) == '{"slug": "y"}'
    expired = json.dumps({"subtype": "success", "is_error": True,
                          "result": "Failed to authenticate: OAuth session expired"})
    with pytest.raises(LLMError, match="/login"):
        claude_cli.parse_output(expired)
    with pytest.raises(LLMError, match="non-JSON"):
        claude_cli.parse_output("boom", "", 1)


def test_claude_cli_command(monkeypatch):
    seen = {}

    def fake_run(cmd, input, capture_output, text, cwd, timeout):
        seen.update(cmd=cmd, input=input, cwd=cwd)
        class P:
            returncode, stderr = 0, ""
            stdout = json.dumps({"subtype": "success", "is_error": False, "structured_output": {"ok": 1}})
        return P()

    monkeypatch.setattr(claude_cli.subprocess, "run", fake_run)
    out = claude_cli.ClaudeCLI("/bin/claude").complete(
        "SYS", "USER", {"$schema": "https://json-schema.org/draft/2020-12/schema", "type": "object"})
    cmd = seen["cmd"]
    assert out == {"ok": 1} and seen["input"] == "USER"
    assert cmd[cmd.index("--system-prompt") + 1] == "SYS"
    assert json.loads(cmd[cmd.index("--json-schema") + 1]) == {"type": "object"}
    assert "--no-session-persistence" in cmd and Path(seen["cwd"]) != ROOT


class _Handler(BaseHTTPRequestHandler):
    requests: list = []
    reply: str = "{}"

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        type(self).requests.append({"body": body, "auth": self.headers.get("Authorization")})
        if "response_format" in body:   # pretend this server has no JSON mode
            self.send_response(400)
            self.end_headers()
            return
        out = json.dumps({"choices": [{"message": {"content": type(self).reply}}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *a):
        pass


@pytest.fixture
def llm_server():
    _Handler.requests = []
    _Handler.reply = json.dumps(GOOD)
    srv = HTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}/v1"
    srv.shutdown()


def test_openai_compat_falls_back_without_json_mode(llm_server):
    p = OpenAICompat(llm_server, "test-model", "sk-test")
    assert json.loads(p.complete("SYS", "USER", {"type": "object"}))["slug"] == GOOD["slug"]
    first, second = _Handler.requests
    assert "response_format" in first["body"] and "response_format" not in second["body"]
    assert second["auth"] == "Bearer sk-test" and second["body"]["model"] == "test-model"
    assert "JSON Schema" in second["body"]["messages"][0]["content"]


def test_cli_script_end_to_end(llm_server, tmp_path, monkeypatch):
    from klip.cli import app
    monkeypatch.setenv("LLM_BASE_URL", llm_server)
    monkeypatch.setenv("LLM_MODEL", "test-model")
    out = tmp_path / "spec.json"
    r = CliRunner().invoke(app, ["script", "Tidur siang", "--provider", "openai", "-o", str(out)])
    assert r.exit_code == 0, r.output
    assert "wrote" in r.output and "Facts to verify" in r.output
    assert load_spec(out).slug == GOOD["slug"]


def test_cli_script_reports_llm_failure(monkeypatch):
    from klip.cli import app
    monkeypatch.setenv("LLM_BASE_URL", "http://127.0.0.1:9/v1")
    monkeypatch.setenv("LLM_MODEL", "m")
    r = CliRunner().invoke(app, ["script", "x", "--provider", "openai"])
    assert r.exit_code == 1 and "can't reach LLM endpoint" in r.output
