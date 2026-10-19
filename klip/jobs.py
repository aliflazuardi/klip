"""Background render jobs for the MCP server: one render at a time, status persisted to disk.

projects/_jobs/<job_id>.json holds the status, so job_status still answers after a server
restart (a job that was running when the server died is reported as "interrupted").
"""

from __future__ import annotations

import json
import logging
import threading
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path

from klip import pipeline
from klip.paths import PROJECTS_DIR

log = logging.getLogger(__name__)

JOBS_DIR = PROJECTS_DIR / "_jobs"
# Rough share of wall time per stage (render dominates), for a progress estimate.
STAGE_PROGRESS = {"voice + assets": 0.0, "compose": 0.2, "render": 0.25, "post": 0.85, "qa": 0.95}


@dataclass
class Job:
    id: str
    spec_path: str
    voice: str | None = None
    variants: bool = False
    slug: str = ""
    project_dir: str = ""
    status: str = "queued"          # queued | running | done | failed | interrupted
    stage: str = ""
    progress: float = 0.0
    created: float = field(default_factory=time.time)
    started: float | None = None
    finished: float | None = None
    outputs: dict = field(default_factory=dict)
    qa: dict | None = None
    warnings: list[str] = field(default_factory=list)
    error: str | None = None

    def to_dict(self) -> dict:
        d = asdict(self)
        end = self.finished or time.time()
        d["elapsed_s"] = round(end - self.started, 1) if self.started else 0.0
        return d


class JobRunner:
    def __init__(self, jobs_dir: Path | None = None):
        self.jobs_dir = jobs_dir or JOBS_DIR
        self.jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="klip-render")

    def _save(self, job: Job) -> None:
        self.jobs_dir.mkdir(parents=True, exist_ok=True)
        tmp = self.jobs_dir / f"{job.id}.json.part"
        tmp.write_text(json.dumps(job.to_dict(), indent=2, ensure_ascii=False, default=str))
        tmp.replace(self.jobs_dir / f"{job.id}.json")

    def submit(self, spec_path: Path, voice: str | None = None, variants: bool = False) -> Job:
        job = Job(id=uuid.uuid4().hex[:10], spec_path=str(spec_path), voice=voice, variants=variants)
        with self._lock:
            self.jobs[job.id] = job
        self._save(job)
        self._pool.submit(self._run, job)
        return job

    def _run(self, job: Job) -> None:
        handler = None
        try:
            spec, project_dir = pipeline.resolve(Path(job.spec_path), job.voice)
            job.slug, job.project_dir = spec.slug, str(project_dir)
            job.status, job.started = "running", time.time()
            self._save(job)
            handler = logging.FileHandler(project_dir / "job.log", encoding="utf-8")
            handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
            logging.getLogger().addHandler(handler)

            def on_stage(stage: str) -> None:
                job.stage, job.progress = stage, STAGE_PROGRESS.get(stage, job.progress)
                self._save(job)

            results = pipeline.run_all(spec, project_dir, on_stage=on_stage)
            post = results["post"]
            job.outputs = {k: post.get(k) for k in ("final", "nomusic", "duration_s", "music")}
            job.outputs.update(cover=str(project_dir / "cover.png"), post_txt=str(project_dir / "post.txt"),
                               caption=(project_dir / "post.txt").read_text(encoding="utf-8"))
            job.qa = results["qa"]
            job.warnings = results["compose"]["warnings"] + results["assets"].get("warnings", [])
            if job.variants and spec.hook_variants:
                job.outputs["variants"] = pipeline.run_variants(spec, project_dir, results, on_stage=on_stage)
            job.status, job.progress, job.stage = "done", 1.0, "done"
        except Exception as e:  # report, never crash the server
            job.status, job.error = "failed", f"{type(e).__name__}: {e}"
            log.error("job %s failed: %s\n%s", job.id, e, traceback.format_exc())
        finally:
            job.finished = time.time()
            if handler:
                logging.getLogger().removeHandler(handler)
                handler.close()
            self._save(job)

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            if job_id in self.jobs:
                return self.jobs[job_id]
        path = self.jobs_dir / f"{job_id}.json"
        if not path.exists():
            return None
        data = json.loads(path.read_text())
        data.pop("elapsed_s", None)
        job = Job(**data)
        if job.status in ("queued", "running"):   # its server process is gone
            job.status = "interrupted"
        return job

    def list(self, limit: int = 10) -> list[Job]:
        if not self.jobs_dir.exists():
            return []
        paths = sorted(self.jobs_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:limit]
        return [j for p in paths if (j := self.get(p.stem))]

    def wait(self, job_id: str, timeout_s: float = 900, poll_s: float = 1.0) -> Job:
        end = time.time() + timeout_s
        while time.time() < end:
            job = self.get(job_id)
            if job and job.status not in ("queued", "running"):
                return job
            time.sleep(poll_s)
        raise TimeoutError(f"job {job_id} still running after {timeout_s}s")
