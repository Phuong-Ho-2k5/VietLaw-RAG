"""Exact candidate primitives for M4; no ranking tuning or public search endpoint."""

from datetime import date

from sqlalchemy import func, literal_column, select

from app.core.errors import DomainError
from app.db import models as m
from app.db.session import engine
from app.domain.serving_reader import validate_context
from app.providers.embedding import checked_vector


def candidates(context, as_of_date, limit, score, filter_expression=None):
    if not 1 <= limit <= 100:
        raise DomainError("INVALID_LIMIT", 422)
    statement = (
        select(m.retrieval_chunks.c.id, m.retrieval_chunks.c.payload, score.label("score"))
        .join(
            m.serving_snapshot_chunks,
            m.serving_snapshot_chunks.c.chunk_id == m.retrieval_chunks.c.id,
        )
        .join(
            m.chunk_embeddings, m.chunk_embeddings.c.id == m.serving_snapshot_chunks.c.embedding_id
        )
        .where(
            m.serving_snapshot_chunks.c.serving_id == context.serving_id,
            m.chunk_embeddings.c.profile_id == context.profile_id,
            m.retrieval_chunks.c.payload["review_status"].astext == "approved",
            m.retrieval_chunks.c.payload["as_of_date"].astext == as_of_date.isoformat(),
        )
    )
    if filter_expression is not None:
        statement = statement.where(filter_expression)
    with engine().connect() as conn:
        validate_context(conn, context, as_of_date)
        rows = (
            conn.execute(statement.order_by(score.desc(), m.retrieval_chunks.c.id).limit(limit))
            .mappings()
            .all()
        )
        return [
            {
                "chunk_id": r["id"],
                "score": float(r["score"]),
                "rank": i + 1,
                "provenance": r["payload"],
                "corpus_snapshot_id": context.corpus_id,
                "serving_snapshot_id": context.serving_id,
            }
            for i, r in enumerate(rows)
        ]


def vector_candidates(context, vector: list[float], as_of_date: date, limit: int = 5):
    vector = checked_vector(vector, context.dimension)
    score = 1 - m.chunk_embeddings.c.vector.cosine_distance(vector)
    return candidates(context, as_of_date, limit, score)


def keyword_candidates(context, query: str, as_of_date: date, limit: int = 5):
    if not query.strip() or len(query) > 4000:
        raise DomainError("INVALID_QUERY", 422)
    config = literal_column("'simple'::regconfig")
    text_vector = func.to_tsvector(
        config, m.retrieval_chunks.c.context_header + " " + m.retrieval_chunks.c.text
    )
    tsquery = func.plainto_tsquery(config, query)
    return candidates(
        context,
        as_of_date,
        limit,
        func.ts_rank(text_vector, tsquery),
        text_vector.op("@@")(tsquery),
    )
