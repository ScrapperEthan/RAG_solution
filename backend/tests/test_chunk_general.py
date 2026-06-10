"""Generality regression for the structure-aware chunker.

Proves the chunker is structure-driven, not page-specific: it works on the MDC
flat page AND on a differently-shaped page (non-channel matrix, a process under a
different title, tables under H2 headings), and leaves plain prose unchanged.

Standalone (only imports backend.ingest.chunk) so it runs without yaml/fastapi.
"""

from __future__ import annotations

import unittest

from backend.ingest.chunk import chunk_page


def _page(body: str) -> dict:
    return {
        "page_id": "P1", "title": "Test Page", "space": "S", "source_url": "u",
        "owner": "o", "labels": [], "captured_at": "t", "update_at": "t",
        "confluence_version": 1, "tree_path": [], "module": [], "card_worthy": True,
        "body_md": body,
    }


def _meta(section: dict) -> dict:
    return section.get("metadata", {})


MDC_BODY = (
    "General Information for the channels that MDC support\n\n"
    "| Channel | Information | Delivery Mode / SLO / RTB Cost |\n"
    "| --- | --- | --- |\n"
    "| PN | push info | real-time |\n"
    "| SMS | sms info | batch nightly |\n"
    "| whatsApp | opt-in via HARO; eric.q.yuan@hsbc.com | real-time mode only, now only support WPB |\n\n"
    "Q: MDC Management Portal access right application and link\n\n"
    "| UAT | Prod |\n"
    "| --- | --- |\n"
    "| UAT Access Right | PROD Access Right |\n"
    "| https://sapp-cmg.hk.hsbc:8004/login | https://pul-mdc-hase.hk.hsbc:8004/login |\n\n"
    "MDC Engagement and Requirement Process\n\n"
    "1. raise engagement ticket by cloning the sample Jira\n"
    "   HSCCM-1 - Authenticate to see issue details\n"
    "2. Create Project confluence\n"
    "3. Create Use Case confluence\n"
    "4. Create use case in portal\n"
    "   a. Basic Information\n"
    "   b. Delivery Channel\n"
    "   c. Optin flag\n"
    "5. Create template in portal\n"
    "   a. Channel: PN/SMS/Email\n"
    "   b. Language: ENG/CHI\n"
    "6. Create message record in governance tool\n"
)

OTHER_BODY = (
    "## Regional SLA\n\n"
    "Latency and cost per region.\n\n"
    "| Region | Latency | Cost |\n"
    "| --- | --- | --- |\n"
    "| APAC | 50ms | $10 |\n"
    "| EMEA | 80ms | $12 |\n\n"
    "## Deployment Runbook\n\n"
    "1. provision cluster\n"
    "2. deploy services\n"
    "   a. api\n"
    "   b. worker\n"
    "3. smoke test\n"
)


class ChunkGeneralityTest(unittest.TestCase):
    def setUp(self) -> None:
        self.mdc = chunk_page(_page(MDC_BODY), {"max_tokens": 0})
        self.other = chunk_page(_page(OTHER_BODY), {"max_tokens": 0})

    def test_matrix_explodes_to_cells_with_metadata(self) -> None:
        matrix = [s for s in self.mdc if _meta(s).get("table_kind") == "matrix"]
        self.assertEqual(len(matrix), 6)
        wa = [s for s in matrix if _meta(s)["channel"] == "whatsApp" and "Delivery Mode" in _meta(s)["attribute"]]
        self.assertTrue(wa)
        self.assertIn("real-time mode only", wa[0]["body_md"])

    def test_url_records_keep_exact_links(self) -> None:
        records = [s for s in self.mdc if _meta(s).get("table_kind") == "record"]
        uat = [s for s in records if "UAT Access Right" in _meta(s).get("row_key", "")]
        self.assertTrue(uat)
        self.assertIn("https://sapp-cmg.hk.hsbc:8004/login", uat[0]["body_md"])

    def test_process_is_hierarchical_not_flattened(self) -> None:
        process = [s for s in self.mdc if _meta(s).get("block") == "process"]
        self.assertEqual(len(process), 6, "6 real steps, not one per line")
        step4 = next(s for s in process if _meta(s)["step"] == "4")
        self.assertIn("a. Basic Information", step4["body_md"])
        self.assertIn("c. Optin flag", step4["body_md"])
        step1 = next(s for s in process if _meta(s)["step"] == "1")
        self.assertIn("HSCCM-1", step1["body_md"], "link detail attaches to its step")
        self.assertFalse(
            any("Authenticate" in _meta(s).get("step_text", "") for s in process),
            "a Jira lock placeholder must not become a fake step",
        )

    def test_generic_non_channel_matrix(self) -> None:
        matrix = [s for s in self.other if _meta(s).get("table_kind") == "matrix"]
        apac = [s for s in matrix if _meta(s).get("row_key") == "APAC" and _meta(s).get("attribute") == "Latency"]
        self.assertTrue(apac, "a Region x Metric matrix must also cell-split")
        self.assertEqual(apac[0]["body_md"], "50ms")
        self.assertEqual(_meta(apac[0])["channel"], "APAC", "row routing key set generically")
        self.assertTrue(any("Regional SLA" in p for p in apac[0]["heading_path"]),
                        "matrix under an H2 heading must be detected (not prefix-gated)")

    def test_process_under_a_different_title(self) -> None:
        process = [s for s in self.other if _meta(s).get("block") == "process"]
        self.assertEqual(len(process), 3, "process detected by structure, not by a hardcoded title")
        step2 = next(s for s in process if _meta(s)["step"] == "2")
        self.assertIn("a. api", step2["body_md"])
        self.assertIn("b. worker", step2["body_md"])

    def test_plain_prose_falls_back_to_headings(self) -> None:
        prose = chunk_page(_page("## Overview\nSome text.\n\n## Details\nMore text.\n"), {"max_tokens": 0})
        self.assertEqual(len(prose), 2)
        self.assertTrue(all(not _meta(s) for s in prose), "prose sections carry no structured metadata")


if __name__ == "__main__":
    unittest.main()
