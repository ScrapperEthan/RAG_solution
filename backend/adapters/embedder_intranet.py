from __future__ import annotations

from typing import Dict, List, Literal


class IntranetEmbedder:
    """Intranet embedding stub.

    Fill this only if the intranet cannot reuse the local BGE-m3/hash-compatible path.
    Ensure dim matches the vector column dimension before loading data.
    """

    def __init__(self, config: Dict):
        self.config = config
        self._dim = int(config.get("dim", 1024))

    @property
    def dim(self) -> int:
        return self._dim

    def embed(self, texts: List[str], *, kind: Literal["query", "passage"]) -> List[List[float]]:
        raise NotImplementedError("Intranet TODO: implement embedding call")

