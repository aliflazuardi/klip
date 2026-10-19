import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from klip.paths import ROOT, SCHEMA_PATH
from klip.spec import Spec, export_schema, load_spec

EXAMPLES = sorted((ROOT / "examples").glob("*.json"))


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.name)
def test_examples_validate(path: Path):
    load_spec(path)


def _base(**over):
    d = {"slug": "x", "scenes": [{"id": "s1", "template": "hook", "narration": "Halo"}]}
    d.update(over)
    return d


def test_minimal_spec_defaults():
    s = Spec.model_validate(_base())
    assert s.voice == "female" and s.speech_rate is None and s.scenes[0].visual.type == "solid"


def test_icon_requires_name():
    with pytest.raises(ValidationError, match="requires visual.name"):
        Spec.model_validate(_base(scenes=[{"id": "s1", "template": "hook", "narration": "x",
                                           "visual": {"type": "icon"}}]))


def test_duplicate_scene_ids_rejected():
    sc = {"id": "s1", "template": "hook", "narration": "x"}
    with pytest.raises(ValidationError, match="duplicate"):
        Spec.model_validate(_base(scenes=[sc, sc]))


def test_unknown_fields_rejected():
    with pytest.raises(ValidationError):
        Spec.model_validate(_base(voise="male"))


def test_bad_rate_and_voice_rejected():
    with pytest.raises(ValidationError):
        Spec.model_validate(_base(speech_rate="fast"))
    with pytest.raises(ValidationError):
        Spec.model_validate(_base(voice="robot"))


def test_committed_schema_is_current():
    assert json.loads(SCHEMA_PATH.read_text()) == export_schema(), "run `uv run klip schema`"
