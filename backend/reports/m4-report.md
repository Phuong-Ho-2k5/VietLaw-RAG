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

Results here describe checks actually run, including the post-review, post-recovery
full backend suite. The interrupted runs are not counted as successful checks.

| Layer | Result |
|---|---|
| Backend full suite including real E5 model test | 92 passed, 12 opt-in tests deselected after review fixes and Docker recovery |
| Temporal regression for dashed/partial dates and relative year | 4 passed |
| OpenAI upstream HTTP simulation | 11 passed; backend and SDK ran for real |
| M4 Postman with real HTTP API, real E5 and simulated OpenAI | 21 requests, 34 assertions, 0 failed; 9 upstream request events |
| M3 Postman admin regression | Passed via existing guarded runner |
| Fresh migration and repeated upgrade | Passed on disposable verification DB |
| Data/evaluation tests | 27 + 18 passed; frozen dataset validator valid (72 total, seed subset 12) |
| Ruff | Passed |
| Docker image / clean Compose | Final reviewed source packaged; clean API/DB/worker, real E5 API query and date-clarification chat passed after fixes |
| Live OpenAI | Explicit smoke skipped: no API key/model in process environment or ignored env file |

The initial baseline verification was affected by an old test process started
while Docker was unavailable; it later overlapped the DB-resetting suite and
caused FK errors. The old process was stopped and sequential reruns passed.
No source-data changes were used to resolve the environment issue.

The first Compose M4 search exceeded the smoke client's former 10-second timeout
while E5 loaded cold in the API container. A bounded 90-second verification-client
timeout allowed the complete clean Compose check to pass; production provider
timeout/deadline settings were not enlarged.

During the final image rebuild, C ran out of space and Docker disconnected. That
interrupted the concurrent native DB suite; its partial failures are infrastructure
results, not a passing final run. Recovery preserves all volumes. Two pre-existing
uv Torch cache directories were relocated from
`C:/Users/Owner/AppData/Local/uv/cache/archive-v0/` to
`backend/.runtime/relocated-uv-cache/`, keeping junctions at the original paths.
Entries: `CFvzSbGdw8nnK05o5n6Vz` and `P9BbetjMe2fCjkQsbDDT-`; about 0.9 GB of
host space was recovered without deleting their contents. Preserve that target
directory while the junctions are in use. Docker Desktop/WSL were restarted after
checking the other distributions were stopped; existing containers remained
present, and no project volumes were deleted. Post-recovery backend and Compose
checks passed. The final code image was layered over the already verified full
dependency image to avoid reinstalling large dependencies on C; the final full
Dockerfile rebuild was interrupted by host disk pressure. The checked-in Dockerfile
and frozen dependency lock remain the clean-build recipe when enough space is available.

## Independent review and regressions

One independent whole-branch reviewer examined the implementation after its
initial commit. All findings were reproduced before fixes; the targeted regression
suite then passed 24 tests. No second independent review pass was performed.

- Persist expired-turn recovery before returning an old key's error; replay can
  no longer roll the interrupted state back to processing.
- Store the submitted question in the same reservation transaction as its user
  row, processing assistant and conversation lease. This required an additive
  `question` argument to the plan's repository interface; the separate write was removed.
- Reject fixed/indefinite contract-type changes and dropped recognized negation,
  including `chưa`; overlapping substring checks were insufficient.
- Preserve clarification status with a safe question when the model's reason is
  blank; temporal clarification independently takes precedence.
- Malformed cursor fields now return the documented 422 rather than an internal
  AttributeError/500. Regraded as a required input-contract fix.
- Failed provider calls now retain operation, requested/actual model, available
  usage, retries, outcome and latency without raw provider error text. Regraded
  as required evidence for the trace contract, rather than optional observability polish.

There are no deferred reviewer findings. Behaviors set aside by the reviewer were
resolved as follows: live reasoning/entailment/injection claims remain unverified
without credentials; exhaustive natural-language time interpretation remains a
documented evaluation limit; blocking E5/DB operations are not forcibly cancelled
(late results are rejected/fenced, but may occupy a worker beyond the deadline);
production rate limiting/TLS and refresh/logout stay in their explicitly deferred
milestones. These are scope/operating limits, not claims of verified behavior.

## Scope, decisions and limits

Implementation stayed in the existing checkout on a new feature branch, reusing
the recorded M3 branch workflow and caches; the user's untracked workbook was
preserved. No new worktree, workspace publish, push, merge or deployment occurred.
The explicit OpenAI model configuration avoids an assumed account capability or
deprecated default. Configure credentials/model locally before live acceptance.
Task tracking used a Windows-native ledger instead of the skill's bash helper
scripts; test and review evidence is retained in this report and Git history.
Interdependent T00-T04 changes were consolidated in one implementation commit,
followed by the regression fix commit, rather than separate task commits.

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
