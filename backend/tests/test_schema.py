import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError


def test_runtime_cannot_truncate_or_disable_integrity(db):
    from app.db.session import engine

    for sql in ("TRUNCATE raw_records CASCADE", "ALTER TABLE raw_records DISABLE TRIGGER ALL"):
        with pytest.raises(DBAPIError), engine().begin() as conn:
            conn.execute(text(sql))


def test_immutable_profile_and_foreign_key(db):
    from app.db.models import embedding_profiles, snapshot_chunks
    from app.db.session import engine
    from app.providers.embedding import default_profile, register_profile

    profile = register_profile(default_profile())
    for operation in (embedding_profiles.update().values(payload={}), embedding_profiles.delete()):
        with pytest.raises(DBAPIError), engine().begin() as conn:
            conn.execute(operation)
    with pytest.raises(DBAPIError), engine().begin() as conn:
        conn.execute(snapshot_chunks.insert().values(corpus_id="f" * 64, chunk_id="e" * 64))
    with engine().connect() as conn:
        assert conn.execute(embedding_profiles.select()).mappings().one()["id"] == profile


def test_singleton_active_pointer(db):
    from app.db.session import engine

    with pytest.raises(DBAPIError), engine().begin() as conn:
        conn.execute(text("INSERT INTO active_corpus(singleton) VALUES (false)"))


def test_ready_with_migrated_database(client):
    assert client.get("/health/ready").status_code == 200
