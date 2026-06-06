from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from backend.ports import Embedder, LLM


def score_variant_with_ragas(
    eval_items: List[Dict],
    variant_id: str,
    llm: LLM,
    embedder: Embedder,
) -> Tuple[Optional[List[Dict[str, float]]], str]:
    if not hasattr(llm, "complete_text"):
        return None, "ragas-unavailable: LLM port does not provide complete_text"
    try:
        from datasets import Dataset
        from ragas import evaluate
        from ragas.metrics import answer_relevancy, context_precision, context_recall, faithfulness
    except ImportError as exc:
        return None, f"ragas-unavailable: {exc}"

    samples = []
    for item in eval_items:
        result = item["per_variant"][variant_id]
        samples.append(
            {
                "user_input": item["q"],
                "response": result["answer"],
                "retrieved_contexts": result.get("contexts") or [],
                "reference": item["gold_answer"],
            }
        )

    try:
        evaluation = evaluate(
            Dataset.from_list(samples),
            metrics=[faithfulness, answer_relevancy, context_precision, context_recall],
            llm=PortRagasLLM(llm),
            embeddings=PortRagasEmbeddings(embedder),
            raise_exceptions=False,
            show_progress=False,
        )
        rows = evaluation.to_pandas().to_dict("records")
    except Exception as exc:
        return None, f"ragas-unavailable: {exc}"

    scores = []
    for row in rows:
        scores.append(
            {
                "faithfulness": as_score(row.get("faithfulness")),
                "answer_relevancy": as_score(row.get("answer_relevancy")),
                "context_precision": as_score(row.get("context_precision")),
                "context_recall": as_score(row.get("context_recall")),
            }
        )
    return scores, "ragas"


def as_score(value) -> float:
    if isinstance(value, (int, float)):
        return max(0.0, min(1.0, float(value)))
    return 0.0


@dataclass
class PortRagasLLM:
    llm: LLM
    multiple_completion_supported: bool = False
    cache = None

    def __post_init__(self) -> None:
        from ragas.run_config import RunConfig

        self.run_config = RunConfig()

    def set_run_config(self, run_config) -> None:
        self.run_config = run_config

    def generate_text(self, prompt, n: int = 1, temperature: float = 0.01, stop=None, callbacks=None):
        from langchain_core.outputs import Generation, LLMResult

        text = self.llm.complete_text(
            "You are a strict RAGAS evaluator. Follow the prompt and return the requested format.",
            prompt.to_string() if hasattr(prompt, "to_string") else str(prompt),
            temperature=temperature,
        )
        return LLMResult(generations=[[Generation(text=text)] for _ in range(n)])

    async def agenerate_text(self, prompt, n: int = 1, temperature: float = 0.01, stop=None, callbacks=None):
        return await asyncio.to_thread(self.generate_text, prompt, n, temperature, stop, callbacks)

    async def generate(self, prompt, n: int = 1, temperature: float = 0.01, stop=None, callbacks=None):
        return await self.agenerate_text(prompt, n=n, temperature=temperature, stop=stop, callbacks=callbacks)

    def is_finished(self, response) -> bool:
        return True


class PortRagasEmbeddings:
    def __init__(self, embedder: Embedder):
        from ragas.run_config import RunConfig

        self.embedder = embedder
        self.run_config = RunConfig()

    def set_run_config(self, run_config) -> None:
        self.run_config = run_config

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        return self.embedder.embed(texts, kind="passage")

    def embed_query(self, text: str) -> List[float]:
        return self.embedder.embed([text], kind="query")[0]

    async def aembed_documents(self, texts: List[str]) -> List[List[float]]:
        return await asyncio.to_thread(self.embed_documents, texts)

    async def aembed_query(self, text: str) -> List[float]:
        return await asyncio.to_thread(self.embed_query, text)

    async def embed_text(self, text: str, is_async: bool = True) -> List[float]:
        return self.embed_query(text) if not is_async else await self.aembed_query(text)

    async def embed_texts(self, texts: List[str], is_async: bool = True) -> List[List[float]]:
        return self.embed_documents(texts) if not is_async else await self.aembed_documents(texts)
