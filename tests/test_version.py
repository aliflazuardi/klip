"""Version: one source (pyproject.toml), exposed as klip.__version__ and listed in CHANGELOG.md."""

import re
import tomllib

from klip import __version__
from klip.paths import ROOT


def _pyproject_version() -> str:
    return tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]


def test_version_matches_pyproject():
    assert __version__ == _pyproject_version()


def test_version_is_semver():
    assert re.fullmatch(r"\d+\.\d+\.\d+(?:-[0-9A-Za-z.]+)?", _pyproject_version())


def test_changelog_has_unreleased_and_current_version():
    log = (ROOT / "CHANGELOG.md").read_text()
    assert "## [Unreleased]" in log
    assert f"## [{_pyproject_version()}]" in log
