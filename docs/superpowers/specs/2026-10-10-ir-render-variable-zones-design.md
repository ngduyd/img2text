# Spec: IR render — trang có zone biến thiên (header/content/footer không phải luôn đủ 3)

Date: 2026-10-10
Status: audit + fix đã duyệt (user)
Path: bounded fix (prompt guard + regression test) — 1 spec cho cả md + docx render

## Problem (đã audit)

- Mỗi trang PDF/ảnh có header/content/footer **khác nhau**, không phải trang nào cũng đủ 3 zone.
- **Heuristic fallback** (`render_page`, bands theo geometry): **XỬ LÝ ĐÚNG** — zone trống tự bỏ, không marker thừa, không bịa. (Đã verify: trang content-only → render "## Câu 2" không header/footer.)
- **LLM render** (`llm_render_md`/`llm_render_docx`): schema zone = `list` default rỗng → flow cho phép zone trống, NHƯNG prompt **chưa có guard** "zone rỗng → render nothing". LLM thấy key `header`/`content`/`footer` trong IR JSON → có thể **bịa** nội dung cho trang thiếu zone.

## Intent

- LLM render: zone `[]` → render nothing, **không bịa** header/content/footer cho trang thiếu.
- Heuristic giữ nguyên (đã đúng).
- Regression test pin: trang content-only không bị bịa; trang header+content không bị thêm footer rỗng.

## Fix (2 chỗ symmetric)

1. `RENDER_MD_PROMPT` (render_md.py): thêm rule — *"Empty zones (header/content/footer = []) → render NOTHING for that zone; do NOT invent content for missing zones. A page may have only content, only header+content, etc."*
2. `RENDER_DOCX_PROMPT` (render_docx.py): guard tương tự (HTML output).

## Non-goals

- Heuristic render (đã đúng). IR schema (zones đã default rỗng). Structurize prompt (không đổi — việc gán zone hợp lệ).

## Testing

- **Regression heuristic** (deterministic, đã verify): IR/result có trang content-only → heuristic md không header/footer thừa.
- **Regression heuristic** trang header+content (không footer) → không thêm footer rỗng.
- **Prompt guard**: assert `RENDER_MD_PROMPT` + `RENDER_DOCX_PROMPT` chứa clause "empty zones → nothing / do not invent" (pin guard vào prompt, tránh ai đó xóa).
- (LLM path khó deterministic → pin guard bằng prompt-assert + heuristic regression.)

## Files

- `server/app/services/render_md.py` (RENDER_MD_PROMPT guard)
- `server/app/services/render_docx.py` (RENDER_DOCX_PROMPT guard)
- `server/tests/test_render_md.py`, `test_render_docx.py` (regression variable-zones + prompt-guard assert)

## Note

- Disjoint với lane R2 (storage/upload/orchestrator/kernel) + Cancel (jobs.py/orchestrator/job_results) → chạy song song được.
