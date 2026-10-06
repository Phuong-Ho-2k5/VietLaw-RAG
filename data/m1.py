"""M1 review pipeline. A raw hit is never treated as verified legal authority."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import zipfile
from collections import Counter
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit

from data.inventory import RECORD_PATH, _sha256_file
from data.legal_text import normalize_text, parse_legal_units, raw_span, retrieval_units


TOPICS = {
    "contract": ("hop-dong-lao-dong", "hợp đồng lao động"),
    "probation": ("thu-viec", "thử việc"),
    "wages": ("tien-luong", "tiền lương", "trả lương"),
    "hours_rest": ("thoi-gio-lam-viec", "thời giờ làm việc", "nghỉ ngơi", "nghi-phep"),
    "termination": ("cham-dut-hop-dong", "chấm dứt hợp đồng", "sa thải"),
}
PIPELINE_VERSION = "m1-v2"
MAX_RECORD_BYTES = 16_000_000
REVIEW_FIELDS = (
    "reviewer", "reviewed_at", "official_source_url", "document_number", "document_type",
    "issuing_body", "issued_on", "effective_from", "effective_conclusion", "source_checked_at",
    "evidence_note", "amendment_note", "title", "raw_sha256", "canonical_sha256",
)


def _read_jsonl(path: Path) -> list[dict]:
    rows = []
    with path.open(encoding="utf-8") as stream:
        for number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"{path}:{number}: invalid JSON") from error
            if not isinstance(row, dict):
                raise ValueError(f"{path}:{number}: expected JSON object")
            rows.append(row)
    return rows


def _write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8", newline="\n")


def _code_hash() -> str:
    digest = hashlib.sha256()
    for name in ("m1.py", "legal_text.py"):
        digest.update(Path(__file__).with_name(name).read_text(encoding="utf-8").encode("utf-8"))
    return digest.hexdigest()


def _jsonl_hash(path: Path) -> str:
    """Hash record content, independent of Git/OS newline and key formatting."""
    digest = hashlib.sha256()
    for row in _read_jsonl(path):
        digest.update(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def _labor_branch(link) -> bool:
    if not isinstance(link, str):
        return False
    try:
        parts = urlsplit(link).path.split("/")
    except ValueError:
        return False
    return len(parts) > 2 and parts[2].lower() == "lao-dong-tien-luong"


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _record(archive: zipfile.ZipFile, row: dict) -> dict:
    if not RECORD_PATH.fullmatch(row["path"]):
        raise ValueError("invalid archive member path")
    if archive.getinfo(row["path"]).file_size > MAX_RECORD_BYTES:
        raise ValueError("raw record exceeds size limit")
    raw = archive.read(row["path"])
    if hashlib.sha256(raw).hexdigest() != row["raw_sha256"]:
        raise ValueError("raw record hash mismatch")
    record = json.loads(raw.decode("utf-8"))
    if record["id"] != row["raw_id"] or record["link"] != row["link"]:
        raise ValueError("inventory does not match raw record")
    return record


def build_candidates(zip_path: Path, inventory_path: Path, output_dir: Path, *, core_record_ids=()) -> list[dict]:
    """Rank all inventory entries; suggestions never grant legal approval."""
    output_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    core_record_ids = sorted(set(core_record_ids))
    with zipfile.ZipFile(zip_path) as archive:
        for row in _read_jsonl(inventory_path):
            signals = {}
            if row["status"] == "valid":
                record = _record(archive, row)
                url_text = (urlsplit(row["link"]).path.rsplit("/", 1)[-1] + " " + (row.get("name") or "")).lower()
                passage = record["passage"]
                for topic, phrases in TOPICS.items():
                    found = []
                    if any(phrase in url_text for phrase in phrases):
                        found.append("url_or_name")
                    for phrase in phrases:
                        pattern = r"\s+".join(re.escape(word) for word in phrase.split())
                        match = re.search(pattern, passage, re.IGNORECASE)
                        if match:
                            found.append({"source": "passage", "start": match.start(), "end": match.end(),
                                          "excerpt": passage[match.start():match.end()]})
                            break
                    if found:
                        signals[topic] = found
            topics = sorted(signals)
            labor_branch = _labor_branch(row.get("link"))
            decision = "candidate" if topics or labor_branch or row["raw_id"] in core_record_ids else "not_prioritized"
            if row["status"] != "valid":
                decision = "quarantined"
            rows.append({"raw_id": row["raw_id"], "path": row["path"], "raw_sha256": row["raw_sha256"],
                         "raw_url": row["link"], "url_labor_branch": labor_branch,
                         "candidate_topics": topics, "signals": signals, "decision": decision,
                         "reviewer_core_selection": row["raw_id"] in core_record_ids,
                         "reason_code": row["reason_code"] if decision == "quarantined" else
                         ("NO_TOPIC_SIGNAL" if decision == "not_prioritized" else None)})
    _write_jsonl(output_dir / "candidate-decisions.jsonl", rows)
    counts = Counter(row["decision"] for row in rows)
    labor = sum(row["url_labor_branch"] for row in rows)
    report = {"schema_version": 2, "pipeline_version": PIPELINE_VERSION, "code_sha256": _code_hash(),
              "config": {"topic_phrases": TOPICS, "core_record_ids": core_record_ids, "max_record_bytes": MAX_RECORD_BYTES,
                         "normalization": "NFC/newlines/blank-lines-with-raw-map", "minimum_structure_samples_per_type": 10,
                         "chunk_policy": "complete-reviewed-clause-or-unnumbered-article", "jsonl_hashing": "canonical-jsonl-utf8"},
              "candidate_sha256": _jsonl_hash(output_dir / "candidate-decisions.jsonl"),
              "zip_sha256": _sha256_file(zip_path),
              "inventory_sha256": _jsonl_hash(inventory_path), "total": len(rows),
              "url_labor_branch": labor, "decision_counts": dict(sorted(counts.items())),
              "topic_counts": {topic: sum(topic in row["candidate_topics"] for row in rows)
                               for topic in TOPICS}}
    _write_json(output_dir / "candidate-report.json", report)
    return rows


def extract_units(raw_passage: str) -> tuple[str, list[dict]]:
    """Compatibility helper returning normalized text and complete retrieval units."""
    text, _ = normalize_text(raw_passage)
    units, _ = parse_legal_units(text)
    return text, retrieval_units(units)


def _load_inputs(zip_path: Path, inventory_path: Path, candidate_path: Path):
    report = json.loads(candidate_path.with_name("candidate-report.json").read_text(encoding="utf-8"))
    expected = {"zip_sha256": _sha256_file(zip_path), "inventory_sha256": _jsonl_hash(inventory_path),
                "candidate_sha256": _jsonl_hash(candidate_path), "code_sha256": _code_hash()}
    for key, value in expected.items():
        if report.get(key) != value:
            raise ValueError(f"{key} hash mismatch; rebuild candidates with the current inputs and code")
    inventory = _read_jsonl(inventory_path)
    candidates = _read_jsonl(candidate_path)
    by_path = {row["path"]: row for row in inventory}
    candidate_paths = [row["path"] for row in candidates]
    if len(by_path) != len(inventory) or len(set(candidate_paths)) != len(candidates) or set(candidate_paths) != set(by_path):
        raise ValueError("candidate/inventory coverage mismatch")
    for candidate in candidates:
        raw = by_path[candidate["path"]]
        if any(candidate[key] != raw[key] for key in ("raw_id", "raw_sha256")):
            raise ValueError("candidate/inventory identity mismatch")
        if raw["status"] != "valid" and candidate["decision"] != "quarantined":
            raise ValueError("candidate bypasses raw quarantine")
    return by_path, candidates, report


def _prepare_document(archive, row):
    record = _record(archive, row)
    raw = record["passage"]
    canonical, mapping = normalize_text(raw)
    units, issues = parse_legal_units(canonical)
    for unit in units:
        unit["raw_start"], unit["raw_end"] = raw_span(mapping, unit["start"], unit["end"])
    return {"raw_id": row["raw_id"], "raw_path": row["path"], "raw_url": row["link"],
            "raw_sha256": row["raw_sha256"], "raw_passage_sha256": hashlib.sha256(raw.encode()).hexdigest(),
            "raw_passage": raw, "canonical_text": canonical,
            "canonical_sha256": hashlib.sha256(canonical.encode()).hexdigest(), "offset_map": mapping,
            "legal_units": units, "parse_issues": issues}


def prepare_records(zip_path: Path, inventory_path: Path, candidate_path: Path, output_dir: Path, *, raw_ids=None) -> dict:
    """Write inspectable canonical documents and an explicitly pending review template."""
    inventory, candidates, inputs = _load_inputs(zip_path, inventory_path, candidate_path)
    selected = set(raw_ids) if raw_ids is not None else None
    if selected is not None and not selected <= {row["raw_id"] for row in candidates if isinstance(row["raw_id"], int)}:
        raise ValueError("unknown selected raw ID")
    prepared_dir = output_dir / "prepared"
    prepared_dir.mkdir(parents=True, exist_ok=True)
    templates, manifest = [], []
    with zipfile.ZipFile(zip_path) as archive:
        for candidate in candidates:
            if (selected is not None and candidate["raw_id"] not in selected) or (selected is None and candidate["decision"] != "candidate"):
                continue
            if candidate["decision"] == "quarantined":
                continue
            doc = _prepare_document(archive, inventory[candidate["path"]])
            _write_json(prepared_dir / f"{candidate['raw_id']}.json", doc)
            manifest.append({key: doc[key] for key in ("raw_id", "raw_path", "raw_sha256", "canonical_sha256", "parse_issues")})
            manifest[-1]["unit_count"] = len(doc["legal_units"])
            template = {key: None for key in REVIEW_FIELDS}
            template.update({"raw_id": candidate["raw_id"], "decision": "pending", "raw_sha256": doc["raw_sha256"],
                             "canonical_sha256": doc["canonical_sha256"], "effective_to": None,
                             "as_of_date": None,
                             "topic_tags": candidate["candidate_topics"], "checked_unit_ids": [],
                             "approved_unit_ids": [], "unit_topic_tags": {},
                             "text_match": False, "structure_reviewed": False})
            templates.append(template)
    _write_jsonl(output_dir / "prepared-manifest.jsonl", manifest)
    _write_jsonl(output_dir / "review-template.jsonl", templates)
    report = {"prepared_count": len(manifest), "parse_issue_count": sum(bool(m["parse_issues"]) for m in manifest),
              "zip_sha256": inputs["zip_sha256"], "code_sha256": inputs["code_sha256"]}
    _write_json(output_dir / "prepare-report.json", report)
    return report


def _review_error(review: dict, candidate: dict) -> str | None:
    if candidate["decision"] == "quarantined":
        return "INVALID_RAW_RECORD"
    if review.get("decision") == "pending":
        return "PENDING_REVIEW"
    if review.get("decision") != "approve":
        return "REJECTED_BY_REVIEWER" if review.get("decision") == "reject" else "INVALID_REVIEW_DECISION"
    tags = review.get("topic_tags")
    if not isinstance(tags, list) or not tags or any(not isinstance(tag, str) or tag not in TOPICS for tag in tags):
        return "OUT_OF_SCOPE"
    if (any(not isinstance(review.get(key), str) or not review[key].strip() for key in REVIEW_FIELDS)
            or review.get("text_match") is not True
            or review.get("structure_reviewed") is not True):
        return "INCOMPLETE_REVIEW"
    if any(not re.fullmatch(r"[0-9a-f]{64}", review[key]) for key in ("raw_sha256", "canonical_sha256")):
        return "INVALID_REVIEW_HASH"
    if not isinstance(review.get("checked_unit_ids"), list) or any(not isinstance(unit, str) for unit in review["checked_unit_ids"]):
        return "INVALID_STRUCTURE_SAMPLES"
    selected = review.get("approved_unit_ids")
    unit_topics = review.get("unit_topic_tags")
    if (not isinstance(selected, list) or not selected or any(not isinstance(unit, str) for unit in selected)
            or not isinstance(unit_topics, dict) or set(unit_topics) != set(selected)):
        return "INCOMPLETE_UNIT_REVIEW"
    if any(not isinstance(tags, list) or not tags or any(topic not in review["topic_tags"] for topic in tags)
           for tags in unit_topics.values()):
        return "OUT_OF_SCOPE"
    if not isinstance(review.get("unit_source_evidence", {}), dict):
        return "INCOMPLETE_UNIT_REVIEW"
    if (review.get("official_source_sha256") is not None and
            not re.fullmatch(r"[0-9a-f]{64}", str(review["official_source_sha256"]))):
        return "INVALID_SOURCE_HASH"
    try:
        for key in ("reviewed_at", "issued_on", "effective_from", "source_checked_at"):
            date.fromisoformat(review[key])
        if review.get("effective_to") is not None:
            date.fromisoformat(review["effective_to"])
        if review.get("as_of_date") is not None:
            date.fromisoformat(review["as_of_date"])
    except (TypeError, ValueError):
        return "INVALID_REVIEW_DATE"
    try:
        source_url = urlsplit(review["official_source_url"])
        host = source_url.hostname or ""
    except ValueError:
        return "UNOFFICIAL_SOURCE"
    approved_domain = (host == "vbpl.vn" or host.endswith(".vbpl.vn") or host == "chinhphu.vn"
                       or host.endswith(".chinhphu.vn") or host.endswith(".gov.vn"))
    if source_url.scheme != "https" or not approved_domain:
        return "UNOFFICIAL_SOURCE"
    if review["effective_conclusion"] not in ("effective_as_of_review", "effective_for_as_of_date"):
        return "UNCERTAIN_EFFECT"
    as_of_date = review.get("as_of_date") or review["reviewed_at"]
    if review["effective_conclusion"] == "effective_for_as_of_date" and not review.get("as_of_date"):
        return "UNCERTAIN_EFFECT"
    if review["effective_conclusion"] == "effective_as_of_review" and as_of_date != review["reviewed_at"]:
        return "UNCERTAIN_EFFECT"
    if review.get("effective_to") and review["effective_to"] < review["effective_from"]:
        return "INVALID_EFFECTIVE_INTERVAL"
    if (as_of_date < review["effective_from"] or
            (review.get("effective_to") and as_of_date >= review["effective_to"])):
        return "NOT_EFFECTIVE_AT_AS_OF_DATE" if review.get("as_of_date") else "NOT_EFFECTIVE_AT_REVIEW"
    if (review["source_checked_at"] > review["reviewed_at"] or review["issued_on"] > as_of_date
            or as_of_date > review["reviewed_at"]):
        return "INVALID_REVIEW_DATE"
    return None


def build_corpus(zip_path: Path, inventory_path: Path, candidate_path: Path,
                 review_path: Path, output_dir: Path) -> dict:
    """Release only records with explicit complete review evidence."""
    inventory, candidates, inputs = _load_inputs(zip_path, inventory_path, candidate_path)
    reviews = _read_jsonl(review_path)
    known_ids = {row["raw_id"] for row in candidates if isinstance(row["raw_id"], int)}
    by_id = {}
    duplicate_ids = set()
    for review in reviews:
        identifier = review.get("raw_id")
        if not isinstance(identifier, int) or isinstance(identifier, bool) or identifier not in known_ids:
            raise ValueError(f"unknown or invalid review raw ID: {identifier}")
        if identifier in by_id:
            duplicate_ids.add(identifier)
        by_id[identifier] = review
    proposed = []
    quarantine = []
    chunks = []
    seen = {}
    structure_samples = {}

    def exclude(candidate, reason, review=None, **extra):
        quarantine.append({"raw_id": candidate["raw_id"], "reason_code": reason, "path": candidate["path"],
                           "review": review, **extra})

    with zipfile.ZipFile(zip_path) as archive:
        for candidate in candidates:
            identifier = candidate["raw_id"]
            review = by_id.get(identifier) if isinstance(identifier, int) else None
            if review is None:
                reason = "PENDING_REVIEW" if candidate["decision"] == "candidate" else candidate["reason_code"] or "NOT_PRIORITIZED"
            elif identifier in duplicate_ids:
                reason = "CONFLICTING_REVIEW"
            else:
                reason = _review_error(review, candidate)
            if reason is not None:
                exclude(candidate, reason, review)
                continue
            row = inventory[candidate["path"]]
            doc = _prepare_document(archive, row)
            if review["raw_sha256"] != doc["raw_sha256"] or review["canonical_sha256"] != doc["canonical_sha256"]:
                exclude(candidate, "REVIEW_HASH_MISMATCH", review)
                continue
            retrieval = {u["unit_id"]: u for u in retrieval_units(doc["legal_units"])}
            selected = set(review["approved_unit_ids"])
            if not selected <= set(retrieval):
                exclude(candidate, "INVALID_APPROVED_UNITS", review)
                continue
            if any(retrieval[unit]["parse_issues"] for unit in selected):
                exclude(candidate, "AMBIGUOUS_LEGAL_STRUCTURE", review, parse_issues=doc["parse_issues"])
                continue
            parents = {retrieval[unit]["parent_id"] for unit in selected} - {None}
            eligible = selected | parents
            checked = set(review["checked_unit_ids"])
            if not checked <= eligible:
                exclude(candidate, "INVALID_STRUCTURE_SAMPLES", review)
                continue
            version_key = {key: review.get(key) for key in
                           ("document_number", "issuing_body", "issued_on", "effective_from", "effective_to")}
            version_key["canonical_sha256"] = doc["canonical_sha256"]
            version_hash = hashlib.sha256(json.dumps(version_key, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
            if version_hash in seen:
                seen[version_hash]["raw_record_ids"].append(identifier)
                seen[version_hash]["additional_provenance"].append({"raw_id": identifier, "raw_path": row["path"],
                                                                  "raw_sha256": row["raw_sha256"], "review": review})
                exclude(candidate, "DUPLICATE_VERSION", review, duplicate_of=seen[version_hash]["raw_id"])
                continue
            doc.update({"version_hash": version_hash, "raw_record_ids": [identifier], "additional_provenance": [],
                        "as_of_date": review.get("as_of_date") or review["reviewed_at"],
                        "topic_tags": review["topic_tags"], "candidate_topics": candidate["candidate_topics"],
                        "review": review, "status": "approved", "source_evidence": {
                            "url": review["official_source_url"], "checked_at": review["source_checked_at"],
                            "text_match": review["text_match"], "note": review["evidence_note"],
                            "amendment_note": review["amendment_note"], "downloaded_sha256": review.get("official_source_sha256")}})
            proposed.append(doc)
            seen[version_hash] = doc
            structure_samples.setdefault(review["document_type"], set()).update((version_hash, unit) for unit in checked)

    active = []
    for doc in proposed:
        review = doc["review"]
        if len(structure_samples[review["document_type"]]) < 10:
            exclude({"raw_id": doc["raw_id"], "path": doc["raw_path"]}, "INSUFFICIENT_STRUCTURE_SAMPLES", review)
            continue
        active.append(doc)
        global_ids = {u["unit_id"]: hashlib.sha256((doc["version_hash"] + ":" + u["unit_id"]).encode()).hexdigest()
                      for u in doc["legal_units"]}
        selected = set(review["approved_unit_ids"])
        for unit in retrieval_units(doc["legal_units"]):
            if unit["unit_id"] not in selected:
                continue
            version_hash = doc["version_hash"]
            chunk_id = hashlib.sha256((version_hash + ":" + str(unit["start"]) + ":" + str(unit["end"])).encode()).hexdigest()
            chunks.append({"chunk_id": chunk_id, "raw_id": doc["raw_id"], "version_hash": version_hash,
                               "unit_ids": [global_ids[unit["unit_id"]]], "topic_tags": review["unit_topic_tags"][unit["unit_id"]],
                               "document_number": review["document_number"], "official_source_url": review["official_source_url"],
                               "source_evidence": review.get("unit_source_evidence", {}).get(unit["unit_id"], doc["source_evidence"]),
                               "effective_from": review["effective_from"], "effective_to": review.get("effective_to"),
                               "as_of_date": doc["as_of_date"],
                               "reviewer": review["reviewer"], "reviewed_at": review["reviewed_at"],
                               "article_label": unit["article_label"], "clause_label": unit["clause_label"], "point_label": unit["point_label"],
                               "raw_start": unit["raw_start"], "raw_end": unit["raw_end"],
                               "start": unit["start"], "end": unit["end"], "text": unit["text"],
                               "context_header": unit["context_header"],
                               "content_hash": hashlib.sha256(unit["text"].encode()).hexdigest(),
                               "parse_confidence": unit["parse_confidence"], "review_status": "approved"})
        parents = {u["parent_id"] for u in doc["legal_units"] if u["unit_id"] in selected} - {None}
        doc["legal_units"] = [u for u in doc["legal_units"] if u["unit_id"] in selected | parents or u["parent_id"] in selected]
        doc["topic_tags"] = sorted({topic for tags in review["unit_topic_tags"].values() for topic in tags})
        for unit in doc["legal_units"]:
            local_id = unit["unit_id"]
            unit["unit_id"] = global_ids[local_id]
            unit["parent_id"] = global_ids.get(unit["parent_id"])
            unit["review_status"] = "context_only" if local_id in parents else "approved"
    supported = sorted({topic for doc in active for topic in doc["topic_tags"]})
    manifest = {"schema_version": 2, "pipeline_version": PIPELINE_VERSION, "code_sha256": inputs["code_sha256"],
                "config": inputs["config"], "active": bool(active), "supported_topics": supported,
                "temporal_scope": {"as_of_dates": sorted({doc["as_of_date"] for doc in active}),
                                   "policy": "only_explicit_verified_dates"},
                "approved_at": max((doc["review"]["reviewed_at"] for doc in active), default=None),
                "zip_sha256": inputs["zip_sha256"], "inventory_sha256": inputs["inventory_sha256"],
                "candidate_sha256": _jsonl_hash(candidate_path), "review_sha256": _jsonl_hash(review_path),
                "documents": active, "chunks": chunks}
    manifest_bytes = json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    manifest["manifest_hash"] = hashlib.sha256(manifest_bytes).hexdigest()
    rendered = json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    snapshots = output_dir / "snapshots"
    snapshots.mkdir(parents=True, exist_ok=True)
    frozen = snapshots / f"{manifest['manifest_hash']}.json"
    if frozen.exists():
        if frozen.read_text(encoding="utf-8") != rendered:
            raise ValueError("snapshot hash collision or modified snapshot")
    else:
        frozen.write_text(rendered, encoding="utf-8", newline="\n")
    current = output_dir / "labor-corpus-v1.json"
    temporary = current.with_suffix(".tmp")
    temporary.write_text(rendered, encoding="utf-8", newline="\n")
    temporary.replace(current)
    _write_jsonl(output_dir / "quarantine.jsonl", quarantine)
    report = {"active_count": len(active), "chunk_count": len(chunks),
              "pending_count": sum(q["reason_code"] == "PENDING_REVIEW" for q in quarantine),
              "quarantine_count": len(quarantine), "reason_counts": dict(sorted(Counter(q["reason_code"] for q in quarantine).items())),
              "structure_sample_counts": {kind: len(samples) for kind, samples in sorted(structure_samples.items())},
              "supported_topics": supported, "m1_complete": bool(active) and set(supported) == set(TOPICS),
              "as_of_dates": manifest["temporal_scope"]["as_of_dates"],
              "manifest_hash": manifest["manifest_hash"]}
    _write_json(output_dir / "review-report.json", report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Build M1 candidates and reviewed corpus")
    parser.add_argument("command", choices=("candidates", "prepare", "release"))
    parser.add_argument("--zip", type=Path, default=Path("selected-contexts.zip"))
    parser.add_argument("--inventory", type=Path, default=Path("data/manifests/m0/raw-inventory.jsonl"))
    parser.add_argument("--candidates", type=Path, default=Path("data/manifests/m1/candidate-decisions.jsonl"))
    parser.add_argument("--reviews", type=Path, default=Path("data/manifests/m1/reviews.jsonl"))
    parser.add_argument("--output", type=Path, default=Path("data/manifests/m1"))
    parser.add_argument("--raw-id", type=int, action="append", help="Select raw IDs for preparation (repeatable)")
    parser.add_argument("--core-record-id", type=int, action="append", default=[], help="Reviewer-selected core IDs to prioritize")
    args = parser.parse_args()
    if args.command == "candidates":
        rows = build_candidates(args.zip, args.inventory, args.output, core_record_ids=args.core_record_id)
        print(f"Ranked {len(rows)} raw records")
    elif args.command == "prepare":
        print(json.dumps(prepare_records(args.zip, args.inventory, args.candidates, args.output, raw_ids=args.raw_id)))
    else:
        report = build_corpus(args.zip, args.inventory, args.candidates, args.reviews, args.output)
        print(json.dumps(report, ensure_ascii=True))


if __name__ == "__main__":
    main()
