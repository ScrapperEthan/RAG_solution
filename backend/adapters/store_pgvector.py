from __future__ import annotations

from typing import Dict, List, Optional

from backend.ports import Hit


class PgVectorStore:
    """pgvector adapter skeleton.

    This file keeps the production boundary in place. The offline demo uses
    JsonVectorStore so it can run without Docker. opencode can either fill this
    with psycopg SQL calls or point the config at an existing implementation.
    """

    def __init__(self, dsn: str, dim: int):
        self.dsn = dsn
        self.dim = dim

    def init_schema(self) -> None:
        raise NotImplementedError("TODO: create refs/descriptions/summaries in pgvector")

    def upsert_refs(self, rows: List[Dict]) -> None:
        raise NotImplementedError("TODO: upsert refs")

    def upsert_descriptions(self, rows: List[Dict]) -> None:
        raise NotImplementedError("TODO: upsert descriptions")

    def upsert_summaries(self, rows: List[Dict]) -> None:
        raise NotImplementedError("TODO: upsert summaries")

    def search_vector(self, table: str, query_vec: List[float], k: int, filters: Optional[Dict] = None) -> List[Hit]:
        raise NotImplementedError("TODO: vector search")

    def search_fts(self, table: str, query_text: str, k: int, filters: Optional[Dict] = None) -> List[Hit]:
        raise NotImplementedError("TODO: FTS search")

    def get_refs(self, ref_ids: List[int]) -> List[Dict]:
        raise NotImplementedError("TODO: fetch refs by id")
