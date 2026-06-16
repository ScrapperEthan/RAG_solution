from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

from backend.ports import RawPage
from backend.util import section_id


HEADING_RE = re.compile(r"^(#{1,3})\s+(.+?)\s*$")
TOKEN_RE = re.compile(r"[A-Za-z0-9_]+|[一-鿿]+")
FENCE_RE = re.compile(r"^\s*(```|~~~)")
LIST_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")
# Real Confluence -> Markdown rows are often NOT wrapped in leading/trailing
# pipes (e.g. "a | b | c"), so accept an optional outer pipe with >=1 inner pipe.
# (folds handoff/17 §1; the strict "^\\|.*\\|$" dropped every unwrapped data row.)
TABLE_RE = re.compile(r"^\s*\|?.+\|.+\|?.*$")
SEPARATOR_RE = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)+\|?\s*$")
NUM_RE = re.compile(r"^\s*(\d+)[.)]\s+(.*\S)\s*$")
SUB_RE = re.compile(r"^\s*([A-Za-z])[.)]\s+(.*\S)\s*$")
QA_RE = re.compile(r"^\s*Q\s*[:：]\s*(.+?)\s*$", re.IGNORECASE)
URL_RE = re.compile(r"https?://\S+")


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def chunk_page(page: RawPage, config: Optional[Dict] = None) -> List[Dict]:
    """Split a Confluence Markdown page into structure-aware sections.

    Detection is driven by STRUCTURE, not by page-specific names:
      * a wide table whose first column is a key  -> one section per cell (matrix)
      * a 2-column table containing a URL          -> one section per column (record)
      * any other table                            -> one section per row (record)
      * a "Q:" line                                -> a Q&A block (+ its inner tables)
      * a numbered list                            -> a process (one section per top-level step)
      * everything else                            -> plain H1/H2/H3 prose sections

    Structured sections carry routing ``metadata`` (table/table_kind/entity_key/
    row_key/attribute/channel/question/block/step) consumed by map and reduce.
    """

    config = config or {}
    min_merge_tokens = int(config.get("min_merge_tokens", 0))
    max_tokens = int(config.get("max_tokens", 1000))
    overlap_tokens = int(config.get("overlap_tokens", 50))
    structured = bool(config.get("structured", True))

    sections = parse_page(page, page["body_md"], structured)
    if not sections:
        sections.append(make_section(page, [page["title"]], page["body_md"]))

    sections = [section for section in sections if section["body_md"].strip()]
    sections = merge_small_sections(sections, min_merge_tokens)
    return split_large_sections(sections, max_tokens, overlap_tokens)


# ---------------------------------------------------------------------------
# Single pass over the whole page (not just the pre-heading prefix)
# ---------------------------------------------------------------------------

def parse_page(page: RawPage, body_md: str, structured: bool) -> List[Dict]:
    lines = body_md.splitlines()
    sections: List[Dict] = []
    h2 = ""
    h3 = ""
    prose: List[str] = []
    in_code = False
    i = 0

    def heading_path() -> List[str]:
        path = [page["title"]]
        if h2:
            path.append(h2)
        if h3 and h3 != h2:
            path.append(h3)
        return path

    def flush_prose() -> Optional[str]:
        """Emit buffered prose as a section; return its trailing caption (a short
        label line a following table/process can use as its name)."""
        nonlocal prose
        caption = _caption(prose)
        body = "\n".join(prose).strip()
        if body:
            sections.append(make_section(page, heading_path(), body))
        prose = []
        return caption

    while i < len(lines):
        line = lines[i]
        if FENCE_RE.match(line):
            in_code = not in_code
        if in_code:
            prose.append(line)
            i += 1
            continue

        heading = HEADING_RE.match(line)
        if heading and "|" not in heading.group(2):
            flush_prose()
            level, title = heading.groups()
            if level == "#" or level == "##":
                h2 = title.strip()
                h3 = ""
            else:
                h3 = title.strip()
            i += 1
            continue
        if heading:
            # A "heading" whose text is a pipe row is a mis-converted table header
            # (Confluence -> Markdown sometimes promotes a bold header row). Drop the
            # marker and let the table/prose machinery handle the row, so it does not
            # pollute heading_path / anchors / section_id for everything beneath it.
            line = heading.group(2)
            lines[i] = line

        if structured and is_table_start(lines, i):
            caption = flush_prose()
            headers, rows, next_i = collect_table(lines, i)
            sections.extend(parse_table(page, heading_path(), caption or _last_heading(heading_path()), headers, rows, None))
            i = next_i
            continue

        if structured and QA_RE.match(line):
            flush_prose()
            new_sections, next_i = parse_qa(page, heading_path(), lines, i)
            sections.extend(new_sections)
            i = next_i
            continue

        if structured and is_process_start(lines, i):
            caption = flush_prose()
            new_sections, next_i = parse_process(page, heading_path(), caption or _last_heading(heading_path()), lines, i)
            sections.extend(new_sections)
            i = next_i
            continue

        prose.append(line)
        i += 1

    flush_prose()
    return sections


