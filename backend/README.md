# Backend M3/M4

FastAPI + PostgreSQL/pgvector, admin authentication, validated M1 imports, resumable
DB jobs, local E5 embeddings, immutable serving snapshots and atomic activation.
M4 adds keyword/vector/hybrid search, OpenAI generation with checked citations,
and owner-scoped chat/history/source/trace endpoints. See the M4 section below.

## Local setup (PowerShell)

Prerequisites: Python 3.10+, uv, Docker with a running Linux engine, and enough
disk space for the DB, Python packages and 470 MB model weights. The initial Docker
build needs additional temporary space on the drive hosting Docker's disk image.

From the repository root:

```powershell
uv sync --project backend --extra dev --frozen
Copy-Item backend/.env.example backend/.env
```

Fill `POSTGRES_PASSWORD`, `RUNTIME_PASSWORD`, `JWT_SECRET` locally with distinct
random hex values (at least 32 characters). `.env` and runtime data are ignored.
No admin is created automatically. Do not put credentials into tracked files.

For Docker-only runtime:

```powershell
docker compose --env-file backend/.env -f infra/compose.m3.yml up -d --build
docker compose --env-file backend/.env -f infra/compose.m3.yml exec api python -m app.cli create-admin --username admin
```

The migrate service uses the owner role and explicitly provisions `vietlaw_app`
with DML privileges only. API and worker use that runtime role. PostgreSQL binds
to localhost port 55432; API binds to localhost port 8000. Migration is forward-only
to preserve source history. Running upgrade again is safe. Do not use `down -v`
unless you intend to discard the local database and release/model volumes.

## Import, embedding and activation

The input is the committed reviewed M1 corpus, not the ZIP or a client-supplied
server path. Copy it into the container, register it, then use the returned ID:

```powershell
docker compose --env-file backend/.env -f infra/compose.m3.yml cp data/manifests/m1/labor-corpus-v1.json api:/tmp/m1.json
docker compose --env-file backend/.env -f infra/compose.m3.yml exec api python -m app.cli register-release /tmp/m1.json
docker compose --env-file backend/.env -f infra/compose.m3.yml exec worker python -m app.cli prepare-model
docker compose --env-file backend/.env -f infra/compose.m3.yml exec worker python -m app.cli register-profile
```

Model preparation needs internet once; runtime encoding uses the pinned local
cache and never downloads during API startup. The model/profile is multilingual
E5 small, revision `614241f622f53c4eeff9890bdc4f31cfecc418b3`, dimension 384,
L2 normalization, 512-token cap including prefix/special tokens. Long inputs are
quarantined instead of silently truncated. There is no production mock encoder.

Open `http://127.0.0.1:8000/docs`. Use `POST /api/v1/auth/token` with JSON
username/password; Authorize with the returned Bearer token. Tokens last 30 minutes.
All admin endpoints require a live enabled admin account.

1. `POST /api/v1/admin/imports` with `{"release_id":"<registered corpus ID>"}`.
2. Poll the returned `Location` until `state=succeeded`. Repeat imports return
   the same job. A 202 response only confirms enqueueing.
3. `POST /api/v1/admin/embedding-jobs` with `corpus_snapshot_id` and
   `embedding_profile_id`; poll until all 10 items succeed.
4. `POST /api/v1/admin/serving-snapshots` with those two IDs creates the ready
   serving snapshot. Record its `id`.
5. `POST /api/v1/admin/serving-snapshots/<id>/review` with
   `{"decision":"approve","note":"<operational review note>"}`.
6. `POST /api/v1/admin/serving-snapshots/<id>/activate` with
   `{"expected_active_id":null}` for first activation, or the current serving ID
   when replacing it. A stale expectation returns 409; inspect the active state
   before retrying rather than blindly overwriting another admin's activation.

Use `/jobs/<id>/retry` only for failed jobs after resolving the cause. Successful
items survive retry; malformed releases need a corrected new release rather than
editing a registered file. Rejected serving snapshots are terminal; changing
source/profile content creates a new identity for review.

## Identity and trust

The corpus ID remains the M1 manifest hash, so frozen M2 gold remains valid.
Serving IDs additionally bind embedding configuration and vector/input hashes.
Source text, units, vectors and snapshot membership are append-only in the DB;
changing a default pointer never changes old snapshot contents.

Registration validates internal integrity and preserves the existing source
review; it does not perform a fresh legal review. M1's reviewer remains Codex.
The admin's operational review is recorded separately in `review_events`.
This corpus verifies only `2026-02-12`; a null legal end date is not evidence
that its coverage extends to today. `pin_active()` and `read_chunks()` in
`app.domain.serving_reader` provide M4's pinned data access. Candidate primitives
in `app.db.search` enforce the same serving/profile/date membership.

