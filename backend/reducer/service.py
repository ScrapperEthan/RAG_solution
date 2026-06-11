from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from backend.ports import LLM
from backend.reducer.canonicals import (
    canonical_id_in_text,
    canonical_ids_for,
    canonical_terms,
    load_vocabulary,
    normalize_term,
    render_registry_markdown,
)
from backend.schemas.validation import validate_card, validate_inverted_row, validate_review_item
from backend.util import clean_dir, read_json, write_json, write_jsonl
from backend.util import section_id as compute_section_id


TIERS = {"narrative", "inline-value", "pointer-only"}


class ReducerService:
    """Match-only reducer: section -> approved canonical (no discovery, no C-AUTO).

    Builds one card per matched canonical with metadata-routed subsections and
    grounded fields. Unmatched sections go to the review queue.
    """

    def __init__(self, outputs_dir: Path, llm: LLM, keyword_table: Path, resolve_aliases: bool = False):
        self.outputs_dir = outputs_dir
        self.llm = llm
        self.keyword_table = keyword_table
        self.resolve_aliases = resolve_aliases

    def run(self) -> Dict[str, int]:
        if not self.keyword_table.exists():
            raise FileNotFoundError(
                f"Approved keyword table not found: {self.keyword_table}. "
                "Please run discover and freeze the keyword table first."
            )
        cards_dir = clean_dir(self.outputs_dir / "cards")
        sections = self._load_sections(sorted((self.outputs_dir / "map").glob("map_*.json")))
        canonicals = load_vocabulary(self.keyword_table)

        grouped: Dict[str, List[Dict]] = {}
        inverted_rows: List[Dict] = []
        review_queue: List[Dict] = []

        for section in sections:
            cids = match_section(section, canonicals)
            if not cids:
                review_queue.append(unmatched_review_item(section))
                continue
            for cid in cids:
                grouped.setdefault(cid, []).append(section)
                inverted_rows.append(inverted_row(cid, section, canonicals))

        cards: List[Dict] = []
        for cid, group in grouped.items():
            card, conflicts = build_card(cid, group, canonicals)
            validate_card(card)
            cards.append(card)
            review_queue.extend(conflicts)
            write_json(cards_dir / f"{safe_filename(card['canonical_name'])}.json", card)

        review_queue.extend(low_confidence_items(sections))
        deduped = dedupe_inverted(inverted_rows)
        for row in deduped:
            validate_inverted_row(row)
        for item in review_queue:
            validate_review_item(item)
        write_jsonl(self.outputs_dir / "inverted_index.jsonl", deduped)
        write_jsonl(self.outputs_dir / "review_queue.jsonl", review_queue)
        (self.outputs_dir / "canonical_keywords.md").write_text(render_registry_markdown(canonicals), encoding="utf-8")
        write_json(self.outputs_dir / "cards_index.json", cards)
        return {"cards": len(cards), "inverted_rows": len(deduped), "review_queue": len(review_queue)}

    def _load_sections(self, map_files: List[Path]) -> List[Dict]:
        # map sections carry the extraction result but not the original body_md;
        # subsection narrative facts need it, so re-attach it from refs by section_id.
        ref_lookup = load_ref_lookup(self.outputs_dir / "refs.json")
        sections: List[Dict] = []
        for path in map_files:
            page = read_json(path)
            for section in page["sections"]:
                enriched = dict(section)
                sid = str(section.get("section_id") or compute_section_id(str(page["page_id"]), section.get("heading_path") or []))
                ref = ref_lookup.get(sid, {})
                enriched.update(
                    {
                        "page_id": page["page_id"],
                        "title": page["title"],
                        "source_url": page["source_url"],
                        "confluence_version": page["confluence_version"],
                        "update_at": page["update_at"],
                        "section_id": sid,
                        "body_md": ref.get("body_md", section.get("body_md", "")),
                        "metadata": dict(section.get("metadata") or {}),
                        "fact_values": list(section.get("fact_values") or []),
                    }
                )
                sections.append(enriched)
        return sections


# ---------------------------------------------------------------------------
# Matching: deterministic metadata routing, then heading-path fallback
# ---------------------------------------------------------------------------

