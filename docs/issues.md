# Issues (backlog)

Mục đích: giữ lại việc **đã biết nhưng cố ý chưa làm**, kèm bằng chứng, để xử lý sau mà không
phải điều tra lại. Mỗi issue một mục `## ISSUE-NNNN`. Không phải spec — chỉ là điểm vào.

---

## ISSUE-0001 — Xoá tài khoản + export toàn bộ dữ liệu của người dùng

- **Trạng thái**: chưa làm (open)
- **Nguồn**: `.pi-flow/0001-production-readiness/` — pha grill vòng 3/5 (2026-11-04), khi bàn
  hướng ToS. Người dùng chốt: tách khỏi đợt ToS, ghi issue để xử lý sau.
- **Mức**: cần spec riêng (đổi DB + route + UI + chính sách dữ liệu), không phải việc lẻ.

### Vấn đề
Người dùng **không có cách**:
1. **Xoá tài khoản** của mình. Hiện chỉ xoá được **từng job**.
2. **Tải về toàn bộ dữ liệu** liên quan tới mình (chỉ tải được từng artifact của từng job).

Với một app nhận tài liệu thật của người khác (hoá đơn, hợp đồng), thiếu 2 đường này là điểm
không thể bào chữa khi mở cho người ngoài — và cũng là câu "quyền của bạn" trong trang
`/legal` không thể viết cho trung thực.

### Bằng chứng
- `[ĐÃ KIỂM CHỨNG]` Router không có route xoá user: chỉ có `DELETE /api/jobs/{id}`
  (`server/app/routers/jobs.py:1747`) và admin `DELETE /api/admin/settings/{key}`
  (`server/app/routers/admin.py` mục `delete_setting`).
- `[ĐÃ KIỂM CHỨNG]` Không có route export tổng: `server/app/routers/exports.py` chỉ export theo job.
- `[ĐÃ KIỂM CHỨNG]` Dữ liệu gắn với user nằm rải ở nhiều bảng: `users`
  (`server/app/core/models.py:31`), `jobs` (`:224`, gồm `result` JSONB và `ir_json`),
  `ocr_suggestions` (`:379`), `document_versions` (`:337`), `feedbacks` (`:151`),
  `page_views` (`:172`), `request_logs` (`:185`), và `email_sends` (theo `to_email`, `:92`).
- `[ĐÃ KIỂM CHỨNG]` Artifact trên storage nằm theo prefix: uploads, `exports/{id}/`, `crops/{id}/`,
  `versions/{id}/` (`server/app/routers/jobs.py:1754-1762`, `server/app/services/storage.py:19-28`).
- `[ĐÃ KIỂM CHỨNG]` Purge hiện tại chỉ phủ **file gốc** của job `done`+`auto_purge`
  (`server/app/services/purge.py:58-80`) — không phủ text/IR/versions.

### Phạm vi đề xuất khi làm
- **Xoá tài khoản**: `DELETE /api/me` (yêu cầu nhập lại mật khẩu) → xoá cascade có kiểm soát:
  storage prefix của mọi job của user, `jobs` + `result`/`ir_json`, `ocr_suggestions`,
  `document_versions`, `feedbacks`, `page_views`, `request_logs` (hoặc ẩn danh `user_id`),
  `refresh_tokens`, `email_sends` theo email; sau đó xoá `users` row. Cần quyết: xoá cứng hay
  soft-delete + thời gian chờ.
- **Export**: `GET /api/me/export` → 1 zip gồm metadata + mọi artifact còn sống; giới hạn kích thước
  hoặc chạy nền nếu lớn (repo chưa có job nền ngoài APScheduler).
- **UI**: mục trong avatar menu (đã có chỗ: `web/src/App.tsx` `nav-user-menu`) + trang xác nhận,
  dùng `ConfirmDialog` sẵn có; không thêm dependency.
- **Trang `/legal`**: sau khi có 2 đường này thì sửa câu "quyền của bạn" thành lời hứa thật.

### Rủi ro cần cân
- Xoá cứng là không hoàn tác. Cần confirm 2 bước + ghi log trước khi xoá.
- `request_logs` giữ IP/UA: xoá hết làm mất dấu vết audit; ẩn danh `user_id` có thể là lựa chọn tốt hơn.
- Job đang `extracting`/`rendering` lúc xoá → phải chặn hoặc huỷ trước (worker còn chạy trên Kaggle).

### Tiêu chí xong (khi làm)
- `DELETE /api/me` xoá sạch: `select count(*)` trên mọi bảng theo user = 0, storage prefix rỗng.
- `GET /api/me/export` trả file mở được, chứa đủ artifact.
- Không còn hàng `jobs` nào trỏ tới user đã xoá (FK/session_id không treo).
- `pytest` + `npm test` xanh; migration idempotent nếu thêm cột/xoá mềm.
