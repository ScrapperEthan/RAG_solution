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
            canonicals = {item["canonical_id"]: item for item in payload["approved_canonicals"]}
            return {"canonical_ids": canonical_ids_for(payload["section"], canonicals), "needs_review": []}
        if "card_reduce_resolve_aliases" in system:
            return {"aliases": []}
        if "card_expand_boundary" in system:
            return {"boundary": mock_expand_boundary(json.loads(user))}
        if "card_summarize" in system:
            return mock_card_summary(json.loads(user))
        if "card_discover_topics" in system:
            return mock_discover(json.loads(user))
        if "card_review_conflict" in system:
            return mock_review_conflict(json.loads(user))
        if "answer_from_context" in system:
            from backend.answer.service import synthesize_answer

            payload = json.loads(user)
            return {"answer": synthesize_answer(payload["query"], payload["refs"])}
        if "agentic_route_card" in system:
            return {"canonical_ids": mock_route_card(json.loads(user))}
        if "agentic_classify_intent" in system or "classify_intent" in system:
            payload = parse_json_or_text(user)
            query = payload.get("query", user) if isinstance(payload, dict) else user
            return {"intent": classify_intent(query)}
        if "judge_faithfulness" in system:
            return {"score": 1.0 if "NO_ANSWER" not in user else 0.8}
        return {}

    def complete_text(
        self,
        system: str,
        user: str,
        *,
        temperature: float = 0.0,
        max_tokens: int = 2048,
    ) -> str:
        if "llm_direct_answer" in system:
            return f"MOCK_DIRECT — ungrounded model answer for: {user}"
        if "NO_ANSWER" in user:
            return '{"score": 0.8, "reason": "mock no-answer path"}'
        return '{"score": 1.0, "reason": "mock deterministic path"}'


def mock_discover(payload: Dict) -> Dict:
    """Deterministic, domain-agnostic stand-in for topic discovery (offline only).

    Maps raw terms that already match an approved canonical, clusters the rest by
    normalized form into candidates. The real LLM does smarter clustering in-network.
    """
    def norm(text: str) -> str:
        return re.sub(r"[^a-z0-9]+", " ", str(text).lower()).strip()

    raw_terms = payload.get("raw_keywords") or []
    approved = payload.get("approved_canonicals") or []
    approved_terms: Dict[str, str] = {}
    for canonical in approved:
        for term in [canonical.get("canonical_name", ""), *(canonical.get("aliases") or [])]:
            if term:
                approved_terms[norm(term)] = canonical.get("canonical_id", "")

    mapped = []
    clusters: Dict[str, Dict] = {}
    for term in raw_terms:
        key = norm(term)
        if not key:
            continue
        if key in approved_terms:
            mapped.append({"raw": term, "canonical_id": approved_terms[key]})
            continue
        cluster = clusters.setdefault(key, {"canonical_name": term, "aliases": [], "evidence_keywords": [], "suggested_subsections": [], "nearest_existing": None})
        if term != cluster["canonical_name"] and term not in cluster["aliases"]:
            cluster["aliases"].append(term)
        cluster["evidence_keywords"].append(term)
    return {"mapped": mapped, "candidates": list(clusters.values()), "needs_review": []}


def mock_review_conflict(payload: Dict) -> Dict:
    """Deterministic offline stand-in for the LLM conflict reviewer.

    Recommends the newest value (the pipeline's auto choice) and flags risk by how
    different the candidate values look: two distinct *numeric* values is high risk
    (picking the newest could silently ship wrong data); plain text edits are
    medium; whitespace-only differences are low. The real in-network LLM reasons
    over the same candidates and writes a fuller justification."""
    candidates = payload.get("candidates") or []
    values = [str(c.get("value", "")).strip() for c in candidates]
    auto = str(payload.get("auto_choice") or (values[-1] if values else ""))
    label = str(payload.get("label") or payload.get("field") or "this field")

    distinct = {v for v in values if v}
    digit_sets = {re.sub(r"[^0-9]", "", v) for v in values if re.search(r"\d", v)}
    if len(digit_sets) > 1:
        risk = "high"
    elif len(distinct) > 1:
        risk = "medium"
    else:
        risk = "low"
    confidence = 0.55 if risk == "high" else (0.75 if risk == "medium" else 0.95)
    reason_zh = (
        f"“{label}”有 {len(distinct)} 个不同取值，已暂选最新版本 “{auto}”。"
        + ("候选值数字明显不同，自动取最新可能漏掉一次真实变更，建议人工确认后再批准。" if risk == "high" else "若最新版本即权威来源，可直接批准最新值。")
    )
    reason_en = (
        f"'{label}' has {len(distinct)} distinct values; kept the newest '{auto}'. "
        + ("Numeric values differ materially, so verify before approving." if risk == "high" else "Approve the newest if it is the authoritative source.")
    )
    return {
        "recommended_value": auto,
        "reason_zh": reason_zh,
        "reason_en": reason_en,
        "confidence": confidence,
        "risk": risk,
    }


def mock_route_card(payload: Dict) -> list:
    """Deterministic offline stand-in for the LLM card router.

    Only resolves unambiguous canonical_name/alias substring hits against the
    catalog the router is given; returns [] otherwise so the caller falls back to
    the full deterministic matcher (keeps offline behaviour identical to before).
    The real in-network LLM does semantic selection over the same catalog.
    """
    query = str(payload.get("query", "")).lower()
    for card in payload.get("cards") or []:
        names = [card.get("canonical_name", ""), *(card.get("aliases") or [])]
        if any(name and name.lower() in query for name in names):
            return [card.get("canonical_id")]
    return []


def mock_card_summary(payload: Dict) -> Dict:
    """Deterministic offline stand-in for the LLM card summarizer.

    Joins the real intro prose + subsection names into a clean wiki-style opener.
    The real in-network LLM writes a more fluent paragraph from the same inputs.
    """
    name = str(payload.get("canonical_name") or "").strip()
    aliases = [str(a).strip() for a in (payload.get("aliases") or []) if str(a).strip()]
    intros = [str(t).strip() for t in (payload.get("intro_texts") or []) if str(t).strip()]
    subs = [str(s).strip() for s in (payload.get("subsections") or []) if str(s).strip()]
    boundary = str(payload.get("boundary") or "").strip()
    lead = intros[0] if intros else boundary
    alias_zh = f"（又称 {', '.join(aliases[:2])}）" if aliases else ""
    sub_zh = f" 覆盖：{'、'.join(subs[:6])}。" if subs else ""
    sub_en = f" Covers: {', '.join(subs[:6])}." if subs else ""
    zh = f"{name}{alias_zh}：{lead}".rstrip("。.") + "。" + sub_zh
    en = f"{name}: {lead}".rstrip(". ") + "." + sub_en
    return {"summary_zh": zh.strip(), "summary_en": en.strip()}


def mock_expand_boundary(payload: Dict) -> str:
    """Deterministic stand-in for the LLM boundary writer (real LLM does this in-network)."""
    name = str(payload.get("canonical_name") or "").strip()
    extras = [str(item).strip() for item in (list(payload.get("aliases") or []) + list(payload.get("subsections") or [])) if str(item).strip()]
    extras = list(dict.fromkeys(extras))
    base = str(payload.get("current_boundary") or "").strip()
    scope = "、".join(extras) if extras else name
    if base:
        return base.rstrip("。.") + (f"；并涵盖：{scope}。" if extras else "。")
    if name:
        return f"{name} 范围涵盖 {scope}。"
    return base


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
