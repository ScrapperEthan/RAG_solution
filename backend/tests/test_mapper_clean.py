"""Deterministic-path regression for the structure-aware mapper.

Covers the parts that run WITHOUT the LLM (structured sections + page summary):
tier assignment, exact inline values, email-not-URL handling, metadata-driven
questions, and a generic (non page-specific) page summary.
"""

from __future__ import annotations

import unittest

from backend.mapper.service import (
    build_page_summary,
    build_structured_section_map,
    extract_inline_values,
    is_atomic_inline_value,
)


def _section(heading_path, body, metadata=None):
    return {
        "section_id": "P#" + "_".join(heading_path),
        "title": heading_path[0],
        "heading_path": heading_path,
        "body_md": body,
        "content_type": "what-is",
        "has_table": False,
        "has_image": False,
        "metadata": metadata or {},
    }


class MapperDeterministicTest(unittest.TestCase):
    def test_matrix_prose_cell_is_narrative(self) -> None:
        sec = _section(
            ["Page", "Channel Matrix", "whatsApp", "Delivery Mode / SLO / RTB Cost"],
            "real-time mode only, now only support WPB",
            {"table_kind": "matrix", "channel": "whatsApp", "row_key": "whatsApp", "attribute": "Delivery Mode / SLO / RTB Cost"},
        )
        m = build_structured_section_map(sec)
        self.assertEqual(m["tier"], "narrative")
        self.assertEqual(m["info_type"], "reference")
        self.assertIn("Delivery Mode", m["summary_en"])
        self.assertIn("whatsApp", m["concepts"])
        self.assertTrue(any("Delivery Mode" in q and "whatsApp" in q for q in m["questions_zh"]))

    def test_record_url_is_inline_value(self) -> None:
        sec = _section(
            ["Page", "Q&A", "portal access", "UAT Access Right"],
            "UAT: https://sapp-cmg.hk.hsbc:8004/login",
            {"table_kind": "record", "row_key": "UAT Access Right", "question": "portal access"},
        )
        m = build_structured_section_map(sec)
        self.assertEqual(m["tier"], "inline-value")
        self.assertIn("https://sapp-cmg.hk.hsbc:8004/login", m["fact_value"])

    def test_email_kept_autolinked_domain_dropped(self) -> None:
        sec = _section(
            ["Page", "Channel Matrix", "whatsApp", "Information"],
            "opt-in via HARO; contact eric.q.yuan@hsbc.com (http://hsbc.com)",
            {"table_kind": "matrix", "channel": "whatsApp", "row_key": "whatsApp", "attribute": "Information"},
        )
        values = extract_inline_values(sec)
        self.assertTrue(any("eric.q.yuan@hsbc.com" in v for v in values), values)
        self.assertNotIn("http://hsbc.com", values)

    def test_long_prose_is_not_inline_value(self) -> None:
        self.assertFalse(is_atomic_inline_value(
            "an API could be provided for retrieving the whatsApp opt-in by mobile number, no bounce back measure"
        ))
        self.assertTrue(is_atomic_inline_value("https://x.y/z"))
        self.assertTrue(is_atomic_inline_value("#HASEsecure"))
        self.assertTrue(is_atomic_inline_value("14 days"))

    def test_process_step_is_how_to_narrative(self) -> None:
        sec = _section(
            ["Page", "Engagement Process", "Step 4: Create use case in portal"],
            "4. Create use case in portal\n   - a. Basic Information\n   - b. Delivery Channel",
            {"block": "process", "step": "4", "step_text": "Create use case in portal"},
        )
        m = build_structured_section_map(sec)
        self.assertEqual(m["info_type"], "how-to")
        self.assertEqual(m["tier"], "narrative")

    def test_page_summary_is_generic(self) -> None:
        mapped = [
            build_structured_section_map(_section(["MDC Check List", "M", "PN", "Info"], "push", {"table_kind": "matrix", "row_key": "PN", "channel": "PN", "attribute": "Info"})),
            build_structured_section_map(_section(["MDC Check List", "Q&A", "q", "UAT"], "UAT: https://x.y/z", {"table_kind": "record", "row_key": "UAT", "question": "q"})),
            build_structured_section_map(_section(["MDC Check List", "Proc", "Step 1: do"], "1. do it", {"block": "process", "step": "1", "step_text": "do"})),
        ]
        ps = build_page_summary({"title": "MDC Check List"}, mapped)
        # generic: derived from data, NOT the old hardcoded "channels / Q&A / engagement process" sentence
        self.assertNotIn("engagement process steps", ps["summary_en"])
        self.assertNotIn("portal links, and engagement endpoints", ps["summary_en"])
        self.assertIn("MDC Check List", ps["summary_en"])
        self.assertTrue(any(k in ps["summary_en"].lower() for k in ("matrix", "record", "process")))
        self.assertIn("PN", ps["summary_en"])  # real entity from the data


if __name__ == "__main__":
    unittest.main()
