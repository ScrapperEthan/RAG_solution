from __future__ import annotations

import json
import re
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple

from backend.ports import LLM
from backend.reducer.canonicals import canonical_id_in_text, load_vocabulary, render_registry_markdown
from backend.schemas.validation import validate_card, validate_inverted_row, validate_review_item
from backend.util import clean_dir, read_json, write_json, write_jsonl


REDUCE_NORMALIZE_SYSTEM = """task: card_reduce_normalize_section
You are normalizing keyword variants into canonical concepts for a knowledge
base. Given one extracted section and already-approved canonical concepts,
return STRICT JSON.

Return:
{
  "canonical_ids": [string],
  "needs_review": [{"raw": string, "reason": string}]
}

Rules:
- Only use the supplied approved canonical concepts. Do not discover or create
  new topics; unmatched content must go to needs_review for the upstream owner.
- Map the section only to existing canonical_id values when the concept is the
  section's main subject, not a passing mention.
- If a term appears only as a cross-reference such as "see X" or "refer to X",
  do not assign ownership to X; leave it for soft_links.
- Match using heading_path, concepts, and the section's primary keywords. Do not
  use "mentioned anywhere" as sufficient evidence.
- Use each topic's boundary to reject ambiguous or out-of-scope matches.
- Ambiguous keywords must go to needs_review instead of being forced into a
  canonical.
- Do not invent concepts absent from the supplied section."""

REDUCE_NORMALIZE_SCHEMA = {"type": "object", "required": ["canonical_ids"]}

ALIAS_RESOLVE_SYSTEM = """task: card_reduce_resolve_aliases
Generate candidate aliases for ONE approved topic that currently has no aliases.
Return STRICT JSON: {"aliases": [string]}.

Rules:
- Candidates are for human review only; do not change the approved keyword table.
- Include common abbreviations, spelling variants, and established full forms.
- Do not include broader, narrower, or merely related concepts."""

ALIAS_RESOLVE_SCHEMA = {"type": "object", "required": ["aliases"]}


class ReducerService:
    def __init__(self, outputs_dir: Path, llm: LLM, keyword_table: Path, resolve_aliases: bool = False):
        self.outputs_dir = outputs_dir
        self.llm = llm
        self.keyword_table = keyword_table
        self.resolve_aliases = resolve_aliases

    def run(self) -> Dict[str, int]:
        cards_dir = clean_dir(self.outputs_dir / "cards")
        map_files = sorted((self.outputs_dir / "map").glob("map_*.json"))
        sections = self._load_sections(map_files)
        canonicals = load_vocabulary(self.keyword_table)
        grouped: Dict[str, List[Dict]] = {}
        inverted_rows: List[Dict] = []
        review_queue: List[Dict] = self._alias_review_items(canonicals) if self.resolve_aliases else []

        for section in sections:
            cids, needs_review = self._normalize_section(section, canonicals)
            for item in needs_review:
                review_queue.append(needs_review_item(item, section))
            if not cids:
                review_queue.append(unmatched_review_item(section))
                continue
            for cid in cids:
                grouped.setdefault(cid, []).append(section)
                inverted_rows.append(inverted_row(cid, section, canonicals))

        cards: List[Dict] = []
        for cid, group in grouped.items():
            card, queue_items = build_card(cid, group, canonicals)
            validate_card(card)
            cards.append(card)
            review_queue.extend(queue_items)
            filename = safe_filename(card["canonical_name"]) + ".json"
            write_json(cards_dir / filename, card)

        review_queue.extend(global_review_items(sections, canonicals))
        deduped_inverted = dedupe_inverted(inverted_rows)
        for row in deduped_inverted:
            validate_inverted_row(row)
        for item in review_queue:
            validate_review_item(item)
        write_jsonl(self.outputs_dir / "inverted_index.jsonl", deduped_inverted)
        write_jsonl(self.outputs_dir / "review_queue.jsonl", review_queue)
        (self.outputs_dir / "canonical_keywords.md").write_text(render_registry_markdown(canonicals), encoding="utf-8")
        write_json(self.outputs_dir / "cards_index.json", cards)
        return {"cards": len(cards), "inverted_rows": len(inverted_rows), "review_queue": len(review_queue)}

    def _load_sections(self, map_files: List[Path]) -> List[Dict]:
        sections: List[Dict] = []
        for path in map_files:
            page = read_json(path)
            for section in page["sections"]:
                enriched = dict(section)
                enriched.update(
                    {
                        "page_id": page["page_id"],
                        "title": page["title"],
                        "source_url": page["source_url"],
                        "confluence_version": page["confluence_version"],
                        "update_at": page["update_at"],
                    }
                )
                sections.append(enriched)
        return sections

    def _normalize_section(self, section: Dict, canonicals: Dict[str, Dict]) -> Tuple[List[str], List[Dict]]:
        response = self.llm.complete_json(
            REDUCE_NORMALIZE_SYSTEM,
            json.dumps(
                {
                    "approved_canonicals": list(canonicals.values()),
                    "section": section,
                },
                ensure_ascii=False,
            ),
            schema=REDUCE_NORMALIZE_SCHEMA,
        )
        ids = response.get("canonical_ids", [])
        if not isinstance(ids, list):
            raise ValueError("card_reduce_normalize_section must return canonical_ids as a list")
        unknown = [cid for cid in ids if cid not in canonicals]
        if unknown:
            raise ValueError(f"Unknown canonical_ids returned by LLM: {unknown}")
        needs_review = response.get("needs_review") or []
        return dedupe_strings(ids), needs_review

    def _alias_review_items(self, canonicals: Dict[str, Dict]) -> List[Dict]:
        items = []
        for cid, canonical in canonicals.items():
            if canonical.get("aliases"):
                continue
            response = self.llm.complete_json(
                ALIAS_RESOLVE_SYSTEM,
                json.dumps(canonical, ensure_ascii=False),
                schema=ALIAS_RESOLVE_SCHEMA,
            )
            aliases = response.get("aliases") or []
            if not isinstance(aliases, list):
                aliases = []
            items.append(alias_review_item(cid, canonical, dedupe_strings([str(alias) for alias in aliases])))
        return items


