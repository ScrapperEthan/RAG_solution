from __future__ import annotations

from typing import Dict, List


def variants() -> List[Dict]:
    return [
        {
            "id": "V1",
            "label": "body · vector · pure RAG",
            "index": "body",
            "search": "vector",
            "rerank": False,
            "answer_source": "pure-rag",
        },
        {
            "id": "V2",
            "label": "body · hybrid · pure RAG",
            "index": "body",
            "search": "hybrid",
            "rerank": False,
            "answer_source": "pure-rag",
        },
        {
            "id": "V3",
            "label": "questions · vector · pure RAG",
            "index": "questions",
            "search": "vector",
            "rerank": False,
            "answer_source": "pure-rag",
        },
        {
            "id": "V4",
            "label": "questions · hybrid · pure RAG",
            "index": "questions",
            "search": "hybrid",
            "rerank": False,
            "answer_source": "pure-rag",
        },
        {
            "id": "V5",
            "label": "both · hybrid · pure RAG",
            "index": "both",
            "search": "hybrid",
            "rerank": False,
            "answer_source": "pure-rag",
        },
        {
            "id": "V6",
            "label": "both · hybrid · rerank placeholder",
            "index": "both",
            "search": "hybrid",
            "rerank": True,
            "answer_source": "pure-rag",
        },
        {
            "id": "C1",
            "label": "card direct",
            "index": "card",
            "search": "card",
            "rerank": False,
            "answer_source": "card-direct",
        },
        {
            "id": "C2",
            "label": "card route + grounding",
            "index": "card",
            "search": "card",
            "rerank": False,
            "answer_source": "card-grounding",
        },
        {
            "id": "A1",
            "label": "agentic card + RAG fallback",
            "index": "both",
            "search": "hybrid",
            "rerank": False,
            "answer_source": "agentic",
        },
    ]

