# M4 — RAG API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. Checklist dưới đây là kế hoạch được duyệt; xem trạng thái triển khai và bằng chứng hiện tại tại `backend/reports/m4-report.md` trước khi tiếp tục. Code M4 đã được triển khai trên `feat/m4-rag-api`; cổng OpenAI live còn chờ key/model và rà soát câu trả lời.

**Goal:** Cung cấp API hỏi đáp pháp luật lao động bằng tiếng Việt, truy xuất trên snapshot đã pin, trả claims có citation kiểm được và lịch sử nguồn mở lại được.

**Architecture:** Tái sử dụng FastAPI, PostgreSQL/pgvector, reader và E5 local của M3. Pipeline đồng bộ: pin snapshot → kiểm thời điểm → rewrite → keyword/vector/hybrid → context → OpenAI generation → citation validation → lưu kết quả. Không giữ transaction DB trong khi gọi model.

**Tech Stack:** Python hiện có, FastAPI/Pydantic, SQLAlchemy Core, Alembic, PostgreSQL/pgvector, Sentence Transformers E5, OpenAI Python SDK, tokenizer tương thích model được chọn, pytest và Postman CLI.

**Spec:** `docs/PROJECT_PLAN.md` (M4), `docs/RAG_ARCHITECTURE.md`; đối chiếu `backend/README.md`, `backend/reports/m3-report.md`, `evaluation/README.md` và mã M3. Các lựa chọn bổ sung bên dưới là đề xuất của kế hoạch; người dùng đã chọn **OpenAI API** cho rewrite/generation.

**Location:** `backend/M4_PLAN.md`, theo cách tổ chức M2/M3 vì `/docs` đang bị Git ignore.

## Global Constraints

- Không sửa manifest/chunk IDs M1 hoặc frozen dev/test/seed M2. Corpus ID: `6ebc3836a333f2239e524d6016c0bdf7c11abe6751c4a1b9cd01185e74fb84b7`.
- Corpus hiện có 10 chunk thuộc một văn bản; chỉ xác minh tại `2026-02-12`. `effective_to = null` không có nghĩa đã xác minh đến hiện tại.
- Mọi truy xuất, context và citation của một lượt dùng cùng `ServingContext`; lưu cả corpus ID, serving ID và embedding profile ID.
- Giữ E5 `intfloat/multilingual-e5-small`, revision `614241f622f53c4eeff9890bdc4f31cfecc418b3`, vector 384 chiều, prefix `query: `. Không đổi sang OpenAI embeddings trong M4.
- Test transaction, membership và vector dùng PostgreSQL/pgvector thật, database verification riêng. Không chạy đồng thời các suite cùng reset database này.
- Chỉ dùng dev/seed để phát triển và chọn tham số. M6 mới đánh giá test giữ riêng; validator được phép kiểm toàn vẹn freeze.
- Giữ nguyên metadata/reviewer nguồn M1; không diễn giải kiểm citation bằng cấu trúc thành kiểm chứng suy luận pháp lý.
- Không commit API key, token, mật khẩu, model cache hoặc log chứa đầy đủ hội thoại. File văn bản dùng UTF-8.
- OpenAPI sinh từ FastAPI là hợp đồng HTTP chuẩn; Postman lưu request/assertion local. Không tạo/publish workspace hoặc gửi run events lên cloud trong phạm vi này.

## Hiện trạng và lựa chọn kiến trúc

M3 đã có `ServingContext`, `pin_active()`, `read_chunks()`, `keyword_candidates()`, `vector_candidates()` và `LocalE5.embed_queries()`. Chưa có hybrid fusion, pipeline trả lời, các bảng chat, quyền truy cập lịch sử hoặc OpenAI provider. `require_admin()` hiện gộp xác thực với kiểm role; CLI mới có `create-admin`.

Các phương án đã cân nhắc:

| Phương án | Lợi ích | Đánh đổi |
|---|---|---|
| **Đề xuất: pipeline đồng bộ trong backend hiện tại** | Tận dụng M3, trace rõ từng bước, phù hợp corpus nhỏ | HTTP phải có deadline; một lượt/conversation tại một thời điểm |
| Worker riêng cho từng câu hỏi | Tách tác vụ dài khỏi HTTP | Thêm queue/polling/state recovery; chưa cần cho demo M4 |
| Framework agent, tool gọi nguồn và reranker ngay | Có sẵn orchestration | Khó giới hạn nguồn, thêm thành phần trước khi có baseline dev |

