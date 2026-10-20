from dataclasses import asdict

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.core.errors import DomainError
from app.core.hashing import canonical_hash, text_hash
from app.db import models as m
from app.db.session import engine
from app.ingestion.jobs import assert_claim, enqueue, item_done, mark_item, prepare_items
from app.providers.embedding import checked_vector, default_profile


def enqueue_embeddings(corpus_snapshot_id: str, embedding_profile_id: str, actor_id):
    with engine().connect() as conn:
        corpus = (
            conn.execute(
                select(m.corpus_snapshots).where(m.corpus_snapshots.c.id == corpus_snapshot_id)
            )
            .mappings()
            .first()
        )
        profile = (
            conn.execute(
                select(m.embedding_profiles).where(
                    m.embedding_profiles.c.id == embedding_profile_id
                )
            )
            .mappings()
            .first()
        )
    if not corpus or not corpus["complete"]:
        raise DomainError("CORPUS_NOT_READY", 422)
    if not profile or profile["payload"] != asdict(default_profile()):
        raise DomainError("UNSUPPORTED_PROFILE", 422)
    return enqueue(
        "embedding",
        f"embedding:{corpus_snapshot_id}:{embedding_profile_id}",
        {"corpus_id": corpus_snapshot_id, "profile_id": embedding_profile_id},
        actor_id,
    )


def embed_release(job):
    from app.providers.local_e5 import get_provider

    corpus_id, profile_id = job["payload"]["corpus_id"], job["payload"]["profile_id"]
    with engine().begin() as conn:
        assert_claim(conn, job)
        rows = (
            conn.execute(
                select(m.retrieval_chunks)
                .join(m.snapshot_chunks, m.snapshot_chunks.c.chunk_id == m.retrieval_chunks.c.id)
                .where(m.snapshot_chunks.c.corpus_id == corpus_id)
                .order_by(m.retrieval_chunks.c.id)
            )
            .mappings()
            .all()
        )
        prepare_items(conn, job, [row["id"] for row in rows])
    provider = get_provider()
    for row in rows:
        with engine().begin() as conn:
            assert_claim(conn, job)
            if item_done(conn, job, row["id"]):
                continue
        # Model work occurs outside a transaction; heartbeat runs independently.
        text = row["context_header"] + "\n" + row["text"]
        try:
            vectors = provider.embed_passages([text])
            if len(vectors) != 1:
                raise DomainError("EMBEDDING_COUNT_MISMATCH", 422)
            vector = checked_vector(vectors[0])
            input_hash = text_hash("passage: " + text)
            vector_hash = canonical_hash(vector)
            identifier = canonical_hash(
                {"chunk_id": row["id"], "profile_id": profile_id, "input_hash": input_hash}
            )
            with engine().begin() as conn:
                assert_claim(conn, job)
                conn.execute(
                    insert(m.chunk_embeddings)
                    .values(
                        id=identifier,
                        chunk_id=row["id"],
                        profile_id=profile_id,
                        input_hash=input_hash,
                        vector_hash=vector_hash,
                        vector=vector,
                    )
                    .on_conflict_do_nothing()
                )
                saved = (
                    conn.execute(
                        select(m.chunk_embeddings).where(m.chunk_embeddings.c.id == identifier)
                    )
                    .mappings()
                    .one()
                )
                # A competing compatible job may have won the insert. Keep its immutable
                # vector, but verify identity and stored float32 hash instead of overwriting.
                if (
                    saved["input_hash"] != input_hash
                    or saved["profile_id"] != profile_id
                    or saved["chunk_id"] != row["id"]
                    or canonical_hash(checked_vector(saved["vector"])) != saved["vector_hash"]
                ):
                    raise DomainError("EMBEDDING_IDENTITY_CONFLICT")
                mark_item(conn, job, row["id"], "succeeded")
        except DomainError as exc:
            with engine().begin() as conn:
                assert_claim(conn, job)
                mark_item(
                    conn,
                    job,
                    row["id"],
                    "quarantined" if exc.code == "EMBEDDING_INPUT_TOO_LONG" else "failed",
                    exc.code,
                )
            raise