def match_section(section: Dict, canonicals: Dict[str, Dict]) -> List[str]:
    deterministic = canonical_ids_from_metadata(section, canonicals)
    if deterministic:
        return deterministic
    return dedupe_strings(canonical_ids_for(section, canonicals))


def canonical_ids_from_metadata(section: Dict, canonicals: Dict[str, Dict]) -> List[str]:
    """Route a structured cell to BOTH its row topic and its column topic.

    A matrix cell (e.g. channel=PN, attribute="Template Maintenance") is evidence
    for the row/inventory topic whose subsection is that channel AND for the
    column topic whose name/alias is that attribute. The old winner-take-all
    scoring kept only the higher-scoring channel topic, which starved every
    attribute-defined topic (it never received a single cell -> no card).
    """
    metadata = section.get("metadata") or {}
    row_terms = [normalize_term(str(metadata.get(k) or "")) for k in ("channel", "row_key")]
    row_terms = [t for t in row_terms if t]
    column_text = " ".join(str(metadata.get(k) or "") for k in ("attribute", "question")).strip()

    ids: List[str] = []
    for cid, canonical in canonicals.items():
        sub_terms = [normalize_term(item) for item in canonical.get("subsections", []) if str(item).strip()]
        # row topic: this cell's row key is one of the canonical's subsections
        if any(term in sub_terms for term in row_terms):
            ids.append(cid)
            continue
        # column topic: the canonical's name/alias matches this cell's attribute/question
        if column_text and canonical_id_in_text(column_text, {cid: canonical}):
            ids.append(cid)
    return dedupe_strings(ids)


# ---------------------------------------------------------------------------
# Card assembly
# ---------------------------------------------------------------------------

def build_card(cid: str, sections: List[Dict], canonicals: Dict[str, Dict]) -> Tuple[Dict, List[Dict]]:
    canonical = canonicals[cid]
    topic_class = canonical.get("topic_class") or infer_topic_class(canonical)
    evidence = aggregate_evidence(sections)
    subsections = build_subsections(canonical, sections)

    fields: List[Dict] = []
    queue: List[Dict] = []

    definition = synthesize_definition(canonical, subsections)
    if definition:
        fields.append(narrative_field("definition", definition, sections, evidence))

    overview = synthesize_overview(canonical, subsections)
    if overview and overview != definition:
        fields.append(narrative_field("overview", overview, sections, evidence))

    config_sections = [s for s in sections if s.get("info_type") == "config" and s.get("fact_values")]
    if config_sections:
        config_field, conflicts = merge_config_field(config_sections, evidence)
        fields.append(config_field)
        for conflict in conflicts:
            queue.append(conflict_item(cid, conflict, len(queue) + 1))

    troubleshoot = build_troubleshoot_field(sections, evidence)
    if troubleshoot:
        fields.append(troubleshoot)

    for pointer in pointer_fields(sections):
        fields.append(pointer)

    related = related_components_field(cid, sections, canonicals, evidence)
    if related:
        fields.append(related)

    fields = [f for f in fields if _has_content(f)]

    flags: List[str] = []
    if any(item["type"] == "conflict" for item in queue):
        flags.append("config field has a version/date conflict")

    card = {
        "canonical_id": cid,
        "canonical_name": canonical["canonical_name"],
        "topic_class": topic_class,
        "aliases": canonical.get("aliases", []),
        "module": canonical.get("module", []),
        "boundary": canonical.get("boundary", ""),
        "topic_type": canonical.get("topic_type", ""),
        "status": canonical.get("status", "approved"),
        "keywords_raw_agg": evidence["keywords_raw_agg"],
        "concepts_agg": evidence["concepts_agg"],
        "questions_agg_en": evidence["questions_en_agg"],
        "questions_agg_zh": evidence["questions_zh_agg"],
        "source_section_ids": evidence["source_section_ids"],
        "subsections": subsections,
        "fields": fields,
        "flags": flags,
    }
    return card, queue


def _has_content(field: Dict) -> bool:
    if field["tier"] == "pointer-only":
        return bool(field.get("pointer_to"))
    return bool(str(field.get("value") or "").strip())


