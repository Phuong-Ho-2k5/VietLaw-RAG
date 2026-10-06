# M1: rà soát và phát hành corpus

`selected-contexts.zip` là dữ liệu ứng viên. `candidate-decisions.jsonl` chỉ giúp ưu tiên rà soát; `candidate_topics` và nhánh URL không xác nhận nội dung hoặc hiệu lực. Người duyệt có thể đưa một bản ghi `not_prioritized` vào phạm vi nếu tự kiểm tra và gắn `topic_tags`.

## Chạy pipeline

```powershell
python -m data.m1 candidates
python -m data.m1 prepare --raw-id 129823 --raw-id 208105 --raw-id 289397
python -m data.m1 release
python -m unittest discover -s data/tests -v
```

`candidates` đọc toàn bộ passage và lưu bằng chứng keyword có span; nhánh URL lao động và `--core-record-id` là tín hiệu ưu tiên bổ sung. Không có tín hiệu chỉ mang nghĩa `not_prioritized`, không phải kết luận ngoài phạm vi.

`prepare` ghi `prepared/<raw_id>.json` gồm raw text, canonical text, mapping offset, cây legal units và các lỗi parse; đồng thời tạo `review-template.jsonl` ở trạng thái `pending`. Có thể bỏ `--raw-id` để chuẩn bị toàn bộ ứng viên. Thư mục `prepared/` không được commit; chạy lại lệnh để tái tạo. Template mới không ghi đè `reviews.jsonl`.

`release` đọc `reviews.jsonl`, ghi `labor-corpus-v1.json`, `quarantine.jsonl`, `review-report.json` và snapshot theo hash. Chưa có quyết định duyệt thì manifest có `active: false` và không chứa chunk. Báo cáo có `m1_complete: false` cho đến khi có corpus đạt cổng và hỗ trợ đủ 5 chủ đề. Corpus lõi hiện có 10 chunk thuộc đủ 5 chủ đề, với `as_of_date: 2026-02-12`; nguồn và quyết định của reviewer Codex được lưu ở cấp unit.

M1 chỉ dùng thư viện chuẩn Python 3.10 trở lên. Đặt ZIP gốc tại root; M0 inventory phải khớp ZIP. Khi mã pipeline, cấu hình, ZIP hoặc inventory thay đổi, chạy lại `candidates` và `prepare`; quyết định duyệt cũ có hash khác sẽ bị cách ly.

## Ghi một quyết định duyệt

Mỗi dòng `reviews.jsonl` là một JSON object. Ví dụ cấu trúc (giá trị chỉ minh họa, **không phải văn bản đã duyệt**):

```json
{
  "raw_id": 123,
  "raw_sha256": "64 ký tự hex từ prepared document",
  "canonical_sha256": "64 ký tự hex từ prepared document",
  "decision": "approve",
  "reviewer": "Tên người duyệt",
  "reviewed_at": "2026-10-05",
  "as_of_date": "2026-02-12",
  "title": "Tên văn bản đã đối chiếu",
  "topic_tags": ["contract"],
  "official_source_url": "https://vbpl.vn/...",
  "official_source_sha256": "Hash bytes của tài liệu tải về nếu có",
  "document_number": "Số hiệu đã đối chiếu",
  "document_type": "Loại văn bản",
  "issuing_body": "Cơ quan ban hành",
  "issued_on": "2020-01-01",
  "effective_from": "2021-01-01",
  "effective_to": null,
  "effective_conclusion": "effective_for_as_of_date",
  "source_checked_at": "2026-10-05",
  "text_match": true,
  "structure_reviewed": true,
  "approved_unit_ids": ["unit_id của khoản hoàn chỉnh hoặc điều không có khoản"],
  "unit_topic_tags": {"unit_id ở trên": ["contract"]},
  "checked_unit_ids": ["unit_id của điều/khoản đã kiểm thủ công"],
  "evidence_note": "URL/trang, các đoạn đã đối chiếu và kết quả",
  "amendment_note": "Quan hệ sửa đổi/bãi bỏ đã kiểm và phạm vi còn áp dụng"
}
```

