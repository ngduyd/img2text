# Spec: Lane S — IR per-page + heading anchors + word images (2026-10-15)

Base: master `cb70a8f`. Server-only. TDD.

## S1 — Word thiếu ảnh: crop on-demand fallback

**Bug**: `exports/{id}/crops/` rỗng (batch chưa ingest) → `_docx_html_export`
(`routers/exports.py`) crop miss → `html_to_docx` drop img. md-layout đã có
on-demand; docx chưa.

**Fix**: `_docx_html_export` — crop `storage.get` KeyError →
`get_or_make_crop(job_id, rid, …)` (cùng pattern `_llm_md_export` crop_loader).
Partial-fail giữ nguyên (crop lỗi → img drop). Test đỏ→xanh: batch crop thiếu
→ on-demand gọi → `html_to_docx` embed ảnh (assert media trong docx).

## S2 — IR per-page sequential

`llm_ir` (`services/render_md.py`) hiện gửi TOÀN BỘ result 1 call.

**Fix**: tách `_ir_page(result, page, running_ctx) -> PageIR` — mỗi trang 1
LLM call, **loop sequential theo thứ tự trang** (page N+1 cần heading stack
đang mở từ page N), gộp `pages[]` → `validate_ir` toàn bộ (giữ nguyên source-id
check). Concurrency: KHÔNG parallel (thứ tự bắt buộc).
Prompt per-page: `IR_PROMPT_PAGE` (mới) — OCR json chỉ 1 trang + running
section context từ trang trước.
Fallback: 1 trang fail → thử lại 1 lần → vẫn fail → degrade kiểu cũ (gọi
1-call full result như hiện tại) + warning. Không kill job.

## S3 — Heading anchors (số thứ tự text) ≠ header trang

- **Heading = số thứ tự trong TEXT** (`^\s*(\d+(\.\d+)*)[.)]\s` regex) —
  KHÔNG phát hiện theo bbox/style. Đánh §index theo y-order: §1, §2, §2.1…
- Prompt annotation: block heading nhận anchor `[§2.1]`; instruction: block
  kế tiếp thuộc mục gần nhất; page N+1 nhận running list các mục đang mở
  (context param `_ir_page`) → nội dung nối đúng mục xuyên trang.
- **Header trang** (tên đề/đầu trang) ≠ heading: detect riêng theo y-band
  top (< ~8% chiều cao) + content không phải số thứ tự → map type
  `header`/`doc_title`, không tham gia §index.
- Merge: stack §index reset theo document, carry xuyên trang.

## S4 — Cross-column normalize (trừ bảng)

Prompt rule: 2 block cùng y-band ở 2 cột → **ép cùng type/level** (trái
heading thì phải heading; không trái-heading/phải-paragraph cùng hàng).
**Ngoại lệ bảng**: block có `html`/`cells` (table) → skip rule.
`validate_ir`: check cùng y-band (tolerance `max(10, 0.3*max(h))`) +
2 cột (x-disjoint) + không bảng → type khác → warning log (KHÔNG fail —
render giữ heuristic fallback pattern sẵn có).

## S5 — Word "chưa hoạt động": verify retry-layout render docx

TDD: test `POST /jobs/{id}/retry-layout` / auto-output path — xác nhận có
gọi `_llm_docx_export` + put `exports/{id}/docx-layout`. Nếu không → fix
theo test đỏ. (Hiện docx-layout tạo OK từ exports flow — cần verify retry
path đầy đủ.)

## Không làm (đã ruling)
- Rotation/tilt từ AABB: không đủ info; kernel đã deskew (`estimate_skew`).
