from __future__ import annotations

import json
import subprocess
import sys
import unittest
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from backend.web import create_app, stream_chunks


ROOT = Path(__file__).resolve().parents[2]


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

    def test_golden_endpoint_returns_questions_and_modules(self) -> None:
        response = self.client.get("/api/golden")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(len(payload["items"]), 15)
        self.assertTrue(payload["modules"])

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
        self.assertIn("1000", result["answer"])
        self.assertEqual(result["execution"]["path"], "agentic-card-direct")
        self.assertEqual(result["execution"]["evidence_kind"], "card")
        self.assertTrue(result["card_evidence"])

    def test_pure_rag_returns_ranked_retrieval_evidence(self) -> None:
        result = self.stream_result({"query": "What is the DM plugin?", "answer_mode": "pure-rag"})
        self.assertEqual(result["execution"]["path"], "rag-retrieval")
        self.assertEqual(result["execution"]["evidence_kind"], "retrieval")
        self.assertTrue(result["evidence_sections"])
        self.assertIsInstance(result["evidence_sections"][0]["score"], float)

    def test_agentic_concept_can_answer_from_card_without_retrieval(self) -> None:
        result = self.stream_result({"query": "What is the DM plugin?", "answer_mode": "agentic"})
        self.assertEqual(result["execution"]["path"], "agentic-card-direct")
        self.assertEqual(result["execution"]["evidence_kind"], "card")
        self.assertTrue(result["card_evidence"])
        self.assertEqual(result["evidence_sections"], [])

    def test_agentic_chinese_concept_does_not_drill_on_generic_plugin_token(self) -> None:
        result = self.stream_result({"query": "DM plugin 是干嘛的?", "answer_mode": "agentic"})
        self.assertEqual(result["execution"]["path"], "agentic-card-direct")
        self.assertFalse(result["execution"]["drilled"])

    def test_card_grounding_returns_sources_without_retrieval_scores(self) -> None:
        result = self.stream_result({"query": "What is the DM plugin?", "answer_mode": "card-grounding"})
        self.assertEqual(result["execution"]["path"], "card-grounding")
        self.assertEqual(result["execution"]["family"], "llm-wiki")
        self.assertEqual(result["execution"]["evidence_kind"], "source")
        self.assertTrue(result["evidence_sections"])
        self.assertIsNone(result["evidence_sections"][0]["score"])

    def test_llm_direct_does_not_claim_local_evidence(self) -> None:
        result = self.stream_result({"query": "What is the DM plugin?", "answer_mode": "llm-direct"})
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
