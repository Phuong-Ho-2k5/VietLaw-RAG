# Backend M3

FastAPI + PostgreSQL/pgvector, admin authentication, validated M1 imports, resumable
DB jobs, local E5 embeddings, immutable serving snapshots and atomic activation.
Chat and public search endpoints belong to M4.

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
