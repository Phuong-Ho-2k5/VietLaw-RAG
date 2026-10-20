from dataclasses import dataclass
from datetime import date

from sqlalchemy import select

from app.core.errors import DomainError
from app.db import models as m
from app.db.session import engine


@dataclass(frozen=True)
class ServingContext:
    serving_id: str
    corpus_id: str
    profile_id: str
    dimension: int
    verified_dates: tuple[str, ...]


def pin_active() -> ServingContext:
    with engine().connect() as conn:
        row = (
            conn.execute(
                select(m.serving_snapshots).join(
                    m.active_corpus, m.active_corpus.c.serving_id == m.serving_snapshots.c.id
                )
            )
            .mappings()
            .first()
        )
        if not row or row["state"] != "sealed":
            raise DomainError("NO_ACTIVE_CORPUS", 503)
        corpus = conn.execute(
            select(m.corpus_snapshots.c.payload).where(m.corpus_snapshots.c.id == row["corpus_id"])
        ).scalar_one()
        return ServingContext(
            row["id"],
            row["corpus_id"],
            row["profile_id"],
            384,
            tuple(corpus["temporal_scope"]["as_of_dates"]),
        )


def validate_context(conn, context: ServingContext, as_of_date: date):
    row = (
        conn.execute(
            select(m.serving_snapshots).where(m.serving_snapshots.c.id == context.serving_id)
        )
        .mappings()
        .first()
    )
    if (
        not row
        or row["state"] != "sealed"
        or row["corpus_id"] != context.corpus_id
        or row["profile_id"] != context.profile_id
        or context.dimension != 384
    ):
        raise DomainError("INVALID_SERVING_CONTEXT")
    corpus = conn.scalar(
        select(m.corpus_snapshots.c.payload).where(m.corpus_snapshots.c.id == context.corpus_id)
    )
    if as_of_date.isoformat() not in corpus["temporal_scope"]["as_of_dates"]:
        raise DomainError("UNVERIFIED_DATE", 422)


def member_query(context):
    return (
        select(m.retrieval_chunks.c.payload)
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
        )
    )


def read_chunks(context: ServingContext, as_of_date: date, topic: str | None = None) -> list[dict]:
    with engine().connect() as conn:
        validate_context(conn, context, as_of_date)
        rows = conn.execute(member_query(context).order_by(m.retrieval_chunks.c.id)).scalars().all()
        return [
            r
            for r in rows
            if r["review_status"] == "approved"
            and r["as_of_date"] == as_of_date.isoformat()
            and (topic is None or topic in r["topic_tags"])
        ]
