import json
from concurrent.futures import ThreadPoolExecutor
from datetime import date

import pytest
from helpers import prepare_corpus
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError


def test_approval_required_and_sealed_rows_are_immutable(db, admin, corpus_path, monkeypatch):
    from app.core.errors import DomainError
    from app.db.session import engine
    from app.domain.snapshots import activate, build_serving_snapshot, review_snapshot

    corpus, profile = prepare_corpus(admin, corpus_path, monkeypatch)
    snapshot = build_serving_snapshot(corpus, profile)
    with pytest.raises(DomainError):
        activate(snapshot["id"], None, admin)
    review_snapshot(snapshot["id"], admin, "approve", "Operational review of existing M1 evidence")
    assert activate(snapshot["id"], None, admin)["state"] == "sealed"
    assert activate(snapshot["id"], snapshot["id"], admin)["state"] == "sealed"
    for statement in (
        "UPDATE retrieval_chunks SET text='tampered'",
        "DELETE FROM retrieval_chunks",
        "UPDATE document_versions SET canonical_text='tampered'",
        "UPDATE legal_units SET payload='{}'",
        "UPDATE chunk_embeddings SET vector_hash='tampered'",
        "DELETE FROM snapshot_chunks",
        "UPDATE serving_snapshots SET state='ready'",
        "DELETE FROM serving_snapshot_chunks",
        "UPDATE corpus_snapshots SET complete=false",
        "DELETE FROM review_events",
    ):
        with pytest.raises(DBAPIError), engine().begin() as conn:
            conn.execute(text(statement))


def test_racing_activation_old_reader_and_rollback(db, admin, corpus_path, tmp_path, monkeypatch):
    from app.core.errors import DomainError
    from app.core.hashing import canonical_hash
    from app.domain.serving_reader import pin_active, read_chunks
    from app.domain.snapshots import activate, build_serving_snapshot, review_snapshot

    corpus_a, profile = prepare_corpus(admin, corpus_path, monkeypatch)
    a = build_serving_snapshot(corpus_a, profile)
    review_snapshot(a["id"], admin, "approve", "First release")
    payload = json.loads(corpus_path.read_text(encoding="utf-8"))
    payload["chunks"] = payload["chunks"][:-1]
    payload["manifest_hash"] = canonical_hash(
        {k: v for k, v in payload.items() if k != "manifest_hash"}
    )
    other = tmp_path / "other.json"
    other.write_text(json.dumps(payload), encoding="utf-8")
    corpus_b, profile = prepare_corpus(admin, other, monkeypatch)
    b = build_serving_snapshot(corpus_b, profile)
    review_snapshot(b["id"], admin, "approve", "Second release")

    def race(identifier):
        try:
            activate(identifier, None, admin)
            return identifier
        except DomainError as exc:
            return exc.code

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(race, [a["id"], b["id"]]))
    assert results.count("ACTIVE_CONFLICT") == 1
    old = pin_active()
    replacement = a if old.serving_id == b["id"] else b
    activate(replacement["id"], old.serving_id, admin)
    assert pin_active().serving_id == replacement["id"]
    assert len(read_chunks(old, date(2026, 2, 12))) == (10 if old.serving_id == a["id"] else 9)
    with pytest.raises(DomainError):
        activate(old.serving_id, old.serving_id, admin)
    assert pin_active().serving_id == replacement["id"]


def test_missing_embedding_and_rejected_snapshot_cannot_activate(
    db, admin, corpus_path, monkeypatch
):
    from app.core.errors import DomainError
    from app.domain.snapshots import activate, build_serving_snapshot, review_snapshot
    from app.ingestion.jobs import enqueue_import
    from app.ingestion.releases import register_release
    from app.ingestion.worker import run_once
    from app.providers.embedding import default_profile, register_profile

    corpus = register_release(corpus_path)
    enqueue_import(corpus, admin)
    run_once("import")
    profile = register_profile(default_profile())
    with pytest.raises(DomainError):
        build_serving_snapshot(corpus, profile)
    prepare_corpus(admin, corpus_path, monkeypatch)
    snapshot = build_serving_snapshot(corpus, profile)
    review_snapshot(snapshot["id"], admin, "reject", "Review rejected")
    with pytest.raises(DomainError):
        activate(snapshot["id"], None, admin)


def test_failure_after_pointer_write_rolls_back_pointer_and_seal(
    db, admin, corpus_path, monkeypatch
):
    from sqlalchemy import event

    from app.core.errors import DomainError
    from app.db.session import engine
    from app.domain.serving_reader import pin_active
    from app.domain.snapshots import activate, build_serving_snapshot, get_snapshot, review_snapshot

    corpus, profile = prepare_corpus(admin, corpus_path, monkeypatch)
    snapshot = build_serving_snapshot(corpus, profile)
    review_snapshot(snapshot["id"], admin, "approve", "Rollback verification")
    reached = False

    def fail_after_updates(conn, cursor, statement, parameters, context, executemany):
        nonlocal reached
        if (
            statement.startswith("INSERT INTO review_events")
            and parameters.get("decision") == "activate"
        ):
            reached = True
            raise RuntimeError("Injected failure after pointer and seal updates")

    event.listen(engine(), "before_cursor_execute", fail_after_updates)
    try:
        with pytest.raises(RuntimeError, match="Injected failure"):
            activate(snapshot["id"], None, admin)
    finally:
        event.remove(engine(), "before_cursor_execute", fail_after_updates)
    assert reached
    assert get_snapshot(snapshot["id"])["state"] == "approved"
    with pytest.raises(DomainError, match="NO_ACTIVE_CORPUS"):
        pin_active()
