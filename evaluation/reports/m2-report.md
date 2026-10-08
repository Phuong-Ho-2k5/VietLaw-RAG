# Báo cáo M2 v1

Ngày rà soát: **08/10/2026**. Reviewer nội dung: **Codex (assistant)**.
Chưa có rà soát chuyên gia pháp lý độc lập; không ghi đây là human review.

## Cổng nghiệm thu

| Task | Đầu ra và bằng chứng |
|---|---|
| M2-T01 | 12 seed có căn cứ hoặc lý do abstain, toàn bộ là subset dev; `evaluation/data/seed.jsonl`. |
| M2-T02 | 72 câu có reviewer, ngày review, note và evidence; 36 dev/36 test, đủ năm chủ đề trên tổng bộ. |
| M2-T03 | Validator schema/gold/temporal/leakage; `split-manifest.json` khóa nội dung, test giữ riêng cho đánh giá cuối. |

Số lượng: **48 answer** (20 direct, 21 scenario, 7 multi-unit), **24 abstain**
(12 insufficient evidence, 6 out of scope, 6 temporal). Mỗi tập có 24 answer
và 12 abstain; không có metric retrieval hay chất lượng LLM ở mốc này.

## Audit nguồn và nội dung

- Metadata [18/VBHN-VPQH](https://vanban.chinhphu.vn/?docid=217002&pageid=27160)
  được mở lại ngày 08/10/2026, khớp ngày ban hành 12/02/2026 và văn bản Bộ luật
  lao động. PDF chính thức quá lớn cho web tool; dùng bản PDF và ảnh trang
  đã lưu ở `data/sources/m1/` để đối chiếu trực quan.
- Điều 13 khoản 1–2, PDF trang 7: định nghĩa, tên gọi khác và nghĩa vụ giao kết.
- Điều 24 khoản 1, Điều 26, PDF trang 11: cách thỏa thuận thử việc và sàn 85%.
- Điều 34 khoản 2–3, PDF trang 14: hoàn thành công việc và thỏa thuận chấm dứt;
  đọc cả tiêu đề điều để giữ ý nghĩa của các khoản ngắn.
- Điều 90 khoản 1–2, PDF trang 35 (in 37): cấu phần lương và giới hạn tối thiểu.
- Điều 105 khoản 1–2, PDF trang 40 (in 42): 8/48 giờ, chế độ tuần 10/48 giờ,
  nghĩa vụ thông báo và khuyến khích 40 giờ. Không đổi khuyến khích thành bắt buộc.
- 48 đáp án được kiểm theo unit tương ứng; phép tính thử việc 8,5/6,8/10,2
  triệu và các tổng giờ 50/45/44 được tính lại. Câu tình huống chỉ kết luận
  trong phạm vi điều khoản được nêu, không xác nhận toàn bộ lịch làm việc hợp pháp.
- 12 câu thiếu chứng cứ được so với danh sách 10 chunk: các quy định cần hỏi
  chưa có trong snapshot, dù có thể xuất hiện ở trang PDF. Không dùng các phần
  ngoài unit M1 đã duyệt để tự tạo gold.
- 6 câu ngoài phạm vi không thuộc năm chủ đề lao động. 6 câu thời điểm có ngày
  không được xác minh hoặc dùng “hiện nay”; gold rỗng và hướng dẫn làm rõ/phải
  có nguồn cho thời điểm khác.

Evidence được lưu ngay trong mỗi dòng câu hỏi, mapping gold giữ số hiệu gốc
45/2019/QH14 và chunk ID; URL evidence trỏ bản hợp nhất dùng để đối chiếu.
Snapshot: `6ebc3836a333f2239e524d6016c0bdf7c11abe6751c4a1b9cd01185e74fb84b7`.
Freeze M2: `e959ebb7769d9be594d0fcc5bfc5f702084e4642bf59b0599ba91f26a5e84b78`.

## Giới hạn và quyết định triển khai

Corpus chỉ gồm 10 unit thuộc 6 điều trong một văn bản. Có 72 câu nhưng nhiều
câu cùng căn cứ; chỉ có 18 family, 9 mỗi tập. Không coi tổng câu là số lượng
vấn đề pháp lý độc lập. Chia theo điều và family thay vì văn bản giúp có hai
tập với gold, nhưng chủ đề dev/test lệch nhau; cần phân tích kết quả theo
nhóm và mở rộng nguồn trước khi kết luận khả năng tổng quát hóa.

Seed lấy từ dev để tránh dùng câu test làm ví dụ tinh chỉnh. Vì vậy seed chưa
bao phủ lương/giờ làm. Freeze là kiểm toàn vẹn và quy trình, không tạo kiểm
soát truy cập hoặc đảm bảo người tinh chỉnh chưa xem test. Chưa chọn tham số
retrieval trên bộ này và chưa có kết quả RAG.

## Kiểm chứng kỹ thuật

Các kiểm thử bao gồm: gold/số điều/khoản/nguồn sai, ngày sai, snapshot sai,
abstain có gold, thiếu evidence của multi-unit, seed khác dev, trùng Unicode,
rò rỉ article/family, corpus bị sửa hoặc inactive, số câu thiếu, freeze bị sửa,
CRLF/key order, tái tạo curation và CLI Windows.

Lệnh nghiệm thu:

```powershell
python -m evaluation.dataset validate
python -m unittest discover -s evaluation/tests -v
python -m unittest discover -s data/tests -v
```

Kết quả: **17/17 kiểm thử M2, 27/27 kiểm thử M0/M1 thành công**; validator
xác minh freeze và đủ 72 câu/12 seed. Reviewer kỹ thuật độc lập đã kiểm cả
72 bản ghi và tooling, không phát hiện lỗi Critical/Important.

Còn một lỗi nhỏ để sau: seed có `question_id` sai kiểu list gây `TypeError`
thay vì `ValueError` ở API Python; CLI vẫn từ chối với exit code 1, không
ghi freeze lỗi. Metadata và hash frozen không thay đổi trong lượt sửa tooling.
