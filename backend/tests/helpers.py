"""Test-only encoder replaces expensive model computation, never production code."""


def prepare_corpus(admin, corpus_path, monkeypatch):
    from app.ingestion.embedding_jobs import enqueue_embeddings
    from app.ingestion.jobs import enqueue_import, get_job
    from app.ingestion.releases import register_release
    from app.ingestion.worker import run_once
    from app.providers import local_e5
    from app.providers.embedding import default_profile, register_profile

    class Encoder:
        def embed_passages(self, texts):
            return [[1.0] + [0.0] * 383 for _ in texts]

    monkeypatch.setattr(local_e5, "get_provider", lambda: Encoder())
    corpus_id = register_release(corpus_path)
    job = enqueue_import(corpus_id, admin)
    run_once("fixture-import")
    assert get_job(job["id"])["state"] == "succeeded"
    profile_id = register_profile(default_profile())
    job = enqueue_embeddings(corpus_id, profile_id, admin)
    run_once("fixture-embedding")
    assert get_job(job["id"])["state"] == "succeeded"
    return corpus_id, profile_id