def _caption(prose: List[str]) -> str:
    for line in reversed(prose):
        stripped = line.strip()
        if not stripped:
            continue
        # a caption is a short label/title line — not a list item, table, or a
        # full sentence (sentences end with punctuation).
        if LIST_RE.match(line) or "|" in line or len(stripped.split()) > 12:
            return ""
        if stripped[-1] in ".。!?！？:：":
            return ""
        return stripped
    return ""


def _last_heading(path: List[str]) -> str:
    return path[-1] if path else ""


# ---------------------------------------------------------------------------
# Tables: generic matrix / transposed / row records
# ---------------------------------------------------------------------------

def is_table_start(lines: List[str], i: int) -> bool:
    return (
        i + 1 < len(lines)
        and "|" in lines[i]
        and bool(SEPARATOR_RE.match(lines[i + 1]))
    )


def collect_table(lines: List[str], start: int) -> Tuple[List[str], List[List[str]], int]:
    headers = split_row(lines[start])
    rows: List[List[str]] = []
    i = start + 2  # skip header + separator
    while i < len(lines) and TABLE_RE.match(lines[i]):
        rows.append(split_row(lines[i]))
        i += 1
    return headers, rows, i


def parse_table(
    page: RawPage,
    base_path: List[str],
    title: str,
    headers: List[str],
    rows: List[List[str]],
    question: Optional[str],
) -> List[Dict]:
    headers = [h.strip() for h in headers]
    rows = [[c.strip() for c in row] for row in rows if any(c.strip() for c in row)]
    if not headers or not rows:
        return []
    label = title or "Table"
    table_name = slugify(question or title) or "table"

    if is_transposed_table(headers, rows):
        return emit_transposed(page, base_path, label, table_name, headers, rows, question)
    if is_matrix(headers, rows):
        return emit_matrix(page, base_path, label, table_name, headers, rows)
    return emit_row_records(page, base_path, label, table_name, headers, rows, question)


def is_matrix(headers: List[str], rows: List[List[str]]) -> bool:
    if len(headers) < 3 or len(rows) < 2:
        return False
    keys = [row[0] for row in rows if row and row[0]]
    if len(keys) < 2:
        return False
    short = all(len(key.split()) <= 6 for key in keys)
    distinct = len({key.lower() for key in keys}) >= max(2, int(0.6 * len(keys)))
    return short and distinct


def is_transposed_table(headers: List[str], rows: List[List[str]]) -> bool:
    # A 2-column comparison table whose cells carry URLs (endpoint / access tables):
    # the COLUMNS are the entities, the ROWS are attributes -> transpose.
    return len(headers) == 2 and len(rows) >= 1 and any(URL_RE.search(cell) for row in rows for cell in row)


