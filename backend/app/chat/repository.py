"""Short owner-scoped transactions; no database locks across provider calls."""

import base64
import json
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from sqlalchemy import and_, or_, select

from app.chat.schemas import (
    ConversationDTO,
    ConversationPage,
    HistoryMessage,
    MessageDTO,
    MessagePage,
    ReservedTurn,
    TurnError,
)
from app.core.errors import DomainError
from app.db import models as m
from app.db.session import engine


def owned(conn, owner_id, conversation_id, lock=False):
    stmt = select(m.conversations).where(
        m.conversations.c.id == conversation_id, m.conversations.c.owner_id == owner_id
    )
    row = conn.execute(stmt.with_for_update() if lock else stmt).mappings().first()
    if not row:
        raise DomainError("CONVERSATION_NOT_FOUND", 404)
    return row


def create_conversation(owner_id: UUID) -> ConversationDTO:
    with engine().begin() as conn:
        row = (
            conn.execute(
                m.conversations.insert()
                .values(owner_id=owner_id)
                .returning(m.conversations.c.id, m.conversations.c.created_at)
            )
            .mappings()
            .one()
        )
        return ConversationDTO(**row)


@contextmanager
def reservation_transaction():
    # Recovery is durable even when the current request replays a failed key.
    # Only domain rejections commit; database/unexpected exceptions still roll back.
    rejected = None
    with engine().begin() as conn:
        try:
            yield conn
        except DomainError as exc:
            rejected = exc
    if rejected is not None:
        raise rejected


def reserve_turn(
    owner_id, conversation_id, key, request_hash, request_id, question=""
) -> ReservedTurn:
    with reservation_transaction() as conn:
        conv = owned(conn, owner_id, conversation_id, True)
        now = datetime.now(timezone.utc)
        if conv["in_flight_message_id"] and conv["lease_until"] <= now:
            conn.execute(
                m.messages.update()
                .where(
                    m.messages.c.id == conv["in_flight_message_id"],
                    m.messages.c.state == "processing",
                )
                .values(state="failed", error_code="TURN_INTERRUPTED", error_status=503)
            )
            conn.execute(
                m.conversations.update()
                .where(m.conversations.c.id == conversation_id)
                .values(in_flight_message_id=None, fence=None, lease_until=None)
            )
            conv = dict(conv, in_flight_message_id=None)
        previous = (
            conn.execute(
                select(m.messages).where(
                    m.messages.c.conversation_id == conversation_id,
                    m.messages.c.idempotency_key == key,
                )
            )
            .mappings()
            .first()
        )
        if previous:
            if previous["request_hash"] != request_hash:
                raise DomainError("IDEMPOTENCY_CONFLICT", 409)
            if previous["state"] == "processing":
                raise DomainError("TURN_PROCESSING", 409)
            if previous["state"] == "failed":
                raise DomainError(previous["error_code"], previous["error_status"])
            return ReservedTurn(
                conversation_id=conversation_id,
                message_id=previous["id"],
                fence=uuid4(),
                replay=previous["result"],
            )
        if conv["in_flight_message_id"]:
            raise DomainError("CONVERSATION_BUSY", 409)
        user_id, message_id, fence = uuid4(), uuid4(), uuid4()
        for identifier, role, seq in [
            (user_id, "user", conv["next_sequence"]),
            (message_id, "assistant", conv["next_sequence"] + 1),
        ]:
            conn.execute(
                m.messages.insert().values(
                    id=identifier,
                    conversation_id=conversation_id,
                    turn_id=message_id,
                    role=role,
                    sequence=seq,
                    state="processing" if role == "assistant" else "completed",
                    text=question if role == "user" else "",
                    request_id=request_id,
                    idempotency_key=key if role == "assistant" else None,
                    request_hash=request_hash if role == "assistant" else None,
                )
            )
        conn.execute(
            m.conversations.update()
            .where(m.conversations.c.id == conversation_id)
            .values(
                next_sequence=conv["next_sequence"] + 2,
                in_flight_message_id=message_id,
                fence=fence,
                lease_until=now + timedelta(seconds=90),
            )
        )
        return ReservedTurn(conversation_id=conversation_id, message_id=message_id, fence=fence)


def finalize_turn(turn, result, trace):
    data = result.model_dump(mode="json") if hasattr(result, "model_dump") else result
    trace_data = trace.model_dump(mode="json") if hasattr(trace, "model_dump") else trace
    with engine().begin() as conn:
        conv = (
            conn.execute(
                select(m.conversations)
                .where(m.conversations.c.id == turn.conversation_id)
                .with_for_update()
            )
            .mappings()
            .one()
        )
        if (
            conv["fence"] != turn.fence
            or conv["in_flight_message_id"] != turn.message_id
            or conv["lease_until"] <= datetime.now(timezone.utc)
        ):
            raise DomainError("TURN_OWNERSHIP_LOST", 409)
        if isinstance(result, TurnError):
            values = dict(state="failed", error_code=result.code, error_status=result.status)
        else:
            values = dict(state="completed", result=data, text=data.get("answer", ""))
            for name in (
                "corpus_snapshot_id",
                "serving_snapshot_id",
                "embedding_profile_id",
                "as_of_date",
            ):
                values[name] = data.get(name)
            for citation in data.get("citations", []):
                row = dict(citation)
                row["serving_id"] = row.pop("serving_snapshot_id")
                conn.execute(m.citations.insert().values(message_id=turn.message_id, **row))
        conn.execute(m.messages.update().where(m.messages.c.id == turn.message_id).values(**values))
        conn.execute(
            m.retrieval_traces.insert().values(message_id=turn.message_id, payload=trace_data)
        )
        conn.execute(
            m.conversations.update()
            .where(m.conversations.c.id == turn.conversation_id)
            .values(in_flight_message_id=None, lease_until=None, fence=None)
        )