def aggregate_evidence(sections: List[Dict]) -> Dict[str, List[str]]:
    return {
        "keywords_raw_agg": dedupe_strings(k for s in sections for k in s.get("keywords_raw", [])),
        "concepts_agg": dedupe_strings(c for s in sections for c in s.get("concepts", [])),
        "questions_en_agg": dedupe_strings(q for s in sections for q in s.get("questions_en", [])),
        "questions_zh_agg": dedupe_strings(q for s in sections for q in s.get("questions_zh", [])),
        "source_section_ids": dedupe_strings(section_id(s) for s in sections),
    }


# ---------------------------------------------------------------------------
# Subsections: route by metadata, fill with real (cleaned) facts
# ---------------------------------------------------------------------------

def build_subsections(canonical: Dict, sections: List[Dict]) -> List[Dict]:
    names = [str(name).strip() for name in canonical.get("subsections", []) if str(name).strip()]
    rows: List[Dict] = []
    for name in names:
        matched = route_subsection_sections(name, sections)
        facts = build_subsection_facts(matched)
        rows.append(
            {
                "name": name,
                "summary": synthesize_subsection(name, facts),
                "key_points": subsection_key_points(facts),
                "facts": facts,
                "evidence_keywords": dedupe_strings(k for s in matched for k in s.get("keywords_raw", [])),
                "source_section_ids": dedupe_strings(section_id(s) for s in matched),
                "sources": sources(matched),
            }
        )
    return rows


def route_subsection_sections(name: str, sections: List[Dict]) -> List[Dict]:
    target = normalize_term(name)
    matched: List[Dict] = []
    for section in sections:
        metadata = section.get("metadata") or {}
        candidates = [
            normalize_term(str(metadata.get(key) or ""))
            for key in ("channel", "row_key", "attribute", "question", "environment")
        ]
        candidates.append(normalize_term(str(section.get("anchor") or "")))
        candidates = [c for c in candidates if c]
        if any(c == target or c in target or target in c for c in candidates):
            matched.append(section)
    return matched


def build_subsection_facts(sections: List[Dict]) -> List[Dict]:
    facts: List[Dict] = []
    for section in sections:
        if is_heading_only_section(section):
            continue
        metadata = section.get("metadata") or {}
        label = fact_label(section)
        values = list(section.get("fact_values") or [])
        if values:
            for value in values:
                cleaned = clean_inline_value(value)
                if cleaned and not is_junk_value(cleaned):
                    facts.append(make_fact(label, "inline-value", cleaned, section))
            continue
        if section.get("tier") == "pointer-only" and section.get("pointer_to"):
            facts.append(make_fact(label, "pointer-only", "", section, pointer_to=section["pointer_to"]))
            continue
        summary = narrative_fact_value(section)
        if summary and not is_junk_value(summary):
            facts.append(make_fact(label, "narrative", summary, section))
    return dedupe_facts(facts)


def make_fact(label: str, tier: str, value: str, section: Dict, pointer_to: Optional[str] = None) -> Dict:
    return {
        "label": label,
        "tier": tier,
        "value": value if tier != "pointer-only" else None,
        "pointer_to": pointer_to,
        "sources": sources([section]),
        "source_section_ids": [section_id(section)],
    }


def fact_label(section: Dict) -> str:
    metadata = section.get("metadata") or {}
    return str(
        metadata.get("attribute")
        or metadata.get("environment")
        or metadata.get("row_key")
        or metadata.get("question")
        or (f"Step {metadata.get('step')}" if metadata.get("step") else "")
        or (section.get("heading_path") or ["detail"])[-1]
    ).strip() or "detail"


def synthesize_subsection(name: str, facts: List[Dict]) -> str:
    parts = [f"{f['label']}: {f['value']}" for f in facts if f.get("value")]
    parts = dedupe_strings(parts)
    return f"{name}: " + "; ".join(parts[:6]) if parts else f"{name} (no extracted facts)."


def subsection_key_points(facts: List[Dict]) -> List[str]:
    points = [f"{f['label']}: {f['value']}" for f in facts if f.get("value")]
    return dedupe_strings(points)[:8]


# ---------------------------------------------------------------------------
# Card-level fields
# ---------------------------------------------------------------------------

