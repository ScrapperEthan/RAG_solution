from __future__ import annotations

from typing import Dict, List, Literal


class LocalBgeM3Embedder:
    """Local BGE-m3 embedding adapter.

    The default demo still uses HashEmbedder. Choose providers.embedder=local
    when sentence-transformers and the BGE-m3 model are available.
    """

    def __init__(self, config: Dict):
        self.model_name = config.get("model") or "BAAI/bge-m3"
        self._dim = int(config.get("dim", 1024))
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise RuntimeError(
                "providers.embedder=local requires sentence-transformers. "
                "Install optional dependencies with `uv sync --extra local`."
            ) from exc
        self.model = SentenceTransformer(self.model_name)

    @property
    def dim(self) -> int:
        return self._dim

    def embed(self, texts: List[str], *, kind: Literal["query", "passage"]) -> List[List[float]]:
        prompts = None
        if kind == "query":
            prompts = [f"Represent this sentence for searching relevant passages: {text}" for text in texts]
        encoded = self.model.encode(
            prompts or texts,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        vectors = encoded.tolist()
        if vectors and len(vectors[0]) != self._dim:
            raise ValueError(f"Embedding dim mismatch: model returned {len(vectors[0])}, config expects {self._dim}")
        return vectors
