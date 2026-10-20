from alembic import op
from pathlib import Path

revision = "0002"
down_revision = "0001"

IMMUTABLE = (
    "raw_records",
    "legal_documents",
    "document_versions",
    "version_raw_records",
    "legal_units",
    "retrieval_chunks",
    "chunk_units",
    "snapshot_chunks",
    "embedding_profiles",
    "chunk_embeddings",
    "serving_snapshot_chunks",
    "review_events",
)


def upgrade():
    # Historical migration is frozen independently of future ORM metadata.
    schema = Path(__file__).with_name("0002_schema.sql").read_text(encoding="utf-8")
    for statement in schema.split(";"):
        if statement.strip():
            op.execute(statement)
    op.execute("INSERT INTO active_corpus(singleton) VALUES (true)")
    op.execute("""CREATE FUNCTION immutable_row() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN RAISE EXCEPTION 'immutable legal/index/audit record'; END $$""")
    for table in IMMUTABLE:
        op.execute(
            f"CREATE TRIGGER immutable BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION immutable_row()"
        )
    op.execute("""CREATE FUNCTION guard_corpus() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
        IF TG_OP='DELETE' OR OLD.complete OR NEW.id<>OLD.id OR NEW.payload<>OLD.payload THEN
            RAISE EXCEPTION 'immutable corpus'; END IF;
        IF NEW.complete AND (SELECT count(*) FROM snapshot_chunks WHERE corpus_id=NEW.id)
             <>jsonb_array_length(NEW.payload->'chunks') THEN RAISE EXCEPTION 'incomplete corpus'; END IF;
        RETURN NEW; END $$""")
    op.execute(
        "CREATE TRIGGER corpus_guard BEFORE UPDATE OR DELETE ON corpus_snapshots FOR EACH ROW EXECUTE FUNCTION guard_corpus()"
    )
    op.execute("""CREATE FUNCTION guard_snapshot_member() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
        IF (SELECT complete FROM corpus_snapshots WHERE id=NEW.corpus_id) THEN RAISE EXCEPTION 'corpus closed'; END IF;
        IF NOT EXISTS (SELECT 1 FROM corpus_snapshots s, jsonb_array_elements(s.payload->'chunks') c
            WHERE s.id=NEW.corpus_id AND c->>'chunk_id'=NEW.chunk_id
            AND c=(SELECT payload FROM retrieval_chunks WHERE id=NEW.chunk_id))
        THEN RAISE EXCEPTION 'invalid corpus membership'; END IF; RETURN NEW; END $$""")
    op.execute(
        "CREATE TRIGGER snapshot_member BEFORE INSERT ON snapshot_chunks FOR EACH ROW EXECUTE FUNCTION guard_snapshot_member()"
    )
    op.execute("""CREATE FUNCTION guard_serving_member() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
        IF NOT EXISTS (SELECT 1 FROM serving_snapshots s JOIN chunk_embeddings e ON e.id=NEW.embedding_id
            JOIN snapshot_chunks c ON c.corpus_id=s.corpus_id AND c.chunk_id=NEW.chunk_id
            WHERE s.id=NEW.serving_id AND s.state='draft' AND e.chunk_id=NEW.chunk_id AND e.profile_id=s.profile_id)
        THEN RAISE EXCEPTION 'invalid or closed serving membership'; END IF; RETURN NEW; END $$""")
    op.execute(
        "CREATE TRIGGER serving_member BEFORE INSERT ON serving_snapshot_chunks FOR EACH ROW EXECUTE FUNCTION guard_serving_member()"
    )
    op.execute("""CREATE FUNCTION guard_serving() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
        IF TG_OP='DELETE' OR OLD.state='sealed' OR NEW.id<>OLD.id OR NEW.corpus_id<>OLD.corpus_id
            OR NEW.profile_id<>OLD.profile_id OR NEW.payload<>OLD.payload THEN RAISE EXCEPTION 'immutable serving snapshot'; END IF;
        IF NOT ((OLD.state='draft' AND NEW.state='ready') OR (OLD.state='ready' AND NEW.state IN ('approved','rejected'))
            OR (OLD.state='approved' AND NEW.state='sealed')) THEN RAISE EXCEPTION 'invalid transition'; END IF;
        IF NEW.state IN ('ready','approved','sealed') AND (SELECT count(*) FROM serving_snapshot_chunks WHERE serving_id=NEW.id)
            <>(SELECT count(*) FROM snapshot_chunks WHERE corpus_id=NEW.corpus_id) THEN RAISE EXCEPTION 'missing embeddings'; END IF;
        RETURN NEW; END $$""")
    op.execute(
        "CREATE TRIGGER serving_guard BEFORE UPDATE OR DELETE ON serving_snapshots FOR EACH ROW EXECUTE FUNCTION guard_serving()"
    )
    op.execute("""CREATE FUNCTION guard_active() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
        IF TG_OP='DELETE' THEN RAISE EXCEPTION 'active singleton cannot be deleted'; END IF;
        IF NEW.serving_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM serving_snapshots WHERE id=NEW.serving_id AND state='sealed')
        THEN RAISE EXCEPTION 'not sealed'; END IF; RETURN NEW; END $$""")
    op.execute(
        "CREATE TRIGGER active_guard BEFORE INSERT OR UPDATE OR DELETE ON active_corpus FOR EACH ROW EXECUTE FUNCTION guard_active()"
    )


def downgrade():
    raise RuntimeError("Forward-only migrations preserve legal provenance")
