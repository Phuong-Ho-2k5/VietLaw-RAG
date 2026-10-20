from alembic import op

revision = "0003"
down_revision = "0002"


def upgrade():
    op.execute(
        "CREATE INDEX chunks_fts ON retrieval_chunks USING GIN (to_tsvector('simple', context_header || ' ' || text))"
    )
    op.execute("CREATE INDEX jobs_claim ON ingestion_jobs(state, lease_until)")
    op.execute("CREATE INDEX chunks_profile ON chunk_embeddings(profile_id, chunk_id)")


def downgrade():
    raise RuntimeError("Forward-only migrations preserve legal provenance")
