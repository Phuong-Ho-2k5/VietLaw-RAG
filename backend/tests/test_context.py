from datetime import date

from test_retrieval import activate_fixture

from app.chat.schemas import CandidateDTO
from app.rag.context import build_context


class Counter:
    def count_tokens(self, text):
        return len(text)


def test_context_budget_keeps_complete_units(db, admin, corpus_path, monkeypatch):
    from app.domain.serving_reader import read_chunks

    ctx = activate_fixture(admin, corpus_path, monkeypatch)
    chunk = next(c for c in read_chunks(ctx, date(2026, 2, 12)) if c["article_label"] == "13")
    candidate = CandidateDTO(
        chunk_id=chunk["chunk_id"],
        corpus_snapshot_id=ctx.corpus_id,
        serving_snapshot_id=ctx.serving_id,
        embedding_profile_id=ctx.profile_id,
        provenance=chunk,
        score=1,
        rank=1,
    )
    monkeypatch.setenv("EVIDENCE_TOKEN_BUDGET", "10")
    assert not build_context(ctx, [candidate], date(2026, 2, 12), "Q", Counter()).chunks
    monkeypatch.setenv("EVIDENCE_TOKEN_BUDGET", "6000")
    bundle = build_context(ctx, [candidate], date(2026, 2, 12), "Q", Counter())
    assert len(bundle.chunks) == 2  # both reviewed clauses in article 13
    assert all(c["article_label"] == "13" for c in bundle.chunks)
    assert all(c["text"] for c in bundle.chunks)
