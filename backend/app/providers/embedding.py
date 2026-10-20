from dataclasses import asdict, dataclass
from typing import Protocol

import numpy as np
from sqlalchemy.dialects.postgresql import insert

from app.core.config import MODEL_REVISION
from app.core.errors import DomainError
from app.core.hashing import canonical_hash
from app.db.models import embedding_profiles
from app.db.session import engine


@dataclass(frozen=True)
class EmbeddingProfile:
    provider: str = "local-e5"
    model: str = "intfloat/multilingual-e5-small"
    revision: str = MODEL_REVISION
    dimension: int = 384
    normalization: str = "l2"
    template: str = "e5-header-text-v1"
    max_tokens: int = 512


class EmbeddingProvider(Protocol):
    profile: EmbeddingProfile

    def embed_passages(self, texts: list[str]) -> list[list[float]]: ...
    def embed_queries(self, texts: list[str]) -> list[list[float]]: ...


def default_profile() -> EmbeddingProfile:
    return EmbeddingProfile()


def register_profile(profile: EmbeddingProfile) -> str:
    if profile != default_profile():
        raise DomainError("UNSUPPORTED_PROFILE", 422)
    payload = asdict(profile)
    identifier = canonical_hash(payload)
    with engine().begin() as conn:
        conn.execute(
            insert(embedding_profiles)
            .values(id=identifier, payload=payload)
            .on_conflict_do_nothing()
        )
    return identifier


def checked_vector(vector, dimension=384) -> list[float]:
    values = np.asarray(vector, dtype=np.float32)
    if values.shape != (dimension,) or not np.all(np.isfinite(values)):
        raise DomainError("INVALID_EMBEDDING", 422)
    norm = float(np.linalg.norm(values))
    if norm == 0 or abs(norm - 1) > 0.001:
        raise DomainError("INVALID_EMBEDDING", 422)
    return values.tolist()