def build_card(cid: str, sections: List[Dict], canonicals: Dict[str, Dict]) -> Tuple[Dict, List[Dict]]:
    canonical = canonicals[cid]
    fields: List[Dict] = []
    queue: List[Dict] = []

    narrative_sections = [s for s in sections if s["tier"] == "narrative"]
    config_sections = [s for s in sections if s["info_type"] == "config" and s["fact_value"]]
    troubleshoot_sections = [s for s in sections if s["info_type"] == "troubleshoot"]
    pointer_sections = [s for s in sections if s["tier"] == "pointer-only"]

    if narrative_sections:
        fields.append(
            {
                "field": "definition",
                "tier": "narrative",
                "value": synthesize_narrative(canonical["canonical_name"], narrative_sections),
                "sources": sources(narrative_sections),
            }
        )

    if config_sections:
        field, conflicts = merge_config_field(config_sections)
        fields.append(field)
        for conflict in conflicts:
            queue.append(
                {
                    "queue_id": f"RQ-conflict-{cid}-{len(queue)+1:03d}",
                    "type": "conflict",
                    "canonical_id": cid,
                    "field": "config",
                    "detail": conflict["detail"],
                    "options": conflict["options"],
                    "status": "open",
                }
            )

    if pointer_sections:
        for item in pointer_sections:
            fields.append(
                {
                    "field": pointer_field_name(item),
                    "tier": "pointer-only",
                    "value": None,
                    "pointer_to": item["pointer_to"],
                    "sources": sources([item]),
                }
            )

    if troubleshoot_sections:
        exact_values = [s["fact_value"] for s in troubleshoot_sections if s["fact_value"]]
        narrative_values = [s["summary_en"] for s in troubleshoot_sections if not s["fact_value"] and s.get("summary_en")]
        if exact_values:
            exact_sections = [s for s in troubleshoot_sections if s["fact_value"]]
            fields.append(
                {
                    "field": "troubleshoot",
                    "tier": "inline-value",
                    "value": "; ".join(exact_values),
                    "sources": sources(exact_sections),
                }
            )
        if narrative_values:
            narrative_sections = [s for s in troubleshoot_sections if not s["fact_value"]]
            fields.append(
                {
                    "field": "troubleshoot_notes" if exact_values else "troubleshoot",
                    "tier": "narrative",
                    "value": " ".join(narrative_values),
                    "sources": sources(narrative_sections),
                }
            )

    related = related_components(cid, sections, canonicals)
    if related:
        fields.append(
            {
                "field": "related_components",
                "tier": "narrative",
                "value": related["value"],
                "soft_links": related["soft_links"],
                "sources": sources(related["sections"]),
            }
        )

    flags: List[str] = []
    if "DMP" in " ".join(k for s in sections for k in s.get("keywords_raw", [])):
        flags.append("alias 'DMP' should remain auditable in Business review")
    if any(item["type"] == "conflict" for item in queue):
        flags.append("config field has version/update conflict")
    if "otp" in canonical["canonical_name"].lower():
        flags.append("OTP may be ambiguous outside MDC OTP context")

    if not fields:
        fields.append(
            {
                "field": "catch_all",
                "tier": "narrative",
                "value": f"Collected references for {canonical['canonical_name']}.",
                "sources": sources(sections),
            }
        )

    return (
        {
            "canonical_id": cid,
            "canonical_name": canonical["canonical_name"],
            "aliases": canonical["aliases"],
            "module": canonical["module"],
            "boundary": canonical.get("boundary", ""),
            "topic_type": canonical.get("topic_type", ""),
            "status": canonical["status"],
            "fields": fields,
            "flags": flags,
        },
        queue,
    )


