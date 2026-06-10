from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from backend.ports import LLM
from backend.reducer.canonicals import load_vocabulary, normalize_term
from backend.util import read_json, write_json, write_jsonl


DISCOVER_SYSTEM = """task: card_discover_topics
You are PROPOSING canonical topic candidates for human review. You are NOT building cards.
Given (a) raw keyword/concept strings collected verbatim from many sections and (b) the list
of already-approved canonical concepts, return STRICT JSON:
{
  "mapped":       [{"raw": string, "canonical_id": string}],
  "candidates":   [{"canonical_name": string, "aliases": [string],
                    "evidence_keywords": [string], "suggested_subsections": [string],
                    "nearest_existing": {"canonical_id": string, "name": string,
                                          "similarity": number, "reason": string} | null}],
  "needs_review": [{"raw": string, "reason": string}]
}

Rules:
- Map a raw term to an existing approved canonical_id when it clearly refers to the same thing.
- Cluster the remaining terms into FEWER, well-scoped candidates; a name should be one thing in
  the user's mind. Prefer merging near-duplicates and proposing the finer item as a subsection.
- For every candidate also report nearest_existing (best-matching approved topic + similarity +
  reason), even if you believe it is new, so humans can catch duplicates.
- Ambiguous terms go to needs_review. Do NOT output cards or final canonical_ids."""

DISCOVER_SCHEMA = {"type": "object", "required": ["candidates"]}

DUP_THRESHOLD = 0.6


class DiscoverService:
    """Propose candidate topics (for the human freeze gate) — never builds cards.

    Output is `proposed_keywords.json` (read by frontend/approve.html), plus a
    jsonl + a markdown review table. Each candidate carries a deterministic
    `dup_warning` (D2) and the model's `nearest_existing` (D1) against the
    current approved table, so duplicates surface before they fragment.
    """

    def __init__(self, outputs_dir: Path, llm: LLM, keyword_table: Optional[Path] = None):
        self.outputs_dir = outputs_dir
        self.llm = llm
        self.keyword_table = keyword_table

    def run(self) -> Dict[str, int]:
        raw_terms, term_sections, modules = self._collect_terms()
        approved = self._load_approved()
        response = self.llm.complete_json(
            DISCOVER_SYSTEM,
            json.dumps({"raw_keywords": raw_terms, "approved_canonicals": list(approved.values())}, ensure_ascii=False),
            schema=DISCOVER_SCHEMA,
        )
        candidates = self._build_candidates(response, term_sections, approved)
        write_json(self.outputs_dir / "proposed_keywords.json", {"candidates": candidates, "modules": modules})
        write_jsonl(self.outputs_dir / "proposed_keywords.jsonl", candidates)
        (self.outputs_dir / "proposed_keywords_review.md").write_text(render_review_md(candidates), encoding="utf-8")
        return {"candidates": len(candidates), "needs_review": sum(1 for c in candidates if c["status"] == "needs_review")}

    def _collect_terms(self) -> Tuple[List[str], Dict[str, List[str]], List[str]]:
        term_sections: Dict[str, List[str]] = {}
        order: List[str] = []
        modules: List[str] = []
        for path in sorted((self.outputs_dir / "map").glob("map_*.json")):
            page = read_json(path)
            for module in (page.get("module") or page.get("labels") or []):
                if module and module not in modules:
                    modules.append(module)
            for section in page.get("sections", []):
                sid = str(section.get("section_id") or "")
                for term in list(section.get("concepts") or []) + list(section.get("keywords_raw") or []):
                    term = str(term).strip()
                    if not term:
                        continue
                    key = term.lower()
                    if key not in term_sections:
                        term_sections[key] = []
                        order.append(term)
                    if sid and sid not in term_sections[key]:
                        term_sections[key].append(sid)
        return order, term_sections, modules

    def _load_approved(self) -> Dict[str, Dict]:
        if not self.keyword_table or not Path(self.keyword_table).exists():
            return {}
        try:
            return load_vocabulary(Path(self.keyword_table))
        except ValueError:
            return {}

    def _build_candidates(self, response: Dict, term_sections: Dict[str, List[str]], approved: Dict[str, Dict]) -> List[Dict]:
        candidates: List[Dict] = []
        for index, raw in enumerate(response.get("candidates") or [], start=1):
            name = str(raw.get("canonical_name") or "").strip()
            if not name:
                continue
            aliases = _clean_list(raw.get("aliases"))
            evidence = _clean_list(raw.get("evidence_keywords")) or [name]
            terms = dedupe([name, *aliases, *evidence])
            source_ids = dedupe(sid for term in terms for sid in term_sections.get(term.lower(), []))
            dup_warning = compute_dup_warning(name, aliases, approved)
            nearest = raw.get("nearest_existing") if isinstance(raw.get("nearest_existing"), dict) else None
            if not nearest and dup_warning:
                top = dup_warning[0]
                nearest = {"canonical_id": top["canonical_id"], "name": top["name"], "similarity": top["score"], "reason": "string match"}
            candidates.append(
                {
                    "canonical_id": f"C-PROP-{index:04d}",
                    "canonical_name": name,
                    "aliases": aliases,
                    "topic_summary": str(raw.get("topic_summary") or "").strip(),
                    "evidence_keywords": evidence,
                    "suggested_module": _clean_list(raw.get("suggested_module")),
                    "suggested_boundary": str(raw.get("suggested_boundary") or "").strip(),
                    "suggested_topic_type": str(raw.get("suggested_topic_type") or "").strip(),
                    "suggested_topic_class": str(raw.get("suggested_topic_class") or "").strip(),
                    "suggested_subsections": _clean_list(raw.get("suggested_subsections")),
                    "source_section_ids": source_ids,
                    "support": len(source_ids),
                    "status": "needs_review" if raw.get("needs_review_reason") else "proposed",
                    "needs_review_reason": str(raw.get("needs_review_reason") or "").strip(),
                    "dup_warning": dup_warning,
                    "nearest_existing": nearest or {},
                }
            )
        return candidates


