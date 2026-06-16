from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Dict, List, Optional

from backend.domains import domain_matches
from backend.ports import Hit


TOKEN_RE = re.compile(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]+")


class JsonVectorStore:
    """Small local vector/FTS store for fixture demos."""

    def __init__(self, path: Path, dim: int):
        self.path = path
        self.dim = dim
        self.refs: List[Dict] = []
        self.descriptions: List[Dict] = []
        self.summaries: List[Dict] = []
        self._load_if_exists()

    def init_schema(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.refs = []
        self.descriptions = []
        self.summaries = []
        self._persist()

    def upsert_refs(self, rows: List[Dict]) -> None:
        self.refs = rows
        self._persist()

    def upsert_descriptions(self, rows: List[Dict]) -> None:
        self.descriptions = rows
        self._persist()

    def upsert_summaries(self, rows: List[Dict]) -> None:
        self.summaries = rows
        self._persist()

    def search_vector(self, table: str, query_vec: List[float], k: int, filters: Optional[Dict] = None) -> List[Hit]:
        rows = self._table_rows(table)
        hits: List[Hit] = []
        for row in rows:
            if not self._matches(row, filters):
                continue
            score = cosine(query_vec, row.get("embedding") or row.get("body_embedding") or [])
            hits.append(hit_for_row(table, row, score, "vector"))
        hits.sort(key=lambda item: item["score"], reverse=True)
        return hits[:k]

    def search_fts(self, table: str, query_text: str, k: int, filters: Optional[Dict] = None) -> List[Hit]:
        rows = self._table_rows(table)
        query_tokens = set(tokens(query_text))
        hits: List[Hit] = []
        for row in rows:
            if not self._matches(row, filters):
                continue
            text = row.get("body_md") or row.get("text") or ""
            row_tokens = tokens(text)
            overlap = sum(1 for token in row_tokens if token in query_tokens)
            if overlap == 0:
                continue
            score = overlap / max(1, len(set(row_tokens)))
            hits.append(hit_for_row(table, row, score, "fts"))
        hits.sort(key=lambda item: item["score"], reverse=True)
        return hits[:k]

    def get_refs(self, ref_ids: List[int]) -> List[Dict]:
        wanted = set(ref_ids)
        by_id = {int(row["ref_id"]): row for row in self.refs}
        return [by_id[ref_id] for ref_id in ref_ids if ref_id in wanted and ref_id in by_id]

    def _table_rows(self, table: str) -> List[Dict]:
        if table == "refs":
            return self.refs
        if table == "descriptions":
            return self.descriptions
        if table == "summaries":
            return self.summaries
        raise ValueError(f"Unknown table: {table}")

    def _matches(self, row: Dict, filters: Optional[Dict]) -> bool:
        if not filters:
            return True
        for key, value in filters.items():
            row_value = row.get(key)
            if key == "domains" and isinstance(row_value, list):
                if not any(domain_matches(value, entry) for entry in row_value):
                    return False
            elif isinstance(row_value, list):
                if value not in row_value:
                    return False
            elif row_value != value:
                return False
        return True

    def _persist(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(
                {
                    "dim": self.dim,
                    "refs": self.refs,
                    "descriptions": self.descriptions,
                    "summaries": self.summaries,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    def _load_if_exists(self) -> None:
        if not self.path.exists():
            return
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        self.refs = payload.get("refs", [])
        self.descriptions = payload.get("descriptions", [])
        self.summaries = payload.get("summaries", [])


def tokens(text: str) -> List[str]:
    return [token.lower() for token in TOKEN_RE.findall(text)]


def cosine(a: List[float], b: List[float]) -> float:
    if not a or not b:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)


def hit_for_row(table: str, row: Dict, score: float, source: str) -> Hit:
    if table == "refs":
        return {
            "table": table,
            "hit_id": str(row["ref_id"]),
            "ref_id": int(row["ref_id"]),
            "score": score,
            "source": source,
        }
    if table == "descriptions":
        return {
            "table": table,
            "hit_id": str(row["desc_id"]),
            "ref_id": int(row["ref_id"]),
            "score": score,
            "source": source,
        }
    if table == "summaries":
        return {
            "table": table,
            "hit_id": str(row["sum_id"]),
            "ref_ids": [int(ref_id) for ref_id in row.get("ref_ids", [])],
            "page_id": str(row.get("page_id", "")),
            "score": score,
            "source": source,
        }
    raise ValueError(f"Unknown table: {table}")