def emit_matrix(page, base_path, label, table_name, headers, rows) -> List[Dict]:
    sections: List[Dict] = []
    entity_key = headers[0] or "row_key"
    for row in rows:
        row_key = row[0] if row else ""
        if not row_key:
            continue
        for col_idx, attribute in enumerate(headers[1:], start=1):
            value = row[col_idx].strip() if col_idx < len(row) else ""
            if not value:
                continue
            metadata = {
                "table": table_name,
                "table_kind": "matrix",
                "entity_key": entity_key,
                "row_key": row_key,
                # `channel` = the row routing key (name kept for downstream routing
                # compatibility; works for any entity, not only channels).
                "channel": row_key,
                "attribute": attribute,
            }
            heading_path = base_path + [label, row_key, attribute]
            sections.append(structured_section(page, heading_path, preserve_cell(value), metadata))
    return sections


def emit_transposed(page, base_path, label, table_name, headers, rows, question) -> List[Dict]:
    sections: List[Dict] = []
    for col_idx, header in enumerate(headers):
        values = [row[col_idx].strip() for row in rows if col_idx < len(row) and row[col_idx].strip()]
        if not values:
            continue
        row_key = values[0]
        facts = [f"{header}: {value}" for value in values[1:]] or [header]
        metadata = {
            "table": table_name,
            "table_kind": "record",
            "row_key": row_key,
            "environment": header,
        }
        if question:
            metadata["question"] = question
        heading_path = base_path + [label, row_key]
        sections.append(structured_section(page, heading_path, "\n".join(facts), metadata))
    return sections


def emit_row_records(page, base_path, label, table_name, headers, rows, question) -> List[Dict]:
    sections: List[Dict] = []
    key_index = 1 if headers and headers[0] in ("#", "No", "No.", "Index") and len(headers) > 1 else 0
    entity_key = headers[key_index] if key_index < len(headers) else "row_key"
    for row in rows:
        row_key = row[key_index].strip() if key_index < len(row) else ""
        if not row_key:
            continue
        parts = [f"{headers[idx]}: {row[idx].strip()}" for idx in range(len(headers)) if idx < len(row) and row[idx].strip()]
        metadata = {
            "table": table_name,
            "table_kind": "record",
            "row_key": row_key,
            "entity_key": entity_key,
        }
        if question:
            metadata["question"] = question
        heading_path = base_path + [label, row_key]
        sections.append(structured_section(page, heading_path, "\n".join(parts), metadata))
    return sections


# ---------------------------------------------------------------------------
# Q&A blocks (a "Q:" line, optionally followed by tables)
# ---------------------------------------------------------------------------

def parse_qa(page: RawPage, base_path: List[str], lines: List[str], start: int) -> Tuple[List[Dict], int]:
    question = QA_RE.match(lines[start]).group(1).strip()
    body_lines: List[str] = []
    i = start + 1
    while i < len(lines):
        if HEADING_RE.match(lines[i]) or QA_RE.match(lines[i]) or is_process_start(lines, i):
            break
        body_lines.append(lines[i])
        i += 1

    sections: List[Dict] = []
    plain, tables = split_prose_and_tables(body_lines)
    narrative = "\n".join([f"Q: {question}"] + plain).strip()
    if narrative and (plain or not tables):
        sections.append(
            structured_section(
                page,
                base_path + ["Q&A", question],
                narrative,
                {"block": "qa", "question": question},
            )
        )
    for headers, rows in tables:
        sections.extend(parse_table(page, base_path + ["Q&A", question], question, headers, rows, question))
    return sections, i


def split_prose_and_tables(lines: List[str]) -> Tuple[List[str], List[Tuple[List[str], List[List[str]]]]]:
    plain: List[str] = []
    tables: List[Tuple[List[str], List[List[str]]]] = []
    i = 0
    while i < len(lines):
        if is_table_start(lines, i):
            headers, rows, next_i = collect_table(lines, i)
            tables.append((headers, rows))
            i = next_i
            continue
        plain.append(lines[i])
        i += 1
    return plain, tables


# ---------------------------------------------------------------------------
# Process / numbered lists (hierarchical: top-level steps keep their sub-items)
# ---------------------------------------------------------------------------

