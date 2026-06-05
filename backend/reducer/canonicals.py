from __future__ import annotations

from typing import Dict, List


CANONICALS: Dict[str, Dict] = {
    "C-0007": {
        "canonical_id": "C-0007",
        "canonical_name": "DM Plugin",
        "aliases": ["Data Management plugin", "DM plugin", "DMP"],
        "component": "DM",
        "status": "approved",
    },
    "C-0008": {
        "canonical_id": "C-0008",
        "canonical_name": "Journey Plugin",
        "aliases": ["journey plugin"],
        "component": "journey",
        "status": "approved",
    },
    "C-0009": {
        "canonical_id": "C-0009",
        "canonical_name": "Adaptor",
        "aliases": ["adaptor", "adapter"],
        "component": "adaptor",
        "status": "proposed",
    },
    "C-0014": {
        "canonical_id": "C-0014",
        "canonical_name": "MDC OTP Service",
        "aliases": ["OTP service", "MDC OTP"],
        "component": "OTP",
        "status": "proposed",
    },
    "C-0100": {
        "canonical_id": "C-0100",
        "canonical_name": "SFMC Migration",
        "aliases": ["SFMC"],
        "component": "SFMC",
        "status": "proposed",
    },
    "C-0101": {
        "canonical_id": "C-0101",
        "canonical_name": "Message Inventory",
        "aliases": ["Message Inventory"],
        "component": "common",
        "status": "proposed",
    },
    "C-0102": {
        "canonical_id": "C-0102",
        "canonical_name": "Supply and Demand",
        "aliases": ["Supply and Demand"],
        "component": "common",
        "status": "proposed",
    },
}


def canonical_ids_for(section: Dict) -> List[str]:
    text = " ".join(section.get("concepts", []) + section.get("keywords_raw", []) + [section.get("anchor", "")]).lower()
    ids: List[str] = []
    if any(term in text for term in ["dm plugin", "data management", "dmp", "batch_size", "max_retry", "dm-429", "dm-503"]):
        ids.append("C-0007")
    if "journey plugin" in text or "journey" in text:
        ids.append("C-0008")
    if "adaptor" in text or "adapter" in text:
        ids.append("C-0009")
    if "mdc otp" in text or "otp_length" in text or "otp_ttl" in text:
        ids.append("C-0014")
    if "sfmc" in text:
        ids.append("C-0100")
    if "message inventory" in text:
        ids.append("C-0101")
    if "supply and demand" in text:
        ids.append("C-0102")
    return dedupe(ids)


def dedupe(items: List[str]) -> List[str]:
    seen = set()
    result = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


def render_registry_markdown() -> str:
    lines = [
        "# Canonical Keywords Registry (demo output)",
        "",
        "| canonical_id | canonical_name | aliases | component | status |",
        "|---|---|---|---|---|",
    ]
    for item in CANONICALS.values():
        lines.append(
            f"| {item['canonical_id']} | {item['canonical_name']} | {'; '.join(item['aliases'])} | {item['component']} | {item['status']} |"
        )
    return "\n".join(lines) + "\n"

