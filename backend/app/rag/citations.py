from datetime import date
from uuid import uuid4

from sqlalchemy import select

from app.chat.schemas import CitationDTO, ValidatedAnswer
from app.core.errors import DomainError
from app.db import models as m
from app.db.session import engine
from app.domain.serving_reader import read_chunks


def invalid():
    raise DomainError("INVALID_CITATION", 502)


def validate_draft(context, bundle, draft) -> ValidatedAnswer:
    if draft.status != "answered":
        if draft.claims or (
            draft.status == "needs_clarification"
            and not (draft.clarification_question or "").strip()
        ):
            invalid()
        return ValidatedAnswer(
            status=draft.status,
            answer=(
                draft.clarification_question
                if draft.status == "needs_clarification"
                else "Không đủ căn cứ trong corpus đã duyệt."
            )
            or "",
        )
    if not draft.claims or draft.clarification_question is not None or not bundle.chunks:
        invalid()
    dates = {c["as_of_date"] for c in bundle.chunks}
    if len(dates) != 1:
        invalid()
    approved = {
        c["chunk_id"]: c for c in read_chunks(context, date.fromisoformat(next(iter(dates))))
    }
    included = {c["chunk_id"]: c for c in bundle.chunks}
    citations = {}
    with engine().connect() as conn:
        for claim in draft.claims:
            if not claim.text.strip() or not claim.source_ids:
                invalid()
            for identifier in claim.source_ids:
                if identifier not in included or identifier not in approved:
                    invalid()
                chunk = approved[identifier]
                if chunk != included[identifier]:
                    invalid()
                canonical = conn.scalar(
                    select(m.document_versions.c.canonical_text).where(
                        m.document_versions.c.id == chunk["version_hash"]
                    )
                )
                start, end = chunk["start"], chunk["end"]
                if (
                    canonical is None
                    or not 0 <= start < end <= len(canonical)
                    or canonical[start:end] != chunk["text"]
                ):
                    invalid()
                if identifier not in citations:
                    metadata = {
                        key: chunk[key]
                        for key in (
                            "document_number",
                            "article_label",
                            "clause_label",
                            "point_label",
                            "context_header",
                            "official_source_url",
                            "source_evidence",
                            "as_of_date",
                            "reviewed_at",
                            "reviewer",
                        )
                    }
                    citations[identifier] = CitationDTO(
                        id=uuid4(),
                        chunk_id=identifier,
                        version_id=chunk["version_hash"],
                        serving_snapshot_id=context.serving_id,
                        start=start,
                        end=end,
                        quote=canonical[start:end],
                        metadata=metadata,
                    )
    return ValidatedAnswer(
        status="answered",
        answer="\n\n".join(c.text for c in draft.claims),
        claims=draft.claims,
        citations=list(citations.values()),
    )
