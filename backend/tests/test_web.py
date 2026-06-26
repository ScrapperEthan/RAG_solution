from __future__ import annotations

import json
import subprocess
import sys
import unittest
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from backend.adapters.llm_mock import MockLLM
from backend.answer.service import AnswerService, should_refuse
from backend.web import card_is_demo, cards_mode, create_app, stream_chunks


ROOT = Path(__file__).resolve().parents[2]


class AnswerRefusalTest(unittest.TestCase):
    """Refusal must be driven by missing evidence, not by hard-coded topics.

    Guards the fix for the old keyword refusal (sms/pricing/monthly cost/多少钱),
    which wrongly refused real, answerable subjects such as the MDC "SMS"
    notification channel whenever they appeared in a grounded question.
    """

    SMS_REF = {
        "section_id": "C-0001#SMS",
        "title": "MDC supported notification channels",
        "heading_path": ["MDC supported notification channels", "SMS"],
        "body_md": "SMS is a supported notification channel.",
        "source_url": "https://example.test/c-0001",
    }

    def test_should_refuse_ignores_topic_keywords_when_refs_exist(self) -> None:
        # SMS / pricing / 多少钱 must NOT force a refusal when evidence is present.
        self.assertFalse(should_refuse("Does MDC support sending SMS?", [self.SMS_REF]))
        self.assertFalse(should_refuse("monthly cost / pricing 多少钱?", [self.SMS_REF]))

    def test_should_refuse_only_when_refs_missing(self) -> None:
        self.assertTrue(should_refuse("Does MDC support sending SMS?", []))
        self.assertFalse(should_refuse("anything", [self.SMS_REF]))

    def test_answer_from_refs_refuses_via_missing_refs(self) -> None:
        answerer = AnswerService(MockLLM())
        refused = answerer.answer_from_refs("Does MDC support sending SMS?", [])
        self.assertTrue(refused["answer"].startswith("NO_ANSWER"))
        answered = answerer.answer_from_refs("Does MDC support sending SMS?", [self.SMS_REF])
        self.assertFalse(answered["answer"].startswith("NO_ANSWER"))


class CardsModeTest(unittest.TestCase):
    """Demo-corpus detection so a real backend can never silently serve mock cards."""

    REAL_SOURCE = {"page_id": "557281", "source_url": "https://confluence.corp.acme.com/x/abc"}

    def test_empty_card_set_is_empty(self) -> None:
        self.assertEqual(cards_mode([]), "empty")

    def test_real_card_has_no_demo_fingerprint(self) -> None:
        real = {"canonical_id": "C-0001", "subsections": [{"facts": [{"sources": [self.REAL_SOURCE]}]}]}
        self.assertFalse(card_is_demo(real))
        self.assertEqual(cards_mode([real]), "real")

    def test_confluence_local_host_is_demo(self) -> None:
        card = {"canonical_id": "C-0001", "fields": [{"sources": [{"page_id": "557281", "source_url": "https://confluence.local/x/abc"}]}]}
        self.assertTrue(card_is_demo(card))
        self.assertEqual(cards_mode([card]), "demo")

    def test_example_test_host_is_demo(self) -> None:
        card = {"canonical_id": "C-0001", "subsections": [{"sources": [{"source_url": "https://example.test/c-0001"}]}]}
        self.assertTrue(card_is_demo(card))

    def test_synthetic_page_id_is_demo(self) -> None:
        card = {"canonical_id": "C-0001", "subsections": [{"facts": [{"sources": [{"page_id": "9100001", "source_url": "https://confluence.corp.acme.com/x"}]}]}]}
        self.assertTrue(card_is_demo(card))

    def test_c_demo_canonical_id_is_demo(self) -> None:
        self.assertTrue(card_is_demo({"canonical_id": "C-DEMO-LEAVE-RULES"}))

    def test_one_demo_card_taints_the_whole_set(self) -> None:
        real = {"canonical_id": "C-0002", "fields": [{"sources": [self.REAL_SOURCE]}]}
        demo = {"canonical_id": "C-DEMO-X"}
        self.assertEqual(cards_mode([real, demo]), "demo")