Không làm UI, streaming/SSE, upload corpus, đăng ký công khai, refresh/logout hoặc production deployment ở M4. Reranker chỉ bổ sung bằng task riêng nếu có số đo dev chứng minh lợi ích; không nằm trong 26 giờ cơ sở. M5 cần xử lý refresh/logout vì M3 hiện chỉ có access token 30 phút.

## Hợp đồng và hành vi đề xuất

### API cho M5

Tất cả endpoint dưới đây yêu cầu Bearer token của user đang enabled. Admin dùng chat như user thường và không tự có quyền xem hội thoại của người khác.

| Method/path | Input | Output và quyền |
|---|---|---|
| `POST /api/v1/search` | `query`, `mode`, `top_k`, `as_of_date`, `topic?` | 200 candidates, ranks, snapshot/profile IDs; phục vụ debug/evaluation, không gọi generation |
| `POST /api/v1/conversations` | Không có trường bắt buộc | 201 conversation rỗng, owner lấy từ token |
| `GET /api/v1/conversations` | `limit=20`, `cursor?` | 200 danh sách của owner, thứ tự `(created_at, id)` giảm dần, `next_cursor` |
| `POST /api/v1/conversations/{id}/messages` | `question`, `mode=hybrid`, `as_of_date?`, `topic?`, bắt buộc header `Idempotency-Key` | 200 kết quả lượt chat; lượt đang xử lý hoặc conversation bận trả 409 |
| `GET /api/v1/conversations/{id}/messages` | `limit=20`, `cursor?` | 200 lịch sử của owner, thứ tự sequence tăng dần, `next_cursor`; kèm trạng thái lượt lỗi |
| `GET /api/v1/messages/{message_id}/citations/{citation_id}` | IDs | 200 quote, canonical span, metadata và provenance từ snapshot của message; không đọc lại active pointer |
| `GET /api/v1/messages/{message_id}/trace` | ID | 200 trace an toàn của lượt thuộc owner; không có API key hoặc raw provider payload |

`mode ∈ {keyword, vector, hybrid}`; `top_k` mặc định 5, giới hạn 1–10. `topic` chỉ nhận năm tags đã đối chiếu manifest M1: `contract`, `probation`, `wages`, `hours_rest`, `termination`. Câu hỏi/query sau trim dài 1–4.000 ký tự; list limit 1–100; cursor sai trả 422. Không nhận `owner_id`, history tùy ý hoặc serving ID tùy ý từ client chat.

Response chat có `status`, `answer`, `claims`, `citations`, `conversation_id`, `message_id`, `request_id`, `corpus_snapshot_id`, `serving_snapshot_id`, `embedding_profile_id`, `as_of_date`, `scope_notice`. `snapshot_id` là alias được mô tả rõ của `serving_snapshot_id` để khớp thiết kế kiến trúc; gold M2 luôn dùng `corpus_snapshot_id`.

- `answered`: ít nhất một claim có nguồn hợp lệ; `answer` dựng từ chính các claim đã kiểm. Không có đoạn kết luận pháp lý tự do bên ngoài claims.
- `insufficient_evidence`: thiếu context hoặc model không tìm đủ căn cứ; claims/citations rỗng.
- `out_of_scope`: ngoài năm nhóm công bố; claims/citations rỗng. Không quyết định chỉ bằng một từ khóa đơn lẻ.
- `needs_clarification`: thiếu dữ kiện quan trọng hoặc ngày không được xác minh; trả câu hỏi làm rõ, claims/citations rỗng.
- Chat thiếu ngày: dùng ngày được xác minh duy nhất của snapshot và nêu `scope_notice`; nếu người dùng nói “hiện nay”, hỏi về mốc chưa xác minh hoặc đưa ngày mâu thuẫn giữa text/body/history thì yêu cầu làm rõ. Ngày explicit của lượt hiện tại ưu tiên hơn ngày cũ; đổi ngày so với lịch sử phải được nêu rõ trong trace.
- Search yêu cầu ngày rõ ràng; ngày ngoài verified dates trả 422 `UNVERIFIED_DATE`. Chat chuyển trường hợp này thành `needs_clarification`, không suy đoán luật tại ngày đó.
- 401 token sai/hết hạn; 404 cho tài nguyên không tồn tại hoặc thuộc người khác; 409 conversation bận/key dùng với payload khác; 422 input sai; 503 corpus/model/provider không sẵn sàng; 502 output provider không hợp lệ hoặc citation vẫn lỗi sau repair; 504 provider timeout.
- Lỗi hạ tầng dùng envelope M3 `{error:{code,message,details},request_id}`; tuyệt đối không biến lỗi thành `answered` hoặc `insufficient_evidence`.

### Retrieval, rewrite và context

