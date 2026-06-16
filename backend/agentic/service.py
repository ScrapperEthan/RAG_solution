from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from backend.answer.service import AnswerService
from backend.ports import LLM
from backend.retrieve.service import Retriever
from backend.util import read_json

logger = logging.getLogger(__name__)


INTENT_SYSTEM = """task: agentic_classify_intent
Classify a user question for a card + RAG agent. Return STRICT JSON:
{"intent": "exact"|"concept"}.

Decision rules:
- exact: concrete values, configuration defaults, limits, counts, identifiers,
  error codes, version-specific behavior, precise steps, parameters, or fields.
- concept: definitions, overviews, responsibilities, relationships, rationale,
  and "how do X and Y work together" questions.
- If the user asks for more detail, expresses doubt, or asks for the original
  source, treat it as exact because the agent should drill down to source text.
- Exact questions require an inline value with anchor or a source drilldown;
  pointer-only and missing fields are not enough for direct answers."""

INTENT_SCHEMA = {"type": "object", "required": ["intent"]}


ROUTER_SYSTEM = """task: agentic_route_card
Select the approved knowledge card(s) that can answer the user question.
You receive a compact card catalog: each entry has canonical_id, canonical_name,
aliases, boundary, and module. There is no vector index — this selection IS the
retrieval step. Return STRICT JSON: {"canonical_ids": [string, ...]}.

Rules:
- Only return canonical_ids that appear in the catalog.
- Prefer the single best card. Return multiple ids only when the question
  genuinely spans more than one card.
- Match on meaning, not surface words: a question may hit a card through its
  aliases or boundary even if it never repeats the canonical_name.
- The boundary states what the card does and does not cover — respect it.
- If no card's boundary covers the question, return {"canonical_ids": []}."""

ROUTER_SCHEMA = {"type": "object", "required": ["canonical_ids"]}


