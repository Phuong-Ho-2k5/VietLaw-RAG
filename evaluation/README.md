# M2 — dữ liệu đánh giá

M2 v1 chứa **72 câu đã rà soát bởi Codex (assistant)**: 36 dev, 36 test.
Seed 12 câu là tập con chính xác của dev, không cộng thêm vào 72 câu.
Đây là bộ đánh giá cho corpus lõi M1 gồm 10 chunk, không đại diện toàn bộ
pháp luật lao động và chưa có rà soát độc lập bởi chuyên gia pháp lý.

## Sử dụng

Chạy tại thư mục gốc, dùng Python 3.10 trở lên, không cần cài dependency:

```powershell
python -m evaluation.dataset validate
python -m unittest discover -s evaluation/tests -v
python -m unittest discover -s data/tests -v
```

`validate` chỉ đọc dữ liệu, kiểm schema, gold, provenance, thời điểm, split và
đối chiếu hash với freeze. Lỗi trả exit code 1. Đường dẫn mặc định được giải
theo vị trí module, không phụ thuộc working directory; có thể dùng `--data`
và `--corpus` để chỉ định release/snapshot khác.

Chỉ dùng [dev](data/dev.jsonl) và [seed](data/seed.jsonl) để chọn chunk size,
embedding, bộ lọc, reranker và tham số retrieval. Giữ [test](data/test.jsonl)
cho lần đánh giá cuối sau khi chốt cấu hình. File test vẫn nằm trong repo;
freeze kiểm toàn vẹn, không ngăn người dùng mở hay tinh chỉnh trên test.

## Nội dung và chia tập

| Loại | Dev | Test | Tổng |
|---|---:|---:|---:|
| Căn cứ trực tiếp | 10 | 10 | 20 |
| Tình huống và tính toán đơn giản | 10 | 11 | 21 |
| Cần nhiều khoản | 4 | 3 | 7 |
| Thiếu chứng cứ trong corpus | 6 | 6 | 12 |
| Ngoài phạm vi | 2 | 4 | 6 |
| Thời điểm thiếu/chưa xác minh | 4 | 2 | 6 |
| **Tổng** | **36** | **36** | **72** |

48 câu có `expected_behavior: answer`; 24 câu có `abstain` và gold rỗng.
Abstain nghĩa là không đủ căn cứ để kết luận từ snapshot. Câu hỏi thời điểm
mơ hồ cần làm rõ, không mặc định áp dụng pháp luật tại ngày hiện tại.

Mọi câu thuộc cùng điều hoặc cùng `family_id` nằm một tập:

- Dev: Điều 13 khoản 1–2; Điều 24 khoản 1; Điều 34 khoản 2–3.
- Test: Điều 26 (không gán khoản giả); Điều 90 khoản 1–2; Điều 105 khoản 1–2.
- Các nhóm âm cũng tách theo nội dung: ví dụ thời gian thử việc chỉ ở dev,
  nghỉ hằng năm chỉ ở test; mọi biến thể cùng nhóm nằm cùng tập.

Corpus chỉ có một văn bản nên chia theo văn bản sẽ không tạo được hai tập
có gold. Chia theo điều và nhóm câu là lựa chọn của thiết kế dataset.
Hệ quả: các chủ đề không cân bằng giữa hai tập; dev không có câu trả lời
được về lương/giờ làm, test không có câu trả lời được về hợp đồng/chấm dứt.
Seed cũng không bao phủ đủ năm chủ đề. Cần báo cáo kết quả theo nhóm và
số mẫu, không coi 72 biến thể là 72 quy định độc lập.

## Schema và gold

Mỗi dòng là object JSON UTF-8, `schema_version: 1`. Validator từ chối trường
thiếu/thừa và nhãn không hợp lệ. Contract chính là
[`validate_dataset`](dataset.py); các nhóm trường:

| Nhóm | Trường |
|---|---|
| Nhận diện | `question_id`, `question`, `split`, `family_id`, `category` |
| Phạm vi | `scope`, `topic`, `as_of_date`, `snapshot_id` |
| Kỳ vọng | `expected_behavior`, `expected_answer`, `gold` |
| Rà soát | `reviewer`, `reviewed_at`, `review_note`, `evidence` |

`gold` là danh sách object gồm `document_number`, `article`, `clause`,
`point`, `chunk_id`; nhãn khoản/điểm chưa có dùng `null`. Các tham chiếu pháp
lý và chunk ID phải khớp chính xác corpus; nhiều khoản đòi hỏi nhiều gold.
Mỗi gold có evidence `legal_source`, URL PDF và trang PDF khớp nguồn M1.

Với câu âm, `evidence` có loại `corpus_scope`, snapshot và lý do thiếu chứng
cứ/ngoài phạm vi/thời điểm. Đây là chứng cứ về **giới hạn corpus**, không là
nguồn pháp lý khẳng định câu trả lời ngoài corpus. Đừng lấy nguồn âm làm
gold retrieval hay citation tích cực.

Gold được pin với snapshot
`6ebc3836a333f2239e524d6016c0bdf7c11abe6751c4a1b9cd01185e74fb84b7`,
chỉ xác minh ngày **12/02/2026**, văn bản gốc 45/2019/QH14. Rà soát nội dung
dùng [bản hợp nhất 18/VBHN-VPQH](https://vanban.chinhphu.vn/?docid=217002&pageid=27160).
Evidence lưu số trang PDF 7, 11, 14, 35, 40; trang PDF 35/40 tương ứng trang
in 37/42. Không nhầm ngày rà soát 08/10/2026 với ngày pháp luật được pin.

`expected_answer` là hướng dẫn chấm theo nghĩa và điều kiện, không yêu cầu
LLM khớp nguyên văn. Khi đo retrieval ở M6, chỉ 48 câu answer có gold hợp
lệ; báo riêng abstention trên 24 câu âm và các mẫu số tương ứng. Các câu
multi-unit cần kiểm đủ mọi gold; Recall@k có thể tính theo số gold tìm được,
MRR theo vị trí gold đầu tiên. Cần chốt cách tổng hợp trước khi mở test.

## Freeze và tạo phiên bản mới

[`split-manifest.json`](data/split-manifest.json) khóa hash ngữ nghĩa của
dev/test/seed, corpus, mapping gold và metadata review. Thay đổi câu, đáp án,
gold, split, reviewer hoặc snapshot làm xác minh thất bại. JSON key order và
LF/CRLF không đổi identity. Thử chạy `freeze` lại chỉ thành công khi nội dung
khớp freeze cũ; không có tùy chọn force để thay thế freeze.

```powershell
python -m evaluation.dataset freeze
```

Để kiểm tái tạo bộ v1, materialize bản curation vào **thư mục chưa tồn tại**:

```powershell
python -m evaluation.curate --output evaluation/releases/m2-v1-copy
python -m evaluation.dataset freeze --data evaluation/releases/m2-v1-copy
python -m evaluation.dataset validate --data evaluation/releases/m2-v1-copy
```

[`curate.py`](curate.py) lưu câu hỏi/đáp án do Codex soạn và rà soát, không
gọi LLM lúc chạy. Không dùng script để tự gắn nhãn review cho nội dung mới:
thay corpus hoặc câu hỏi cần đối chiếu nguồn và ngày lại, cập nhật audit,
reviewer, ngày review và release ID rồi phát hành ở đường dẫn mới.

Xem [báo cáo nghiệm thu](reports/m2-report.md) và [kế hoạch M2](M2_PLAN.md).
