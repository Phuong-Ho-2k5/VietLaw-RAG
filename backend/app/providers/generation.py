from typing import Protocol

from app.chat.schemas import ContextBundle, GenerationDraft, HistoryMessage, RewriteResult


class GenerationProvider(Protocol):
    def count_tokens(self, text: str) -> int: ...
    def rewrite(
        self, question: str, history: list[HistoryMessage], deadline: float
    ) -> RewriteResult: ...
    def generate(
        self, question: str, context: ContextBundle, repair_errors: list[str], deadline: float
    ) -> GenerationDraft: ...
