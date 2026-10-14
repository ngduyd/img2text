# Plan: Lane S — IR per-page + word images (2026-10-15) — rev3

Spec: `docs/superpowers/specs/2026-10-15-lane-s-ir-word-design.md` (rev2).
Base `cb70a8f`. Worktree `lane-s-ir`. Server: venv chung, DB `img2text_test`@5436, PYTHONPATH, targeted pytest chunk 8'. Commit mỗi task. TDD.
Rev3: fix plan-review (P0 build_docx params, P1 callers/DI/signature/sweep, P2 regex/PDF).

## Task 1 — S1a: `_docx_html_export` crop on-demand (fmt=docx)
- Test đỏ: html chứa `crops/rid.png`, batch crop KeyError, monkeypatch `get_or_make_crop` → bytes truyền vào `html_to_docx` (spy).
- Fix: `_docx_html_export(job_id, job, storage)`; catch `KeyError` only. **Call site duy nhất: `export_job` exports.py:605** (download_export serve cache qua storage.get — KHÔNG gọi → không sửa).

## Task 2 — S1b: `build_docx` figure embed crop (fmt=docx-layout)
- **Design** (P0): placeholder `<p>[ảnh]</p>` không mang rid → đổi IR docx render: figure node → `<img src="crops/{rid}.png">`.
- **rid chốt** (P1): `rid = figure.source_block_ids[0]` (KHÔNG dùng `node.id` — auto `auto_n*` → loader miss silent); prompt instruct LLM emit `source_block_ids` đúng cho figure; builder validate qua `find_region` — unknown rid → placeholder.
- **Params/threading** (P1): `build_docx(result, use_llm, style_overrides, ir_sink, crop_loader=None)`; **`_llm_docx_export(job_id, job, ir_sink, storage=None)`** (exports.py:426, KHÔNG phải :439) + thread `storage` từ 2 caller (`export_job` :560, `auto_generate_output` :601 — check call site thật). Closure: load `exports/{id}/crops/{rid}.png` → KeyError → `get_or_make_crop(job_id, rid, job, result, storage)` (exports.py:148) → None.
- Test đỏ: (a) figure + crop bytes → docx zip có `word/media/*`; (b) crop_loader None/thất bại/unknown rid → giữ `<p>[ảnh]</p>` (partial-fail); (c) prompt emit `source_block_ids` cho figure.
- Note ceiling: PDF source (R26 `get_or_make_crop` image-only) → placeholder-only, warning.

## Task 3 — S5: retry-layout render docx (verify)
- Test: `POST /jobs/{id}/retry-layout` (LLM mock) → spy put `exports/{id}/docx-layout`. Xanh = evidence ghi nhận; đỏ → fix wiring `auto_generate_output`.

## Task 4 — S3a: `extract_heading_anchors` trong `services/ir.py`
- **Signature** (P1): `extract_heading_anchors(pages: list[dict], state: AnchorState | None) -> (list annotations, AnchorState)` — page_height per page cho y-band 15%; state = doc-level §counter + stack carry xuyên trang.
- Test đỏ matrix:
  - positive: `"1. Benefit"`, `"1) Foo"` (trailing space bắt buộc), `"1.1.1"`, `"   2.2 Indent"`,
  - negative: `"2024. Năm"` (4-digit guard explicit), `"Câu 1:"`, `"Bài 2"`, `"abc 1. x"` (không đầu block),
  - y-order → §sequence liên tục xuyên trang (state carry), header y-band 15% top + không số → excluded → header/doc_title.
- Fix: helper shared trong ir.py.

## Task 5 — S2: `_ir_page` sequential shared (DI)
- **Signature** (P1): `_ir_page(page_ocr: dict, running_ctx: str, chat_fn) -> dict` trong ir.py — KHÔNG import httpx; `render_md.llm_ir` + `render_docx.llm_ir` delegate, mỗi nơi pass `_chat` của mình (giữ 2 HTTP clients hiện có, 1 shared logic).
- Test đỏ (inject `chat_fn` fake): 2 page → đúng 2 call **đúng thứ tự** (log order), page2 prompt chứa §context page1, merge sort page_number + check trùng/thiếu; >20 page (`MAX_IR_PAGE_CALLS=20`) → degrade 1-call; page fail → retry 1 → fail → fallback legacy `IR_PROMPT` full-result.
- Fix: loop sequential + merge.

## Task 6 — S4+S3b: prompt rules + validator
- Test đỏ: (a) `IR_PROMPT_PAGE` chứa cross-column rule + table exception + header y-band 15% + §anchor instruction; (b) `validate_ir` (sau `_fill_bbox`) warning: cùng y-band + 2 cột + khác type + không bảng (lookup `source_block_ids` → OCR region `cells`/`<table`, pattern `render_md.py:147`); bảng → không warn; (c) legacy `IR_PROMPT` snapshot không đổi.
- Fix: prompt + validate warn-only (rationale: fail đã có heuristic fallback — warning giữ signal).

## Task 7 — sweep (glob THẬT)
- `test_ir.py test_render_md.py test_render_docx.py test_export_md_layout.py test_export_llm_docx.py test_docx_html.py test_export_docx.py test_crop_embed.py test_job_retry.py test_jobs_retry.py`.
