"""Immutable serving manifests, operational review and compare-and-swap activation."""

from dataclasses import asdict

from sqlalchemy import select, text

from app.core.errors import DomainError
from app.core.hashing import canonical_hash, text_hash
from app.db import models as m
from app.db.session import engine
from app.ingestion.manifest import validate_payload
from app.providers.embedding import checked_vector, default_profile


def readiness(conn, corpus_id, profile_id):
    corpus = (
        conn.execute(select(m.corpus_snapshots).where(m.corpus_snapshots.c.id == corpus_id))
        .mappings()
        .first()
    )
    profile = (
        conn.execute(select(m.embedding_profiles).where(m.embedding_profiles.c.id == profile_id))
        .mappings()
        .first()
    )
    if not corpus or not corpus["complete"]:
        raise DomainError("CORPUS_NOT_READY")
    if (
        not profile
        or profile["payload"] != asdict(default_profile())
        or canonical_hash(profile["payload"]) != profile_id
    ):
        raise DomainError("UNSUPPORTED_PROFILE")
    release = validate_payload(corpus["payload"])
    if release.corpus_id != corpus_id:
        raise DomainError("CORPUS_HASH_MISMATCH")
    chunks = (
        conn.execute(
            select(m.retrieval_chunks)
            .join(m.snapshot_chunks, m.snapshot_chunks.c.chunk_id == m.retrieval_chunks.c.id)
            .where(m.snapshot_chunks.c.corpus_id == corpus_id)
            .order_by(m.retrieval_chunks.c.id)
        )
        .mappings()
        .all()
    )
    expected = {c["chunk_id"]: c for c in release.payload["chunks"]}
    if len(chunks) != len(expected):
        raise DomainError("CORPUS_MEMBERSHIP_MISMATCH")
    manifest, members = [], []
    for chunk in chunks:
        if (
            expected.get(chunk["id"]) != chunk["payload"]
            or text_hash(chunk["text"]) != chunk["content_hash"]
        ):
            raise DomainError("CHUNK_HASH_MISMATCH")
        input_hash = text_hash("passage: " + chunk["context_header"] + "\n" + chunk["text"])
        row = (
            conn.execute(
                select(m.chunk_embeddings).where(
                    m.chunk_embeddings.c.chunk_id == chunk["id"],
                    m.chunk_embeddings.c.profile_id == profile_id,
                    m.chunk_embeddings.c.input_hash == input_hash,
                )
            )
            .mappings()
            .first()
        )
        if not row:
            raise DomainError("EMBEDDINGS_NOT_READY")
        vector = checked_vector(row["vector"])
        if canonical_hash(vector) != row["vector_hash"]:
            raise DomainError("VECTOR_HASH_MISMATCH")
        manifest.append([chunk["id"], chunk["content_hash"], input_hash, row["vector_hash"]])
        members.append({"chunk_id": chunk["id"], "embedding_id": row["id"]})
    return {"corpus_id": corpus_id, "profile_id": profile_id, "members": manifest}, members


def snapshot_dto(row):
    return {
        "id": row["id"],
        "corpus_snapshot_id": row["corpus_id"],
        "embedding_profile_id": row["profile_id"],
        "state": row["state"],
        "chunk_count": len(row["payload"]["members"]),
        "manifest_hash": row["id"],
    }


def get_snapshot(identifier):
    with engine().connect() as conn:
        row = (
            conn.execute(select(m.serving_snapshots).where(m.serving_snapshots.c.id == identifier))
            .mappings()
            .first()
        )
        if not row:
            raise DomainError("SNAPSHOT_NOT_FOUND", 404)
        events = (
            conn.execute(
                select(
                    m.review_events.c.actor_id,
                    m.review_events.c.decision,
                    m.review_events.c.note,
                    m.review_events.c.created_at,
                )
                .where(m.review_events.c.object_id == identifier)
                .order_by(m.review_events.c.created_at)
            )
            .mappings()
            .all()
        )
        return dict(snapshot_dto(row), review_events=[dict(e) for e in events])


