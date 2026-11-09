# Dữ liệu demo

Máy mới không có GPU thì job upload sẽ nằm `queued` vô hạn, và DB trắng thì
người xem chỉ thấy empty state. Thư mục này nạp sẵn dữ liệu để mở app là thấy
ngay kết quả OCR thật.

```bash
docker compose -f deploy/docker-compose.dev.yml up -d
docker compose -f deploy/docker-compose.dev.yml exec -T server \
    python /app/deploy/demo/seed.py
# đăng nhập: demo@img2text.dev / demo-2024-pw
```

Đổi tài khoản: `DEMO_EMAIL` / `DEMO_PASSWORD` trong môi trường container.

## Nó tạo gì

| | |
|---|---|
| Tài khoản | `demo@img2text.dev`, `is_verified=true`, `ocr_enabled=true` (không cần SMTP) |
| Job 1 | Đề thi Ngữ văn (1 trang) — 19 gợi ý sửa lỗi OCR |
| Job 2 | Đáp án đề thi Tiếng Anh (1 trang) — 5 gợi ý sửa lỗi |

`result` (regions + markdown), `ocr_suggestions`, và ảnh trang gốc đều là dữ
liệu thật lấy từ job đã chạy qua PaddleOCR-VL. IR không cần lưu: export tự
sinh lại từ `result` và cache vào `jobs.ir_json`.

Idempotent: chạy lại sẽ xoá job cũ **của tài khoản demo** rồi tạo lại, không
đụng dữ liệu user khác.

## File

```
seed.py                     # script nạp
de-thi-ngu-van.{jpg,json}   # fixture: ảnh + result + suggestions
de-thi-tieng-anh.{jpg,json}
```

`.json` có `slug, filename, file_type, page_count, image, sha256, result,
suggestions`. Muốn thêm bản mẫu khác: chạy một job thật rồi dump cùng cấu trúc
(ảnh + `result::text` + rows `ocr_suggestions`), thả vào đây là seed tự nhặt
(`deploy/demo/*.json`).
