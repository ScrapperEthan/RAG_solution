from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

from backend.ingest.chunk import chunk_page
from backend.schemas.validation import validate_card, validate_map_page


ROOT = Path(__file__).resolve().parents[2]


class PipelineDemoTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        subprocess.run(
            [sys.executable, "-m", "backend.pipeline", "demo"],
            cwd=str(ROOT),
            check=True,
            capture_output=True,
            text=True,
        )

    def test_dm_card_has_conflict_and_new_batch_size(self) -> None:
        card = json.loads((ROOT / "outputs" / "cards" / "DM_Plugin.json").read_text(encoding="utf-8"))
        config = next(field for field in card["fields"] if field["field"] == "config")
        self.assertIn("batch_size: 1000", config["value"])
        self.assertTrue(config["conflict"])

    def test_review_queue_contains_known_items(self) -> None:
        text = (ROOT / "outputs" / "review_queue.jsonl").read_text(encoding="utf-8")
        self.assertIn("RQ-0011", text)
        self.assertIn("RQ-0019", text)
        self.assertIn("batch_size conflict", text)

    def test_eval_report_has_agentic_variant(self) -> None:
        report = json.loads((ROOT / "outputs" / "eval_report.json").read_text(encoding="utf-8"))
        variant_ids = {variant["id"] for variant in report["variants"]}
        self.assertIn("A1", variant_ids)
        self.assertEqual(report["golden"]["size"], 15)

    def test_chroma_config_retrieves_after_demo(self) -> None:
        subprocess.run(
            [sys.executable, "-m", "backend.pipeline", "demo", "--config", "config.chroma.yaml"],
            cwd=str(ROOT),
            check=True,
            capture_output=True,
            text=True,
        )
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "backend.pipeline",
                "retrieve",
                "--config",
                "config.chroma.yaml",
                "--query",
                "DM plugin default batch_size?",
            ],
            cwd=str(ROOT),
            check=True,
            capture_output=True,
            text=True,
        )
        payload = json.loads(result.stdout)
        self.assertTrue(payload["hits"])


class ChunkingAndSchemaTest(unittest.TestCase):
    def test_chunker_ignores_headings_inside_code_fences(self) -> None:
        page = raw_page(
            "## Real Section\nText before code.\n\n```text\n## Not a heading\n```\n\nMore text.\n## Second Section\nDone."
        )
        sections = chunk_page(page)
        self.assertEqual([section["heading_path"][-1] for section in sections], ["Real Section", "Second Section"])

    def test_chunker_splits_large_sections_at_block_boundaries(self) -> None:
        body = "## Big Section\n" + "\n\n".join(f"Paragraph {idx} " + ("word " * 12) for idx in range(12))
        sections = chunk_page(raw_page(body), {"max_tokens": 50, "overlap_tokens": 10})
        self.assertGreater(len(sections), 1)
        self.assertTrue(all("(part " in section["heading_path"][-1] for section in sections))

    def test_map_schema_rejects_unknown_tier(self) -> None:
        page = json.loads((ROOT / "outputs" / "map" / "map_123456.json").read_text(encoding="utf-8"))
        page["sections"][0]["tier"] = "guessed"
        with self.assertRaises(ValueError):
            validate_map_page(page)

    def test_card_schema_rejects_pointer_without_pointer_target(self) -> None:
        card = json.loads((ROOT / "outputs" / "cards" / "DM_Plugin.json").read_text(encoding="utf-8"))
        pointer = next(field for field in card["fields"] if field["tier"] == "pointer-only")
        pointer.pop("pointer_to", None)
        with self.assertRaises(ValueError):
            validate_card(card)


def raw_page(body: str) -> dict:
    return {
        "page_id": "T-001",
        "title": "Test Page",
        "space": "TEST",
        "source_url": "https://example.test",
        "owner": "tester",
        "labels": [],
        "captured_at": "2026-06-04T00:00:00Z",
        "update_at": "2026-06-04T00:00:00Z",
        "confluence_version": 1,
        "tree_path": ["Root"],
        "body_md": body,
    }


if __name__ == "__main__":
    unittest.main()
