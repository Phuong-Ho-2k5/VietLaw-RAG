# M1 — báo cáo triển khai và cổng nghiệm thu

Ngày rà soát: 2026-10-05. **M1 đã phát hành corpus lõi v1 cho đủ 5 chủ đề**, gồm 10 chunk từ Bộ luật Lao động, có đối chiếu nguồn và 10 mẫu cấu trúc. Phạm vi pháp luật được pin tại **12/02/2026**, ngày của bản hợp nhất đối chiếu. Reviewer là **Codex (assistant; visual comparison of official PDF)**. `review-report.json` ghi `m1_complete: true` cho phạm vi này; việc mở rộng nội dung hoặc thời điểm cần lượt rà soát mới.

| Task | Phần đã triển khai | Phần còn phải hoàn tất |
|---|---|---|
| M1-T01 | Đọc toàn bộ 8.532 inventory rows; tín hiệu URL/tên/full text, bằng chứng có span, lựa chọn luật lõi của reviewer | Rà soát phạm vi thực của ứng viên; nhãn tự động chỉ giúp ưu tiên |
| M1-T02 | Validator metadata, nguồn HTTPS, hash nội dung, mốc áp dụng và log reviewer; đối chiếu 10 unit của record 129823 với nguồn chính thức | Rà soát các ứng viên khác khi mở rộng corpus |
| M1-T03 | NFC/newlines/blank lines với raw mapping; cây chương/mục/điều/khoản/điểm; đã kiểm trực quan 10 unit thuộc loại Bộ luật | Phần lỗi parse giữ ngoài unit được duyệt; loại văn bản mới cần ít nhất 10 mẫu riêng |
| M1-T04 | Đã phát hành 10 chunk cho đủ 5 chủ đề; khử trùng có provenance và khoảng hiệu lực; snapshot theo hash, alias và quarantine | Mở rộng phạm vi bằng snapshot mới có rà soát |

## Số liệu chạy trên ZIP thật

- ZIP SHA-256: `48100aad58f3827bd25efd181487f76b00c59a9d1a11ba27c67bbeb030de2723`.
- 8.532 bản ghi được ghi nhận: 2.288 ứng viên ưu tiên, 6.224 chưa được ưu tiên, 20 passage rỗng cách ly.
- Nhánh URL `Lao-dong-Tien-luong`, không phân biệt hoa/thường: 468 rows (gồm 1 passage rỗng). M0 thống kê riêng nhánh viết hoa là 459 và nhánh viết thường là 9.
- Topic signals có thể chồng lấp: hợp đồng 845, thử việc 123, tiền lương 1.401, thời giờ/nghỉ ngơi 201, chấm dứt 490. Đây không phải số văn bản hợp lệ theo chủ đề.
- Đã tạo bản chờ duyệt cho 5 records: 129823, 208105, 289397, 245505, 277743. Hai records có phần cấu trúc cần xử lý; unit lỗi không thể được phát hành qua cổng duyệt.
- Corpus hiện tại: 1 document/version có unit được duyệt, 10 chunk active; 8.531 rows còn lại có lý do cách ly/chờ rà soát. Trong đó 2.287 ứng viên ưu tiên chưa duyệt.

## Phạm vi corpus lõi

| Chủ đề | Unit đã đối chiếu | Trang PDF / số trang in trên văn bản |
|---|---|---|
| Hợp đồng | Điều 13 khoản 1, 2 | 7 / 7 |
| Thử việc | Điều 24 khoản 1; Điều 26 | 11 / 11 |
| Tiền lương | Điều 90 khoản 1, 2 | 35 / 37 |
| Thời giờ làm việc | Điều 105 khoản 1, 2 | 40 / 42 |
| Chấm dứt hợp đồng | Điều 34 khoản 2, 3 | 14 / 14 |

Đây là phạm vi kiến thức hẹp của corpus v1. Chỉ các unit trên được tạo chunk; toàn bộ nội dung một văn bản hoặc mọi câu hỏi trong một chủ đề không mặc nhiên được hỗ trợ. `temporal_scope` giới hạn các câu hỏi về thời điểm tại 12/02/2026. Câu hỏi thiếu chứng cứ hoặc ngoài mốc này cần được RAG từ chối/làm rõ ở M4.

## Chứng cứ nguồn đã tìm

Record 129823 chứa bản gốc Bộ luật Lao động 45/2019/QH14. Đã đối chiếu metadata chính thức và [bản hợp nhất 18/VBHN-VPQH, ngày 12/02/2026](https://vanban.chinhphu.vn/?docid=217002&pageid=27160), tải PDF 86 trang và lưu SHA-256. PDF scan được kiểm trực quan trên trang 1, 7, 11, 14, 35, 40; các unit được chọn khớp từ ngữ, nhãn và điều kiện, với khác biệt ở xuống dòng/khoảng trắng trình bày. Nhật ký nguồn, mẫu cấu trúc và quyết định reviewer nằm trong `source-checks.jsonl`, `unit-review-audit.jsonl` và `reviews.jsonl`. Các phần đã sửa đổi hoặc chưa kiểm của bản gốc giữ ngoài tập chunk active.

## Kiểm chứng

`python -m unittest discover -s data/tests -v`: 27 tests qua. Các ca kiểm bao gồm nguồn chưa đủ chứng cứ, thời điểm hiệu lực, hash review bị cũ, coverage manifest, nhãn điều tham chiếu, heading xuống dòng, scope ở cấp unit, mẫu cấu trúc thiếu, offsets, trùng phiên bản, snapshot lặp lại, LF/CRLF, console Windows CP1258 và phân biệt ngày rà soát với ngày áp dụng pháp luật.

Chạy lại theo [hướng dẫn M1](../../M1_REVIEW.md). Dữ liệu chuẩn bị và PDF tải về được giữ ngoài Git, có thể tái tạo từ ZIP/URL cùng hash; quyết định đã rà soát nằm trong `reviews.jsonl`, ràng buộc với raw/canonical hashes. Snapshot không tự cập nhật khi văn bản thay đổi.
