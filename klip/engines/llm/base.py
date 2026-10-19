from __future__ import annotations

from typing import Protocol


class LLMError(RuntimeError):
    pass


class LLMProvider(Protocol):
    name: str

    def complete(self, system: str, user: str, schema: dict) -> str | dict:
        """Return the model's answer: a parsed dict (structured output) or raw text containing JSON."""
        ...
