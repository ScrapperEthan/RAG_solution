"""Regression checks for handoff/23's frontend clarity contract."""

from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
INDEX = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
APP = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
STYLE = (ROOT / "frontend" / "style.css").read_text(encoding="utf-8")
CARDS = (ROOT / "frontend" / "cards.html").read_text(encoding="utf-8")
FLOW = (ROOT / "frontend" / "flow.html").read_text(encoding="utf-8")
OFFLINE_DEMO = (ROOT / "frontend" / "offline-demo.js").read_text(encoding="utf-8")
DEBUG_PANEL = (ROOT / "frontend" / "debug-panel.js").read_text(encoding="utf-8")


class FrontendClarityTest(unittest.TestCase):
    def test_card_mode_hints_match_the_approved_copy(self) -> None:
        self.assertIn('<small id="cardModeHint" class="card-mode-hint"></small>', INDEX)
        self.assertIn(
            "答案直接取自卡片里 reduce 已提炼的字段值，不回原文。快、像查词条；精确值受卡片保真度限制。",
            APP,
        )
        self.assertIn(
            "卡片只用来定位主题，答案回到 Confluence 原文段落由 LLM 重新生成，可逐句追溯。适合精确值/有争议的问题。",
            APP,
        )
        self.assertIn('el("cardModeSelect").addEventListener("change"', APP)
        self.assertIn("updateCardModeHint();", APP)

    def test_evidence_provenance_has_all_four_states_and_drill_badge(self) -> None:
        self.assertIn('id="evidenceProvenance"', INDEX)
        for copy in (
            "证据来源：卡片字段（未回原文）",
            "证据来源：原文段落（已回原文取证）",
            "证据来源：全库检索（RAG，未经卡片）",
            "无可验证证据",
            "是否回原文：",
        ):
            self.assertIn(copy, APP)
        for css_class in ("is-card", "is-source", "is-retrieval", "is-none", "is-drill"):
            self.assertIn(css_class, STYLE)

    def test_visible_llm_wiki_copy_was_renamed(self) -> None:
        self.assertNotIn("LLM + Wiki", INDEX)
        self.assertNotIn("LLM + Wiki", APP)
        self.assertNotIn("LLM + Wiki", FLOW)
        self.assertIn("卡片库（审批卡）", INDEX)
        self.assertIn("卡片库（审批卡）", APP)

    def test_internal_family_and_answer_mode_contract_is_unchanged(self) -> None:
        self.assertIn('data-answer-family="llm-wiki"', INDEX)
        self.assertIn('<option value="card-direct">', INDEX)
        self.assertIn('<option value="card-grounding">', INDEX)
        self.assertIn('if (state.answerFamily === "rag") return "pure-rag";', APP)
        self.assertIn('if (state.answerFamily === "llm-wiki") return el("cardModeSelect").value;', APP)
        self.assertIn('if (state.answerFamily === "llm-direct") return "llm-direct";', APP)
        self.assertIn("answer_mode: selectedAnswerMode()", APP)

    def test_each_page_explains_its_unique_role(self) -> None:
        self.assertIn("主问答页：同一问题在 基线 / RAG / 卡片库 三族下的回答", INDEX)
        self.assertIn("演示一次回答的下钻路径", CARDS)
        self.assertIn("不是</u>主问答页", CARDS)

    def test_index_has_a_complete_backend_free_demo_fallback(self) -> None:
        self.assertIn('<script src="./offline-demo.js"></script>', INDEX)
        self.assertIn('<span id="demoTip">', INDEX)
        self.assertIn("activateOfflineDemo(error.message);", APP)
        self.assertIn("if (state.offlineDemo)", APP)
        self.assertIn("await runOfflineQuestion(request);", APP)
        self.assertIn("state.report = window.OFFLINE_DEMO.report;", APP)
        self.assertIn("脱敏离线演示", APP)
        for copy in ("我每年有几天年假？", "请假申请规则", "D-004", "offline-demo-hash"):
            self.assertIn(copy, OFFLINE_DEMO)
        self.assertIn(".system-status.is-demo", STYLE)

    def test_offline_demo_moves_slowly_and_highlights_the_active_step(self) -> None:
        self.assertIn("const offlineDemoTiming", APP)
        self.assertIn("stepHold: 1600", APP)
        self.assertIn('renderExecutionTrace(result.execution, { activeIndex: index, completedCount: index });', APP)
        self.assertIn('setStatus("working", `步骤 ${index + 1}/${steps.length} · 进行中`);', APP)
        self.assertIn('aria-current="step"', APP)
        for css_class in (".trace-step.is-active", ".trace-step.is-complete", ".trace-step.is-pending"):
            self.assertIn(css_class, STYLE)

    def test_debug_panel_renders_card_then_rag_fallback_as_two_stage_chain(self) -> None:
        for copy in (
            "Card Drilldown Attempt",
            "Fallback Retrieval",
            "卡片下钻失败 → RAG 回退链路",
            "已尝试，返回 NO_ANSWER",
            "该卡覆盖不全",
            "RAG 救场命中",
        ):
            self.assertIn(copy, DEBUG_PANEL)
        self.assertIn('endsWith("-then-rag-fallback")', DEBUG_PANEL)
        self.assertIn("debug?.drilldown && debug?.retrieval", DEBUG_PANEL)
        self.assertIn("tag 加权", DEBUG_PANEL)
        self.assertIn("boost_domains", DEBUG_PANEL)

    def test_cards_page_renders_two_stage_fallback_and_marks_gap(self) -> None:
        self.assertNotIn("<script src=", CARDS.lower())
        self.assertIn("Card Drilldown Attempt", CARDS)
        self.assertIn("Fallback Retrieval", CARDS)
        self.assertIn("agentic-source-drilldown-then-rag-fallback", CARDS)
        self.assertIn("Card drilldown returned NO_ANSWER", CARDS)
        self.assertIn("该卡 source 覆盖不全", CARDS)
        self.assertIn("fallback-gap", CARDS)
        self.assertIn("result?.debug?.drilldown && result?.debug?.retrieval", APP)
        self.assertIn("card-grounding-then-rag-fallback", APP)

    def test_frontend_renders_sibling_card_hop_as_two_stage_chain(self) -> None:
        for path in (
            "card-grounding-then-sibling-card",
            "agentic-source-drilldown-then-sibling-card",
        ):
            self.assertIn(path, APP)
        for copy in (
            'endsWith("-then-sibling-card")',
            "同 tag 兄弟卡",
            "顺 tag 跳到",
            "非原始路由卡",
        ):
            self.assertIn(copy, APP)
            self.assertIn(copy, CARDS)
        for copy in (
            "Original Card Drilldown Attempt",
            "Sibling Card Hit",
            "two-stage sibling-card",
            "同 tag 兄弟卡命中",
        ):
            self.assertIn(copy, DEBUG_PANEL)
            self.assertIn(copy, CARDS)


if __name__ == "__main__":
    unittest.main()
