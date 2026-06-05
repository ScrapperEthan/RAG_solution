from __future__ import annotations

import re
from typing import Dict, List, Optional

from backend.ports import RawPage
from backend.util import section_id


HEADING_RE = re.compile(r"^(#{2,3})\s+(.+?)\s*$")
TOKEN_RE = re.compile(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]+")
FENCE_RE = re.compile(r"^\s*(```|~~~)")
LIST_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")
TABLE_RE = re.compile(r"^\s*\|.*\|\s*$")


def chunk_page(page: RawPage, config: Optional[Dict] = None) -> List[Dict]:
    """Split a Confluence Markdown page into H2/H3 sections.

    Split at H2/H3 heading boundaries, then optionally merge tiny sections and
    split oversized sections at Markdown block boundaries. Tables, code fences,
    and lists are handled as indivisible blocks during secondary splitting.
    """

    config = config or {}
    min_merge_tokens = int(config.get("min_merge_tokens", 0))
    max_tokens = int(config.get("max_tokens", 1000))
    overlap_tokens = int(config.get("overlap_tokens", 50))

    sections: List[Dict] = []
    current_h2 = ""
    current_h3 = ""
    current_title = ""
    buffer: List[str] = []
    in_code = False

    for line in page["body_md"].splitlines():
        if FENCE_RE.match(line):
            in_code = not in_code
        match = None if in_code else HEADING_RE.match(line)
        if match:
            if current_title or buffer:
                sections.append(build_section(page, current_h2, current_h3, current_title, buffer))
            level, title = match.groups()
            if level == "##":
                current_h2 = title.strip()
                current_h3 = ""
            else:
                current_h3 = title.strip()
            current_title = title.strip()
            buffer = []
        else:
            buffer.append(line)

    if current_title or buffer:
        sections.append(build_section(page, current_h2, current_h3, current_title, buffer))

    if not sections:
        sections.append(build_section(page, page["title"], "", page["title"], [page["body_md"]]))

    sections = [section for section in sections if section["body_md"].strip()]
    sections = merge_small_sections(sections, min_merge_tokens)
    return split_large_sections(sections, max_tokens, overlap_tokens)


def build_section(page: RawPage, h2: str, h3: str, title: str, buffer: List[str]) -> Dict:
    heading_path = [page["title"]]
    if h2:
        heading_path.append(h2)
    if h3 and h3 != h2:
        heading_path.append(h3)
    body = "\n".join(buffer).strip()
    return make_section(page, heading_path, body)


def make_section(page: RawPage, heading_path: List[str], body: str) -> Dict:
    return {
        "ref_id": 0,
        "section_id": section_id(page["page_id"], heading_path),
        "page_id": page["page_id"],
        "space": page["space"],
        "source_url": page["source_url"],
        "title": page["title"],
        "heading_path": heading_path,
        "tree_path": page["tree_path"],
        "owner": page["owner"],
        "labels": page["labels"],
        "content_type": infer_content_type(page["labels"], heading_path[-1], body),
        "component": infer_component(heading_path[-1] + "\n" + body),
        "status": "",
        "has_table": has_markdown_table(body),
        "has_image": "![" in body,
        "body_md": body,
        "confluence_version": page["confluence_version"],
        "update_at": page["update_at"],
        "captured_at": page["captured_at"],
    }


def merge_small_sections(sections: List[Dict], min_merge_tokens: int) -> List[Dict]:
    if min_merge_tokens <= 0 or len(sections) <= 1:
        return sections

    merged: List[Dict] = []
    pending: Optional[Dict] = None
    for section in sections:
        if token_count(section["body_md"]) < min_merge_tokens:
            if pending is None:
                pending = dict(section)
            else:
                pending["body_md"] = join_bodies([pending["body_md"], section["body_md"]])
                pending["has_table"] = pending["has_table"] or section["has_table"]
                pending["has_image"] = pending["has_image"] or section["has_image"]
            continue
        if pending is not None:
            section = merge_into(section, pending)
            pending = None
        merged.append(section)

    if pending is not None:
        if merged:
            merged[-1] = merge_into(merged[-1], pending)
        else:
            merged.append(pending)
    return merged


