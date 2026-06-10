from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from pathlib import Path
from typing import Dict, Iterable, List


def load_vocabulary(path: Path) -> Dict[str, Dict]:
    """加载同事维护并经 Business 审批的 topic 表。"""

    if not path.exists():
        raise FileNotFoundError(f"Keyword table not found: {path}")
    if path.suffix.lower() in {".jsonl", ".ndjson"}:
        rows = load_jsonl_rows(path)
    elif path.suffix.lower() == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        rows = payload if isinstance(payload, list) else payload.get("rows", [])
    elif path.suffix.lower() in {".md", ".markdown"}:
        rows = load_markdown_rows(path)
    else:
        raise ValueError(f"Unsupported keyword table format: {path.suffix}")

    vocabulary: Dict[str, Dict] = {}
    for raw in rows:
        concept = normalize_concept(raw)
        if concept["status"] != "approved":
            continue
        cid = concept["canonical_id"]
        if cid in vocabulary:
            raise ValueError(f"Duplicate canonical_id in keyword table: {cid}")
        vocabulary[cid] = concept
    if not vocabulary:
        raise ValueError(f"Keyword table contains no approved topics: {path}")
    return vocabulary


def load_jsonl_rows(path: Path) -> List[Dict]:
    rows: List[Dict] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = line.strip()
        if not line or line.startswith("//") or line.startswith("#"):
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSONL at {path}:{line_number}: {exc}") from exc
        if not isinstance(row, dict):
            raise ValueError(f"Keyword table row must be an object: {path}:{line_number}")
        rows.append(row)
    return rows


def load_markdown_rows(path: Path) -> List[Dict]:
    lines = path.read_text(encoding="utf-8").splitlines()
    for idx, line in enumerate(lines):
        if not line.strip().startswith("|"):
            continue
        headers = split_markdown_row(line)
        if not headers or not {"canonical_id", "canonical_name"}.issubset(headers):
            continue
        if idx + 1 >= len(lines) or not is_markdown_separator(lines[idx + 1]):
            continue
        rows = []
        for data_line in lines[idx + 2 :]:
            if not data_line.strip().startswith("|"):
                break
            values = split_markdown_row(data_line)
            rows.append(dict(zip(headers, values)))
        return rows
    raise ValueError(f"No supported keyword table found in Markdown: {path}")


def split_markdown_row(line: str) -> List[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def is_markdown_separator(line: str) -> bool:
    cells = split_markdown_row(line)
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells)


def normalize_concept(raw: Dict) -> Dict:
    canonical_name = str(raw.get("canonical_name") or raw.get("topic") or "").strip()
    if not canonical_name:
        raise ValueError("Keyword table row missing topic/canonical_name")
    canonical_id = str(raw.get("canonical_id") or stable_external_id(canonical_name)).strip()
    return {
        "canonical_id": canonical_id,
        "canonical_name": canonical_name,
        "aliases": list_value(raw.get("aliases")),
        "module": list_value(raw.get("module")),
        "topic_type": str(raw.get("topic_type") or raw.get("type") or "").strip(),
        "confidence": float_value(raw.get("confidence"), 1.0),
        "note_useful": str(raw.get("note_useful") or raw.get("why useful") or "").strip(),
        "boundary": str(raw.get("boundary") or raw.get("topic boundary") or "").strip(),
        "related_pages": list_value(raw.get("related_pages") or raw.get("related page") or raw.get("source_pages")),
        "review_note": str(raw.get("review_note") or raw.get("review note") or raw.get("notes") or "").strip(),
        "status": str(raw.get("status") or "approved").strip().lower(),
    }


def list_value(value) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return dedupe(str(item).strip() for item in value if str(item).strip())
    text = str(value).strip()
    if not text or text in {"—", "-"}:
        return []
    if text.startswith("["):
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                return dedupe(str(item).strip() for item in parsed if str(item).strip())
        except json.JSONDecodeError:
            pass
    reader = csv.reader(io.StringIO(text), delimiter=";")
    return dedupe(item.strip() for item in next(reader) if item.strip())


