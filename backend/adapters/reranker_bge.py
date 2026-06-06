from __future__ import annotations

import re
from typing import Dict, List


TOKEN_RE = re.compile(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]+")


class BgeReranker:
    """Cross-encoder reranker with a deterministic offline fallback."""

    def __init__(self, config: Dict):
        self.model_name = config.get("model") or "BAAI/bge-reranker-v2-m3"
        self.status = self.model_name
        self.placeholder = False
        self.model = None
        try:
            from sentence_transformers import CrossEncoder

            self.model = CrossEncoder(self.model_name)
        except ImportError:
            self.status = "placeholder: lexical fallback; install sentence-transformers for bge-reranker-v2-m3"
            self.placeholder = True

    def rerank(self, query: str, refs: List[Dict]) -> List[Dict]:
        if not refs:
            return []
        rows = [dict(ref) for ref in refs]
        if self.model is not None:
            pairs = [(query, ref.get("body_md", "")) for ref in rows]
            scores = self.model.predict(pairs).tolist()
        else:
            scores = [lexical_score(query, ref) for ref in rows]
        for ref, score in zip(rows, scores):
            ref["rerank_score"] = float(score)
        rows.sort(key=lambda ref: (ref["rerank_score"], ref.get("score", 0.0), str(ref.get("section_id", ""))), reverse=True)
        return rows


def lexical_score(query: str, ref: Dict) -> float:
    query_tokens = set(tokens(query))
    body_tokens = tokens(
        " ".join(
            [
                ref.get("title", ""),
                " ".join(ref.get("heading_path", [])),
                ref.get("body_md", ""),
            ]
        )
    )
    if not query_tokens or not body_tokens:
        return 0.0
    overlap = sum(1 for token in body_tokens if token in query_tokens)
    unique_overlap = len(query_tokens.intersection(body_tokens))
    return unique_overlap + overlap / max(1, len(body_tokens))


def tokens(text: str) -> List[str]:
    return [token.lower() for token in TOKEN_RE.findall(text)]
