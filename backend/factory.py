from __future__ import annotations

from typing import Any, Dict

from backend.adapters.confluence_file import FileConfluenceSource
from backend.adapters.confluence_json import CompositeConfluenceSource, JsonConfluenceSource
from backend.adapters.confluence_mcp import McpConfluenceSource
from backend.adapters.embedder_hash import HashEmbedder
from backend.adapters.embedder_intranet import IntranetEmbedder
from backend.adapters.embedder_local import LocalBgeM3Embedder
from backend.adapters.llm_copilot import CopilotLLM
from backend.adapters.llm_gpt55 import Gpt55LLM
from backend.adapters.llm_mock import MockLLM
from backend.adapters.llm_openai_compat import OpenAICompatLLM
from backend.adapters.reranker_bge import BgeReranker
from backend.adapters.store_chroma import ChromaVectorStore
from backend.adapters.store_json import JsonVectorStore
from backend.adapters.store_pgvector import PgVectorStore
from backend.config import resolve_path
from backend.ports import ConfluenceSource, Embedder, LLM, Reranker, VectorStore


def build_confluence_source(config: Dict[str, Any]) -> ConfluenceSource:
    provider = config["providers"]["confluence"]
    if provider == "file":
        return FileConfluenceSource(resolve_path(config["paths"]["fixtures_dir"]))
    if provider == "json":
        return JsonConfluenceSource(resolve_path(config["paths"].get("incoming_dir", "inbox")))
    if provider == "file+json":
        # Existing Confluence (md fixtures) PLUS new pages dropped as JSON, so the
        # new content can conflict with what is already there. See handoff/35.
        return CompositeConfluenceSource([
            FileConfluenceSource(resolve_path(config["paths"]["fixtures_dir"])),
            JsonConfluenceSource(resolve_path(config["paths"].get("incoming_dir", "inbox"))),
        ])
    if provider == "mcp":
        return McpConfluenceSource(config)
    raise ValueError(f"Unknown confluence provider: {provider}")


def build_llm(config: Dict[str, Any]) -> LLM:
    provider = config["providers"]["llm"]
    if provider == "mock":
        return MockLLM()
    if provider == "openai_compat":
        return OpenAICompatLLM(config["llm"])
    if provider == "gpt55":
        return Gpt55LLM(config["llm"])
    if provider == "copilot":
        return CopilotLLM(config["llm"])
    raise ValueError(f"Unknown llm provider: {provider}")


def build_embedder(config: Dict[str, Any]) -> Embedder:
    provider = config["providers"]["embedder"]
    if provider == "hash":
        return HashEmbedder(dim=int(config["embedder"]["dim"]))
    if provider == "local":
        return LocalBgeM3Embedder(config["embedder"])
    if provider == "intranet":
        return IntranetEmbedder(config["embedder"])
    raise ValueError(f"Unknown embedder provider: {provider}")


def build_reranker(config: Dict[str, Any]) -> Reranker:
    return BgeReranker(config.get("reranker", {}))


def build_store(config: Dict[str, Any], embedder: Embedder) -> VectorStore:
    provider = config["providers"]["store"]
    if provider == "json":
        return JsonVectorStore(resolve_path(config["store"]["path"]), embedder.dim)
    if provider == "chroma":
        return ChromaVectorStore(resolve_path(config["store"].get("chroma_path", "outputs/chroma")), embedder.dim)
    if provider == "pgvector":
        return PgVectorStore(config["store"]["dsn"], embedder.dim)
    raise ValueError(f"Unknown store provider: {provider}")
