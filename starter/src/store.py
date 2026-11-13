"""PostgreSQL + pgvector store: exact cosine search with SQL metadata filters."""
import hashlib
from typing import Any

import psycopg
from psycopg.rows import dict_row

from .models import Chunk

FILTER_COLUMNS = {"version", "section", "subsection", "document_id"}  # whitelist: column names never come from input
RESULT_COLUMNS = "chunk_id, document_id, source, page, version, section, subsection, char_start, char_end, text"


def _vec(vector: list[float]) -> str:
    return "[" + ",".join(f"{x:.7g}" for x in vector) + "]"


class PgVectorStore:
    def __init__(self, database_url: str, dimensions: int) -> None:
        if dimensions <= 0:
            raise ValueError("dimensions must be positive")
        self.database_url = database_url
        self.dimensions = dimensions

    def _connect(self) -> psycopg.Connection:
        return psycopg.connect(self.database_url, connect_timeout=5)

    def create_schema(self) -> None:
        with self._connect() as conn:
            conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
            conn.execute(f"""
                CREATE TABLE IF NOT EXISTS chunks (
                    strategy text NOT NULL,
                    chunk_id text NOT NULL,
                    document_id text NOT NULL,
                    source text NOT NULL,
                    page integer NOT NULL,
                    version text NOT NULL,
                    section text NOT NULL,
                    subsection text NOT NULL,
                    char_start integer NOT NULL,
                    char_end integer NOT NULL,
                    text text NOT NULL,
                    content_hash text NOT NULL,
                    embedding vector({self.dimensions}) NOT NULL,
                    PRIMARY KEY (strategy, chunk_id))""")
            conn.execute("CREATE INDEX IF NOT EXISTS chunks_strategy_version ON chunks (strategy, version)")
            dim = conn.execute("SELECT atttypmod FROM pg_attribute WHERE attrelid = 'chunks'::regclass "
                               "AND attname = 'embedding'").fetchone()[0]
            if dim != self.dimensions:
                raise ValueError(f"table has vector({dim}) but model gives {self.dimensions}")

    def upsert(self, strategy: str, chunks: list[Chunk], vectors: list[list[float]]) -> dict[str, int]:
        """Insert/update by (strategy, chunk_id); delete chunks of these documents that no longer exist."""
        if len(chunks) != len(vectors):
            raise ValueError("chunks and vectors differ in length")
        if any(len(v) != self.dimensions for v in vectors):
            raise ValueError("vector dimension mismatch")
        if len({c.chunk_id for c in chunks}) != len(chunks):
            raise ValueError("duplicate chunk_id in batch")
        rows = [(strategy, c.chunk_id, c.document_id, c.source, c.page, c.metadata["version"],
                 c.metadata["section"], c.metadata["subsection"], c.metadata["char_start"],
                 c.metadata["char_end"], c.text, hashlib.sha256(c.text.encode()).hexdigest(), _vec(v))
                for c, v in zip(chunks, vectors)]
        with self._connect() as conn, conn.cursor() as cur:
            cur.executemany("""
                INSERT INTO chunks (strategy, chunk_id, document_id, source, page, version, section,
                                    subsection, char_start, char_end, text, content_hash, embedding)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::vector)
                ON CONFLICT (strategy, chunk_id) DO UPDATE SET
                    document_id = EXCLUDED.document_id, source = EXCLUDED.source, page = EXCLUDED.page,
                    version = EXCLUDED.version, section = EXCLUDED.section, subsection = EXCLUDED.subsection,
                    char_start = EXCLUDED.char_start, char_end = EXCLUDED.char_end, text = EXCLUDED.text,
                    content_hash = EXCLUDED.content_hash, embedding = EXCLUDED.embedding""", rows)
            cur.execute("DELETE FROM chunks WHERE strategy = %s AND document_id = ANY(%s) AND NOT chunk_id = ANY(%s)",
                        (strategy, sorted({c.document_id for c in chunks}), [c.chunk_id for c in chunks]))
            deleted = cur.rowcount
        # counted after commit, on a fresh connection
        return {"written": len(rows), "obsolete_deleted": deleted, "rows_now": self.count(strategy)}

    def count(self, strategy: str) -> int:
        with self._connect() as conn:
            return conn.execute("SELECT count(*) FROM chunks WHERE strategy = %s", (strategy,)).fetchone()[0]

    def delete_strategy(self, strategy: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM chunks WHERE strategy = %s", (strategy,))

    def search(self, strategy: str, query_vector: list[float], top_k: int = 3,
               filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        filters = filters or {}
        unknown = set(filters) - FILTER_COLUMNS
        if unknown:
            raise ValueError(f"filter not allowed: {sorted(unknown)}")
        where = "".join(f" AND {column} = %s" for column in filters)
        vec = _vec(query_vector)
        with self._connect() as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute(f"SELECT {RESULT_COLUMNS}, 1 - (embedding <=> %s::vector) AS score FROM chunks "
                        f"WHERE strategy = %s{where} ORDER BY embedding <=> %s::vector LIMIT %s",
                        (vec, strategy, *filters.values(), vec, top_k))
            return cur.fetchall()
