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
    unmatched_canonical_item,
)
from backend.schemas.validation import validate_card, validate_review_item


CANON = {
    "C-0001": {
        "canonical_id": "C-0001",
        "canonical_name": "MDC supported notification channels",
        "aliases": ["notification channels"],
        "domains": ["Channel standard"],
        "topic_type": "inventory",
        "topic_class": "catalog",
        "boundary": "MDC 支持的渠道及各渠道属性。",
        "subsections": ["PN", "whatsApp"],
        "status": "approved",
    }
}


def _section(
    heading_path,
    metadata,
    *,
    tier="narrative",
    fact_values=None,
    info_type="reference",
    summary="s",
    page_id="3725",
    confluence_version=31,
    update_at="2026-06-10T00:00:00Z",
):
    return {
        "section_id": page_id + "#" + "_".join(heading_path),
        "page_id": page_id,
        "title": heading_path[0],
        "source_url": "https://wpb/x",
        "confluence_version": confluence_version,
        "update_at": update_at,
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
            "domains": [],
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
            "domains": [],
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

    def test_subsection_same_label_conflict_keeps_newest_and_queues_review(self) -> None:
        old = _section(
            ["MDC Check List", "Channel Matrix", "PN", "SLO"],
            {"table_kind": "matrix", "channel": "PN", "row_key": "PN", "attribute": "SLO"},
            tier="inline-value",
            fact_values=["4h"],
            page_id="old-page",
            confluence_version=4,
            update_at="2026-05-01T00:00:00Z",
        )
        new = _section(
            ["MDC Catalogue", "Channel Matrix", "PN", "SLO"],
            {"table_kind": "matrix", "channel": "PN", "row_key": "PN", "attribute": "SLO"},
            tier="inline-value",
            fact_values=["8h"],
            page_id="new-page",
            confluence_version=8,
            update_at="2026-06-01T00:00:00Z",
        )

        card, queue = build_card("C-0001", [old, new], CANON)

        conflict = next(item for item in queue if item["type"] == "fact-conflict")
        validate_review_item(conflict)
        self.assertTrue(any(option.startswith("4h (old-page, v4") for option in conflict["options"]))
        self.assertTrue(any(option.startswith("8h (new-page, v8") for option in conflict["options"]))
        pn = next(subsection for subsection in card["subsections"] if subsection["name"] == "PN")
        slo = [fact for fact in pn["facts"] if fact["label"] == "SLO"]
        self.assertEqual([fact["value"] for fact in slo], ["8h"])
        self.assertIn("subsection 'PN' label 'SLO' has conflicting values", card["flags"])

    def test_subsection_same_label_same_value_does_not_queue_conflict(self) -> None:
        first = _section(
            ["MDC Check List", "Channel Matrix", "PN", "SLO"],
            {"table_kind": "matrix", "channel": "PN", "row_key": "PN", "attribute": "SLO"},
            tier="inline-value",
            fact_values=["4h"],
            page_id="page-a",
            confluence_version=4,
            update_at="2026-05-01T00:00:00Z",
        )
        second = _section(
            ["MDC Catalogue", "Channel Matrix", "PN", "SLO"],
            {"table_kind": "matrix", "channel": "PN", "row_key": "PN", "attribute": "SLO"},
            tier="inline-value",
            fact_values=["4h"],
            page_id="page-b",
            confluence_version=5,
            update_at="2026-06-01T00:00:00Z",
        )

        card, queue = build_card("C-0001", [first, second], CANON)

        self.assertFalse(any(item["type"] == "fact-conflict" for item in queue))
        self.assertFalse(any("conflicting values" in flag for flag in card["flags"]))

    def test_subsection_conflict_normalizes_label_and_has_stable_queue_id(self) -> None:
        upper = _section(
            ["MDC Check List", "Channel Matrix", "PN", "SLO"],
            {"table_kind": "matrix", "channel": "PN", "row_key": "PN", "attribute": "SLO"},
            tier="inline-value",
            fact_values=["4h"],
            page_id="upper-page",
            confluence_version=4,
            update_at="2026-05-01T00:00:00Z",
        )
        lower = _section(
            ["MDC Catalogue", "Channel Matrix", "PN", "slo"],
            {"table_kind": "matrix", "channel": "PN", "row_key": "PN", "attribute": " slo "},
            tier="inline-value",
            fact_values=["8h"],
            page_id="lower-page",
            confluence_version=8,
            update_at="2026-06-01T00:00:00Z",
        )

        newest_lower_card, newest_lower_queue = build_card("C-0001", [upper, lower], CANON)
        newest_lower_conflict = next(item for item in newest_lower_queue if item["type"] == "fact-conflict")

        upper["update_at"] = "2026-07-01T00:00:00Z"
        newest_upper_card, newest_upper_queue = build_card("C-0001", [upper, lower], CANON)
        newest_upper_conflict = next(item for item in newest_upper_queue if item["type"] == "fact-conflict")

        self.assertEqual(newest_lower_conflict["queue_id"], newest_upper_conflict["queue_id"])
        self.assertEqual(newest_lower_conflict["field"], "PN / slo")
        self.assertEqual(newest_upper_conflict["field"], "PN / SLO")
        newest_lower_pn = next(subsection for subsection in newest_lower_card["subsections"] if subsection["name"] == "PN")
        newest_upper_pn = next(subsection for subsection in newest_upper_card["subsections"] if subsection["name"] == "PN")
        self.assertEqual([fact["value"] for fact in newest_lower_pn["facts"] if fact["label"] == "slo"], ["8h"])
        self.assertEqual([fact["value"] for fact in newest_upper_pn["facts"] if fact["label"] == "SLO"], ["4h"])

    def test_unrouted_facts_surface_as_data_derived_subsection(self) -> None:
        # machine-named subsections don't match the data terms; the inline-value
        # fact must still surface (grouped by its own key), not vanish into
        # keywords_raw_agg.
        canon = {
            "C-9": {
                "canonical_id": "C-9",
                "canonical_name": "Engagement Contacts",
                "aliases": ["contact point"],
                "domains": [],
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

    def test_unmatched_canonical_surfaced_as_valid_review_item(self) -> None:
        item = unmatched_canonical_item("C-0001", CANON["C-0001"])
        validate_review_item(item)  # raises on failure
        self.assertEqual(item["type"], "unmatched-canonical")
        self.assertEqual(item["canonical_id"], "C-0001")
        self.assertEqual(item["near_misses"], [])

    def test_unmatched_canonical_surfaces_near_miss_sections(self) -> None:
        # The topic's alias appears in a section body, but that section's main
        # subject (heading) is something else -> no card, yet the near miss is
        # surfaced so the owner can add an alias/subsection or drop the topic.
        mention = _section(
            ["Other Page", "Overview"],
            {},
            summary="See the notification channels matrix for the full list.",
        )
        self.assertEqual(match_section(mention, CANON), [])
        item = unmatched_canonical_item("C-0001", CANON["C-0001"], [mention])
        validate_review_item(item)
        self.assertTrue(item["near_misses"])
        self.assertEqual(item["near_misses"][0]["anchor"], "Other Page > Overview")
        self.assertIn("notification channels", item["near_misses"][0]["matched_terms"])
        self.assertIn("Other Page > Overview", item["options"][0])

    def test_cleaning_kills_echo_and_junk(self) -> None:
        self.assertNotIn("Q:", clean_narrative_text("Q: portal access right Q: portal access right"))
        self.assertTrue(is_junk_value("-."))
        self.assertTrue(is_junk_value("Getting issue details..."))
        self.assertFalse(is_junk_value("https://x.y/z"))


if __name__ == "__main__":
    unittest.main()
