from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Dict, Iterable, List
from urllib.parse import urlparse

from backend.ports import LLM
from backend.schemas.validation import validate_map_page
from backend.util import clean_dir, read_json, write_json


MAP_SECTION_SYSTEM = """task: card_map_section
You extract a structured record from ONE section of a Confluence page for a
knowledge card index. Be faithful to the text. Never invent facts, keywords, or
values.

Return STRICT JSON with these fields:
{
  "concepts": [string],
  "keywords_raw": [string],
  "info_type": one of ["what-is","how-to","config","troubleshoot","reference","decision","meeting-notes"],
  "tier": one of ["narrative","inline-value","pointer-only"],
  "fact_value": string|null,
  "pointer_to": string|null,
  "summary_en": string,
  "summary_zh": string,
  "questions_en": [string],
  "questions_zh": [string],
  "confidence": number
}

Rules:
- concepts are topics this section is mainly about. Prefer known canonical names
  if they clearly match, otherwise use the original wording.
- keywords_raw must be copied as written in the section, including abbreviations
  and exact identifiers. Do not normalize or merge synonyms in map.
- tier=inline-value only when the section literally contains the precise value
  such as a number, code, error code, URL, or table cell. Copy exact values into
  fact_value.
- If the section only says the value lives elsewhere, use tier=pointer-only and
  set pointer_to. Do not fabricate a value.
- Conceptual definitions, roles, and relationships are tier=narrative.
- Keep plugin, API, error, and parameter names intact; do not translate them.
- questions_en/questions_zh should each contain 3-7 questions the section fully
  answers, including at least one keyword-style query and one natural sentence.
- confidence is 0..1; lower it for ambiguous extraction."""

PAGE_SUMMARY_SYSTEM = """task: card_map_page_summary
Summarize how all sections on one Confluence page relate. Return STRICT JSON
with summary_en, summary_zh, cross_questions_en, and cross_questions_zh.

Rules:
- The summary should explain cross-section relationships, not repeat every
  section verbatim.
- Write 2-4 cross-cutting questions that the whole page answers.
- Keep exact component names, identifiers, and parameter names unchanged.
- Do not introduce topics absent from the supplied mapped sections."""

MAP_SECTION_SCHEMA = {
    "type": "object",
    "required": [
        "anchor", "heading_path", "concepts", "keywords_raw", "info_type", "tier",
        "fact_value", "pointer_to", "has_table", "has_image", "summary_en",
        "summary_zh", "questions_en", "questions_zh", "confidence",
    ],
}

PAGE_SUMMARY_SCHEMA = {
    "type": "object",
    "required": ["summary_en", "summary_zh", "cross_questions_en", "cross_questions_zh"],
}

