"""Standalone regression for the topic discovery proposer (no yaml needed).

Covers D2 deterministic dup detection and the end-to-end DiscoverService with the
MockLLM: candidates carry C-PROP ids + dup_warning against the existing table, and
NO cards are produced.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from backend.adapters.llm_mock import MockLLM
from backend.reducer.discovery import (
    DiscoverService,
    char_trigram_dice,
    compute_dup_warning,
    fuzzy_score,
    token_jaccard,
)


class FuzzyTest(unittest.TestCase):
    def test_surface_variant_is_high(self) -> None:
        self.assertGreaterEqual(fuzzy_score("Notification Preference", "Notification Preferences"), 0.6)  # char-trigram
        self.assertGreaterEqual(fuzzy_score("MDC Portal", "MDC Management Portal"), 0.6)  # token jaccard (0.67)
        self.assertGreaterEqual(char_trigram_dice("Notification Preference", "Notification Preferences"), 0.6)

    def test_unrelated_is_low(self) -> None:
        self.assertLess(fuzzy_score("Bulk SMS Throttling", "MDC Management Portal"), 0.6)
        self.assertEqual(token_jaccard("", "x"), 0.0)

    def test_dup_warning_against_existing(self) -> None:
        approved = {"C-0001": {"canonical_name": "Notification Preference", "aliases": []}}
        warn = compute_dup_warning("Notification Preferences", [], approved)
        self.assertTrue(warn and warn[0]["canonical_id"] == "C-0001")
        self.assertFalse(compute_dup_warning("Bulk SMS Throttling", [], approved))


class DiscoverServiceTest(unittest.TestCase):
    def test_proposes_not_builds_cards(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            (out / "map").mkdir()
            (out / "map" / "map_P.json").write_text(
                json.dumps(
                    {
                        "page_id": "P",
                        "domains": ["Channel standard"],
                        "sections": [
                            {"section_id": "P#a", "concepts": ["Notification Preferences"], "keywords_raw": ["Bulk SMS Throttling", "PN"]},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            table = out / "keyword_table.jsonl"
            table.write_text(json.dumps({"canonical_id": "C-0001", "canonical_name": "Notification Preference", "status": "approved"}) + "\n", encoding="utf-8")

            result = DiscoverService(out, MockLLM(), table).run()

            self.assertGreaterEqual(result["candidates"], 1)
            self.assertFalse((out / "cards").exists(), "discover must NOT build cards")
            payload = json.loads((out / "proposed_keywords.json").read_text(encoding="utf-8"))
            self.assertIn("candidates", payload)
            self.assertIn("Channel standard", payload["domains"])

            by_name = {c["canonical_name"]: c for c in payload["candidates"]}
            self.assertTrue(all(c["canonical_id"].startswith("C-PROP-") for c in payload["candidates"]))
            # the plural near-duplicate surfaces a dup_warning against the frozen topic
            self.assertIn("Notification Preferences", by_name)
            self.assertTrue(any(w["canonical_id"] == "C-0001" for w in by_name["Notification Preferences"]["dup_warning"]))
            # a genuinely new topic has no dup_warning
            self.assertEqual(by_name["Bulk SMS Throttling"]["dup_warning"], [])


if __name__ == "__main__":
    unittest.main()
