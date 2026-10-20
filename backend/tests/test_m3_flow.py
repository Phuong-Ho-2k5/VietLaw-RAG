from helpers import prepare_corpus


def test_http_admin_workflow_and_conflicts(client, admin, corpus_path, monkeypatch):
    from app.auth.tokens import issue_token

    corpus, profile = prepare_corpus(admin, corpus_path, monkeypatch)
    headers = {"Authorization": "Bearer " + issue_token(admin)}
    body = {"release_id": corpus}
    first = client.post("/api/v1/admin/imports", json=body, headers=headers)
    assert first.status_code == 202
    assert (
        client.post("/api/v1/admin/imports", json=body, headers=headers).json()["id"]
        == first.json()["id"]
    )
    job = client.get(first.headers["Location"], headers=headers)
    assert job.json()["state"] == "succeeded"
    assert client.post(first.headers["Location"] + "/retry", headers=headers).status_code == 409
    embedded = client.post(
        "/api/v1/admin/embedding-jobs",
        json={"corpus_snapshot_id": corpus, "embedding_profile_id": profile},
        headers=headers,
    )
    assert embedded.status_code == 202
    created = client.post(
        "/api/v1/admin/serving-snapshots",
        json={"corpus_snapshot_id": corpus, "embedding_profile_id": profile},
        headers=headers,
    )
    assert created.status_code == 201
    url = "/api/v1/admin/serving-snapshots/" + created.json()["id"]
    assert (
        client.post(
            url + "/activate", json={"expected_active_id": None}, headers=headers
        ).status_code
        == 409
    )
    assert (
        client.post(
            url + "/review",
            json={"decision": "approve", "note": "HTTP acceptance review"},
            headers=headers,
        ).status_code
        == 200
    )
    assert (
        client.post(
            url + "/activate", json={"expected_active_id": None}, headers=headers
        ).status_code
        == 200
    )
    conflict = client.post(url + "/activate", json={"expected_active_id": None}, headers=headers)
    assert conflict.status_code == 409 and conflict.json()["error"]["code"] == "ACTIVE_CONFLICT"
    assert client.get(url, headers=headers).json()["chunk_count"] == 10


def test_contract_has_security_and_safe_error_shape(client):
    contract = client.get("/openapi.json").json()
    for path, methods in contract["paths"].items():
        if path.startswith("/api/v1/admin"):
            assert all(op.get("security") for op in methods.values())
    missing = client.get("/does-not-exist")
    assert missing.status_code == 404
    assert set(missing.json()) == {"error", "request_id"}


def test_contract_defines_polling_and_snapshot_outputs(client):
    contract = client.get("/openapi.json").json()
    schemas = contract["components"]["schemas"]
    assert {"id", "kind", "state", "attempt", "error", "errors", "counts", "item_errors"} <= set(
        schemas["JobDTO"]["properties"]
    )
    assert {"id", "corpus_snapshot_id", "embedding_profile_id", "state", "chunk_count"} <= set(
        schemas["SnapshotDTO"]["properties"]
    )
    error = contract["paths"]["/api/v1/admin/imports"]["post"]["responses"]["422"]
    assert "ErrorResponse" in str(error)
