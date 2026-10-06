import unittest

from data.legal_text import normalize_text, parse_legal_units, raw_span


class LegalTextTests(unittest.TestCase):
    def test_normalizes_unicode_newlines_and_maps_back_to_original(self):
        raw = "Đie\u0302\u0300u 1. Hợp đồng\r\n\r\n\r\n1. Lương\u00a0cơ bản.  \r\n"
        canonical, mapping = normalize_text(raw)
        self.assertEqual(canonical, "Điều 1. Hợp đồng\n\n1. Lương cơ bản.\n")
        start = canonical.index("1. Lương")
        span = raw_span(mapping, start, len(canonical))
        self.assertEqual(raw[span[0]:span[1]], "1. Lương\u00a0cơ bản.  \r\n")

    def test_preserves_tables_and_internal_whitespace(self):
        raw = "Điều 1. Bảng\nCột A\tCột B\n10  20\n"
        canonical, mapping = normalize_text(raw)
        self.assertEqual(canonical, raw)
        self.assertEqual(raw_span(mapping, 0, len(canonical)), (0, len(raw)))

    def test_parser_keeps_chapter_section_article_clause_and_point_spans(self):
        text = "Chương I\nQUY ĐỊNH\nMục 1\nHỢP ĐỒNG\nĐiều 1. Nội dung\n1. Điều kiện:\na) Tiền lương;\nb) Ngoại lệ.\n2. Phạm vi.\nĐiều 2. Khác\nNội dung."
        units, issues = parse_legal_units(text)
        self.assertEqual(issues, [])
        self.assertEqual([u["kind"] for u in units], ["article", "clause", "point", "point", "clause", "article"])
        self.assertEqual(units[2]["point_label"], "a")
        self.assertEqual(units[0]["heading_path"], ["Chương I", "Mục 1", "Điều 1. Nội dung"])
        self.assertTrue(all(text[u["start"]:u["end"]] == u["text"] for u in units))
        self.assertEqual(units[1]["parent_id"], units[0]["unit_id"])

    def test_duplicate_articles_are_flagged_for_manual_resolution(self):
        _, issues = parse_legal_units("Điều 1. A\nNội dung\nĐiều 1. B\nNội dung")
        self.assertIn("DUPLICATE_ARTICLE_LABEL", issues)

    def test_wrapped_headings_are_parsed_and_article_references_are_not_headings(self):
        text = "Chương\n\nII\nĐiều\n\n3. Hợp đồng\n1. Theo quy định tại\nĐiều 93 của Bộ luật.\n2. Nội dung khác.\nĐiều\n4. Hiệu lực\n1. Áp dụng."
        units, issues = parse_legal_units(text)
        self.assertEqual(issues, [])
        self.assertEqual([(u["article_label"], u["clause_label"]) for u in units if u["kind"] == "clause"],
                         [("3", "1"), ("3", "2"), ("4", "1")])
        self.assertEqual(units[0]["heading_path"][0], "Chương II")


if __name__ == "__main__":
    unittest.main()