def encode_cursor(value):
    return base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip("=")


def decode_cursor(value):
    try:
        if len(value) > 512:
            raise ValueError()
        return json.loads(
            base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
        )
    except (ValueError, UnicodeError):
        raise DomainError("INVALID_CURSOR", 422) from None


def list_conversations(owner_id, limit=20, cursor=None):
    stmt = select(m.conversations).where(m.conversations.c.owner_id == owner_id)
    if cursor:
        try:
            decoded = decode_cursor(cursor)
            if (
                not isinstance(decoded, list)
                or len(decoded) != 2
                or any(not isinstance(item, str) for item in decoded)
            ):
                raise ValueError("Invalid cursor types")
            stamp, identifier = decoded
            stamp, identifier = datetime.fromisoformat(stamp), UUID(identifier)
        except (ValueError, TypeError):
            raise DomainError("INVALID_CURSOR", 422) from None
        stmt = stmt.where(
            or_(
                m.conversations.c.created_at < stamp,
                and_(m.conversations.c.created_at == stamp, m.conversations.c.id < identifier),
            )
        )
    with engine().connect() as conn:
        rows = (
            conn.execute(
                stmt.order_by(
                    m.conversations.c.created_at.desc(), m.conversations.c.id.desc()
                ).limit(limit + 1)
            )
            .mappings()
            .all()
        )
    items = [ConversationDTO(id=r["id"], created_at=r["created_at"]) for r in rows[:limit]]
    return ConversationPage(
        items=items,
        next_cursor=encode_cursor([items[-1].created_at.isoformat(), str(items[-1].id)])
        if len(rows) > limit
        else None,
    )


def list_messages(owner_id, conversation_id, limit=20, cursor=None):
    with engine().connect() as conn:
        owned(conn, owner_id, conversation_id)
        after = 0
        if cursor:
            decoded = decode_cursor(cursor)
            if (
                not isinstance(decoded, dict)
                or decoded.get("conversation") != str(conversation_id)
                or type(decoded.get("after")) is not int
                or decoded["after"] < 0
            ):
                raise DomainError("INVALID_CURSOR", 422)
            after = decoded["after"]
        rows = (
            conn.execute(
                select(m.messages)
                .where(
                    m.messages.c.conversation_id == conversation_id, m.messages.c.sequence > after
                )
                .order_by(m.messages.c.sequence)
                .limit(limit + 1)
            )
            .mappings()
            .all()
        )
    fields = MessageDTO.model_fields
    items = [MessageDTO(**{k: r[k] for k in fields}) for r in rows[:limit]]
    return MessagePage(
        items=items,
        next_cursor=encode_cursor(
            {"conversation": str(conversation_id), "after": items[-1].sequence}
        )
        if len(rows) > limit
        else None,
    )


def history(owner_id, conversation_id):
    with engine().connect() as conn:
        owned(conn, owner_id, conversation_id)
        completed = select(m.messages.c.turn_id).where(
            m.messages.c.conversation_id == conversation_id,
            m.messages.c.role == "assistant",
            m.messages.c.state == "completed",
        )
        rows = (
            conn.execute(
                select(m.messages)
                .where(m.messages.c.turn_id.in_(completed))
                .order_by(m.messages.c.sequence.desc())
                .limit(6)
            )
            .mappings()
            .all()
        )
    return [
        HistoryMessage(role=r["role"], text=r["text"], as_of_date=r["as_of_date"])
        for r in reversed(rows)
    ]


def owned_message(conn, owner_id, message_id):
    row = (
        conn.execute(
            select(m.messages)
            .join(m.conversations)
            .where(m.messages.c.id == message_id, m.conversations.c.owner_id == owner_id)
        )
        .mappings()
        .first()
    )
    if not row:
        raise DomainError("MESSAGE_NOT_FOUND", 404)
    return row


def read_citation(owner_id, message_id, citation_id):
    with engine().connect() as conn:
        owned_message(conn, owner_id, message_id)
        row = (
            conn.execute(
                select(m.citations).where(
                    m.citations.c.message_id == message_id, m.citations.c.id == citation_id
                )
            )
            .mappings()
            .first()
        )
        if not row:
            raise DomainError("CITATION_NOT_FOUND", 404)
        result = dict(row)
        result.pop("message_id")
        result["serving_snapshot_id"] = result.pop("serving_id")
        return result


def read_trace(owner_id, message_id):
    with engine().connect() as conn:
        owned_message(conn, owner_id, message_id)
        row = conn.scalar(
            select(m.retrieval_traces.c.payload).where(
                m.retrieval_traces.c.message_id == message_id
            )
        )
        if row is None:
            raise DomainError("TRACE_NOT_READY", 409)
        return row
