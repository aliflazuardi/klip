import os

import pytest

# Tests run against klip.yaml alone: a personal klip.local.yaml (another TTS engine, a whole take…)
# must not change what they check.
os.environ["KLIP_LOCAL_CONFIG"] = os.path.join(os.path.dirname(__file__), "no-local-config.yaml")


@pytest.fixture(autouse=True)
def _no_real_claude(monkeypatch):
    """Tests must never call the real Claude CLI (slow, uses the user's plan)."""
    from klip.engines.media import vision

    def blocked(self, sheets):
        raise RuntimeError("real Claude vision calls are disabled in tests")

    monkeypatch.setattr(vision.VisionReviewer, "review", blocked)
