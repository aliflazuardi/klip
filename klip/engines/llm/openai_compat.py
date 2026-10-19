"""Any OpenAI-compatible chat endpoint: Ollama, LM Studio, OpenRouter, vLLM, etc.

.env: LLM_BASE_URL (e.g. http://localhost:11434/v1), LLM_MODEL, optional LLM_API_KEY.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from klip import config, env
from klip.engines.llm.base import LLMError


class OpenAICompat:
    name = "openai"

    def __init__(self, base_url: str | None = None, model: str | None = None, api_key: str | None = None):
        self.base_url = (base_url or env.get("LLM_BASE_URL") or "").rstrip("/")
        self.model = model or env.get("LLM_MODEL")
        self.api_key = api_key or env.get("LLM_API_KEY")

    def available(self) -> bool:
        return bool(self.base_url and self.model)

    def _post(self, payload: dict) -> dict:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        req = urllib.request.Request(f"{self.base_url}/chat/completions", data=json.dumps(payload).encode(),
                                     headers=headers, method="POST")
        timeout = (config.get("llm.openai", {}) or {}).get("timeout_s", 300)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r)

    def complete(self, system: str, user: str, schema: dict) -> str | dict:
        if not self.available():
            raise LLMError("set LLM_BASE_URL and LLM_MODEL in .env to use an OpenAI-compatible endpoint")
        payload = {
            "model": self.model,
            "temperature": (config.get("llm.openai", {}) or {}).get("temperature", 0.7),
            "messages": [
                {"role": "system", "content": system + "\n\n## JSON Schema\n" + json.dumps(schema)},
                {"role": "user", "content": user},
            ],
            "response_format": {"type": "json_object"},
        }
        try:
            data = self._post(payload)
        except urllib.error.HTTPError as e:
            if e.code != 400:
                raise LLMError(f"LLM endpoint returned HTTP {e.code}") from None
            payload.pop("response_format")  # some servers don't support JSON mode
            try:
                data = self._post(payload)
            except urllib.error.HTTPError as e2:
                raise LLMError(f"LLM endpoint returned HTTP {e2.code}") from None
        except (urllib.error.URLError, TimeoutError) as e:
            raise LLMError(f"can't reach LLM endpoint {self.base_url}: {e}") from None
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise LLMError(f"unexpected response from LLM endpoint: {str(data)[:300]}") from None