def merge_config_field(sections: List[Dict]) -> Tuple[Dict, List[Dict]]:
    facts: Dict[str, List[Dict]] = {}
    for section in sections:
        for part in (section["fact_value"] or "").split(";"):
            if ":" not in part:
                continue
            name, value = part.split(":", 1)
            facts.setdefault(name.strip(), []).append({"value": value.strip(), "section": section})

    chosen_parts: List[str] = []
    chosen_sources: List[Dict] = []
    conflict_details: List[Dict] = []
    queue_conflicts: List[Dict] = []
    for name, candidates in facts.items():
        candidates.sort(
            key=lambda c: (
                parse_update_at(c["section"].get("update_at", "")),
                int(c["section"].get("confluence_version") or 0),
            ),
            reverse=True,
        )
        chosen = candidates[0]
        chosen_parts.append(f"{name}: {chosen['value']}")
        chosen_sources.append(chosen["section"])
        unique_values = sorted({candidate["value"] for candidate in candidates})
        if len(unique_values) > 1:
            conflict_detail = [
                {
                    "value": f"{name}: {candidate['value']}",
                    "page_id": candidate["section"]["page_id"],
                    "confluence_version": candidate["section"]["confluence_version"],
                    "update_at": candidate["section"]["update_at"],
                }
                for candidate in candidates
            ]
            conflict_details.extend(conflict_detail)
            queue_conflicts.append(
                {
                    "detail": f"{name} conflict; temporarily chose newest value {chosen['value']}.",
                    "options": [entry["value"] + f" ({entry['page_id']})" for entry in conflict_detail],
                }
            )

    field = {
        "field": "config",
        "tier": "inline-value",
        "value": "; ".join(chosen_parts),
        "authoritative": True,
        "conflict": bool(conflict_details),
        "conflict_detail": conflict_details,
        "sources": sources(chosen_sources),
    }
    return field, queue_conflicts


def synthesize_narrative(name: str, sections: List[Dict]) -> str:
    selected = []
    for section in sections[:4]:
        selected.append(section["summary_zh"])
    return f"{name}: " + " ".join(selected)


def related_components(cid: str, sections: List[Dict], canonicals: Dict[str, Dict]) -> Dict:
    text = " ".join(s["anchor"] + " " + " ".join(s.get("keywords_raw", [])) for s in sections).lower()
    links = [
        other_cid
        for other_cid in canonicals
        if other_cid != cid and canonical_id_in_text(text, {other_cid: canonicals[other_cid]})
    ]
    if not links:
        return {}
    names = [canonicals[link]["canonical_name"] for link in links if link in canonicals]
    return {"value": "Related to " + ", ".join(names) + ".", "soft_links": links, "sections": sections}


def pointer_field_name(section: Dict) -> str:
    pointer = (section.get("pointer_to") or "").lower()
    if "configuration" in pointer:
        return "config_pointer"
    return "pointer"


def sources(sections: List[Dict]) -> List[Dict]:
    rows: List[Dict] = []
    for section in sections:
        rows.append(
            {
                "page_id": section["page_id"],
                "anchor": section["anchor"],
                "source_url": section["source_url"],
                "confluence_version": section["confluence_version"],
            }
        )
    return dedupe_sources(rows)


def inverted_row(cid: str, section: Dict, canonicals: Dict[str, Dict]) -> Dict:
    canonical = canonicals[cid]
    return {
        "canonical_id": cid,
        "canonical_name": canonical["canonical_name"],
        "module": canonical["module"],
        "page_id": section["page_id"],
        "anchor": section["anchor"],
        "section_id": f"{section['page_id']}#{section['heading_path'][-1]}",
        "info_type": section["info_type"],
        "tier": section["tier"],
        "confidence": section["confidence"],
        "confluence_version": section["confluence_version"],
    }


