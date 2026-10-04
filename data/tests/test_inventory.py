import hashlib
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from data.inventory import build_inventory


def write_zip(path: Path, entries: list[tuple[str, bytes]]) -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in entries:
            archive.writestr(name, content)


def record(identifier: int, passage: str, *, name: str | None = None) -> bytes:
    item = {
        "id": identifier,
        "link": f"https://thuvienphapluat.vn/van-ban/Lao-dong-Tien-luong/doc-{identifier}.aspx",
        "passage": passage,
    }
    if name is not None:
        item["name"] = name
    return json.dumps(item, ensure_ascii=False).encode("utf-8")


class InventoryTests(unittest.TestCase):
    def test_classifies_every_file_and_reports_nonempty_duplicates(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "selected-contexts.zip"
            write_zip(
                source,
                [
                    ("selected-contexts/context_1.json", record(1, "Điều 1. Làm việc")),
                    ("selected-contexts/context_2.json", record(2, "Điều 1.\nLàm việc", name="Bản 2")),
                    ("selected-contexts/context_3.json", record(3, "", name="Rỗng")),
                    ("selected-contexts/context_4.json", b"{bad-json"),
                    ("selected-contexts/context_5.json", record(99, "Sai ID")),
                    ("../outside.json", record(6, "Sai đường dẫn")),
                ],
            )
            source_hash = hashlib.sha256(source.read_bytes()).hexdigest()

            report = build_inventory(source, root / "output")

            self.assertEqual(report["zip_sha256"], source_hash)
            self.assertEqual(report["total_files"], 6)
            self.assertEqual(report["valid"], 2)
            self.assertEqual(report["quarantined"], 4)
            self.assertEqual(report["reason_counts"], {
                "EMPTY_PASSAGE": 1,
                "ID_MISMATCH": 1,
                "INVALID_JSON": 1,
                "INVALID_PATH": 1,
            })
            self.assertEqual(report["missing_name"], 2)
            self.assertEqual(report["duplicate_nonempty_passage_groups"], 1)
            self.assertEqual(report["duplicate_nonempty_passage_excess"], 1)
            self.assertEqual(report["url_topic_counts"]["Lao-dong-Tien-luong"], 4)
            rows = [json.loads(line) for line in (root / "output/raw-inventory.jsonl").read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(rows), 6)
            self.assertEqual(sum(row["status"] == "valid" for row in rows), 2)
            self.assertTrue(all(row["raw_sha256"] for row in rows))
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), source_hash)

    def test_repeated_runs_have_identical_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "selected-contexts.zip"
            write_zip(source, [("selected-contexts/context_7.json", record(7, "Khoản 1."))])
            build_inventory(source, root / "first")
            build_inventory(source, root / "second")
            for filename in ("raw-inventory.jsonl", "quarantine.jsonl", "m0-report.json", "m0-report.md"):
                self.assertEqual((root / "first" / filename).read_bytes(), (root / "second" / filename).read_bytes())

    def test_oversized_record_is_quarantined_without_losing_hash(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "selected-contexts.zip"
            payload = record(8, "x" * 100)
            write_zip(source, [("selected-contexts/context_8.json", payload)])

            report = build_inventory(source, root / "output", max_record_bytes=60)

            self.assertEqual(report["reason_counts"], {"RECORD_TOO_LARGE": 1})
            row = json.loads((root / "output/quarantine.jsonl").read_text(encoding="utf-8"))
            self.assertEqual(row["raw_sha256"], hashlib.sha256(payload).hexdigest())
            self.assertEqual(row["uncompressed_bytes"], len(payload))

    def test_malformed_url_is_quarantined_without_stopping_other_records(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "selected-contexts.zip"
            malformed = json.dumps(
                {"id": 1, "link": "https://[broken", "passage": "Text"}
            ).encode("utf-8")
            write_zip(
                source,
                [
                    ("selected-contexts/context_1.json", malformed),
                    ("selected-contexts/context_2.json", record(2, "Text hợp lệ")),
                ],
            )

            report = build_inventory(source, root / "output")

            self.assertEqual(report["valid"], 1)
            self.assertEqual(report["reason_counts"], {"INVALID_LINK": 1})


if __name__ == "__main__":
    unittest.main()
