"""Conflict review subsystem.

`reduce` detects field-level conflicts (same label, divergent values across
pages/versions) and auto-resolves them newest-wins. That is a *temporary*
choice. This module turns each conflict into a reviewable record, asks the LLM
for a recommendation + reasoning, and lets a human freeze a decision that
survives the next full rebuild via a decision ledger.

Flow (pipeline command ``review-conflicts``, run after ``reduce``):
    review_queue.jsonl ─▶ structured conflict records
                         ─▶ LLM review (recommendation + reason + risk)
                         ─▶ apply decision ledger (open / resolved / stale)
                         ─▶ rewrite resolved values back into cards_index.json
                         ─▶ write conflicts.jsonl

The ledger (`conflict_decisions.jsonl`) is the durable contract — symmetric with
the keyword-table freeze gate. `conflict_id` is keyed on (canonical, scope,
label) only, so a decision sticks across rebuilds; a changed candidate *set* is
caught by the value fingerprint and re-opens the conflict as ``stale``.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from backend.ports import LLM
from backend.reducer.canonicals import normalize_term
from backend.util import read_json, read_jsonl, write_json, write_jsonl


CONFLICT_TYPES = {"conflict", "fact-conflict"}
AUTO_BASIS = "newest update_at/version"

CONFLICT_REVIEW_SYSTEM = """task: card_review_conflict
You are reviewing ONE field-level conflict for a knowledge card. Several Confluence
sections give different values for the same field. The pipeline temporarily kept the
newest value; your job is to recommend what a human should approve and explain why.
Do NOT invent values — recommend one of the supplied candidate values verbatim.
Return STRICT JSON:
{"recommended_value": string, "reason_zh": string, "reason_en": string,
 "confidence": number (0..1), "risk": "low" | "medium" | "high"}
