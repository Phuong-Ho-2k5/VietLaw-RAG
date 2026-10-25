from datetime import date

import pytest
from helpers import prepare_corpus

from app.rag.retrieval import fuse_rrf, retrieve


def candidate(identifier, rank):
    return dict(
        chunk_id=identifier,
        rank=rank,
        score=0.5,
        provenance={},
        corpus_snapshot_id="c",
        serving_snapshot_id="s",
        embedding_profile_id="p",
    )


def test_rrf_dedup_and_stable_ties():
    rows = fuse_rrf([candidate("a", 1), candidate("b", 2)], [candidate("a", 1), candidate("c", 2)])
    assert [r.chunk_id for r in rows] == ["a", "b", "c"]
    assert rows[0].score == pytest.approx(2 / 61)
    assert rows[1].score == pytest.approx(1 / 62)


def activate_fixture(admin, corpus_path, monkeypatch):
    from app.domain.serving_reader import pin_active
    from app.domain.snapshots import activate, build_serving_snapshot, review_snapshot

    corpus, profile = prepare_corpus(admin, corpus_path, monkeypatch)
    snapshot = build_serving_snapshot(corpus, profile)
    review_snapshot(snapshot["id"], admin, "approve", "fixture review")
    activate(snapshot["id"], None, admin)
    return pin_active()


def test_keyword_does_not_embed(db, admin, corpus_path, monkeypatch):
    from app.providers import local_e5

    ctx = activate_fixture(admin, corpus_path, monkeypatch)

    def forbidden():
        raise AssertionError("Keyword must not load E5")

    monkeypatch.setattr(local_e5, "get_provider", forbidden)
    rows = retrieve(ctx, "hợp đồng", date(2026, 2, 12), "keyword", 5, "contract")
    assert rows
    assert all("contract" in r.provenance["topic_tags"] for r in rows)
    assert all(r.serving_snapshot_id == ctx.serving_id for r in rows)


def test_modes_share_pin_and_topic_filter_before_limit(db, admin, corpus_path, monkeypatch):
    from app.providers import local_e5
    from app.providers.embedding import default_profile

    ctx = activate_fixture(admin, corpus_path, monkeypatch)

    class Queries:
        profile = default_profile()

        def embed_queries(self, texts):
            return [[1.0] + [0.0] * 383]

    monkeypatch.setattr(local_e5, "get_provider", Queries)
    for mode in ("keyword", "vector", "hybrid"):
        rows = retrieve(ctx, "lương", date(2026, 2, 12), mode, 1, "wages")
        assert len(rows) == 1
        assert rows[0].provenance["topic_tags"] == ["wages"]
        assert rows[0].embedding_profile_id == ctx.profile_id


def test_profile_dimension_and_approval_guards(db, admin, corpus_path, monkeypatch):
    from app.core.errors import DomainError
    from app.providers import local_e5
    from app.providers.embedding import EmbeddingProfile

    ctx = activate_fixture(admin, corpus_path, monkeypatch)

    class Wrong:
        profile = EmbeddingProfile(model="wrong")

        def embed_queries(self, texts):
            raise AssertionError("Profile must be checked before encoding")

    monkeypatch.setattr(local_e5, "get_provider", Wrong)
    with pytest.raises(DomainError, match="EMBEDDING_PROFILE_MISMATCH"):
        retrieve(ctx, "test", date(2026, 2, 12), "vector")
