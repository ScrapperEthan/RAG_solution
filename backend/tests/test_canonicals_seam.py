"""Seam regression: load_vocabulary -> normalize_concept must carry topic_class
and subsections through to the reducer (no LLM, no yaml needed).

This is the seam the other reducer tests miss: they hand-build the canonical
dict and feed it to build_card directly, so they never exercise the loader.
A frozen keyword table that declares subsections/topic_class was silently
losing both because normalize_concept did not copy them.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from backend.reducer.canonicals import load_vocabulary, normalize_concept


ROW = {
    "canonical_id": "C-0002",
    "canonical_name": "MDC Management Portal",
    "topic_type": "inventory",
    "topic_class": "system component",
    "subsections": ["Portal link", "UAT Access right", "PROD Access right"],
    "status": "approved",
}


class NormalizeConceptSeam(unittest.TestCase):
    def test_normalize_concept_keeps_topic_class_and_subsections(self):
        concept = normalize_concept(ROW)
        self.assertEqual(concept["topic_class"], "system component")
        self.assertEqual(concept["subsections"], ["Portal link", "UAT Access right", "PROD Access right"])

    def test_normalize_concept_accepts_aliases(self):
        concept = normalize_concept({**ROW, "class": "catalog", "subsection": "only one"})
        # explicit topic_class wins; subsection (singular) alias is accepted
        self.assertEqual(concept["topic_class"], "system component")

    def test_load_vocabulary_carries_fields(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "keyword_table.jsonl"
            path.write_text(
                '{"canonical_id":"C-0002","canonical_name":"MDC Management Portal",'
                '"topic_class":"system component",'
                '"subsections":["Portal link","UAT Access right","PROD Access right"],'
                '"status":"approved"}\n',
                encoding="utf-8",
            )
            vocab = load_vocabulary(path)
            concept = vocab["C-0002"]
            self.assertEqual(concept["topic_class"], "system component")
            self.assertEqual(len(concept["subsections"]), 3)


if __name__ == "__main__":
    unittest.main()
