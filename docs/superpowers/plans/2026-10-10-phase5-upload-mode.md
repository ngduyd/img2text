# Phase 5: Upload mode selector + cụm nút (Hủy/Gửi lên) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`).

**Goal:** Tạo job chọn mode: "Lấy layout" (+ format md/docx) vs "Chỉ trích xuất văn bản". Cụm [Hủy][Gửi lên · format ▾] góc trên phải khung upload. extract_only → bỏ qua auto-gen layout.

**Architecture:** Server: upload accept `mode` → `jobs.mode`; `auto_generate_output` skip nếu extract_only. Web: Dropzone/wizards mode selector + cụm nút vị trí mới; `jobs.mode` state; uploadJob mode param.

**Tech Stack:** FastAPI (server); React (web). `jobs.mode` column đã migrate (Phase 1).

**Spec:** Sub-system E — `docs/superpowers/specs/2026-10-10-redesign-editor-versioning-design.md`. Phase 1+4 merged.

## Global Constraints

- Server `jobs.mode`: 'layout' (default) | 'extract_only'. Upload endpoint (multipart) nhận optional `mode`. `auto_generate_output`: `if job.mode == "extract_only": return False` (skip layout, không schedule/render).
- Web: Dropzone state `mode` ('layout'|'extract_only'); khi extract_only → ẩn format picker. Wizard thêm mode radios. Cụm [Hủy][Gửi lên · format ▾] move khung upload góc trên phải (format ▾ = FormatSplitButton đã có).
- uploadJob(file, {output_format, mode}).
- Design tokens DESIGN.md; R59 toast; R51 testids adjust-only (btn-format-* giữ).
- Test: server `DATABASE_URL=...img2text_test`; web `cd web && npm test && npx tsc -b --force && npm run build`.

## Review Focus

- extract_only: job tạo → OCR → không gen layout; layout_cache miss; UI không hiện "cần vẽ layout" cho extract_only.
- Mode flow: default layout; đổi mode → format picker ẩn/hiện; upload gửi đúng mode.
- Backward-compat: không gửi mode → default layout (hành vi cũ).

---

### Task 1: Server mode + auto-gen skip

**Files:** `server/app/routers/jobs.py` (upload), `server/app/services/job_results.py` (auto_generate_output), `server/app/services/exports.py` (auto_generate_output nếu tách), tests.

- [ ] Red test: upload mode=extract_only → job.mode stored; auto_generate_output skip (no layout artifact). Green. Commit.

### Task 2: Web mode state + Dropzone/wizards

**Files:** `Dropzone.tsx`, `PdfWizard.tsx`, `ImageCropWizard.tsx`, `Jobs.tsx`, `api/client.ts` (uploadJob mode), `api/types.ts`.

- [ ] Red tests: mode radios, extract_only → format picker ẩn, upload sends mode, cụm nút góc phải. Green. Commit.

### Task 3: Gate

- [ ] Server subset + `cd web && npm test && npx tsc -b --force && npm run build` → xanh. Commit.
