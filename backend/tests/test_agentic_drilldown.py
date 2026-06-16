from __future__ import annotations

import unittest

from backend.agentic.service import AgenticService, with_execution


def _service_with_refs(refs):
    # Bypass __init__ (which reads outputs/) to unit-test refs_for_card in isolation.
    svc = AgenticService.__new__(AgenticService)
    svc.refs = refs
    svc.cards = {}
    return svc


class RefsForCardTest(unittest.TestCase):
    def test_card_section_ids_keeps_fact_subsection_field_order(self):
        card = {
            "subsections": [
                {
                    "name": "Specific",
                    "source_section_ids": ["P#Sub"],
                    "facts": [{"field": "x", "label": "X", "source_section_ids": ["P#Fact"]}],
                },
            ],
            "fields": [{"field": "summary", "source_section_ids": ["P#Field"]}],
        }
        rows = _service_with_refs({})._card_section_ids(card)
        self.assertEqual([row["origin"] for row in rows], ["fact", "subsection", "field"])
        self.assertEqual([row["section_id"] for row in rows], ["P#Fact", "P#Sub", "P#Field"])

    def test_resolves_full_path_section_ids_from_subsections_and_fields(self):
        refs = {
            "P#A > B > Leaf": {"section_id": "P#A > B > Leaf", "body_md": "leaf body"},
            "P#A > Overview": {"section_id": "P#A > Overview", "body_md": "overview body"},
        }
        card = {
            "subsections": [
                {"source_section_ids": ["P#A > B > Leaf"], "facts": [{"source_section_ids": ["P#A > B > Leaf"]}]},
            ],
            "fields": [{"source_section_ids": ["P#A > Overview"]}],
        }
        refs_out = _service_with_refs(refs).refs_for_card(card)
        ids = {r["section_id"] for r in refs_out}
        self.assertEqual(ids, {"P#A > B > Leaf", "P#A > Overview"})

    def test_leaf_only_key_would_not_resolve(self):
        # Guards the regression: the old code built "{page}#{anchor.split(' > ')[-1]}"
        # (e.g. "P#Leaf"), which is absent from the full-path-keyed loaded_refs.
        refs = {"P#A > B > Leaf": {"section_id": "P#A > B > Leaf", "body_md": "x"}}
        card = {"subsections": [{"source_section_ids": ["P#A > B > Leaf"], "facts": []}], "fields": []}
        self.assertEqual(len(_service_with_refs(refs).refs_for_card(card)), 1)
        self.assertNotIn("P#Leaf", refs)

    def test_no_source_ids_returns_empty(self):
        card = {"subsections": [{"source_section_ids": [], "facts": []}], "fields": []}
        self.assertEqual(_service_with_refs({}).refs_for_card(card), [])

    def test_debug_drilldown_reports_missed_section_ids(self):
        refs = {"P#Hit": {"section_id": "P#Hit", "body_md": "hit"}}
        card = {
            "subsections": [
                {"source_section_ids": ["P#Miss"], "facts": [{"source_section_ids": ["P#Hit"]}]},
            ],
            "fields": [],
        }
        debug = _service_with_refs(refs)._debug_drilldown(card, [refs["P#Hit"]])
        self.assertEqual(debug["resolved_section_ids"], ["P#Hit"])
        self.assertEqual(debug["missed_section_ids"], ["P#Miss"])
        self.assertEqual(debug["counts"]["capped_to"], 1)


class WithExecutionDiagnosticTest(unittest.TestCase):
    def test_empty_source_evidence_surfaces_diagnostic(self):
        result = with_execution(
            {"answer": "NO_ANSWER", "evidence_sections": []},
            requested_mode="agentic",
            path="agentic-source-drilldown",
            evidence_kind="source",
            steps=["Match approved canonical card"],
            card={"canonical_id": "C-1", "canonical_name": "X", "module": []},
        )
        self.assertTrue(result["diagnostic"])
        self.assertEqual(result["execution"]["diagnostic"], result["diagnostic"])
        self.assertTrue(any("0 条原文" in step for step in result["execution"]["steps"]))

    def test_present_evidence_has_no_diagnostic(self):
        result = with_execution(
            {"answer": "ok", "evidence_sections": [{"section_id": "P#A > B"}]},
            requested_mode="agentic",
            path="card-grounding",
            evidence_kind="source",
            steps=["step"],
            card=None,
        )
        self.assertIsNone(result["diagnostic"])


if __name__ == "__main__":
    unittest.main()
