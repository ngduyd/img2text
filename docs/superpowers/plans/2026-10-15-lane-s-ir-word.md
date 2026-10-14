# Plan: Lane S — IR per-page + word images (2026-10-15)

Spec: `docs/superpowers/specs/2026-10-15-lane-s-ir-word-design.md`.
Base `cb70a8f`. Worktree `lane-s-ir`. Server: venv chung, DB `img2text_test`@5436, PYTHONPATH, targeted pytest chunk 8'. Commit mỗi task. TDD.

## Task 1 — S1: docx crop on-demand fallback
- Test đỏ: `_docx_html_export` — html chứa `crops/rid.png`, storage.get crop → KeyError, monkeypatch `get_or_make_crop` trả bytes → assert bytes truyền vào `html_to_docx` (spy) / docx có media.
- Fix: `_docx_html_export` thêm fallback `get_or_make_crop` (pattern `_llm_md_export`).

## Task 2 — S5: retry-layout render docx (verify trước)
- Test đỏ: `POST /jobs/{id}/retry-layout` (done job, LLM mock) → assert `exports/{id}/docx-layout` được put (spy storage).
- Chạy → nếu xanh = flow OK (test ghi nhận) → ghi chú evidence; đỏ → fix wiring (gọi `_llm_docx_export` song song md).

## Task 3 — S3a: heading anchor helper + prompt annotation
- Test đỏ: `extract_heading_anchors(page_blocks)` → list `(block_id, "§2.1")` từ text regex (`1.`, `1.1`, `2.2`) y-order; header y-band top ≠ heading; non-numbered → None.
- Fix: helper trong `services/ir.py` (hoặc render_md), unit tests.

## Task 4 — S2: `_ir_page` sequential + merge
- Test đỏ: `llm_ir` per-page — mock `_chat` trả 2 page IR khác nhau; assert `_chat` gọi ĐÚNG 2 lần, sequential (log call order), gộp `pages[]` theo page_number; running_ctx truyền từ page1→2 (assert prompt page2 chứa section context).
- Fix: tách `_ir_page(result, page, ctx)`, loop sequential, merge; fallback 1-call full result khi all fail (mock LLM fail → degrade test).

## Task 5 — S4: cross-column normalize
- Test đỏ: (a) prompt chứa rule "same y-band 2 columns → same type, EXCEPT table"; (b) `validate_ir` warning khi cùng y-band + 2 cột + khác type + không bảng; bảng (cells) → không warn.
- Fix: prompt update + validate check (warning không fail).

## Task 6 — S3b: header/heading phân tách trong prompt
- Test đỏ: prompt assertion — header y-band top rule + §index chỉ cho numbered headings.
- Fix: `IR_PROMPT_PAGE` sections update.

## Task 7 — sweep
- `pytest tests/test_ir.py tests/test_render_md.py tests/test_export_md_layout.py tests/test_export_docx*.py tests/test_retry*.py` + related chunks.

## Rollout
1 worker sequential (S3→S2 phụ thuộc S3a), commit/task. Report: git log + red-green.
