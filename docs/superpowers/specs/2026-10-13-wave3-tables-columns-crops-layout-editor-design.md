# Spec: Wave-3 — bảng cells, layout 2 cột, crop→output, JobDetail UX, Layout editor (2026-10-13)

Base: master `264e8c5`. Tiếp nối spec 2026-10-13 (đã merged Lane A-D).

## Bối cảnh (evidence run thật)

- Job2 (bảng UNIT 1): VLM xuất block table = HTML `<table>` → kernel join thẳng md →
  preview `markdown-it html:false` escape → chữ `<table>` thô đầy màn hình.
- Job1 (đề Hóa): `p1_b15 [60,602,322,713]` + `p1_b17 [345,518,583,713]` = 2 hình
  2 cột cùng hàng → linearize tuần tự → mất bố cục. 2 region `image_unextractable`
  → md không marker → không crop nào về output (loop path đã có marker `IMAGE_MARKER`,
  batch kernel CHƯA emit).
- PDF gốc: iframe `sandbox=""` chặn browser PDF viewer → trắng.
- Section Văn bản bị đóng khung chiều cao → 20 trang scroll chết.
- LLM proofread timeout 180s; ir_json stub 0 blocks.

## Users

Giáo viên cần bản Word/bảng chính xác + hình sạch; layout xem được, sửa tay được.

## Đúng/sai/MVP

Đúng: parse VLM HTML table → `cells` (rowspan/colspan/header) MỘT LẦN ở kernel;
md artifact = GFM pipe (markdown thuần, preview/editor tự render, không đụng sanitizer);
docx-layout = python-docx `add_table` + `merge()` theo span (fidelity 100%).
Sai: convert pandas `to_markdown` (mất span, thêm dep); cho phép raw HTML trong
preview (không cần nữa khi md đã pipe); layout edit đụng text version (dual-truth
deferred — layout artifact có đời sống riêng).

MVP = mục 1-8 bên dưới.

## Assumption (verify lúc implement)

1. bs4 có sẵn trong kernel venv (paddlex deps) — fallback regex nếu không.
2. `cells` lưu trong region jsonb: `{html, cells, text}` — html = nguồn sự thật.
3. Pipe table preview render OK với `markdown-it` mặc định (html:false giữ nguyên).
4. 2 image marker cùng dòng (ngăn bởi space) → preview render 2 ảnh inline (mặc định
   markdown token kế nhau trong 1 paragraph = inline) — verify bằng test DOM.
5. Layout edit: `PATCH /api/jobs/{id}/layout-content` kind `md-layout` snapshot
   (document_versions đã có kind này từ wave trước), export layout đọc edited.

## User-facing behavior

1. Bảng trong output = **bảng thật** (preview/editor md là pipe table; docx = bảng
   python-docx có merge span; pdf qua pandoc).
2. Layout 2 cột: regions cùng hàng (y-center band, tolerance ~10px) sort trái→phải
   trước khi linearize; **2 image regions cùng hàng → md 2 marker trên CÙNG dòng**
   → preview 2 ảnh ngang.
3. Image region `image_unextractable` → md chứa `IMAGE_MARKER` (đúng format
   `app.core.schemas.IMAGE_MARKER`) → render embed crop + rembg (wiring đã có) →
   ảnh hiển trong preview + export.
4. PDF gốc hiện được (bỏ sandbox iframe, blob URL same-origin).
5. **1 panel "File gốc" duy nhất** sticky trượt xuyên cả phần Văn bản lẫn Layout
   (gộp 2 aside → wrapper grid 1 cột trái = 2 section stack, cột phải = sticky panel).
6. Section Văn bản bỏ khung chiều cao — nội dung dài, cuộn trang chính.
7. **Layout editor**: md pane + word pane sửa trực tiếp (mặc định = xem), nút "Lưu
   layout" → snapshot kind md-layout; không đụng bản văn (text_version riêng);
   export layout dùng bản đã sửa.
8. Regression: 369 web + 595 server test xanh.

## Non-goals

Dual-truth sync (text ↔ layout edit); colspan trong GFM (pipe không có span — md
mất span, docx giữ); IR LLM zones (deferred); JPEG-XL.

## Risks

- Bảng lớn (job2 page3 bao trùm trang) → pipe table khổng lồ trong editor (chấp nhận).
- Gộp sticky panel = đổi layout grid JobDetail → test section grid 7/5 cần adjust.
- Python-docx merge span = API `cell.merge` dễ sai grid — test fixture bảng 2×2 có span.
- Kernel md đổi format → server test contract (test_render_md) cần update theo.

## Open questions

Không — user đã chốt (1a/2b/3 editor).