- Pin active **một lần mỗi lượt mới**; replay key cũ trả kết quả đã lưu. Lượt tiếp theo có thể pin snapshot mới; text assistant cũ không được coi là chứng cứ của lượt mới.
- Mỗi nhánh lấy tối đa 10 candidate; hybrid khử trùng theo `chunk_id`, điểm `sum(1 / (60 + rank))`; tie-break bằng chunk ID tăng dần. Keyword mode không gọi embedding. Hybrid không lặng lẽ chuyển sang keyword khi vector/provider lỗi.
- Thêm topic filter **trước LIMIT** cho cả hai nhánh DB; vẫn giữ guards snapshot/profile/date/approved của M3. Giữ `simple` full-text làm baseline, không tự chuyển sang OR/unaccent nếu chưa có kết quả dev.
- Chỉ dùng tối đa 6 message đã hoàn tất gần nhất, tối đa 2.000 token lịch sử. Rewrite trả `standalone_question`, `needs_clarification`, `reason`; giữ số tiền, ngày, phủ định và loại hợp đồng. Timeout/output sai của rewrite fallback câu gốc và ghi cờ trace; không fallback nếu đã hết deadline toàn lượt.
- Context ưu tiên top 5, nhóm chứng cứ theo `(version_id, article_label)` và thêm mọi sibling của điều đó khi có trong **membership đã duyệt**, dedup theo chunk; heading lấy từ DB. Không kéo nguyên điều từ canonical text nếu đoạn bổ sung chưa được duyệt trong snapshot. Nhóm này giữ đủ phần điều đã có trong corpus, không khẳng định corpus đã bao phủ mọi ngoại lệ hoặc văn bản viện dẫn bên ngoài.
- Giữ nguyên toàn bộ chunk được chọn; không cắt giữa khoản hoặc bỏ phần ngoại lệ để vừa budget. Không đủ chỗ cho một nhóm quy tắc/ngoại lệ thì loại cả nhóm và ghi lý do; không có nhóm đủ chỗ trả `insufficient_evidence` trước generation.
- Dùng source ID bằng chunk ID gốc. Evidence quote là toàn bộ text chunk, span `[start,end)` theo Unicode code point trên `document_versions.canonical_text`, khớp payload M1; không dùng byte offsets hoặc raw offsets. Parent heading không phải nguồn pháp lý riêng.
- Mặc định: evidence budget 6.000 token, input tổng 10.000, output generation 2.000, rewrite output 512. Input tổng tính cả prompt/schema/question/history/context; tokenizer phải tương thích model, chừa overhead an toàn và fail rõ khi không xác định được encoding. Không truncate âm thầm.

### OpenAI integration

- Dùng OpenAI Python SDK, Responses API và structured output Pydantic; schema strict, không có tools/web/file search. Gửi bounded history thủ công, `store=False`, không dùng OpenAI Conversations hoặc `previous_response_id` làm nguồn lịch sử chuẩn.
- Cấu hình `OPENAI_API_KEY` dạng secret, `OPENAI_MODEL`, `OPENAI_REWRITE_MODEL` (mặc định bằng model generation). Không tự chọn “latest”: trước triển khai T03 cần ghi model ID cụ thể đang có quyền truy cập và hỗ trợ Responses/structured output, encoding tương thích và context window trong cấu hình chạy/báo cáo.
- SDK timeout mỗi call tối đa 20 giây; deadline pipeline 60 giây. `max_retries=0` ở SDK để không nhân retry. Adapter retry tối đa một lần cho connection/429/5xx nếu còn deadline, tôn trọng `Retry-After` trong thời gian còn lại. Không retry 401/403 hoặc JSON/schema lỗi theo cơ chế transport.
- Draft output: `status`, `clarification_question: str | null`, `claims: list[{text: str, source_ids: list[str]}]`. Refusal, incomplete và parse error có xử lý riêng; không coi JSON parse được là đã grounded.
- Validator kiểm mọi claim có source ID, ID thuộc context và pinned snapshot, chunk approved, version/metadata/span khớp DB; quote do backend trích, không nhận quote/URL/điều khoản do model tạo. Reject cả draft nếu bất kỳ claim lỗi; cho tối đa một repair trong deadline, không phát hành bản trả lời một phần còn claim lỗi.
- Không gọi generation khi context rỗng. Với context có nhưng không liên quan, prompt phải cho phép abstain; kiểm tình huống này bằng dev và test. Kiểm cấu trúc citation không chứng minh claim được nguồn hỗ trợ về nghĩa: báo cáo phải có rà soát thủ công.
- Trace ghi model ID thực tế trả về, prompt/schema versions, usage, latency, số lần retry/repair, source IDs và validation result. Không ghi API key hoặc chain-of-thought.

