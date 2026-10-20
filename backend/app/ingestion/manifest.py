"""Validate M1's content-addressed release without relabelling its legal review."""

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit

from app.core.config import Settings
from app.core.errors import DomainError
from app.core.hashing import canonical_hash, text_hash
from app.ingestion.m1_structure import normalize_text, parse_legal_units, raw_span


@dataclass(frozen=True)
class ValidatedRelease:
    corpus_id: str
    payload: dict


def require(condition, code="INVALID_RELEASE"):
    if not condition:
        raise DomainError(code, 422)


def secure_url(value):
    parsed = urlsplit(value)
    require(parsed.scheme == "https" and bool(parsed.hostname) and not parsed.username)


def digest(value):
    require(isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value))


def check_structure(document):
    canonical, mapping = normalize_text(document["raw_passage"])
    require(canonical == document["canonical_text"] and mapping == document["offset_map"])
    parsed, _ = parse_legal_units(canonical)
    version = document["version_hash"]
    expected = {text_hash(version + ":" + u["unit_id"]): u for u in parsed}
    local_ids = {}
    for supplied in document["legal_units"]:
        original = expected[supplied["unit_id"]]
        local_ids[supplied["unit_id"]] = original["unit_id"]
        for field in (
            "kind",
            "article_label",
            "clause_label",
            "point_label",
            "heading_path",
            "start",
            "end",
            "text",
            "context_header",
            "parse_confidence",
        ):
            require(supplied[field] == original[field], "STRUCTURE_MISMATCH")
        expected_parent = (
            text_hash(version + ":" + original["parent_id"]) if original["parent_id"] else None
        )
        require(supplied["parent_id"] == expected_parent, "STRUCTURE_MISMATCH")
        require(
            (supplied["raw_start"], supplied["raw_end"])
            == raw_span(mapping, original["start"], original["end"]),
            "RAW_SPAN_MISMATCH",
        )
    return local_ids


