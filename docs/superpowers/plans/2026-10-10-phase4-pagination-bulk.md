# Phase 4: Jobs list pagination + bulk retry — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`).

**Goal:** Jobs list phân trang server-side (10/trang) + checkbox chọn nhiều + bulk "Chạy lại đã chọn".

**Architecture:** Server: `GET /jobs` nhận `page`/`page_size` → `{items, total, page, page_size}`. Web: pagination controls, checkbox mỗi hàng + select-all-trang, sticky bulk bar → retryJob từng selected failed job.

**Tech Stack:** FastAPI + SQLAlchemy (server); React + TanStack Query (web). Vitest + pytest.

**Spec:** Sub-system D — `docs/superpowers/specs/2026-10-10-redesign-editor-versioning-design.md`. Phase 1 đã merged.

## Global Constraints

- Server `GET /api/jobs`: optional `page` (default 1), `page_size` (default 10, max 100). Response `{items, total, page, page_size}`. KHÔNG đổi shape `items` element.
- Web `api.listJobs(page?, page_size?)`. Pagination controls prev/next + page numbers. 10/trang.
- Checkbox mỗi `JobRow` (`testid="row-select-{id}"`) + header select-all-trang (`testid="select-all-page"`).
- Bulk bar sticky bottom khi có chọn: "n đã chọn" + nút `testid="bulk-retry"` → gọi retryJob cho TỪNG job selected status=failed → toast R59 → invalidate.
- Giữ StatusFilterTabs (filter client-side trên trang hiện tại).
- Design tokens: radius 6/8, accent, contrast ≥4.5, no em-dash.
- Test DB server: `DATABASE_URL="...img2text_test"` (đã có migration). Web: `cd web && npm test && npx tsc -b --force && npm run build`.

## Review Focus

- Pagination math: total vs items trên trang; filter interaction (filter thay đổi → reset page?); empty page.
- Bulk retry: chỉ retry failed được chọn; partial failure (1 job fail) → toast + không abort cả batch.
- Race: chọn + đổi trang → bulk bar state.

---

### Task 1: Server pagination

**Files:** `server/app/routers/jobs.py` (list endpoint), tests.

**Interfaces:** `GET /jobs?page=1&page_size=10` → `{items: JobListItem[], total, page, page_size}`.

- [ ] Red test: default 10 items, page 2, total correct, max page_size. Green. Commit.

### Task 2: Web listJobs params + pagination UI

**Files:** `api/client.ts`, `api/types.ts`, `Jobs.tsx`.

- [ ] Red test: listJobs(page), pagination controls render + click page 2 → refetch. Green. Commit.

### Task 3: Checkbox + bulk bar

**Files:** `JobRow.tsx` (+checkbox), `Jobs.tsx` (selection state, select-all, sticky bulk bar), `api/client.ts` (bulk retry).

- [ ] Red tests: checkbox render, select N → bulk bar "N đã chọn", bulk-retry → retryJob từng failed + toast + invalidate, select-all-trang. Green. Commit.

### Task 4: Gate

- [ ] Server subset + `cd web && npm test && npx tsc -b --force && npm run build` → xanh. Commit.
