from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from threading import Lock
from typing import Any, Dict, Iterable, List, Optional

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from backend.agentic.service import AgenticService
from backend.answer.service import AnswerService
from backend.config import load_config, resolve_path
from backend.factory import build_embedder, build_llm, build_reranker, build_store
from backend.pipeline import output_status
from backend.retrieve.service import Retriever
from backend.util import read_json, read_jsonl


LLM_DIRECT_SYSTEM = """task: llm_direct_answer
Answer using only the connected model's own knowledge.
Do not claim that vector retrieval, card routing, or source drilldown occurred.
If the provider does not expose citations, state uncertainty instead of inventing citations."""

ANSWER_MODES = {
    "agentic": {
        "id": "A1",
        "label": "Agentic router",
        "answer_source": "agentic",
        "family": "agentic",
        "family_label": "Agentic",
        "index": "both",
        "search": "hybrid",
        "rerank": False,
    },
    "pure-rag": {
        "id": "RAG",
        "label": "Pure RAG",
        "answer_source": "pure-rag",
        "family": "rag",
        "family_label": "RAG",
        "index": "both",
        "search": "hybrid",
        "rerank": False,
    },
    "card-direct": {
        "id": "CARD",
        "label": "Card direct",
        "answer_source": "card-direct",
        "family": "llm-wiki",
        "family_label": "LLM + Wiki (Card)",
    },
    "card-grounding": {
        "id": "GROUND",
        "label": "Card + source grounding",
        "answer_source": "card-grounding",
        "family": "llm-wiki",
        "family_label": "LLM + Wiki (Card)",
    },
}


class ChatRequest(BaseModel):
    query: str = ""
    golden_id: Optional[str] = None
    language: str = "en"
    module: Optional[str] = None
    answer_mode: str = "agentic"
    debug: bool = False


class DemoRuntime:
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.outputs_dir = resolve_path(config["paths"]["outputs_dir"])
        self.golden_items = read_jsonl(resolve_path(config["paths"]["golden_seed"]))
        self._golden_by_id = {item["q_id"]: item for item in self.golden_items}
        self._lock = Lock()
        self._retriever: Optional[Retriever] = None
        self._answer_service: Optional[AnswerService] = None
        self._agentic_service: Optional[AgenticService] = None
        self._llm = None

    def modules(self) -> List[str]:
        rows = read_jsonl(resolve_path(self.config["paths"]["keyword_table"]))
        modules = {
            module
            for row in rows
            if row.get("status") == "approved"
            for module in row.get("module", [])
            if isinstance(module, str) and module.strip()
        }
        return sorted(modules)

    def resolve_chat(self, request: ChatRequest) -> tuple[str, Optional[Dict[str, Any]], Optional[Dict[str, str]]]:
        golden = None
        query = request.query.strip()
        if request.golden_id:
            golden = self._golden_by_id.get(request.golden_id)
            if golden is None:
                raise HTTPException(status_code=404, detail=f"Unknown golden question: {request.golden_id}")
            query_key = "q_zh" if request.language.lower().startswith("zh") else "q_en"
            query = str(golden.get(query_key) or golden.get("q_en") or "").strip()
        if not query:
            raise HTTPException(status_code=422, detail="A query or golden_id is required")
        filters = {"module": request.module} if request.module else None
        return query, golden, filters

    def answer(self, query: str, filters: Optional[Dict[str, str]], answer_mode: str, debug: bool = False) -> Dict[str, Any]:
        self._ensure_services()
        assert self._agentic_service is not None
        if answer_mode == "llm-direct":
            return self._answer_from_llm_direct(query, debug=debug)
        variant = ANSWER_MODES.get(answer_mode)
        if variant is None:
            raise ValueError(f"Unknown answer_mode: {answer_mode}")
        variant = {**variant}
        if answer_mode == "pure-rag":
            retrieval = self.config["retrieval"]
            variant.update(
                {
                    "index": retrieval["index"],
                    "search": retrieval["search"],
                    "top_k": int(retrieval["top_k"]),
                    "rrf_k": int(retrieval["rrf_k"]),
                    "rerank": bool(retrieval.get("rerank", False)),
                }
            )
        result = self._agentic_service.answer(query, variant, filters=filters, debug=debug)
        result["execution"]["family"] = variant["family"]
        result["execution"]["family_label"] = variant["family_label"]
        sections = result.pop("evidence_sections", [])
        return {
            "query": query,
            **result,
            "rerank_status": self._retriever.last_rerank_status if self._retriever is not None else "off",
            "evidence_sections": [public_ref(ref) for ref in sections],
        }

    def _answer_from_llm_direct(self, query: str, debug: bool = False) -> Dict[str, Any]:
        assert self._llm is not None
        answer = self._llm.complete_text(LLM_DIRECT_SYSTEM, query)
        result = {
            "query": query,
            "answer": answer,
            "citations": [],
            "retrieved_section_ids": [],
            "contexts": [],
            "drilled": None,
            "card_evidence": [],
            "evidence_sections": [],
            "rerank_status": "not-applicable",
            "execution": {
                "requested_mode": "llm-direct",
                "path": "llm-direct",
                "family": "baseline",
                "family_label": "Model direct (no grounding)",
                "evidence_kind": "none",
                "steps": ["Send question directly to connected LLM", "Return model answer without local grounding or retrieval trace"],
                "intent": None,
                "drilled": None,
                "card": None,
            },
        }
        if debug:
            result["debug"] = {
                "query": query,
                "answer_mode": "llm-direct",
                "intent": None,
                "routing": {
                    "method": "none",
                    "llm_returned_ids": [],
                    "catalog_size": 0,
                    "chosen_card": None,
                },
                "retrieval": None,
                "drilldown": None,
                "refs_used": [],
                "card_used": None,
            }
        return result

    def _ensure_services(self) -> None:
        if self._agentic_service is not None:
            return
        with self._lock:
            if self._agentic_service is not None:
                return
            embedder = build_embedder(self.config)
            store = build_store(self.config, embedder)
            self._retriever = Retriever(embedder, store, build_reranker(self.config))
            self._llm = build_llm(self.config)
            self._answer_service = AnswerService(self._llm)
            self._agentic_service = AgenticService(self.outputs_dir, self._retriever, self._answer_service, self._llm)