class ConflictEndpointTest(unittest.TestCase):
    """/api/conflicts feed + /api/conflicts/resolve write-back, isolated outputs."""

    def setUp(self) -> None:
        import yaml

        from backend.adapters.llm_mock import MockLLM as _MockLLM
        from backend.reducer.conflicts import ConflictReviewService
        from backend.reducer.service import conflict_id
        from backend.util import write_json, write_jsonl

        self._tmp = tempfile.TemporaryDirectory()
        self.outputs = Path(self._tmp.name) / "outputs"
        self.outputs.mkdir(parents=True)
        self.cid = conflict_id("C-1", "PN", "SLO")
        write_jsonl(
            self.outputs / "review_queue.jsonl",
            [
                {
                    "queue_id": "RQ-factconflict-C-1-abc",
                    "type": "fact-conflict",
                    "canonical_id": "C-1",
                    "field": "PN / SLO",
                    "detail": "Subsection 'PN' label 'SLO' has 2 conflicting values; temporarily kept newest '8h'.",
                    "options": ["4h (old, v4, 2026-01-01)", "8h (new, v8, 2026-02-01)"],
                    "status": "open",
                    "conflict_id": self.cid,
                    "label": "SLO",
                    "subsection": "PN",
                    "auto_choice": "8h",
                    "candidates": [
                        {"value": "4h", "page_id": "old", "source_url": "u1", "confluence_version": 4, "update_at": "2026-01-01"},
                        {"value": "8h", "page_id": "new", "source_url": "u2", "confluence_version": 8, "update_at": "2026-02-01"},
                    ],
                }
            ],
        )
        write_json(
            self.outputs / "cards_index.json",
            [
                {
                    "canonical_id": "C-1",
                    "canonical_name": "Payment Notify",
                    "subsections": [{"name": "PN", "facts": [{"label": "SLO", "tier": "inline-value", "value": "8h"}], "sources": []}],
                    "fields": [],
                    "flags": ["subsection 'PN' label 'SLO' has conflicting values"],
                }
            ],
        )
        ConflictReviewService(self.outputs, _MockLLM()).run()

        cfg_path = Path(self._tmp.name) / "config.yaml"
        cfg_path.write_text(yaml.safe_dump({"paths": {"outputs_dir": str(self.outputs)}}), encoding="utf-8")
        self.client = TestClient(create_app(str(cfg_path)))

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_conflicts_feed_carries_llm_review_and_open_header(self) -> None:
        response = self.client.get("/api/conflicts")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get("X-Open-Conflicts"), "1")
        records = response.json()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["llm_review"]["risk"], "high")

    def test_health_reports_open_conflict_count(self) -> None:
        payload = self.client.get("/api/health").json()
        self.assertEqual(payload["conflict_count"], 1)
        self.assertEqual(payload["open_conflict_count"], 1)

    def test_resolve_freezes_decision_and_rewrites_card(self) -> None:
        response = self.client.post(
            "/api/conflicts/resolve",
            json={"conflict_id": self.cid, "chosen_value": "4h", "decided_by": "ethan"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["conflict"]["status"], "resolved")
        self.assertEqual(self.client.get("/api/health").json()["open_conflict_count"], 0)
        card = self.client.get("/api/cards").json()[0]
        self.assertEqual(card["subsections"][0]["facts"][0]["value"], "4h")

    def test_resolve_unknown_conflict_is_404(self) -> None:
        response = self.client.post(
            "/api/conflicts/resolve",
            json={"conflict_id": "CF-nope", "chosen_value": "x"},
        )
        self.assertEqual(response.status_code, 404)


class WebDemoTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        subprocess.run(
            [sys.executable, "-m", "backend.pipeline", "demo"],
            cwd=str(ROOT),
            check=True,
            capture_output=True,
            text=True,
        )
        cls.client = TestClient(create_app())

    def test_health_flags_demo_cards(self) -> None:
        payload = self.client.get("/api/health").json()
        self.assertEqual(payload["cards_mode"], "demo")
        self.assertGreater(payload["cards_count"], 0)

    def test_cards_endpoint_advertises_demo_mode_header(self) -> None:
        response = self.client.get("/api/cards")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get("X-Cards-Mode"), "demo")

    def test_golden_endpoint_returns_questions_and_modules(self) -> None:
        response = self.client.get("/api/golden")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(len(payload["items"]), 15)
        self.assertTrue(payload["domains"])

    def test_mock_eval_report_requires_explicit_opt_in(self) -> None:
        blocked = self.client.get("/api/eval-report")
        self.assertEqual(blocked.status_code, 409)
        self.assertEqual(blocked.json()["detail"]["code"], "demo_report_requires_opt_in")
        allowed = self.client.get("/api/eval-report?allow_demo=true")
        self.assertEqual(allowed.status_code, 200)
        self.assertEqual(allowed.json()["judge"], "mock")

    def test_missing_eval_report_is_not_generated_by_web_app(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            outputs = Path(tmp) / "empty-outputs"
            config_path = Path(tmp) / "config.yaml"
            config_path.write_text(
                "\n".join(
                    [
                        "paths:",
                        f'  outputs_dir: "{outputs.as_posix()}"',
                    ]
                ),
                encoding="utf-8",
            )
            client = TestClient(create_app(str(config_path)))
            response = client.get("/api/eval-report?allow_demo=true")
            self.assertEqual(response.status_code, 404)
            self.assertFalse((outputs / "eval_report.json").exists())

    def test_real_eval_report_loads_without_demo_opt_in(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            outputs = Path(tmp) / "real-outputs"
            outputs.mkdir()
            (outputs / "eval_report.json").write_text(
                json.dumps({"embedding_model": "bge-m3", "judge": "gpt-5.5", "variants": []}),
                encoding="utf-8",
            )
            config_path = Path(tmp) / "config.yaml"
            config_path.write_text(
                "\n".join(
                    [
                        "paths:",
                        f'  outputs_dir: "{outputs.as_posix()}"',
                    ]
                ),
                encoding="utf-8",
            )
            client = TestClient(create_app(str(config_path)))
            response = client.get("/api/eval-report")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["judge"], "gpt-5.5")

    def test_golden_chat_stream_includes_gold_tokens_and_result(self) -> None:
        response = self.client.post(
            "/api/chat/stream",
            json={"golden_id": "G-002", "language": "en"},
        )
        self.assertEqual(response.status_code, 200)
        events = [json.loads(line) for line in response.text.splitlines() if line]
        self.assertEqual(events[0]["type"], "meta")
        self.assertEqual(events[0]["golden"]["q_id"], "G-002")
        self.assertTrue(any(event["type"] == "token" for event in events))
        result = next(event["result"] for event in events if event["type"] == "result")
        self.assertIn("real-time", result["answer"])
        self.assertEqual(result["execution"]["path"], "agentic-card-direct")
        self.assertEqual(result["execution"]["evidence_kind"], "card")
        self.assertTrue(result["card_evidence"])
        self.assertNotIn("debug", result)

    def test_debug_chat_stream_includes_recall_chain(self) -> None:
        result = self.stream_result(
            {
                "query": "What is the Delivery Mode for PN?",
                "answer_mode": "card-grounding",
                "debug": True,
            }
        )
        self.assertIn("debug", result)
        debug = result["debug"]
        self.assertEqual(debug["answer_mode"], "card-grounding")
        self.assertEqual(debug["routing"]["chosen_card"], result["execution"]["card"]["canonical_id"])
        self.assertIsNotNone(debug["drilldown"])
        self.assertTrue(debug["drilldown"]["gathered"])
        self.assertTrue(debug["drilldown"]["resolved_section_ids"])
        self.assertIn("missed_section_ids", debug["drilldown"])
        self.assertTrue(debug["refs_used"])
        self.assertIn("body_md", debug["refs_used"][0])
        self.assertIn("subsections", debug["card_used"])

    def test_debug_pure_rag_includes_retrieval_hits(self) -> None:
        result = self.stream_result({"query": "What is the MDC Management Portal?", "answer_mode": "pure-rag", "debug": True})
        self.assertIn("debug", result)
        debug = result["debug"]
        self.assertIsNotNone(debug["retrieval"])
        self.assertTrue(debug["retrieval"]["hits"])
        self.assertIn("score", debug["retrieval"]["hits"][0])
        self.assertIsNone(debug["drilldown"])

    def test_pure_rag_returns_ranked_retrieval_evidence(self) -> None:
        result = self.stream_result({"query": "What is the MDC Management Portal?", "answer_mode": "pure-rag"})
        self.assertEqual(result["execution"]["path"], "rag-retrieval")
        self.assertEqual(result["execution"]["evidence_kind"], "retrieval")
        self.assertTrue(result["evidence_sections"])
        self.assertIsInstance(result["evidence_sections"][0]["score"], float)

    def test_agentic_concept_can_answer_from_card_without_retrieval(self) -> None:
        result = self.stream_result({"query": "What is the MDC Management Portal?", "answer_mode": "agentic"})
        self.assertEqual(result["execution"]["path"], "agentic-card-direct")
        self.assertEqual(result["execution"]["evidence_kind"], "card")
        self.assertTrue(result["card_evidence"])
        self.assertEqual(result["evidence_sections"], [])

    def test_agentic_chinese_concept_does_not_drill_on_generic_plugin_token(self) -> None:
        result = self.stream_result({"query": "MDC Management Portal 是干嘛的?", "answer_mode": "agentic"})
        self.assertEqual(result["execution"]["path"], "agentic-card-direct")
        self.assertFalse(result["execution"]["drilled"])

    def test_card_grounding_returns_sources_without_retrieval_scores(self) -> None:
        result = self.stream_result({"query": "What is the MDC Management Portal?", "answer_mode": "card-grounding"})
        self.assertEqual(result["execution"]["path"], "card-grounding")
        self.assertEqual(result["execution"]["family"], "llm-wiki")
        self.assertEqual(result["execution"]["evidence_kind"], "source")
        self.assertTrue(result["evidence_sections"])
        self.assertIsNone(result["evidence_sections"][0]["score"])

    def test_llm_direct_does_not_claim_local_evidence(self) -> None:
        result = self.stream_result({"query": "What is the MDC Management Portal?", "answer_mode": "llm-direct"})
        self.assertEqual(result["execution"]["path"], "llm-direct")
        self.assertEqual(result["execution"]["family"], "baseline")
        self.assertEqual(result["execution"]["evidence_kind"], "none")
        self.assertEqual(result["evidence_sections"], [])
        self.assertEqual(result["citations"], [])

    def test_unknown_golden_question_is_404(self) -> None:
        response = self.client.post("/api/chat/stream", json={"golden_id": "missing"})
        self.assertEqual(response.status_code, 404)

    def test_stream_chunks_reconstructs_text(self) -> None:
        text = "中文回答 and English answer"
        self.assertEqual("".join(stream_chunks(text, chunk_size=3)), text)

    def stream_result(self, payload):
        response = self.client.post("/api/chat/stream", json=payload)
        self.assertEqual(response.status_code, 200)
        events = [json.loads(line) for line in response.text.splitlines() if line]
        errors = [event for event in events if event["type"] == "error"]
        self.assertEqual(errors, [])
        return next(event["result"] for event in events if event["type"] == "result")


if __name__ == "__main__":
    unittest.main()