Nguồn chính thức đã đối chiếu khi lập plan: [Structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs), [Responses Python reference](https://developers.openai.com/api/reference/python/resources/responses). Schema strict vẫn cần xử lý refusal/incomplete và kiểm nguồn ở backend.

### Lưu trữ và concurrency

- `conversations`: UUID, owner FK users, created_at, next_sequence, in_flight_message_id/lease_until.
- `messages`: UUID, conversation FK, sequence unique trong conversation, role, text, trạng thái processing/completed/failed, result JSONB, request_id, idempotency_key, request_hash, error_code, các snapshot/profile IDs và resolved date của lượt assistant. Unique key theo `(conversation_id,idempotency_key)` cho lượt assistant; user/assistant được liên kết cùng turn ID.
- `citations`: UUID, assistant message FK, chunk/version FK, serving ID, canonical start/end, quote; FK composite `(serving_id,chunk_id)` đến `serving_snapshot_chunks`. Claim-source mapping nằm trong result JSONB và phải khớp rows citations.
- `retrieval_traces`: một row/message, snapshot/profile IDs, original/rewritten query (chỉ DB có kiểm owner), ranks/scores từng nhánh, fusion, context IDs, budgets, prompt/model versions, timings, usage và error codes.
- Một transaction ngắn giữ quyền xử lý conversation, cấp sequence và lưu user + processing assistant. Lease 90 giây dài hơn deadline; sau đó gọi model ngoài transaction. Transaction cuối kiểm token sở hữu lượt trước khi lưu result/citations/trace và giải phóng conversation.
- Key trùng + cùng payload trả kết quả đã hoàn tất; còn processing trả 409; failed trả lại lỗi đã lưu. Cùng key khác payload trả 409. Muốn thử lại lượt failed dùng key mới; lượt cũ vẫn có trong lịch sử. Không tuyên bố exactly-once với upstream OpenAI khi process crash.
- Khi phát hiện lease quá hạn, đánh dấu lượt cũ failed `TURN_INTERRUPTED` rồi cho nhận lượt mới. Worker/request cũ không được finalize sau khi mất ownership. Lượt lỗi không có citations và không đưa vào rewrite history.

## Review Focus

1. Active pointer đổi giữa retrieval/generation hoặc khi mở nguồn cũ: toàn lượt và citations vẫn dùng snapshot gốc (T01/T04).
2. Vector luôn có top-k dù câu hỏi không liên quan; context thiếu ngoại lệ hoặc quá dài: phải abstain/giữ nguyên nhóm chứng cứ, không ép trả lời (T02/T03).
3. Follow-up chứa phủ định, số tiền hoặc ngày mâu thuẫn history: rewrite không thêm tình tiết và phải hỏi lại khi không xác định được (T02).
4. Model trả source giả, prompt injection, refusal, output dở dang hoặc provider 429/timeout: không rò claims chưa kiểm, bounded retry và lỗi kỹ thuật rõ ràng (T03).
5. Hai user, hai request cùng conversation, replay key và crash trước finalize: không lộ lịch sử, không tạo hai turn do replay và không ghi kết quả từ lease cũ (T00/T04).

## Thứ tự triển khai và ước lượng

26 giờ giữ theo roadmap, chia lại phần nền chat để các task phụ thuộc rõ ràng. Đây là ước lượng cơ sở, chưa phải cam kết; nên dành thêm 6–10 giờ dự phòng cho tích hợp model, simulation và sửa lỗi.

| Task | Đầu ra độc lập | Giờ | Mapping roadmap |
|---|---|---:|---|
| T00 | Contract, migration, auth user, persistence | 4 | Phần nền của M4-T04 |
| T01 | Ba retrieval mode + search API | 6 | M4-T01 |
| T02 | Rewrite, time policy, bounded context | 5 | M4-T02 |
| T03 | OpenAI generation, citation validation | 6 | M4-T03 |
| T04 | Chat/history/source/trace, acceptance | 5 | M4-T04 và tích hợp |
| **Tổng** | | **26** | |

Chạy tuần tự `T00 → T01 → T02 → T03 → T04`. Khoảng 2 tuần ở mức 15 giờ/tuần; tính cả dự phòng khoảng 3 tuần. Không chốt ngày lịch khi chưa biết ngày bắt đầu và model được cấp quyền.

### T00 — Contract, auth và nền lưu trữ (4 giờ)

**Files:** Create `backend/app/chat/schemas.py`, `backend/app/chat/repository.py`, `backend/migrations/versions/0004_chat.py`, `backend/tests/test_chat_storage.py`, `backend/tests/test_chat_auth.py`; modify `backend/app/db/models/__init__.py`, `backend/app/auth/dependencies.py`, `backend/app/cli.py`, `backend/app/main.py`, `backend/scripts/verify_fresh_migration.py`, `backend/tests/test_health.py`, `backend/tests/test_schema.py`.

**Interfaces:** `require_user()` trả row user enabled; `require_admin()` gọi lại nó rồi check role. Repository: `create_conversation(owner_id: UUID) -> ConversationDTO`, `reserve_turn(owner_id: UUID, conversation_id: UUID, key: str, request_hash: str, request_id: str) -> ReservedTurn`, `finalize_turn(turn: ReservedTurn, result: ChatResult | TurnError, trace: TraceDTO) -> None`. Schemas định nghĩa `CandidateDTO`, `RewriteResult`, `ContextBundle`, `GenerationDraft`, `ValidatedAnswer`, `ChatRequest`, `ChatResult`, `TraceDTO`, `ReservedTurn`, `TurnError`, `HistoryMessage`, `TemporalDecision`, `CitationDTO`, `ConversationDTO`, `ConversationPage`, `MessagePage` dùng chung các task sau; các DTO theo contract ở trên, page chứa `items` và `next_cursor` nullable. `ReservedTurn` mang turn/message IDs, fencing token và replay/error result khi key đã tồn tại.

- [ ] Viết test `test_user_auth_keeps_admin_routes_restricted`: user chat dependency thành công, admin endpoint 403, disabled/hết hạn 401. `test_owner_isolation`: user B và admin không đọc/reserve conversation của user A (404).
- [ ] Viết `test_turn_idempotency_and_lease`: cùng key/hash có một turn; key khác hash 409; hai key đồng thời chỉ một reserve được; lease cũ không finalize. `test_citation_fk_rejects_nonmember` chứng minh composite FK chặn citation sai snapshot.
- [ ] Chạy `backend/.venv/Scripts/python -m pytest backend/tests/test_chat_storage.py backend/tests/test_chat_auth.py -q`; xác nhận fail do giao diện chưa có trước khi viết code.
- [ ] Thêm migration forward-only `0004`, models, DTOs, repository và CLI `create-user --username` dùng hidden password prompt. Không đổi token issuer/audience của M3; cập nhật readiness và script migration đang hardcode `0003` sang `0004`.
- [ ] Chạy lại hai file test; chạy `backend/.venv/Scripts/python backend/scripts/verify_fresh_migration.py` và `backend/.venv/Scripts/python backend/scripts/migrate_verification.py` trên DB verification đã chuẩn bị. PASS khi migration mới/repeat thành công, auth cũ không regress.
- [ ] Commit riêng schema/auth/persistence sau khi checks pass.

### T01 — Retrieval và search API (6 giờ)

**Files:** Create `backend/app/rag/retrieval.py`, `backend/app/api/search.py`, `backend/tests/test_retrieval.py`, `backend/tests/test_search_api.py`; modify `backend/app/db/search.py`, `backend/app/main.py`, `backend/contracts/openapi.json`. Tạo package `backend/app/rag/__init__.py`, `backend/app/chat/__init__.py` cùng task đầu tiên dùng chúng.

**Interfaces:** `retrieve(context: ServingContext, query: str, as_of_date: date, mode: Literal['keyword','vector','hybrid'], top_k: int = 5, topic: str | None = None) -> list[CandidateDTO]`; `fuse_rrf(keyword: list[CandidateDTO], vector: list[CandidateDTO], k: int = 60) -> list[CandidateDTO]`. DTO có chunk ID, corpus/serving/profile IDs, score/rank, từng branch rank/score và provenance. Giữ các hàm candidates M3 tương thích, thêm `topic=None` cuối signature.

- [ ] Viết `test_rrf_dedup_and_stable_ties`: chunk đứng hạng 1 ở hai nhánh có score `2/61`, một nhánh có `1/61`, dedup một lần; bằng điểm sort theo ID.
- [ ] Viết `test_modes_share_pin_and_topic_filter_before_limit`, `test_keyword_does_not_embed`, `test_profile_dimension_and_approval_guards`, `test_activation_during_request_keeps_original_snapshot`; dùng fixtures PostgreSQL và barrier khi đổi active.
- [ ] Chạy `backend/.venv/Scripts/python -m pytest backend/tests/test_retrieval.py backend/tests/test_search_api.py -q` và ghi nhận fail đúng nguyên nhân thiếu chức năng.
- [ ] Implement retrieval, filter DB trước limit, profile identity check trước query encode, trace branch ranks. Search chỉ nhận verified date và pin snapshot một lần; không cần gọi OpenAI.
- [ ] Chạy lại test mới và `backend/tests/test_serving_reader.py`, `backend/tests/test_snapshot_activation.py`; chạy một query E5 thật với profile đã pin và xác nhận IDs/dimension, không gọi đó là bằng chứng chất lượng retrieval.
- [ ] Export OpenAPI bằng script hiện có; commit retrieval/search/tests/contract sau khi pass.

### T02 — Rewrite, thời điểm và context (5 giờ)

**Files:** Create `backend/app/providers/generation.py`, `backend/app/rag/rewrite.py`, `backend/app/rag/temporal.py`, `backend/app/rag/context.py`, `backend/app/rag/prompts.py`, `backend/tests/test_rewrite.py`, `backend/tests/test_temporal.py`, `backend/tests/test_context.py`; modify `backend/app/core/config.py`.

**Interfaces:** Protocol `GenerationProvider.rewrite(question: str, history: list[HistoryMessage], deadline: float) -> RewriteResult`, `GenerationProvider.generate(question: str, context: ContextBundle, repair_errors: list[str], deadline: float) -> GenerationDraft`, `GenerationProvider.count_tokens(text: str) -> int`. `rewrite_question(..., provider: GenerationProvider) -> RewriteResult`; `resolve_date(question: str, supplied: date | None, previous: date | None, context: ServingContext) -> TemporalDecision`; `build_context(context: ServingContext, candidates: list[CandidateDTO], as_of_date: date, question: str, provider: GenerationProvider) -> ContextBundle`. `TemporalDecision` chứa resolved date hoặc clarification; `ContextBundle` chứa full chunks/spans, token counts và excluded groups. History chỉ lấy từ repository owner-scoped.

- [ ] Viết `test_rewrite_preserves_negation_amount_and_contract`, `test_rewrite_failure_uses_original`, `test_history_is_bounded_and_not_evidence`. Mock provider output cố ý thêm tình tiết phải bị reject/fallback ở các trường có thể kiểm xác định; bổ sung checklist review nghĩa trên dev cho tình tiết không kiểm được bằng cấu trúc.
- [ ] Viết `test_current_or_conflicting_date_needs_clarification`, `test_missing_date_reports_verified_scope`, `test_old_history_date_does_not_override_current_turn`.
- [ ] Viết `test_context_budget_keeps_complete_units`, `test_sibling_must_be_snapshot_member`, `test_canonical_unicode_spans`, `test_no_context_skips_generation`; test rules + exception bị loại cùng nhau khi budget thiếu.
- [ ] Chạy ba file test mới để thấy fail; implement protocol, policy và context theo defaults đã ghi, lấy text/span từ DB; không sửa/rechunk dữ liệu M1 để vừa budget. Với câu mơ hồ khó nhận biết bằng rule, schema rewrite phải cho phép yêu cầu làm rõ; không tuyên bố rule nhận diện mọi cách viết ngày tự nhiên.
- [ ] Chạy lại test; rà 12 seed dev về giữ điều kiện và phạm vi thời gian, ghi trường hợp fail để T03/T04 kiểm lại. Không đọc test để chỉnh prompt.
- [ ] Commit rewrite/context/policy sau khi pass.

### T03 — OpenAI generation và citation validation (6 giờ)

**Files:** Create `backend/app/providers/openai_generation.py`, `backend/app/rag/citations.py`, `backend/app/rag/generation.py`, `backend/tests/test_openai_provider.py`, `backend/tests/test_citations.py`, `backend/tests/test_generation.py`, `backend/tests/test_generation_live.py`; modify `backend/app/core/config.py`, `backend/pyproject.toml` và lockfile dependency hiện có.

**Interfaces:** `OpenAIGenerationProvider` implements protocol T02. `validate_draft(context: ServingContext, bundle: ContextBundle, draft: GenerationDraft) -> ValidatedAnswer`; `generate_answer(context: ServingContext, question: str, bundle: ContextBundle, provider: GenerationProvider, deadline: float) -> ValidatedAnswer`. Validation failures có mã cố định dùng cho repair; reply text dựng từ validated claims, metadata/citations chỉ do backend cấp.

- [ ] Preflight: chọn model ID cụ thể theo quyền account, khóa SDK/tokenizer tương thích, xác nhận schema/encoding/context window và cấu hình secrets. API key do môi trường cung cấp, không yêu cầu gửi vào chat. Nếu thiếu quyền/model thì không ghi live acceptance là pass.
- [ ] Viết `test_provider_refusal_incomplete_and_invalid_json`, `test_transport_retry_deadline`, `test_openai_payload_is_bounded_and_store_false`; assertions cho 401 không retry, 429 retry tối đa một lần, timeout thành 504, không echo provider raw error chứa thông tin nhạy cảm.
- [ ] Viết `test_unknown_source_or_wrong_snapshot_rejected`, `test_db_quote_and_canonical_span_match`, `test_empty_source_list_rejected`, `test_repair_only_once`, `test_no_free_text_outside_validated_claims`, `test_irrelevant_context_can_abstain`. Test passage chứa chỉ dẫn giả bằng test double để kiểm backend không nhận nguồn giả; kiểm hành vi model thật bằng mẫu dev riêng.
- [ ] Chạy các test mới để thấy fail; implement SDK Responses structured output, retry/deadline, repair và validator. Không coi source ID hợp lệ là bằng chứng claim đúng nghĩa.
- [ ] Khi chạy real adapter qua HTTP, áp dụng `postman:api-simulation`: chạy backend thật với OpenAI upstream mô phỏng cho success/429/5xx/timeout/refusal/incomplete. Fixture phải mô phỏng đúng wire response Responses API, không chỉ trả object draft nội bộ; lưu định nghĩa simulation local và lệnh chạy thực tế, không publish.
- [ ] Chạy test local, simulation và một smoke OpenAI thật trên seed dev: câu có căn cứ, câu thiếu căn cứ và passage injection. Fixture injection dùng context riêng trong test, không chỉnh corpus M1. Live test opt-in bằng marker `live` được đăng ký trong `pyproject.toml`; thiếu key ghi not run rõ ràng, không thay bằng stub rồi nhận đã tích hợp thật. Kiểm quote/citation bằng DB và review claim thủ công.
- [ ] Ghi model/prompt/SDK versions, usage, latency và kết quả thực tế; commit provider/generation/validator/tests. Nếu simulation CLI bị giới hạn entitlement, theo skill bootstrap báo blocker, không tuyên bố đã kiểm upstream fault qua simulation.

### T04 — Chat, lịch sử, nguồn và nghiệm thu (5 giờ)

**Files:** Create `backend/app/chat/service.py`, `backend/app/api/chat.py`, `backend/tests/test_chat_api.py`, `backend/tests/test_m4_flow.py`, `backend/contracts/postman/m4/`, `backend/scripts/build_m4_collection.py`, `backend/scripts/run_m4_postman.py`, `backend/reports/m4-report.md`, `infra/compose.m4.yml`; modify `backend/app/main.py`, `backend/app/chat/repository.py`, `backend/README.md`, `README.md`, `backend/contracts/openapi.json`, `backend/scripts/verify_compose.py`.

**Interfaces:** `send_message(owner_id: UUID, conversation_id: UUID, body: ChatRequest, idempotency_key: str, request_id: str) -> ChatResult`; `list_conversations(owner_id: UUID, limit: int, cursor: str | None) -> ConversationPage`; `list_messages(owner_id: UUID, conversation_id: UUID, limit: int, cursor: str | None) -> MessagePage`; `read_citation(owner_id: UUID, message_id: UUID, citation_id: UUID) -> CitationDTO`; `read_trace(owner_id: UUID, message_id: UUID) -> TraceDTO`. Service dùng T00 reserve/finalize, T01 retrieval, T02 policy/context và T03 generation.

- [ ] Viết `test_chat_answer_followup_and_abstention`, `test_historical_citation_survives_activation`, `test_history_and_trace_reject_other_owner`, `test_pagination_and_key_replay`, `test_provider_failure_persists_failed_turn`, `test_expired_lease_prevents_late_finalize`. Assertion nguồn cũ so chính xác quote, version, serving ID và canonical offsets.
- [ ] Chạy test mới để thấy fail; nối pipeline, endpoint history/source/trace, error mapping và transaction kết quả. Xác thực ownership trước khi gọi model hoặc đọc dữ liệu nhạy cảm.
- [ ] Compose M4 dùng file M3 làm base, thêm model-cache read-only mount cho **API** (M3 chỉ worker có mount), OpenAI env chỉ cho API, giữ tên volume/project runtime hiện có. Không tạo lại dữ liệu M3; verify Compose dùng project/database riêng và cleanup chỉ tài nguyên của lần kiểm đó.
- [ ] Thêm collection M4: login hai user, cả ba search modes, trả lời, follow-up, thiếu căn cứ, ngày chưa xác minh, mở quote, owner isolation, history pagination, key replay/conflict và lỗi provider qua simulation. Dùng fixtures seed dev; cập nhật OpenAPI từ app. Giữ collection M3 để kiểm regression admin, không ghi đè scripts/assertions cũ.
- [ ] Runner M4 chỉ reset dedicated verification DB sau guard, chạy backend HTTP thật, E5 thật; provider mô phỏng cho acceptance xác định, live smoke chạy riêng. Credentials runtime nằm trong `.runtime`, tắt report events như runner M3; in exit code và số assertions, không chỉ HTTP 200.
- [ ] Chạy toàn bộ cổng bên dưới; lập report phân biệt unit/mock, PostgreSQL, upstream simulation và OpenAI live. Rà tay mẫu dev có multi-unit, thiếu căn cứ và injection; không ghi Recall/MRR hoặc chất lượng pháp lý đã đạt nếu chưa đo.
- [ ] Commit integration/docs/report sau khi checks pass. Không tự merge/publish/deploy.

## Cổng nghiệm thu và lệnh chạy dự kiến

Các lệnh dưới đây **dành cho lúc triển khai**, chưa được chạy để chứng minh M4. Chạy ở repo root, tuần tự; chuẩn bị verification DB và migration trước. Live smoke có thể phát sinh phí OpenAI, chỉ chạy số mẫu nhỏ đã định và ghi usage.

```powershell
backend/.venv/Scripts/python backend/scripts/verification_db.py
backend/.venv/Scripts/python backend/scripts/migrate_verification.py
backend/.venv/Scripts/python backend/scripts/verify_fresh_migration.py
backend/.venv/Scripts/python -m pytest backend/tests -m "not live" -q
backend/.venv/Scripts/ruff check backend/app backend/tests backend/scripts
backend/.venv/Scripts/python -m evaluation.dataset validate
backend/.venv/Scripts/python -m unittest discover -s evaluation/tests -q
backend/.venv/Scripts/python -m unittest discover -s data/tests -q
backend/.venv/Scripts/python backend/scripts/export_openapi.py
backend/.venv/Scripts/python backend/scripts/build_m4_collection.py
postman collection lint backend/contracts/postman/m3
postman collection lint backend/contracts/postman/m4
backend/.venv/Scripts/python backend/scripts/run_postman.py
backend/.venv/Scripts/python backend/scripts/run_m4_postman.py
backend/.venv/Scripts/python -m pytest backend/tests/test_generation_live.py -m live -q
backend/.venv/Scripts/python backend/scripts/verify_compose.py
```

T03/T04 phải bổ sung lệnh simulation chính xác từ CLI help và tài nguyên được tạo vào README trước bàn giao; không ghi lệnh giả định chưa được xác minh.

- [ ] Ba retrieval modes dùng cùng serving/profile/date; kết quả không chứa chunk ngoài membership hoặc chưa approved.
- [ ] Câu seed có căn cứ trả ít nhất một claim đã kiểm, nguồn/quote mở lại đúng DB; không có nguồn giả vượt validator trong regression suite.
- [ ] Không context thì không gọi generation; context không liên quan cho phép abstain; ngày chưa xác minh không trả kết luận pháp lý.
- [ ] Snapshot đổi giữa lượt hoặc sau khi lưu không làm đổi nguồn đã trích.
- [ ] User khác không truy cập conversation/message/citation/trace; pagination và replay hoạt động theo contract.
- [ ] Lỗi provider có request ID và HTTP error riêng; failed turn được lưu, không có assistant answer giả hoặc citation dở dang.
- [ ] API chạy được từ Compose với E5 cache; có bằng chứng smoke OpenAI thật, không chỉ stub. Nếu chưa chạy live, report ghi rõ M4 còn thiếu cổng tích hợp thật.
- [ ] M1/M2 validator vẫn pass; report ghi cấu hình, giới hạn corpus/ngày, kết quả từng lớp kiểm thử, reviewer và vấn đề còn mở.

## Bàn giao cho M5/M6

M5 nhận OpenAPI, collection M4, response examples và quy tắc owner/history/source. Frontend render trạng thái `answered/insufficient_evidence/out_of_scope/needs_clarification`, nguồn theo citation endpoint và lỗi kỹ thuật riêng; bổ sung refresh/logout ở phần auth của M5.

M6 nhận trace, runner/search có đủ ba mode, corpus/serving/profile/model/prompt IDs cố định. Chốt công thức Recall@5/MRR@10 và cách chấm abstention trước khi mở test; không dùng kết quả test để quay lại chọn tham số M4. Chất lượng suy luận/grounding phải được rà soát riêng với kiểm citation bằng cấu trúc.