def global_review_items(sections: List[Dict], canonicals: Dict[str, Dict]) -> List[Dict]:
    items: List[Dict] = []
    all_keywords = " ".join(k for section in sections for k in section.get("keywords_raw", []))
    if "DMP" in all_keywords:
        cid = canonical_id_in_text("DMP", canonicals) or ""
        items.append(
            {
                "queue_id": "RQ-0011",
                "type": "alias-confirmation",
                "canonical_id": cid,
                "field": "aliases",
                "detail": "Confirm whether DMP should be treated as an alias of DM Plugin in this slice.",
                "options": ["yes", "no"],
                "status": "open",
            }
        )
    if re.search(r"\bOTP\b", all_keywords) or "otp_length" in all_keywords:
        cid = canonical_id_in_text("MDC OTP Service", canonicals) or canonical_id_in_text("OTP", canonicals) or ""
        items.append(
            {
                "queue_id": "RQ-0019",
                "type": "ambiguity",
                "canonical_id": cid,
                "field": "aliases",
                "detail": "OTP may mean MDC OTP Service or generic one-time password; confirm usage.",
                "options": ["MDC OTP Service", "generic OTP / split"],
                "status": "open",
            }
        )
    for section in sections:
        if section["confidence"] < 0.6:
            items.append(
                {
                    "queue_id": f"RQ-lowconf-{section['page_id']}",
                    "type": "low-confidence",
                    "canonical_id": "",
                    "field": "",
                    "detail": f"Low confidence extraction at {section['anchor']}",
                    "options": [],
                    "status": "open",
                }
            )
    return items


def dedupe_inverted(rows: List[Dict]) -> List[Dict]:
    seen = set()
    result = []
    for row in rows:
        key = (row["canonical_id"], row["page_id"], row["anchor"])
        if key not in seen:
            seen.add(key)
            result.append(row)
    return result


def dedupe_sources(rows: List[Dict]) -> List[Dict]:
    seen = set()
    result = []
    for row in rows:
        key = (row["page_id"], row["anchor"])
        if key not in seen:
            seen.add(key)
            result.append(row)
    return result


def dedupe_strings(items: List[str]) -> List[str]:
    seen = set()
    result = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


def needs_review_item(item: Dict, section: Dict) -> Dict:
    raw = str(item.get("raw") or section.get("anchor", ""))
    reason = str(item.get("reason") or "LLM marked this normalization as ambiguous.")
    return {
        "queue_id": f"RQ-normalize-{stable_short(raw + section['anchor'])}",
        "type": "normalization-review",
        "canonical_id": "",
        "field": "canonical_keywords",
        "detail": f"{raw}: {reason}",
        "options": [],
        "status": "open",
    }


def unmatched_review_item(section: Dict) -> Dict:
    return {
        "queue_id": f"RQ-unmatched-{stable_short(section['anchor'])}",
        "type": "unmatched-section",
        "canonical_id": "",
        "field": "association",
        "detail": f"No approved canonical could be assigned to {section['anchor']}; report it to the upstream keyword-table owner.",
        "options": section.get("keywords_raw", []),
        "status": "open",
    }


def stable_short(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:8]


def alias_review_item(cid: str, canonical: Dict, aliases: List[str]) -> Dict:
    return {
        "queue_id": f"RQ-aliases-{cid}",
        "type": "alias-resolution-request",
        "canonical_id": cid,
        "field": "aliases",
        "detail": f"Review candidate aliases for approved topic '{canonical['canonical_name']}' before updating the upstream keyword table.",
        "options": aliases,
        "status": "open",
    }


def parse_update_at(value: str) -> datetime:
    if not value:
        return datetime.min.replace(tzinfo=timezone.utc)
    text = str(value).strip()
    candidates = [text]
    if text.endswith("Z"):
        candidates.append(text[:-1] + "+00:00")
    if " " in text and "T" not in text:
        candidates.append(text.replace(" ", "T"))
    for candidate in candidates:
        try:
            parsed = datetime.fromisoformat(candidate)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except ValueError:
            continue
    for fmt in ("%Y/%m/%d %H:%M:%S", "%Y/%m/%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return datetime.min.replace(tzinfo=timezone.utc)


def safe_filename(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "_", name).strip("_")
