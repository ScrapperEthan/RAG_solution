from __future__ import annotations

import json
import re
from typing import Dict, List, Optional, Tuple

from backend.ports import Hit


TABLES = {
    "refs": ("ref_id", "body_md", "body_embedding"),
    "descriptions": ("desc_id", "text", "embedding"),
    "summaries": ("sum_id", "text", "embedding"),
}
FILTER_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class PgVectorStore:
    """pgvector 存储；module 使用 text[] 并建立 GIN 索引。"""

    def __init__(self, dsn: str, dim: int):
        self.dsn = dsn
        self.dim = dim

    def init_schema(self) -> None:
        statements = [
            "CREATE EXTENSION IF NOT EXISTS vector",
            "DROP TABLE IF EXISTS descriptions",
            "DROP TABLE IF EXISTS summaries",
            "DROP TABLE IF EXISTS refs",
            f"""
            CREATE TABLE refs (
                ref_id BIGINT PRIMARY KEY,
                row_json JSONB NOT NULL,
                module TEXT[] NOT NULL DEFAULT '{{}}',
                body_md TEXT NOT NULL,
                body_embedding VECTOR({self.dim}) NOT NULL
            )
            """,
            f"""
            CREATE TABLE descriptions (
                desc_id TEXT PRIMARY KEY,
                ref_id BIGINT NOT NULL,
                row_json JSONB NOT NULL,
                module TEXT[] NOT NULL DEFAULT '{{}}',
                text TEXT NOT NULL,
                embedding VECTOR({self.dim}) NOT NULL
            )
            """,
            f"""
            CREATE TABLE summaries (
                sum_id TEXT PRIMARY KEY,
                ref_ids BIGINT[] NOT NULL DEFAULT '{{}}',
                page_id TEXT NOT NULL,
                row_json JSONB NOT NULL,
                module TEXT[] NOT NULL DEFAULT '{{}}',
                text TEXT NOT NULL,
                embedding VECTOR({self.dim}) NOT NULL
            )
            """,
            "CREATE INDEX refs_module_gin ON refs USING GIN (module)",
            "CREATE INDEX descriptions_module_gin ON descriptions USING GIN (module)",
            "CREATE INDEX summaries_module_gin ON summaries USING GIN (module)",
        ]
        with self._connect(register_vector_type=False) as conn:
            with conn.cursor() as cur:
                for statement in statements:
                    cur.execute(statement)

    def upsert_refs(self, rows: List[Dict]) -> None:
        query = """
            INSERT INTO refs (ref_id, row_json, module, body_md, body_embedding)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (ref_id) DO UPDATE SET
                row_json = EXCLUDED.row_json,
                module = EXCLUDED.module,
                body_md = EXCLUDED.body_md,
                body_embedding = EXCLUDED.body_embedding
        """
        values = [
            (row["ref_id"], self._jsonb(row), row.get("module", []), row["body_md"], row["body_embedding"])
            for row in rows
        ]
        self._executemany(query, values)

    def upsert_descriptions(self, rows: List[Dict]) -> None:
        query = """
            INSERT INTO descriptions (desc_id, ref_id, row_json, module, text, embedding)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (desc_id) DO UPDATE SET
                ref_id = EXCLUDED.ref_id,
                row_json = EXCLUDED.row_json,
                module = EXCLUDED.module,
                text = EXCLUDED.text,
                embedding = EXCLUDED.embedding
        """
        values = [
            (row["desc_id"], row["ref_id"], self._jsonb(row), row.get("module", []), row["text"], row["embedding"])
            for row in rows
        ]
        self._executemany(query, values)

    def upsert_summaries(self, rows: List[Dict]) -> None:
        query = """
            INSERT INTO summaries (sum_id, ref_ids, page_id, row_json, module, text, embedding)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (sum_id) DO UPDATE SET
                ref_ids = EXCLUDED.ref_ids,
                page_id = EXCLUDED.page_id,
                row_json = EXCLUDED.row_json,
                module = EXCLUDED.module,
                text = EXCLUDED.text,
                embedding = EXCLUDED.embedding
        """
        values = [
            (
                row["sum_id"],
                row.get("ref_ids", []),
                row["page_id"],
                self._jsonb(row),
                row.get("module", []),
                row["text"],
                row["embedding"],
            )
            for row in rows
        ]
        self._executemany(query, values)

    def search_vector(self, table: str, query_vec: List[float], k: int, filters: Optional[Dict] = None) -> List[Hit]:
        _, _, embedding_column = table_spec(table)
        where, params = filter_sql(filters)
        query = f"""
            SELECT row_json, 1 - ({embedding_column} <=> %s) AS score
            FROM {table}
            {where}
            ORDER BY {embedding_column} <=> %s
            LIMIT %s
        """
        return self._search(table, query, [query_vec, *params, query_vec, k], "vector")

    def search_fts(self, table: str, query_text: str, k: int, filters: Optional[Dict] = None) -> List[Hit]:
        _, text_column, _ = table_spec(table)
        where, params = filter_sql(filters)
        search_clause = f"to_tsvector('simple', {text_column}) @@ plainto_tsquery('simple', %s)"
        where = f"{where} {'AND' if where else 'WHERE'} {search_clause}"
        query = f"""
            SELECT row_json, ts_rank(to_tsvector('simple', {text_column}), plainto_tsquery('simple', %s)) AS score
            FROM {table}
            {where}
            ORDER BY score DESC
            LIMIT %s
        """
        return self._search(table, query, [query_text, *params, query_text, k], "fts")

    def get_refs(self, ref_ids: List[int]) -> List[Dict]:
        if not ref_ids:
            return []
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT row_json FROM refs WHERE ref_id = ANY(%s)", (ref_ids,))
                rows = [row[0] for row in cur.fetchall()]
        by_id = {int(row["ref_id"]): row for row in rows}
        return [by_id[ref_id] for ref_id in ref_ids if ref_id in by_id]

    def _search(self, table: str, query: str, params: List, source: str) -> List[Hit]:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                rows = cur.fetchall()
        return [hit_for_row(table, row_json, float(score), source) for row_json, score in rows]

    def _executemany(self, query: str, values: List[Tuple]) -> None:
        if not values:
            return
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.executemany(query, values)

    def _connect(self, register_vector_type: bool = True):
        try:
            import psycopg
        except ImportError as exc:
            raise RuntimeError("pgvector store requires `uv sync --extra pgvector`.") from exc
        conn = psycopg.connect(self.dsn)
        if register_vector_type:
            try:
                from pgvector.psycopg import register_vector
            except ImportError as exc:
                conn.close()
                raise RuntimeError("pgvector store requires `uv sync --extra pgvector`.") from exc
            register_vector(conn)
        return conn

    @staticmethod
    def _jsonb(row: Dict):
        from psycopg.types.json import Jsonb

        return Jsonb(json.loads(json.dumps(row, ensure_ascii=False)))


