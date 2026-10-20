# M3 — Kế hoạch nền tảng backend và ingestion

> **For agentic workers:** Use `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox syntax for tracking. Tài liệu này là đề xuất triển khai, chưa phải báo cáo hoàn thành.

**Goal:** Nhập corpus M1 vào PostgreSQL, tạo embedding thật, duyệt và kích hoạt một bản phục vụ bất biến qua API được bảo vệ, sẵn sàng cho retrieval ở M4.

**Architecture:** FastAPI và worker là hai process dùng chung PostgreSQL/pgvector. Worker nhận job từ DB, không cần Redis/Celery. Giữ nguyên định danh corpus/chunk M1; lưu cấu hình embedding và bản phục vụ riêng để không thay đổi gold M2.

**Tech Stack:** Python 3.10+, FastAPI, Pydantic Settings, SQLAlchemy 2, Alembic, psycopg 3, PostgreSQL/pgvector, Sentence Transformers, Argon2, JWT, pytest. Khóa phiên bản dependency và Docker image sau khi kiểm tra tương thích ở T01.

**Spec:** `docs/PROJECT_PLAN.md` (M3), `docs/RAG_ARCHITECTURE.md`, `docs/DATASET_REBUILD.md`; đối chiếu triển khai thực tế trong `data/m1.py`, `evaluation/dataset.py`, `data/manifests/m1/labor-corpus-v1.json`. Các quyết định bổ sung bên dưới là đề xuất cần được rà soát trước khi viết code.

**Location:** Đặt plan tại `backend/M3_PLAN.md`, cùng cách tổ chức milestone như `evaluation/M2_PLAN.md`; thư mục `/docs` hiện bị Git ignore.

## Phạm vi và đầu vào

- M3-T01: runtime FastAPI, DB, migration và health.
- M3-T02: schema, admin auth, nhập corpus, job có retry và tiếp tục sau lỗi.
- M3-T03: embedding worker, vector storage và full-text index.
- M3-T04: review, bản phục vụ bất biến, activate nguyên tử và giao diện dữ liệu cho M4.
- Đầu vào chuẩn: snapshot M1 đã duyệt, không nhập thẳng toàn ZIP vào tập phục vụ. Tái sử dụng pipeline M0/M1 cho dữ liệu mới.
- Không triển khai chat/generation/reranking, UI React, đăng ký công khai, refresh-token flow, upload tùy ý hoặc triển khai production trong M3.
- Docker Compose ở M3 chỉ phục vụ chạy DB/API/worker và kiểm thử local; CI và đóng gói phát hành đầy đủ thuộc M7.

## Global Constraints

- Không sửa ZIP, manifest/snapshot M1, chunk IDs hoặc frozen dev/test/seed M2.
- Corpus gốc: `6ebc3836a333f2239e524d6016c0bdf7c11abe6751c4a1b9cd01185e74fb84b7`; kiểm hash bằng quy tắc canonical JSON của M1, không hash lại bằng định dạng mới.
- Phạm vi thời gian chỉ có ngày được xác minh `2026-02-12`. Không diễn giải `effective_to = null` thành đã xác minh đến hiện tại.
- Giữ nguyên reviewer/evidence lịch sử của M1. Người import và admin duyệt vận hành được ghi riêng; không đổi assistant review thành human review.
- Mọi chunk phục vụ phải có provenance, review approved, embedding hợp lệ và thuộc bản phục vụ đã chốt. Không tự duyệt lại dữ liệu chỉ vì JSON ghi `approved`.
- Test DB dùng PostgreSQL/pgvector thật trong database riêng; không dùng SQLite để chứng minh transaction, lock hoặc vector.
- Không commit mật khẩu, JWT secret, model cache, raw/prepared text hay dữ liệu volume. Mọi đọc/ghi văn bản và CLI dùng UTF-8 rõ ràng trên Windows.
- Không tự tạo Postman workspace hoặc publish tài nguyên. M3 tạo OpenAPI và bộ request/assertion local, có thể review bằng Git.

## Quyết định thiết kế

### 1. Cách vận hành

Đề xuất DB-backed worker vì corpus ban đầu chỉ có 10 chunk: ít thành phần, có thể kiểm thử khóa và khôi phục job bằng chính PostgreSQL. Hai phương án khác: chạy ingestion đồng bộ trong HTTP đơn giản hơn nhưng dễ timeout/mất tiến độ; Celery/Redis có hàng đợi chuyên dụng nhưng tăng cấu hình và vận hành ở mốc này.

Luồng chuẩn: CLI đăng ký release M1 từ file local → API tạo import job → worker validate/import → job embedding → admin kiểm tra readiness và duyệt bản phục vụ → activate → M4 đọc bằng ID đã pin.

API không nhận đường dẫn filesystem từ client. CLI đăng ký file vào thư mục release cấu hình sẵn, kiểm hash và tạo `release_id`; HTTP chỉ nhận ID đó. Giới hạn mặc định 64 MiB/file release và 10.000 chunk; vượt giới hạn trả lỗi có mã, không tự cắt nội dung.

### 2. Hai lớp định danh snapshot

- `corpus_snapshot_id`: chính `manifest_hash` M1; gold M2 vẫn trỏ ID này.
- `embedding_profile_id`: hash của provider, model, revision cố định, dimension, normalization, input-template version và giới hạn token.
- `serving_snapshot_id`: hash canonical của corpus ID, embedding profile ID và danh sách sắp xếp `(chunk_id, content_hash, embedding_input_hash, vector_hash)`.
- `active_corpus`: một hàng singleton giữ `serving_snapshot_id` mặc định. Không đưa cờ active vào nội dung đã hash.
- Cùng corpus có thể có nhiều bản phục vụ với embedding khác nhau. M4 pin serving ID một lần và ghi cả corpus ID để đánh giá M2.
- Không update/delete nội dung hoặc membership của bản đã seal. Dùng trigger DB chặn thay đổi; runtime DB role không có quyền DDL/tắt trigger. Role migration tách khỏi runtime.

### 3. Schema tối thiểu

| Bảng | Dữ liệu và ràng buộc chính |
|---|---|
| `users` | UUID, username unique, password hash, role admin/user, disabled; chỉ CLI tạo admin |
| `raw_records` | ZIP hash, path, raw ID, raw URL, raw hash; unique `(zip_hash, path)` |
| `legal_documents` | Số hiệu và metadata gốc; không đồng nhất số hiệu gốc với số hiệu bản hợp nhất đối chiếu |
| `document_versions` | Version hash unique, canonical text, metadata thời gian, source evidence, liên kết raw records |
| `legal_units` | ID M1, version, parent, labels nullable, canonical/raw offsets, review status |
| `retrieval_chunks` | ID/content hash/text/header M1, liên kết units, provenance; không chứa embedding có thể bị ghi đè |
| `corpus_snapshots`, `snapshot_chunks` | Corpus hash và membership bất biến; lưu payload gốc để đối chiếu |
| `embedding_profiles`, `chunk_embeddings` | Profile bất biến, vector(384), input hash, vector hash; unique `(chunk_id, profile_id, input_hash)` |
| `serving_snapshots`, `serving_snapshot_chunks` | Gắn corpus với đúng embedding rows; draft → ready → approved → sealed |
| `active_corpus` | Khóa singleton; FK đến bản đã seal |
| `ingestion_jobs`, `ingestion_job_items` | Loại job, state, attempt, lease/token, checkpoint, per-item error và kết quả |
| `review_events` | Actor, quyết định, object ID/hash, timestamp, lý do; append-only |

`conversations/messages/citations/retrieval_traces` thuộc M4. JSONB được dùng cho evidence và payload gốc; quan hệ/membership/uniqueness chính dùng FK và unique constraints. Không tái tạo unit ID từ labels hoặc sinh khoản giả khi giá trị là null.

### 4. Embedding baseline

Đề xuất local `intfloat/multilingual-e5-small`, vector 384 chiều, chuẩn hóa L2. Dùng `passage: {context_header}\n{text}` cho chunk; M4 dùng `query: {question}`. Pin revision thực tế vào cấu hình/profile trước khi tạo bản phục vụ đầu tiên, không dùng nhánh `main` làm identity.

Model card chính thức: https://huggingface.co/intfloat/multilingual-e5-small . T01 xác nhận cấu hình/tokenizer và pin commit; T05 chạy model thật. Đây là baseline hạ tầng, chưa phải kết luận chất lượng trên pháp luật Việt Nam.

Kiểm số token trước encode, tính cả prefix và special tokens; vượt giới hạn tokenizer/model thì lỗi `EMBEDDING_INPUT_TOO_LONG`, không silently truncate hoặc thay chunk M1. Vector sai số chiều, NaN/Inf hoặc zero norm bị từ chối. Profile mock chỉ dùng test, không được seal/activate. Cache model ngoài Git, chuẩn bị/download bằng CLI rõ ràng; API startup không tải model.

Full-text baseline: `to_tsvector('simple', context_header || ' ' || text)` và GIN index. M3 dùng exact vector distance trên tập đã lọc để chứng minh truy cập đúng dữ liệu; chưa cần ANN/HNSW ở 10 chunk. Benchmark và ranking thuộc M4/M6.

### 5. Job, lỗi và concurrency

Job states: `queued → running → succeeded | failed`; `retry` tạo lại phần việc chưa xong và trả về queued, giữ attempt/error history. Per-item states: pending/running/succeeded/failed/quarantined. Validation lỗi vĩnh viễn không auto retry; lỗi I/O tạm thời retry tối đa 3 lần, backoff 1/2/4 giây, sau đó failed.

Worker claim bằng `FOR UPDATE SKIP LOCKED`; lease 120 giây, heartbeat 30 giây. Worker khác reclaim lease hết hạn; mọi ghi kết quả phải so token fencing để worker cũ không ghi đè. Commit từng item, transaction cuối chỉ xác nhận batch hoàn tất; không giữ DB transaction trong lúc model encode. Unique constraint xử lý import đồng thời; cùng identity nhưng khác nội dung phải lỗi, không upsert ghi đè.

Idempotency cho import: unique `(release_id, operation)` trả lại job cũ; retry dùng endpoint riêng. Embedding job unique `(corpus_snapshot_id, embedding_profile_id, operation)`. Activate khóa singleton, kiểm `expected_active_id`, rồi đổi FK trong một transaction; precondition không khớp trả 409. Kích hoạt lại chính ID đang active là no-op nếu precondition khớp.

### 6. API contract đề xuất

Prefix `/api/v1`, trừ health. Admin endpoints dùng JWT Bearer, role được kiểm lại từ DB. Token sống 30 phút, cố định algorithm HS256, kiểm issuer/audience/expiry; secret bắt buộc từ môi trường. Login sai dùng lỗi chung; thiếu/sai token 401, đúng token nhưng thiếu quyền 403. Tạo admin bằng CLI nhập mật khẩu ẩn, không đưa mật khẩu vào command history. Trước khi expose ngoài local cần bổ sung rate limit ở deployment.

| Method/path | Request chính | Kết quả |
|---|---|---|
| `GET /health/live` | — | 200 nếu process sống |
| `GET /health/ready` | — | 200 nếu DB/extension/migration sẵn sàng; lỗi 503; không yêu cầu đã có corpus |
| `POST /api/v1/auth/token` | JSON username/password | 200 access token; 401 sai credentials |
| `POST /api/v1/admin/imports` | `release_id` | 202 job ID, Location; gọi lặp trả cùng job |
| `GET /api/v1/admin/jobs/{job_id}` | — | 200 state/counts/errors; 404 không có |
| `POST /api/v1/admin/jobs/{job_id}/retry` | — | 202; 409 nếu state không cho retry |
| `POST /api/v1/admin/embedding-jobs` | `corpus_snapshot_id`, `embedding_profile_id` | 202 job ID; 422 ID/profile không hợp lệ |
| `POST /api/v1/admin/serving-snapshots` | Corpus ID, profile ID | 201 draft ID; 409 thiếu embedding/readiness |
| `POST /api/v1/admin/serving-snapshots/{id}/review` | `decision: approve/reject`, note | 200 và review event; lỗi readiness 409 |
| `POST /api/v1/admin/serving-snapshots/{id}/activate` | `expected_active_id` nullable | 200 serving/corpus IDs; 409 conflict hoặc chưa được duyệt |
| `GET /api/v1/admin/serving-snapshots/{id}` | — | Readiness, membership count, hashes và audit metadata |

Mọi lỗi JSON: `{error: {code, message, details}, request_id}`; không trả stack trace/secret/raw credentials. Chuẩn hóa cả lỗi Pydantic, 404 và 500. Response tạo job không có nghĩa import đã xong. Polling client đọc job đến terminal state. Chưa thêm public search API trong M3.

OpenAPI sinh từ FastAPI là source of truth; export `backend/contracts/openapi.json`. Bộ request Postman local có assertion thêm cho auth, idempotency, readiness, activation conflict. Chọn định dạng CLI hỗ trợ khi thực thi bằng `postman --version`/help, không khởi tạo workspace chỉ để lập plan.

## Review Focus

1. Payload tự nhận approved nhưng canonical spans/hash/evidence sai: T04 phải reject/quarantine và không tạo bản phục vụ.
2. Hai worker cùng nhập hoặc worker chết rồi sống lại: T04/T05 phải không nhân bản hoặc ghi đè kết quả mới.
3. Hai admin activate đồng thời: T06 chỉ một precondition thắng; reader đã pin vẫn đọc bản cũ.
4. Đổi model revision/template hoặc vector sai chiều: T05/T06 phải tách profile và chặn dữ liệu không tương thích.
5. Không có prepared files, text tiếng Việt hoặc khoản null: T04 dùng corpus committed làm đầu vào; UTF-8 và labels/offsets giữ nguyên.

## Phân rã công việc

Mỗi task dưới đây hoàn thành theo vòng: viết test hành vi → chạy thấy fail vì phần chức năng còn thiếu → implement tối thiểu → chạy test pass → review diff và commit riêng. Các lệnh là lệnh dự kiến sau khi đã có file; chưa được chạy để chứng minh M3.

### T01 — Runtime và database (M3-T01; 4 giờ)

**Files:** tạo `backend/pyproject.toml`, file khóa dependency, `backend/app/__init__.py`, `backend/app/main.py`, `backend/app/core/config.py`, `backend/app/core/errors.py`, `backend/app/db/session.py`, `backend/alembic.ini`, `backend/migrations/env.py`, `backend/.env.example`, `infra/compose.m3.yml`, `backend/Dockerfile`, `backend/tests/conftest.py`, `backend/tests/test_health.py`.

**Interfaces:** `create_app() -> FastAPI`; `Settings` từ env; `get_session() -> Iterator[Session]`. SQLAlchemy session sync, worker process riêng; không thực hiện encode trong request.

- [x] Test live=200; ready=503 khi DB unavailable/migration lệch; ready=200 khi DB đã migrate; cấu hình thiếu secret phải fail startup rõ ràng.
- [x] Pin dependencies/image và model revision; kiểm Python 3.10 trên máy hiện tại, cấu hình volume cache và DB healthcheck. Default port DB chỉ bind loopback.
- [x] Migration đầu tạo extension vector; cung cấp Compose services `db`, `migrate`, `api`, `worker`, volume DB riêng và biến môi trường mẫu không có secret thật.
- [x] Run từ root: `docker compose -f infra/compose.m3.yml up -d db`; `python -m pip install -e "./backend[dev]"`; `python -m alembic -c backend/alembic.ini upgrade head`; `python -m pytest backend/tests/test_health.py -q`.
- [x] Kiểm model card/config/tokenizer tại revision pin; ghi dimension/token limit/revision vào cấu hình mẫu và báo cáo. Commit runtime/config/migration.

### T02 — Schema và invariant DB (M3-T02; 4 giờ)

**Files:** tạo `backend/app/db/models/{identity,corpus,embeddings,jobs,snapshots}.py`, `backend/migrations/versions/0002_domain.py`, `backend/tests/test_schema.py`. Model registry import từ `backend/app/db/models/__init__.py`.

**Interfaces:** IDs corpus/chunk/version là hex string M1; job/user/event IDs là UUID. Repository không trả ORM rows ra API; DTO Pydantic đặt cùng module tính năng dùng chúng.

- [x] Test duplicate identity bị chặn, FK membership sai bị chặn, article không có clause giữ null, chỉ một active pointer tồn tại.
- [x] Tạo các bảng/ràng buộc ở phần schema; canonical text/offsets lấy từ `documents` trong payload M1, không phụ thuộc `prepared/` ignored.
- [x] Định nghĩa trigger seal và quyền runtime/migration; test trực tiếp SQL không sửa được sealed membership/text/vector hoặc xóa embedding đang được tham chiếu.
- [x] Run: `python -m pytest backend/tests/test_schema.py -q`; kiểm upgrade trên DB trống và chạy upgrade head lần hai không thay schema. Commit schema.

### T03 — Auth admin và contract nền (M3-T02; 3 giờ)

**Files:** tạo `backend/app/auth/{passwords,tokens,dependencies,routes}.py`, `backend/app/cli.py`, `backend/app/api/router.py`, `backend/tests/test_auth.py`.

**Interfaces:** `require_admin(...) -> User`; CLI `python -m app.cli create-admin --username NAME`; `POST /api/v1/auth/token` theo contract trên. Module `app` được import sau cài editable package T01.

- [x] Test Argon2 không lưu plaintext, login đúng/sai, JWT hết hạn/sai chữ ký/sai issuer/audience, disabled user, missing token 401 và user role 403.
- [x] Implement CLI interactive, không seed admin/password mặc định. Đăng ký health/auth/router và lỗi có request_id.
- [x] Run: `python -m pytest backend/tests/test_auth.py -q`; kiểm OpenAPI security scheme và response login không lộ password hash. Commit auth.

### T04 — Release adapter và ingestion có thể tiếp tục (M3-T02; 6 giờ)

**Files:** tạo `backend/app/ingestion/{manifest,releases,service,jobs,worker,routes}.py`, `backend/tests/test_manifest_import.py`, `backend/tests/test_job_recovery.py`; mở rộng CLI T03.

**Interfaces:** `load_release(path: Path) -> ValidatedRelease`; `register_release(path: Path) -> str`; `enqueue_import(release_id: str, actor_id: UUID) -> JobDTO`; `run_once(worker_id: str) -> bool`. `ValidatedRelease` chứa corpus ID, documents, units, chunks và evidence đã kiểm; DTO definitions nằm trong `manifest.py`/`jobs.py` tương ứng.

- [x] Test import release committed ra đúng 1 version/10 chunks và ID M1; gọi lặp/concurrent không tăng count, giữ reviewer nguồn và thêm audit actor.
- [x] Test hash snapshot/chunk sai, duplicate chunk ID, offsets ngoài text, span không khớp, orphan unit, evidence thiếu, review pending hoặc thời gian không khớp: không được seal; ghi reason code. Toàn manifest lỗi integrity thì fail trước ghi domain rows.
- [x] Test không có `prepared/`, Unicode/CRLF, label null và giới hạn file/chunk count; body HTTP không nhận filesystem path.
- [x] Implement đối chiếu canonical/hash/relations từ full payload M1; dùng M1 IDs, source URLs, raw/canonical hashes và temporal policy nguyên gốc. Không import all ZIP hoặc gọi lại source web để tự tạo review.
- [x] Implement per-item checkpoint, lỗi có trạng thái; failure ở item N giữ item đã commit nhưng corpus ở staging và không activate được. Retry bỏ qua item thành công sau khi đối chiếu identity/hash.
- [x] Test worker crash/lease reclaim/fencing; hai worker đồng thời; same identity/different content bị lỗi. Run: `python -m pytest backend/tests/test_manifest_import.py backend/tests/test_job_recovery.py -q`. Commit ingestion.

### T05 — Embedding worker và index (M3-T03; 5 giờ)

**Files:** tạo `backend/app/providers/{embedding,local_e5}.py`, `backend/app/ingestion/embedding_jobs.py`, `backend/app/db/search.py`, `backend/migrations/versions/0003_indexes.py`, `backend/tests/test_embeddings.py`, `backend/tests/test_embedding_smoke.py`.

**Interfaces:** `EmbeddingProvider.embed_passages(texts: list[str]) -> list[list[float]]`; `EmbeddingProvider.embed_queries(texts: list[str]) -> list[list[float]]`; profile metadata chứa model/revision/dimension/template/token limit; `enqueue_embeddings(corpus_snapshot_id: str, embedding_profile_id: str, actor_id: UUID) -> JobDTO`.

- [x] Unit tests profile identity đổi khi revision/template đổi; chunk text/hash không đổi; wrong count/dimension, NaN/Inf/zero vector, token overflow đều fail; không nhận hash-derived fake vector làm baseline thật.
- [x] Implement local model loader/cache và batch encode, lưu input hash + vector hash, checkpoints và retry có fencing; worker load model trước claim hoặc duy trì heartbeat độc lập khi encode lâu.
- [x] Test restart không tạo embedding trùng, không dùng vector từ profile khác, partial batch không được ready; tạo GIN full-text `simple`, vector distance chỉ chạy trong tập profile/membership tương thích.
- [x] Run: `python -m pytest backend/tests/test_embeddings.py -q`. Chạy smoke model thật: `python -m pytest backend/tests/test_embedding_smoke.py -m model -q`; phải ghi rõ PASS hoặc BLOCKED nếu model chưa tải được, không đổi sang mock và báo hoàn thành.
- [x] Ghi bằng chứng 10/10 vector thật hợp lệ và cấu hình revision/dimension; không đo/tuning bằng test M2. Commit embedding/index.

### T06 — Review, seal, activate và reader cho M4 (M3-T04; 5 giờ)

**Files:** tạo `backend/app/domain/{snapshots,serving_reader}.py`, `backend/app/api/admin_snapshots.py`, `backend/tests/test_snapshot_activation.py`, `backend/tests/test_serving_reader.py`; bổ sung trigger nếu T02 chưa đủ trường final hash.

**Interfaces:** `build_serving_snapshot(corpus_snapshot_id: str, embedding_profile_id: str) -> SnapshotDTO`; `review_snapshot(serving_snapshot_id: str, actor_id: UUID, decision: str, note: str) -> SnapshotDTO`; `activate(serving_snapshot_id: str, expected_active_id: str | None, actor_id: UUID) -> SnapshotDTO`; `pin_active() -> ServingContext`; `read_chunks(context: ServingContext, as_of_date: date, topic: str | None = None) -> list[ChunkDTO]`. `ServingContext` gồm serving/corpus/profile IDs, dimension và các ngày đã xác minh.

- [x] Test thiếu metadata/evidence/vector hoặc profile test thì không approve/seal; 10/10 hợp lệ mới chốt hash. Rejection có audit note và không activate được.
- [x] Implement seal và activate một transaction, lock singleton và so precondition; không đọc cờ `active: true` M1 để tự activate.
- [x] Test hai kết nối activate cạnh tranh: một thắng, một 409; thất bại giữa transaction giữ pointer cũ. Reader đã pin bản A vẫn lấy đúng A sau khi đổi B.
- [x] Test mutation của sealed corpus/units/chunks/vector bị DB chặn; reader lấy đúng approved members/profile, không rò draft/rejected data; ngày ngoài 2026-02-12 trả lỗi temporal có mã, không mặc định coi còn hiệu lực.
- [x] Run: `python -m pytest backend/tests/test_snapshot_activation.py backend/tests/test_serving_reader.py -q`. Commit review/activate/reader.

### T07 — Contract, smoke toàn luồng và bàn giao (xuyên suốt M3; 3 giờ)

**Files:** tạo `backend/scripts/export_openapi.py`, `backend/contracts/openapi.json`, request/assertion Postman local trong `backend/contracts/`, `backend/tests/test_m3_flow.py`, `backend/README.md`, `backend/reports/m3-report.md`; cập nhật `README.md` chỉ khi nghiệm thu xong.

- [x] Export OpenAPI từ `create_app()`; kiểm mọi endpoint/auth/error/status code trong contract. Test 401/403, import 202 + polling, repeat identity, retry và activation 409 qua HTTP thật hoặc TestClient + DB thật.
- [x] Postman skill khi thực thi: dùng `api-testing` cho collection, `bootstrap` chỉ nếu CLI cần setup. Không publish hoặc bind workspace tự động. Nếu chọn embedding HTTP thay local, bổ sung `api-discovery` trước tích hợp và `api-simulation` cho timeout/429/5xx khi chạy code.
- [x] Smoke trên DB riêng: migrate → create admin → register release → import → worker → embed model thật → review → activate → pin/read đủ 10 chunk → import/retry lại không trùng. Tạo fixture riêng để chứng minh đổi snapshot và giữ bản cũ; không sửa snapshot M1/M2 thật.
- [x] Run: `python -m pytest backend/tests -m "not model" -q`; chạy riêng model smoke; `python -m evaluation.dataset validate`; `python -m unittest discover -s evaluation/tests -q`; `python -m unittest discover -s data/tests -q`.
- [x] Hướng dẫn đủ lệnh từ checkout sạch và file env local; test DB khác runtime DB và không teardown volume người dùng. Ghi kết quả thực, model/image/dependency pins, hạn chế và lỗi còn lại. Commit contract/docs/report sau khi checks pass.

## Cổng nghiệm thu M3

- [x] DB/API/worker chạy được từ hướng dẫn; migration tái lập, ready phản ánh tình trạng DB đúng.
- [x] Admin auth bảo vệ tất cả thao tác thay đổi dữ liệu; không có tài khoản mặc định/secret committed.
- [x] Import M1 tạo đúng 10 chunk và provenance; lặp hoặc chạy đồng thời không nhân bản; lỗi có checkpoint/retry/audit.
- [x] Có embedding thật cho 10/10 chunk; metadata model/revision/dimension/template đầy đủ và vector hợp lệ.
- [x] Chỉ bản đã duyệt, đủ embedding và seal mới activate; concurrent activate, worker crash và rollback đã được kiểm bằng PostgreSQL thật.
- [x] Reader pin snapshot và lọc profile/temporal/membership đúng; bản cũ còn đọc được sau khi đổi mặc định.
- [x] OpenAPI và request/assertion local khớp API; tests M0/M1/M2 còn pass và freeze M2 không đổi.
- [x] Báo cáo M3 không ghi Recall/MRR hoặc chất lượng trả lời là kết quả đã đạt. Các metric đó thuộc M4/M6.

## Thời lượng và thứ tự

`T01 → T02 → T03 → T04 → T05 → T06 → T07`. Ước lượng **30–38 giờ**, gồm khoảng 30 giờ task và dự phòng lỗi môi trường/model/concurrency. Mốc cũ 24 giờ khá sát vì chưa tách chi phí auth, contract và kiểm thử khôi phục/concurrency. Đây là ước lượng, không phải cam kết lịch; ở 15 giờ/tuần tương đương khoảng 2–3 tuần.

Người dùng đã duyệt kế hoạch và yêu cầu thực thi toàn bộ M3 trên branch mới, có commit, ngày 20/10/2026. Đã thực thi tuần tự và nghiệm thu; xem `backend/reports/m3-report.md` cho kiểm thử thực tế, quyết định triển khai và giới hạn.
