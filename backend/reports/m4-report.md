# M4 implementation and verification report

Date: 2026-10-25. Branch: `feat/m4-rag-api`. Source baseline: `aba39aa` (M3).

## Delivered behavior

- Migration 0004: owner conversations, durable message turns, citations with
  snapshot membership FK, retrieval traces, sequence/idempotency constraints.
- User authentication separated from admin authorization; hidden-password
  `create-user` CLI. Other users/admins cannot view another owner's history/sources.
- Keyword/vector/hybrid search, RRF k=60, topic filtering before limit, profile
  identity checks and pinned serving/corpus/profile IDs. E5 embedding identity
  is unchanged; OpenAI embeddings were not introduced.
- Bounded history rewrite, explicit temporal policy and atomic article groups
  in evidence budget. Unverified/current/conflicting dates ask for clarification.
- OpenAI Responses adapter with strict Pydantic-derived schema, bounded input,
  timeout/retry/deadline, refusal/incomplete/error handling and `store=False`.
  Model is explicitly configured; unknown tokenizer fails closed.
- Every released legal claim has context/snapshot sources; quotes/spans/metadata
  come from DB. Invalid draft gets at most one repair. No partial invalid draft
  or provider failure becomes a legal answer.
- Chat/history/citation/trace API, owner pagination, key replay/conflict,
  conversation fencing and expired-turn recovery. Sources use the original
  serving snapshot after later activation.
- FastAPI-generated OpenAPI, local Postman M4 collection, locally authored OpenAI
  simulation, managed acceptance runner, M4 Compose override and setup guide.

## Verification evidence

Results here describe checks actually run; final counts are updated after review.

| Layer | Result |
|---|---|
| Backend full suite including real E5 model test | 84 passed, 12 opt-in tests deselected (before final review) |
| Temporal regression for dashed/partial dates and relative year | 4 passed |
| OpenAI upstream HTTP simulation | 11 passed; backend and SDK ran for real |
| M4 Postman with real HTTP API, real E5 and simulated OpenAI | 21 requests, 34 assertions, 0 failed; 9 upstream request events |
| M3 Postman admin regression | Passed via existing guarded runner |
| Fresh migration and repeated upgrade | Passed on disposable verification DB |
| Data/evaluation tests | 27 + 18 passed; frozen dataset validator valid (72 total, seed subset 12) |
| Ruff | Passed |
| Docker image | Built successfully; clean Compose verification pending at draft time |
| Live OpenAI | Not run successfully: no API key/model in session environment |

The initial baseline verification was affected by an old test process started
while Docker was unavailable; it later overlapped the DB-resetting suite and
caused FK errors. The old process was stopped and sequential reruns passed.
No source-data changes were used to resolve the environment issue.

## Scope, decisions and limits

Implementation stayed in the existing checkout on a new feature branch, reusing
the recorded M3 branch workflow and caches; the user's untracked workbook was
preserved. No new worktree, workspace publish, push, merge or deployment occurred.
The explicit OpenAI model configuration avoids an assumed account capability or
deprecated default. Configure credentials/model locally before live acceptance.

The corpus still has 10 reviewed chunks from one document and verifies only
2026-02-12. Existing assistant source review is preserved; no legal review was
upgraded to independent human review. No new Recall/MRR, legal accuracy, citation
semantic precision or model injection-resistance result is claimed. Simulation
echoes fixture evidence and cannot validate legal reasoning. The 12 dev seed
questions still need live/manual answer review; frozen test was not used to tune.

Strict schema/citation checks prove source existence, membership, canonical quote
and offsets; they do not prove entailment. Rewrite guards cover explicit dates,
numbers and selected conditions; free-form semantic preservation still needs
manual evaluation. Unsupported natural-language time forms can require further
clarification handling as new cases are found.

Provider calls are outside DB transactions. One active turn per conversation is
bounded by deadline/lease and fenced at finalization. A process crash can leave
an upstream call made without a saved answer; exactly-once upstream calls are
not guaranteed. Source/DB role protections retain the M3 operational trust model.

M5 owns UI and refresh/logout. M6 owns frozen-test metrics and systematic
grounding/abstention review. Public production rate limiting/TLS and CI packaging
remain later work. M4 code is implemented; final live-provider acceptance is open.
