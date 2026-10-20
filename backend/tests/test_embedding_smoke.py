import pytest


@pytest.mark.model
def test_real_model_import_embed_and_activate(db, admin, corpus_path):
    from app.core.errors import DomainError
    from app.ingestion.embedding_jobs import enqueue_embeddings
    from app.ingestion.jobs import enqueue_import, get_job
    from app.ingestion.releases import register_release
    from app.ingestion.worker import run_once
    from app.providers.embedding import default_profile, register_profile
    from app.providers.local_e5 import get_provider

    release = register_release(corpus_path)
    enqueue_import(release, admin)
    run_once("real-import")
    profile = register_profile(default_profile())
    job = enqueue_embeddings(release, profile, admin)
    run_once("real-embedding")
    assert get_job(job["id"])["state"] == "succeeded"
    assert get_job(job["id"])["counts"]["succeeded"] == 10
    provider = get_provider()
    with pytest.raises(DomainError, match="EMBEDDING_INPUT_TOO_LONG"):
        provider.embed_passages(["word " * 2000])
    assert len(provider.embed_queries(["Tiền lương thử việc?"])[0]) == 384
    from datetime import date

    from app.domain.serving_reader import pin_active, read_chunks
    from app.domain.snapshots import activate, build_serving_snapshot, review_snapshot

    serving = build_serving_snapshot(release, profile)
    review_snapshot(serving["id"], admin, "approve", "Model smoke: preserved M1 review")
    activate(serving["id"], None, admin)
    context = pin_active()
    assert context.corpus_id == "6ebc3836a333f2239e524d6016c0bdf7c11abe6751c4a1b9cd01185e74fb84b7"
    assert len(read_chunks(context, date(2026, 2, 12))) == 10
    from app.db.search import keyword_candidates, vector_candidates

    assert vector_candidates(
        context, provider.embed_queries(["Tiền lương thử việc"])[0], date(2026, 2, 12), 5
    )
    assert keyword_candidates(context, "lương", date(2026, 2, 12), 5)
