from datetime import datetime, timedelta, timezone
from uuid import UUID

import jwt

from app.core.config import Settings
from app.core.errors import DomainError


def issue_token(user_id: UUID) -> str:
    settings = Settings()
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "sub": str(user_id),
            "iat": now,
            "exp": now + timedelta(minutes=30),
            "iss": settings.jwt_issuer,
            "aud": settings.jwt_audience,
        },
        settings.jwt_secret,
        algorithm="HS256",
    )


def read_token(token: str) -> UUID:
    settings = Settings()
    try:
        claims = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=["HS256"],
            audience=settings.jwt_audience,
            issuer=settings.jwt_issuer,
            options={"require": ["sub", "iat", "exp", "iss", "aud"]},
        )
        return UUID(claims["sub"])
    except (jwt.PyJWTError, ValueError, TypeError):
        raise DomainError("INVALID_TOKEN", 401)
