from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any, Dict

from backend.answer.service import AnswerService
from backend.config import load_config, resolve_path
from backend.eval.service import EvalService
from backend.factory import build_confluence_source, build_embedder, build_llm, build_store
from backend.ingest.service import IngestionService
from backend.load.service import LoadService
from backend.mapper.service import MapperService
from backend.reducer.service import ReducerService
from backend.retrieve.service import Retriever
from backend.util import ensure_dir


def main() -> None:
    parser = argparse.ArgumentParser(description="Confluence RAG/card PoC pipeline")
    parser.add_argument(
        "command",
        choices=["ingest", "map", "reduce", "load", "retrieve", "answer", "eval", "demo", "status"],
    )
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--query", default="")
    args = parser.parse_args()
    config = load_config(args.config)
    outputs_dir = resolve_path(config["paths"]["outputs_dir"])
    ensure_dir(outputs_dir)

    if args.command == "demo":
        clean_demo_outputs(outputs_dir)
        print_json("ingest", run_ingest(config, outputs_dir))
        print_json("map", run_map(config, outputs_dir))
        print_json("reduce", run_reduce(config, outputs_dir))
        print_json("load", run_load(config, outputs_dir))
        report = run_eval(config, outputs_dir)
        print_json(
            "eval",
            {
                "golden_size": report["golden"]["size"],
                "variants": len(report["variants"]),
                "report": str(outputs_dir / "eval_report.json"),
            },
        )
        return

    if args.command == "ingest":
        print_json("ingest", run_ingest(config, outputs_dir))
    elif args.command == "map":
        print_json("map", run_map(config, outputs_dir))
    elif args.command == "reduce":
        print_json("reduce", run_reduce(config, outputs_dir))
    elif args.command == "load":
        print_json("load", run_load(config, outputs_dir))
    elif args.command == "retrieve":
        print_json("retrieve", run_retrieve(config, outputs_dir, args.query))
    elif args.command == "answer":
        print_json("answer", run_answer(config, outputs_dir, args.query))
    elif args.command == "eval":
        report = run_eval(config, outputs_dir)
        print_json("eval", {"golden_size": report["golden"]["size"], "variants": len(report["variants"])})
    elif args.command == "status":
        print_json("status", output_status(outputs_dir))


def run_ingest(config: Dict[str, Any], outputs_dir: Path) -> Dict[str, int]:
    source = build_confluence_source(config)
    return IngestionService(source, outputs_dir, config.get("chunk", {})).run(config["slice"]["root"])


def run_map(config: Dict[str, Any], outputs_dir: Path) -> Dict[str, int]:
    llm = build_llm(config)
    return MapperService(outputs_dir, llm).run()


def run_reduce(config: Dict[str, Any], outputs_dir: Path) -> Dict[str, int]:
    llm = build_llm(config)
    return ReducerService(outputs_dir, llm).run()


def run_load(config: Dict[str, Any], outputs_dir: Path) -> Dict[str, int]:
    embedder = build_embedder(config)
    store = build_store(config, embedder)
    return LoadService(outputs_dir, embedder, store).run()


def run_eval(config: Dict[str, Any], outputs_dir: Path) -> Dict:
    llm = build_llm(config)
    embedder = build_embedder(config)
    store = build_store(config, embedder)
    retriever = Retriever(embedder, store)
    golden_seed = resolve_path(config["paths"]["golden_seed"])
    return EvalService(outputs_dir, golden_seed, retriever, llm).run()


def run_retrieve(config: Dict[str, Any], outputs_dir: Path, query: str) -> Dict:
    if not query:
        raise ValueError("--query is required for retrieve")
    embedder = build_embedder(config)
    store = build_store(config, embedder)
    retriever = Retriever(embedder, store)
    refs = retriever.retrieve(
        query,
        index=config["retrieval"]["index"],
        search=config["retrieval"]["search"],
        top_k=int(config["retrieval"]["top_k"]),
        rrf_k=int(config["retrieval"]["rrf_k"]),
    )
    return {
        "query": query,
        "hits": [
            {
                "section_id": ref["section_id"],
                "title": ref["title"],
                "heading_path": ref["heading_path"],
                "score": ref.get("score", 0.0),
            }
            for ref in refs
        ],
    }


def run_answer(config: Dict[str, Any], outputs_dir: Path, query: str) -> Dict:
    if not query:
        raise ValueError("--query is required for answer")
    embedder = build_embedder(config)
    store = build_store(config, embedder)
    retriever = Retriever(embedder, store)
    refs = retriever.retrieve(
        query,
        index=config["retrieval"]["index"],
        search=config["retrieval"]["search"],
        top_k=int(config["retrieval"]["top_k"]),
        rrf_k=int(config["retrieval"]["rrf_k"]),
    )
    llm = build_llm(config)
    result = AnswerService(llm).answer_from_refs(query, refs)
    return {"query": query, **result}


def output_status(outputs_dir: Path) -> Dict[str, bool]:
    return {
        "capture": (outputs_dir / "capture").exists(),
        "map": (outputs_dir / "map").exists(),
        "cards": (outputs_dir / "cards").exists(),
        "store": (outputs_dir / "store" / "store.json").exists(),
        "eval_report": (outputs_dir / "eval_report.json").exists(),
    }


def clean_demo_outputs(outputs_dir: Path) -> None:
    ensure_dir(outputs_dir)
    for child in outputs_dir.iterdir():
        if child.name == "chroma":
            continue
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()


def print_json(label: str, payload: Dict) -> None:
    print(json.dumps({"step": label, **payload}, ensure_ascii=False))


if __name__ == "__main__":
    main()
