from __future__ import annotations

import copy
import os
from pathlib import Path
from typing import Any, Dict

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[1]


DEFAULT_CONFIG: Dict[str, Any] = {
    "providers": {
        "confluence": "file",
        "llm": "mock",
        "embedder": "hash",
        "store": "json",
    },
    "paths": {
        "fixtures_dir": "fixtures/confluence",
        "golden_seed": "fixtures/golden_seed/golden_seed.jsonl",
        "outputs_dir": "outputs",
        "keyword_table": "fixtures/keyword_table.jsonl",
    },
    "slice": {
        "root": "Q2 - Engagement/MDC Onboarding",
    },
    "llm": {
        "base_url": "",
        "model": "mock",
        "api_key_env": "OPENAI_API_KEY",
        "temperature": 0.0,
    },
    "embedder": {
        "model": "hash-lexical",
        "dim": 256,
    },
    "reranker": {
        "model": "BAAI/bge-reranker-v2-m3",
    },
    "store": {
        "path": "outputs/store/store.json",
        "chroma_path": "outputs/chroma",
        "dsn": "postgresql://postgres:postgres@localhost:5432/rag_poc",
    },
    "retrieval": {
        "index": "both",
        "search": "hybrid",
        "top_k": 8,
        "rrf_k": 60,
        "rerank": False,
    },
    "reduce": {
        "resolve_aliases": False,
    },
    "chunk": {
        "min_merge_tokens": 0,
        "max_tokens": 1000,
        "overlap_tokens": 50,
    },
    "generation": {
        "require_citations": True,
        "refuse_when_no_context": True,
    },
    "eval": {
        "golden_size": 50,
        "judge": "mock",
    },
}


def deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    merged = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def resolve_path(path_value: str) -> Path:
    path = Path(path_value)
    if path.is_absolute():
        return path
    return PROJECT_ROOT / path


def load_config(path: str = "config.yaml") -> Dict[str, Any]:
    config_path = resolve_path(path)
    if config_path.exists():
        with config_path.open("r", encoding="utf-8") as fh:
            loaded = yaml.safe_load(fh) or {}
    else:
        loaded = {}
    config = deep_merge(DEFAULT_CONFIG, loaded)
    config["project_root"] = str(PROJECT_ROOT)
    config["env"] = dict(os.environ)
    return config