def float_value(value, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def stable_external_id(name: str) -> str:
    digest = hashlib.sha1(normalize_term(name).encode("utf-8")).hexdigest()[:8].upper()
    return f"C-EXT-{digest}"


def canonical_ids_for(section: Dict, canonicals: Dict[str, Dict]) -> List[str]:
    """按段落主旨匹配 topic，交叉引用不产生归属。"""
    heading_path = [str(item) for item in section.get("heading_path", [])]
    page_title = str(section.get("title") or (heading_path[0] if heading_path else ""))
    leaf_heading = str(heading_path[-1] if heading_path else "")
    heading_ids = dedupe(cid for text in heading_path for cid in canonical_ids_in_text(text, canonicals))
    page_ids = canonical_ids_in_text(page_title, canonicals)
    leaf_ids = canonical_ids_in_text(leaf_heading, canonicals)

    if heading_ids and not is_cross_reference_heading(leaf_heading):
        return heading_ids
    if leaf_ids and not is_cross_reference_heading(leaf_heading):
        return leaf_ids
    if page_ids:
        return page_ids
    if heading_ids:
        return heading_ids
    if leaf_ids:
        return leaf_ids

    concepts = [str(item) for item in section.get("concepts", [])]
    if len(concepts) == 1:
        concept_ids = canonical_ids_in_text(concepts[0], canonicals)
        if concept_ids:
            return concept_ids
    elif len(concepts) > 1:
        return []
    primary_keywords = [str(item) for item in section.get("keywords_raw", [])[:2]]
    return dedupe(cid for text in primary_keywords for cid in canonical_ids_in_text(text, canonicals))


def canonical_ids_in_text(text: str, canonicals: Dict[str, Dict]) -> List[str]:
    return [
        cid
        for cid, canonical in canonicals.items()
        if any(term_in_text(term, text) for term in canonical_terms(canonical))
    ]


def is_cross_reference_heading(text: str) -> bool:
    lowered = normalize_term(text)
    markers = ("connects to", "receiving from", "see ", "refer to", "related to")
    return any(marker in lowered for marker in markers)


def canonical_id_in_text(text: str, canonicals: Dict[str, Dict]) -> str | None:
    for cid, canonical in canonicals.items():
        if any(term_in_text(term, text) for term in canonical_terms(canonical)):
            return cid
    return None


def canonical_terms(canonical: Dict) -> List[str]:
    return dedupe(
        normalize_term(term)
        for term in [canonical["canonical_name"], *canonical.get("aliases", [])]
        if len(normalize_term(term)) >= 2
    )


def term_in_text(term: str, text: str) -> bool:
    normalized_term = normalize_term(term)
    normalized_text = f" {normalize_term(text)} "
    return bool(normalized_term) and f" {normalized_term} " in normalized_text


def normalize_term(term: str) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", " ", str(term).lower()).strip()


def dedupe(items: Iterable[str]) -> List[str]:
    seen = set()
    result = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


def render_registry_markdown(canonicals: Dict[str, Dict]) -> str:
    lines = [
        "# Approved Keyword Table Snapshot",
        "",
        "| canonical_id | canonical_name | aliases | module | topic_type | confidence | boundary | related_pages | status |",
        "|---|---|---|---|---|---:|---|---|---|",
    ]
    for item in canonicals.values():
        lines.append(
            "| {canonical_id} | {canonical_name} | {aliases} | {module} | {topic_type} | {confidence:.2f} | {boundary} | {related_pages} | {status} |".format(
                canonical_id=item["canonical_id"],
                canonical_name=item["canonical_name"],
                aliases="; ".join(item["aliases"]),
                module="; ".join(item["module"]),
                topic_type=item["topic_type"],
                confidence=item["confidence"],
                boundary=item["boundary"],
                related_pages="; ".join(item["related_pages"]),
                status=item["status"],
            )
        )
    return "\n".join(lines) + "\n"