def build_serving_snapshot(corpus_snapshot_id: str, embedding_profile_id: str):
    with engine().begin() as conn:
        # Serialize identical builds without relying on a last-write-wins upsert.
        conn.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
            {"key": corpus_snapshot_id + embedding_profile_id},
        )
        payload, members = readiness(conn, corpus_snapshot_id, embedding_profile_id)
        identifier = canonical_hash(payload)
        existing = (
            conn.execute(select(m.serving_snapshots).where(m.serving_snapshots.c.id == identifier))
            .mappings()
            .first()
        )
        if existing:
            return snapshot_dto(existing)
        conn.execute(
            m.serving_snapshots.insert().values(
                id=identifier,
                corpus_id=corpus_snapshot_id,
                profile_id=embedding_profile_id,
                payload=payload,
                state="draft",
            )
        )
        for member in members:
            conn.execute(m.serving_snapshot_chunks.insert().values(serving_id=identifier, **member))
        conn.execute(
            m.serving_snapshots.update()
            .where(m.serving_snapshots.c.id == identifier)
            .values(state="ready")
        )
    return get_snapshot(identifier)


def verify_serving(conn, row):
    payload, members = readiness(conn, row["corpus_id"], row["profile_id"])
    saved = (
        conn.execute(
            select(m.serving_snapshot_chunks.c.chunk_id, m.serving_snapshot_chunks.c.embedding_id)
            .where(m.serving_snapshot_chunks.c.serving_id == row["id"])
            .order_by(m.serving_snapshot_chunks.c.chunk_id)
        )
        .mappings()
        .all()
    )
    if (
        payload != row["payload"]
        or canonical_hash(payload) != row["id"]
        or [dict(m) for m in saved] != members
    ):
        raise DomainError("SERVING_HASH_MISMATCH")


def review_snapshot(serving_snapshot_id: str, actor_id, decision: str, note: str):
    if decision not in ("approve", "reject") or not note.strip():
        raise DomainError("INVALID_REVIEW", 422)
    with engine().begin() as conn:
        row = (
            conn.execute(
                select(m.serving_snapshots)
                .where(m.serving_snapshots.c.id == serving_snapshot_id)
                .with_for_update()
            )
            .mappings()
            .first()
        )
        if not row:
            raise DomainError("SNAPSHOT_NOT_FOUND", 404)
        if row["state"] != "ready":
            raise DomainError("SNAPSHOT_NOT_REVIEWABLE")
        if decision == "approve":
            verify_serving(conn, row)
        conn.execute(
            m.review_events.insert().values(
                actor_id=actor_id, object_id=serving_snapshot_id, decision=decision, note=note
            )
        )
        conn.execute(
            m.serving_snapshots.update()
            .where(m.serving_snapshots.c.id == serving_snapshot_id)
            .values(state="approved" if decision == "approve" else "rejected")
        )
    return get_snapshot(serving_snapshot_id)


def activate(serving_snapshot_id: str, expected_active_id: str | None, actor_id):
    with engine().begin() as conn:
        active = conn.execute(select(m.active_corpus).with_for_update()).mappings().one()
        if active["serving_id"] != expected_active_id:
            raise DomainError("ACTIVE_CONFLICT")
        row = (
            conn.execute(
                select(m.serving_snapshots)
                .where(m.serving_snapshots.c.id == serving_snapshot_id)
                .with_for_update()
            )
            .mappings()
            .first()
        )
        if not row:
            raise DomainError("SNAPSHOT_NOT_FOUND", 404)
        if row["state"] not in ("approved", "sealed"):
            raise DomainError("SNAPSHOT_NOT_APPROVED")
        verify_serving(conn, row)
        if active["serving_id"] == serving_snapshot_id:
            return snapshot_dto(row)
        if row["state"] == "approved":
            conn.execute(
                m.serving_snapshots.update()
                .where(m.serving_snapshots.c.id == serving_snapshot_id)
                .values(state="sealed")
            )
        conn.execute(m.active_corpus.update().values(serving_id=serving_snapshot_id))
        conn.execute(
            m.review_events.insert().values(
                actor_id=actor_id,
                object_id=serving_snapshot_id,
                decision="activate",
                note="Previous serving ID: " + str(active["serving_id"]),
            )
        )
    return get_snapshot(serving_snapshot_id)
