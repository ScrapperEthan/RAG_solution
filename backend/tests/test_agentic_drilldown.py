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

    def test_query_ranks_relevant_section_first_without_dropping(self):
        # Document order puts the off-topic section first; a query about the
        # second section must float it up so the answerer sees it before the cap,
        # but NO section is dropped (ranking only reorders).
        refs = {
            "P#A > Timeout": {"section_id": "P#A > Timeout", "title": "Timeout", "body_md": "connection timeout settings"},
            "P#A > Retry": {"section_id": "P#A > Retry", "title": "Retry", "body_md": "max_retry default is 3"},
        }
        card = {
            "subsections": [
                {"source_section_ids": ["P#A > Timeout"], "facts": []},
                {"source_section_ids": ["P#A > Retry"], "facts": []},
            ],
            "fields": [],
        }
        svc = _service_with_refs(refs)
        ranked = svc.refs_for_card(card, "what is the max_retry default")
        self.assertEqual([r["section_id"] for r in ranked], ["P#A > Retry", "P#A > Timeout"])
        # No query -> document order preserved (back-compat with existing callers).
        unranked = svc.refs_for_card(card)
        self.assertEqual([r["section_id"] for r in unranked], ["P#A > Timeout", "P#A > Retry"])

    def test_cjk_and_enumerate_query_preserve_full_set_in_order(self):
        # A CJK-only query has no latin tokens -> every cell scores 0 -> the full
        # matrix is kept in document order (handoff/28 enumeration contract).
        refs = {
            "P#C > SMS": {"section_id": "P#C > SMS", "title": "SMS", "body_md": "SMS via telecom A"},
            "P#C > Email": {"section_id": "P#C > Email", "title": "Email", "body_md": "Email via SMTP"},
            "P#C > PN": {"section_id": "P#C > PN", "title": "PN", "body_md": "Push via APNS"},
        }
        card = {
            "subsections": [
                {"source_section_ids": ["P#C > SMS"], "facts": []},
                {"source_section_ids": ["P#C > Email"], "facts": []},
                {"source_section_ids": ["P#C > PN"], "facts": []},
            ],
            "fields": [],
        }
        ranked = _service_with_refs(refs).refs_for_card(card, "支持哪些渠道")
        self.assertEqual([r["section_id"] for r in ranked], ["P#C > SMS", "P#C > Email", "P#C > PN"])


