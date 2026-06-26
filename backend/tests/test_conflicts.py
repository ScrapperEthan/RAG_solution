"""Conflict review subsystem: detect -> LLM review -> ledger -> apply to cards."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from backend.adapters.llm_mock import MockLLM
from backend.reducer.conflicts import (
    ConflictReviewService,
    apply_decisions,
    apply_resolved_to_cards,
    candidates_fingerprint,
    conflict_records_from_queue,
    read_conflicts,
    read_ledger,
    record_decision,
    review_conflicts_with_llm,
)
from backend.reducer.service import conflict_id
from backend.util import read_json, write_json, write_jsonl


CID = conflict_id("C-1", "PN", "SLO")


def sample_queue():
    return [
        {
            "queue_id": "RQ-unmatched-abc",  # non-conflict item must be ignored
            "type": "unmatched-section",
            "canonical_id": "",
            "field": "association",
            "detail": "no match",
            "options": [],
            "status": "open",
        },
        {
            "queue_id": "RQ-factconflict-C-1-abc",
            "type": "fact-conflict",
            "canonical_id": "C-1",
            "field": "PN / SLO",
            "detail": "Subsection 'PN' label 'SLO' has 2 conflicting values; temporarily kept newest '8h'.",
            "options": ["4h (old, v4, 2026-01-01)", "8h (new, v8, 2026-02-01)"],
            "status": "open",
            "conflict_id": CID,
            "label": "SLO",
            "subsection": "PN",
            "auto_choice": "8h",
            "candidates": [
                {"value": "4h", "page_id": "old", "source_url": "u1", "confluence_version": 4, "update_at": "2026-01-01"},
                {"value": "8h", "page_id": "new", "source_url": "u2", "confluence_version": 8, "update_at": "2026-02-01"},
            ],
        },
    ]


def sample_cards():
    return [
        {
            "canonical_id": "C-1",
            "canonical_name": "Payment Notify",
            "subsections": [{"name": "PN", "facts": [{"label": "SLO", "tier": "inline-value", "value": "8h"}], "sources": []}],
            "fields": [],
            "flags": ["subsection 'PN' label 'SLO' has conflicting values"],
        }
    ]


class ConflictRecordTest(unittest.TestCase):
    def test_only_conflict_items_become_records_with_metadata(self) -> None:
        records = conflict_records_from_queue(sample_queue(), sample_cards())
        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertEqual(record["conflict_id"], CID)
        self.assertEqual(record["canonical_name"], "Payment Notify")
        self.assertEqual(record["auto_choice"], "8h")
        self.assertEqual(len(record["candidates"]), 2)
        self.assertTrue(record["candidates_fingerprint"])

    def test_llm_review_flags_numeric_divergence_as_high_risk(self) -> None:
        records = review_conflicts_with_llm(conflict_records_from_queue(sample_queue(), sample_cards()), MockLLM())
        review = records[0]["llm_review"]
        self.assertEqual(review["risk"], "high")  # 4h vs 8h -> distinct numbers
        self.assertIn(review["recommended_value"], {"4h", "8h"})
        self.assertTrue(review["reason_zh"])

    def test_decision_resolves_only_when_fingerprint_matches(self) -> None:
        records = conflict_records_from_queue(sample_queue(), sample_cards())
        fp = records[0]["candidates_fingerprint"]
        resolved = apply_decisions(
            conflict_records_from_queue(sample_queue(), sample_cards()),
            [{"conflict_id": CID, "chosen_value": "4h", "candidates_fingerprint": fp}],
        )
        self.assertEqual(resolved[0]["status"], "resolved")
        # A decision made against a different value set re-opens as stale.
        stale = apply_decisions(
            conflict_records_from_queue(sample_queue(), sample_cards()),
            [{"conflict_id": CID, "chosen_value": "4h", "candidates_fingerprint": "deadbeef"}],
        )
        self.assertEqual(stale[0]["status"], "stale")

    def test_apply_resolved_rewrites_the_card_fact_value(self) -> None:
        cards = sample_cards()
        records = apply_decisions(
            conflict_records_from_queue(sample_queue(), cards),
            [{"conflict_id": CID, "chosen_value": "4h", "candidates_fingerprint": candidates_fingerprint(sample_queue()[1]["candidates"])}],
        )
        changed = apply_resolved_to_cards(cards, records)
        self.assertEqual(changed, 1)
        self.assertEqual(cards[0]["subsections"][0]["facts"][0]["value"], "4h")
        self.assertTrue(cards[0]["resolved_conflicts"])


class ConflictServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.outputs = Path(self._tmp.name)
        write_jsonl(self.outputs / "review_queue.jsonl", sample_queue())
        write_json(self.outputs / "cards_index.json", sample_cards())

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_run_writes_reviewed_conflicts_feed(self) -> None:
        stats = ConflictReviewService(self.outputs, MockLLM()).run()
        self.assertEqual(stats["conflicts"], 1)
        self.assertEqual(stats["open"], 1)
        feed = read_conflicts(self.outputs)
        self.assertEqual(feed[0]["status"], "open")
        self.assertIsNotNone(feed[0]["llm_review"])

    def test_record_decision_persists_and_rewrites_card(self) -> None:
        ConflictReviewService(self.outputs, MockLLM()).run()
        updated = record_decision(self.outputs, CID, "4h", decided_by="ethan")
        self.assertEqual(updated["status"], "resolved")
        self.assertEqual(read_ledger(self.outputs)[0]["chosen_value"], "4h")
        card = read_json(self.outputs / "cards_index.json")[0]
        self.assertEqual(card["subsections"][0]["facts"][0]["value"], "4h")

    def test_unknown_conflict_id_raises(self) -> None:
        ConflictReviewService(self.outputs, MockLLM()).run()
        with self.assertRaises(KeyError):
            record_decision(self.outputs, "CF-nope", "x")


if __name__ == "__main__":
    unittest.main()
