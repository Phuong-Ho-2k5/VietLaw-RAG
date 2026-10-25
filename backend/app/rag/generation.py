import time

from app.chat.schemas import ValidatedAnswer
from app.core.errors import DomainError
from app.rag.citations import validate_draft


def generate_answer(context, question, bundle, provider, deadline):
    if not bundle.chunks:
        return ValidatedAnswer(
            status="insufficient_evidence", answer="Không đủ căn cứ trong corpus đã duyệt."
        )
    errors = []
    for attempt in range(2):
        if time.monotonic() >= deadline:
            raise DomainError("PROVIDER_TIMEOUT", 504)
        draft = provider.generate(question, bundle, errors, deadline)
        try:
            return validate_draft(context, bundle, draft)
        except DomainError as error:
            if attempt or error.code != "INVALID_CITATION":
                raise
            errors = [error.code]
    raise AssertionError("Unreachable")