def synthesize_definition(canonical: Dict, subsections: List[Dict]) -> str:
    boundary = clean_narrative_text(canonical.get("boundary", ""))
    if boundary:
        return boundary
    names = [s["name"] for s in subsections]
    if names:
        return f"{canonical['canonical_name']}：涵盖 " + "、".join(names) + "。"
    return ""


def synthesize_overview(canonical: Dict, subsections: List[Dict]) -> str:
    lines: List[str] = []
    for sub in subsections:
        values = [f"{f['label']}: {f['value']}" for f in sub.get("facts", []) if f.get("value")]
        if values:
            lines.append(f"{sub['name']} — " + "; ".join(dedupe_strings(values)[:3]))
    return "\n".join(lines)


def merge_config_field(sections: List[Dict], evidence: Dict) -> Tuple[Dict, List[Dict]]:
    facts: Dict[str, List[Dict]] = {}
    for section in sections:
        for value in section.get("fact_values") or []:
            if ":" not in value:
                continue
            name, raw = value.split(":", 1)
            facts.setdefault(name.strip(), []).append({"value": clean_inline_value(raw), "section": section})

    chosen_parts: List[str] = []
    chosen_sources: List[Dict] = []
    conflicts: List[Dict] = []
    detail_rows: List[Dict] = []
    for name, candidates in facts.items():
        candidates.sort(
            key=lambda c: (parse_update_at(c["section"].get("update_at", "")), int(c["section"].get("confluence_version") or 0)),
            reverse=True,
        )
        chosen = candidates[0]
        chosen_parts.append(f"{name}: {chosen['value']}")
        chosen_sources.append(chosen["section"])
        unique = sorted({c["value"] for c in candidates})
        if len(unique) > 1:
            rows = [
                {"value": f"{name}: {c['value']}", "page_id": c["section"]["page_id"], "confluence_version": c["section"]["confluence_version"], "update_at": c["section"]["update_at"]}
                for c in candidates
            ]
            detail_rows.extend(rows)
            conflicts.append({"detail": f"{name} conflict; temporarily chose newest value {chosen['value']}.", "options": [r["value"] + f" ({r['page_id']})" for r in rows]})

    field = {
        "field": "config",
        "tier": "inline-value",
        "value": "; ".join(chosen_parts),
        "authoritative": True,
        "conflict": bool(detail_rows),
        "conflict_detail": detail_rows,
        "sources": sources(chosen_sources),
        "evidence_keywords": evidence["keywords_raw_agg"],
        "source_section_ids": dedupe_strings(section_id(s) for s in chosen_sources),
    }
    return field, conflicts


def build_troubleshoot_field(sections: List[Dict], evidence: Dict) -> Optional[Dict]:
    ts = [s for s in sections if s.get("info_type") == "troubleshoot"]
    exact = dedupe_strings(clean_inline_value(s["fact_value"]) for s in ts if s.get("fact_value"))
    if exact:
        owners = [s for s in ts if s.get("fact_value")]
        return {
            "field": "troubleshoot",
            "tier": "inline-value",
            "value": "; ".join(exact),
            "sources": sources(owners),
            "evidence_keywords": evidence["keywords_raw_agg"],
            "source_section_ids": dedupe_strings(section_id(s) for s in owners),
        }
    notes = dedupe_strings(clean_narrative_text(s.get("summary_en", "")) for s in ts if not s.get("fact_value"))
    notes = [n for n in notes if n]
    if notes:
        owners = [s for s in ts if not s.get("fact_value")]
        return narrative_field("troubleshoot", "\n".join(f"- {n}" for n in notes), owners, evidence)
    return None


def pointer_fields(sections: List[Dict]) -> List[Dict]:
    out: List[Dict] = []
    for section in sections:
        if section.get("tier") == "pointer-only" and section.get("pointer_to"):
            out.append(
                {
                    "field": "pointer",
                    "tier": "pointer-only",
                    "value": None,
                    "pointer_to": section["pointer_to"],
                    "sources": sources([section]),
                    "source_section_ids": [section_id(section)],
                }
            )
    return out


