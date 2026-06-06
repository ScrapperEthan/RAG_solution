from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List

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
  such as a number, code, error code, or table cell. Copy exact values into
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
- Write 2-4 cross-cutting questions that the whole page answers, especially
  "how do X and Y work together" style questions.
- Keep exact component names, identifiers, and parameter names unchanged.
- Do not introduce topics absent from the supplied mapped sections."""

MAP_SECTION_SCHEMA = {
    "type": "object",
    "required": [
        "anchor",
        "heading_path",
        "concepts",
        "keywords_raw",
        "info_type",
        "tier",
        "fact_value",
        "pointer_to",
        "has_table",
        "has_image",
        "summary_en",
        "summary_zh",
        "questions_en",
        "questions_zh",
        "confidence",
    ],
}

PAGE_SUMMARY_SCHEMA = {
    "type": "object",
    "required": ["summary_en", "summary_zh", "cross_questions_en", "cross_questions_zh"],
}


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
        page_summary = self.llm.complete_json(
            PAGE_SUMMARY_SYSTEM,
            json.dumps(
                {
                    "title": first["title"],
                    "tree_path": first["tree_path"],
                    "sections": mapped_sections,
                },
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
        return self.llm.complete_json(
            MAP_SECTION_SYSTEM,
            json.dumps(section, ensure_ascii=False),
            schema=MAP_SECTION_SCHEMA,
        )
