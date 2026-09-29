# VietLaw RAG

VietLaw RAG là dự án hỏi đáp pháp luật lao động Việt Nam sử dụng **Retrieval-Augmented Generation (RAG)**. Hệ thống hướng đến việc tìm kiếm các quy định liên quan và tạo câu trả lời tiếng Việt kèm trích dẫn điều, khoản và nguồn văn bản.

## Mục tiêu

- Hỗ trợ người dùng tra cứu các câu hỏi phổ biến về pháp luật lao động.
- Trả lời dựa trên nội dung của văn bản đã được đưa vào hệ thống.
- Cho phép người dùng kiểm tra điều khoản và nguồn được sử dụng trong câu trả lời.
- So sánh chất lượng của tìm kiếm từ khóa, tìm kiếm vector và tìm kiếm kết hợp.

## Phạm vi ban đầu

Phiên bản đầu tiên tập trung vào:

- Hợp đồng lao động.
- Thử việc.
- Tiền lương.
- Thời giờ làm việc và nghỉ ngơi.
- Chấm dứt hợp đồng lao động.

## Chức năng dự kiến

- Đăng ký, đăng nhập và phân quyền người dùng/quản trị viên.
- Hỏi đáp pháp luật lao động bằng tiếng Việt.
- Trả lời kèm tên văn bản, điều, khoản và đoạn trích nguồn.
- Lưu lịch sử hội thoại.
- Nhập, xử lý và duyệt văn bản pháp luật trước khi đưa vào tra cứu.
- Đánh giá chất lượng truy xuất và độ chính xác của trích dẫn.

## Công nghệ dự kiến

| Thành phần | Công nghệ |
|---|---|
| Frontend | React, TypeScript, Vite |
| Backend | Python, FastAPI |
| Database | PostgreSQL, pgvector |
| ORM và migration | SQLAlchemy, Alembic |
| Authentication | JWT, Argon2 |
| Testing | pytest, Playwright |
| Deployment | Docker Compose |

## Trạng thái

Dự án đang trong giai đoạn khởi tạo và thiết kế. Mã nguồn ứng dụng sẽ được phát triển theo từng milestone trong kế hoạch dự án.

## Lưu ý

VietLaw RAG là dự án học tập và tra cứu thông tin. Kết quả từ hệ thống không thay thế tư vấn pháp lý chuyên nghiệp; người dùng cần đối chiếu văn bản gốc và thời điểm áp dụng.
