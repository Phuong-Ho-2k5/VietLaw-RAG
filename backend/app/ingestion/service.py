from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.core.errors import DomainError
from app.core.hashing import canonical_hash
from app.db import models as m
from app.db.session import engine
from app.ingestion.jobs import assert_claim, item_done, mark_item, prepare_items
from app.ingestion.manifest import load_release
from app.ingestion.releases import release_path


def put(conn, table, values):
    """Insert once, then compare all supplied immutable fields; never overwrite on conflict."""
    primary = [c.name for c in table.primary_key.columns]
    conn.execute(insert(table).values(**values).on_conflict_do_nothing())
    row = (
        conn.execute(select(table).where(*(table.c[key] == values[key] for key in primary)))
        .mappings()
        .first()
    )
    if not row or any(row[key] != value for key, value in values.items()):
        raise DomainError("IDENTITY_CONTENT_CONFLICT")


def import_chunk(conn, corpus_id, chunk):
    put(
        conn,
        m.retrieval_chunks,
        {
            "id": chunk["chunk_id"],
            "version_id": chunk["version_hash"],
            "text": chunk["text"],
            "context_header": chunk["context_header"],
            "content_hash": chunk["content_hash"],
            "payload": chunk,
        },
    )
    for unit in chunk["unit_ids"]:
        put(conn, m.chunk_units, {"chunk_id": chunk["chunk_id"], "unit_id": unit})
    put(conn, m.snapshot_chunks, {"corpus_id": corpus_id, "chunk_id": chunk["chunk_id"]})


def import_release(job):
    release = load_release(release_path(job["payload"]["release_id"]))
    data, corpus_id = release.payload, release.corpus_id
    if corpus_id != job["payload"]["release_id"]:
        raise DomainError("RELEASE_ID_MISMATCH")
    with engine().begin() as conn:
        assert_claim(conn, job)
        existing = (
            conn.execute(select(m.corpus_snapshots).where(m.corpus_snapshots.c.id == corpus_id))
            .mappings()
            .first()
        )
        if existing and existing["complete"]:
            if existing["payload"] != data:
                raise DomainError("IDENTITY_CONTENT_CONFLICT")
            return
        put(conn, m.corpus_snapshots, {"id": corpus_id, "payload": data})
        prepare_items(conn, job, [c["chunk_id"] for c in data["chunks"]])
        for doc in data["documents"]:
            review = doc["review"]
            document_id = canonical_hash({"document_number": review["document_number"]})
            put(
                conn,
                m.legal_documents,
                {
                    "id": document_id,
                    "document_number": review["document_number"],
                    "payload": {
                        "title": review["title"],
                        "document_type": review["document_type"],
                        "issuing_body": review["issuing_body"],
                    },
                },
            )
            raw_key = canonical_hash({"zip_hash": data["zip_sha256"], "path": doc["raw_path"]})
            put(
                conn,
                m.raw_records,
                {
                    "id": raw_key,
                    "zip_hash": data["zip_sha256"],
                    "path": doc["raw_path"],
                    "payload": {
                        "raw_id": doc["raw_id"],
                        "raw_url": doc["raw_url"],
                        "raw_sha256": doc["raw_sha256"],
                        "raw_passage_sha256": doc["raw_passage_sha256"],
                    },
                },
            )
            put(
                conn,
                m.document_versions,
                {
                    "id": doc["version_hash"],
                    "document_id": document_id,
                    "canonical_text": doc["canonical_text"],
                    "payload": doc,
                },
            )
            put(conn, m.version_raw_records, {"version_id": doc["version_hash"], "raw_id": raw_key})
            for unit in doc["legal_units"]:
                put(
                    conn,
                    m.legal_units,
                    {
                        "id": unit["unit_id"],
                        "version_id": doc["version_hash"],
                        "parent_id": unit["parent_id"],
                        "payload": unit,
                    },
                )
    for chunk in data["chunks"]:
        identifier = chunk["chunk_id"]
        try:
            with engine().begin() as conn:
                assert_claim(conn, job)
                if item_done(conn, job, identifier):
                    continue
                import_chunk(conn, corpus_id, chunk)
                mark_item(conn, job, identifier, "succeeded")
        except DomainError as exc:
            with engine().begin() as conn:
                assert_claim(conn, job)
                mark_item(conn, job, identifier, "failed", exc.code)
            raise
    with engine().begin() as conn:
        assert_claim(conn, job)
        conn.execute(
            m.corpus_snapshots.update()
            .where(m.corpus_snapshots.c.id == corpus_id)
            .values(complete=True)
        )
        conn.execute(
            m.review_events.insert().values(
                actor_id=job["actor_id"],
                object_id=corpus_id,
                decision="import",
                note="Imported existing source review; no new legal review claimed",
            )
        )
