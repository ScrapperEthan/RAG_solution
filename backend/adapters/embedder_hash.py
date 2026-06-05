from __future__ import annotations

import hashlib
import math
import re
from typing import List, Literal


TOKEN_RE = re.compile(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]+")


class HashEmbedder:
    """Deterministic lexical embedding for offline tests.

    This keeps the pipeline runnable without downloading BGE-m3. Intranet can switch
    providers to a real embedding implementation without touching pipeline code.
    """

    def __init__(self, dim: int = 256):
        self._dim = dim

    @property
    def dim(self) -> int:
        return self._dim

    def embed(self, texts: List[str], *, kind: Literal["query", "passage"]) -> List[List[float]]:
        return [self._embed_one(text) for text in texts]

    def _embed_one(self, text: str) -> List[float]:
        vec = [0.0] * self._dim
        for token in TOKEN_RE.findall(text.lower()):
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            idx = int.from_bytes(digest[:4], "big") % self._dim
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vec[idx] += sign
        norm = math.sqrt(sum(value * value for value in vec)) or 1.0
        return [value / norm for value in vec]

