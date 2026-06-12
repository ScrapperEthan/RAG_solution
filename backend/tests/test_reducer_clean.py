"""Standalone regression for the match-only reducer (no LLM, no yaml needed).

Covers the properties that matter: match-only (no C-AUTO), metadata-routed
subsections filled with real inline-value facts, de-hardcoded flags, unmatched
-> review queue, echo/junk cleaning, and validate_card acceptance.
"""

from __future__ import annotations

import unittest

from backend.reducer.service import (
    build_card,
    clean_narrative_text,
    is_junk_value,
    match_section,
)
from backend.schemas.validation import validate_card


CANON = {
    "C-0001": {
        "canonical_id": "C-0001",
        "canonical_name": "MDC supported notification channels",
        "aliases": ["notification channels"],
        "module": ["Channel standard"],
        "topic_type": "inventory",
        "topic_class": "catalog",
        "boundary": "MDC 支持的渠道及各渠道属性。",
        "subsections": ["PN", "whatsApp"],
        "status": "approved",
    }
}


def _section(heading_path, metadata, *, tier="narrative", fact_values=None, info_type="reference", summary="s"):
    return {
        "section_id": "3725#" + "_".join(heading_path),
        "page_id": "3725",
        "title": heading_path[0],
        "source_url": "https://wpb/x",
        "confluence_version": 31,
        "update_at": "2026-06-10T00:00:00Z",
        "anchor": " > ".join(heading_path),
        "heading_path": heading_path,
        "metadata": metadata,
        "tier": tier,
        "fact_value": "; ".join(fact_values) if fact_values else None,
        "fact_values": fact_values or [],
        "info_type": info_type,
        "confidence": 0.9,
        "keywords_raw": [metadata.get("row_key", ""), metadata.get("attribute", "")],
        "concepts": [metadata.get("row_key", "")],
        "questions_en": ["q?"],
        "questions_zh": ["q？"],
        "summary_en": summary,
        "summary_zh": summary,
        "body_md": summary,
    }


WHATSAPP_CELL = _section(
    ["MDC Check List", "Channel Matrix", "whatsApp", "Delivery Mode"],
    {"table_kind": "matrix", "channel": "whatsApp", "row_key": "whatsApp", "attribute": "Delivery Mode"},
    tier="inline-value",
    fact_values=["https://sapp-cmg.hk.hsbc:8004/login"],
)


