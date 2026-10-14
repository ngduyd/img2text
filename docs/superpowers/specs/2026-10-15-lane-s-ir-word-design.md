# Spec: Lane S — IR per-page + heading anchors + word images (2026-10-15) — rev2

Base: master `cb70a8f`. Server-only. TDD.
Rev2: fix theo spec-review (2 P0 + 3 P1 + P2s).

## S1 — Word thiếu ảnh: fix CẢ 2 đường (P0-2)

**Symptom**: user tải Word → không ảnh. 2 path đều mất ảnh:
- **(a) `fmt=docx`** (`_docx_html_export`, exports.py:495): crop miss → drop img.
  Fix: fallback on-demand `get_or_make_crop`.
  **Signature đổi**: `_docx_html_export(job_id, job, storage)` (cần
  `job.result` cho crop) → caller `export_job` + `download_export` update.
  Catch scope: swallow `KeyError` (giống md path); `HTTPException` propagate (R27).
- **(b) `fmt=docx-layout`** (`build_docx`, render_docx.py:438): figure map →
  `<p>[ảnh]</p>` placeholder, **không bao giờ embed**. Fix: figure node →
  load crop bytes (`exports/{id}/crops/{rid}.png` → on-demand fallback) →
  `python-docx` `add_picture(bytes)` (crop thiếu → giữ `<p>[ảnh]</p>`,
  partial-fail pattern).

Test đỏ→xanh mỗi path: batch crop thiếu → on-demand gọi → ảnh trong
output (docx: assert media part; html-export: assert bytes vào html_to_docx).

## S2 — IR per-page sequential (shared, P0-1)

- **`_ir_page(result, page, running_ctx) -> PageIR` đặt trong `services/ir.py`**
  — DÙNG CHUNG cho cả `render_md.llm_ir` VÀ `render_docx.py:304` (hiện 2
  copy `llm_ir`/duplicate call — cả 2 refactor sang shared).
- Sequential loop theo `page_number` (thứ tự bắt buộc: running heading stack).
- Prompt: `IR_PROMPT_PAGE` mới (1 trang OCR json + running_ctx).
- **Cost cap**: `MAX_IR_PAGE_CALLS = 20` — trang > 20 → degrade 1-call full
  (prompt cũ) + warning (giữ job chạy, tránh N×180s worst case).
- Per-page fail → retry 1 lần → still fail → degrade full-result 1-call.
- Merge: sort `page_number`, check không trùng/thiếu, map `page_id` đúng
  trang; `validate_ir` toàn bộ giữ nguyên.

## S3 — Heading anchors ≠ header trang

- `extract_heading_anchors(blocks) -> list[(block_id, §label)]` đặt
  **`services/ir.py`** (shared 2 path).
- Regex **đầu block**: `^\s*(\d+(?:\.\d+)*)[.)]\s` — **loại 4-digit năm**
  (`2024.` → negative). Numbering **liên tục xuyên trang** (document-level
  counter, KHÔNG reset/trang); stack §mục đang mở carry qua `running_ctx`.
- **Negative matrix (test)**: `"2024."` false+; `"1)"` true; `"1.1.1"` true;
  `"   1. Benefit"` true (indent vẫn match); `"Câu 1:"`/`"Bài 2"` = **out of
  scope** (không số thuần → không anchor, ghi rõ ceiling).
- **Header trang** ≠ heading: y-band top **15%** (chốt theo `IR_PROMPT`
  hiện tại, bỏ số 8% ở rev1) + không phải số thứ tự → type
  `header`/`doc_title`, không tham gia §index. Prompt ghi rule riêng.

## S4 — Cross-column normalize (trừ bảng)

- **Prompt rule** (trong `IR_PROMPT_PAGE`): cùng y-band + 2 cột → ép cùng
  type/level — block có `<table`/cells (OCR `text` chứa `<table`) → **ngoại lệ**.
- **Validator** `validate_ir` (sau `_fill_bbox`): 2 node cùng y-band
  (tolerance `max(10, 0.3*max(h))`) + x-disjoint 2 cột + **không phải bảng**
  (lookup qua `source_block_ids` → OCR region `text` có `<table`/`cells`,
  pattern `render_md.py:147`) + type khác → **warning log**.
- **Rationale warn-only** (không raise): fail-closed đã có sẵn pattern
  heuristic fallback kill render — warning giữ signal cho tuning, không
  chặn output (graceful degradation đã established). "Ép" thực thi ở prompt.

## S5 — Word retry verify

Test `POST /jobs/{id}/retry-layout` (LLM mock) → assert
`exports/{id}/docx-layout` được put (spy storage). Wiring đã có
(`jobs.py:773 → auto_generate_output`) → nhiều khả năng green-confirm
(ghi nhận evidence); đỏ → fix wiring.

## Legacy IR_PROMPT (P2-13)

- Fallback 1-call (degrade) + prompt cũ: **giữ nguyên** (degradation path,
  không đổi behavior).
- `IR_PROMPT_PAGE` = bản mới có S3/S4 rules; `render_docx` dùng chung
  (không giữ copy riêng).

## Không làm
- Rotation/tilt từ AABB (đã ruling — kernel `estimate_skew` deskew sẵn).
