from datetime import date

from app.chat.schemas import CandidateDTO, Mode
from app.core.errors import DomainError
from app.core.hashing import canonical_hash
from app.db.search import keyword_candidates, vector_candidates
from app.domain.serving_reader import ServingContext


def fuse_rrf(keyword, vector, k=60) -> list[CandidateDTO]:
    merged = {}
    for branch, rows in (("keyword", keyword), ("vector", vector)):
        for raw in rows:
            item = raw.model_dump() if isinstance(raw, CandidateDTO) else dict(raw)
            identifier = item["chunk_id"]
            if identifier not in merged:
                merged[identifier] = dict(item, score=0.0, branches={})
            entry = merged[identifier]
            if branch not in entry["branches"]:
                entry["score"] += 1 / (k + item["rank"])
                entry["branches"][branch] = {"rank": item["rank"], "score": item["score"]}
    rows = sorted(merged.values(), key=lambda r: (-r["score"], r["chunk_id"]))
    return [CandidateDTO(**dict(r, rank=i)) for i, r in enumerate(rows, 1)]


def retrieve(
    context: ServingContext,
    query: str,
    as_of_date: date,
    mode: Mode,
    top_k: int = 5,
    topic: str | None = None,
) -> list[CandidateDTO]:
    if mode not in ("keyword", "vector", "hybrid") or not 1 <= top_k <= 10:
        raise DomainError("INVALID_SEARCH", 422)
    branches = {}
    if mode in ("keyword", "hybrid"):
        branches["keyword"] = keyword_candidates(context, query, as_of_date, 10, topic)
    if mode in ("vector", "hybrid"):
        from dataclasses import asdict

        from app.providers.local_e5 import get_provider

        provider = get_provider()
        if canonical_hash(asdict(provider.profile)) != context.profile_id:
            raise DomainError("EMBEDDING_PROFILE_MISMATCH", 503)
        vector = provider.embed_queries([query])[0]
        branches["vector"] = vector_candidates(context, vector, as_of_date, 10, topic)
    for rows in branches.values():
        for row in rows:
            row["embedding_profile_id"] = context.profile_id
    if mode == "hybrid":
        return fuse_rrf(branches["keyword"], branches["vector"])[:top_k]
    return [
        CandidateDTO(**dict(r, branches={mode: {"rank": r["rank"], "score": r["score"]}}))
        for r in branches[mode][:top_k]
    ]