class WithExecutionDiagnosticTest(unittest.TestCase):
    def test_empty_source_evidence_surfaces_diagnostic(self):
        result = with_execution(
            {"answer": "NO_ANSWER", "evidence_sections": []},
            requested_mode="agentic",
            path="agentic-source-drilldown",
            evidence_kind="source",
            steps=["Match approved canonical card"],
            card={"canonical_id": "C-1", "canonical_name": "X", "domains": []},
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


class _StubAnswerer:
    """Grounds an answer only when a ref body carries the ANSWER_HERE marker;
    otherwise refuses with NO_ANSWER (mirrors the real grounded answerer)."""

    def answer_from_refs(self, query, refs):
        text = " ".join(r.get("body_md", "") for r in refs)
        answer = "found it" if "ANSWER_HERE" in text else "NO_ANSWER — not grounded"
        return {"answer": answer, "citations": [], "retrieved_section_ids": [], "contexts": []}


class _StubRetriever:
    def __init__(self, refs):
        self._refs = refs
        self.called = False
        self.last_kwargs = None

    def retrieve(self, query, **kwargs):
        self.called = True
        self.last_kwargs = kwargs
        return self._refs


_FALLBACK_CARD = {
    "canonical_id": "C-1",
    "canonical_name": "Rate limit",
    "domains": [],
    # A real, resolvable source section that does NOT contain the asked value:
    # refs_for_card returns it (non-empty), but the answerer still refuses.
    "subsections": [{"name": "s", "source_section_ids": ["P#A > B"], "facts": []}],
    "fields": [],
}


def _fallback_service(card_section_body, rag_refs):
    svc = AgenticService.__new__(AgenticService)
    svc.cards = {}
    svc.refs = {"P#A > B": {"section_id": "P#A > B", "body_md": card_section_body}}
    svc.answerer = _StubAnswerer()
    svc.retriever = _StubRetriever(rag_refs)
    return svc


class DrilldownFallbackTest(unittest.TestCase):
    def test_no_answer_from_card_falls_back_to_rag(self):
        rag_refs = [{"section_id": "P#X > Y", "body_md": "ANSWER_HERE 200/sec", "source_url": "u", "heading_path": []}]
        svc = _fallback_service("irrelevant body", rag_refs)
        result = svc._drilldown_with_fallback(
            query="rate limit?",
            card=_FALLBACK_CARD,
            routing={"method": "llm-router"},
            source="card-grounding",
            path="card-grounding",
            steps=["Match approved canonical card"],
            intent=None,
            variant={},
            filters=None,
            debug=True,
        )
        self.assertEqual(result["answer"], "found it")
        self.assertTrue(svc.retriever.called)
        self.assertEqual(result["execution"]["path"], "card-grounding-then-rag-fallback")
        self.assertEqual(result["evidence_sections"], rag_refs)
        # The failed card drilldown stays visible so under-built cards are diagnosable.
        self.assertEqual(result["debug"]["drilldown"]["resolved_section_ids"], ["P#A > B"])
        self.assertTrue(any("NO_ANSWER" in step for step in result["execution"]["steps"]))

    def test_grounded_card_answer_never_touches_rag(self):
        rag_refs = [{"section_id": "P#X > Y", "body_md": "ANSWER_HERE", "source_url": "u", "heading_path": []}]
        svc = _fallback_service("ANSWER_HERE in the card section", rag_refs)
        result = svc._drilldown_with_fallback(
            query="rate limit?",
            card=_FALLBACK_CARD,
            routing={"method": "llm-router"},
            source="card-grounding",
            path="card-grounding",
            steps=["Match approved canonical card"],
            intent=None,
            variant={},
            filters=None,
            debug=False,
        )
        self.assertEqual(result["answer"], "found it")
        self.assertFalse(svc.retriever.called)
        self.assertEqual(result["execution"]["path"], "card-grounding")


_PRIMARY_CARD = {
    "canonical_id": "C-PRI",
    "canonical_name": "请假申请",
    "aliases": [],
    "domains": ["人事服务"],
    "subsections": [{"name": "s", "source_section_ids": ["P#PRI"], "facts": []}],
    "fields": [],
}
_SIBLING_CARD = {
    "canonical_id": "C-SIB",
    "canonical_name": "年假天数",
    "aliases": ["年假"],
    "domains": ["人事服务"],  # shares the tag with the primary card
    "subsections": [{"name": "s", "source_section_ids": ["P#SIB"], "facts": []}],
    "fields": [],
}


def _sibling_service(primary_body, sibling_body, rag_refs):
    svc = AgenticService.__new__(AgenticService)
    svc.refs = {
        "P#PRI": {"section_id": "P#PRI", "body_md": primary_body},
        "P#SIB": {"section_id": "P#SIB", "body_md": sibling_body},
    }
    svc.cards = {"C-PRI": _PRIMARY_CARD, "C-SIB": _SIBLING_CARD}
    svc.answerer = _StubAnswerer()
    svc.retriever = _StubRetriever(rag_refs)
    return svc


def _drill(svc, query, debug=False):
    return svc._drilldown_with_fallback(
        query=query,
        card=_PRIMARY_CARD,
        routing={"method": "llm-router"},
        source="card-grounding",
        path="card-grounding",
        steps=["Match approved canonical card"],
        intent=None,
        variant={},
        filters=None,
        debug=debug,
    )


_RAG = [{"section_id": "P#X", "body_md": "ANSWER_HERE from rag", "source_url": "u", "heading_path": []}]


class DrilldownSiblingTest(unittest.TestCase):
    def test_sibling_card_answers_before_touching_rag(self):
        svc = _sibling_service("primary has no value", "ANSWER_HERE 年假 10 天", _RAG)
        result = _drill(svc, "年假有几天？", debug=True)
        self.assertEqual(result["answer"], "found it")
        self.assertEqual(result["execution"]["path"], "card-grounding-then-sibling-card")
        self.assertEqual(result["execution"]["card"]["canonical_id"], "C-SIB")
        self.assertFalse(svc.retriever.called)  # stayed in the card layer
        self.assertEqual(result["debug"]["card_used"]["canonical_id"], "C-SIB")

    def test_no_relevant_sibling_falls_to_tag_weighted_rag(self):
        svc = _sibling_service("primary has no value", "sibling has no value", _RAG)
        result = _drill(svc, "完全无关 zzz")
        self.assertEqual(result["answer"], "found it")
        self.assertEqual(result["execution"]["path"], "card-grounding-then-rag-fallback")
        self.assertTrue(svc.retriever.called)
        # RAG fallback is tag-weighted by the original card's module.
        self.assertEqual(svc.retriever.last_kwargs.get("boost_domains"), ["人事服务"])

    def test_relevant_sibling_that_also_misses_falls_to_rag_with_note(self):
        svc = _sibling_service("primary has no value", "sibling has no value", _RAG)
        result = _drill(svc, "年假有几天？")  # overlaps the sibling, but its source lacks the answer
        self.assertEqual(result["execution"]["path"], "card-grounding-then-rag-fallback")
        self.assertTrue(any("C-SIB" in step for step in result["execution"]["steps"]))
        self.assertEqual(svc.retriever.last_kwargs.get("boost_domains"), ["人事服务"])


if __name__ == "__main__":
    unittest.main()
