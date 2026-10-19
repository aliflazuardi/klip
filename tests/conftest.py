import pytest


@pytest.fixture(autouse=True)
def _no_real_claude(monkeypatch):
    """Tests must never call the real Claude CLI (slow, uses the user's plan)."""
    from klip.engines.media import vision

    def blocked(self, sheets):
        raise RuntimeError("real Claude vision calls are disabled in tests")

    monkeypatch.setattr(vision.VisionReviewer, "review", blocked)
