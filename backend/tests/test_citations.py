from datetime import date

import pytest
from test_context import Counter
from test_retrieval import activate_fixture

from app.chat.schemas import CandidateDTO, Claim, GenerationDraft
from app.rag.citations import validate_draft
from app.rag.context import build_context


def evidence_fixture(admin, corpus_path, monkeypatch):
    from app.domain.serving_reader import read_chunks

    ctx = activate_fixture(admin, corpus_path, monkeypatch)
    chunk = read_chunks(ctx, date(2026, 2, 12))[0]
    candidate = CandidateDTO(
        chunk_id=chunk["chunk_id"],
        corpus_snapshot_id=ctx.corpus_id,
        serving_snapshot_id=ctx.serving_id,
        embedding_profile_id=ctx.profile_id,
        provenance=chunk,
        score=1,
        rank=1,
    )
    return ctx, build_context(ctx, [candidate], date(2026, 2, 12), "Q", Counter())


@pytest.mark.parametrize("sources", [["fake"], []])
def test_unknown_source_or_empty_source_list_rejected(db, admin, corpus_path, monkeypatch, sources):
    from app.core.errors import DomainError

    ctx, bundle = evidence_fixture(admin, corpus_path, monkeypatch)
    draft = GenerationDraft(
        status="answered",
        clarification_question=None,
        claims=[Claim(text="Claim", source_ids=sources)],
    )
    with pytest.raises(DomainError, match="INVALID_CITATION"):
        validate_draft(ctx, bundle, draft)


def test_db_quote_and_canonical_unicode_span_match(db, admin, corpus_path, monkeypatch):
    from sqlalchemy import select

    from app.db import models as m
    from app.db.session import engine

    ctx, bundle = evidence_fixture(admin, corpus_path, monkeypatch)
    source = bundle.chunks[0]
    draft = GenerationDraft(
        status="answered",
        clarification_question=None,
        claims=[Claim(text="Nhận định", source_ids=[source["chunk_id"]])],
    )
    answer = validate_draft(ctx, bundle, draft)
    citation = answer.citations[0]
    with engine().connect() as conn:
        text = conn.scalar(
            select(m.document_versions.c.canonical_text).where(
                m.document_versions.c.id == citation.version_id
            )
        )
    assert citation.quote == text[citation.start : citation.end] == source["text"]
    assert answer.answer == "Nhận định"
    assert citation.serving_snapshot_id == ctx.serving_id
    bundle.chunks[0] = dict(source, text="forged")
    with pytest.raises(Exception, match="INVALID_CITATION"):
        validate_draft(ctx, bundle, draft)
