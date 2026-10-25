from sqlalchemy import select
from test_retrieval import activate_fixture

from app.chat.schemas import GenerationDraft, RewriteResult
from app.core.errors import DomainError


class ChatProvider:
    metrics = []

    def count_tokens(self, text):
        return len(text) // 4

    def rewrite(self, question, history, deadline):
        return RewriteResult(standalone_question=question, needs_clarification=False, reason="")

    def generate(self, question, context, errors, deadline):
        return GenerationDraft(
            status="answered",
            clarification_question=None,
            claims=[
                {
                    "text": "Hợp đồng lao động là sự thỏa thuận giữa người lao động và người sử dụng lao động.",
                    "source_ids": [context.chunks[0]["chunk_id"]],
                }
            ],
        )

    def close(self):
        pass


def chat_setup(client, admin, corpus_path, monkeypatch):
    from app.auth.tokens import issue_token
    from app.providers import openai_generation

    ctx = activate_fixture(admin, corpus_path, monkeypatch)
    monkeypatch.setattr(openai_generation, "get_generation_provider", ChatProvider)
    headers = {"Authorization": "Bearer " + issue_token(admin)}
    response = client.post("/api/v1/conversations", headers=headers)
    assert response.status_code == 201, response.text
    return ctx, headers, response.json()["id"]


def test_chat_answer_followup_and_abstention(client, admin, corpus_path, monkeypatch):
    ctx, headers, conv = chat_setup(client, admin, corpus_path, monkeypatch)
    endpoint = f"/api/v1/conversations/{conv}/messages"
    payload = {"question": "hợp đồng", "mode": "keyword"}
    first = client.post(endpoint, headers=dict(headers, **{"Idempotency-Key": "one"}), json=payload)
    assert first.status_code == 200, first.text
    data = first.json()
    assert data["status"] == "answered"
    assert data["serving_snapshot_id"] == ctx.serving_id
    assert data["as_of_date"] == "2026-02-12"
    replay = client.post(
        endpoint, headers=dict(headers, **{"Idempotency-Key": "one"}), json=payload
    )
    assert replay.json() == data
    follow = client.post(
        endpoint, headers=dict(headers, **{"Idempotency-Key": "two"}), json=payload
    )
    assert follow.status_code == 200
    missing = client.post(
        endpoint,
        headers=dict(headers, **{"Idempotency-Key": "none"}),
        json={"question": "xyzunmatched", "mode": "keyword"},
    )
    assert missing.json()["status"] == "insufficient_evidence"
    clarification = client.post(
        endpoint,
        headers=dict(headers, **{"Idempotency-Key": "date"}),
        json={"question": "Luật hiện nay?", "mode": "keyword"},
    )
    assert clarification.json()["status"] == "needs_clarification"
    citation = data["citations"][0]
    opened = client.get(
        f"/api/v1/messages/{data['message_id']}/citations/{citation['id']}", headers=headers
    )
    assert opened.json()["quote"] == citation["quote"]
    page = client.get(endpoint + "?limit=2", headers=headers).json()
    assert len(page["items"]) == 2 and page["next_cursor"]
    assert (
        client.get(endpoint, params={"cursor": page["next_cursor"]}, headers=headers).json()[
            "items"
        ][0]["sequence"]
        == 3
    )
    assert client.get(endpoint + "?cursor=bad", headers=headers).status_code == 422


def test_history_and_trace_reject_other_owner(client, admin, corpus_path, monkeypatch):
    from app.auth.passwords import create_user
    from app.auth.tokens import issue_token

    _, headers, conv = chat_setup(client, admin, corpus_path, monkeypatch)
    endpoint = f"/api/v1/conversations/{conv}/messages"
    data = client.post(
        endpoint,
        headers=dict(headers, **{"Idempotency-Key": "one"}),
        json={"question": "hợp đồng", "mode": "keyword"},
    ).json()
    other = create_user("other-chat", "a-secure-long-password", "user")
    other_headers = {"Authorization": "Bearer " + issue_token(other)}
    citation = data["citations"][0]["id"]
    for path in [
        endpoint,
        f"/api/v1/messages/{data['message_id']}/trace",
        f"/api/v1/messages/{data['message_id']}/citations/{citation}",
    ]:
        assert client.get(path, headers=other_headers).status_code == 404
    assert client.get("/api/v1/conversations", headers=other_headers).json()["items"] == []