def public_ref(ref: Dict[str, Any]) -> Dict[str, Any]:
    score = ref.get("score")
    return {
        "section_id": ref.get("section_id", ""),
        "title": ref.get("title", ""),
        "heading_path": ref.get("heading_path", []),
        "source_url": ref.get("source_url", ""),
        "module": ref.get("module", []),
        "score": round(float(score), 6) if isinstance(score, (int, float)) else None,
        "body_md": ref.get("body_md", ""),
    }


def stream_chunks(text: str, chunk_size: int = 14) -> Iterable[str]:
    for start in range(0, len(text), chunk_size):
        yield text[start : start + chunk_size]


def ndjson(payload: Dict[str, Any]) -> bytes:
    return (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")


def report_mode(path: Path) -> str:
    if not path.exists():
        return "missing"
    report = read_json(path)
    embedding_model = str(report.get("embedding_model", "")).lower()
    judge = str(report.get("judge", "")).lower()
    return "demo" if "hash" in embedding_model or judge == "mock" else "real"


def create_app(config_path: str = "config.yaml") -> FastAPI:
    config = load_config(config_path)
    runtime = DemoRuntime(config)
    app = FastAPI(title="Confluence RAG PoC Demo", version="0.1.0")

    @app.get("/api/health")
    def health() -> Dict[str, Any]:
        eval_report_path = runtime.outputs_dir / "eval_report.json"
        return {
            "status": "ok",
            "providers": config["providers"],
            "outputs": output_status(runtime.outputs_dir),
            "golden_size": len(runtime.golden_items),
            "eval_report_mode": report_mode(eval_report_path),
        }

    @app.get("/api/golden")
    def golden() -> Dict[str, Any]:
        return {"items": runtime.golden_items, "modules": runtime.modules()}

    @app.get("/api/cards")
    def cards() -> JSONResponse:
        # Read-only feed for frontend/cards.html (the card visualizer). Returns the
        # cards_index.json array, or [] before the pipeline has produced cards.
        path = runtime.outputs_dir / "cards_index.json"
        return JSONResponse(read_json(path) if path.exists() else [])

    @app.get("/api/eval-report")
    def eval_report(allow_demo: bool = False) -> JSONResponse:
        path = runtime.outputs_dir / "eval_report.json"
        if not path.exists():
            raise HTTPException(status_code=404, detail="Run the demo pipeline to generate eval_report.json")
        report = read_json(path)
        if report_mode(path) == "demo" and not allow_demo:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "demo_report_requires_opt_in",
                    "message": "The available eval report uses mock/hash demo data and was not loaded automatically.",
                },
            )
        return JSONResponse(report)

    @app.post("/api/chat/stream")
    async def chat_stream(request: ChatRequest) -> StreamingResponse:
        query, golden_item, filters = runtime.resolve_chat(request)

        async def events():
            yield ndjson(
                {
                    "type": "meta",
                    "query": query,
                    "golden": golden_item,
                    "filters": filters or {},
                }
            )
            try:
                result = await asyncio.to_thread(runtime.answer, query, filters, request.answer_mode, request.debug)
                for chunk in stream_chunks(result["answer"]):
                    yield ndjson({"type": "token", "text": chunk})
                    await asyncio.sleep(0.018)
                yield ndjson({"type": "result", "result": result})
            except Exception as exc:
                yield ndjson({"type": "error", "message": str(exc)})

        return StreamingResponse(
            events(),
            media_type="application/x-ndjson",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    frontend_dir = resolve_path("frontend")
    app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")
    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Confluence RAG PoC demo web app")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    uvicorn.run(create_app(args.config), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
