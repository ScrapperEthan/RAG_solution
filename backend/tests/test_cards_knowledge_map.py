"""Regression checks for handoff/25's cards knowledge-map contract."""

from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CARDS = (ROOT / "frontend" / "cards.html").read_text(encoding="utf-8")


class CardsKnowledgeMapTest(unittest.TestCase):
    def test_view_switch_defaults_to_structure_and_exposes_map_controls(self) -> None:
        self.assertIn('<button id="structureViewBtn" class="is-active"', CARDS)
        self.assertIn('<button id="mapViewBtn"', CARDS)
        self.assertIn('<section id="structureWorkspace" class="workspace">', CARDS)
        self.assertIn('<section id="mapWorkspace" class="map-workspace" hidden>', CARDS)
        self.assertIn('const state = { cards: [], selectedId: null', CARDS)
        self.assertIn('view: "structure", includeModuleEdges: false', CARDS)
        self.assertIn('el("moduleEdgeField").hidden = view !== "map";', CARDS)

    def test_related_component_edges_are_undirected_and_deduplicated(self) -> None:
        self.assertIn('field.field === "related_components"', CARDS)
        self.assertIn('arr(field.soft_links).forEach(target => addEdge(id, String(target), "related"))', CARDS)
        self.assertIn("const pair = [source, target].sort();", CARDS)
        self.assertIn('const key = pair.join("|");', CARDS)
        self.assertIn("if (seen.has(key)) return;", CARDS)
        self.assertIn("if (!ids.has(source) || !ids.has(target) || source === target) return;", CARDS)

    def test_community_coloring_module_fallback_and_legend_are_present(self) -> None:
        self.assertIn("function graphGroups(nodes, edges, explicitCount)", CARDS)
        self.assertIn('return {mode:"module", groups:new Map(nodes.map(node => [node.id, moduleKey(node.card)]))};', CARDS)
        self.assertIn("const labels = new Map(nodes.map(node => [node.id, node.id]));", CARDS)
        self.assertIn('`相关知识组 ${index + 1}`', CARDS)
        self.assertIn('id="moduleEdgeToggle"', CARDS)
        self.assertIn('addEdge(nodes[i].id, nodes[j].id, "module")', CARDS)
        self.assertIn('id="mapLegend" class="map-legend"', CARDS)
        self.assertIn("这些知识卡目前还没有明确关联；仍可点击圆点查看每张卡。", CARDS)

    def test_offline_sample_is_a_plain_language_leave_example(self) -> None:
        for card_id in (
            "C-DEMO-LEAVE-RULES",
            "C-DEMO-LEAVE-FLOW",
            "C-DEMO-LEAVE-BALANCE",
            "C-DEMO-LEAVE-HELP",
        ):
            self.assertIn(card_id, CARDS)
        for copy in ("我每年有几天年假？", "请假申请规则", "请假审批流程", "年假余额查询", "请假问题找谁", "每年 10 天"):
            self.assertIn(copy, CARDS)
        for old_copy in ("Sample Service Support", "Sample Runbook", "Sample Escalation"):
            self.assertNotIn(old_copy, CARDS)
        self.assertIn("const SAMPLE_CARDS = [", CARDS)
        self.assertIn("setCards(structuredClone(SAMPLE_CARDS), true);", CARDS)
        self.assertIn("if (!Array.isArray(cards) || cards.length === 0)", CARDS)
        self.assertIn("useSample(false);", CARDS)
        self.assertNotIn("hsbc", CARDS.lower())

    def test_clicking_map_node_returns_to_structure_and_opens_card(self) -> None:
        self.assertIn('data-map-card-id="${esc(node.id)}"', CARDS)
        self.assertIn("state.selectedId = node.dataset.mapCardId;", CARDS)
        self.assertIn('setView("structure");', CARDS)
        self.assertIn("renderCardList();", CARDS)
        self.assertIn("renderCardDetail();", CARDS)

    def test_map_explains_itself_and_answer_demo_returns_to_structure(self) -> None:
        for copy in (
            "圆点 = 一张知识卡",
            "实线 = 两张卡明确相关",
            "点击圆点 = 查看卡片内容",
            "已切回“结构”",
        ):
            self.assertIn(copy, CARDS)
        self.assertIn('if (!query) return;\n  setView("structure");', CARDS)
        self.assertIn('if (cardId && state.cards.some(card => card.canonical_id === cardId)) state.selectedId = cardId;\n  setView("structure");\n  renderAll();', CARDS)

    def test_map_is_vanilla_and_has_mobile_fallback(self) -> None:
        self.assertNotIn("<script src=", CARDS.lower())
        self.assertNotIn("cdn", CARDS.lower())
        self.assertNotIn("vis.js", CARDS.lower())
        self.assertNotIn("d3.js", CARDS.lower())
        self.assertIn("function layoutGraph(nodes, edges)", CARDS)
        self.assertIn(".knowledge-map, .knowledge-map svg { min-height: 430px; }", CARDS)


if __name__ == "__main__":
    unittest.main()
