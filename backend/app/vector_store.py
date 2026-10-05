from __future__ import annotations

import json
import logging

from pgvector.psycopg import register_vector

from app.catalog import VEHICLES
from app.text import EMBEDDING_DIM, cosine, embed, vehicle_document

logger = logging.getLogger("cg.vector")


class VectorStore:
    def __init__(self, dsn: str | None) -> None:
        self.backend = "memory"
        self._conn = None
        self._memory = {
            vehicle["id"]: embed(vehicle_document(vehicle)) for vehicle in VEHICLES
        }
        if dsn:
            self._try_postgres(dsn)

    def _try_postgres(self, dsn: str) -> None:
        try:
            import psycopg

            conn = psycopg.connect(dsn, autocommit=True, connect_timeout=3)
            conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
            register_vector(conn)
            conn.execute(
                f"""
                CREATE TABLE IF NOT EXISTS vehicle_memory (
                    id TEXT PRIMARY KEY,
                    document TEXT NOT NULL,
                    metadata JSONB NOT NULL,
                    embedding vector({EMBEDDING_DIM}) NOT NULL
                )
                """
            )
            for vehicle in VEHICLES:
                conn.execute(
                    """
                    INSERT INTO vehicle_memory (id, document, metadata, embedding)
                    VALUES (%s, %s, %s::jsonb, %s)
                    ON CONFLICT (id) DO UPDATE
                    SET document = EXCLUDED.document,
                        metadata = EXCLUDED.metadata,
                        embedding = EXCLUDED.embedding
                    """,
                    (
                        vehicle["id"],
                        vehicle_document(vehicle),
                        json.dumps(vehicle),
                        self._memory[vehicle["id"]],
                    ),
                )
            self._conn = conn
            self.backend = "pgvector"
            logger.info("memória vetorial conectada ao pgvector")
        except Exception as exc:
            logger.warning("pgvector indisponível (%s); busca fica em memória", exc)
            self._conn = None
            self.backend = "memory"

    def scores(self, query: str) -> dict[str, float]:
        query_vector = embed(query)
        if self._conn is not None:
            try:
                literal = "[" + ",".join(f"{value:.8f}" for value in query_vector) + "]"
                rows = self._conn.execute(
                    """
                    SELECT id, 1 - (embedding <=> %s::vector) AS score
                    FROM vehicle_memory
                    """,
                    (literal,),
                ).fetchall()
                return {row[0]: float(row[1]) for row in rows}
            except Exception as exc:
                logger.warning("consulta pgvector falhou (%s); usando memória", exc)
        return {
            vehicle_id: cosine(query_vector, vector)
            for vehicle_id, vector in self._memory.items()
        }