Use risk="high" when the values look materially different (e.g. different numbers/units)
so picking the newest could silently ship wrong data; use "low" when they are trivially
equivalent (formatting/whitespace)."""

CONFLICT_REVIEW_SCHEMA = {"type": "object", "required": ["recommended_value", "reason_zh", "confidence"]}


# ---------------------------------------------------------------------------
# Build structured records from the reduce review queue
# ---------------------------------------------------------------------------

def candidates_fingerprint(candidates: List[Dict]) -> str:
    values = sorted({str(c.get("value", "")).strip() for c in candidates})
    return hashlib.sha1("|".join(values).encode("utf-8")).hexdigest()[:12]


def conflict_records_from_queue(review_queue: List[Dict], cards: Optional[List[Dict]] = None) -> List[Dict]:
    names = {
        str(card.get("canonical_id")): str(card.get("canonical_name") or "")
        for card in (cards or [])
        if isinstance(card, dict)
    }
    records: List[Dict] = []
    for item in review_queue:
        if item.get("type") not in CONFLICT_TYPES:
            continue
        candidates = list(item.get("candidates") or [])
        cid = str(item.get("canonical_id") or "")
        records.append(
            {
                "conflict_id": str(item.get("conflict_id") or item.get("queue_id") or ""),
                "type": item["type"],
                "canonical_id": cid,
                "canonical_name": names.get(cid, ""),
                "field": str(item.get("field") or ""),
                "label": str(item.get("label") or ""),
                "subsection": str(item.get("subsection") or ""),
                "candidates": candidates,
                "candidates_fingerprint": candidates_fingerprint(candidates),
                "auto_choice": str(item.get("auto_choice") or ""),
                "auto_basis": AUTO_BASIS,
                "detail": str(item.get("detail") or ""),
                "llm_review": None,
                "status": "open",
                "decision": None,
            }
        )
    return records


# ---------------------------------------------------------------------------
# LLM review
# ---------------------------------------------------------------------------

def review_conflicts_with_llm(records: List[Dict], llm: Optional[LLM]) -> List[Dict]:
    if llm is None:
        return records
    for record in records:
        # Only spend a call on conflicts a human still has to look at.
        if record.get("status") == "resolved" or record.get("llm_review"):
            continue
        payload = {
            "canonical_name": record.get("canonical_name") or record.get("canonical_id"),
            "field": record.get("field"),
            "label": record.get("label"),
            "candidates": record.get("candidates"),
            "auto_choice": record.get("auto_choice"),
        }
        try:
            response = llm.complete_json(
                CONFLICT_REVIEW_SYSTEM,
                json.dumps(payload, ensure_ascii=False),
                schema=CONFLICT_REVIEW_SCHEMA,
            )
        except Exception:
            continue
        record["llm_review"] = normalize_review(response, record)
    return records


def normalize_review(response: Dict, record: Dict) -> Dict:
    values = [str(c.get("value", "")) for c in record.get("candidates", [])]
    recommended = str(response.get("recommended_value") or record.get("auto_choice") or "")
    # Guard: the model must recommend an actual candidate, else fall back to auto.
    if values and recommended not in values:
        recommended = record.get("auto_choice") or values[-1]
    risk = str(response.get("risk") or "medium").lower()
    if risk not in {"low", "medium", "high"}:
        risk = "medium"
    try:
        confidence = max(0.0, min(1.0, float(response.get("confidence", 0.5))))
    except (TypeError, ValueError):
        confidence = 0.5
    return {
        "recommended_value": recommended,
        "reason_zh": str(response.get("reason_zh") or response.get("reason") or "").strip(),
        "reason_en": str(response.get("reason_en") or "").strip(),
        "confidence": round(confidence, 2),
        "risk": risk,
    }


# ---------------------------------------------------------------------------
# Decision ledger
# ---------------------------------------------------------------------------

def apply_decisions(records: List[Dict], ledger: List[Dict]) -> List[Dict]:
    latest: Dict[str, Dict] = {}
    for row in ledger:
        cid = str(row.get("conflict_id") or "")
        if cid:
            latest[cid] = row  # later rows win (append-only ledger)
    for record in records:
        decision = latest.get(record["conflict_id"])
        if not decision:
            record["status"] = "open"
            record["decision"] = None
            continue
        record["decision"] = {
            "chosen_value": str(decision.get("chosen_value", "")),
            "decided_by": str(decision.get("decided_by", "")),
            "decided_at": str(decision.get("decided_at", "")),
            "candidates_fingerprint": str(decision.get("candidates_fingerprint", "")),
        }
        if record["decision"]["candidates_fingerprint"] == record["candidates_fingerprint"]:
            record["status"] = "resolved"
        else:
            # Decision was made against a different set of values; a new value has
            # arrived since. Re-open loudly instead of trusting a stale choice.
            record["status"] = "stale"
    return records


def effective_value(record: Dict) -> str:
    if record.get("status") == "resolved" and record.get("decision"):
        return record["decision"]["chosen_value"]
    return record.get("auto_choice", "")


# ---------------------------------------------------------------------------
# Apply resolved decisions back into the served cards
# ---------------------------------------------------------------------------

def apply_resolved_to_cards(cards: List[Dict], records: List[Dict]) -> int:
    by_cid: Dict[str, Dict] = {str(card.get("canonical_id")): card for card in cards if isinstance(card, dict)}
    changed = 0
    for record in records:
        if record.get("status") != "resolved":
            continue
        chosen = record["decision"]["chosen_value"]
        if chosen == record.get("auto_choice"):
            continue  # human agreed with the newest value; nothing to rewrite
        card = by_cid.get(record["canonical_id"])
        if not card:
            continue
        if _rewrite_card_value(card, record, chosen):
            changed += 1
    return changed


def _rewrite_card_value(card: Dict, record: Dict, chosen: str) -> bool:
    target_label = normalize_term(record.get("label", ""))
    if record["type"] == "fact-conflict":
        for subsection in card.get("subsections", []) or []:
            if record.get("subsection") and normalize_term(subsection.get("name", "")) != normalize_term(record["subsection"]):
                continue
            for fact in subsection.get("facts", []) or []:
                if normalize_term(fact.get("label", "")) == target_label and fact.get("value") not in (None, ""):
                    fact["value"] = chosen
                    fact["resolved_conflict"] = record["conflict_id"]
                    _note_resolution(card, record, chosen)
                    return True
        return False
    # config conflict: the config field value is "name: v; name2: v2"
    for field in card.get("fields", []) or []:
        if field.get("field") != "config":
            continue
        name = record.get("label", "")
        pattern = re.compile(rf"({re.escape(name)}\s*:\s*)([^;]+)")
        new_value, n = pattern.subn(lambda m: m.group(1) + chosen, str(field.get("value") or ""))
        if n:
            field["value"] = new_value
            field["resolved_conflict"] = record["conflict_id"]
            _note_resolution(card, record, chosen)
            return True
    return False


def _note_resolution(card: Dict, record: Dict, chosen: str) -> None:
    card.setdefault("resolved_conflicts", [])
    note = f"{record.get('field')} resolved to '{chosen}' by {record['decision'].get('decided_by') or 'review'}"
    if note not in card["resolved_conflicts"]:
        card["resolved_conflicts"].append(note)


# ---------------------------------------------------------------------------
# Service + file I/O
# ---------------------------------------------------------------------------

CONFLICTS_FILE = "conflicts.jsonl"
LEDGER_FILE = "conflict_decisions.jsonl"


def read_conflicts(outputs_dir: Path) -> List[Dict]:
    return read_jsonl(outputs_dir / CONFLICTS_FILE)


def read_ledger(outputs_dir: Path) -> List[Dict]:
    return read_jsonl(outputs_dir / LEDGER_FILE)


class ConflictReviewService:
    """Build → LLM-review → apply-ledger → apply-to-cards → write conflicts.jsonl."""

    def __init__(self, outputs_dir: Path, llm: Optional[LLM] = None):
        self.outputs_dir = Path(outputs_dir)
        self.llm = llm

    def run(self) -> Dict[str, int]:
        review_queue = read_jsonl(self.outputs_dir / "review_queue.jsonl")
        cards_path = self.outputs_dir / "cards_index.json"
        cards = read_json(cards_path) if cards_path.exists() else []
        if not isinstance(cards, list):
            cards = []

        records = conflict_records_from_queue(review_queue, cards)
        records = apply_decisions(records, read_ledger(self.outputs_dir))
        records = review_conflicts_with_llm(records, self.llm)
        applied = apply_resolved_to_cards(cards, records)
        if applied:
            write_json(cards_path, cards)
        write_jsonl(self.outputs_dir / CONFLICTS_FILE, records)
        return {
            "conflicts": len(records),
            "open": sum(1 for r in records if r["status"] == "open"),
            "stale": sum(1 for r in records if r["status"] == "stale"),
            "resolved": sum(1 for r in records if r["status"] == "resolved"),
            "applied_to_cards": applied,
        }


def record_decision(outputs_dir: Path, conflict_id: str, chosen_value: str, decided_by: str = "human") -> Dict:
    """Append a human approval to the ledger, then recompute statuses + cards.

    Returns the updated conflict record. Raises KeyError if the conflict_id is
    unknown (so the API can 404). No LLM call — review suggestions are reused.
    """
    outputs_dir = Path(outputs_dir)
    records = read_conflicts(outputs_dir)
    target = next((r for r in records if r["conflict_id"] == conflict_id), None)
    if target is None:
        raise KeyError(conflict_id)

    ledger_row = {
        "conflict_id": conflict_id,
        "chosen_value": chosen_value,
        "decided_by": decided_by,
        "decided_at": datetime.now(timezone.utc).isoformat(),
        "candidates_fingerprint": target["candidates_fingerprint"],
    }
    with (outputs_dir / LEDGER_FILE).open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(ledger_row, ensure_ascii=False) + "\n")

    # Recompute every record's status against the updated ledger and re-apply to
    # the served cards so the approval is visible immediately (no reduce needed).
    records = apply_decisions(records, read_ledger(outputs_dir))
    cards_path = outputs_dir / "cards_index.json"
    cards = read_json(cards_path) if cards_path.exists() else []
    if isinstance(cards, list) and apply_resolved_to_cards(cards, records):
        write_json(cards_path, cards)
    write_jsonl(outputs_dir / CONFLICTS_FILE, records)
    return next(r for r in records if r["conflict_id"] == conflict_id)
