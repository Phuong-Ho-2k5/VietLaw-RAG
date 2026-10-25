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
        rewritten = result.standalone_question

        def facts(text):
            return set(re.findall(r"\d+(?:[.,/]\d+)*", text))

        if (
            not rewritten.strip()
            or len(rewritten) > 4000
            or not facts(question).issubset(facts(rewritten))
            or not facts(rewritten).issubset(facts(question + " ".join(m.text for m in bounded)))
            or ("không" in question.casefold() and "không" not in rewritten.casefold())
        ):
            return fallback
        for term in ("không xác định thời hạn", "xác định thời hạn", "thử việc"):
            if term in question.casefold() and term not in rewritten.casefold():
                return fallback
        return result
    except (DomainError, ValueError):
        if time.monotonic() >= deadline:
            raise DomainError("PROVIDER_TIMEOUT", 504) from None
        return fallback