def related_components_field(cid: str, sections: List[Dict], canonicals: Dict[str, Dict], evidence: Dict) -> Optional[Dict]:
    text = " ".join(
        (str(s.get("anchor") or "") + " " + " ".join(s.get("keywords_raw", []))) for s in sections
    ).lower()
    links = [
        other
        for other in canonicals
        if other != cid and canonical_id_in_text(text, {other: canonicals[other]})
    ]
    if not links:
        return None
    names = [canonicals[link]["canonical_name"] for link in links]
    return {
        "field": "related_components",
        "tier": "narrative",
        "value": "Related to " + ", ".join(names) + ".",
        "soft_links": links,
        "sources": sources(sections),
        "evidence_keywords": evidence["keywords_raw_agg"],
        "source_section_ids": evidence["source_section_ids"],
    }


def narrative_field(field_name: str, value: str, sections: List[Dict], evidence: Dict) -> Dict:
    return {
        "field": field_name,
        "tier": "narrative",
        "value": clean_narrative_text(value),
        "sources": sources(sections),
        "evidence_keywords": evidence["keywords_raw_agg"],
        "source_section_ids": evidence["source_section_ids"],
    }


# ---------------------------------------------------------------------------
# Cleaning (kills the B1/B2 echo + stub + junk noise)
# ---------------------------------------------------------------------------

ECHO_RE = re.compile(r"\bQ\s*[:：]\s*", re.IGNORECASE)


def clean_narrative_text(text: str) -> str:
    cleaned = str(text or "").strip()
    if not cleaned:
        return ""
    cleaned = ECHO_RE.sub("", cleaned)
    # collapse "X: X" / "X X" immediate repeats
    cleaned = re.sub(r"(.{6,80}?)(?:\s*[:：]?\s*\1)+", r"\1", cleaned).strip()
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    return cleaned.strip(" :：-")


def clean_inline_value(text: str) -> str:
    value = str(text or "").strip().strip("`\"'")
    dup = re.fullmatch(r"(https?://\S+?)\s*\((https?://\S+)\)", value)
    if dup and dup.group(1).rstrip("/") == dup.group(2).rstrip("/"):
        value = dup.group(1)
    return value.strip()


def is_junk_value(value: str) -> bool:
    cleaned = str(value or "").strip(" .-:：")
    if not cleaned:
        return True
    if re.fullmatch(r"[-.\s]+", str(value or "")):
        return True
    if "authenticate to see" in cleaned.lower() or "getting issue details" in cleaned.lower():
        return True
    return False


def is_heading_only_section(section: Dict) -> bool:
    body = clean_narrative_text(str(section.get("body_md") or ""))
    heading = normalize_term((section.get("heading_path") or [""])[-1])
    if not body:
        return True
    return normalize_term(body) == heading and not section.get("fact_values")


def narrative_fact_value(section: Dict) -> str:
    summary = clean_narrative_text(section.get("summary_en") or section.get("summary_zh") or "")
    if summary:
        return summary
    return clean_narrative_text(str(section.get("body_md") or "").splitlines()[0] if section.get("body_md") else "")


# ---------------------------------------------------------------------------
# Review queue / inverted index / helpers
# ---------------------------------------------------------------------------

def conflict_item(cid: str, conflict: Dict, n: int) -> Dict:
    return {"queue_id": f"RQ-conflict-{cid}-{n:03d}", "type": "conflict", "canonical_id": cid, "field": "config", "detail": conflict["detail"], "options": conflict["options"], "status": "open"}


def unmatched_review_item(section: Dict) -> Dict:
    anchor = str(section.get("anchor") or section_id(section))
    return {
        "queue_id": f"RQ-unmatched-{stable_short(anchor)}",
        "type": "unmatched-section",
        "canonical_id": "",
        "field": "association",
        "detail": f"No approved canonical could be assigned to {anchor}; report it to the keyword-table owner.",
        "options": section.get("keywords_raw", []),
        "status": "open",
    }


def low_confidence_items(sections: List[Dict]) -> List[Dict]:
    items: List[Dict] = []
    for section in sections:
        try:
            confidence = float(section.get("confidence", 1.0))
        except (TypeError, ValueError):
            confidence = 1.0
        if confidence < 0.6:
            items.append(
                {
                    "queue_id": f"RQ-lowconf-{stable_short(section_id(section))}",
                    "type": "low-confidence",
                    "canonical_id": "",
                    "field": "",
                    "detail": f"Low confidence extraction at {section.get('anchor') or section_id(section)}",
                    "options": [],
                    "status": "open",
                }
            )
    return items


