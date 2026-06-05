from __future__ import annotations

from typing import Dict, List, Optional

from backend.ports import Embedder, Hit, VectorStore


class Retriever:
    def __init__(self, embedder: Embedder, store: VectorStore):
        self.embedder = embedder
        self.store = store

    def retrieve(
        self,
        query: str,
        *,
        index: str = "both",
        search: str = "hybrid",
        top_k: int = 8,
        rrf_k: int = 60,
        filters: Optional[Dict] = None,
    ) -> List[Dict]:
        query_vec = self.embedder.embed([query], kind="query")[0]
        ranked_lists: List[List[Hit]] = []
        vector_k = max(top_k * 2, 10)

        if index in {"body", "both"}:
            ranked_lists.append(self.store.search_vector("refs", query_vec, vector_k, filters))
        if index in {"questions", "both"}:
            ranked_lists.append(self.store.search_vector("descriptions", query_vec, vector_k, filters))
        if search == "hybrid":
            ranked_lists.append(self.store.search_fts("refs", query, vector_k, filters))
            if index in {"questions", "both"}:
                ranked_lists.append(self.store.search_fts("descriptions", query, vector_k, filters))

        ranked_lists.append(self.store.search_vector("summaries", query_vec, min(vector_k, 10), filters))
        fused_ids = rrf(ranked_lists, rrf_k)
        ref_ids = [ref_id for ref_id, _ in fused_ids[:top_k]]
        refs = self.store.get_refs(ref_ids)
        score_by_id = dict(fused_ids)
        for ref in refs:
            ref["score"] = score_by_id.get(ref["ref_id"], 0.0)
        return refs


def rrf(ranked_lists: List[List[Hit]], rrf_k: int) -> List[tuple[int, float]]:
    scores: Dict[int, float] = {}
    for hits in ranked_lists:
        for rank, hit in enumerate(hits, start=1):
            scores[hit["ref_id"]] = scores.get(hit["ref_id"], 0.0) + 1.0 / (rrf_k + rank)
    return sorted(scores.items(), key=lambda item: item[1], reverse=True)
