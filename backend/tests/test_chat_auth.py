from fastapi import Depends
from sqlalchemy import update


def test_user_auth_keeps_admin_routes_restricted(client):
    from app.auth.dependencies import require_user
    from app.auth.passwords import create_user
    from app.auth.tokens import issue_token
    from app.db.models import users
    from app.db.session import engine

    @client.app.get("/test-user")
    def who(user=Depends(require_user)):
        return {"id": str(user["id"])}

    user = create_user("normal", "a-secure-long-password", "user")
    headers = {"Authorization": "Bearer " + issue_token(user)}
    assert client.get("/test-user", headers=headers).json() == {"id": str(user)}
    assert client.get("/api/v1/admin/jobs/" + "0" * 32, headers=headers).status_code == 403
    with engine().begin() as conn:
        conn.execute(update(users).where(users.c.id == user).values(disabled=True))
    assert client.get("/test-user", headers=headers).status_code == 401
