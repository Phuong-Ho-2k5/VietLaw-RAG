from datetime import datetime, timedelta, timezone

import pytest


def test_expired_claim_fences_old_worker_and_retries_checkpoint(db, admin, corpus_path):
    from app.core.errors import DomainError
    from app.db.models import ingestion_jobs
    from app.db.session import engine
    from app.ingestion.jobs import assert_claim, claim, enqueue_import, get_job, retry_job
    from app.ingestion.releases import register_release
    from app.ingestion.worker import run_once

    job = enqueue_import(register_release(corpus_path), admin)
    old = claim("old")
    with engine().begin() as conn:
        conn.execute(
            ingestion_jobs.update().values(
                lease_until=datetime.now(timezone.utc) - timedelta(seconds=1)
            )
        )
    new = claim("new")
    assert old["id"] == new["id"] and old["fence"] != new["fence"]
    with pytest.raises(DomainError), engine().begin() as conn:
        assert_claim(conn, old)
    with engine().begin() as conn:
        conn.execute(
            ingestion_jobs.update().values(
                lease_until=datetime.now(timezone.utc) - timedelta(seconds=1)
            )
        )
    assert run_once("restart")
    assert get_job(job["id"])["state"] == "succeeded"
    with pytest.raises(DomainError):
        retry_job(job["id"], admin)


def test_interrupted_import_resumes_committed_items(db, admin, corpus_path, monkeypatch):
    from app.core.errors import DomainError
    from app.ingestion import service
    from app.ingestion.jobs import enqueue_import, get_job, retry_job
    from app.ingestion.releases import register_release
    from app.ingestion.worker import run_once

    job = enqueue_import(register_release(corpus_path), admin)
    original = service.import_chunk
    calls = 0

    def interrupt(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 3:
            raise DomainError("INJECTED_FAILURE")
        return original(*args, **kwargs)

    monkeypatch.setattr(service, "import_chunk", interrupt)
    run_once("interrupted")
    result = get_job(job["id"])
    assert result["state"] == "failed"
    assert result["counts"]["succeeded"] == 2
    assert result["errors"][-1]["code"] == "INJECTED_FAILURE"
    retry_job(job["id"], admin)
    monkeypatch.setattr(service, "import_chunk", original)
    run_once("resumed")
    assert get_job(job["id"])["counts"]["succeeded"] == 10
    assert get_job(job["id"])["state"] == "succeeded"


def test_transient_database_failure_retries_without_duplicating(
    db, admin, corpus_path, monkeypatch
):
    from sqlalchemy.exc import OperationalError

    from app.ingestion import service, worker
    from app.ingestion.jobs import enqueue_import, get_job
    from app.ingestion.releases import register_release
    from app.ingestion.worker import run_once

    original = service.import_chunk
    calls = 0

    def transient(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls <= 2:
            raise OperationalError(
                "test injected transient disconnect", {}, Exception("disconnect")
            )
        return original(*args, **kwargs)

    monkeypatch.setattr(service, "import_chunk", transient)
    monkeypatch.setattr(worker.time, "sleep", lambda _: None)
    job = enqueue_import(register_release(corpus_path), admin)
    run_once("transient")
    assert get_job(job["id"])["state"] == "succeeded"
    assert get_job(job["id"])["counts"]["succeeded"] == 10
    assert calls == 12
