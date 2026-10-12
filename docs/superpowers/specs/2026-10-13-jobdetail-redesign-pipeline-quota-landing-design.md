# Spec: Ảnh chụp điện thoại + JobDetail 2 section + pipeline crop/quota/landing (2026-10-13)

## Bối cảnh

User test E2E thật qua R2 dev: upload → job → Kaggle batch OCR. Raid bug + yêu cầu
mới: ảnh chụp điện thoại (JPEG-HEIC/JPEG-AV1, ngang/dọc, quét tài liệu), JobDetail
2 section dọc, preview styled, export 2 nhóm, pipeline crop→remove-background→MD,
landing mới + screenshot, quota 25/ngày-150/tuần, admin LLM timeout/token.

Evidance từ run thật (Version 20, T4x2): wheelhouse mới OK (133 pkg, onnxruntime
đúng extra), job jpg fail `cannot identify image file` (file `.jpg` thật ra là
`%PDF-1.7`), job pdf fail `'NoneType' object is not callable`
(`process_job(preprocess=...)` shadow module fn `preprocess`).

## Nguồn sự thật

- **OCR = PaddleOCR-VL** trên Kaggle T4x2, kernel `jhandf/img2text-batch`,
  wheelhouse dataset `img2text-wheelbuild-env` (uv --no-index, cp312).
- **Server** FastAPI + Postgres, storage R2 (presigned PUT/GET), worker = batch
  script kernel (manifest URL mode), orchestrate qua
  `server/app/services/kaggle_orchestrator.py`.
- **Web** Vite React SPA (`web/`), Design System `web/DESIGN.md`.

## Users (đã xác nhận)

1. **Giáo viên** — ảnh chụp đề/khối tài liệu thật → Markdown/DOCX/PDF sạch.
   Sợ mất bố cục gốc, sợ tốn quota vì job lỗi.
2. **Admin/dev (user hiện tại)** — giữ E2E chain + debug pipeline.

## Đúng/sai/MVP

Đúng: ảnh chụp phone sinh ra từ máy phone (Pillow 12.3 quen HEIC/AVIF; webp
luôn quen). HEIC-HEIF → Pillow ≥10.3 `Image.open` thẳng (libheif plugin built-in
từ Pillow 11.3; verify lúc implement, fallback `pillow-heif` nếu build thiếu
libheif). JPEG-AVIF (Pixel) → Pillow ≥11.3. JPEG-XL → **KHÔNG** (Pillow chưa
support; defer, ghi chú trong docs).

Sai (không làm): giữ "chỉ jpg/png/pdf" status quo (user không dùng được ảnh
phone); đoán bằng magic-byte THAY metadata (metadata vẫn là primary; magic chỉ
là cross-check chặn file sai đuôi); GPU worker self-host (infra tốn kém, out
scope).

MVP = đủ 6 mục user + 2 fix pipeline blocker; HEIC/AVIF là mức 2, JPEG-XL defer.

## Assumption (cần verify)

1. **HEIC**: Pillow 12.3 đã đọc HEIC/HEIF qua plugin built-in (`pillow_heif`
   auto-register) — nếu container/venv thiếu libheif thì thêm
   `pillow-heif` vào server deps + `register_heif_opener()`. Verify = test ảnh
   HEIC thật.
2. **JPEG-AVIF**: Pillow ≥11.3 đọc AVIF (đóng gói libavif) — verify = test ảnh
   AVIF thật.
3. **Magic-byte**: server `POST /api/jobs` (tạo job, sau upload) GET object →
   sniff 16 byte đầu → mismatch với ext → 422 + delete. Không sniff ở presign
   (chưa có bytes).
4. **Quota**: `users.daily_page_limit` (default 25), `users.weekly_page_limit`
   (150); đếm theo `page_count` của job (pdf = số trang, image = 1); block
   pre-create 429; hiển thị QuotaBadge. Week = Mon→Sun (Asia/Ho_Chi_Minh).
5. **Admin LLM**: `settings.llm_timeout` (default 180s), `llm_api_key` masked
   write-only (không echo). Token = LLM API key cho proxy 100.86.205.2:20128.

## User-facing behavior

1. **Ảnh chụp điện thoại**
   - Upload nhận jpg/jpeg/png/webp/pdf + **heic/heif/avif**; picker `accept`
     mở rộng; server `ALLOWED_EXTENSIONS` + `CONTENT_TYPE_BY_EXT` thêm.
   - Ảnh phone (ngang/dọc, EXIF rotation) → OCR giữ nguyên; EXIF-rotate áp
     trước OCR (Pillow `ImageOps.exif_transpose`).
   - Quét tài liệu nhiều ảnh → multi-image job (mỗi ảnh 1 trang; md join
     `---`).
2. **JobDetail 2 section** (cuộn dọc, không tab): Văn bản (IssuesPanel +
   Markdown render + click-to-highlight) trên; Layout (styled preview + 7/5
   ảnh gốc) dưới. Preview mặc định = styled HTML, toggle xem Markdown/HTML.
3. **Preview styled**: iframe sandbox + docStyle tokens (font Inter, radius
   6/8, spacing 4/8/16/24/32, accent) — không còn khối chữ trần.
4. **Export 2 nhóm**: nhóm "Văn bản" (md/html/docx/pdf) + nhóm "Layout"
   (md-layout/docx-layout) trên ExportBar; label rõ.
5. **Pipeline crop → remove-background**: kernel emit crops (rembg u2net) →
   md artifact tham chiếu `crops/{rid}.png` → server serve presigned GET →
   preview hiển ảnh sạch.
6. **Quota**: QuotaBadge (header + Jobs) "còn X/Y trang hôm nay"; block tạo
   job vượt → 429 toast; admin chỉnh per-user trong AdminUsers.
7. **Admin LLM settings**: timeout (120–600s) + api key masked (write-only) trong
   AdminSettings; đổi → áp cho worker (env下一 run).
8. **Landing mới**: hero + 6 slot screenshot thật (login, upload, jobdetail 2
   section, layout preview, export, admin) + copy Việt hóa; capture script
   (Playwright) — CHẠY TAY trên máy bình thường.
9. **Fix pipeline blocker**: (a) `process_job` param shadow → rename
   `preprocess_spec`; (b) create-time magic-byte sniff → 422 rõ ràng.

## Non-goals

- JPEG-XL, TIFF, BMP (defer).
- Self-host GPU worker.
- Dual-truth bidirectional sync (deferred backlog).
- Rate limit RAM→Redis (defer, note P2).

## Risks

- HEIC/AVIF plugin built-in có thể thiếu native lib → fallback `pillow-heif`
  / `pillow-avif` (server deps tăng ~5MB).
- Magic-byte GET object = 1 round-trip R2 thêm mỗi create (≤50MB, chấp nhận).
- Quota per-week cần migration ALTER (dev đã chạy tay; prod cần checklist).
- Landing screenshot cần máy bình thường (sandbox chặn Chrome network) —
  user tự chạy `capture.mjs`.

## Open questions

1. HEIC/AVIF mức 2 có cần ngay hay MVP jpg/png/webp/pdf + fix blocker đủ trước?
2. Export nhóm "Layout" giữ md-layout/docx-layout (2 file) hay thêm pdf-layout?
3. Landing screenshot slot nào QUAN TRỌNH nhất (để ưu tiên capture)?
