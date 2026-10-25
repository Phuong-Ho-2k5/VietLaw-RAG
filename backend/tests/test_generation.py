import time

import pytest

from app.chat.schemas import ContextBundle, GenerationDraft
from app.rag.generation import generate_answer


def test_no_context_skips_generation():
    class Never:
        def generate(self, *args):
            raise AssertionError("Empty context must not call model")

    result = generate_answer(None, "Q", ContextBundle(), Never(), time.monotonic() + 1)
    assert result.status == "insufficient_evidence"
    assert not result.claims


def test_repair_only_once(db, admin, corpus_path, monkeypatch):
    from test_citations import evidence_fixture

    from app.core.errors import DomainError

    ctx, bundle = evidence_fixture(admin, corpus_path, monkeypatch)

    class Invalid:
        calls = 0

        def generate(self, question, context, errors, deadline):
            self.calls += 1
            if self.calls == 2:
                assert errors == ["INVALID_CITATION"]
            return GenerationDraft(
                status="answered",
                clarification_question=None,
                claims=[{"text": "bad", "source_ids": ["fake"]}],
            )

    provider = Invalid()
    with pytest.raises(DomainError, match="INVALID_CITATION"):
        generate_answer(ctx, "Q", bundle, provider, time.monotonic() + 5)
    assert provider.calls == 2
