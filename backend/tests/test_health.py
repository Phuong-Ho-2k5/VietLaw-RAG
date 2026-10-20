import pytest
from fastapi.testclient import TestClient


def test_live_and_unavailable_database(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "test-secret-only-" * 3)
    monkeypatch.setenv(
        "DATABASE_URL", "postgresql+psycopg://none:none@127.0.0.1:1/none?connect_timeout=1"
    )
    from app.main import create_app

    with TestClient(create_app()) as client:
        assert client.get("/health/live").status_code == 200
        response = client.get("/health/ready")
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "NOT_READY"
        assert response.json()["request_id"]


def test_missing_secret_is_configuration_error(monkeypatch):
    monkeypatch.delenv("JWT_SECRET", raising=False)
    from pydantic import ValidationError

    from app.core.config import Settings

    with pytest.raises(ValidationError):
        Settings(_env_file=None)
