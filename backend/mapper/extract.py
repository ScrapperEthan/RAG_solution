from __future__ import annotations

import re
from typing import Dict, List, Optional


def extract_section_record(section: Dict) -> Dict:
    text = section["body_md"]
    heading_path = section["heading_path"]
    heading = heading_path[-1]
    concepts = infer_concepts(heading, text)
    keywords = extract_keywords(heading, text)
    info_type = infer_info_type(heading, text, section.get("content_type", "what-is"))
    tier, fact_value, pointer_to = infer_tier_and_value(section, info_type)
    summary_en, summary_zh = summarize(heading, concepts, info_type, tier, fact_value)
    questions_en, questions_zh = questions(heading, concepts, keywords, info_type, tier)
    return {
        "anchor": " > ".join(heading_path),
        "heading_path": heading_path,
        "concepts": concepts,
        "keywords_raw": keywords,
        "info_type": info_type,
        "tier": tier,
        "fact_value": fact_value,
        "pointer_to": pointer_to,
        "has_table": section["has_table"],
        "has_image": section["has_image"],
        "summary_en": summary_en,
        "summary_zh": summary_zh,
        "questions_en": questions_en,
        "questions_zh": questions_zh,
        "confidence": confidence_for(tier, keywords, text),
    }


def infer_concepts(heading: str, text: str) -> List[str]:
    lowered = f"{heading}\n{text}".lower()
    concepts: List[str] = []
    if any(term in lowered for term in ["dm plugin", "data management plugin", "dmp", "batch_size", "max_retry", "dm-429", "dm-503"]):
        concepts.append("DM Plugin")
    if "journey plugin" in lowered or "journey" in heading.lower() or "max_concurrent_journeys" in lowered:
        concepts.append("Journey Plugin")
    if "adaptor" in lowered or "adapter" in lowered or "payload mapping" in lowered:
        concepts.append("Adaptor")
    if "mdc otp" in lowered or "otp_length" in lowered or "otp_ttl" in lowered:
        concepts.append("MDC OTP Service")
    elif re.search(r"\botp\b", lowered):
        concepts.append("OTP")
    if "sfmc" in lowered:
        concepts.append("SFMC Migration")
    if "message inventory" in lowered:
        concepts.append("Message Inventory")
    if "supply" in lowered and "demand" in lowered:
        concepts.append("Supply and Demand")
    if not concepts:
        concepts.append(heading)
    return dedupe(concepts)


def extract_keywords(heading: str, text: str) -> List[str]:
    raw = f"{heading}\n{text}"
    candidates = [
        "Data Management plugin",
        "DM plugin",
        "DMP",
        "Journey plugin",
        "adaptor",
        "adapter",
        "MDC OTP Service",
        "OTP",
        "SFMC",
        "Message Inventory",
        "batch_size",
        "max_retry",
        "max_concurrent_journeys",
        "otp_length",
        "otp_ttl",
        "adaptor_mode",
        "campaign_id",
        "user_id",
        "DM-429",
        "DM-503",
    ]
    found: List[str] = []
    for candidate in candidates:
        if re.search(re.escape(candidate), raw, flags=re.IGNORECASE):
            found.append(candidate)
    for code in re.findall(r"`([^`]+)`", raw):
        if code not in found and re.match(r"[A-Za-z0-9_:-]+$", code):
            found.append(code)
    return dedupe(found or [heading])


def infer_info_type(heading: str, text: str, default: str) -> str:
    lowered = f"{heading}\n{text}".lower()
    if "error" in lowered or "troubleshoot" in lowered or "faq" in lowered:
        return "troubleshoot"
    if "rationale" in lowered or "decision" in lowered:
        return "decision"
    if "config" in lowered or "param" in lowered or "default" in lowered:
        return "config"
    if "how" in heading.lower() or "receiving" in lowered or "payload" in lowered:
        return "how-to"
    if default in {"what-is", "how-to", "config", "troubleshoot", "reference", "decision", "meeting-notes"}:
        return default
    return "what-is"


