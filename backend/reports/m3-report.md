# M3 acceptance report

Date: 2026-10-20. Branch: `feat/m3-platform-ingestion`.
Scope: `backend/M3_PLAN.md`, approved for implementation by the user on 2026-10-20.

## Delivered

- FastAPI runtime, safe error envelope/request IDs, health and migration readiness.
- Locked Python dependencies, CPU Torch source, digest-pinned PostgreSQL/pgvector,
  Python and uv images; Docker Compose for DB, migration, API and worker.
- Argon2 admin credentials, hidden-prompt creation CLI, 30-minute JWTs validating
  issuer/audience/expiry/signature and current account/role status.
- Relational raw/document/version/unit/chunk provenance, immutable corpus and
  vector rows, protected snapshot membership and append-only review events.
- M1 registration/validation, idempotent import and embedding jobs, per-item
  checkpoints, transient retries, independent lease heartbeat and fencing.
- Local multilingual E5 small embeddings, float32 normalized 384-dimensional
  vectors, bounded tokenizer input and no silent truncation or mock production mode.
- Serving manifest hashes, operational approve/reject, atomic activation with
  expected-active precondition, rollback and stable historical reads.
- Exact keyword/vector candidate primitives restricted to the pinned serving
  snapshot/profile and explicitly verified date. No public search/chat API yet.
- Generated OpenAPI and 15 Git-native Postman requests, plus native/Compose
  verification helpers and a clean-checkout README.

## Evidence actually run

| Check | Result |
|---|---|
| `python -m pytest backend/tests -q` | **52 passed**, including real local model smoke |
| `python -m unittest discover -s evaluation/tests -q` | **18 passed** |
| `python -m unittest discover -s data/tests -q` | **27 passed** |
| `python -m evaluation.dataset validate` | Valid: 36 dev, 36 test, 12 dev-subset seed; frozen identity unchanged |
| Ruff check/format, Git whitespace check | Passed |
| `postman collection lint backend/contracts/postman/m3` | 15 requests, 0 errors, 0 warnings |
| `python backend/scripts/run_postman.py` | Real HTTP API: **15 requests / 30 assertions passed**, event reporting disabled |
| `python backend/scripts/verify_fresh_migration.py` | Frozen migrations on a new DB and repeat upgrade both passed |
| `docker build -f backend/Dockerfile -t vietlaw-m3:local .` | Passed with locked CPU dependencies and excluded secrets/cache/raw data |
| `python backend/scripts/verify_compose.py` | New isolated Compose project: DB/API/worker, real embedding, review, activation and pinned 10-chunk read passed; only that invocation's test volumes removed |

Unit tests use a test-only encoder where they exercise concurrency/error behavior;
the model smoke, Postman preparation and clean Compose smoke used the real pinned
E5 model. DB tests use actual PostgreSQL/pgvector and a DML-only runtime role,
not SQLite. No cloud workspace was created, bound or published.

## Corpus and model identity

- M1 corpus: `6ebc3836a333f2239e524d6016c0bdf7c11abe6751c4a1b9cd01185e74fb84b7`.
- Frozen M2: `e959ebb7769d9be594d0fcc5bfc5f702084e4642bf59b0599ba91f26a5e84b78`.
- Model: `intfloat/multilingual-e5-small`, revision
  `614241f622f53c4eeff9890bdc4f31cfecc418b3`, 384 dimensions, L2, 512 tokens.
- Template: `passage: {context_header}\n{text}`; queries use `query: {question}`.
- Profile: `a7c912b27ce3eda2abfb42cbb4d74d8fadf26cb2b5460ab256fb49ca7771fab7`.
- Corpus/chunk/version IDs and frozen M2 inputs were not rewritten. Serving IDs
  additionally bind the exact stored input/vector hashes; tiny platform-dependent
  float differences can legitimately yield different serving IDs.

## Independent review and fixes

A separate reviewer inspected the implementation against the plan and source
specification. Three Important findings were reproduced and fixed:

1. Jointly modified chunk/unit labels and raw spans could pass a rehashed manifest.
   The adapter now reconstructs normalization, raw mapping, parser structure and
   local/global unit IDs using a pinned M1 parser. Regression cases were observed
   failing before the fix, then passing. The original M1 source files are unchanged.
2. Chunk evidence could contradict the historical review. Evidence and topic tags
   now match the reviewed local-unit mapping; document-level source evidence also
   matches its historical review. Rehashed forged evidence/URL cases fail closed.
3. Overlapping corpus embedding jobs could race on the same vector identity.
   A barrier-controlled two-worker regression reproduced the unique violation;
   conflict-safe insertion and stored identity/hash verification now let both jobs
   finish without overwriting vectors.

The reviewer also identified a test coverage gap: the original conflict test
failed before mutation and did not prove rollback after a write. An additional
test injects an error after pointer/seal updates and proves both are rolled back.
No review findings remain deferred. Fixes were verified by regression tests and
the full suite; there was no second independent review pass.

## Decisions and their limits

- Used the user-requested new branch in the existing checkout, preserving the
  untracked workbook. This avoids changing the user's workspace location; normal
  branch isolation applies rather than a separate worktree directory.
- Consolidated SQLAlchemy Core metadata in `db/models/__init__.py`; the initial
  migration uses frozen SQL rather than importing future application metadata.
  Source/index rows are immutable from insertion, stricter than waiting for seal;
  corrections therefore require new content identities.
- Process embeddings per chunk, with a batch-capable provider, for precise recovery
  on this 10-chunk corpus. Throughput optimization is deferred; large corpora may
  need batching without weakening item checkpoints.
- The M1 parser is vendored with its source hash into the backend adapter to keep
  Docker independent of raw-data tools and reproduce historical structure. A new
  parser contract needs an explicit adapter/version change; existing M1 files stay
  untouched.
- Only the selected local E5 profile is supported. Alternative models/dimensions
  require an explicit schema/profile migration and fresh serving release.
- Registration checks internal consistency and retains historical review; it does
  not re-verify legal substance against the web. Operational approval remains
  separate from Codex's source review. Legal validity depends on that prior review.
- API credentials and the runtime DB role are trusted operational boundaries.
  Guards prevent mutation of sealed/source records; they do not claim to defend
  against an attacker possessing privileged database/DDL access.

## Environment incident and remaining scope

During Docker verification, the host C drive filled and Docker's filesystem became
read-only. Only Torch cache entries downloaded by this task were moved to ignored
scratch storage on D; only this task's generated Docker image/build layer was
removed before rebuilding without uv cache. Docker/WSL was restarted after freeing
space, then DB tests, actual HTTP checks and clean Compose flow passed. C still has
limited free space (about 0.9 GB at verification); free additional space before
large unrelated builds. No existing user Docker volume was deleted.

This is the M3 local foundation, not a production release. Public auth flows,
rate limiting/TLS policy, chat/generation, UI, retrieval-quality evaluation and full
deployment/CI remain later milestones. The corpus contains 10 reviewed chunks from
one document and verifies only 2026-02-12. No Recall/MRR or answer-quality result is
claimed by this milestone.
