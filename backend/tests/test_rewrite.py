import time

from app.chat.schemas import HistoryMessage, RewriteResult
from app.core.errors import DomainError
from app.rag.rewrite import rewrite_question


class Rewriter:
    def count_tokens(self, text):
        return len(text)

    def rewrite(self, question, history, deadline):
        return RewriteResult(standalone_question=self.output, needs_clarification=False, reason="")


def test_rewrite_preserves_negation_amount_and_contract():
    provider = Rewriter()
    provider.output = "Hợp đồng xác định thời hạn trả 500 đồng"
    original = "Không có hợp đồng không xác định thời hạn, trả 600 đồng?"
    history = [HistoryMessage(role="user", text="Về hợp đồng")]
    assert (
        rewrite_question(original, history, provider, time.monotonic() + 5).standalone_question
        == original
    )


def test_rewrite_failure_uses_original():
    class Broken(Rewriter):
        def rewrite(self, *args):
            raise DomainError("PROVIDER_TIMEOUT", 504)

    result = rewrite_question(
        "Còn trường hợp đó?",
        [HistoryMessage(role="user", text="Thử việc")],
        Broken(),
        time.monotonic() + 5,
    )
    assert result.fallback
    assert result.standalone_question == "Còn trường hợp đó?"


def test_history_is_bounded_and_not_evidence():
    class Capture(Rewriter):
        def rewrite(self, question, history, deadline):
            assert len(history) <= 6
            assert sum(self.count_tokens(m.text) for m in history) <= 2000
            return RewriteResult(standalone_question=question, needs_clarification=False, reason="")

    rewrite_question(
        "Còn trường hợp đó?",
        [HistoryMessage(role="user", text="x" * 800)] * 10,
        Capture(),
        time.monotonic() + 5,
    )