def merge_into(target: Dict, extra: Dict) -> Dict:
    row = dict(target)
    row["body_md"] = join_bodies([extra["body_md"], target["body_md"]])
    row["has_table"] = target["has_table"] or extra["has_table"]
    row["has_image"] = target["has_image"] or extra["has_image"]
    return row


def split_large_sections(sections: List[Dict], max_tokens: int, overlap_tokens: int) -> List[Dict]:
    if max_tokens <= 0:
        return sections
    result: List[Dict] = []
    for section in sections:
        if token_count(section["body_md"]) <= max_tokens:
            result.append(section)
            continue
        result.extend(split_section(section, max_tokens, overlap_tokens))
    return result


def split_section(section: Dict, max_tokens: int, overlap_tokens: int) -> List[Dict]:
    blocks = markdown_blocks(section["body_md"])
    parts: List[List[str]] = []
    current: List[str] = []
    current_tokens = 0
    for block in blocks:
        block_tokens = token_count(block)
        if current and current_tokens + block_tokens > max_tokens:
            parts.append(current)
            current = overlap_blocks(current, overlap_tokens)
            current_tokens = sum(token_count(item) for item in current)
        current.append(block)
        current_tokens += block_tokens
    if current:
        parts.append(current)

    rows: List[Dict] = []
    for idx, blocks_for_part in enumerate(parts, start=1):
        row = dict(section)
        row["body_md"] = join_bodies(blocks_for_part)
        row["heading_path"] = section["heading_path"][:-1] + [f"{section['heading_path'][-1]} (part {idx})"]
        row["section_id"] = section_id(section["page_id"], row["heading_path"])
        row["has_table"] = has_markdown_table(row["body_md"])
        row["has_image"] = "![" in row["body_md"]
        rows.append(row)
    return rows


def markdown_blocks(text: str) -> List[str]:
    blocks: List[str] = []
    current: List[str] = []
    mode = "paragraph"
    in_code = False

    for line in text.splitlines():
        next_mode = block_mode(line, in_code)
        if FENCE_RE.match(line):
            next_mode = "code"
            in_code = not in_code
        if current and next_mode != mode and line.strip():
            blocks.append("\n".join(current).strip())
            current = []
        if not line.strip() and not in_code:
            if current:
                blocks.append("\n".join(current).strip())
                current = []
            mode = "paragraph"
            continue
        current.append(line)
        mode = next_mode
    if current:
        blocks.append("\n".join(current).strip())
    return [block for block in blocks if block]


def block_mode(line: str, in_code: bool) -> str:
    if in_code:
        return "code"
    if FENCE_RE.match(line):
        return "code"
    if TABLE_RE.match(line):
        return "table"
    if LIST_RE.match(line):
        return "list"
    return "paragraph"


def overlap_blocks(blocks: List[str], overlap_tokens: int) -> List[str]:
    if overlap_tokens <= 0:
        return []
    selected: List[str] = []
    total = 0
    for block in reversed(blocks):
        selected.insert(0, block)
        total += token_count(block)
        if total >= overlap_tokens:
            break
    return selected


def token_count(text: str) -> int:
    return len(TOKEN_RE.findall(text))


def join_bodies(parts: List[str]) -> str:
    return "\n\n".join(part.strip() for part in parts if part.strip())


def has_markdown_table(text: str) -> bool:
    lines = text.splitlines()
    for idx, line in enumerate(lines[:-1]):
        if TABLE_RE.match(line) and re.match(r"^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$", lines[idx + 1]):
            return True
    return False


def infer_content_type(labels: List[str], title: str, body: str) -> str:
    text = " ".join(labels + [title, body]).lower()
    if "troubleshoot" in text or "error" in text or "faq" in text:
        return "troubleshoot"
    if "decision" in text or "rationale" in text:
        return "decision"
    if "config" in text or "param" in text or "default" in text:
        return "config"
    if "how" in title.lower() or "workflow" in text or "way of working" in text:
        return "how-to"
    return "what-is"


def infer_component(text: str) -> str:
    lowered = text.lower()
    if "otp" in lowered:
        return "OTP"
    if "journey" in lowered:
        return "journey"
    if "adaptor" in lowered or "adapter" in lowered:
        return "adaptor"
    if "dm plugin" in lowered or "data management" in lowered or "dmp" in lowered or "batch_size" in lowered:
        return "DM"
    if "sfmc" in lowered:
        return "SFMC"
    return "common"
