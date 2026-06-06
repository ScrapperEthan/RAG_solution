from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from backend.ports import Embedder, Hit, Reranker, VectorStore


class Retriever:
    def __init__(self, embedder: Embedder, store: VectorStore, reranker: Optional[Reranker] = None):
        self.embedder = embedder
        self.store = store
        self.reranker = reranker
        self.last_rerank_status = "off"

    def retrieve(
        self,
        query: str,
        *,
        index: str = "both",
        search: str = "hybrid",
        top_k: int = 8,
        rrf_k: int = 60,
        rerank: bool = False,
        filters: Optional[Dict] = None,
    ) -> List[Dict]:
        query_vec = self.embedder.embed([query], kind="query")[0]
        ranked_lists: List[List[Hit]] = []
        vector_k = max(top_k * 2, 10)
        candidate_k = max(top_k * 3, vector_k)

        if index in {"body", "both"}:
            ranked_lists.append(self.store.search_vector("refs", query_vec, candidate_k, filters))
        if index in {"questions", "both"}:
            ranked_lists.append(self.store.search_vector("descriptions", query_vec, candidate_k, filters))
        if search == "hybrid":
            ranked_lists.append(self.store.search_fts("refs", query, candidate_k, filters))
            if index in {"questions", "both"}:
                ranked_lists.append(self.store.search_fts("descriptions", query, candidate_k, filters))

        ranked_lists.append(self.store.search_vector("summaries", query_vec, min(candidate_k, 10), filters))
        fused_ids = rrf(ranked_lists, rrf_k)
        ref_ids = [ref_id for ref_id, _ in fused_ids[:candidate_k]]
        refs = self.store.get_refs(ref_ids)
        refs = [ref for ref in refs if matches_filters(ref, filters)]
        score_by_id = dict(fused_ids)
        for ref in refs:
            ref["score"] = score_by_id.get(ref["ref_id"], 0.0)
        refs.sort(key=lambda ref: score_by_id.get(ref["ref_id"], 0.0), reverse=True)
        if rerank:
            if self.reranker is None:
                self.last_rerank_status = "placeholder: no reranker configured"
            else:
                refs = self.reranker.rerank(query, refs)
                self.last_rerank_status = self.reranker.status
        else:
            self.last_rerank_status = "off"
        return refs[:top_k]


def rrf(ranked_lists: List[List[Hit]], rrf_k: int) -> List[Tuple[int, float]]:
    scores: Dict[int, float] = {}
    for hits in ranked_lists:
        seen_hits: set[Tuple[str, str]] = set()
        for rank, hit in enumerate(hits, start=1):
            hit_key = (hit.get("table", "refs"), hit.get("hit_id", str(hit.get("ref_id", ""))))
            if hit_key in seen_hits:
                continue
            seen_hits.add(hit_key)
            score = 1.0 / (rrf_k + rank)
            for ref_id in hit_ref_ids(hit):
                scores[ref_id] = scores.get(ref_id, 0.0) + score
    return sorted(scores.items(), key=lambda item: item[1], reverse=True)


def hit_ref_ids(hit: Hit) -> List[int]:
    if "ref_ids" in hit:
        return [int(ref_id) for ref_id in hit["ref_ids"]]
    if "ref_id" in hit:
        return [int(hit["ref_id"])]
    return []


def matches_filters(row: Dict, filters: Optional[Dict]) -> bool:
    if not filters:
        return True
    for key, value in filters.items():
        row_value = row.get(key)
        if isinstance(row_value, list):
            if value not in row_value:
                return False
        elif row_value != value:
            return False
    return True
