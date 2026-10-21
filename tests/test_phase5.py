"""Batch mode, background jobs, and the MCP server (in-process and over real stdio)."""

import asyncio
import json
import sys
import time
from pathlib import Path

import pytest
import yaml
from mcp import Client
from mcp.client.stdio import StdioServerParameters

from klip import batch, jobs, mcp_server
from klip.paths import ROOT
from klip.spec import Spec

GOOD = json.loads((ROOT / "examples" / "tidur-siang.json").read_text())


def fake_results(passed=True):
    return {"post": {"final": "/x/final.mp4", "nomusic": None, "duration_s": 44.0, "music": None},
            "qa": {"passed": passed, "checks": [{"name": "duration", "ok": passed, "detail": ""}]},
            "compose": {"warnings": []}, "assets": {"warnings": []}}


# ---- batch

def test_batch_load_shapes_and_defaults(tmp_path):
    (tmp_path / "s.json").write_text(json.dumps(GOOD))
    f = tmp_path / "b.yaml"
    f.write_text(yaml.safe_dump({"defaults": {"voice": "male", "duration": 40, "progress_bar": False, "stage": True},
                                 "items": ["Topik A", {"topic": "Topik B", "voice": "female", "progress_bar": True,
                                                       "stage": False},
                                           {"spec": "s.json"}]}))
    a, b, c = batch.load(f)
    assert (a.topic, a.voice, a.duration, a.progress_bar) == ("Topik A", "male", 40, False)
    assert (b.voice, b.duration, b.progress_bar) == ("female", 40, True)
    assert a.stage and not b.stage
    assert c.spec == str(tmp_path / "s.json") and c.label == "s"
    f.write_text(yaml.safe_dump({"items": [{"voice": "male"}]}))
    with pytest.raises(ValueError, match="needs a topic or a spec"):
        batch.load(f)


def test_batch_continues_past_failures(tmp_path, monkeypatch):
    from klip.stages import script
    monkeypatch.setattr(batch, "PROJECTS_DIR", tmp_path)
    spec = Spec.model_validate(GOOD)
    calls = []

    def fake_generate(topic, *a, **k):
        calls.append(topic)
        if topic == "boom":
            raise RuntimeError("LLM down")
        return script.ScriptResult(spec.model_copy(update={"slug": topic.replace(" ", "-")}), [])

    monkeypatch.setattr(script, "generate", fake_generate)
    monkeypatch.setattr(script, "get_provider", lambda *a: None)
    monkeypatch.setattr(script, "save", lambda s, out=None: tmp_path / f"{s.slug}.json")
    monkeypatch.setattr(batch.pipeline, "resolve", lambda p, v=None, **k: (spec, tmp_path))
    outcomes = iter([fake_results(True), fake_results(False)])
    monkeypatch.setattr(batch.pipeline, "run_all", lambda *a, **k: next(outcomes))

    f = tmp_path / "b.yaml"
    f.write_text(yaml.safe_dump({"items": ["satu", "boom", "dua"]}))
    results, report = batch.run(f)
    assert [r.status for r in results] == ["ok", "failed", "qa_failed"]
    assert "LLM down" in results[1].detail and "QA failed: duration" in results[2].detail
    assert calls == ["satu", "boom", "dua"] and json.loads(report.read_text())[0]["status"] == "ok"

    results, _ = batch.run(f, scripts_only=True)
    assert [r.status for r in results] == ["scripted", "failed", "scripted"]
    follow = yaml.safe_load((tmp_path / "b.specs.yaml").read_text())
    assert [i["spec"] for i in follow["items"]] == [str(tmp_path / "satu.json"), str(tmp_path / "dua.json")]


# ---- jobs

def test_job_runner_done_failed_and_interrupted(tmp_path, monkeypatch):
    spec = Spec.model_validate(GOOD)
    (tmp_path / "post.txt").write_text("caption")
    monkeypatch.setattr(jobs.pipeline, "resolve", lambda p, v=None, **k: (spec, tmp_path))

    def run_all(spec, project_dir, on_stage=None, **k):
        for s in ("voice + assets", "render", "qa"):
            on_stage(s)
        if str(project_dir).endswith("never"):
            raise RuntimeError("nope")
        return fake_results()

    monkeypatch.setattr(jobs.pipeline, "run_all", run_all)
    runner = jobs.JobRunner(tmp_path / "_jobs")
    job = runner.wait(runner.submit(tmp_path / "s.json").id, timeout_s=10, poll_s=0.05)
    assert job.status == "done" and job.progress == 1.0 and job.outputs["final"] == "/x/final.mp4"
    assert job.qa["passed"] and job.outputs["caption"] == "caption"

    monkeypatch.setattr(jobs.pipeline, "resolve", lambda p, v=None: (spec, tmp_path / "never"))
    (tmp_path / "never").mkdir()
    bad = runner.wait(runner.submit(tmp_path / "s.json").id, timeout_s=10, poll_s=0.05)
    assert bad.status == "failed" and "nope" in bad.error

    # a job file left "running" by a dead server reads back as interrupted
    stale = jobs.Job(id="stale1", spec_path="x", status="running")
    runner._save(stale)
    assert jobs.JobRunner(tmp_path / "_jobs").get("stale1").status == "interrupted"
    assert {j.id for j in runner.list(10)} >= {job.id, bad.id, "stale1"}


