"""Render settings: worker count, the raw-video cache, and post copying the renderer's video stream."""

import json
import subprocess

from klip import config
from klip.engines.render import hyperframes
from klip.stages import post
from klip.stages import render as render_stage


def test_cores_means_one_worker_per_core_but_one(monkeypatch):
    monkeypatch.setattr(hyperframes.os, "cpu_count", lambda: 8)
    assert hyperframes.resolve_workers("cores") == "7"
    monkeypatch.setattr(hyperframes.os, "cpu_count", lambda: 32)
    assert hyperframes.resolve_workers("cores") == str(config.get("render.max_workers"))
    monkeypatch.setattr(hyperframes.os, "cpu_count", lambda: 1)
    assert hyperframes.resolve_workers("cores") == "1"
    assert hyperframes.resolve_workers("auto") == "auto" and hyperframes.resolve_workers("4") == "4"


class FakeRenderer:
    name = "fake"

    def __init__(self, settings):
        self.settings, self.calls = settings, 0

    def render(self, comp, out, fps=30):
        self.calls += 1
        out.write_bytes(b"mp4")
        return out


def test_raw_video_is_reused_until_the_composition_or_its_settings_change(tmp_path):
    (tmp_path / "composition").mkdir()
    (tmp_path / "composition" / "compose.json").write_text(json.dumps({"hash": "h1"}))
    r = FakeRenderer({"quality": "looks", "crf": 19})
    render_stage.run(tmp_path, r)
    render_stage.run(tmp_path, r)
    assert r.calls == 1
    r.settings = {"quality": "looks", "crf": 17}
    render_stage.run(tmp_path, r)
    assert r.calls == 2 and json.loads((tmp_path / "render.json").read_text())["settings"]["crf"] == 17


def _video(path, pix_fmt):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=108x192:r=30:d=1",
                    "-c:v", "libx264", "-pix_fmt", pix_fmt, str(path)], check=True)
    return path


def test_post_copies_a_ready_h264_stream_and_reencodes_anything_else(tmp_path, monkeypatch):
    wav = tmp_path / "a.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=f=440:d=1", str(wav)], check=True)
    cmds = []
    real = post.ffmpeg.run
    monkeypatch.setattr(post.ffmpeg, "run", lambda args: cmds.append(args) or real(args))
    post.encode(_video(tmp_path / "ok.mp4", "yuv420p"), wav, tmp_path / "out1.mp4")
    assert cmds[-1][cmds[-1].index("-c:v") + 1] == "copy"
    post.encode(_video(tmp_path / "odd.mp4", "yuv444p"), wav, tmp_path / "out2.mp4")
    assert cmds[-1][cmds[-1].index("-c:v") + 1] == "libx264" and config.get("render.preset") in cmds[-1]
