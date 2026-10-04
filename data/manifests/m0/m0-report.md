# M0 — Báo cáo kiểm kê selected-contexts.zip

- SHA-256 ZIP: 48100aad58f3827bd25efd181487f76b00c59a9d1a11ba27c67bbeb030de2723
- Số file: 8,532; schema valid: 8,512; quarantine: 20.
- Thiếu trường name: 1,125; ID duy nhất: 8,532; URL duy nhất: 8,532.
- Nội dung không rỗng trùng sau chuẩn hóa khoảng trắng: 4 nhóm, 5 bản ghi dư.
- Độ dài passage (ký tự): trung vị 23,110.0, p90 90,141, p99 285,366, tối đa 5,983,358.
- URL ở nhánh Lao-dong-Tien-luong: 459; đây chỉ là tín hiệu phân loại sơ bộ.

## Schema quan sát được

| Bộ trường | Số file |
|---|---:|
| id,link,name,passage | 7,407 |
| id,link,passage | 1,125 |

## Lý do quarantine

| Mã | Số file |
|---|---:|
| EMPTY_PASSAGE | 20 |

## Nhánh URL lớn nhất

| Nhánh | Số file |
|---|---:|
| van-ban | 7,594 |
| cong-van | 540 |
| tcvn | 367 |
| TCVN | 31 |

## Giới hạn

Valid chỉ xác nhận cấu trúc bản ghi, không xác nhận chủ đề, nguồn có thẩm quyền, hiệu lực hay độ đầy đủ của văn bản. Nhánh URL chỉ là tín hiệu ưu tiên rà soát. Passage rỗng được cách ly trước bước chia đoạn và embedding.

Chạy lại: python -m data.inventory --zip selected-contexts.zip --output data/manifests/m0