# ---- MCP

def call(name, args=None):
    async def go():
        async with Client(mcp_server.server) as c:
            r = await c.call_tool(name, args or {})
            return r.structured_content
    return asyncio.run(go())


def test_mcp_lists_all_tools():
    async def go():
        async with Client(mcp_server.server) as c:
            return {t.name for t in (await c.list_tools()).tools}
    assert asyncio.run(go()) == {"get_spec_schema", "list_voices", "list_templates", "list_styles",
                                 "validate_spec", "render_spec", "photo_brief", "job_status", "list_jobs"}


def test_mcp_schema_and_lists():
    s = call("get_spec_schema")
    assert "## Writing guide" in s["writing_guide"] and s["example_spec"]["slug"] == "tidur-siang-ideal"
    assert set(call("list_templates")) == {"hook", "explain", "list_item", "myth_fact", "stat", "compare", "cta"}
    assert {"default", "bold"} <= set(call("list_styles"))
    assert call("list_voices")["male"]["voice_id"] == "id-ID-ArdiNeural"


def test_mcp_validate_reports_errors_and_review_info():
    ok = call("validate_spec", {"spec": GOOD})
    assert ok["valid"] and ok["estimated_duration_s"] > 0 and len(ok["facts_to_verify"]) == 3
    bad = call("validate_spec", {"spec": {**GOOD, "target_duration_s": 15}})
    assert not bad["valid"] and any("outside" in e for e in bad["errors"])
    assert not call("validate_spec", {"spec": json.dumps({"slug": "x"})})["valid"]


def test_mcp_render_spec_rejects_invalid_and_starts_valid(tmp_path, monkeypatch):
    assert call("render_spec", {"spec": {**GOOD, "target_duration_s": 15}})["started"] is False
    submitted = []
    monkeypatch.setattr(mcp_server, "ROOT", tmp_path)
    monkeypatch.setattr(mcp_server.runner, "submit",
                        lambda path, voice=None, variants=False: submitted.append((path, voice)) or jobs.Job(id="j1", spec_path=str(path)))
    # male reads faster: a 40 s target keeps this female-length script within the duration check
    r = call("render_spec", {"spec": json.dumps({**GOOD, "target_duration_s": 40}), "voice": "male"})
    assert r["started"] and r["job_id"] == "j1", r
    assert submitted == [(tmp_path / "specs" / "tidur-siang-ideal.json", "male")]
    assert json.loads(submitted[0][0].read_text())["slug"] == "tidur-siang-ideal"
    # progress_bar toggle is saved into the spec; omitted keeps the spec's value
    call("render_spec", {"spec": {**GOOD, "target_duration_s": 40}, "voice": "male", "progress_bar": False})
    assert json.loads(submitted[-1][0].read_text())["progress_bar"] is False
    call("render_spec", {"spec": {**GOOD, "target_duration_s": 40}, "voice": "male"})
    assert "progress_bar" not in json.loads(submitted[-1][0].read_text())
    assert "unknown job" in call("job_status", {"job_id": "nope"})["error"]


def test_mcp_over_real_stdio():
    """Launch the server as a subprocess, like Claude Desktop does; stdout must be pure MCP."""
    params = StdioServerParameters(command=sys.executable, args=["-m", "klip.mcp_server"], cwd=str(ROOT))

    async def go():
        async with Client(params) as c:
            names = {t.name for t in (await c.list_tools()).tools}
            v = (await c.call_tool("list_voices", {})).structured_content
            return names, v
    names, voices = asyncio.run(go())
    assert "render_spec" in names and "female" in voices


def test_desktop_entry_uses_absolute_paths():
    from klip.cli import desktop_server_entry
    e = desktop_server_entry()
    assert Path(e["command"]).is_absolute() and e["args"][:2] == ["--directory", str(ROOT)]
    assert e["args"][-1] == "klip-mcp" and "/usr/bin" in e["env"]["PATH"]


def test_resolve_progress_bar_override(tmp_path):
    from klip import pipeline
    (tmp_path / "s.json").write_text(json.dumps(GOOD))
    spec, _ = pipeline.resolve(tmp_path / "s.json", out_dir=tmp_path / "p")
    assert spec.progress_bar is None
    spec, d = pipeline.resolve(tmp_path / "s.json", out_dir=tmp_path / "p", progress_bar=False)
    assert spec.progress_bar is False
    assert json.loads((d / "spec.resolved.json").read_text())["progress_bar"] is False
