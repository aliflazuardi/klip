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


def test_loop_seam_ends_on_the_first_frame(tmp_path):
    from PIL import Image, ImageChops, ImageStat

    from klip.spec import load_spec
    from klip.paths import ROOT
    raw = tmp_path / "raw.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=108x192:r=30:d=2",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(raw)], check=True)
    (tmp_path / "words.json").write_text(json.dumps([{"text": "a", "startMs": 0, "endMs": 1000, "sceneId": "s1"}]))
    spec = load_spec(ROOT / "examples" / "menguap.json")
    assert post.loop_seam(spec.model_copy(update={"loop": False}), tmp_path, raw, 2.0) == raw
    out = post.loop_seam(spec.model_copy(update={"loop": True}), tmp_path, raw, 2.0)
    assert out.name == "raw_loop.mp4"
    assert abs(float(post.ffmpeg.probe(out)["format"]["duration"]) - 2.0) < 0.1
    frames = []
    for i, args in enumerate((["-i", str(out)], ["-sseof", "-0.04", "-i", str(out)])):
        png = tmp_path / f"f{i}.png"
        subprocess.run(["ffmpeg", "-v", "error", "-y", *args, "-frames:v", "1", "-update", "1", str(png)], check=True)
        frames.append(Image.open(png).convert("RGB"))
    assert max(ImageStat.Stat(ImageChops.difference(*frames)).mean) < 6      # last frame ≈ first frame
    # no room after the last word: no seam
    (tmp_path / "words.json").write_text(json.dumps([{"text": "a", "startMs": 0, "endMs": 1950, "sceneId": "s1"}]))
    assert post.loop_seam(spec.model_copy(update={"loop": True}), tmp_path, raw, 2.0) == raw
