from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Dict, List, Optional

from backend.ports import Hit
from backend.util import ensure_dir


TOKEN_RE = re.compile(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]+")


class ChromaVectorStore:
    """Local Chroma-backed vector store for quick verification.

    Chroma metadata is scalar-only, so full rows are kept in a JSON sidecar while
    vectors/documents/minimal metadata are stored in persistent Chroma collections.
    """

    def __init__(self, path: Path, dim: int):
        try:
            import chromadb
        except ImportError as exc:
            raise RuntimeError("chromadb is not installed. Run `uv sync --python 3.12`.") from exc

        self.path = path
        self.dim = dim
        ensure_dir(self.path)
        self.sidecar_path = self.path / "rows.json"
        self.client = chromadb.PersistentClient(path=str(self.path))
        self.refs: List[Dict] = []
        self.descriptions: List[Dict] = []
        self.summaries: List[Dict] = []
        self._load_sidecar()

    def init_schema(self) -> None:
        for name in ("refs", "descriptions", "summaries"):
            try:
                self.client.delete_collection(name)
            except Exception:
                pass
            self.client.get_or_create_collection(name=name)
        self.refs = []
        self.descriptions = []
        self.summaries = []
        self._persist_sidecar()

    def upsert_refs(self, rows: List[Dict]) -> None:
        self.refs = rows
        collection = self.client.get_or_create_collection(name="refs")
        if rows:
            collection.upsert(
                ids=[str(row["ref_id"]) for row in rows],
                embeddings=[row["body_embedding"] for row in rows],
                documents=[row["body_md"] for row in rows],
                metadatas=[flat_metadata(row, row["ref_id"]) for row in rows],
            )
        self._persist_sidecar()

    def upsert_descriptions(self, rows: List[Dict]) -> None:
        self.descriptions = rows
        collection = self.client.get_or_create_collection(name="descriptions")
        if rows:
            collection.upsert(
                ids=[str(row["desc_id"]) for row in rows],
                embeddings=[row["embedding"] for row in rows],
                documents=[row["text"] for row in rows],
                metadatas=[flat_metadata(row, row["ref_id"]) for row in rows],
            )
        self._persist_sidecar()

    def upsert_summaries(self, rows: List[Dict]) -> None:
        self.summaries = rows
        collection = self.client.get_or_create_collection(name="summaries")
        if rows:
            collection.upsert(
                ids=[str(row["sum_id"]) for row in rows],
                embeddings=[row["embedding"] for row in rows],
                documents=[row["text"] for row in rows],
                metadatas=[flat_metadata(row, row["ref_id"]) for row in rows],
            )
        self._persist_sidecar()

    def search_vector(self, table: str, query_vec: List[float], k: int, filters: Optional[Dict] = None) -> List[Hit]:
        collection = self.client.get_or_create_collection(name=table)
        query_kwargs = {
            "query_embeddings": [query_vec],
            "n_results": k,
            "include": ["metadatas", "distances"],
        }
        where = chroma_where(filters)
        if where:
            query_kwargs["where"] = where
        result = collection.query(**query_kwargs)
        hits: List[Hit] = []
        ids = result.get("ids", [[]])[0]
        metadatas = result.get("metadatas", [[]])[0]
        distances = result.get("distances", [[]])[0]
        for item_id, metadata, distance in zip(ids, metadatas, distances):
            ref_id = int(metadata.get("ref_id") or item_id)
            hits.append({"ref_id": ref_id, "score": 1.0 / (1.0 + float(distance)), "source": "vector"})
        return hits

    def search_fts(self, table: str, query_text: str, k: int, filters: Optional[Dict] = None) -> List[Hit]:
        rows = self._table_rows(table)
        query_tokens = set(tokens(query_text))
        hits: List[Hit] = []
        for row in rows:
            if not matches(row, filters):
                continue
            text = row.get("body_md") or row.get("text") or ""
            row_tokens = tokens(text)
            overlap = sum(1 for token in row_tokens if token in query_tokens)
            if overlap == 0:
                continue
            score = overlap / math.sqrt(max(1, len(set(row_tokens))))
            hits.append({"ref_id": int(row["ref_id"]), "score": score, "source": "fts"})
        hits.sort(key=lambda item: item["score"], reverse=True)
        return hits[:k]

    def get_refs(self, ref_ids: List[int]) -> List[Dict]:
        by_id = {int(row["ref_id"]): row for row in self.refs}
        return [by_id[ref_id] for ref_id in ref_ids if ref_id in by_id]

    def _table_rows(self, table: str) -> List[Dict]:
        if table == "refs":
            return self.refs
        if table == "descriptions":
            return self.descriptions
        if table == "summaries":
            return self.summaries
        raise ValueError(f"Unknown table: {table}")

    def _load_sidecar(self) -> None:
        if not self.sidecar_path.exists():
            return
        payload = json.loads(self.sidecar_path.read_text(encoding="utf-8"))
        self.refs = payload.get("refs", [])
        self.descriptions = payload.get("descriptions", [])
        self.summaries = payload.get("summaries", [])

    def _persist_sidecar(self) -> None:
        self.sidecar_path.write_text(
            json.dumps(
                {"refs": self.refs, "descriptions": self.descriptions, "summaries": self.summaries},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )


def flat_metadata(row: Dict, ref_id: int) -> Dict:
    metadata: Dict[str, object] = {"ref_id": int(ref_id)}
    for key in ("page_id", "title", "content_type", "component", "section_id", "kind", "lang"):
        if key in row and row[key] is not None:
            metadata[key] = str(row[key])
    return metadata


def chroma_where(filters: Optional[Dict]) -> Optional[Dict]:
    if not filters:
        return None
    return {key: str(value) for key, value in filters.items()}


def matches(row: Dict, filters: Optional[Dict]) -> bool:
    if not filters:
        return True
    return all(str(row.get(key)) == str(value) for key, value in filters.items())


def tokens(text: str) -> List[str]:
    return [token.lower() for token in TOKEN_RE.findall(text)]
