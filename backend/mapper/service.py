from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List

from backend.ports import LLM
from backend.schemas.validation import validate_map_page
from backend.util import clean_dir, read_json, write_json


MAP_SECTION_SYSTEM = """task: card_map_section
Extract one Confluence section into the card-map JSON fields. Be faithful to the
section text, keep keywords verbatim, and only set inline-value when the exact
value is present in the section."""

PAGE_SUMMARY_SYSTEM = """task: card_map_page_summary
Summarize how the page sections relate and return bilingual summary fields plus
cross-cutting questions."""

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