## Verification

The helper creates a dedicated container on **55433**, separate from runtime DB
55432, with random credentials stored only in ignored `.runtime/verification.json`.
It does not remove any existing Docker volume. Do not run multiple test suites
concurrently against this shared verification database.

```powershell
backend/.venv/Scripts/python backend/scripts/verification_db.py
backend/.venv/Scripts/python backend/scripts/migrate_verification.py
backend/.venv/Scripts/python -m app.cli prepare-model
backend/.venv/Scripts/python -m pytest backend/tests -q
backend/.venv/Scripts/ruff check backend/app backend/tests backend/scripts
backend/.venv/Scripts/python -m evaluation.dataset validate
backend/.venv/Scripts/python -m unittest discover -s evaluation/tests -q
backend/.venv/Scripts/python -m unittest discover -s data/tests -q
```

For native model preparation/export, set `JWT_SECRET` in the current shell first;
`Settings` intentionally does not auto-load `.env`. The API also needs the runtime
`DATABASE_URL` and a shared `RELEASE_DIR` when run natively. Test fixtures load their
isolated config themselves. A missing DB/model fails the corresponding tests;
the suite does not silently substitute SQLite or mock embeddings for model smoke.

Model-only: `python -m pytest backend/tests/test_embedding_smoke.py -m model -q`.
Fast suite: `python -m pytest backend/tests -m "not model" -q`.

OpenAPI is generated from the app:

```powershell
backend/.venv/Scripts/python backend/scripts/export_openapi.py
backend/.venv/Scripts/python backend/scripts/build_collection.py
postman collection lint backend/contracts/postman/m3
backend/.venv/Scripts/python backend/scripts/run_postman.py
```

After building the image, `python backend/scripts/verify_compose.py` checks a new
isolated Compose project on API port 18004 / DB port 55434 using the already
prepared native model cache as a read-only mount. It removes only the test
project and volumes created by that invocation.

The Postman runner **resets only the dedicated verification DB**, prepares real
embeddings, starts an API on localhost 18003, runs 15 local requests with assertions,
then stops its own API and removes its temporary credential environment. Reports
stay under ignored `.runtime`; `--no-report-events` disables workspace reporting.
Do not run it concurrently with pytest. No workspace binding/publishing is needed.

M3 does not claim retrieval accuracy or legal answer quality. Recall/MRR,
generation and UI acceptance are later milestones. The local admin API is not
configured for public deployment (TLS, rate limiting and deployment policy remain
deployment work).

## M4 RAG API

M4 keeps M3's E5 embedding profile and source identities. OpenAI is used for
bounded conversational rewrite and structured claim generation through the
Responses API. No answer is released until its source IDs, snapshot membership,
canonical offsets and DB quotes pass validation. This checks source structure;
it does not establish that a claim is a correct legal interpretation.

The corpus verifies only **2026-02-12**. A question without a date uses that
scope explicitly; present-day/unverified or conflicting dates ask for clarification.
An empty retrieval context does not call generation. Infrastructure/provider errors
return the M3 error envelope and request ID, never a legal answer.

### Configuration and startup

Fill `OPENAI_API_KEY` and `OPENAI_MODEL` in the ignored local env file. The model
must support Responses and strict structured outputs and have a tokenizer known
to the pinned tiktoken version. `OPENAI_REWRITE_MODEL` is optional. No model is
selected automatically. `OPENAI_BASE_URL` defaults to OpenAI; change it only for
an intentional gateway or local simulation. API keys belong only in environment
configuration. Account/model access has to be verified with a live smoke.

Upgrade the same existing Compose project, preserving its project name/volumes:

```powershell
docker compose --env-file backend/.env -f infra/compose.m3.yml -f infra/compose.m4.yml up -d --build
```

The M4 override mounts the prepared native model cache read-only into the API.
Prepare it with the M3 CLI first. The worker retains its existing model volume.
Migration 0004 adds chat tables; migrations and source snapshots are forward-only.
Native `Settings` still does not auto-load `.env`: set variables in the process
before starting uvicorn. Create a regular local chat user with a hidden password:

```powershell
backend/.venv/Scripts/python -m app.cli create-user --username demo
```

### HTTP consumer contract

Use `POST /api/v1/auth/token` to obtain a 30-minute access token. Both user/admin
roles may chat, while admin endpoints remain admin-only. Every conversation,
message, citation and trace is private to its owner, including against other
admins. Refresh/logout and frontend flows remain M5 work.