class AgenticService:
    def __init__(self, outputs_dir: Path, retriever: Retriever, answerer: AnswerService, llm: LLM):
        self.outputs_dir = outputs_dir
        self.retriever = retriever
        self.answerer = answerer
        self.llm = llm
        self.cards = load_cards(outputs_dir)
        self.refs = load_refs(outputs_dir)

    def answer(self, query: str, variant: Dict, filters: Optional[Dict] = None, debug: bool = False) -> Dict:
        source = variant.get("answer_source", "pure-rag")
        if source == "pure-rag":
            refs = self.retriever.retrieve(
                query,
                index=variant.get("index", "body"),
                search=variant.get("search", "vector"),
                top_k=variant.get("top_k", 8),
                rerank=bool(variant.get("rerank", False)),
                filters=filters,
            )
            result = self.answerer.answer_from_refs(query, refs)
            result["drilled"] = None
            result["evidence_sections"] = refs
            result = with_execution(
                result,
                requested_mode=source,
                path="rag-retrieval",
                evidence_kind="retrieval",
                steps=["Run configured vector/full-text retrieval", "Generate answer from retrieved sections"],
            )
            if debug:
                result["debug"] = self._debug_payload(
                    query=query,
                    answer_mode=source,
                    intent=None,
                    routing=self._empty_routing(),
                    retrieval=self._debug_retrieval(variant, refs),
                    drilldown=None,
                    refs_used=refs,
                    card_used=None,
                )
            return result

        card, routing = self.find_card(query, return_meta=True)
        if not card:
            refs = self.retriever.retrieve(
                query,
                index="both",
                search="hybrid",
                top_k=8,
                rerank=bool(variant.get("rerank", False)),
                filters=filters,
            )
            result = self.answerer.answer_from_refs(query, refs)
            result["drilled"] = True
            result["evidence_sections"] = refs
            result = with_execution(
                result,
                requested_mode=source,
                path="agentic-rag-fallback" if source == "agentic" else "rag-fallback",
                evidence_kind="retrieval",
                steps=["No approved card matched the question", "Fallback to hybrid RAG retrieval"],
            )
            if debug:
                result["debug"] = self._debug_payload(
                    query=query,
                    answer_mode=source,
                    intent=None,
                    routing=routing,
                    retrieval=self._debug_retrieval({"index": "both", "search": "hybrid", "top_k": 8, "rerank": variant.get("rerank", False)}, refs),
                    drilldown=None,
                    refs_used=refs,
                    card_used=None,
                )
            return result

        if source == "card-direct":
            result = answer_from_card(query, card, drilled=False)
            result = with_execution(
                result,
                requested_mode=source,
                path="card-direct",
                evidence_kind="card",
                card=card,
                steps=["Match approved canonical card", "Answer from card fields without source drilldown"],
            )
            if debug:
                result["debug"] = self._debug_payload(
                    query=query,
                    answer_mode=source,
                    intent=None,
                    routing=routing,
                    retrieval=None,
                    drilldown=None,
                    refs_used=[],
                    card_used=card,
                )
            return result

        if source == "card-grounding":
            refs = self.refs_for_card(card)
            result = self.answerer.answer_from_refs(query, refs)
            result["drilled"] = True
            result["evidence_sections"] = refs
            result = with_execution(
                result,
                requested_mode=source,
                path="card-grounding",
                evidence_kind="source",
                card=card,
                steps=["Match approved canonical card", "Follow card source anchors", "Generate answer from source sections"],
            )
            if debug:
                result["debug"] = self._debug_payload(
                    query=query,
                    answer_mode=source,
                    intent=None,
                    routing=routing,
                    retrieval=None,
                    drilldown=self._debug_drilldown(card, refs),
                    refs_used=refs,
                    card_used=card,
                )
            return result

        if source == "agentic":
            intent = self.classify_intent(query)
            if intent == "exact" and not has_relevant_inline_value(card, query):
                refs = self.refs_for_card(card)
                result = self.answerer.answer_from_refs(query, refs)
                result["drilled"] = True
                result["evidence_sections"] = refs
                result = with_execution(
                    result,
                    requested_mode=source,
                    path="agentic-source-drilldown",
                    evidence_kind="source",
                    card=card,
                    intent=intent,
                    steps=["Match approved canonical card", "Classify intent as exact", "Inline value missing", "Drill down to source anchors"],
                )
                if debug:
                    result["debug"] = self._debug_payload(
                        query=query,
                        answer_mode=source,
                        intent=intent,
                        routing=routing,
                        retrieval=None,
                        drilldown=self._debug_drilldown(card, refs),
                        refs_used=refs,
                        card_used=card,
                    )
                return result
            if has_relevant_pointer_field(card, query):
                refs = self.refs_for_card(card)
                result = self.answerer.answer_from_refs(query, refs)
                result["drilled"] = True
                result["evidence_sections"] = refs
                result = with_execution(
                    result,
                    requested_mode=source,
                    path="agentic-source-drilldown",
                    evidence_kind="source",
                    card=card,
                    intent=intent,
                    steps=["Match approved canonical card", f"Classify intent as {intent}", "Relevant field is pointer-only", "Drill down to source anchors"],
                )
                if debug:
                    result["debug"] = self._debug_payload(
                        query=query,
                        answer_mode=source,
                        intent=intent,
                        routing=routing,
                        retrieval=None,
                        drilldown=self._debug_drilldown(card, refs),
                        refs_used=refs,
                        card_used=card,
                    )
                return result
            result = answer_from_card(query, card, drilled=False, intent=intent)
            result = with_execution(
                result,
                requested_mode=source,
                path="agentic-card-direct",
                evidence_kind="card",
                card=card,
                intent=intent,
                steps=["Match approved canonical card", f"Classify intent as {intent}", "Use answerable card fields directly"],
            )
            if debug:
                result["debug"] = self._debug_payload(
                    query=query,
                    answer_mode=source,
                    intent=intent,
                    routing=routing,
                    retrieval=None,
                    drilldown=None,
                    refs_used=[],
                    card_used=card,
                )
            return result

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

    def find_card(self, query: str, return_meta: bool = False):
        """Retrieve the card to answer from. No embedding: the LLM reads a compact
        card catalog and picks (primary); deterministic keyword/alias matching is
        the fallback when the LLM declines or the pipeline runs offline."""
        routed, llm_ids, catalog_size = self._route_card_llm_with_meta(query)
        routing = {
            "method": "none",
            "llm_returned_ids": llm_ids,
            "catalog_size": catalog_size,
            "chosen_card": None,
        }
        if routed is not None:
            routing["method"] = "llm-router"
            routing["chosen_card"] = routed.get("canonical_id")
            return (routed, routing) if return_meta else routed
        keyword = self.match_card_keyword(query)
        if keyword is not None:
            routing["method"] = "keyword-fallback"
            routing["chosen_card"] = keyword.get("canonical_id")
            return (keyword, routing) if return_meta else keyword
        return (None, routing) if return_meta else None

    def route_card_llm(self, query: str) -> Optional[Dict]:
        """Let the LLM select a card from the catalog (id + name + aliases +
        boundary + module). The catalog is small enough to fit one prompt, so this
        single selection replaces vector retrieval. Returns None when the LLM
        declines or errors, so the caller falls back to keyword matching."""
        routed, _, _ = self._route_card_llm_with_meta(query)
        return routed

    def _route_card_llm_with_meta(self, query: str) -> Tuple[Optional[Dict], List[str], int]:
        if not self.cards:
            return None, [], 0
        catalog = [
            {
                "canonical_id": cid,
                "canonical_name": card["canonical_name"],
                "aliases": card.get("aliases", []),
                "boundary": card.get("boundary", ""),
                "module": card.get("module", []),
            }
            for cid, card in self.cards.items()
        ]
        try:
            response = self.llm.complete_json(
                ROUTER_SYSTEM,
                json.dumps({"query": query, "cards": catalog}, ensure_ascii=False),
                schema=ROUTER_SCHEMA,
            )
        except Exception:
            return None, [], len(catalog)
        ids = response.get("canonical_ids") if isinstance(response, dict) else None
        ids = [str(cid) for cid in ids] if isinstance(ids, list) else []
        if not ids:
            return None, [], len(catalog)
        for cid in ids:
            if cid in self.cards:
                return self.cards[cid], ids, len(catalog)
        return None, ids, len(catalog)

    def match_card_keyword(self, query: str) -> Optional[Dict]:
        lowered = query.lower()
        for cid, card in self.cards.items():
            names = [card["canonical_name"]] + card.get("aliases", [])
            if any(name.lower() in lowered for name in names):
                return self.cards.get(cid)
        for card in self.cards.values():
            card_text = " ".join(
                [
                    card["canonical_name"],
                    *card.get("aliases", []),
                    " ".join(str(field.get("value") or "") for field in card.get("fields", [])),
                ]
            ).lower()
            if any(token in card_text for token in lowered.split() if len(token) >= 4):
                return card
        return None

    def refs_for_card(self, card: Dict) -> List[Dict]:
        """Follow a card back to its source sections in loaded_refs.json.

        Use the card's recorded ``source_section_ids`` directly: they ARE the
        loaded_refs keys (full heading-path form, see backend.util.section_id).
        The old code rebuilt ``{page_id}#{anchor.split(' > ')[-1]}`` (leaf-only,
        and ``anchor`` even carries the page title), which never matched the
        full-path keys -> 0 refs -> empty context -> NO_ANSWER on every drilldown.

        Subsections (and their facts) hold most of a card's evidence, so collect
        the specific ones first, then the card-level field aggregates as fallback.
        """
        section_ids = self._card_section_ids(card)
        seen = set()
        refs = []
        for item in section_ids:
            sid = item["section_id"]
            if sid in self.refs and sid not in seen:
                refs.append(self.refs[sid])
                seen.add(sid)
        if not refs:
            logger.warning(
                "refs_for_card found 0 refs for card %s: none of its %d source_section_ids "
                "resolve in loaded_refs.json (check reduce/load section_id consistency)",
                card.get("canonical_id"),
                len(section_ids),
            )
        return refs[:8]

    def _card_section_ids(self, card: Dict) -> List[Dict[str, str]]:
        """Return source section ids in the exact order card drilldown uses."""
        rows: List[Dict[str, str]] = []
        for sub_index, sub in enumerate(card.get("subsections", [])):
            subsection = str(sub.get("name") or f"subsection[{sub_index}]")
            for fact_index, fact in enumerate(sub.get("facts", [])):
                for sid in fact.get("source_section_ids", []):
                    if sid:
                        rows.append(
                            {
                                "origin": "fact",
                                "section_id": str(sid),
                                "subsection": subsection,
                                "fact_index": str(fact_index),
                                "field": str(fact.get("field") or ""),
                                "label": str(fact.get("label") or ""),
                            }
                        )
            for sid in sub.get("source_section_ids", []):
                if sid:
                    rows.append(
                        {
                            "origin": "subsection",
                            "section_id": str(sid),
                            "subsection": subsection,
                            "fact_index": "",
                            "field": "",
                            "label": "",
                        }
                    )
        for field_index, field in enumerate(card.get("fields", [])):
            for sid in field.get("source_section_ids", []):
                if sid:
                    rows.append(
                        {
                            "origin": "field",
                            "section_id": str(sid),
                            "subsection": "",
                            "fact_index": "",
                            "field_index": str(field_index),
                            "field": str(field.get("field") or ""),
                            "label": str(field.get("label") or ""),
                        }
                    )
        return rows

    def _debug_payload(
        self,
        *,
        query: str,
        answer_mode: str,
        intent: Optional[str],
        routing: Dict[str, Any],
        retrieval: Optional[Dict[str, Any]],
        drilldown: Optional[Dict[str, Any]],
        refs_used: List[Dict],
        card_used: Optional[Dict],
    ) -> Dict[str, Any]:
        return {
            "query": query,
            "answer_mode": answer_mode,
            "intent": intent,
            "routing": routing,
            "retrieval": retrieval,
            "drilldown": drilldown,
            "refs_used": [debug_ref(ref) for ref in refs_used],
            "card_used": debug_card(card_used) if card_used else None,
        }

    def _debug_retrieval(self, variant: Dict, refs: List[Dict]) -> Dict[str, Any]:
        return {
            "index": variant.get("index", "both"),
            "search": variant.get("search", "hybrid"),
            "top_k": int(variant.get("top_k", 8)),
            "rerank": bool(variant.get("rerank", False)),
            "hits": [debug_ref_hit(ref) for ref in refs],
        }

    def _debug_drilldown(self, card: Dict, refs_used: List[Dict]) -> Dict[str, Any]:
        gathered = self._card_section_ids(card)
        resolved: List[str] = []
        missed: List[str] = []
        seen_resolved = set()
        seen_missed = set()
        for item in gathered:
            sid = item["section_id"]
            if sid in self.refs:
                if sid not in seen_resolved:
                    resolved.append(sid)
                    seen_resolved.add(sid)
            elif sid not in seen_missed:
                missed.append(sid)
                seen_missed.add(sid)
        return {
            "gathered": gathered,
            "resolved_section_ids": resolved,
            "missed_section_ids": missed,
            "counts": {
                "gathered": len(gathered),
                "resolved": len(resolved),
                "missed": len(missed),
                "capped_to": len(refs_used),
            },
        }

    def _empty_routing(self) -> Dict[str, Any]:
        return {
            "method": "none",
            "llm_returned_ids": [],
            "catalog_size": len(self.cards),
            "chosen_card": None,
        }


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