def validate_payload(d: dict) -> ValidatedRelease:
    try:
        require(d["schema_version"] == 2 and d["active"] is True)
        digest(d["manifest_hash"])
        require(
            canonical_hash({k: v for k, v in d.items() if k != "manifest_hash"})
            == d["manifest_hash"],
            "MANIFEST_HASH_MISMATCH",
        )
        require(0 < len(d["chunks"]) <= Settings().max_chunks, "CHUNK_LIMIT")
        scope = d["temporal_scope"]
        require(scope["policy"] == "only_explicit_verified_dates" and bool(scope["as_of_dates"]))
        for day in scope["as_of_dates"]:
            date.fromisoformat(day)
        digest(d["zip_sha256"])
        documents, units, local_ids = {}, {}, {}
        for document in d["documents"]:
            version = document["version_hash"]
            require(version not in documents)
            documents[version] = document
            review = document["review"]
            local_ids.update(check_structure(document))
            require(document["status"] == "approved" and review["decision"] == "approve")
            require(review["text_match"] is True and review["structure_reviewed"] is True)
            require(review["effective_conclusion"] == "effective_for_as_of_date")
            require(bool(review["reviewer"].strip()) and bool(review["evidence_note"].strip()))
            date.fromisoformat(review["reviewed_at"])
            require(
                document["as_of_date"] == review["as_of_date"]
                and document["as_of_date"] in scope["as_of_dates"]
            )
            require(
                date.fromisoformat(review["effective_from"])
                <= date.fromisoformat(document["as_of_date"])
            )
            if review["effective_to"]:
                require(
                    date.fromisoformat(document["as_of_date"])
                    <= date.fromisoformat(review["effective_to"])
                )
            secure_url(review["official_source_url"])
            source = document["source_evidence"]
            for field, review_field in (
                ("url", "official_source_url"),
                ("checked_at", "source_checked_at"),
                ("downloaded_sha256", "official_source_sha256"),
                ("note", "evidence_note"),
                ("amendment_note", "amendment_note"),
            ):
                require(source[field] == review[review_field], "SOURCE_EVIDENCE_MISMATCH")
            require(source["text_match"] is True)
            require(
                text_hash(document["canonical_text"])
                == document["canonical_sha256"]
                == review["canonical_sha256"]
            )
            require(text_hash(document["raw_passage"]) == document["raw_passage_sha256"])
            require(document["raw_sha256"] == review["raw_sha256"])
            digest(document["raw_sha256"])
            version_key = {
                k: review.get(k)
                for k in (
                    "document_number",
                    "issuing_body",
                    "issued_on",
                    "effective_from",
                    "effective_to",
                )
            }
            version_key["canonical_sha256"] = document["canonical_sha256"]
            require(
                hashlib.sha256(
                    json.dumps(version_key, sort_keys=True, ensure_ascii=False).encode()
                ).hexdigest()
                == version
            )
            approved = {
                text_hash(version + ":" + local_id) for local_id in review["approved_unit_ids"]
            }
            for unit in document["legal_units"]:
                identifier = unit["unit_id"]
                require(identifier not in units)
                digest(identifier)
                require(type(unit["start"]) is int and type(unit["end"]) is int)
                require(0 <= unit["start"] < unit["end"] <= len(document["canonical_text"]))
                require(document["canonical_text"][unit["start"] : unit["end"]] == unit["text"])
                require(0 <= unit["raw_start"] < unit["raw_end"] <= len(document["raw_passage"]))
                require(unit["review_status"] in ("approved", "context_only"))
                if unit["review_status"] == "approved":
                    require(identifier in approved)
                units[identifier] = (version, unit)
            for unit in document["legal_units"]:
                if unit["parent_id"]:
                    require(unit["parent_id"] in units and units[unit["parent_id"]][0] == version)
        seen = set()
        for chunk in d["chunks"]:
            identifier = chunk["chunk_id"]
            require(identifier not in seen)
            seen.add(identifier)
            require(chunk["review_status"] == "approved")
            document = documents[chunk["version_hash"]]
            review = document["review"]
            require(chunk["as_of_date"] == document["as_of_date"])
            require(chunk["content_hash"] == text_hash(chunk["text"]))
            require(
                chunk["chunk_id"]
                == text_hash(f"{chunk['version_hash']}:{chunk['start']}:{chunk['end']}")
            )
            require(
                chunk["document_number"] == review["document_number"]
                and chunk["raw_id"] == document["raw_id"]
            )
            for field in (
                "reviewer",
                "reviewed_at",
                "effective_from",
                "effective_to",
                "official_source_url",
            ):
                require(chunk[field] == review[field])
            require(
                bool(chunk["topic_tags"]) and set(chunk["topic_tags"]) <= set(d["supported_topics"])
            )
            require(bool(chunk["unit_ids"]))
            # M1 v2 releases one complete approved legal unit per chunk.
            require(len(chunk["unit_ids"]) == 1)
            version, unit = units[chunk["unit_ids"][0]]
            require(version == chunk["version_hash"] and unit["review_status"] == "approved")
            for field in (
                "start",
                "end",
                "raw_start",
                "raw_end",
                "text",
                "context_header",
                "article_label",
                "clause_label",
                "point_label",
            ):
                require(chunk[field] == unit[field])
            evidence = chunk["source_evidence"]
            local_id = local_ids[unit["unit_id"]]
            reviewed_evidence = review.get("unit_source_evidence", {}).get(
                local_id, document["source_evidence"]
            )
            require(evidence == reviewed_evidence, "SOURCE_EVIDENCE_MISMATCH")
            require(
                chunk["topic_tags"] == review["unit_topic_tags"][local_id], "REVIEW_TOPIC_MISMATCH"
            )
            require(
                evidence["text_match"] is True
                and bool(evidence["note"])
                and bool(evidence["reviewer"])
            )
            require(evidence["as_of_date"] == chunk["as_of_date"])
            date.fromisoformat(evidence["checked_at"])
            secure_url(evidence["url"])
            secure_url(evidence["metadata_url"])
            digest(evidence["downloaded_sha256"])
            require(type(evidence["pdf_page"]) is int and evidence["pdf_page"] > 0)
        return ValidatedRelease(d["manifest_hash"], d)
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError):
        raise DomainError("INVALID_RELEASE", 422) from None


def load_release(path: Path) -> ValidatedRelease:
    limit = Settings().max_release_bytes
    with Path(path).open("rb") as stream:
        raw = stream.read(limit + 1)
    require(len(raw) <= limit, "RELEASE_SIZE_LIMIT")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeError, ValueError):
        raise DomainError("INVALID_RELEASE", 422) from None
    return validate_payload(payload)
