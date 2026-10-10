# Phase 3: Job detail split-view + gỡ component — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`).

**Goal:** Job detail split-view: trái = bản có layout (sửa được) | phải = bản gốc (đối chiếu), tỷ lệ 7/5. Gỡ badge "Đầu ra: Word" + stats "Tổng 21 vùng · ..."; gộp nút tải vào 1 cụm rail.

**Architecture:** Web-only. ResultPanel split 2 cột (7/5 grid). Rail bỏ job-meta card (badge+stats) + bỏ card bọc ExportBar. Sửa layout trực tiếp → detach hook đã có (Phase 1 PUT endpoints).

**Tech Stack:** React, DESIGN.md tokens. Vitest + Testing Library.

**Spec:** Sub-system C — `docs/superpowers/specs/2026-10-10-redesign-editor-versioning-design.md`. Phase 1+2+4 merged. `JobDetail.tsx` đã có link extraction (Phase 2).

## Global Constraints

- Split-grid `lg:grid-cols-7`/`lg:grid-cols-5` (layout trái 7, gốc phải 5) — hoặc `lg:grid-cols-[7fr_5fr]`. Mobile stack.
- Trái: ResultPanel (UnifiedEditor md/word) sửa được. Phải: OriginalFilePanel (ảnh/OCR text đối chiếu).
- **Gỡ**: Badge "Đầu ra: Word" (`job-output-format`), `statsLine` "Tổng ... vùng ..." (`result-stats`), `job-meta` card bọc. Giữ InfoPanel + ExportBar.
- Gộp nút tải: ExportBar 1 cụm trong rail (bỏ card bọc ngoài thừa — Card testid panel-export có thể giữ hay bỏ, tùy gọn).
- R51 testids adjust-only. DESIGN.md tokens. R59 toast.
- Test: `cd web && npm test && npx tsc -b --force && npm run build`.

## Review Focus

- Split 7/5 render đúng, mobile stack. Layout sửa được (md/word) + gốc hiển thị đối chiếu.
- Gỡ component: KHÔNG còn badge/stats trong DOM. ExportBar vẫn hoạt động.
- Không break Phase 2 (link extraction) + Phase 1 (detach khi sửa layout).

---

### Task 1: Split-view layout

**Files:** `JobDetail.tsx`, `components/panels/ResultPanel.tsx`, `components/panels/OriginalFilePanel.tsx`.

- [ ] Red test: split-grid 2 cột (layout|gốc) render, mobile stack. Green. Commit.

### Task 2: Gỡ component + gộp nút tải

**Files:** `JobDetail.tsx`.

- [ ] Red test: không còn `job-output-format` badge + `result-stats` statsLine trong DOM. ExportBar vẫn render. Green. Commit.

### Task 3: Gate

- [ ] `cd web && npm test && npx tsc -b --force && npm run build` → xanh. Commit.