def debug_ref(ref: Dict) -> Dict[str, Any]:
    score = ref.get("score")
    heading_path = ref.get("heading_path", [])
    return {
        "section_id": ref.get("section_id", ""),
        "anchor": ref.get("anchor") or " > ".join(heading_path),
        "title": ref.get("title", ""),
        "heading_path": heading_path,
        "source_url": ref.get("source_url", ""),
        "module": ref.get("module", []),
        "score": round(float(score), 6) if isinstance(score, (int, float)) else None,
        "body_md": ref.get("body_md", ""),
    }


def debug_ref_hit(ref: Dict) -> Dict[str, Any]:
    score = ref.get("score")
    return {
        "section_id": ref.get("section_id", ""),
        "title": ref.get("title", ""),
        "heading_path": ref.get("heading_path", []),
        "source_url": ref.get("source_url", ""),
        "score": round(float(score), 6) if isinstance(score, (int, float)) else None,
    }


def debug_card(card: Dict) -> Dict[str, Any]:
    keys = [
        "canonical_id",
        "canonical_name",
        "topic_class",
        "topic_type",
        "aliases",
        "module",
        "boundary",
        "status",
        "keywords_raw_agg",
        "concepts_agg",
        "questions_agg_en",
        "questions_agg_zh",
        "source_section_ids",
        "subsections",
        "fields",
        "flags",
    ]
    return {key: card.get(key) for key in keys if key in card}


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
        "contexts": snippets,
        "drilled": drilled,
        "card_evidence": [
            {
                "field": field.get("field", ""),
                "tier": field.get("tier", ""),
                "value": field.get("value"),
                "pointer_to": field.get("pointer_to"),
                "sources": field.get("sources", []),
            }
            for field in selected_fields
        ],
    }


