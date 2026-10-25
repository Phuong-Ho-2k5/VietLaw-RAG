import time
from uuid import UUID

from app.chat import repository
from app.chat.schemas import ChatResult, TurnError, ValidatedAnswer
from app.core.config import Settings
from app.core.errors import DomainError
from app.core.hashing import canonical_hash
from app.domain.serving_reader import pin_active
from app.rag.context import build_context
from app.rag.generation import generate_answer
from app.rag.retrieval import retrieve
from app.rag.rewrite import rewrite_question
from app.rag.temporal import resolve_date


def send_message(owner_id: UUID, conversation_id: UUID, body, idempotency_key, request_id):
    from app.providers.openai_generation import get_generation_provider

    deadline = time.monotonic() + Settings().pipeline_timeout
    turn = repository.reserve_turn(
        owner_id,
        conversation_id,
        idempotency_key,
        canonical_hash(body.model_dump(mode="json")),
        request_id,
        question=body.question,
    )
    if turn.replay is not None:
        return ChatResult.model_validate(turn.replay)
    trace, provider = {"request_id": request_id, "mode": body.mode}, None
    try:
        context = pin_active()
        trace.update(
            corpus_snapshot_id=context.corpus_id,
            serving_snapshot_id=context.serving_id,
            embedding_profile_id=context.profile_id,
            original_query=body.question,
        )
        history = repository.history(owner_id, conversation_id)
        previous = next((m.as_of_date for m in reversed(history) if m.as_of_date), None)
        temporal = resolve_date(body.question, body.as_of_date, previous, context)
        trace.update(
            previous_date=previous.isoformat() if previous else None,
            resolved_date=temporal.as_of_date.isoformat() if temporal.as_of_date else None,
        )
        if temporal.clarification:
            answer = ValidatedAnswer(status="needs_clarification", answer=temporal.clarification)
        else:
            query = body.question
            if history:
                provider = get_generation_provider()
                rewritten = rewrite_question(query, history, provider, deadline)
                trace["rewrite"] = rewritten.model_dump()
                query = rewritten.standalone_question
                # Rewritten/history facts cannot introduce an unverified legal date.
                checked_date = resolve_date(query, temporal.as_of_date, previous, context)
                clarification = checked_date.clarification
                if rewritten.needs_clarification:
                    clarification = (
                        clarification
                        or rewritten.reason.strip()
                        or ("Bạn muốn hỏi cụ thể về trường hợp nào?")
                    )
            else:
                clarification = None
            if clarification:
                answer = ValidatedAnswer(status="needs_clarification", answer=clarification)
            else:
                candidates = retrieve(context, query, temporal.as_of_date, body.mode, 5, body.topic)
                trace["candidates"] = [c.model_dump(exclude={"provenance"}) for c in candidates]
                if not candidates:
                    answer = ValidatedAnswer(
                        status="insufficient_evidence",
                        answer="Không đủ căn cứ trong corpus đã duyệt.",
                    )
                else:
                    if provider is None:
                        provider = get_generation_provider()
                    bundle = build_context(
                        context, candidates, temporal.as_of_date, query, provider
                    )
                    trace.update(
                        context_ids=[c["chunk_id"] for c in bundle.chunks],
                        evidence_tokens=bundle.token_count,
                        excluded_groups=bundle.excluded_groups,
                    )
                    answer = generate_answer(context, query, bundle, provider, deadline)
        if time.monotonic() >= deadline:
            raise DomainError("PROVIDER_TIMEOUT", 504)
        result = ChatResult(
            **answer.model_dump(),
            conversation_id=conversation_id,
            message_id=turn.message_id,
            request_id=request_id,
            corpus_snapshot_id=context.corpus_id,
            serving_snapshot_id=context.serving_id,
            snapshot_id=context.serving_id,
            embedding_profile_id=context.profile_id,
            as_of_date=temporal.as_of_date,
            scope_notice=temporal.scope_notice,
        )
        trace.update(
            status=result.status,
            citation_validation="passed" if result.claims else "not_needed",
            provider_calls=getattr(provider, "metrics", []),
        )
        repository.finalize_turn(turn, result, trace)
        return result
    except Exception as exc:
        error = exc if isinstance(exc, DomainError) else DomainError("INTERNAL_ERROR", 500)
        trace.update(error_code=error.code, provider_calls=getattr(provider, "metrics", []))
        try:
            repository.finalize_turn(turn, TurnError(code=error.code, status=error.status), trace)
        except DomainError as finalize_error:
            if finalize_error.code != "TURN_OWNERSHIP_LOST":
                raise
        raise error from None
    finally:
        if provider is not None:
            provider.close()
