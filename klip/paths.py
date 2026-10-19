"""Well-known locations. Override the repo root with KLIP_HOME and the cache with KLIP_CACHE_DIR."""

import os
from pathlib import Path

ROOT = Path(os.environ.get("KLIP_HOME", Path(__file__).resolve().parents[1]))
TEMPLATES_DIR = ROOT / "templates"
RENDERER_DIR = ROOT / "renderer"
SCHEMA_PATH = ROOT / "schema" / "spec.schema.json"
PROJECTS_DIR = ROOT / "projects"
CACHE_DIR = Path(os.environ.get("KLIP_CACHE_DIR", Path.home() / ".cache" / "klip"))
