from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select

from app.auth.tokens import read_token
from app.core.errors import DomainError
from app.db.models import users
from app.db.session import engine

bearer = HTTPBearer(auto_error=False)


def require_admin(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
    if not credentials or credentials.scheme.lower() != "bearer":
        raise DomainError("INVALID_TOKEN", 401)
    identifier = read_token(credentials.credentials)
    with engine().connect() as conn:
        user = conn.execute(select(users).where(users.c.id == identifier)).mappings().first()
    if not user or user["disabled"]:
        raise DomainError("INVALID_TOKEN", 401)
    if user["role"] != "admin":
        raise DomainError("ADMIN_REQUIRED", 403)
    return user