# ---------------------------------------------------------------------------
# D2: deterministic fuzzy duplicate detection (token Jaccard + char-trigram Dice)
# ---------------------------------------------------------------------------

def compute_dup_warning(name: str, aliases: List[str], approved: Dict[str, Dict]) -> List[Dict]:
    candidate_terms = dedupe([name, *aliases])
    warnings: List[Dict] = []
    for cid, canonical in approved.items():
        existing_terms = dedupe([canonical.get("canonical_name", ""), *canonical.get("aliases", [])])
        score = max((fuzzy_score(a, b) for a in candidate_terms for b in existing_terms if a and b), default=0.0)
        if score >= DUP_THRESHOLD:
            warnings.append({"canonical_id": cid, "name": canonical.get("canonical_name", ""), "score": round(score, 2)})
    warnings.sort(key=lambda w: w["score"], reverse=True)
    return warnings


def fuzzy_score(a: str, b: str) -> float:
    return max(token_jaccard(a, b), char_trigram_dice(a, b))


def token_jaccard(a: str, b: str) -> float:
    sa, sb = set(normalize_term(a).split()), set(normalize_term(b).split())
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def char_trigram_dice(a: str, b: str) -> float:
    ta, tb = _trigrams(normalize_term(a)), _trigrams(normalize_term(b))
    if not ta or not tb:
        return 0.0
    return 2 * len(ta & tb) / (len(ta) + len(tb))


def _trigrams(text: str) -> set:
    compact = re.sub(r"\s+", "", text)
    if len(compact) >= 3:
        return {compact[i : i + 3] for i in range(len(compact) - 2)}
    return {compact} if compact else set()


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def render_review_md(candidates: List[Dict]) -> str:
    lines = [
        "# Proposed Keyword Candidates (review before freezing)",
        "",
        "| id | canonical_name | aliases | support | dup (existing) | status |",
        "|---|---|---|---:|---|---|",
    ]
    for c in candidates:
        dup = "; ".join(f"{w['canonical_id']}({w['score']})" for w in c["dup_warning"]) or "-"
        lines.append(
            f"| {c['canonical_id']} | {c['canonical_name']} | {'; '.join(c['aliases'])} | {c['support']} | {dup} | {c['status']} |"
        )
    return "\n".join(lines) + "\n"


def _clean_list(value) -> List[str]:
    if not isinstance(value, list):
        return []
    return dedupe(str(item).strip() for item in value if str(item).strip())


def dedupe(items) -> List[str]:
    seen = set()
    out: List[str] = []
    for item in items:
        text = str(item).strip()
        if not text or text.lower() in seen:
            continue
        seen.add(text.lower())
        out.append(text)
    return out
