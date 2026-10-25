from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.chat.repository import create_conversation, finalize_turn, reserve_turn


def test_turn_idempotency_and_lease(db, admin):
    from app.core.errors import DomainError
    from app.db import models as m
    from app.db.session import engine

    conv = create_conversation(admin)
    turn = reserve_turn(admin, conv.id, "first", "hash", "request")
    for key, digest, code in [
        ("first", "other", "IDEMPOTENCY_CONFLICT"),
        ("first", "hash", "TURN_PROCESSING"),
        ("second", "hash", "CONVERSATION_BUSY"),
    ]:
        with pytest.raises(DomainError) as error:
            reserve_turn(admin, conv.id, key, digest, "new-request")
        assert error.value.code == code
    with engine().begin() as conn:
        conn.execute(
            m.conversations.update()
            .where(m.conversations.c.id == conv.id)
            .values(lease_until=datetime.now(timezone.utc) - timedelta(seconds=1))
        )
    newer = reserve_turn(admin, conv.id, "second", "hash", "new-request")
    with pytest.raises(DomainError, match="TURN_OWNERSHIP_LOST"):
        finalize_turn(turn, {"status": "insufficient_evidence"}, {})
    finalize_turn(newer, {"status": "insufficient_evidence", "answer": ""}, {})
    replay = reserve_turn(admin, conv.id, "second", "hash", "replay")
    assert replay.replay["status"] == "insufficient_evidence"
    with engine().connect() as conn:
        rows = conn.execute(select(m.messages).order_by(m.messages.c.sequence)).mappings().all()
    assert len(rows) == 4
    assert rows[1]["error_code"] == "TURN_INTERRUPTED"
    assert rows[3]["state"] == "completed"


def test_owner_isolation(db, admin):
    from app.auth.passwords import create_user
    from app.chat.repository import list_messages
    from app.core.errors import DomainError

    owner = create_user("chat-owner", "a-secure-long-password", "user")
    other = create_user("chat-other", "a-secure-long-password", "user")
    conv = create_conversation(owner)
    for actor in [other, admin]:
        with pytest.raises(DomainError) as error:
            list_messages(actor, conv.id, 20, None)
        assert error.value.status == 404
        with pytest.raises(DomainError):
            reserve_turn(actor, conv.id, "first", "hash", "req")
    with pytest.raises(DomainError):
        list_messages(owner, uuid4(), 20, None)


def test_two_concurrent_turns_allow_one_reservation(db, admin):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from app.core.errors import DomainError

    conv = create_conversation(admin)
    barrier = Barrier(2)

    def reserve(key):
        barrier.wait(timeout=5)
        try:
            return reserve_turn(admin, conv.id, key, "hash", "req")
        except DomainError as exc:
            return exc.code

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(reserve, ["one", "two"]))
    assert sum(r == "CONVERSATION_BUSY" for r in results) == 1


def test_citation_fk_rejects_nonmember(db, admin, corpus_path, monkeypatch):
    from sqlalchemy.exc import DBAPIError
    from test_citations import evidence_fixture

    from app.db import models as m
    from app.db.session import engine

    ctx, bundle = evidence_fixture(admin, corpus_path, monkeypatch)
    turn = reserve_turn(admin, create_conversation(admin).id, "key", "hash", "req")
    chunk = bundle.chunks[0]
    with pytest.raises(DBAPIError), engine().begin() as conn:
        conn.execute(m.citations.insert().values(id=uuid4(), message_id=turn.message_id,
            chunk_id=chunk["chunk_id"], version_id=chunk["version_hash"], serving_id="f" * 64,
            start=chunk["start"], end=chunk["end"], quote=chunk["text"], metadata={}))