class ReducerCleanTest(unittest.TestCase):
    def test_match_is_table_only_no_c_auto(self) -> None:
        self.assertEqual(match_section(WHATSAPP_CELL, CANON), ["C-0001"])
        card, _ = build_card("C-0001", [WHATSAPP_CELL], CANON)
        self.assertEqual(card["canonical_id"], "C-0001")
        self.assertFalse(card["canonical_id"].startswith("C-AUTO"))

    def test_unmatched_section(self) -> None:
        stray = _section(["Other Page", "Misc"], {"table_kind": "matrix", "row_key": "Telex", "channel": "Telex", "attribute": "x"})
        self.assertEqual(match_section(stray, CANON), [])

    def test_image_section_matched_by_keyword_name(self) -> None:
        # an image/screenshot section is OCR'd into one prose blob with many
        # concepts, but its title (a canonical name) sits in keywords_raw.
        canon = dict(CANON)
        canon["C-0004"] = {
            "canonical_id": "C-0004",
            "canonical_name": "Message Path Service Catalogue",
            "aliases": ["message path"],
            "module": [],
            "topic_type": "inventory",
            "topic_class": "catalog",
            "boundary": "",
            "subsections": [],
            "status": "approved",
        }
        section = _section(["MDC Check List", "Image Evidence", "image-evidence-1"], {})
        section["concepts"] = ["messaging paths", "service levels", "cost tiers"]
        section["keywords_raw"] = ["Message Path Service Catalogue", "For transparency, below table ..."]
        self.assertEqual(match_section(section, canon), ["C-0004"])

    def test_matrix_cell_routes_to_row_and_column_topics(self) -> None:
        # a (channel x attribute) cell is evidence for the channel topic AND the
        # attribute topic; winner-take-all used to drop the attribute topic.
        canon = dict(CANON)
        canon["C-0005"] = {
            "canonical_id": "C-0005",
            "canonical_name": "Template Governance and Maintenance",
            "aliases": ["Template Maintenance"],
            "module": [],
            "topic_type": "process",
            "topic_class": "workflow",
            "boundary": "",
            "subsections": ["Template Maintenance"],
            "status": "approved",
        }
        cell = _section(
            ["MDC Check List", "Channel Matrix", "PN", "Template Maintenance"],
            {"table_kind": "matrix", "channel": "PN", "row_key": "PN", "attribute": "Template Maintenance"},
        )
        ids = match_section(cell, canon)
        self.assertIn("C-0001", ids, "row topic (channels) must still match")
        self.assertIn("C-0005", ids, "column topic (template governance) must no longer be starved")

    def test_subsection_filled_with_inline_value(self) -> None:
        card, _ = build_card("C-0001", [WHATSAPP_CELL], CANON)
        subs = {s["name"]: s for s in card["subsections"]}
        self.assertIn("whatsApp", subs)
        facts = subs["whatsApp"]["facts"]
        self.assertTrue(any(f["tier"] == "inline-value" and "sapp-cmg" in (f["value"] or "") for f in facts), facts)
        # an empty subsection still renders gracefully (no stub echo)
        self.assertIn("PN", subs)
        self.assertNotIn(": Q:", subs["whatsApp"]["summary"])

    def test_unrouted_facts_surface_as_data_derived_subsection(self) -> None:
        # machine-named subsections don't match the data terms; the inline-value
        # fact must still surface (grouped by its own key), not vanish into
        # keywords_raw_agg.
        canon = {
            "C-9": {
                "canonical_id": "C-9",
                "canonical_name": "Engagement Contacts",
                "aliases": ["contact point"],
                "module": [],
                "topic_type": "reference",
                "topic_class": "",
                "boundary": "",
                "subsections": ["Application contacts", "Governance contacts"],
                "status": "approved",
            }
        }
        cell = _section(
            ["MDC Check List", "Q&A", "Engagement contact point", "MDC", "Contact Point"],
            {"table_kind": "matrix", "row_key": "MDC", "channel": "MDC", "attribute": "Contact Point"},
            tier="inline-value",
            fact_values=["Joe Z Y JIAN"],
        )
        card, _ = build_card("C-9", [cell], canon)
        subs = {s["name"]: s for s in card["subsections"]}
        self.assertIn("MDC", subs, "unrouted cell surfaces under its own data key")
        self.assertTrue(
            any("Joe Z Y JIAN" in (f.get("value") or "") for f in subs["MDC"]["facts"]),
            subs["MDC"]["facts"],
        )

    def test_no_hardcoded_dmp_or_otp_flags(self) -> None:
        cell = _section(
            ["MDC Check List", "Matrix", "whatsApp", "Info"],
            {"table_kind": "matrix", "channel": "whatsApp", "row_key": "whatsApp", "attribute": "Info"},
            tier="inline-value", fact_values=["DMP"],
        )
        card, _ = build_card("C-0001", [cell], CANON)
        joined = " ".join(card["flags"])
        self.assertNotIn("DMP", joined)
        self.assertNotIn("OTP", joined)

    def test_card_passes_validation(self) -> None:
        card, _ = build_card("C-0001", [WHATSAPP_CELL], CANON)
        validate_card(card)  # raises on failure

    def test_cleaning_kills_echo_and_junk(self) -> None:
        self.assertNotIn("Q:", clean_narrative_text("Q: portal access right Q: portal access right"))
        self.assertTrue(is_junk_value("-."))
        self.assertTrue(is_junk_value("Getting issue details..."))
        self.assertFalse(is_junk_value("https://x.y/z"))


if __name__ == "__main__":
    unittest.main()
