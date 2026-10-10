# Phase 2: Trang trích xuất văn bản (highlight + click-fix + save-sync) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`).

**Goal:** Route `/jobs/:id/extraction` — render text gốc (HTML), highlight từ lỗi (từ proofread suggestions) bôi vàng, click → popover → accept = `POST /extraction` (save + incremental sync, 0 LLM), nút "Vẽ lại layout" (full LLM), hiện "cần render lại" khi sync fail.

**Architecture:** Web-only. Dùng API Phase 1 (GET/POST `/extraction`, versions, restore) + proofread suggestions (GET `/suggestions`). Highlights = `<mark>` quanh phrase gợi ý. Accept → saveExtraction → invalidate job+extraction → hiện layout mới hoặc "cần render lại" hint.

**Tech Stack:** React, TanStack Query, existing DESIGN.md tokens (dark zinc, accent xanh, radius 6/8), tailwind. Vitest + Testing Library.

**Spec:** Sub-system B — `docs/superpowers/specs/2026-10-10-redesign-editor-versioning-design.md`. Server Phase 1 đã merged (extraction endpoints). Read both.

## Global Constraints

- Route `/jobs/:id/extraction` (App.tsx ~:321 thêm sibling Route).
- API client (`web/src/api/client.ts`): +`getExtraction(id)` → `{text, text_version}`, +`saveExtraction(id, {old_phrase,new_phrase,expected_text_version,force?})` → `{synced, needs_render, text_version}`, +`listVersions(id,kind)`, +`restoreVersion(id,vid)`.
- Highlight: `bg-warning/20` + underline dotted. Click → popover (phrase → suggestion + reason + Áp dụng/Bỏ qua), KHÔNG modal.
- Accept → saveExtraction (auto sync) → UI loading → 200 → invalidate `["job",id]` + `["extraction",id]` → nếu `needs_render` non-empty hiện hint "Cần vẽ lại layout" + nút.
- "Vẽ lại layout" → dùng `api.retryLayout(id)` (Phase 1 chưa có /render-layout riêng) → invalidate.
- Design tokens: accent xanh, radius 6/8, contrast ≥4.5, no em-dash, R59 toast, loading skeleton.
- Test: `cd web && npm test && npx tsc -b --force && npm run build`.

## Review Focus

- **Accept flow correctness**: POST đúng expected_text_version (optimistic lock); 409 → refresh + toast; force flag cho detached.
- **Highlight accuracy**: mark quanh đúng phrase (không nhầm substring); phrase xuất hiện nhiều lần.
- **needs_render state**: hiện hint + nút vẽ lại layout khi sync fail; không hiện layout stale làm current.
- **a11y**: popover keyboard-accessible, focus-visible, contrast.

---

### Task 1: API client fns + types

**Files:** `web/src/api/client.ts`, `web/src/api/types.ts`.

**Interfaces:** `Extraction {text, text_version}`, `ExtractionSaveResult {synced: Record<string,bool>, needs_render: string[], text_version}`. Fns: getExtraction, saveExtraction, listVersions, restoreVersion.

- [ ] Red test: client fns gọi đúng endpoint/method (mock fetch). Green. Commit.

### Task 2: Route + ExtractionPage skeleton (render text)

**Files:** `web/src/App.tsx` (+Route), `web/src/pages/ExtractionPage.tsx` (new), link từ JobDetail.

**Interfaces:** ExtractionPage dùng `getExtraction` + `getSuggestions`. Render text per trang/region (HTML). Header: back link + "Vẽ lại layout" button + trạng thái sync.

- [ ] Red test: render text gốc, back link. Green. Commit.

### Task 3: Highlight + popover + accept (save-sync)

**Files:** `ExtractionPage.tsx`, popover component.

**Interfaces:** suggestions → map phrase → `<mark data-testid="suggestion-mark-{sid}">`. Click → popover `suggestion-popover-{sid}` với Áp dụng (`btn-apply-{sid}`) → `saveExtraction(job, {old_phrase: s.original, new_phrase: s.suggestion, expected_text_version})`.

- [ ] Red tests: mark render, click → popover, Áp dụng → saveExtraction called + invalidate, 409 → toast+refresh. Green. Commit.

### Task 4: needs_render + "Vẽ lại layout" + link ↔ JobDetail

**Files:** `ExtractionPage.tsx`, `JobDetail.tsx` (link "Trích xuất văn bản").

**Interfaces:** save result `needs_render` non-empty → hint + `btn-redraw-layout` → retryLayout → invalidate. JobDetail header thêm link sang extraction.

- [ ] Red tests: needs_render → hint+button; redraw → retryLayout called; JobDetail link render. Green. Commit.

### Task 5: Gate

- [ ] `cd web && npm test && npx tsc -b --force && npm run build` → xanh.

### Task 6 (optional/note): Version history UI

- Minimal "Lịch sử phiên bản" panel (listVersions + restore) — nếu fit, thêm; nếu không defer Phase sau. Ghi trong commit nếu defer.