def infer_tier_and_value(section: Dict, info_type: str) -> tuple[str, Optional[str], Optional[str]]:
    text = section["body_md"]
    lowered = text.lower()
    if "supports retry configuration" in lowered and "does not state the default" in lowered:
        return "pointer-only", None, "DM Plugin Overview > Configuration"

    values = extract_fact_values(text)
    if values and info_type in {"config", "troubleshoot", "reference"}:
        return "inline-value", "; ".join(values), None
    if "see the" in lowered or "refer to" in lowered:
        return "pointer-only", None, pointer_from_text(text)
    return "narrative", None, None


def extract_fact_values(text: str) -> List[str]:
    values: List[str] = []
    table_values = {
        "batch_size": r"`batch_size`\s*\|\s*([0-9]+)",
        "max_retry": r"`max_retry`\s*\|\s*([0-9]+)",
        "max_concurrent_journeys": r"`max_concurrent_journeys`\s*\|\s*([0-9]+)",
        "otp_length": r"`otp_length`\s*\|\s*([0-9]+)",
        "otp_ttl": r"`otp_ttl`\s*\|\s*([0-9]+)",
        "adaptor_mode": r"`adaptor_mode`\s*\|\s*([A-Za-z0-9_-]+)",
    }
    for name, pattern in table_values.items():
        match = re.search(pattern, text)
        if match:
            values.append(f"{name}: {match.group(1)}")

    inline_patterns = [
        (r"`batch_size`\s+is increased to\s+\*\*?([0-9]+)\*\*?", "batch_size"),
        (r"`batch_size`\s+is increased to\s+([0-9]+)", "batch_size"),
        (r"\*\*(DM-[0-9]+)\*\*:\s*([^.\n]+)", "error"),
        (r"\*\*(DM-[0-9]+)\*\*:\s*([^.\n]+)", "error"),
    ]
    for pattern, name in inline_patterns:
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            if name == "error":
                values.append(f"{match.group(1)}: {match.group(2).strip()}")
            else:
                values.append(f"{name}: {match.group(1)}")
    return dedupe(values)


def pointer_from_text(text: str) -> str:
    if "Journey Plugin" in text:
        return "Journey Plugin page > Integration"
    if "DM Plugin Overview" in text:
        return "DM Plugin Overview > Configuration"
    return "source page referenced by this section"


def summarize(heading: str, concepts: List[str], info_type: str, tier: str, fact_value: Optional[str]) -> tuple[str, str]:
    concept = ", ".join(concepts)
    if fact_value:
        return (
            f"{heading} provides exact {info_type} values for {concept}: {fact_value}.",
            f"{heading} 提供 {concept} 的精确 {info_type} 信息:{fact_value}。",
        )
    return (
        f"{heading} covers {info_type} information for {concept} ({tier}).",
        f"{heading} 说明 {concept} 的 {info_type} 信息({tier})。",
    )


def questions(heading: str, concepts: List[str], keywords: List[str], info_type: str, tier: str) -> tuple[List[str], List[str]]:
    concept = concepts[0]
    keyword = keywords[0]
    en = [
        f"What is {concept}?",
        f"{keyword} {info_type}",
        f"Where is {concept} documented?",
    ]
    zh = [
        f"{concept} 是什么?",
        f"{keyword} {info_type}",
        f"{concept} 在哪里说明?",
    ]
    if tier == "inline-value":
        en.insert(0, f"What exact values are configured for {concept}?")
        zh.insert(0, f"{concept} 的精确配置值是什么?")
    if tier == "pointer-only":
        en.insert(0, f"Where should I look up the exact value for {concept}?")
        zh.insert(0, f"{concept} 的精确值应该去哪里查?")
    return dedupe(en)[:7], dedupe(zh)[:7]


def confidence_for(tier: str, keywords: List[str], text: str) -> float:
    if tier == "inline-value":
        return 0.95
    if tier == "pointer-only":
        return 0.65
    if keywords:
        return 0.86
    return 0.55


def dedupe(items: List[str]) -> List[str]:
    seen = set()
    result = []
    for item in items:
        norm = item.lower()
        if norm not in seen:
            seen.add(norm)
            result.append(item)
    return result