def alias_review_item(cid: str, canonical: Dict, aliases: List[str]) -> Dict:
    return {"queue_id": f"RQ-aliases-{cid}", "type": "alias-resolution-request", "canonical_id": cid, "field": "aliases", "detail": f"Review candidate aliases for '{canonical['canonical_name']}'.", "options": aliases, "status": "open"}


def inverted_row(cid: str, section: Dict, canonicals: Dict[str, Dict]) -> Dict:
    canonical = canonicals[cid]
    return {
        "canonical_id": cid,
        "canonical_name": canonical["canonical_name"],
        "module": canonical.get("module", []),
        "page_id": section["page_id"],
        "anchor": str(section.get("anchor") or section_id(section)),
        "section_id": section_id(section),
        "info_type": section.get("info_type", "what-is"),
        "tier": section.get("tier", "narrative"),
        "confidence": float(section.get("confidence", 0.8) or 0.8),
        "confluence_version": section["confluence_version"],
    }


def sources(sections: List[Dict]) -> List[Dict]:
    rows: List[Dict] = []
    for section in sections:
        rows.append(
            {
                "page_id": section["page_id"],
                "anchor": str(section.get("anchor") or section_id(section)),
                "source_url": section["source_url"],
                "confluence_version": section["confluence_version"],
            }
        )
    seen = set()
    out: List[Dict] = []
    for row in rows:
        key = (row["page_id"], row["anchor"])
        if key not in seen:
            seen.add(key)
            out.append(row)
    return out


def load_ref_lookup(path: Path) -> Dict[str, Dict]:
    """Index refs.json by section_id so reduce can re-attach the original body_md."""
    if not path.exists():
        return {}
    refs = read_json(path)
    return {str(item.get("section_id") or ""): item for item in refs if isinstance(item, dict) and item.get("section_id")}


def section_id(section: Dict) -> str:
    return str(section.get("section_id") or compute_section_id(str(section.get("page_id", "")), section.get("heading_path") or []))


def infer_topic_class(canonical: Dict) -> str:
    topic_type = str(canonical.get("topic_type") or "").lower()
    mapping = {"process": "workflow", "service": "system_component", "component": "system_component", "inventory": "catalog", "planning": "catalog"}
    return mapping.get(topic_type, "")


def dedupe_facts(facts: List[Dict]) -> List[Dict]:
    seen = set()
    out: List[Dict] = []
    for fact in facts:
        key = (fact.get("label"), fact.get("tier"), str(fact.get("value")), fact.get("pointer_to"))
        if key not in seen:
            seen.add(key)
            out.append(fact)
    return out


def dedupe_inverted(rows: List[Dict]) -> List[Dict]:
    seen = set()
    out: List[Dict] = []
    for row in rows:
        key = (row["canonical_id"], row["page_id"], row["anchor"])
        if key not in seen:
            seen.add(key)
            out.append(row)
    return out


def dedupe_strings(items: Iterable[str]) -> List[str]:
    seen = set()
    out: List[str] = []
    for item in items:
        text = str(item).strip()
        if not text or text.lower() in seen:
            continue
        seen.add(text.lower())
        out.append(text)
    return out


def stable_short(text: str) -> str:
    return hashlib.sha1(str(text).encode("utf-8")).hexdigest()[:8]


def parse_update_at(value: str) -> datetime:
    text = str(value or "").strip()
    if not text:
        return datetime.min.replace(tzinfo=timezone.utc)
    candidates = [text]
    if text.endswith("Z"):
        candidates.append(text[:-1] + "+00:00")
    if " " in text and "T" not in text:
        candidates.append(text.replace(" ", "T"))
    for candidate in candidates:
        try:
            parsed = datetime.fromisoformat(candidate)
            return parsed.replace(tzinfo=parsed.tzinfo or timezone.utc).astimezone(timezone.utc)
        except ValueError:
            continue
    for fmt in ("%Y/%m/%d %H:%M:%S", "%Y/%m/%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return datetime.min.replace(tzinfo=timezone.utc)


def safe_filename(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "_", str(name)).strip("_") or "card"
