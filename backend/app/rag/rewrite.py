import re
import time

from app.chat.schemas import RewriteResult
from app.core.errors import DomainError


def rewrite_question(question, history, provider, deadline):
    if time.monotonic() >= deadline:
        raise DomainError("PROVIDER_TIMEOUT", 504)
    bounded, tokens = [], 0
    for message in reversed(history[-6:]):
        size = provider.count_tokens(message.text)
        if tokens + size > 2000:
            break
        bounded.insert(0, message)
        tokens += size
    fallback = RewriteResult(
        standalone_question=question, needs_clarification=False, reason="", fallback=True
    )
    if not bounded:
        return RewriteResult(standalone_question=question, needs_clarification=False, reason="")
    try:
        result = provider.rewrite(question, bounded, deadline)
        if result.needs_clarification:
            return RewriteResult(
                standalone_question=question,
                needs_clarification=True,
                reason=result.reason.strip() or "Bạn muốn hỏi cụ thể về trường hợp nào?",
            )
        rewritten = result.standalone_question

        def facts(text):
            return set(re.findall(r"\d+(?:[.,/]\d+)*", text))

        if (
            not rewritten.strip()
            or len(rewritten) > 4000
            or not facts(question).issubset(facts(rewritten))
            or not facts(rewritten).issubset(facts(question + " ".join(m.text for m in bounded)))
            or any(
                negation in question.casefold() and negation not in rewritten.casefold()
                for negation in ("không", "chưa", "chẳng", "chả", "đừng")
            )
        ):
            return fallback

        def contract_types(text):
            return {
                " ".join(term.split())
                for term in re.findall(r"\b(?:không\s+)?xác\s+định\s+thời\s+hạn\b", text.casefold())
            }

        explicit_types = contract_types(question)
        if explicit_types and explicit_types != contract_types(rewritten):
            return fallback
        if "thử việc" in question.casefold() and "thử việc" not in rewritten.casefold():
            return fallback
        return result
    except (DomainError, ValueError):
        if time.monotonic() >= deadline:
            raise DomainError("PROVIDER_TIMEOUT", 504) from None
        return fallback
