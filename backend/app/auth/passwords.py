from uuid import UUID

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from sqlalchemy import select

from app.core.errors import DomainError
from app.db.models import users
from app.db.session import engine

hasher = PasswordHasher()
_dummy_hash = hasher.hash("timing-equalization-placeholder")


def create_user(username: str, password: str, role: str = "admin") -> UUID:
    if (
        not 1 <= len(username) <= 120
        or not 12 <= len(password) <= 256
        or role not in ("admin", "user")
    ):
        raise DomainError("INVALID_USER", 422)
    with engine().begin() as conn:
        return conn.execute(
            users.insert()
            .values(username=username, password_hash=hasher.hash(password), role=role)
            .returning(users.c.id)
        ).scalar_one()


def authenticate(username: str, password: str):
    with engine().connect() as conn:
        row = conn.execute(select(users).where(users.c.username == username)).mappings().first()
    try:
        hasher.verify(row["password_hash"] if row else _dummy_hash, password)
    except (VerificationError, InvalidHashError):
        raise DomainError("INVALID_CREDENTIALS", 401)
    if not row or row["disabled"]:
        raise DomainError("INVALID_CREDENTIALS", 401)
    return row
