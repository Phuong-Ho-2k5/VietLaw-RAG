"""Read-only M0 inventory. 'valid' means schema-valid, not legally verified."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import statistics
import zipfile
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import urlsplit


RECORD_PATH = re.compile(r"selected-contexts/context_([0-9]+)\.json\Z")
DEFAULT_MAX_RECORD_BYTES = 16_000_000
READ_BLOCK_BYTES = 1024 * 1024


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(READ_BLOCK_BYTES), b""):
            digest.update(block)
    return digest.hexdigest()


def _percentile(values: list[int], percent: float) -> int:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * percent) - 1)]


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def build_inventory(
    zip_path: Path, output_dir: Path, *, max_record_bytes: int = DEFAULT_MAX_RECORD_BYTES
) -> dict:
    """Audit each ZIP file and write deterministic inventory and report files."""
    zip_path = Path(zip_path)
    output_dir = Path(output_dir)
    if max_record_bytes < 1:
        raise ValueError("max_record_bytes must be positive")
    output_dir.mkdir(parents=True, exist_ok=True)

    zip_sha256 = _sha256_file(zip_path)
    reasons: Counter[str] = Counter()
    key_sets: Counter[str] = Counter()
    categories: Counter[str] = Counter()
    topics: Counter[str] = Counter()
    ids: Counter[int] = Counter()
    links: Counter[str] = Counter()
    text_hashes: dict[str, list[str]] = defaultdict(list)
    lengths: list[int] = []
    missing_name = valid = total_files = 0
    inventory_path = output_dir / "raw-inventory.jsonl"
    quarantine_path = output_dir / "quarantine.jsonl"

    with (
        zipfile.ZipFile(zip_path) as archive,
        inventory_path.open("w", encoding="utf-8", newline="\n") as inventory,
        quarantine_path.open("w", encoding="utf-8", newline="\n") as quarantine,
    ):
        members = sorted(
            (member for member in archive.infolist() if not member.is_dir()),
            key=lambda member: member.filename,
        )
        for member in members:
            total_files += 1
            raw_hash = hashlib.sha256()
            raw_bytes = bytearray()
            read_bytes = 0
            with archive.open(member) as stream:
                for block in iter(lambda: stream.read(READ_BLOCK_BYTES), b""):
                    raw_hash.update(block)
                    read_bytes += len(block)
                    if len(raw_bytes) < max_record_bytes:
                        raw_bytes.extend(block[: max_record_bytes - len(raw_bytes)])

            row: dict = {
                "path": member.filename,
                "declared_uncompressed_bytes": member.file_size,
                "uncompressed_bytes": read_bytes,
                "raw_sha256": raw_hash.hexdigest(),
                "raw_id": None,
                "link": None,
                "name": None,
                "passage_chars": None,
                "normalized_passage_sha256": None,
                "status": "valid",
                "reason_code": None,
            }
            match = RECORD_PATH.fullmatch(member.filename)
            reason = None
            if not match:
                reason = "INVALID_PATH"
            elif read_bytes > max_record_bytes:
                reason = "RECORD_TOO_LARGE"
            else:
                try:
                    document = json.loads(raw_bytes.decode("utf-8"))
                except UnicodeDecodeError:
                    reason = "INVALID_UTF8"
                except json.JSONDecodeError:
                    reason = "INVALID_JSON"
                else:
                    if not isinstance(document, dict):
                        reason = "INVALID_SCHEMA"
                    else:
                        key_sets[",".join(sorted(document))] += 1
                        if "name" not in document:
                            missing_name += 1
                        identifier = document.get("id")
                        link = document.get("link")
                        name = document.get("name")
                        passage = document.get("passage")
                        row["raw_id"] = identifier
                        row["link"] = link
                        row["name"] = name
                        if isinstance(identifier, int) and not isinstance(identifier, bool):
                            ids[identifier] += 1
                        parsed_link = None
                        if isinstance(link, str):
                            links[link] += 1
                            try:
                                parsed_link = urlsplit(link)
                            except ValueError:
                                pass
                            if parsed_link is not None:
                                parts = parsed_link.path.split("/")
                                if len(parts) > 1 and parts[1]:
                                    categories[parts[1]] += 1
                                if len(parts) > 2 and parts[2]:
                                    topics[parts[2]] += 1
                        if isinstance(passage, str):
                            row["passage_chars"] = len(passage)
                            lengths.append(len(passage))
                            normalized = " ".join(passage.split())
                            if normalized:
                                digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
                                row["normalized_passage_sha256"] = digest
                                text_hashes[digest].append(member.filename)
                        if (
                            not isinstance(identifier, int)
                            or isinstance(identifier, bool)
                            or identifier <= 0
                        ):
                            reason = "INVALID_ID"
                        elif identifier != int(match.group(1)):
                            reason = "ID_MISMATCH"
                        elif (
                            parsed_link is None
                            or parsed_link.scheme != "https"
                            or not parsed_link.netloc
                        ):
                            reason = "INVALID_LINK"
                        elif name is not None and not isinstance(name, str):
                            reason = "INVALID_NAME"
                        elif not isinstance(passage, str):
                            reason = "INVALID_PASSAGE"
                        elif not passage.strip():
                            reason = "EMPTY_PASSAGE"

            if reason:
                row["status"] = "quarantined"
                row["reason_code"] = reason
                reasons[reason] += 1
            else:
                valid += 1
            serialized = json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
            inventory.write(serialized)
            if reason:
                quarantine.write(serialized)

    duplicates = {digest: paths for digest, paths in text_hashes.items() if len(paths) > 1}
    length_summary = {
        "count": len(lengths),
        "min": min(lengths) if lengths else None,
        "median": statistics.median(lengths) if lengths else None,
        "p90": _percentile(lengths, 0.9) if lengths else None,
        "p99": _percentile(lengths, 0.99) if lengths else None,
        "max": max(lengths) if lengths else None,
    }
    report = {
        "schema_version": 1,
        "zip_file": zip_path.name,
        "zip_sha256": zip_sha256,
        "max_record_bytes": max_record_bytes,
        "total_files": total_files,
        "valid": valid,
        "quarantined": total_files - valid,
        "reason_counts": dict(sorted(reasons.items())),
        "schema_key_sets": dict(sorted(key_sets.items())),
        "missing_name": missing_name,
        "unique_ids": len(ids),
        "duplicate_id_excess": sum(count - 1 for count in ids.values()),
        "unique_links": len(links),
        "duplicate_link_excess": sum(count - 1 for count in links.values()),
        "url_category_counts": dict(sorted(categories.items())),
        "url_topic_counts": dict(sorted(topics.items())),
        "passage_length_chars": length_summary,
        "duplicate_nonempty_passage_groups": len(duplicates),
        "duplicate_nonempty_passage_excess": sum(len(paths) - 1 for paths in duplicates.values()),
        "duplicate_nonempty_passages": dict(sorted(duplicates.items())),
        "inventory_sha256": _sha256_file(inventory_path),
        "quarantine_sha256": _sha256_file(quarantine_path),
    }
    _write_json(output_dir / "m0-report.json", report)
    top_categories = sorted(categories.items(), key=lambda item: (-item[1], item[0]))[:10]
    lines = [
        "# M0 — Báo cáo kiểm kê selected-contexts.zip",
        "",
        f"- SHA-256 ZIP: {zip_sha256}",
        f"- Số file: {total_files:,}; schema valid: {valid:,}; quarantine: {total_files - valid:,}.",
        f"- Thiếu trường name: {missing_name:,}; ID duy nhất: {len(ids):,}; URL duy nhất: {len(links):,}.",
        f"- Nội dung không rỗng trùng sau chuẩn hóa khoảng trắng: {len(duplicates)} nhóm, "
        f"{report['duplicate_nonempty_passage_excess']} bản ghi dư.",
        (
            f"- Độ dài passage (ký tự): trung vị {length_summary['median']:,}, "
            f"p90 {length_summary['p90']:,}, p99 {length_summary['p99']:,}, "
            f"tối đa {length_summary['max']:,}."
            if lengths
            else "- Không có passage kiểu chuỗi."
        ),
        f"- URL ở nhánh Lao-dong-Tien-luong: {topics.get('Lao-dong-Tien-luong', 0):,}; "
        "đây chỉ là tín hiệu phân loại sơ bộ.",
        "",
        "## Schema quan sát được",
        "",
        "| Bộ trường | Số file |",
        "|---|---:|",
        *[f"| {keys} | {count:,} |" for keys, count in sorted(key_sets.items())],
        "",
        "## Lý do quarantine",
        "",
        "| Mã | Số file |",
        "|---|---:|",
        *[f"| {reason} | {count:,} |" for reason, count in sorted(reasons.items())],
        "",
        "## Nhánh URL lớn nhất",
        "",
        "| Nhánh | Số file |",
        "|---|---:|",
        *[f"| {category} | {count:,} |" for category, count in top_categories],
        "",
        "## Giới hạn",
        "",
        "Valid chỉ xác nhận cấu trúc bản ghi, không xác nhận chủ đề, nguồn có thẩm quyền, "
        "hiệu lực hay độ đầy đủ của văn bản. Nhánh URL chỉ là tín hiệu ưu tiên rà soát. "
        "Passage rỗng được cách ly trước bước chia đoạn và embedding.",
        "",
        "Chạy lại: python -m data.inventory --zip selected-contexts.zip --output data/manifests/m0",
        "",
    ]
    (output_dir / "m0-report.md").write_text("\n".join(lines), encoding="utf-8", newline="\n")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Build M0 ZIP inventory and data-quality report.")
    parser.add_argument("--zip", type=Path, default=Path("selected-contexts.zip"))
    parser.add_argument("--output", type=Path, default=Path("data/manifests/m0"))
    parser.add_argument("--max-record-bytes", type=int, default=DEFAULT_MAX_RECORD_BYTES)
    args = parser.parse_args()
    report = build_inventory(args.zip, args.output, max_record_bytes=args.max_record_bytes)
    print(
        f"ZIP {report['zip_sha256']}: {report['total_files']} files, "
        f"{report['valid']} valid, {report['quarantined']} quarantined"
    )


if __name__ == "__main__":
    main()
