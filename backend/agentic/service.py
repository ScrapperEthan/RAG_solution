from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional

from backend.answer.service import AnswerService
from backend.ports import LLM
from backend.reducer.canonicals import CANONICALS
from backend.retrieve.service import Retriever
from backend.util import read_json


INTENT_SYSTEM = """task: agentic_classify_intent
Classify the user question as exact when it asks for a concrete value, code,
identifier, default, limit, or count. Otherwise classify it as concept."""

INTENT_SCHEMA = {"type": "object", "required": ["intent"]}


class AgenticService:
    def __init__(self, outputs_dir: Path, retriever: Retriever, answerer: AnswerService, llm: LLM):
        self.outputs_dir = outputs_dir
        self.retriever = retriever
        self.answerer = answerer
        self.llm = llm
        self.cards = load_cards(outputs_dir)
        self.refs = load_refs(outputs_dir)

    def answer(self, query: str, variant: Dict) -> Dict:
        source = variant.get("answer_source", "pure-rag")
        if source == "pure-rag":
            refs = self.retriever.retrieve(
                query,
                index=variant.get("index", "body"),
                search=variant.get("search", "vector"),
                top_k=variant.get("top_k", 8),
            )
            result = self.answerer.answer_from_refs(query, refs)
            result["drilled"] = None
            return result

        card = self.find_card(query)
        if not card:
            refs = self.retriever.retrieve(query, index="both", search="hybrid", top_k=8)
            result = self.answerer.answer_from_refs(query, refs)
            result["drilled"] = True
            return result

        if source == "card-direct":
            return answer_from_card(query, card, drilled=False)

        if source == "card-grounding":
            refs = self.refs_for_card(card)
            result = self.answerer.answer_from_refs(query, refs)
            result["drilled"] = True
            return result

        if source == "agentic":
            intent = self.classify_intent(query)
            if intent == "exact" and not has_relevant_inline_value(card, query):
                refs = self.refs_for_card(card)
                result = self.answerer.answer_from_refs(query, refs)
                result["drilled"] = True
                return result
            if has_relevant_pointer_field(card, query):
                refs = self.refs_for_card(card)
                result = self.answerer.answer_from_refs(query, refs)
                result["drilled"] = True
                return result
            return answer_from_card(query, card, drilled=False, intent=intent)

        raise ValueError(f"Unknown answer_source: {source}")

    def classify_intent(self, query: str) -> str:
        response = self.llm.complete_json(
            INTENT_SYSTEM,
            json.dumps({"query": query}, ensure_ascii=False),
            schema=INTENT_SCHEMA,
        )
        intent = response.get("intent")
        if intent not in {"exact", "concept"}:
            raise ValueError(f"Unknown agentic intent returned by LLM: {intent}")
        return intent

    def find_card(self, query: str) -> Optional[Dict]:
        lowered = query.lower()
        for cid, canonical in CANONICALS.items():
            names = [canonical["canonical_name"]] + canonical["aliases"]
            if any(name.lower() in lowered for name in names):
                return self.cards.get(cid)
        if "retry" in lowered or "batch" in lowered or "dm " in lowered or "message batches" in lowered:
            return self.cards.get("C-0007")
        if "journey" in lowered:
            return self.cards.get("C-0008")
        if "adaptor" in lowered or "adapter" in lowered:
            return self.cards.get("C-0009")
        if "otp" in lowered:
            return self.cards.get("C-0014")
        return None

    def refs_for_card(self, card: Dict) -> List[Dict]:
        section_ids = []
        for field in card["fields"]:
            for source in field.get("sources", []):
                heading = source["anchor"].split(" > ")[-1]
                section_ids.append(f"{source['page_id']}#{heading}")
        seen = set()
        refs = []
        for sid in section_ids:
            if sid in self.refs and sid not in seen:
                refs.append(self.refs[sid])
                seen.add(sid)
        return refs[:8]


def load_cards(outputs_dir: Path) -> Dict[str, Dict]:
    path = outputs_dir / "cards_index.json"
    if not path.exists():
        return {}
    return {card["canonical_id"]: card for card in read_json(path)}


def load_refs(outputs_dir: Path) -> Dict[str, Dict]:
    path = outputs_dir / "loaded_refs.json"
    if not path.exists():
        return {}
    return {ref["section_id"]: ref for ref in read_json(path)}


def answer_from_card(query: str, card: Dict, drilled: bool, intent: str = "concept") -> Dict:
    selected_fields = select_fields_for_query(query, card, intent)
    citations = []
    snippets = []
    section_ids = []
    for field in selected_fields:
        if field.get("value"):
            snippets.append(str(field["value"]))
        for source in field.get("sources", []):
            citations.append(source["source_url"])
            section_ids.append(f"{source['page_id']}#{source['anchor'].split(' > ')[-1]}")
    if not snippets:
        answer = "NO_ANSWER — card has no answerable value."
    else:
        answer = " ".join(snippets[:2])
    return {
        "answer": answer,
        "citations": dedupe(citations)[:3],
        "retrieved_section_ids": dedupe(section_ids),
        "drilled": drilled,
    }


def has_relevant_inline_value(card: Dict, query: str) -> bool:
    lowered = query.lower()
    for field in card["fields"]:
        if field["tier"] != "inline-value" or not field.get("value"):
            continue
        field_text = f"{field.get('field', '')} {field.get('value', '')}".lower()
        if query_mentions_field(lowered, field_text):
            return True
    return False


def has_relevant_pointer_field(card: Dict, query: str) -> bool:
    lowered = query.lower()
    for field in card["fields"]:
        if field["tier"] != "pointer-only":
            continue
        field_text = f"{field.get('field', '')} {field.get('pointer_to', '')}".lower()
        if query_mentions_field(lowered, field_text):
            return True
    return False


def select_fields_for_query(query: str, card: Dict, intent: str) -> List[Dict]:
    lowered = query.lower()
    exact_fields = [
        field
        for field in card["fields"]
        if field["tier"] == "inline-value" and query_mentions_field(lowered, f"{field.get('field', '')} {field.get('value', '')}".lower())
    ]
    if exact_fields:
        return exact_fields
    if intent == "exact":
        pointer_fields = [
            field
            for field in card["fields"]
            if field["tier"] == "pointer-only" and query_mentions_field(lowered, f"{field.get('field', '')} {field.get('pointer_to', '')}".lower())
        ]
        if pointer_fields:
            return pointer_fields
    narrative_fields = [
        field
        for field in card["fields"]
        if field["tier"] == "narrative" or field.get("field") in {"definition", "related_components"}
    ]
    return narrative_fields or card["fields"]


def query_mentions_field(query: str, field_text: str) -> bool:
    exact_markers = [
        "batch_size",
        "batch size",
        "max_retry",
        "retry",
        "otp_length",
        "otp_ttl",
        "error",
        "dm-429",
        "dm-503",
        "default",
        "config",
        "配置",
        "默认",
        "重试",
        "错误",
        "有效期",
    ]
    if any(marker in query and marker in field_text for marker in exact_markers):
        return True
    return any(token in field_text for token in query.split() if len(token) >= 4)


def dedupe(items: List[str]) -> List[str]:
    seen = set()
    result = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result
