import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

from data.m1 import _review_error, build_candidates, build_corpus, extract_units, prepare_records
from data.legal_text import normalize_text, parse_legal_units, retrieval_units


def write_fixture(root: Path) -> tuple[Path, Path]:
    source = root / "source.zip"
    records = [
        (1, "https://thuvienphapluat.vn/van-ban/Lao-dong-Tien-luong/Thong-tu-hop-dong-lao-dong.aspx", "Điều 1. Hợp đồng lao động\n" + "\n".join(f"{i}. Nội dung hợp đồng." for i in range(1, 11))),
        (2, "https://thuvienphapluat.vn/van-ban/Bao-hiem/quy-dinh-thu-viec.aspx", "Điều 2. Thử việc\n1. Thời hạn."),
        (3, "https://thuvienphapluat.vn/van-ban/Lao-dong-Tien-luong/noi-dung-khac.aspx", "Điều 3. Quy định khác.\n" + "\n".join(f"{i}. Quy định." for i in range(1, 11))),
    ]
    inventory = root / "inventory.jsonl"
    with zipfile.ZipFile(source, "w") as archive, inventory.open("w", encoding="utf-8") as out:
        for identifier, link, passage in records:
            path = f"selected-contexts/context_{identifier}.json"
            payload = json.dumps({"id": identifier, "link": link, "passage": passage}, ensure_ascii=False).encode()
            archive.writestr(path, payload)
            out.write(json.dumps({"path": path, "raw_id": identifier, "link": link, "name": None,
                                  "raw_sha256": hashlib.sha256(payload).hexdigest(), "status": "valid",
                                  "reason_code": None}, ensure_ascii=False) + "\n")
    return source, inventory


def approved_review(source, identifier=1):
    with zipfile.ZipFile(source) as archive:
        payload = archive.read(f"selected-contexts/context_{identifier}.json")
    raw = json.loads(payload)["passage"]
    canonical, _ = normalize_text(raw)
    units, _ = parse_legal_units(canonical)
    return {"raw_id": identifier, "decision": "approve", "reviewer": "A", "title": "Văn bản thử nghiệm",
            "reviewed_at": "2026-10-05", "official_source_url": "https://vbpl.vn/example",
            "document_number": "10/2020/TT-BLDTBXH", "document_type": "Thông tư", "issuing_body": "Bộ Lao động",
            "issued_on": "2020-11-12", "effective_from": "2021-01-01", "effective_to": None,
            "effective_conclusion": "effective_as_of_review", "source_checked_at": "2026-10-05",
            "text_match": True, "structure_reviewed": True, "topic_tags": ["contract"],
            "evidence_note": "Compared full source text", "amendment_note": "Checked amendments",
            "raw_sha256": hashlib.sha256(payload).hexdigest(),
            "canonical_sha256": hashlib.sha256(canonical.encode()).hexdigest(),
            "checked_unit_ids": [u["unit_id"] for u in units if u["kind"] in ("article", "clause")],
            "approved_unit_ids": [u["unit_id"] for u in retrieval_units(units)],
            "unit_source_evidence": {u["unit_id"]: {"url": "https://vbpl.vn/example", "pdf_page": 1,
                                                    "checked_at": "2026-10-05", "text_match": True}
                                     for u in retrieval_units(units)},
            "unit_topic_tags": {u["unit_id"]: ["contract"] for u in retrieval_units(units)}}


def write_reviews(path, reviews):
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in reviews), encoding="utf-8")


