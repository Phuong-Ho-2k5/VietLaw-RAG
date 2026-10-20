from datetime import datetime, timedelta, timezone

import jwt
import pytest
from sqlalchemy import select


def test_login_and_disabled_user(client, admin):
    from app.db.models import users
    from app.db.session import engine

    response = client.post(
        "/api/v1/auth/token",
        json={"username": "reviewer", "password": "a-long-local-test-password"},
    )
    assert response.status_code == 200
    token = response.json()["access_token"]
    assert "password" not in response.text
    with engine().begin() as conn:
        saved = conn.execute(select(users).where(users.c.id == admin)).mappings().one()
        assert saved["password_hash"].startswith("$argon2id$")
        conn.execute(users.update().where(users.c.id == admin).values(disabled=True))
    assert (
        client.get(
            "/api/v1/admin/jobs/00000000-0000-0000-0000-000000000000",
            headers={"Authorization": "Bearer " + token},
        ).status_code
        == 401
    )
    assert (
        client.post(
            "/api/v1/auth/token",
            json={"username": "reviewer", "password": "a-long-local-test-password"},
        ).status_code
        == 401
    )


@pytest.mark.parametrize("case", ["missing", "signature", "expired", "issuer", "audience", "user"])
def test_admin_permission_checks(client, admin, case):
    from app.auth.passwords import create_user
    from app.core.config import Settings

    settings = Settings()
    sub = (
        str(create_user("normal", "another-long-test-password", "user"))
        if case == "user"
        else str(admin)
    )
    now = datetime.now(timezone.utc)
    claims = {
        "sub": sub,
        "iat": now,
        "exp": now + timedelta(minutes=-1 if case == "expired" else 30),
        "iss": "wrong" if case == "issuer" else settings.jwt_issuer,
        "aud": "wrong" if case == "audience" else settings.jwt_audience,
    }
    token = jwt.encode(
        claims,
        "incorrect-signature-key-" * 2 if case == "signature" else settings.jwt_secret,
        algorithm="HS256",
    )
    headers = {} if case == "missing" else {"Authorization": "Bearer " + token}
    assert client.get(
        "/api/v1/admin/jobs/00000000-0000-0000-0000-000000000000", headers=headers
    ).status_code == (403 if case == "user" else 401)


def test_bad_credentials_and_safe_validation(client, admin):
    for name in ("reviewer", "unknown"):
        response = client.post("/api/v1/auth/token", json={"username": name, "password": "wrong"})
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "INVALID_CREDENTIALS"
    response = client.post(
        "/api/v1/auth/token", json={"username": "reviewer", "password": {"secret": "do-not-echo"}}
    )
    assert response.status_code == 422
    assert "do-not-echo" not in response.text
