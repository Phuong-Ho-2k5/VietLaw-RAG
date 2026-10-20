from dataclasses import asdict, replace

import pytest
from sqlalchemy import func, select


@pytest.mark.parametrize(
    "vector", [[0.0] * 384, [1.0] * 383, [float("nan")] * 384, [float("inf")] * 384, [1.0] * 384]
)
def test_reject_invalid_vector(vector):
    from app.core.errors import DomainError
    from app.providers.embedding import checked_vector

    with pytest.raises(DomainError):
        checked_vector(vector)


def test_profile_identity_and_unsupported_provider(db):
    from app.core.errors import DomainError
    from app.core.hashing import canonical_hash
    from app.providers.embedding import default_profile, register_profile

    profile = default_profile()
    assert canonical_hash(asdict(profile)) != canonical_hash(
        asdict(replace(profile, revision="b" * 40))
    )
    assert canonical_hash(asdict(profile)) != canonical_hash(
        asdict(replace(profile, template="other"))
    )
    with pytest.raises(DomainError):
        register_profile(replace(profile, provider="mock"))


def test_embedding_jobs_resume_and_validate_count(db, admin, corpus_path, monkeypatch):
    from app.db.models import chunk_embeddings
    from app.db.session import engine
    from app.ingestion.embedding_jobs import enqueue_embeddings
    from app.ingestion.jobs import enqueue_import, get_job, retry_job
    from app.ingestion.releases import register_release
    from app.ingestion.worker import run_once
    from app.providers import local_e5
    from app.providers.embedding import default_profile, register_profile

    enqueue_import(register_release(corpus_path), admin)
    run_once("import")
    profile = register_profile(default_profile())
    job = enqueue_embeddings(register_release(corpus_path), profile, admin)

    class WrongCount:
        def embed_passages(self, texts):
            return []

    monkeypatch.setattr(local_e5, "get_provider", lambda: WrongCount())
    run_once("bad-output")
    assert get_job(job["id"])["state"] == "failed"
    assert get_job(job["id"])["error"] == "EMBEDDING_COUNT_MISMATCH"

    class TestEncoder:
        def embed_passages(self, texts):
            return [[1.0] + [0.0] * 383 for _ in texts]

    monkeypatch.setattr(local_e5, "get_provider", lambda: TestEncoder())
    retry_job(job["id"], admin)
    run_once("retry")
    assert get_job(job["id"])["state"] == "succeeded"
    assert enqueue_embeddings(register_release(corpus_path), profile, admin)["id"] == job["id"]
    with engine().connect() as conn:
        assert conn.scalar(select(func.count()).select_from(chunk_embeddings)) == 10
        assert all(len(r.vector) == 384 for r in conn.execute(select(chunk_embeddings)))


def test_overlapping_corpus_embedding_jobs_are_concurrently_idempotent(
    db, admin, corpus_path, tmp_path, monkeypatch
):
    import json
    import threading
    from concurrent.futures import ThreadPoolExecutor

    from sqlalchemy.engine import Connection
    from sqlalchemy.sql.dml import Insert

    from app.core.hashing import canonical_hash
    from app.ingestion.embedding_jobs import enqueue_embeddings
    from app.ingestion.jobs import enqueue_import, get_job
    from app.ingestion.releases import register_release
    from app.ingestion.worker import run_once
    from app.providers import local_e5
    from app.providers.embedding import default_profile, register_profile

    payload = json.loads(corpus_path.read_text(encoding="utf-8"))
    payload["chunks"] = payload["chunks"][:-1]
    payload["manifest_hash"] = canonical_hash(
        {k: v for k, v in payload.items() if k != "manifest_hash"}
    )
    second = tmp_path / "overlapping.json"
    second.write_text(json.dumps(payload), encoding="utf-8")
    corpora = [register_release(p) for p in (corpus_path, second)]
    for corpus in corpora:
        enqueue_import(corpus, admin)
        run_once("import")
    profile = register_profile(default_profile())
    jobs = [enqueue_embeddings(corpus, profile, admin) for corpus in corpora]

    class Encoder:
        def embed_passages(self, texts):
            return [[1.0] + [0.0] * 383 for _ in texts]

    monkeypatch.setattr(local_e5, "get_provider", lambda: Encoder())
    barrier = threading.Barrier(2)
    lock = threading.Lock()
    inserts = 0
    original = Connection.execute

    def synchronized_insert(connection, statement, *args, **kwargs):
        nonlocal inserts
        if isinstance(statement, Insert) and statement.table.name == "chunk_embeddings":
            with lock:
                inserts += 1
                first = inserts <= 2
            if first:
                barrier.wait(timeout=10)
        return original(connection, statement, *args, **kwargs)

    monkeypatch.setattr(Connection, "execute", synchronized_insert)
    with ThreadPoolExecutor(2) as pool:
        list(pool.map(run_once, ["embedding-one", "embedding-two"]))
    assert [get_job(job["id"])["state"] for job in jobs] == ["succeeded", "succeeded"]
