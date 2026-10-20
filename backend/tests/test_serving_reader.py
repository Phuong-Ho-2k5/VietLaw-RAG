from datetime import date

import pytest
from helpers import prepare_corpus


def test_reader_temporal_topics_and_search_scope(db, admin, corpus_path, monkeypatch):
    from app.core.errors import DomainError
    from app.db.search import keyword_candidates, vector_candidates
    from app.domain.serving_reader import pin_active, read_chunks
    from app.domain.snapshots import activate, build_serving_snapshot, review_snapshot

    with pytest.raises(DomainError):
        pin_active()
    corpus, profile = prepare_corpus(admin, corpus_path, monkeypatch)
    serving = build_serving_snapshot(corpus, profile)
    review_snapshot(serving["id"], admin, "approve", "Checked readiness")
    activate(serving["id"], None, admin)
    context = pin_active()
    assert len(read_chunks(context, date(2026, 2, 12))) == 10
    assert len(read_chunks(context, date(2026, 2, 12), "probation")) == 2
    with pytest.raises(DomainError):
        read_chunks(context, date(2026, 10, 20))
    assert not read_chunks(context, date(2026, 2, 12), "unknown")
    assert keyword_candidates(context, "lương", date(2026, 2, 12), 5)
    candidates = vector_candidates(context, [1.0] + [0.0] * 383, date(2026, 2, 12), 5)
    assert len(candidates) == 5
    assert all(
        c["corpus_snapshot_id"] == corpus and c["serving_snapshot_id"] == context.serving_id
        for c in candidates
    )
    with pytest.raises(DomainError):
        vector_candidates(context, [1.0], date(2026, 2, 12), 5)
