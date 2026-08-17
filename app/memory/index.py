from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Sequence
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


def memory_text(payload: dict[str, Any]) -> str:
    """Build bounded index text from public memory fields only."""
    parts = [str(payload.get("kind", "")), str(payload.get("content", ""))]
    parts.extend(str(value) for value in payload.get("tags", []))
    parts.extend(str(value) for value in payload.get("evidence_refs", []))
    return " ".join(part for part in parts if part).strip()


def cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right) or not left:
        raise ValueError("vectors must have the same non-zero dimensions")
    numerator = sum(a * b for a, b in zip(left, right, strict=True))
    denominator = math.sqrt(sum(a * a for a in left)) * math.sqrt(sum(b * b for b in right))
    return numerator / denominator if denominator else 0.0


class HashEmbeddingProvider:
    """Deterministic local embedding used until a model-backed provider is configured."""

    def __init__(self, dimensions: int = 64) -> None:
        if dimensions < 8 or dimensions > 2048:
            raise ValueError("dimensions must be between 8 and 2048")
        self.dimensions = dimensions

    def embed(self, value: str) -> list[float]:
        vector = [0.0] * self.dimensions
        tokens = value.lower().split() or [""]
        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimensions
            sign = 1.0 if digest[4] % 2 else -1.0
            vector[index] += sign
        norm = math.sqrt(sum(component * component for component in vector))
        return [component / norm for component in vector] if norm else vector


class PgvectorMemoryIndex:
    """Secondary PostgreSQL/pgvector index; audit events remain authoritative."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        dimensions: int = 64,
        embedding_provider: HashEmbeddingProvider | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._provider = embedding_provider or HashEmbeddingProvider(dimensions)
        self._table_ready = False

    async def ensure_ready(self) -> None:
        if self._table_ready:
            return
        bind = self._session_factory.kw.get("bind")
        if bind is None or bind.dialect.name != "postgresql":
            raise RuntimeError("pgvector memory index requires PostgreSQL")
        dimensions = self._provider.dimensions
        async with bind.begin() as connection:
            await connection.execute(text(f"""
                CREATE TABLE IF NOT EXISTS triada_memory_embeddings (
                    event_id VARCHAR(36) PRIMARY KEY,
                    memory_id VARCHAR(36) NOT NULL,
                    trace_id VARCHAR(36) NOT NULL,
                    task_id VARCHAR(36) NOT NULL,
                    payload JSONB NOT NULL,
                    embedding vector({dimensions}) NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL
                )
            """))
            await connection.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_triada_memory_embeddings_trace_id "
                "ON triada_memory_embeddings (trace_id)"
            ))
        self._table_ready = True

    async def index_event(self, event: Any) -> None:
        await self.ensure_ready()
        payload = dict(event.payload)
        embedding = self._provider.embed(memory_text(payload))
        async with self._session_factory() as session:
            await session.execute(
                text("""
                    INSERT INTO triada_memory_embeddings
                        (event_id, memory_id, trace_id, task_id, payload, embedding, created_at)
                    VALUES (:event_id, :memory_id, :trace_id, :task_id, CAST(:payload AS jsonb),
                            CAST(:embedding AS vector), :created_at)
                    ON CONFLICT (event_id) DO NOTHING
                """),
                {
                    "event_id": str(event.id),
                    "memory_id": str(payload["memory_id"]),
                    "trace_id": str(event.trace_id),
                    "task_id": str(event.task_id),
                    "payload": json.dumps(payload),
                    "embedding": str(embedding),
                    "created_at": event.created_at,
                },
            )
            await session.commit()

    async def search(self, query: str, *, limit: int = 20) -> list[dict[str, Any]]:
        await self.ensure_ready()
        embedding = self._provider.embed(query)
        async with self._session_factory() as session:
            rows = (await session.execute(text("""
                SELECT event_id, memory_id, trace_id, task_id, payload,
                       embedding <=> CAST(:embedding AS vector) AS distance
                FROM triada_memory_embeddings
                ORDER BY distance, created_at DESC
                LIMIT :limit
            """), {"embedding": str(embedding), "limit": limit})).mappings().all()
        result = []
        for row in rows:
            payload = row["payload"]
            if isinstance(payload, str):
                payload = json.loads(payload)
            result.append({**payload, "event_id": row["event_id"], "trace_id": row["trace_id"], "task_id": row["task_id"], "distance": float(row["distance"])})
        return result
