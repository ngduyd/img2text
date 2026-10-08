# Plan M — Vùng sửa hợp nhất (md/word) + LLM layout on-demand (spec)

User chốt: (1) "Sửa gì thì lưu đó" — chỉ call LLM khi layout CHƯA có, LLM vẽ từ JSON của VLM (result.json); (2) auto-call + spinner OK; (3) gộp preview+editor thành 1 vùng, switch [Markdown|Word], rail giữ.

## Contract server (M1 — làm trước/cùng)
- `GET /api/jobs/{id}` thêm `layout_cache: {md: bool, docx: bool}` (storage.exists exports/{id}/md-layout + docx-layout, owner-or-admin đã có).
- `PUT /api/jobs/{id}/export/md-layout/content` body {markdown: str} — owner-or-admin, done-only 409, length ≤ 500k → 422 "Nội dung quá dài."; storage.put exports/{id}/md-layout (upsert) → 204. (Lưu ý: PATCH /content (job.content) VẪN giữ nguyên — 2 đường lưu KHÁC nhau: content = bản OCR/sửa thô, md-layout = bản layout LLM.)
- Style overrides word: `jobs.layout_style` TEXT column (JSON nullable) — POST/PATCH `PUT /api/jobs/{id}/layout-style` body {style: object|null} (keys enum: fontFamily?, fontSize?, align?, indent?, spacing?, underline? — validate enum keys, values typed) → lưu column, 204. GET job trả `layout_style` (parse JSON | null).
- `POST /api/jobs/{id}/export {fmt:"docx-layout"}` renderer nhận thêm style overrides từ job → áp TRƯỚC (global: base font/size/align/margins; underline→runs) — override LLM plan (user "sửa gì lưu đó" thắng LLM). md-layout renderer: style overrides word áp client CSS (xem web).
- Migration: `ALTER TABLE jobs ADD COLUMN IF NOT EXISTS layout_style TEXT;` (dev: tôi/user chạy; README note).

## Contract web (M2)
- Gộp: PreviewTabs card ("Tài liệu") + MarkdownEditor card → MỘT card `panel-editor` tiêu đề "Soạn thảo": mode segmented control [Markdown | Word] (testids switch-mode-md/switch-mode-word; default = job.output_format === "docx" ? "word" : "md").
- Flow mode (cả 2 giống nhau):
  1. layout_cache[mode] false → **auto** exportJob(fmt: md-layout|docx-layout) + spinner trong content area (testid layout-loading "Đang vẽ layout bằng LLM…") → fetch artifact (downloadExport blob: md → text, docx → mammoth HTML) → render; false → toast.error(mapApiError) + nút thử lại (btn-retry-layout).
  2. true → fetch artifact → render NGAY (không LLM).
  3. Content: md = sandbox iframe render md-layout text + nút "Chỉnh sửa nguồn" toggle → textarea source md-layout (toolbar MdToolbar hoạt động trên nguồn) → **Lưu** (PUT md-layout/content) + toast "Đã lưu." ; word = mammoth HTML iframe + DocStyleTools variant word (tools style) → **Lưu style** (PUT layout-style) + toast; content word đổi → hint "Sửa chữ ở dạng Markdown" (md mode).
- Cache sau khi lưu md-layout: storage đã upsert → lần sau cache hit (không re-LLM) ✓ đúng "mới call khi chưa có".
- bỏ: card "Tài liệu" tab-rời + MarkdownEditor card cũ (testids preview-markdown/preview-docx-frame chuyển vào content area iframe; md-source-preview/btn-save/btn-edit-doc adjust; R51 note). btn-edit-doc header giữ (focus vùng Soạn thảo). Issues/OriginalFile/Export/Info rail GIỮ.
- Tools bars: trên content area (toolbar md) hoặc rail style (word) — theo taste skill + DESIGN.md tokens, zero em-dash, a11y.

## Gates
server: full suite; web: full suite + tsc + build; e2e Section M (M1 cache-miss auto-LLM spinner, M2 lưu md-layout không re-LLM lần sau, M3 lưu style word + export giữ style, M4 switch mode).

# Plan M3 — Word editing THẬT + single-row toolbar (user feedback round)

## Binding M3-server
- `PUT /api/jobs/{id}/export/docx-layout/html` {html: str} owner/done/≤1MB else 422 "Nội dung quá dài." → storage.put(f"exports/{id}/docx.html") → 204.
- `layout_cache.docx` = exists(docx.html) OR exists(docx-layout). GET job trả thêm `docx_html_cached: bool`? (GIẢN: thêm key `docx_html` vào layout_cache object — {md, docx, docx_html}).
- Export fmt=docx: nếu exports/{id}/docx.html tồn tại → **HTML→docx converter MỚI** (services/html_to_docx.py): walker python-docx cho subset tag MÌNH EMIT (p/div h1-h3 b i u span[style font-size/font-family] ul ol li table tr th td align attrs) — preserve font/size/align/table/underline; KHÔNG dùng pandoc (mất inline style). Fallback: không có docx.html → path cũ (llm_docx plan render). markdown fmt giữ nguyên.
- Tests: PUT html (204 + đọc lại + oversize 422 + 403/409), layout_cache flags mới, export docx đọc docx.html → python-docx assert table/font/size/align, fallback không html.

## Binding M3-web (UnifiedEditor word mode LÀM LẠI)
- Word content = iframe contenteditable (srcDoc = sanitize DOMPurify của docx.html nếu cache, else mammoth từ docx-layout như hiện tại); editing ON = iframe document.designMode="on" hoặc contentEditable với execCommand (styleWithCSS).
- Toolbar WORD 1 HÀNG duy nhất (scroll-x nếu tràn, gap-sm, label screen-reader/ title): undo redo | select font family | select size (8..72 pt) | B I U | align L C R J | list ul/ol | insert table (grid picker 1..10×1..10) khi caret trong table: +row −row +col −col | clear format. Tất cả áp theo VÙN CHỌN (selection) qua execCommand/custom wrap span style — KHÔNG áp cả document. Testids word-tb-* giữ tên cũ nếu match được, thêm word-tb-table/word-tb-size/font.
- Layout: vùng "Soạn thảo" MỞ RỘNG (content col rộng hết cột trái, min-height ~60vh, toolbar sticky top trong card), md mode cũng toolbar 1 hàng (MdToolbar + DocStyleTools gộp vào 1 hàng?? DocStyleTools md-content align/indent/bullet dùng selection md logic — GIỮ md như hiện tại chỉ nới kích thước; word toolbar mới là single-row).
- Save word: btn-save-layout-word "Lưu" → serialize iframe HTML → api.putDocxHtml (client fn mới) → toast "Đã lưu."; sau save layout_cache.docx_html=true → lần sau load thẳng KHÔNG mammoth/LLM.
- BỎ hint "Sửa chữ ở dạng Markdown" (word tự chứa nội dung). md mode không đổi.
- Tests: toolbar 1 hàng (word toolbar container single row assertion), selection-based (mock execCommand spy called with selection), insert table → iframe HTML có table, save → putDocxHtml, load docx.html path, mammoth fallback path.
- Gates: web test+tsc+build; server subset M3 + controller full sau merge.
