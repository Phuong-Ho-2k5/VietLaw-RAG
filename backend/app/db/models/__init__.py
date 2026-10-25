"""Relational identity and membership; original legal metadata remains in immutable JSONB."""

import uuid

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

metadata = MetaData()


def key(name="id", foreign=None, primary=True):
    args = [ForeignKey(foreign)] if foreign else []
    return Column(name, String(64), *args, primary_key=primary, nullable=False)


def payload():
    return Column("payload", JSONB, nullable=False)


users = Table(
    "users",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
    Column("username", String(120), unique=True, nullable=False),
    Column("password_hash", Text, nullable=False),
    Column("role", String(16), nullable=False),
    Column("disabled", Boolean, nullable=False, server_default="false"),
    CheckConstraint("role in ('admin','user')"),
)
raw_records = Table(
    "raw_records",
    metadata,
    key(),
    Column("zip_hash", String(64), nullable=False),
    Column("path", Text, nullable=False),
    payload(),
    UniqueConstraint("zip_hash", "path"),
)
legal_documents = Table(
    "legal_documents",
    metadata,
    key(),
    Column("document_number", Text, unique=True, nullable=False),
    payload(),
)
document_versions = Table(
    "document_versions",
    metadata,
    key(),
    key("document_id", "legal_documents.id", False),
    Column("canonical_text", Text, nullable=False),
    payload(),
)
version_raw_records = Table(
    "version_raw_records",
    metadata,
    key("version_id", "document_versions.id"),
    key("raw_id", "raw_records.id"),
)
legal_units = Table(
    "legal_units",
    metadata,
    key(),
    key("version_id", "document_versions.id", False),
    Column(
        "parent_id", String(64), ForeignKey("legal_units.id", deferrable=True, initially="DEFERRED")
    ),
    payload(),
)
retrieval_chunks = Table(
    "retrieval_chunks",
    metadata,
    key(),
    key("version_id", "document_versions.id", False),
    Column("text", Text, nullable=False),
    Column("context_header", Text, nullable=False),
    Column("content_hash", String(64), nullable=False),
    payload(),
)
chunk_units = Table(
    "chunk_units",
    metadata,
    key("chunk_id", "retrieval_chunks.id"),
    key("unit_id", "legal_units.id"),
)
corpus_snapshots = Table(
    "corpus_snapshots",
    metadata,
    key(),
    payload(),
    Column("complete", Boolean, server_default="false", nullable=False),
)
snapshot_chunks = Table(
    "snapshot_chunks",
    metadata,
    key("corpus_id", "corpus_snapshots.id"),
    key("chunk_id", "retrieval_chunks.id"),
)
embedding_profiles = Table("embedding_profiles", metadata, key(), payload())
chunk_embeddings = Table(
    "chunk_embeddings",
    metadata,
    key(),
    key("chunk_id", "retrieval_chunks.id", False),
    key("profile_id", "embedding_profiles.id", False),
    Column("input_hash", String(64), nullable=False),
    Column("vector_hash", String(64), nullable=False),
    Column("vector", Vector(384), nullable=False),
    UniqueConstraint("chunk_id", "profile_id", "input_hash"),
)
serving_snapshots = Table(
    "serving_snapshots",
    metadata,
    key(),
    key("corpus_id", "corpus_snapshots.id", False),
    key("profile_id", "embedding_profiles.id", False),
    payload(),
    Column("state", String(16), nullable=False, server_default="draft"),
    CheckConstraint("state in ('draft','ready','approved','rejected','sealed')"),
)
serving_snapshot_chunks = Table(
    "serving_snapshot_chunks",
    metadata,
    key("serving_id", "serving_snapshots.id"),
    key("chunk_id", "retrieval_chunks.id"),
    key("embedding_id", "chunk_embeddings.id", False),
)
active_corpus = Table(
    "active_corpus",
    metadata,
    Column("singleton", Boolean, primary_key=True),
    Column("serving_id", String(64), ForeignKey("serving_snapshots.id")),
    CheckConstraint("singleton = true"),
)
ingestion_jobs = Table(
    "ingestion_jobs",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
    Column("identity", String(200), unique=True, nullable=False),
    Column("kind", String(16), nullable=False),
    payload(),
    Column("actor_id", UUID(as_uuid=True), ForeignKey("users.id"), nullable=False),
    Column("state", String(16), nullable=False, server_default="queued"),
    Column("attempt", Integer, nullable=False, server_default="0"),
    Column("fence", UUID(as_uuid=True)),
    Column("worker_id", Text),
    Column("lease_until", DateTime(timezone=True)),
    Column("error", String(120)),
    Column("errors", JSONB, nullable=False, server_default="[]"),
    CheckConstraint("kind in ('import','embedding')"),
    CheckConstraint("state in ('queued','running','succeeded','failed')"),
)
ingestion_job_items = Table(
    "ingestion_job_items",
    metadata,
    Column("job_id", UUID(as_uuid=True), ForeignKey("ingestion_jobs.id"), primary_key=True),
    Column("item_id", String(64), primary_key=True),
    Column("state", String(16), nullable=False),
    Column("error", String(120)),
    Column("attempt", Integer, nullable=False, server_default="0"),
    CheckConstraint("state in ('pending','running','succeeded','failed','quarantined')"),
)
review_events = Table(
    "review_events",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
    Column("actor_id", UUID(as_uuid=True), ForeignKey("users.id"), nullable=False),
    Column("object_id", Text, nullable=False),
    Column("decision", Text, nullable=False),
    Column("note", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

conversations = Table(
    "conversations", metadata,
    Column("id", UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
    Column("owner_id", UUID(as_uuid=True), ForeignKey("users.id"), nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
    Column("next_sequence", Integer, nullable=False, server_default="1"),
    Column("in_flight_message_id", UUID(as_uuid=True)),
    Column("fence", UUID(as_uuid=True)),
    Column("lease_until", DateTime(timezone=True)),
)
messages = Table(
    "messages", metadata,
    Column("id", UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
    Column("conversation_id", UUID(as_uuid=True), ForeignKey("conversations.id"), nullable=False),
    Column("turn_id", UUID(as_uuid=True), nullable=False),
    Column("sequence", Integer, nullable=False),
    Column("role", String(16), nullable=False),
    Column("text", Text, nullable=False, server_default=""),
    Column("state", String(16), nullable=False),
    Column("result", JSONB),
    Column("request_id", String(64), nullable=False),
    Column("idempotency_key", String(128)),
    Column("request_hash", String(64)),
    Column("error_code", String(120)),
    Column("error_status", Integer),
    Column("corpus_snapshot_id", String(64), ForeignKey("corpus_snapshots.id")),
    Column("serving_snapshot_id", String(64), ForeignKey("serving_snapshots.id")),
    Column("embedding_profile_id", String(64), ForeignKey("embedding_profiles.id")),
    Column("as_of_date", String(10)),
    UniqueConstraint("conversation_id", "sequence"),
    UniqueConstraint("conversation_id", "idempotency_key"),
    CheckConstraint("role in ('user','assistant')"),
    CheckConstraint("state in ('processing','completed','failed')"),
)
citations = Table(
    "citations", metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("message_id", UUID(as_uuid=True), ForeignKey("messages.id"), nullable=False),
    Column("chunk_id", String(64), ForeignKey("retrieval_chunks.id"), nullable=False),
    Column("version_id", String(64), ForeignKey("document_versions.id"), nullable=False),
    Column("serving_id", String(64), nullable=False),
    Column("start", Integer, nullable=False), Column("end", Integer, nullable=False),
    Column("quote", Text, nullable=False),
    Column("metadata", JSONB, nullable=False),
    ForeignKeyConstraint(["serving_id", "chunk_id"],
                         ["serving_snapshot_chunks.serving_id", "serving_snapshot_chunks.chunk_id"]),
    CheckConstraint('"start" >= 0 AND "end" > "start"'),
)
retrieval_traces = Table(
    "retrieval_traces", metadata,
    Column("message_id", UUID(as_uuid=True), ForeignKey("messages.id"), primary_key=True),
    payload(),
)
