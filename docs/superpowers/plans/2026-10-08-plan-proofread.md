# Plan: LLM Proofread — phát hiện & gợi ý sửa lỗi OCR

## Goal
Sau OCR, LLM (`oc/fledge-alpha-free`) đọc text từng trang → phát hiện từ/cụm từ nghi ngờ OCR lệch → lưu vị trí + lý do + gợi ý. UI side panel + highlight source. User quyết định Áp dụng / Bỏ qua. **Không tự thay thế.**

## Decisions (user confirmed)
1. **Auto chạy sau OCR** (fire-and-forget, cùng pattern `_schedule_auto_output`).
2. **MD mode = phương án B**: side panel + highlight source (MDEditor không đụng).
3. **Áp dụng** = replace trong editor content (md source / docx.html) → save → xóa suggestion.

## Server

### Model: `OcrSuggestion` (core/models.py)
```
id, job_id FK, page_index int, start int, end int,
original text, suggestion text, reason text,
status text default 'pending' (pending/accepted/rejected),
created_at
```
Dev: `ALTER TABLE ocr_suggestions ...` thủ công (Alembic deferred). Deploy checklist ghi chú.

### Service: `services/proofread.py` (new)
- `run_proofread(job)`: mỗi page trong `job.result["pages"]` → join `regions[].text` (newline) → LLM call.
- LLM client: copy pattern `llm_md.py` (`_plan`): POST `{LLM_BASE_URL}/chat/completions`, `model=settings.llm_model`, temperature 0, `response_format={"type":"json_object"}`, `Authorization: Bearer {LLM_API_KEY}` nếu có. Timeout 120s.
- Prompt:
  ```
  Đề thi (ngữ cảnh): {subject hint tự suy từ 3 dòng đầu}
  Văn bản OCR (có thể lệch):
  {page text}
  Tìm từ/cụm từ bị OCR sai: ký tự lỗi, thiếu dấu, sai ngữ cảnh.
  Trả JSON: {"items":[{"phrase":"...","reason":"...","suggestion":"..."}]}
  Chỉ nghi ngờ thực sự. Không sửa lỗi chính tả bình thường. Không đổi nội dung đúng.
  ```
- Parse JSON → mỗi item: fuzzy locate `phrase` trong page text (normalize whitespace; fold diacritics nếu cần) → char offsets [start,end). Không tìm thấy → skip.
- Lưu `OcrSuggestion` rows (status pending). Log: `proofread: job=%s pages=%d suggestions=%d elapsed=%.1fs`.
- LLM down/error → log warning, **không fail job** (suggestions = best-effort).

### Hook: `services/job_results.py`
- Thêm `_schedule_proofread(job)` — cùng pattern `_schedule_auto_output` (create_task + `_pending_output` set). Gọi sau khi schedule auto_output trong `_store` (hoặc song song). LLM down → warning, không ảnh hưởng job status.

### API: `routers/jobs.py`
- `GET /api/jobs/{id}/suggestions` → `[{id, page_index, start, end, original, suggestion, reason, status}]` (pending trước, mới nhất trước).
- `POST /api/jobs/{id}/suggestions/{sid}/accept` → status=accepted (không replace — client tự replace + save).
- `POST /api/jobs/{id}/suggestions/{sid}/reject` → status=rejected.
- `POST /api/jobs/{id}/proofread` → chạy lại proofread thủ công (nút refresh), trả về count.

## Web

### `components/SuggestionsPanel.tsx` (new)
- Props: jobId, suggestions, onAccept(sid), onReject(sid), onJump(suggestion).
- List theo page: mỗi item = `original` (strikethrough đỏ) → `suggestion` (xanh), reason (muted), nút **Áp dụng** / **Bỏ qua**.
- Badge số pending trên nút "Kiểm tra lỗi" (Sparkles icon) — UnifiedEditor header.

### `components/UnifiedEditor.tsx` (integrate)
- Load suggestions khi job load (GET). Panel hiện bên phải editor (hoặc below — chọn layout compact).
- **onJump(suggestion)**:
  - MD mode: tìm textarea trong MDEditor DOM (`.w-md-editor-text-input`), set selectionRange(start,end) trên **page text**... ⚠️ offsets là trong page text (join regions), không phải md source. Fuzzy: tìm `original` trong textarea value (normalize whitespace) → select + focus + scroll.
  - Word mode: Tiptap — tìm phrase trong `editor.getText()` → map sang PM positions → `setTextSelection` + scrollIntoView.
- **onAccept(suggestion)**:
  - MD: replace `original` → `suggestion` trong textarea value (fuzzy) → PUT `/export/md-layout/content` → POST accept.
  - Word: Tiptap replace text range → PUT `/export/docx-layout/html` → POST accept.
  - Không tìm thấy → toast "Không tìm thấy trong nội dung".
- **onReject**: POST reject → remove khỏi list.

### `lib/api.ts`
- `getSuggestions(jobId)`, `acceptSuggestion(jobId, sid)`, `rejectSuggestion(jobId, sid)`, `runProofread(jobId)`.

## Model wiring
- `LLM_MODEL=oc/fledge-alpha-free` env (config.py:69 env-overridable). Client tái sử dụng pattern llm_md.

## Tests
- Server: test_proofread.py — mock LLM response → parse → locate → store; LLM down → no fail; hook schedule; API endpoints.
- Web: SuggestionsPanel render + accept/reject; onJump highlight (mock editor).

## Gates
- Server: `pytest tests/test_proofread.py -q` + full suite.
- Web: `npm test && npx tsc --noEmit && npm run build`.

## Risks
- LLM ảo giác → chỉ nghi ngờ, user reject; fuzzy-match chặn phrase không tồn tại.
- Offsets trong page text ≠ editor content → dùng fuzzy find theo `original` phrase (không dùng offsets để replace).
- Chi phí: 1 call/page async.
