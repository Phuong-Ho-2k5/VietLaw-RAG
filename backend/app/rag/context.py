import json

from app.chat.schemas import ContextBundle
from app.core.config import Settings
from app.core.errors import DomainError
from app.domain.serving_reader import read_chunks


def context_text(bundle):
    return json.dumps(bundle.chunks, ensure_ascii=False, separators=(",", ":"))


def build_context(context, candidates, as_of_date, question, provider) -> ContextBundle:
    settings = Settings()
    approved = read_chunks(context, as_of_date)
    by_id = {c["chunk_id"]: c for c in approved}
    groups, ordered = {}, []
    for c in approved:
        groups.setdefault((c["version_hash"], c["article_label"]), []).append(c)
    for candidate in candidates[:5]:
        if (
            candidate.serving_snapshot_id != context.serving_id
            or candidate.corpus_snapshot_id != context.corpus_id
            or candidate.embedding_profile_id != context.profile_id
            or candidate.chunk_id not in by_id
        ):
            raise DomainError("INVALID_CONTEXT_SOURCE", 502)
        c = by_id[candidate.chunk_id]
        key = (c["version_hash"], c["article_label"])
        if key not in ordered:
            ordered.append(key)
    bundle = ContextBundle()
    for key in ordered:
        group = sorted(groups[key], key=lambda c: (c["start"], c["chunk_id"]))
        proposed = ContextBundle(chunks=bundle.chunks + group)
        size = provider.count_tokens(context_text(proposed))
        if size > settings.evidence_token_budget:
            bundle.excluded_groups.append(":".join(key))
            continue
        bundle.chunks = proposed.chunks
        bundle.token_count = size
    return bundle
