"""Klip: prompt → short vertical video pipeline."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("klip")  # single source of truth: [project].version in pyproject.toml
except PackageNotFoundError:  # running from a checkout without `uv sync`
    __version__ = "0.0.0+unknown"
