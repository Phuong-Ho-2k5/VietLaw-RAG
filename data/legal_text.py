"""Conservative normalization and legal structure extraction with source offsets."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections import Counter


ARTICLE = re.compile(r"(?m)^[ \t]*Điều[ \t\r\n]+([0-9]+[a-z]?)[ \t]*[.:]", re.IGNORECASE)
CHAPTER = re.compile(r"(?m)^[ \t]*Chương[ \t\r\n]+(?:[IVXLCDM]+|[0-9]+)\b", re.IGNORECASE)
SECTION = re.compile(r"(?m)^[ \t]*Mục[ \t\r\n]+[0-9]+\b", re.IGNORECASE)
CLAUSE = re.compile(r"(?m)^[ \t]*([0-9]+)[.][ \t]+(?=\S)")
POINT = re.compile(r"(?m)^[ \t]*([a-zđ])[)][ \t]*(?=\S)", re.IGNORECASE)


def normalize_text(raw: str) -> tuple[str, list[dict]]:
    """Normalize NFC/newlines/blank lines, preserving tables and a line-level map.

    Changed lines map to their whole raw line. Identity runs support exact offsets.
    No text is inferred and internal horizontal whitespace is retained.
    """
    parts = []
    mapping = []
    raw_start = canonical_start = 0
    previous_blank = False
    for line in raw.splitlines(keepends=True):
        newline = line.endswith(("\r", "\n"))
        body = line.rstrip("\r\n") if newline else line
        normalized = unicodedata.normalize("NFC", body.replace("\u00a0", " ")).rstrip(" \t")
        blank = not normalized
        normalized += "\n" if newline else ""
        if blank and previous_blank:
            normalized = ""
        previous_blank = blank
        operation = "identity" if normalized == line else "normalized"
        item = {"canonical_start": canonical_start, "canonical_end": canonical_start + len(normalized),
                "raw_start": raw_start, "raw_end": raw_start + len(line), "operation": operation}
        if operation == "identity" and mapping and mapping[-1]["operation"] == "identity":
            mapping[-1]["canonical_end"] = item["canonical_end"]
            mapping[-1]["raw_end"] = item["raw_end"]
        else:
            mapping.append(item)
        parts.append(normalized)
        raw_start += len(line)
        canonical_start += len(normalized)
    return "".join(parts), mapping


def raw_span(mapping: list[dict], start: int, end: int) -> tuple[int, int]:
    """Return a raw range covering a nonempty canonical span."""
    if start < 0 or end <= start or not mapping or end > mapping[-1]["canonical_end"]:
        raise ValueError("invalid canonical span")
    ranges = []
    for item in mapping:
        left, right = max(start, item["canonical_start"]), min(end, item["canonical_end"])
        if left >= right:
            continue
        if item["operation"] == "identity":
            ranges.append((item["raw_start"] + left - item["canonical_start"],
                           item["raw_start"] + right - item["canonical_start"]))
        else:
            ranges.append((item["raw_start"], item["raw_end"]))
    return ranges[0][0], ranges[-1][1]


def parse_legal_units(text: str) -> tuple[list[dict], list[str]]:
    """Extract explicit article/clause/point labels and flag ambiguous structure."""
    boundaries = []
    chapter = section = None
    events = sorted([(match.start(), kind, match) for kind, pattern in
                     (("chapter", CHAPTER), ("section", SECTION), ("article", ARTICLE))
                     for match in pattern.finditer(text)], key=lambda entry: entry[0])
    for start, kind, match in events:
        if kind == "chapter":
            heading = " ".join(match.group().split())
            chapter, section = heading, None
            boundaries.append({"kind": "heading", "start": start})
        elif kind == "section":
            heading = " ".join(match.group().split())
            section = heading
            boundaries.append({"kind": "heading", "start": start})
        else:
            line_end = text.find("\n", match.end())
            heading = " ".join(text[start:line_end if line_end >= 0 else len(text)].split())
            boundaries.append({"kind": "article", "start": start, "label_end": match.end(), "label": match.group(1),
                               "heading": heading, "path": [h for h in (chapter, section, heading) if h]})
    articles = [b for b in boundaries if b["kind"] == "article"]
    issues = set()
    if not articles:
        issues.add("NO_ARTICLE_STRUCTURE")
    if any(count > 1 for count in Counter(a["label"] for a in articles).values()):
        issues.add("DUPLICATE_ARTICLE_LABEL")
    units = []
    content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()

    def make_unit(kind, start, end, article, clause=None, point=None, parent=None, header=None):
        identity = f"{content_hash}:{kind}:{start}:{end}"
        return {"unit_id": hashlib.sha256(identity.encode()).hexdigest(), "kind": kind,
                "article_label": article["label"], "clause_label": clause, "point_label": point,
                "heading_path": article["path"], "parent_id": parent, "start": start, "end": end,
                "text": text[start:end], "context_header": header or article["heading"],
                "parse_confidence": "explicit_labels"}

    for index, boundary in enumerate(boundaries):
        if boundary["kind"] != "article":
            continue
        end = boundaries[index + 1]["start"] if index + 1 < len(boundaries) else len(text)
        article = make_unit("article", boundary["start"], end, boundary)
        unit_start = len(units)
        local_issues = set()
        if sum(a["label"] == boundary["label"] for a in articles) > 1:
            local_issues.add("DUPLICATE_ARTICLE_LABEL")
        units.append(article)
        clauses = list(CLAUSE.finditer(text, boundary["label_end"], end))
        if len({c.group(1) for c in clauses}) != len(clauses):
            local_issues.add("DUPLICATE_CLAUSE_LABEL")
        if any(int(c.group(1)) <= int(previous.group(1)) for previous, c in zip(clauses, clauses[1:])):
            local_issues.add("NON_MONOTONIC_CLAUSES")
        header = text[boundary["start"]:clauses[0].start()].strip() if clauses else boundary["heading"]
        for clause_index, match in enumerate(clauses):
            stop = clauses[clause_index + 1].start() if clause_index + 1 < len(clauses) else end
            clause = make_unit("clause", match.start(), stop, boundary, match.group(1),
                               parent=article["unit_id"], header=header)
            units.append(clause)
            points = list(POINT.finditer(text, match.end(), stop))
            if len({p.group(1) for p in points}) != len(points):
                local_issues.add("DUPLICATE_POINT_LABEL")
            for point_index, point in enumerate(points):
                point_end = points[point_index + 1].start() if point_index + 1 < len(points) else stop
                units.append(make_unit("point", point.start(), point_end, boundary, match.group(1),
                                       point.group(1), clause["unit_id"], header))
        issues.update(local_issues)
        for unit in units[unit_start:]:
            unit["parse_issues"] = sorted(local_issues)
    return units, sorted(issues)


def retrieval_units(units: list[dict]) -> list[dict]:
    """Keep clauses whole, including points and exceptions, or the whole article."""
    parents_with_clauses = {u["parent_id"] for u in units if u["kind"] == "clause"}
    return [u for u in units if u["kind"] == "clause" or
            (u["kind"] == "article" and u["unit_id"] not in parents_with_clauses)]
