from __future__ import annotations

from typing import Dict, Iterable, List


REQUIRED_MAP_PAGE = [
    "page_id",
    "source_url",
    "title",
    "space",
    "tree_path",
    "owner",
    "labels",
    "confluence_version",
    "update_at",
    "captured_at",
    "page_summary",
    "sections",
]

REQUIRED_MAP_SECTION = [
    "anchor",
    "heading_path",
    "concepts",
    "keywords_raw",
    "info_type",
    "tier",
    "fact_value",
    "pointer_to",
    "has_table",
    "has_image",
    "summary_en",
    "summary_zh",
    "questions_en",
    "questions_zh",
    "confidence",
]

REQUIRED_CARD = ["canonical_id", "canonical_name", "aliases", "module", "status", "fields", "flags"]
INFO_TYPES = {"what-is", "how-to", "config", "troubleshoot", "reference", "decision", "meeting-notes"}
TIERS = {"narrative", "inline-value", "pointer-only"}
GOLDEN_TYPES = {"single", "multihop", "identifier-lookup", "pointer-drill", "out-of-scope"}
VARIANT_METRICS = {
    "recall@5",
    "recall@8",
    "mrr",
    "ndcg@8",
    "faithfulness",
    "answer_relevancy",
    "context_precision",
    "context_recall",
    "association_recall",
    "drill_miss_rate",
}

REQUIRED_PER_VARIANT = ["hit@8", "retrieved", "answer", "citations", "faithfulness", "drilled"]


def validate_map_page(page: Dict) -> None:
    require_keys(page, REQUIRED_MAP_PAGE, "map page")
    require_type(page["page_id"], str, "map page.page_id")
    require_type(page["tree_path"], list, "map page.tree_path")
    require_type(page["sections"], list, "map page.sections")
    require_keys(page["page_summary"], ["summary_en", "summary_zh", "cross_questions_en", "cross_questions_zh"], "page_summary")
    for section in page["sections"]:
        require_keys(section, REQUIRED_MAP_SECTION, "map section")
        require_type(section["anchor"], str, "map section.anchor")
        require_type(section["heading_path"], list, "map section.heading_path")
        require_non_empty_list(section["concepts"], "map section.concepts")
        require_non_empty_list(section["keywords_raw"], "map section.keywords_raw")
        require_enum(section["info_type"], INFO_TYPES, "map section.info_type")
        require_enum(section["tier"], TIERS, "map section.tier")
        require_type(section["has_table"], bool, "map section.has_table")
        require_type(section["has_image"], bool, "map section.has_image")
        require_non_empty_list(section["questions_en"], "map section.questions_en")
        require_non_empty_list(section["questions_zh"], "map section.questions_zh")
        require_range(section["confidence"], 0.0, 1.0, "map section.confidence")
        if section["tier"] == "inline-value" and not section["fact_value"]:
            raise ValueError(f"inline-value section missing fact_value: {section['anchor']}")
        if section["tier"] == "pointer-only" and not section["pointer_to"]:
            raise ValueError(f"pointer-only section missing pointer_to: {section['anchor']}")


def validate_card(card: Dict) -> None:
    require_keys(card, REQUIRED_CARD, "card")
    require_type(card["canonical_id"], str, "card.canonical_id")
    require_type(card["canonical_name"], str, "card.canonical_name")
    require_type(card["aliases"], list, "card.aliases")
    require_string_list(card["module"], "card.module")
    require_type(card["fields"], list, "card.fields")
    require_type(card["subsections"], list, "card.subsections")
    for subsection in card["subsections"]:
        require_keys(subsection, ["name", "sources"], "card subsection")
        require_type(subsection["name"], str, "card subsection.name")
        require_type(subsection["sources"], list, "card subsection.sources")
        for source in subsection["sources"]:
            require_keys(source, ["page_id", "anchor", "source_url", "confluence_version"], "card subsection source")
    for field in card["fields"]:
        require_keys(field, ["field", "tier", "value", "sources"], "card field")
        require_enum(field["tier"], TIERS, "card field.tier")
        require_type(field["sources"], list, "card field.sources")
        if field["tier"] == "pointer-only" and not field.get("pointer_to"):
            raise ValueError(f"pointer-only card field missing pointer_to: {card['canonical_id']}:{field['field']}")
        if field["tier"] != "pointer-only" and field.get("value") is None:
            raise ValueError(f"non-pointer card field missing value: {card['canonical_id']}:{field['field']}")
        for source in field["sources"]:
            require_keys(source, ["page_id", "anchor", "source_url", "confluence_version"], "card field source")


