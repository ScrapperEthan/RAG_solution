"""Contract for the live conflict-review panel on the approve page (handoff/35)."""

from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
APPROVE = (ROOT / "frontend" / "approve.html").read_text(encoding="utf-8")


class ApproveConflictPanelTest(unittest.TestCase):
    def test_panel_pulls_and_resolves_conflicts_against_the_backend(self) -> None:
        self.assertIn('id="conflictsPanel"', APPROVE)
        self.assertIn('id="cfList"', APPROVE)
        self.assertIn('id="cfCount"', APPROVE)
        self.assertIn("/api/conflicts", APPROVE)
        self.assertIn("/api/conflicts/resolve", APPROVE)
        self.assertIn('"approve-ui"', APPROVE)  # decisions are attributed
        # Stays self-contained (no external scripts), like the rest of the app.
        self.assertNotIn("<script src=", APPROVE.lower())

    def test_conflicts_are_highlighted_red_with_llm_advice(self) -> None:
        # Red, prominent styling that fires until a decision is frozen.
        self.assertIn(".cf{border:1px solid var(--red);border-left:6px solid var(--red)", APPROVE)
        self.assertIn(".cf.is-resolved", APPROVE)  # green once resolved
        self.assertIn("cf-badge risk-", APPROVE)
        for copy in ("字段冲突复核", "大模型建议", "采纳建议并冻结", "系统暂取最新", "已写入冻结账本"):
            self.assertIn(copy, APPROVE)

    def test_stale_decisions_reopen_loudly(self) -> None:
        self.assertIn('r.status === "stale"', APPROVE)
        self.assertIn("需复核 · 有新值", APPROVE)


if __name__ == "__main__":
    unittest.main()
