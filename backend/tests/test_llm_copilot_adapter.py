from __future__ import annotations

import unittest

from backend.adapters.llm_copilot import CopilotLLM, CopilotResponseError, _extract_json
from backend.factory import build_llm


class ExtractJsonTest(unittest.TestCase):
    def test_plain_object(self):
        self.assertEqual(_extract_json('{"intent": "exact"}'), {"intent": "exact"})

    def test_json_code_fence(self):
        content = 'here you go:\n```json\n{"canonical_ids": ["C-0001"]}\n```\nhope that helps'
        self.assertEqual(_extract_json(content), {"canonical_ids": ["C-0001"]})

    def test_bare_code_fence(self):
        self.assertEqual(_extract_json('```\n{"answer": "ok"}\n```'), {"answer": "ok"})

    def test_prose_wrapped_object(self):
        content = 'The answer is: {"answer": "Joe Z Y JIAN"} per the source.'
        self.assertEqual(_extract_json(content), {"answer": "Joe Z Y JIAN"})

    def test_braces_inside_strings_do_not_break_carving(self):
        content = 'note {"answer": "use the {placeholder} value"} done'
        self.assertEqual(_extract_json(content), {"answer": "use the {placeholder} value"})

    def test_empty_raises(self):
        with self.assertRaises(CopilotResponseError):
            _extract_json("   ")

    def test_non_object_json_raises(self):
        with self.assertRaises(CopilotResponseError):
            _extract_json("[1, 2, 3]")

    def test_unparseable_raises(self):
        with self.assertRaises(CopilotResponseError):
            _extract_json("the copilot is offline today, sorry")


class FactoryWiringTest(unittest.TestCase):
    def test_factory_returns_copilot_adapter(self):
        config = {"providers": {"llm": "copilot"}, "llm": {"base_url": "https://intranet.example", "model": "copilot"}}
        self.assertIsInstance(build_llm(config), CopilotLLM)

    def test_seam_is_inert_until_opencode_fills_it(self):
        # The transport seam must raise NotImplementedError (not silently no-op),
        # so the external repo never pretends to have a working copilot.
        llm = CopilotLLM({"base_url": "https://intranet.example", "model": "copilot"})
        with self.assertRaises(NotImplementedError):
            llm.complete_json("task: answer_from_context", "{}", schema={"type": "object"})
        with self.assertRaises(NotImplementedError):
            llm.complete_text("task: anything", "hello")


if __name__ == "__main__":
    unittest.main()
