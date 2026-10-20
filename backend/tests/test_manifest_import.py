import copy
import json
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import func, select


def rewrite(path, tmp_path, mutate):
    from app.core.hashing import canonical_hash

    payload = json.loads(path.read_text(encoding="utf-8"))
    mutate(payload)
    payload["manifest_hash"] = canonical_hash(
        {k: v for k, v in payload.items() if k != "manifest_hash"}
    )
    output = tmp_path / "release.json"
    output.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return output


def test_import_preserves_provenance_and_is_idempotent(db, admin, corpus_path):
    from app.db.models import document_versions, retrieval_chunks, review_events
    from app.db.session import engine
    from app.ingestion.jobs import enqueue_import, get_job
    from app.ingestion.releases import register_release
    from app.ingestion.worker import run_once

    release = register_release(corpus_path)
    with ThreadPoolExecutor(2) as pool:
        ids = list(pool.map(lambda _: enqueue_import(release, admin)["id"], range(2)))
    assert ids[0] == ids[1]
    with ThreadPoolExecutor(2) as pool:
        list(pool.map(lambda i: run_once(str(i)), range(2)))
    assert get_job(ids[0])["state"] == "succeeded"
    assert enqueue_import(release, admin)["id"] == ids[0]
    with engine().connect() as conn:
        assert conn.scalar(select(func.count()).select_from(document_versions)) == 1
        rows = conn.execute(select(retrieval_chunks)).mappings().all()
        assert len(rows) == 10
        assert {r["id"] for r in rows} == {
            c["chunk_id"] for c in json.loads(corpus_path.read_text(encoding="utf-8"))["chunks"]
        }
        assert all(r["payload"]["reviewer"].startswith("Codex") for r in rows)
        assert (
            next(r for r in rows if r["payload"]["article_label"] == "26")["payload"][
                "clause_label"
            ]
            is None
        )
        assert conn.scalar(select(func.count()).select_from(review_events)) >= 1


@pytest.mark.parametrize(
    "case",
    [
        "hash",
        "span",
        "chunk_hash",
        "duplicate",
        "orphan",
        "evidence",
        "pending",
        "temporal",
        "canonical",
        "label",
        "unit",
    ],
)
def test_malformed_release_rejected_even_with_recomputed_manifest(db, corpus_path, tmp_path, case):
    from app.core.errors import DomainError
    from app.ingestion.manifest import load_release

    def mutate(d):
        c = d["chunks"][0]
        if case == "span":
            c["start"] = -1
        if case == "chunk_hash":
            c["content_hash"] = "0" * 64
        if case == "duplicate":
            d["chunks"].append(copy.deepcopy(c))
        if case == "orphan":
            c["unit_ids"] = ["f" * 64]
        if case == "evidence":
            c["source_evidence"] = {}
        if case == "pending":
            c["review_status"] = "pending"
        if case == "temporal":
            c["as_of_date"] = "2026-10-20"
        if case == "canonical":
            d["documents"][0]["canonical_text"] += "tampered"
        if case == "label":
            c["clause_label"] = "invented"
        if case == "unit":
            d["documents"][0]["legal_units"][0]["text"] = "tampered"

    path = rewrite(corpus_path, tmp_path, mutate)
    if case == "hash":
        d = json.loads(path.read_text(encoding="utf-8"))
        d["manifest_hash"] = "f" * 64
        path.write_text(json.dumps(d), encoding="utf-8")
    with pytest.raises(DomainError):
        load_release(path)


def test_limits_and_crlf(db, corpus_path, tmp_path, monkeypatch):
    from app.core.errors import DomainError
    from app.ingestion.manifest import load_release

    copy_path = tmp_path / "windows.json"
    copy_path.write_bytes(corpus_path.read_bytes().replace(b"\n", b"\r\n"))
    assert (
        load_release(copy_path).corpus_id
        == "6ebc3836a333f2239e524d6016c0bdf7c11abe6751c4a1b9cd01185e74fb84b7"
    )
    monkeypatch.setenv("MAX_CHUNKS", "9")
    with pytest.raises(DomainError):
        load_release(copy_path)
    monkeypatch.setenv("MAX_RELEASE_BYTES", "10")
    with pytest.raises(DomainError):
        load_release(copy_path)


def test_http_does_not_accept_file_paths(client, admin):
    from app.auth.tokens import issue_token

    response = client.post(
        "/api/v1/admin/imports",
        json={"path": "../../secret"},
        headers={"Authorization": "Bearer " + issue_token(admin)},
    )
    assert response.status_code == 422


@pytest.mark.parametrize("case", ["raw_span", "joint_label", "unit_evidence", "official_url"])
def test_reviewed_metadata_cannot_be_changed_by_rehashing(corpus_path, tmp_path, case):
    from app.core.errors import DomainError
    from app.ingestion.manifest import load_release

    def mutate(payload):
        chunk = next(c for c in payload["chunks"] if c["article_label"] == "26")
        document = payload["documents"][0]
        unit = next(u for u in document["legal_units"] if u["unit_id"] == chunk["unit_ids"][0])
        if case == "raw_span":
            for value in (unit, chunk):
                value.update(raw_start=0, raw_end=1)
        elif case == "joint_label":
            for value in (unit, chunk):
                value.update(clause_label="999", context_header="Invented heading")
        elif case == "unit_evidence":
            chunk["source_evidence"].update(downloaded_sha256="0" * 64, pdf_page=999)
        else:
            document["review"]["official_source_url"] = "https://example.com/unreviewed"
            for c in payload["chunks"]:
                c["official_source_url"] = "https://example.com/unreviewed"

    with pytest.raises(DomainError):
        load_release(rewrite(corpus_path, tmp_path, mutate))