class M1Tests(unittest.TestCase):
    def test_candidates_use_multiple_signals_and_account_for_every_record(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source, inventory = write_fixture(root)
            rows = build_candidates(source, inventory, root / "out")
            self.assertEqual(len(rows), 3)
            self.assertIn("contract", rows[0]["candidate_topics"])
            self.assertIn("probation", rows[1]["candidate_topics"])
            self.assertEqual(rows[2]["candidate_topics"], [])
            self.assertEqual(rows[2]["decision"], "candidate")
            self.assertTrue(rows[2]["url_labor_branch"])

    def test_extract_units_preserves_spans_and_clause_labels(self):
        text = "Điều 1. Hợp đồng\r\n1. Nội dung.\r\n2. Lương.\r\nĐiều 2. Thử việc"
        canonical, units = extract_units(text)
        self.assertEqual(canonical, text.replace("\r\n", "\n"))
        self.assertEqual([(u["article_label"], u["clause_label"]) for u in units],
                         [("1", "1"), ("1", "2"), ("2", None)])
        self.assertEqual(units[0]["context_header"], "Điều 1. Hợp đồng")
        self.assertTrue(all(canonical[u["start"]:u["end"]] == u["text"] for u in units))

    def test_release_requires_complete_review_and_deduplicates(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source, inventory = write_fixture(root)
            build_candidates(source, inventory, root / "out")
            review = root / "review.jsonl"
            write_reviews(review, [approved_review(source)])
            result = build_corpus(source, inventory, root / "out/candidate-decisions.jsonl", review, root / "release")
            self.assertEqual(result["active_count"], 1)
            self.assertEqual(result["pending_count"], 2)
            manifest = json.loads((root / "release/labor-corpus-v1.json").read_text(encoding="utf-8"))
            self.assertEqual(len(manifest["chunks"]), 10)
            self.assertTrue(all(c["reviewer"] == "A" and c["official_source_url"] for c in manifest["chunks"]))
            self.assertEqual(manifest["chunks"][0]["source_evidence"]["pdf_page"], 1)

    def test_incomplete_or_conflicting_review_cannot_activate(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source, inventory = write_fixture(root)
            build_candidates(source, inventory, root / "out")
            review = root / "review.jsonl"
            review.write_text(json.dumps({"raw_id": 1, "decision": "approve", "reviewer": "A",
                                          "topic_tags": ["contract"]}) + "\n")
            result = build_corpus(source, inventory, root / "out/candidate-decisions.jsonl", review, root / "release")
            self.assertEqual(result["active_count"], 0)
            self.assertIn("INCOMPLETE_REVIEW", (root / "release/quarantine.jsonl").read_text())

    def test_reviewer_can_include_relevant_record_without_keyword_signal(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source, inventory = write_fixture(root)
            build_candidates(source, inventory, root / "out")
            review = root / "review.jsonl"
            write_reviews(review, [approved_review(source, 3)])
            result = build_corpus(source, inventory, root / "out/candidate-decisions.jsonl", review, root / "release")
            self.assertEqual(result["active_count"], 1)

    def test_review_rejects_non_https_and_not_yet_effective_version(self):
        candidate = {"candidate_topics": ["contract"], "decision": "candidate"}
        review = {"decision": "approve", "reviewer": "A", "reviewed_at": "2026-10-05",
                  "official_source_url": "http://vbpl.vn/example", "document_number": "1/2026/TT",
                  "document_type": "Thông tư", "issuing_body": "Bộ A", "issued_on": "2026-01-01",
                  "effective_from": "2026-12-01", "effective_conclusion": "effective_as_of_review",
                  "source_checked_at": "2026-10-05", "evidence_note": "Compared source",
                  "text_match": True, "structure_reviewed": True, "topic_tags": ["contract"],
                  "title": "Title", "amendment_note": "Checked", "raw_sha256": "a" * 64,
                  "canonical_sha256": "b" * 64, "checked_unit_ids": ["c" * 64],
                  "approved_unit_ids": ["c" * 64], "unit_topic_tags": {"c" * 64: ["contract"]}}
        self.assertEqual(_review_error(review, candidate), "UNOFFICIAL_SOURCE")
        review["official_source_url"] = "https://vbpl.vn/example"
        self.assertEqual(_review_error(review, candidate), "NOT_EFFECTIVE_AT_REVIEW")
        review["effective_from"] = "2021-01-01"
        review["official_source_url"] = "https://datafiles.chinhphu.vn/example.pdf"
        self.assertIsNone(_review_error(review, candidate))
        review["official_source_url"] = "https://chinhphu.vn.evil.org/example.pdf"
        self.assertEqual(_review_error(review, candidate), "UNOFFICIAL_SOURCE")

    def test_quarantined_raw_record_cannot_be_approved(self):
        self.assertEqual(_review_error({"decision": "approve", "topic_tags": ["contract"]},
                                       {"decision": "quarantined"}), "INVALID_RAW_RECORD")

    def test_malformed_inventory_link_stays_accounted_for(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source.zip"
            with zipfile.ZipFile(source, "w") as archive:
                archive.writestr("selected-contexts/context_1.json", "{}")
            inventory = root / "inventory.jsonl"
            inventory.write_text(json.dumps({"raw_id": 1, "path": "selected-contexts/context_1.json",
                "raw_sha256": "x", "link": "https://[broken", "name": None,
                "status": "quarantined", "reason_code": "INVALID_LINK"}) + "\n", encoding="utf-8")
            rows = build_candidates(source, inventory, root / "out")
            self.assertEqual(rows[0]["decision"], "quarantined")

    def test_prepare_exposes_text_offsets_and_pending_review_template(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source, inventory = write_fixture(root)
            build_candidates(source, inventory, root / "out")
            report = prepare_records(source, inventory, root / "out/candidate-decisions.jsonl", root / "stage", raw_ids=[1])
            self.assertEqual(report["prepared_count"], 1)
            document = json.loads((root / "stage/prepared/1.json").read_text(encoding="utf-8"))
            self.assertEqual(len(document["legal_units"]), 11)
            template = json.loads((root / "stage/review-template.jsonl").read_text(encoding="utf-8"))
            self.assertEqual(template["decision"], "pending")
            self.assertFalse(template["text_match"])
            self.assertEqual(template["canonical_sha256"], document["canonical_sha256"])

    def test_release_blocks_stale_review_and_insufficient_structure_samples(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source, inventory = write_fixture(root)
            build_candidates(source, inventory, root / "out")
            review = approved_review(source)
            review["canonical_sha256"] = "0" * 64
            review_file = root / "review.jsonl"
            write_reviews(review_file, [review])
            result = build_corpus(source, inventory, root / "out/candidate-decisions.jsonl", review_file, root / "release")
            self.assertEqual(result["reason_counts"].get("REVIEW_HASH_MISMATCH"), 1)
            review = approved_review(source)
            review["checked_unit_ids"] = review["checked_unit_ids"][:1]
            write_reviews(review_file, [review])
            result = build_corpus(source, inventory, root / "out/candidate-decisions.jsonl", review_file, root / "release")
            self.assertEqual(result["active_count"], 0)
            self.assertEqual(result["reason_counts"].get("INSUFFICIENT_STRUCTURE_SAMPLES"), 1)

    def test_stale_candidate_manifest_is_rejected_without_overwriting_release(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source, inventory = write_fixture(root)
            build_candidates(source, inventory, root / "out")
            candidates = root / "out/candidate-decisions.jsonl"
            rows = [json.loads(line) for line in candidates.read_text(encoding="utf-8").splitlines()]
            rows[0]["raw_sha256"] = "0" * 64
            write_reviews(candidates, rows)
            reviews = root / "reviews.jsonl"
            write_reviews(reviews, [])
            with self.assertRaisesRegex(ValueError, "candidate.*hash"):
                build_corpus(source, inventory, candidates, reviews, root / "release")
            self.assertFalse((root / "release/labor-corpus-v1.json").exists())

    def test_repeated_release_preserves_hash_and_snapshot_bytes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source, inventory = write_fixture(root)
            build_candidates(source, inventory, root / "out")
            reviews = root / "reviews.jsonl"
            write_reviews(reviews, [approved_review(source)])
            first = build_corpus(source, inventory, root / "out/candidate-decisions.jsonl", reviews, root / "release")
            frozen = root / f"release/snapshots/{first['manifest_hash']}.json"
            before = frozen.read_bytes()
            second = build_corpus(source, inventory, root / "out/candidate-decisions.jsonl", reviews, root / "release")
            self.assertEqual(first["manifest_hash"], second["manifest_hash"])
            self.assertEqual(before, frozen.read_bytes())

    def test_full_text_finds_relevant_content_outside_labor_branch_after_prefix(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source, inventory = write_fixture(root)
            with zipfile.ZipFile(source, "a") as archive:
                item = {"id": 4, "link": "https://example.org/van-ban/Bao-hiem/lao-dong-tien-luong.aspx",
                        "passage": "x" * 2500 + "\nĐiều 1. Quy định về thử\nviệc"}
                payload = json.dumps(item, ensure_ascii=False).encode()
                archive.writestr("selected-contexts/context_4.json", payload)
            with inventory.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps({"path": "selected-contexts/context_4.json", "raw_id": 4,
                                        "raw_sha256": hashlib.sha256(payload).hexdigest(), "link": item["link"],
                                        "name": None, "status": "valid", "reason_code": None}) + "\n")
            rows = build_candidates(source, inventory, root / "out")
            self.assertIn("probation", rows[-1]["candidate_topics"])
            self.assertFalse(rows[-1]["url_labor_branch"])

    def test_dedup_keeps_provenance_and_distinguishes_effective_versions(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source, inventory = write_fixture(root)
            with zipfile.ZipFile(source, "a") as archive:
                item = json.loads(archive.read("selected-contexts/context_1.json"))
                item["id"] = 4
                item["link"] = "https://example.org/duplicate.aspx"
                payload = json.dumps(item, ensure_ascii=False).encode()
                archive.writestr("selected-contexts/context_4.json", payload)
            with inventory.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps({"path": "selected-contexts/context_4.json", "raw_id": 4,
                                        "raw_sha256": hashlib.sha256(payload).hexdigest(), "link": item["link"],
                                        "name": None, "status": "valid", "reason_code": None}) + "\n")
            build_candidates(source, inventory, root / "out")
            first, duplicate = approved_review(source), approved_review(source, 4)
            reviews = root / "reviews.jsonl"
            write_reviews(reviews, [first, duplicate])
            result = build_corpus(source, inventory, root / "out/candidate-decisions.jsonl", reviews, root / "release")
            self.assertEqual(result["active_count"], 1)
            self.assertEqual(result["reason_counts"]["DUPLICATE_VERSION"], 1)
            manifest = json.loads((root / "release/labor-corpus-v1.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["documents"][0]["raw_record_ids"], [1, 4])
            duplicate["effective_from"] = "2022-01-01"
            write_reviews(reviews, [first, duplicate])
            result = build_corpus(source, inventory, root / "out/candidate-decisions.jsonl", reviews, root / "release")
            self.assertEqual(result["active_count"], 2)
            manifest = json.loads((root / "release/labor-corpus-v1.json").read_text(encoding="utf-8"))
            self.assertEqual(len({c["chunk_id"] for c in manifest["chunks"]}), 20)

    def test_release_only_emits_units_with_explicit_scope_review(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source, inventory = write_fixture(root)
            build_candidates(source, inventory, root / "out")
            review = approved_review(source)
            # Nine clauses plus their article provide ten distinct structural checks.
            review["approved_unit_ids"] = review["approved_unit_ids"][:9]
            review["unit_topic_tags"] = {unit: ["probation"] for unit in review["approved_unit_ids"]}
            review["topic_tags"] = ["probation"]
            review["checked_unit_ids"] = review["checked_unit_ids"][:10]
            reviews = root / "reviews.jsonl"
            write_reviews(reviews, [review])
            result = build_corpus(source, inventory, root / "out/candidate-decisions.jsonl", reviews, root / "release")
            self.assertEqual(result["chunk_count"], 9)
            manifest = json.loads((root / "release/labor-corpus-v1.json").read_text(encoding="utf-8"))
            self.assertTrue(all(chunk["topic_tags"] == ["probation"] for chunk in manifest["chunks"]))

    def test_line_endings_of_jsonl_inputs_do_not_change_snapshot_identity(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source, inventory = write_fixture(root)
            build_candidates(source, inventory, root / "out")
            reviews = root / "reviews.jsonl"
            write_reviews(reviews, [approved_review(source)])
            candidates = root / "out/candidate-decisions.jsonl"
            first = build_corpus(source, inventory, candidates, reviews, root / "release")
            for path in (inventory, candidates, reviews):
                path.write_bytes(path.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
            second = build_corpus(source, inventory, candidates, reviews, root / "release")
            self.assertEqual(first["manifest_hash"], second["manifest_hash"])

    def test_historical_effect_scope_is_separate_from_review_date(self):
        with tempfile.TemporaryDirectory() as temp:
            source, _ = write_fixture(Path(temp))
            review = approved_review(source)
            review.update({"as_of_date": "2022-01-01", "effective_to": "2023-01-01",
                           "effective_conclusion": "effective_for_as_of_date"})
            self.assertIsNone(_review_error(review, {"decision": "candidate"}))
            review["as_of_date"] = "2023-01-01"
            self.assertEqual(_review_error(review, {"decision": "candidate"}), "NOT_EFFECTIVE_AT_AS_OF_DATE")

    def test_release_cli_succeeds_with_windows_console_encoding(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source, inventory = write_fixture(root)
            build_candidates(source, inventory, root / "out")
            reviews = root / "reviews.jsonl"
            write_reviews(reviews, [approved_review(source)])
            review = approved_review(source)
            review["document_type"] = "Bộ luật"
            write_reviews(reviews, [review])
            environment = dict(os.environ, PYTHONIOENCODING="cp1258")
            result = subprocess.run([sys.executable, "-m", "data.m1", "release", "--zip", str(source),
                                     "--inventory", str(inventory), "--candidates", str(root / "out/candidate-decisions.jsonl"),
                                     "--reviews", str(reviews), "--output", str(root / "release")],
                                    cwd=Path(__file__).resolve().parents[2], env=environment, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr.decode("ascii", errors="replace"))
            self.assertEqual(json.loads(result.stdout)["chunk_count"], 10)


if __name__ == "__main__":
    unittest.main()