`topic_tags` chỉ nhận `contract`, `probation`, `wages`, `hours_rest`, `termination`. Nguồn chính thức phải dùng HTTPS tại `vbpl.vn`, `chinhphu.vn` (gồm subdomain) hoặc tên miền `.gov.vn`; [Cơ sở dữ liệu quốc gia về văn bản pháp luật](https://vbpl.vn/) là một điểm tra cứu. Người duyệt cần mở văn bản gốc, kiểm số hiệu, loại, cơ quan, ngày ban hành, nội dung tương ứng, tình trạng sửa đổi/bãi bỏ và hiệu lực tại ngày duyệt. URL đúng miền và các trường được điền **không tự chứng minh** các kết luận này.

Chỉ các unit trong `approved_unit_ids` được tạo chunk. Mỗi unit phải có `unit_topic_tags` trong phạm vi đã duyệt; một tài liệu rộng không tự đưa mọi điều vào corpus. `text_match` và kết luận hiệu lực áp dụng cho các unit được chọn. `effective_to` là ngày hết hiệu lực, không nằm trong khoảng áp dụng `[effective_from, effective_to)`; `null` thể hiện chưa có ngày kết thúc được xác định, không chứng minh hiệu lực vô thời hạn.

`reviewed_at` là ngày tiến hành rà soát; `as_of_date` là thời điểm pháp luật được xác minh, có thể sớm hơn ngày rà soát. Dùng `effective_for_as_of_date` cùng ngày xác minh cụ thể; `effective_as_of_review` chỉ dùng khi xác minh tại đúng ngày rà soát. Snapshot ghi `temporal_scope.policy: only_explicit_verified_dates`; ingestion/RAG phải giữ phạm vi này khi phục vụ câu hỏi có thời điểm. Corpus lõi hiện được xác minh tại 12/02/2026; cần rà soát thêm trước khi phục vụ thời điểm khác.

Có thể thêm `unit_source_evidence` theo unit ID (URL/PDF hash, số trang, ngày kiểm, kết quả) để chunk giữ vị trí đối chiếu nguồn. Corpus lõi đã lưu đầy đủ các trường này, cùng nhật ký `unit-review-audit.jsonl`.

Nếu không đủ chứng cứ, ghi `decision: "reject"` cùng `reason_code`/`evidence_note`, hoặc để `pending`; pipeline không kích hoạt bản ghi. Không gán `effective_from` bằng ngày truy cập. Nếu không rõ hiệu lực, không ghi `effective_as_of_review`. Hai quyết định cho cùng raw ID bị cách ly với `CONFLICTING_REVIEW`; ID không tồn tại làm lệnh dừng để người duyệt sửa lỗi nhập.

## Kiểm cấu trúc và snapshot

Chuẩn hóa NFC, xuống dòng LF, khoảng trắng cuối dòng và dòng trống; giữ whitespace nội bộ để bảo toàn bảng. `offset_map` có mapping chính xác cho đoạn không đổi; dòng đã đổi mapping về toàn dòng raw, không giả định ánh xạ từng ký tự. Mỗi unit có span canonical và raw để mở lại bản gốc.

Parser nhận chương/mục, tiêu đề điều có dấu `.` hoặc `:`, khoản và điểm có nhãn rõ ràng, kể cả heading xuống dòng. Không gán nhãn điều cho dòng tham chiếu dạng “Điều 93 của Bộ luật”. `parse_confidence: explicit_labels` mô tả cách trích nhãn; người duyệt vẫn phải kiểm heading, khoản, điểm, bảng, phần text cắt và ngoại lệ trước khi đặt `structure_reviewed: true`. Clause chunk giữ toàn bộ các điểm và điều kiện bên trong; giữ chunk dài để duyệt thay vì tự cắt điều kiện pháp lý theo số ký tự.

Điền `checked_unit_ids` bằng ít nhất 10 điều/khoản khác nhau cho **mỗi loại văn bản** trong corpus (có thể cộng qua nhiều tài liệu). Unit phải thuộc phần đã chọn hoặc article parent của phần đó. Pipeline đếm các ID hợp lệ và cách ly loại văn bản thiếu mẫu với `INSUFFICIENT_STRUCTURE_SAMPLES`. Unit có nhãn trùng/không theo thứ tự bị cách ly với `AMBIGUOUS_LEGAL_STRUCTURE`; có thể chọn phần khác không có lỗi, nhưng không xác nhận phần lỗi bằng cách chỉ đổi một cờ boolean.

`labor-corpus-v1.json` là manifest hiện tại; `snapshots/<manifest_hash>.json` lưu bản theo nội dung. Alias chỉ cập nhật sau khi snapshot được ghi/kiểm. Mỗi chunk giữ raw ID, version, legal unit IDs, topic được duyệt, điều/khoản, canonical/raw offsets, nguồn và reviewer. Manifest giữ code hash, cấu hình, ZIP/inventory/candidate/review hashes, phạm vi và thời điểm duyệt. Hash ZIP/raw record là hash bytes; hash JSONL dùng JSON UTF-8 chuẩn (key được sắp xếp, LF) để LF/CRLF hoặc cách căn JSON không thay đổi snapshot. Code hash chuẩn hóa xuống dòng LF. File snapshot cũ bị sửa sẽ làm lệnh dừng trước khi đổi alias.

Khử trùng theo số hiệu, cơ quan, ngày ban hành, khoảng hiệu lực và canonical hash; giữ `raw_record_ids`, provenance và log `DUPLICATE_VERSION`. Cùng nội dung ở khoảng hiệu lực khác nhau được giữ thành version khác. Quyết định merge các bản khác nhau vẫn cần reviewer.

## Kiểm nguồn đã thực hiện

Xem `data/manifests/m1/source-checks.jsonl` và `unit-review-audit.jsonl`. Record `129823` chứa bản gốc 45/2019/QH14; đã đối chiếu metadata và 10 unit với [bản hợp nhất 18/VBHN-VPQH ngày 12/02/2026](https://vanban.chinhphu.vn/?docid=217002&pageid=27160). PDF scan được kiểm trực quan; hash và số trang được lưu trong từng unit. Reviewer là Codex (assistant), được ghi rõ trong quyết định. Corpus chỉ đưa các unit đã chọn vào chunk; các phần chưa kiểm hoặc có lỗi parse giữ ngoài tập phục vụ trả lời.
