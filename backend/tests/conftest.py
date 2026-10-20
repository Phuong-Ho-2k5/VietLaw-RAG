import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def test_configuration(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "isolated-test-signing-key-" * 2)


@pytest.fixture
def db(monkeypatch):
    config_file = ROOT / "backend/.runtime/verification.json"
    if not config_file.exists():
        pytest.fail("Run backend/scripts/verification_db.py first; PostgreSQL tests are required")
    config = json.loads(config_file.read_text(encoding="utf-8"))
    for key, value in config.items():
        monkeypatch.setenv(key, value)
    from app.db.models import metadata

    owner = create_engine(config["MIGRATION_DATABASE_URL"])
    with owner.begin() as conn:
        names = ",".join(f'"{table.name}"' for table in metadata.sorted_tables)
        conn.execute(text("TRUNCATE " + names + " CASCADE"))
        conn.execute(text("INSERT INTO active_corpus (singleton) VALUES (true)"))
    yield {"database": "isolated verification PostgreSQL"}
    owner.dispose()


@pytest.fixture
def client(db):
    from fastapi.testclient import TestClient

    from app.main import create_app

    with TestClient(create_app(), raise_server_exceptions=False) as client:
        yield client


@pytest.fixture
def admin(db):
    from app.auth.passwords import create_user

    return create_user("reviewer", "a-long-local-test-password", "admin")


@pytest.fixture
def corpus_path():
    return ROOT / "data/manifests/m1/labor-corpus-v1.json"