URL_RE = re.compile(r"https?://[^\s()<>]+")
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
TOKEN_RE = re.compile(r"[A-Za-z0-9_#./:-]+")
DURATION_RE = re.compile(r"\d+(?:\s*(?:s|sec|secs|min|mins|hr|hrs|hour|hours|day|days|d))?", re.IGNORECASE)
POINTER_RE = re.compile(r"(?:refer to|see(?:\s+in)?|details? (?:in|refer to)|configured in|maintained in|available in)\s+(.+)", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Service: structured sections -> deterministic; prose sections -> LLM port
# ---------------------------------------------------------------------------

class MapperService:
    def __init__(self, outputs_dir: Path, llm: LLM):
        self.outputs_dir = outputs_dir
        self.llm = llm

    def run(self) -> Dict[str, int]:
        map_dir = clean_dir(self.outputs_dir / "map")
        refs_files = sorted((self.outputs_dir / "refs").glob("refs_*.json"))
        pages = 0
        sections = 0
        for path in refs_files:
            refs = read_json(path)
            if not refs:
                continue
            page_map = self._map_page(refs)
            validate_map_page(page_map)
            write_json(map_dir / f"map_{page_map['page_id']}.json", page_map)
            pages += 1
            sections += len(page_map["sections"])
        return {"pages": pages, "sections": sections}

    def _map_page(self, refs: List[Dict]) -> Dict:
        first = refs[0]
        mapped_sections = [self._map_section(section) for section in refs]
        structured = sum(1 for section in refs if section.get("metadata"))
        if structured > max(1, len(refs) // 2):
            page_summary = build_page_summary(first, mapped_sections)
        else:
            page_summary = self.llm.complete_json(
                PAGE_SUMMARY_SYSTEM,
                json.dumps(
                    {"title": first["title"], "tree_path": first["tree_path"], "sections": mapped_sections},
                    ensure_ascii=False,
                ),
                schema=PAGE_SUMMARY_SCHEMA,
            )
        return {
            "page_id": first["page_id"],
            "source_url": first["source_url"],
            "title": first["title"],
            "space": first["space"],
            "tree_path": first["tree_path"],
            "owner": first["owner"],
            "labels": first["labels"],
            "confluence_version": first["confluence_version"],
            "update_at": first["update_at"],
            "captured_at": first["captured_at"],
            "page_summary": page_summary,
            "sections": mapped_sections,
        }

    def _map_section(self, section: Dict) -> Dict:
        if section.get("metadata"):
            payload = build_structured_section_map(section)
        else:
            payload = self.llm.complete_json(
                MAP_SECTION_SYSTEM,
                json.dumps(section, ensure_ascii=False),
                schema=MAP_SECTION_SCHEMA,
            )
            payload = _finalise_prose_payload(payload, section)
        return payload


# ---------------------------------------------------------------------------
# Deterministic extraction for structured (cell / record / process / qa) sections
# ---------------------------------------------------------------------------

def build_structured_section_map(section: Dict) -> Dict:
    metadata = dict(section.get("metadata") or {})
    inline_values = extract_inline_values(section)
    pointer_target = "" if inline_values else extract_pointer_target(section)
    if inline_values:
        tier = "inline-value"
    elif pointer_target:
        tier = "pointer-only"
    else:
        tier = "narrative"
    return {
        "section_id": section.get("section_id", ""),
        "metadata": metadata,
        "anchor": " > ".join(section.get("heading_path", [])),
        "heading_path": section.get("heading_path", []),
        "concepts": topic_terms(section),
        "keywords_raw": keyword_terms(section),
        "info_type": infer_info_type(section, metadata),
        "tier": tier,
        "fact_value": "; ".join(inline_values) if inline_values else None,
        "fact_values": inline_values,
        "pointer_to": pointer_target or None,
        "has_table": bool(section.get("has_table", False)),
        "has_image": bool(section.get("has_image", False)),
        "summary_en": summarize_structured_body(section, metadata),
        "summary_zh": summarize_structured_body(section, metadata),
        "questions_en": build_questions(section, "en"),
        "questions_zh": build_questions(section, "zh"),
        "confidence": 0.95 if (inline_values or pointer_target) else 0.82,
    }


def _finalise_prose_payload(payload: Dict, section: Dict) -> Dict:
    payload.setdefault("anchor", " > ".join(section.get("heading_path", [])))
    payload.setdefault("heading_path", section.get("heading_path", []))
    payload.setdefault("has_table", bool(section.get("has_table", False)))
    payload.setdefault("has_image", bool(section.get("has_image", False)))
    payload["section_id"] = section.get("section_id", "")
    payload["metadata"] = dict(section.get("metadata") or {})
    payload["concepts"] = dedupe(payload.get("concepts") or topic_terms(section))
    payload["keywords_raw"] = dedupe(payload.get("keywords_raw") or keyword_terms(section))
    payload.setdefault("questions_en", build_questions(section, "en"))
    payload.setdefault("questions_zh", build_questions(section, "zh"))
    payload.setdefault("fact_values", [payload["fact_value"]] if payload.get("fact_value") else [])
    return payload


def topic_terms(section: Dict) -> List[str]:
    metadata = section.get("metadata") or {}
    items = [str(metadata.get(key) or "").strip() for key in ("row_key", "channel", "attribute", "question")]
    items = [item for item in items if item]
    if not items:
        items.append(_leaf(section))
    return dedupe(items)


def keyword_terms(section: Dict) -> List[str]:
    metadata = section.get("metadata") or {}
    items = [str(metadata.get(key) or "").strip() for key in ("channel", "row_key", "attribute", "question", "environment")]
    items = [item for item in items if item]
    items.extend(extract_inline_values(section)[:6])
    if not items:
        items.append(_leaf(section))
    return dedupe(items)


def build_questions(section: Dict, language: str) -> List[str]:
    metadata = section.get("metadata") or {}
    entity = str(metadata.get("row_key") or metadata.get("channel") or "").strip()
    attribute = str(metadata.get("attribute") or "").strip()
    question = str(metadata.get("question") or "").strip()
    items: List[str] = []
    if entity and attribute:
        items.append(f"{entity} 的 {attribute} 是什么？" if language == "zh" else f"What is the {attribute} for {entity}?")
    if question:
        items.append(f"{question} 是什么？" if language == "zh" else question)
    if not items:
        leaf = _leaf(section)
        items.append(f"{leaf} 是什么？" if language == "zh" else f"What is {leaf}?")
    return items[:7]


def infer_info_type(section: Dict, metadata: Dict) -> str:
    if metadata.get("block") == "process":
        return "how-to"
    if metadata.get("question") or metadata.get("attribute"):
        return "reference"
    return str(section.get("content_type") or "what-is")


def summarize_structured_body(section: Dict, metadata: Dict) -> str:
    label = str(metadata.get("attribute") or metadata.get("row_key") or metadata.get("question") or "").strip()
    body = str(section.get("body_md") or "").strip()
    first_line = next((line.strip() for line in body.splitlines() if line.strip()), body)
    first_line = _strip_label_echo(first_line, metadata)
    return f"{label}: {first_line}" if label and first_line and label.lower() not in first_line.lower() else (first_line or body)


def _strip_label_echo(text: str, metadata: Dict) -> str:
    cleaned = str(text or "").strip()
    candidates = [str(metadata.get(key) or "").strip() for key in ("question", "row_key", "attribute") if metadata.get(key)]
    for candidate in candidates:
        cleaned = re.sub(rf"^(?:Q\s*[:：])?\s*{re.escape(candidate)}\s*[:：\-]\s*", "", cleaned, flags=re.IGNORECASE).strip()
    return cleaned


# ---------------------------------------------------------------------------
# Inline-value / pointer extraction (atomic precise values only)
# ---------------------------------------------------------------------------

def extract_inline_values(section: Dict) -> List[str]:
    body = str(section.get("body_md") or "").strip()
    if not body:
        return []
    metadata = section.get("metadata") or {}
    emails = [normalize_email(m.group(0)) for m in EMAIL_RE.finditer(body)]
    urls = [normalize_artifact(m.group(0)) for m in URL_RE.finditer(body)]
    urls = [u for u in urls if should_keep_url(u, emails)]

    values: List[str] = list(urls) + list(emails)

    lines = [line.strip().lstrip("-*+ ").strip() for line in body.splitlines() if line.strip()]
    if metadata.get("table_kind") == "record":
        for line in lines:
            if ":" in line:
                value = line.split(":", 1)[1].strip()
                if value and is_atomic_inline_value(value):
                    values.append(normalize_artifact(value))
    elif metadata.get("table_kind") == "matrix" and is_atomic_inline_value(body):
        values.append(normalize_artifact(body))

    return dedupe(v for v in values if is_atomic_inline_value(v))


def extract_pointer_target(section: Dict) -> str:
    body = str(section.get("body_md") or "").strip()
    if URL_RE.search(body):
        return ""
    match = POINTER_RE.search(body)
    if not match:
        return ""
    return match.group(1).strip().rstrip(".").strip()


def is_atomic_inline_value(text: str) -> bool:
    """True for a single precise value (url / email / code / number / short token),
    False for sentences or multi-fact prose."""
    value = normalize_artifact(text)
    if not value:
        return False
    if value.startswith("http"):
        return True
    if EMAIL_RE.fullmatch(value):
        return True
    if TOKEN_RE.fullmatch(value):  # identifier / code / #tag / slash-list, no spaces
        return True
    if DURATION_RE.fullmatch(value):
        return True
    if any(marker in value for marker in (". ", "! ", "? ", "。", "；")):
        return False
    words = re.findall(r"\S+", value)
    if not words or len(words) > 8:
        return False
    if len(words) > 4 and any(m in value.lower() for m in (",", " and ", " or ", "、")):
        return False
    return True


def normalize_artifact(text: str) -> str:
    value = str(text).strip().strip("`\"'")
    # "<url> (<url>)" duplicate (Confluence auto-link) -> keep one
    dup = re.fullmatch(r"(https?://\S+?)\s*\((https?://\S+)\)", value)
    if dup and dup.group(1).rstrip("/") == dup.group(2).rstrip("/"):
        value = dup.group(1)
    if value.startswith("http"):
        value = value.rstrip(".,;:")
    return value.strip()


def normalize_email(text: str) -> str:
    return re.sub(r"\s+", "", str(text).strip())


def should_keep_url(url: str, emails: List[str]) -> bool:
    """Drop a bare-domain URL that is really an auto-linked email domain
    (e.g. 'http://hsbc.com' produced from 'eric.q.yuan@hsbc.com')."""
    cleaned = normalize_artifact(url)
    if not cleaned:
        return False
    host = (urlparse(cleaned).hostname or "").lower()
    path = (urlparse(cleaned).path or "").strip("/")
    if emails and host and not path:
        email_domains = {e.split("@", 1)[-1].lower() for e in emails if "@" in e}
        if host in email_domains:
            return False
    return True


# ---------------------------------------------------------------------------
# Generic page summary (derived from the data, no page-specific wording)
# ---------------------------------------------------------------------------

def build_page_summary(first: Dict, mapped_sections: List[Dict]) -> Dict:
    kinds: Counter = Counter()
    entities: List[str] = []
    for section in mapped_sections:
        meta = section.get("metadata") or {}
        kinds[meta.get("table_kind") or meta.get("block") or "narrative"] += 1
        entity = meta.get("row_key") or meta.get("channel") or meta.get("question") or _leaf(section)
        if entity:
            entities.append(str(entity))
    entities = dedupe(entities)[:8]
    title = first["title"]

    labels_en = {"matrix": "matrix facts", "record": "record entries", "process": "process steps", "qa": "Q&A items", "narrative": "narrative sections"}
    labels_zh = {"matrix": "矩阵事实", "record": "记录条目", "process": "流程步骤", "qa": "问答条目", "narrative": "叙述段落"}
    parts_en = [f"{count} {labels_en.get(kind, kind)}" for kind, count in kinds.most_common()]
    parts_zh = [f"{count} 个{labels_zh.get(kind, kind)}" for kind, count in kinds.most_common()]
    desc_en = ", ".join(parts_en) or f"{len(mapped_sections)} sections"
    desc_zh = "、".join(parts_zh) or f"{len(mapped_sections)} 个段落"
    ent_en = f" Key entities: {', '.join(entities)}." if entities else ""
    ent_zh = f" 关键条目：{', '.join(entities)}。" if entities else ""
    return {
        "summary_en": f"{title} captures {desc_en}.{ent_en}",
        "summary_zh": f"{title} 收录了 {desc_zh}。{ent_zh}",
        "cross_questions_en": [f"What does {title} capture?", "How do the entities on this page relate?"],
        "cross_questions_zh": [f"{title} 收录了哪些内容？", "本页各条目之间有什么关系？"],
    }


def _leaf(section: Dict) -> str:
    path = section.get("heading_path") or [section.get("title", "Section")]
    return str(path[-1]) if path else "Section"


def dedupe(items: Iterable[str]) -> List[str]:
    seen = set()
    result: List[str] = []
    for item in items:
        text = str(item).strip()
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(text)
    return result