def table_spec(table: str) -> Tuple[str, str, str]:
    if table not in TABLES:
        raise ValueError(f"Unknown table: {table}")
    return TABLES[table]


def filter_sql(filters: Optional[Dict]) -> Tuple[str, List]:
    if not filters:
        return "", []
    clauses = []
    params: List = []
    for key, value in filters.items():
        if key == "module":
            clauses.append("%s = ANY(module)")
            params.append(value)
            continue
        if not FILTER_KEY_RE.fullmatch(key):
            raise ValueError(f"Unsupported filter key: {key!r}")
        clauses.append("row_json ->> %s = %s")
        params.extend([key, json_scalar_text(value)])
    return "WHERE " + " AND ".join(clauses), params


def json_scalar_text(value) -> str:
    if value is True:
        return "true"
    if value is False:
        return "false"
    if value is None:
        return "null"
    return str(value)


def hit_for_row(table: str, row: Dict, score: float, source: str) -> Hit:
    if table == "refs":
        return {"table": table, "hit_id": str(row["ref_id"]), "ref_id": int(row["ref_id"]), "score": score, "source": source}
    if table == "descriptions":
        return {"table": table, "hit_id": str(row["desc_id"]), "ref_id": int(row["ref_id"]), "score": score, "source": source}
    if table == "summaries":
        return {
            "table": table,
            "hit_id": str(row["sum_id"]),
            "ref_ids": [int(ref_id) for ref_id in row.get("ref_ids", [])],
            "page_id": str(row.get("page_id", "")),
            "score": score,
            "source": source,
        }
    raise ValueError(f"Unknown table: {table}")
