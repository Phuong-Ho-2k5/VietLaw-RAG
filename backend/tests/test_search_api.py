from test_retrieval import activate_fixture


def test_search_pinned_contract_and_invalid_input(client, admin, corpus_path, monkeypatch):
    from app.auth.tokens import issue_token
    ctx = activate_fixture(admin, corpus_path, monkeypatch)
    headers = {"Authorization": "Bearer " + issue_token(admin)}
    payload = {"query": "hợp đồng", "mode": "keyword", "as_of_date": "2026-02-12"}
    response = client.post("/api/v1/search", headers=headers, json=payload)
    assert response.status_code == 200
    assert response.json()[0]["serving_snapshot_id"] == ctx.serving_id
    for field, value in [("top_k", 11), ("mode", "invalid"), ("topic", "wage"),
                         ("as_of_date", "2026-10-25"), ("query", "  ")]:
        assert client.post("/api/v1/search", headers=headers,
                           json=dict(payload, **{field: value})).status_code == 422