def test_provider_failure_persists_failed_turn(client, admin, corpus_path, monkeypatch):
    from app.db import models as m
    from app.db.session import engine
    from app.providers import openai_generation

    _, headers, conv = chat_setup(client, admin, corpus_path, monkeypatch)

    class Broken(ChatProvider):
        def generate(self, *args):
            raise DomainError("PROVIDER_TIMEOUT", 504)

    monkeypatch.setattr(openai_generation, "get_generation_provider", Broken)
    endpoint = f"/api/v1/conversations/{conv}/messages"
    response = client.post(
        endpoint,
        headers=dict(headers, **{"Idempotency-Key": "one"}),
        json={"question": "hợp đồng", "mode": "keyword"},
    )
    assert response.status_code == 504, response.text
    assert response.json()["request_id"]
    with engine().connect() as conn:
        row = (
            conn.execute(select(m.messages).where(m.messages.c.role == "assistant"))
            .mappings()
            .one()
        )
        assert row["state"] == "failed" and row["result"] is None
        assert not conn.execute(select(m.citations)).first()


def test_historical_citation_survives_activation(client, admin, corpus_path, monkeypatch, tmp_path):
    import json

    from helpers import prepare_corpus

    from app.core.hashing import canonical_hash
    from app.domain.serving_reader import pin_active
    from app.domain.snapshots import activate, build_serving_snapshot, review_snapshot
    from app.providers import openai_generation

    old, headers, conv = chat_setup(client, admin, corpus_path, monkeypatch)
    payload = json.loads(corpus_path.read_text(encoding="utf-8"))
    # A disjoint membership proves source reopening doesn't accidentally use the new snapshot.
    payload["chunks"] = [c for c in payload["chunks"] if c["article_label"] != "13"]
    payload["manifest_hash"] = canonical_hash(
        {k: v for k, v in payload.items() if k != "manifest_hash"}
    )
    other = tmp_path / "other.json"
    other.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    corpus, profile = prepare_corpus(admin, other, monkeypatch)
    replacement = build_serving_snapshot(corpus, profile)
    review_snapshot(replacement["id"], admin, "approve", "Fixture second release")

    class SwitchDuringGeneration(ChatProvider):
        def generate(self, *args):
            activate(replacement["id"], old.serving_id, admin)
            return super().generate(*args)

    monkeypatch.setattr(openai_generation, "get_generation_provider", SwitchDuringGeneration)
    response = client.post(
        f"/api/v1/conversations/{conv}/messages",
        headers=dict(headers, **{"Idempotency-Key": "switch"}),
        json={"question": "hợp đồng", "mode": "keyword", "topic": "contract"},
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["serving_snapshot_id"] == old.serving_id
    assert pin_active().serving_id == replacement["id"]
    for citation in result["citations"]:
        opened = client.get(
            f"/api/v1/messages/{result['message_id']}/citations/{citation['id']}", headers=headers
        ).json()
        assert opened["quote"] == citation["quote"]
        assert opened["serving_snapshot_id"] == old.serving_id


def test_empty_clarification_reason_still_prevents_generation(
    client, admin, corpus_path, monkeypatch
):
    from app.providers import openai_generation

    _, headers, conv = chat_setup(client, admin, corpus_path, monkeypatch)
    endpoint = f"/api/v1/conversations/{conv}/messages"
    payload = {"question": "hợp đồng", "mode": "keyword"}
    assert (
        client.post(
            endpoint, headers=dict(headers, **{"Idempotency-Key": "first"}), json=payload
        ).status_code
        == 200
    )

    class Ambiguous(ChatProvider):
        def rewrite(self, question, history, deadline):
            return RewriteResult(standalone_question=question, needs_clarification=True, reason="")

        def generate(self, *args):
            raise AssertionError("Ambiguity must not call generation")

    monkeypatch.setattr(openai_generation, "get_generation_provider", Ambiguous)
    response = client.post(
        endpoint, headers=dict(headers, **{"Idempotency-Key": "second"}), json=payload
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "needs_clarification"
    assert response.json()["answer"].strip()


def test_malformed_conversation_cursor_is_validation_error(client, admin):
    from app.auth.tokens import issue_token
    from app.chat.repository import encode_cursor

    response = client.get(
        "/api/v1/conversations",
        params={"cursor": encode_cursor(["2026-02-12T00:00:00+00:00", 123])},
        headers={"Authorization": "Bearer " + issue_token(admin)},
    )
    assert response.status_code == 422
