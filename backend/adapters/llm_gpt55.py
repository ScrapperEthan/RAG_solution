from __future__ import annotations

from typing import Dict

from backend.adapters.llm_openai_compat import OpenAICompatLLM


class Gpt55LLM(OpenAICompatLLM):
    """Intranet gpt-5.5 adapter.

    If the intranet endpoint is OpenAI-compatible, configure base_url/model/api_key
    and use this as-is. If not, opencode should override complete_json here.
    """

    def __init__(self, config: Dict):
        super().__init__(config)