def is_process_start(lines: List[str], i: int) -> bool:
    line = lines[i]
    match = NUM_RE.match(line)
    if match:
        if match.group(1) == "1":
            return True
        # mid-list (after a blank) still counts if the previous non-blank line was a list item
        for prev in range(i - 1, -1, -1):
            if not lines[prev].strip():
                continue
            return bool(NUM_RE.match(lines[prev]) or SUB_RE.match(lines[prev]))
        return False
    # a short caption/title line directly preceding a numbered list (e.g. a process heading)
    text = line.strip()
    if not text or LIST_RE.match(line) or "|" in line or len(text.split()) > 12 or HEADING_RE.match(line) or QA_RE.match(line):
        return False
    for j in range(i + 1, len(lines)):
        if not lines[j].strip():
            continue
        nxt = NUM_RE.match(lines[j])
        return bool(nxt and nxt.group(1) == "1")
    return False


def parse_process(page: RawPage, base_path: List[str], default_title: str, lines: List[str], start: int) -> Tuple[List[Dict], int]:
    title = default_title or "Process"
    i = start
    nonblank = start
    while nonblank < len(lines) and not lines[nonblank].strip():
        nonblank += 1
    if nonblank < len(lines) and not NUM_RE.match(lines[nonblank]):
        title = lines[nonblank].strip()   # consume the process heading line
        i = nonblank + 1

    steps: List[Dict] = []
    current: Optional[Dict] = None
    while i < len(lines):
        line = lines[i]
        if HEADING_RE.match(line) or QA_RE.match(line):
            break
        if is_table_start(lines, i):
            break
        text = line.strip()
        if not text:
            i += 1
            continue
        num = NUM_RE.match(line)
        if num:
            current = {"num": num.group(1), "text": num.group(2).strip(), "subs": []}
            steps.append(current)
            i += 1
            continue
        sub = SUB_RE.match(line)
        if sub and current is not None:
            current["subs"].append(f"{sub.group(1)}. {sub.group(2).strip()}")
            i += 1
            continue
        if current is not None:
            # a detail line (a link, a note) under the current step -> attach, NOT a new step
            current["subs"].append(text)
            i += 1
            continue
        break  # prose before any numbered item -> not part of the list

    sections: List[Dict] = []
    title = title or "Process"
    for step in steps:
        body = "\n".join([f"{step['num']}. {step['text']}"] + [f"   - {sub}" for sub in step["subs"]])
        metadata = {"block": "process", "step": step["num"], "step_text": step["text"]}
        heading_path = base_path + [title, f"Step {step['num']}: {step['text']}"[:80]]
        sections.append(structured_section(page, heading_path, body, metadata))
    return sections, i


# ---------------------------------------------------------------------------
# Section construction
# ---------------------------------------------------------------------------

def structured_section(page: RawPage, heading_path: List[str], body: str, metadata: Dict[str, str]) -> Dict:
    row = make_section(page, dedupe_path(heading_path), body)
    row["metadata"] = metadata
    return row


def dedupe_path(path: List[str]) -> List[str]:
    out: List[str] = []
    for part in path:
        part = str(part).strip()
        if not part:
            continue
        if out and out[-1].lower() == part.lower():
            continue
        out.append(part)
    return out


def make_section(page: RawPage, heading_path: List[str], body: str) -> Dict:
    body = body.strip()
    leaf = heading_path[-1] if heading_path else page["title"]
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
        "content_type": infer_content_type(page["labels"], leaf, body),
        "component": "",
        "domains": list(page.get("domains", [])),
        "card_worthy": bool(page.get("card_worthy", True)),
        "status": "",
        "metadata": {},
        "has_table": has_markdown_table(body),
        "has_image": "![" in body,
        "body_md": body,
        "confluence_version": page["confluence_version"],
        "update_at": page["update_at"],
        "captured_at": page["captured_at"],
    }


def split_row(line: str) -> List[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def preserve_cell(text: str) -> str:
    return re.sub(r"[ \t]{2,}", " ", str(text).strip())


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(text or "").lower()).strip("_")


# ---------------------------------------------------------------------------
# Small-section merge / large-section split (unchanged behaviour)
# ---------------------------------------------------------------------------

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
    if in_code or FENCE_RE.match(line):
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
        if TABLE_RE.match(line) and SEPARATOR_RE.match(lines[idx + 1]):
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
