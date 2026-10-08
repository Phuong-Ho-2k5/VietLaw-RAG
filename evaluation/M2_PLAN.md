# M2 implementation plan

Goal: publish a reviewed evaluation set for the M1 corpus, with 12 seed and
at least 60 dev/test questions, legal gold, abstention cases and frozen test.
Spec: `docs/DATASET_REBUILD.md` (Dataset đánh giá) and
`docs/PROJECT_PLAN.md` (M2); implementation follows the existing approved scope.
Tech stack: Python 3.10+, standard library, unittest, UTF-8 JSONL.

## Constraints and decisions

- Pin the immutable M1 snapshot and its explicit verified date, 2026-02-12.
- Author 72 questions: 48 answer, 12 insufficient evidence, 6 out of scope,
  6 unsupported/unspecified date. Reviewer is explicitly Codex, not a human.
- Group by article and semantic family; no article or family crosses splits.
  Dev articles: 13, 24, 34; test articles: 26, 90, 105.
- Seed is a 12-question subset of dev only. It is not a third evaluation split.
- Abstention gold is empty. Its evidence records the scope limitation, not a
  positive legal citation. Do not infer absent law from absent corpus content.
- Freeze semantic hashes of all inputs, corpus, mapping and review information.
  An existing freeze cannot be overwritten; changes require a new release path.
- Work in the current checkout; preserve the user's untracked workbook.

## Tasks

1. Validator and release tooling: write failing tests for correct references,
   empty abstention gold, temporal restrictions, cross-split article/family
   leakage, Unicode duplicates, invalid schema and corrupted corpus. Implement
   `validate_dataset(dev, test, seed, corpus) -> dict` and
   `freeze_dataset(directory, corpus_path) -> dict`, then run unit tests.
2. Curate 72 rows and seed, each with question, split, family, category,
   expected behavior/answer, reviewer, date, evidence and gold references.
   Recheck all selected articles against official PDF pages 7, 11, 14, 35, 40.
   Run validation and freeze to `evaluation/data/split-manifest.json`.
3. Write usage and acceptance report; verify frozen hashes, mutation rejection,
   Windows CLI behavior, all data/M2 tests and independent code review.

## Review focus

Wrong dates, legal label mismatch, absent evidence, semantic leakage and
silent replacement of an existing frozen test must fail closed. Freeze is an
integrity control, not filesystem access control or a claim of blind evaluation.

## Progress

- Baseline: 27 data tests pass. Official metadata reopened; PDF pages reviewed.
- Task 1: validator tests RED (missing module, then hash separator mismatch)
  to GREEN. Corpus hash now uses exactly the canonical JSON encoding of M1.
- Task 2: 72 curated cases and 12 dev-only seed rows validated; freeze created.
- Additional malformed-enum regression: list-valued category/topic RED to
  GREEN with explicit type checks; content/key order/CRLF regression covered.
- Ruling: keep approved scope from project design; execute in place and pin
  current M1 date. Cost if scope expands: new corpus/dataset release required.
- Ruling: article/family split with dev-only seed trades topic balance for
  leakage prevention on a one-document corpus. Cost: limited tuning coverage;
  report topic-specific metrics and expand corpus before general conclusions.
- Task 3: documentation, frozen verification and full test checks complete:
  M2 17/17, M0/M1 27/27; `python -m evaluation.dataset validate` accepts
  36 dev + 36 test + 12 dev-subset seed. Freeze identity unchanged.
- Final review: independent reviewer checked all 72 records and code; no
  Critical or Important findings. Enum ValueError issue was already fixed
  while review ran; final parent-run 17/17 confirms that regression.
- Follow-up fix: malformed seed IDs now raise ValueError before dictionary
  lookup. Regression reproduced TypeError for list/dict IDs before the fix;
  verifies rejection of list, dict, null, numeric, boolean and empty IDs.
