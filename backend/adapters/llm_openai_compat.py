from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Dict


class OpenAICompatLLM:
    """Minimal OpenAI-compatible chat completions client."""

    def __init__(self, config: Dict):
        self.base_url = config.get("base_url", "").rstrip("/")
        self.model = config.get("model", "")
        api_key = config.get("api_key") or os.environ.get(config.get("api_key_env", "OPENAI_API_KEY"), "")
        self.api_key = api_key

    def complete_json(
        self,
        system: str,
        user: str,
        *,
        schema: Dict,
        temperature: float = 0.0,
        max_tokens: int = 2048,
    ) -> Dict:
        if not self.base_url:
            raise ValueError("llm.base_url is required for OpenAICompatLLM")
        body = {
            "model": self.model,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        data = json.dumps(body).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=data,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"LLM request failed: {exc.code} {detail}") from exc
        content = payload["choices"][0]["message"]["content"]
        return json.loads(content)

