from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from backend.adapters.llm_mock import MockLLM
from backend.adapters.store_pgvector import filter_sql
from backend.ingest.chunk import chunk_page
from backend.reducer.canonicals import canonical_ids_for, load_vocabulary
from backend.reducer.service import ReducerService, merge_config_field
from backend.retrieve.service import Retriever
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

    def test_portal_card_has_inline_links_and_clean_summary(self) -> None:
        card = json.loads((ROOT / "outputs" / "cards" / "MDC_Management_Portal.json").read_text(encoding="utf-8"))
        prod = next(sub for sub in card["subsections"] if sub["name"] == "PROD Access right")
        links = [fact["value"] for fact in prod["facts"] if fact["tier"] == "inline-value"]
        self.assertTrue(any(str(value).startswith("https://mdc-portal-prod") for value in links))
        definition = next(field for field in card["fields"] if field["field"] == "definition")
        self.assertNotIn("covers what-is", definition["value"])
        self.assertIn("MDC Management Portal", definition["value"])

    def test_all_approved_topics_get_cards_without_unmatched(self) -> None:
        cards = json.loads((ROOT / "outputs" / "cards_index.json").read_text(encoding="utf-8"))
        self.assertEqual(len(cards), 7)
        review = (ROOT / "outputs" / "review_queue.jsonl").read_text(encoding="utf-8")
        self.assertNotIn("unmatched-topic", review)
        self.assertNotIn("unmatched-section", review)

    def test_eval_report_has_agentic_variant(self) -> None:
        report = json.loads((ROOT / "outputs" / "eval_report.json").read_text(encoding="utf-8"))
        variant_ids = {variant["id"] for variant in report["variants"]}
        families = {variant["family"] for variant in report["variants"]}
        self.assertIn("A1", variant_ids)
        self.assertEqual(families, {"rag", "llm-wiki", "agentic"})
        self.assertEqual(report["golden"]["size"], 15)
        self.assertEqual(report["judge"], "mock")
        self.assertIn("hash", report["embedding_model"])

    def test_frontend_marks_hash_mock_report_as_demo(self) -> None:
        index = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
        app = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
        self.assertIn("demoBanner", index)
        self.assertIn("familyComparison", index)
        self.assertIn("卡片库（审批卡）", index)
        self.assertNotIn("LLM + Wiki", index)
        self.assertIn("模型直答 · 无 grounding", index)
        self.assertNotIn("answerModeSelect", index)
        self.assertIn("isDemoReport", app)
        self.assertIn('judge === "mock"', app)
        self.assertIn('"llm-direct"', app)
        self.assertNotIn("llm-wiki-direct", app)

    def test_loaded_summaries_use_independent_ids(self) -> None:
        summaries = json.loads((ROOT / "outputs" / "loaded_summaries.json").read_text(encoding="utf-8"))
        self.assertTrue(summaries)
        self.assertTrue(all(str(row["sum_id"]).startswith("s") for row in summaries))
        self.assertTrue(all("ref_id" not in row for row in summaries))
        self.assertTrue(all(row.get("ref_ids") for row in summaries))
        self.assertTrue(all(isinstance(row.get("module"), list) for row in summaries))

    def test_module_is_multivalue_across_card_inverted_and_refs(self) -> None:
        card = json.loads((ROOT / "outputs" / "cards" / "MDC_Management_Portal.json").read_text(encoding="utf-8"))
        self.assertEqual(len(card["module"]), 2)
        inverted = [
            json.loads(line)
            for line in (ROOT / "outputs" / "inverted_index.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        self.assertTrue(all(isinstance(row["module"], list) for row in inverted))
        refs = json.loads((ROOT / "outputs" / "loaded_refs.json").read_text(encoding="utf-8"))
        self.assertTrue(all(isinstance(row["module"], list) for row in refs))

    def test_demo_keeps_every_fixture_page(self) -> None:
        fixture_pages = list((ROOT / "fixtures" / "confluence").glob("*.md"))
        loaded_refs = json.loads((ROOT / "outputs" / "loaded_refs.json").read_text(encoding="utf-8"))
        self.assertEqual(len({row["page_id"] for row in loaded_refs}), len(fixture_pages))

    def test_rerank_variant_changes_at_least_one_ranking(self) -> None:
        report = json.loads((ROOT / "outputs" / "eval_report.json").read_text(encoding="utf-8"))
        changed = any(
            item["per_variant"]["V5"]["retrieved"] != item["per_variant"]["V6"]["retrieved"]
            for item in report["items"]
        )
        self.assertTrue(changed)

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
                "Whatsapp delivery mode?",
                "--filter",
                "module=Q2 - Engagement",
            ],
            cwd=str(ROOT),
            check=True,
            capture_output=True,
            text=True,
        )
        payload = json.loads(result.stdout)
        self.assertTrue(payload["hits"])
        self.assertTrue(all("Q2 - Engagement" in hit["module"] for hit in payload["hits"]))


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
        page = json.loads((ROOT / "outputs" / "map" / "map_9100001.json").read_text(encoding="utf-8"))
        page["sections"][0]["tier"] = "guessed"
        with self.assertRaises(ValueError):
            validate_map_page(page)

    def test_card_schema_rejects_pointer_without_pointer_target(self) -> None:
        card = json.loads((ROOT / "outputs" / "cards" / "Testing_bounce_back_and_retry.json").read_text(encoding="utf-8"))
        pointer = next(field for field in card["fields"] if field["tier"] == "pointer-only")
        pointer.pop("pointer_to", None)
        with self.assertRaises(ValueError):
            validate_card(card)

    def test_merge_config_field_parses_datetime_before_choosing_newest(self) -> None:
        old = section_stub("S > Old", "batch_size: 500", "2026-06-02T08:00:00+08:00", 1)
        new = section_stub("S > New", "batch_size: 1000", "2026-06-02T01:00:00Z", 1)
        field, conflicts = merge_config_field([old, new], {"keywords_raw_agg": []})
        self.assertIn("batch_size: 1000", field["value"])
        self.assertTrue(conflicts)

    def test_vocabulary_loads_only_approved_rows_and_aliases_match(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "keyword_table.jsonl"
            path.write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "canonical_id": "C-1",
                                "topic": "DM Plugin",
                                "aliases": ["DMP", "Data Management"],
                                "module": ["Integration", "Delivery"],
                                "related page": ["P-1"],
                                "status": "approved",
                            }
                        ),
                        json.dumps({"canonical_id": "C-2", "topic": "Draft", "status": "proposed"}),
                    ]
                ),
                encoding="utf-8",
            )
            vocabulary = load_vocabulary(path)
            self.assertEqual(set(vocabulary), {"C-1"})
            self.assertEqual(vocabulary["C-1"]["module"], ["Integration", "Delivery"])
            self.assertEqual(
                canonical_ids_for(
                    {
                        "title": "Data Management Overview",
                        "heading_path": ["Data Management Overview", "Configuration"],
                        "concepts": ["Data Management"],
                        "keywords_raw": ["DMP"],
                    },
                    vocabulary,
                ),
                ["C-1"],
            )

    def test_reduce_reports_unknown_main_subject_without_creating_topic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            outputs = Path(tmp)
            map_dir = outputs / "map"
            map_dir.mkdir(parents=True)
            page = {
                "page_id": "P-NEW",
                "source_url": "https://example.test/new",
                "title": "Quantum Switch",
                "space": "TEST",
                "tree_path": ["Root"],
                "owner": "tester",
                "labels": [],
                "confluence_version": 1,
                "update_at": "2026-06-04T00:00:00Z",
                "captured_at": "2026-06-04T00:00:00Z",
                "page_summary": {
                    "summary_en": "Quantum Switch page.",
                    "summary_zh": "Quantum Switch 页面。",
                    "cross_questions_en": ["What is Quantum Switch?"],
                    "cross_questions_zh": ["Quantum Switch 是什么?"],
                },
                "sections": [
                    {
                        "anchor": "Quantum Switch > Overview",
                        "heading_path": ["Quantum Switch", "Overview"],
                        "concepts": ["Quantum Switch"],
                        "keywords_raw": ["Quantum Switch", "QS"],
                        "info_type": "what-is",
                        "tier": "narrative",
                        "fact_value": None,
                        "pointer_to": None,
                        "has_table": False,
                        "has_image": False,
                        "summary_en": "Defines Quantum Switch.",
                        "summary_zh": "定义 Quantum Switch。",
                        "questions_en": ["What is Quantum Switch?"],
                        "questions_zh": ["Quantum Switch 是什么?"],
                        "confidence": 0.9,
                    }
                ],
            }
            (map_dir / "map_P-NEW.json").write_text(json.dumps(page, ensure_ascii=False), encoding="utf-8")
            ReducerService(outputs, MockLLM(), ROOT / "fixtures" / "keyword_table.jsonl").run()
            cards = json.loads((outputs / "cards_index.json").read_text(encoding="utf-8"))
            self.assertEqual(cards, [])
            review = (outputs / "review_queue.jsonl").read_text(encoding="utf-8")
            self.assertIn("unmatched-section", review)
            self.assertNotIn("new-concept", review)

    def test_summary_hits_expand_to_page_refs(self) -> None:
        store = FakeStore()
        retriever = Retriever(FakeEmbedder(), store)
        refs = retriever.retrieve("integration", top_k=4)
        self.assertEqual([ref["ref_id"] for ref in refs], [1, 2])

    def test_summary_expansion_respects_module_filter(self) -> None:
        store = FakeStore()
        retriever = Retriever(FakeEmbedder(), store)
        refs = retriever.retrieve("integration", top_k=4, filters={"module": "Integration"})
        self.assertEqual([ref["ref_id"] for ref in refs], [1])

    def test_pgvector_module_filter_uses_array_membership(self) -> None:
        where, params = filter_sql({"module": "Integration & API standard", "page_id": "123456", "card_worthy": True})
        self.assertIn("%s = ANY(module)", where)
        self.assertEqual(params, ["Integration & API standard", "page_id", "123456", "card_worthy", "true"])


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
        "module": [],
        "card_worthy": False,
        "body_md": body,
    }