def with_execution(
    result: Dict,
    *,
    requested_mode: str,
    path: str,
    evidence_kind: str,
    steps: List[str],
    card: Optional[Dict] = None,
    intent: Optional[str] = None,
) -> Dict:
    steps = list(steps)
    diagnostic = None
    # Make a silent failure visible: a source/retrieval path that produced no
    # evidence yields NO_ANSWER for a reason the UI must show, not hide.
    if evidence_kind in {"source", "retrieval"} and not result.get("evidence_sections"):
        diagnostic = "drilldown/retrieval returned 0 source refs — answer is ungrounded"
        steps.append("⚠ 命中 0 条原文证据：未取到可引用的来源段落，因此返回 NO_ANSWER")
        logger.warning("%s produced 0 evidence sections for card %s", path, (card or {}).get("canonical_id"))
    result["diagnostic"] = diagnostic
    result["execution"] = {
        "requested_mode": requested_mode,
        "path": path,
        "evidence_kind": evidence_kind,
        "steps": steps,
        "intent": intent,
        "drilled": result.get("drilled"),
        "diagnostic": diagnostic,
        "card": (
            {
                "canonical_id": card.get("canonical_id", ""),
                "canonical_name": card.get("canonical_name", ""),
                "module": card.get("module", []),
            }
            if card
            else None
        ),
    }
    return result


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
    generic_tokens = {
        "plugin",
        "service",
        "component",
        "what",
        "does",
        "about",
        "please",
        "tell",
        "干嘛的",
        "是什么",
    }
    return any(token in field_text for token in query.split() if len(token) >= 4 and token not in generic_tokens)


def dedupe(items: List[str]) -> List[str]:
    seen = set()
    result = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result