- `POST /api/v1/search`: `query`, `mode` (`keyword`, `vector`, `hybrid`), required
  `as_of_date`, optional `topic`, `top_k` (1-10, default 5). Returns a candidate
  array with pinned corpus/serving/profile IDs, branch ranks and provenance.
- `POST /api/v1/conversations`: creates a conversation owned by the token user.
- `GET /api/v1/conversations?limit=20&cursor=...`: owner list, newest first.
- `POST /api/v1/conversations/{id}/messages`: body `question`, optional `mode`,
  `as_of_date`, `topic`. Required ASCII `Idempotency-Key` header (1-128 characters).
- `GET /api/v1/conversations/{id}/messages?limit=20&cursor=...`: chronological
  messages, including failed turns. Lists return `items` and nullable `next_cursor`.
- `GET /api/v1/messages/{id}/citations/{citation_id}`: original canonical quote,
  `[start,end)` Unicode offsets, version, reviewed source metadata and serving ID.
- `GET /api/v1/messages/{id}/trace`: owner-only ranking, context IDs, token usage,
  prompt/model versions and error codes. Trace is not a public operational log.

Chat results have `status`, `answer`, `claims`, `citations`, conversation/message/
request IDs, `corpus_snapshot_id`, `serving_snapshot_id`, `embedding_profile_id`,
`as_of_date`, and `scope_notice`. `snapshot_id` aliases the serving ID; M2 gold
continues to use the separate corpus ID. Status is `answered`,
`insufficient_evidence`, `out_of_scope`, or `needs_clarification`. Only `answered`
has claims/citations. A structurally valid citation alone does not prove relevance.

HTTP errors: 401 invalid token, 403 admin required, 404 absent/non-owner resource,
409 busy conversation/key conflict, 422 invalid input/date, 502 invalid/refused/
incomplete provider output or citation repair failure, 503 unavailable corpus/model/
provider, 504 timeout. Failed turns retain the code and have no answer/citations.
A repeated key with identical payload replays the completed turn, including the
original request ID; different payload is 409. Processing keys return 409; failed
keys replay the stored error. Retry a failed turn with a new key. The response's
`X-Request-ID` identifies the current HTTP exchange.

A request pins the active serving snapshot once; activation during generation
cannot change its sources. New turns can use a new snapshot; historical citation
URLs keep the old membership. One turn per conversation is processed at once,
with a 90-second fenced lease and 60-second pipeline deadline. Process interruption
can cause an upstream call to have happened without a saved answer; exactly-once
OpenAI calls are not promised.

### Verification and upstream simulation

Default pytest excludes `live` and `simulation` markers. Unit/DB tests use the
isolated verification PostgreSQL; run DB-resetting suites/runners sequentially.
Prepare migration head with the M3 helpers, then:

```powershell
backend/.venv/Scripts/python -m pytest backend/tests -m 'not live and not simulation' -q
backend/.venv/Scripts/python backend/scripts/export_openapi.py
backend/.venv/Scripts/python backend/scripts/build_m4_collection.py
postman collection lint backend/contracts/postman/m4
backend/.venv/Scripts/python backend/scripts/run_m4_postman.py
```

The M4 runner first executes M3 acceptance on its guarded test database, then
runs a real API with real E5 and a locally managed Postman OpenAI simulation.
It checks 21 requests, history/source ownership, idempotency and provider errors;
it never uses a real OpenAI key or records run events. Logs are ignored under
`backend/.runtime/`; its temporary credential file is removed on exit.

To exercise upstream faults over real HTTP separately, use two terminals:

```powershell
postman simulation run postman/simulations/m4-openai.sim.yaml --port 4904 --output ndjson --no-history
```

```powershell
$env:M4_SIMULATION_URL = 'http://127.0.0.1:4904/openai/v1'
backend/.venv/Scripts/python -m pytest backend/tests/test_m4_flow.py -m simulation -q
```

The mock is a locally authored subset of the official Responses wire contract,
not an OpenAI-owned mock. Its fixture markers exercise success, 401, 429, 500,
timeout, refusal, incomplete output, invalid JSON, fake source, abstention and
out-of-scope status. It does not simulate legal reasoning or account/model access.
See `postman/simulations/m4-openai.context.md` for reproduction and limitations.

For a real OpenAI smoke, configure key/model in the process and explicitly run:

```powershell
backend/.venv/Scripts/python -m pytest backend/tests/test_generation_live.py -m live -q -rs
```

Missing credentials visibly skip live acceptance. The opt-in test makes three
small calls for grounding, abstention and injection; provider usage is available
in traces. Do not treat simulated/unit success as live or legal-quality evidence.
Final retrieval metrics on frozen test remain M6; only dev/seed may guide changes.
