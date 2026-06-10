from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Tuple

from backend.ports import LLM
from backend.util import write_jsonl


EXPAND_BOUNDARY_SYSTEM = """task: card_expand_boundary
You write a concise scope boundary for ONE approved knowledge topic. The boundary
is used downstream to decide whether a passage belongs to this topic, so it must
reflect the topic's CURRENT full scope, which may have grown after merges.

Return STRICT JSON: {"boundary": string}.

Rules:
- Cover the full scope implied by canonical_name + every alias + every subsection.
- One or two sentences: say what the topic covers; optionally note what it excludes.
- Keep exact product/component names. Do not invent scope absent from the inputs.
- Use the same language as current_boundary when it is non-empty, otherwise Chinese."""

EXPAND_BOUNDARY_SCHEMA = {"type": "object", "required": ["boundary"]}


def expand_boundary(canonical: Dict, llm: LLM) -> str:
    """Ask the LLM to (re)write a topic boundary covering its current full scope.

    Used after a merge widens a topic: the absorbed aliases/subsections are already
    on the row, so the LLM regenerates a boundary that covers the union.
    """

    payload = {
        "canonical_name": canonical.get("canonical_name") or canonical.get("topic") or "",
        "aliases": list(canonical.get("aliases") or []),
        "subsections": list(canonical.get("subsections") or []),
        "current_boundary": str(canonical.get("boundary") or ""),
    }
    response = llm.complete_json(
        EXPAND_BOUNDARY_SYSTEM,
        json.dumps(payload, ensure_ascii=False),
        schema=EXPAND_BOUNDARY_SCHEMA,
    )
    boundary = str(response.get("boundary") or "").strip()
    return boundary or payload["current_boundary"]


def needs_refine(row: Dict) -> bool:
    """A topic needs a fresh boundary if it absorbed a merge (boundary_stale) or
    has no boundary yet. Only approved rows are touched."""

    if str(row.get("status", "approved")).strip().lower() != "approved":
        return False
    return bool(row.get("boundary_stale")) or not str(row.get("boundary") or "").strip()


def refine_boundaries(table_path: Path, llm: LLM) -> Dict[str, int]:
    """Regenerate boundaries (via the LLM port) for topics flagged boundary_stale
    or missing a boundary, then write the keyword table back in place.

    Idempotent: refined rows drop the boundary_stale flag and gain a non-empty
    boundary, so a second run refines nothing.
    """

    rows, fmt = _read_rows(table_path)
    refined = 0
    for row in rows:
        if not needs_refine(row):
            continue
        row["boundary"] = expand_boundary(row, llm)
        row.pop("boundary_stale", None)
        refined += 1
    _write_rows(table_path, rows, fmt)
    return {"topics": len(rows), "boundaries_refined": refined}


def _read_rows(path: Path) -> Tuple[List[Dict], str]:
    if not path.exists():
        raise FileNotFoundError(f"Keyword table not found: {path}")
    suffix = path.suffix.lower()
    if suffix in {".jsonl", ".ndjson"}:
        rows: List[Dict] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("//") or line.startswith("#"):
                continue
            rows.append(json.loads(line))
        return rows, "jsonl"
    if suffix == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        rows = payload if isinstance(payload, list) else payload.get("rows", [])
        return list(rows), "json"
    raise ValueError(f"refine_boundaries supports .jsonl/.json keyword tables, got {suffix}")


def _write_rows(path: Path, rows: List[Dict], fmt: str) -> None:
    if fmt == "jsonl":
        write_jsonl(path, rows)
    else:
        path.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