def section_stub(anchor: str, fact_value: str, update_at: str, version: int) -> dict:
    return {
        "anchor": anchor,
        "page_id": anchor.split(" > ", 1)[0],
        "source_url": "https://example.test",
        "confluence_version": version,
        "update_at": update_at,
        "fact_value": fact_value,
        "fact_values": [fact_value],
        "summary_en": "",
        "info_type": "config",
        "tier": "inline-value",
        "confidence": 0.9,
    }


class FakeEmbedder:
    @property
    def dim(self) -> int:
        return 2

    def embed(self, texts, *, kind):
        return [[1.0, 0.0] for _ in texts]


class FakeStore:
    def __init__(self) -> None:
        self.refs = [
            {"ref_id": 1, "section_id": "P#A", "body_md": "A", "module": ["Integration"], "score": 0.0},
            {"ref_id": 2, "section_id": "P#B", "body_md": "B", "module": ["Delivery"], "score": 0.0},
        ]

    def search_vector(self, table, query_vec, k, filters=None):
        if table == "summaries":
            return [{"table": "summaries", "hit_id": "s1", "ref_ids": [1, 2], "score": 1.0, "source": "vector"}]
        return []

    def search_fts(self, table, query_text, k, filters=None):
        return []

    def get_refs(self, ref_ids):
        by_id = {row["ref_id"]: row for row in self.refs}
        return [dict(by_id[ref_id]) for ref_id in ref_ids if ref_id in by_id]


if __name__ == "__main__":
    unittest.main()
