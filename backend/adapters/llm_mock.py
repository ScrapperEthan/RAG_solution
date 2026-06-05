from __future__ import annotations

import json
import re
from typing import Dict


class MockLLM:
    """Deterministic JSON LLM stand-in.

    It is intentionally simple. The domain-specific extraction is implemented in
    mapper/reducer code, while this adapter keeps the LLM port available for tests.
    """

    def complete_json(
        self,
        system: str,
        user: str,
        *,
        schema: Dict,
        temperature: float = 0.0,
        max_tokens: int = 2048,
    ) -> Dict:
        if "card_map_section" in system:
            from backend.mapper.extract import extract_section_record

            return extract_section_record(json.loads(user))
        if "card_map_page_summary" in system:
            return page_summary(json.loads(user))
        if "card_reduce_normalize_section" in system:
            from backend.reducer.canonicals import canonical_ids_for

            payload = json.loads(user)
            return {"canonical_ids": canonical_ids_for(payload["section"])}
        if "answer_from_context" in system:
            from backend.answer.service import synthesize_answer

            payload = json.loads(user)
            return {"answer": synthesize_answer(payload["query"], payload["refs"])}
        if "agentic_classify_intent" in system or "classify_intent" in system:
            payload = parse_json_or_text(user)
            query = payload.get("query", user) if isinstance(payload, dict) else user
            return {"intent": classify_intent(query)}
        if "judge_faithfulness" in system:
            return {"score": 1.0 if "NO_ANSWER" not in user else 0.8}
        return {}


def parse_json_or_text(text: str):
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def page_summary(payload: Dict) -> Dict:
    title = payload["title"]
    sections = payload.get("sections", [])
    concepts = sorted({concept for section in sections for concept in section.get("concepts", [])})
    concept_text_en = ", ".join(concepts) if concepts else "the page topics"
    concept_text_zh = "、".join(concepts) if concepts else "页面主题"
    return {
        "summary_en": f"{title} contains {len(sections)} sections about {concept_text_en}.",
        "summary_zh": f"{title} 包含 {len(sections)} 个 section，主题包括 {concept_text_zh}。",
        "cross_questions_en": [f"How do the sections in {title} relate?"],
        "cross_questions_zh": [f"{title} 里的各部分如何关联?"],
    }


def classify_intent(text: str) -> str:
    lowered = text.lower()
    exact_markers = [
        "default",
        "batch_size",
        "max_retry",
        "otp_length",
        "otp_ttl",
        "error code",
        "dm-429",
        "how many",
        "几次",
        "默认",
        "错误码",
        "有效期",
        "多少",
    ]
    if any(marker in lowered for marker in exact_markers):
        return "exact"
    if re.search(r"\bwhy\b|\bhow\b|怎么|为什么|配合|work together", lowered):
        return "concept"
    return "concept"
