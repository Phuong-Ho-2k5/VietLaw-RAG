"""Real backend -> OpenAI SDK -> local Postman simulation HTTP, opt in via marker."""

import os

import pytest
from test_retrieval import activate_fixture


@pytest.mark.simulation
@pytest.mark.parametrize("marker,status,code", [
    ("", 200, None), ("__429__", 503, "PROVIDER_UNAVAILABLE"),
    ("__500__", 503, "PROVIDER_UNAVAILABLE"), ("__401__", 503, "PROVIDER_UNAVAILABLE"),
    ("__timeout__", 504, "PROVIDER_TIMEOUT"), ("__refusal__", 502, "PROVIDER_REFUSAL"),
    ("__incomplete__", 502, "PROVIDER_INCOMPLETE"),
    ("__invalid_json__", 502, "PROVIDER_INVALID_OUTPUT"),
    ("__fake_source__", 502, "INVALID_CITATION"),
    ("__abstain__", 200, "insufficient_evidence"),
    ("__out_of_scope__", 200, "out_of_scope"),
])
def test_backend_with_postman_upstream(client, admin, corpus_path, monkeypatch, marker, status, code):
    from app.auth.tokens import issue_token
    from app.providers import local_e5
    from app.providers.embedding import default_profile

    url = os.environ.get("M4_SIMULATION_URL")
    if not url:
        pytest.skip("Set M4_SIMULATION_URL to the running Postman simulation")
    activate_fixture(admin, corpus_path, monkeypatch)
    class Encoder:
        profile = default_profile()
        def embed_queries(self, texts):
            return [[1.0] + [0.0] * 383]
    monkeypatch.setattr(local_e5, "get_provider", Encoder)
    monkeypatch.setenv("OPENAI_API_KEY", "local-simulation-only")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-4.1-mini")
    monkeypatch.setenv("OPENAI_BASE_URL", url)
    if marker == "__timeout__":
        monkeypatch.setenv("PROVIDER_TIMEOUT", "0.1")
    headers = {"Authorization": "Bearer " + issue_token(admin)}
    conv = client.post("/api/v1/conversations", headers=headers).json()["id"]
    headers["Idempotency-Key"] = "one"
    response = client.post(f"/api/v1/conversations/{conv}/messages", headers=headers,
                           json={"question": "hợp đồng " + marker, "mode": "vector"})
    assert response.status_code == status, response.text
    if status != 200:
        assert response.json()["error"]["code"] == code
        history = client.get(f"/api/v1/conversations/{conv}/messages", headers=headers).json()
        assert history["items"][1]["state"] == "failed"
        assert history["items"][1]["result"] is None
    else:
        data = response.json()
        assert data["status"] == (code or "answered")
        assert bool(data["citations"]) == (data["status"] == "answered")
