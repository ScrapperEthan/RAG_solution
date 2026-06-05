from __future__ import annotations

from typing import Dict, List, Literal, Optional, Protocol, TypedDict


class PageRef(TypedDict):
    page_id: str
    title: str
    tree_path: List[str]
    update_at: str
    confluence_version: int


class RawPage(TypedDict):
    page_id: str
    title: str
    space: str
    source_url: str
    owner: str
    labels: List[str]
    captured_at: str
    update_at: str
    confluence_version: int
    tree_path: List[str]
    body_md: str


class Hit(TypedDict):
    ref_id: int
    score: float
    source: Literal["vector", "fts", "card"]


class ConfluenceSource(Protocol):
    def list_pages(self, slice_root: str) -> List[PageRef]:
        ...

    def get_page(self, page_id: str) -> RawPage:
        ...


class LLM(Protocol):
    def complete_json(
        self,
        system: str,
        user: str,
        *,
        schema: Dict,
        temperature: float = 0.0,
        max_tokens: int = 2048,
    ) -> Dict:
        ...


class Embedder(Protocol):
    def embed(self, texts: List[str], *, kind: Literal["query", "passage"]) -> List[List[float]]:
        ...

    @property
    def dim(self) -> int:
        ...


class VectorStore(Protocol):
    def init_schema(self) -> None:
        ...

    def upsert_refs(self, rows: List[Dict]) -> None:
        ...

    def upsert_descriptions(self, rows: List[Dict]) -> None:
        ...

    def upsert_summaries(self, rows: List[Dict]) -> None:
        ...

    def search_vector(
        self, table: str, query_vec: List[float], k: int, filters: Optional[Dict] = None
    ) -> List[Hit]:
        ...

    def search_fts(
        self, table: str, query_text: str, k: int, filters: Optional[Dict] = None
    ) -> List[Hit]:
        ...

    def get_refs(self, ref_ids: List[int]) -> List[Dict]:
        ...