def validate_inverted_row(row: Dict) -> None:
    require_keys(
        row,
        ["canonical_id", "canonical_name", "module", "page_id", "anchor", "section_id", "info_type", "tier", "confidence", "confluence_version"],
        "inverted row",
    )
    require_string_list(row["module"], "inverted row.module")
    require_enum(row["info_type"], INFO_TYPES, "inverted row.info_type")
    require_enum(row["tier"], TIERS, "inverted row.tier")
    require_range(row["confidence"], 0.0, 1.0, "inverted row.confidence")


def validate_review_item(item: Dict) -> None:
    require_keys(item, ["queue_id", "type", "canonical_id", "field", "detail", "options", "status"], "review item")
    require_type(item["queue_id"], str, "review item.queue_id")
    require_type(item["detail"], str, "review item.detail")
    require_type(item["options"], list, "review item.options")


def require_keys(payload: Dict, keys: Iterable[str], label: str) -> None:
    missing = [key for key in keys if key not in payload]
    if missing:
        raise ValueError(f"{label} missing required keys: {missing}")


def require_type(value, expected_type, label: str) -> None:
    if not isinstance(value, expected_type):
        raise ValueError(f"{label} must be {expected_type.__name__}")


def require_enum(value: str, allowed: set, label: str) -> None:
    if value not in allowed:
        raise ValueError(f"{label} must be one of {sorted(allowed)}, got {value!r}")


def require_non_empty_list(value, label: str) -> None:
    require_type(value, list, label)
    if not value:
        raise ValueError(f"{label} must not be empty")


def require_string_list(value, label: str) -> None:
    require_type(value, list, label)
    if any(not isinstance(item, str) for item in value):
        raise ValueError(f"{label} must contain only strings")


def require_range(value, low: float, high: float, label: str) -> None:
    if not isinstance(value, (int, float)) or not low <= float(value) <= high:
        raise ValueError(f"{label} must be a number between {low} and {high}")


def validate_golden_items(items: List[Dict]) -> None:
    for item in items:
        require_keys(
            item,
            ["q_id", "q_en", "q_zh", "type", "gold_section_ids", "gold_answer", "human_checked"],
            "golden item",
        )
        require_enum(item["type"], GOLDEN_TYPES, "golden item.type")
        if item["gold_section_ids"] != "NO_ANSWER":
            require_non_empty_list(item["gold_section_ids"], "golden item.gold_section_ids")
        require_type(item["human_checked"], bool, "golden item.human_checked")


def validate_eval_report(report: Dict) -> None:
    require_keys(report, ["run_id", "embedding_model", "judge", "golden", "baseline_id", "variants", "items"], "eval report")
    require_keys(report["golden"], ["size", "by_type", "frozen_hash"], "eval report.golden")
    if not isinstance(report["variants"], list) or not report["variants"]:
        raise ValueError("eval report variants must be a non-empty list")
    require_type(report["items"], list, "eval report.items")
    if report["golden"]["size"] != len(report["items"]):
        raise ValueError("eval report golden.size must match item count")

    variant_ids = []
    for variant in report["variants"]:
        require_keys(
            variant,
            ["id", "label", "index", "search", "rerank", "answer_source", "metrics"],
            "eval report variant",
        )
        variant_ids.append(variant["id"])
        missing_metrics = VARIANT_METRICS - set(variant["metrics"])
        if missing_metrics:
            raise ValueError(f"eval variant missing metrics: {sorted(missing_metrics)}")
        for metric in VARIANT_METRICS:
            value = variant["metrics"][metric]
            if metric in {"association_recall", "drill_miss_rate"} and value is None:
                continue
            if not isinstance(value, (int, float)):
                raise ValueError(f"eval metric {variant['id']}.{metric} must be numeric or null")

    if report["baseline_id"] not in variant_ids:
        raise ValueError("eval report baseline_id must reference a variant id")

    for item in report["items"]:
        require_keys(item, ["q_id", "type", "q", "gold", "gold_answer", "per_variant"], "eval report item")
        require_enum(item["type"], GOLDEN_TYPES, "eval item.type")
        require_type(item["per_variant"], dict, "eval item.per_variant")
        for variant_id in variant_ids:
            if variant_id not in item["per_variant"]:
                raise ValueError(f"eval item {item['q_id']} missing per_variant {variant_id}")
            result = item["per_variant"][variant_id]
            require_keys(result, REQUIRED_PER_VARIANT, f"eval item {item['q_id']} per_variant {variant_id}")
            if not isinstance(result["retrieved"], list):
                raise ValueError(f"eval item {item['q_id']} retrieved must be a list")
            if not isinstance(result["citations"], list):
                raise ValueError(f"eval item {item['q_id']} citations must be a list")
