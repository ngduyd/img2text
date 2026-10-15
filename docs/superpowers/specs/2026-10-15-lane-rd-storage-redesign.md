# Lane RD — /storage Redesign Spec

> **Spec location:** `docs/superpowers/specs/2026-10-15-lane-rd-storage-redesign.md`  
> **Worktree:** `lane-rd-storage`  
> **Source:** `web/src/pages/Storage.tsx`  
> **Design System:** `web/DESIGN.md`  
> **Audit baseline:** CHANGES-REQUIRED (combined QA + UI/UX audits — 15 findings mapped below)

---

## Goal

Elevate the user storage page (`/storage`) to DESIGN.md parity: token-only colors, a11y landmarks, responsive tables, composed empty states, pagination, error/retry, and consistent i18n — **without changing any testid, endpoint, or purge logic**.

---

## Non-Goals

- Admin storage page (`/admin/storage`) — separate page, separate spec
- New API endpoints or backend changes
- New i18n keys (all copy exists in `storage.own.*`)
- Visual redesign beyond DESIGN.md token compliance

---

## Architecture

Single-page React component (`Storage.tsx`) using:
- TanStack Query for data fetching (add pagination, error boundary)
- `useT()` for i18n (replace all `translate()` calls)
- Shared `Button` (danger variant already token-compliant), `Card`, `Badge`, `Skeleton`, `ConfirmDialog`
- New helpers in `lib/storage.ts`: `sumKeptBytes`, `ageDays`
- Page wrapper: `main#main.mx-auto.max-w-7xl.px-4.py-6` for skip-link + content width

---

## Audit Findings → Spec Requirements (Traceability Matrix)

| ID | Severity | File:Line | Finding | Spec Requirement |
|---|---|---|---|---|
| **P0-1** | critical | Storage.tsx:32-35,63,101 | `useQuery` missing `isError` → infinite skeleton | Add `isError` state, show composed error + retry button (pattern: JobDetail) |
| **P0-2** | critical | Storage.tsx:35 | `listJobs(1,100)` hardcoded → no pagination | Add page state, `listJobs(page, PAGE_SIZE)`, prev/next controls (pattern: AdminStorage.tsx:147-171) |
| **P0-3** | critical | Storage.tsx:60 | Missing `main#main.mx-auto.max-w` wrapper → skip-link dead | Wrap page in `main id="main" className="mx-auto max-w-7xl px-4 py-6"` |
| **P0-4** | critical | Storage.tsx:61 | Zero `h1` → add `h1` + subtitle retention | Add `<h1>{t("storage.own.title")}</h1>` + `<p className="text-muted">{t("storage.own.subtitle")}</p>` (new i18n key `storage.own.subtitle`: "Quản lý file lưu trữ của bạn") |
| **P0-5** | major | Storage.tsx:94 | Purge-due disabled gate wrong (`items.length===0`) | Disable when `kept.length === 0` (only kept files can be purged) |
| **A1** | critical | Storage.tsx:1 | No page-level `h1` (duplicate of P0-4) | Covered by P0-4 |
| **A2** | major | Storage.tsx:88,115 | Hardcoded `border-error/40 bg-error/10` on danger buttons | Remove custom `className`; `variant="danger"` already token-compliant (`text-error hover:bg-error/10`) |
| **A3** | major | Storage.tsx:93 | Table headers missing `scope="col"` | Add `scope="col"` to all `<th>` |
| **A4** | major | Storage.tsx:103 | Table `overflow-x-auto` without sticky first column | Add `sticky left-0 bg-surface z-10` to filename `th`/`td`; responsive `max-w` |
| **A5** | minor | Storage.tsx:67 | Stat grid `grid-cols-2 sm:grid-cols-3` → orphan on mobile | `grid-cols-1 sm:grid-cols-3 gap-4` |
| **A6** | minor | Storage.tsx:83 | `max-w-40` fixed width on filename | `max-w-[10ch] sm:max-w-[16ch] lg:max-w-[24ch] truncate` |
| **A7** | minor | Storage.tsx:119,122 | Mixed `translate()` vs `t()` | Replace all `translate()` with `t()` from `useT()` |
| **A8** | minor | Storage.tsx:58 | Table wrapped in Card (elevation not needed) | Replace Card with `<section aria-labelledby="table-heading" className="border-t border-border">` + `<h2 id="table-heading" className="sr-only">` |
| **A9** | nit | Storage.tsx:88 | Danger button has border+bg (DESIGN.md: error text + error/10 hover only) | Covered by A2 — Button `danger` variant already correct |
| **A10** | minor | Storage.tsx:112,72 | Inline `ageDays` + `keptBytes` reduce | Extract to `lib/storage.ts` |
| **P1-1** | minor | Storage.tsx:108 | Empty state bare text (Jobs.tsx: composed pattern) | Composed empty: icon + title + body + CTA (upload link) |
| **P1-2** | minor | Storage.tsx:63,101 | Skeleton misaligned layout | Skeleton rows matching final table columns (5 cols + actions) |
| **P1-3** | minor | Storage.tsx:93-100 | Table readability: `th scope`, `font-mono`, Link `/jobs/:id`, `<time>`, title truncate, `px-3` | Filename → `<Link to={/jobs/${j.id}} title={j.filename}>`; dates in `<time dateTime={...}>`; `px-3` cells; `font-mono tabular-nums` for numbers |
| **P1-4** | minor | Storage.tsx:80-88 | Card header: no flex-wrap, CTA < 44px | Header `flex flex-wrap items-center gap-2`; CTA `min-h-11 min-w-11` |
| **P1-5** | minor | Storage.tsx:88 | CTA label static "Xóa file hết hạn" → dynamic "Xóa N file" + helper retention | Button label: `t("storage.own.purgeDue", { n: kept.length })`; helper text: `t("storage.own.retentionHelper")` (new key) |
| **P2** | minor | Storage.tsx:112 | `ageDays` null → NaN guard | `ageDays(iso: string \| null \| undefined): number` — return 0 if falsy |

---

## UI/UX Requirements (from DESIGN.md)

| Rule | Application |
|---|---|
| **Radius** | Buttons: 8px (`rounded-md`); Cards: 8px (`rounded-card`); Badges: `rounded-full` |
| **Accent** | Single blue (`--accent`/`--accent-text`) — no new hues |
| **Focus** | Global `:focus-visible` ring (2px accent, 2px offset) — no custom focus |
| **Contrast** | All text ≥4.5:1 (tokens.test.ts gates) |
| **Spacing** | 4/8/16/24/32/48 scale — `gap-4` (16px), `px-3 py-2` (12/8px), section gaps `gap-6`/`gap-8` |
| **No em-dash** | Copy uses `—` only in i18n JSON |
| **Typography** | System sans-serif; mono for numbers/timestamps/IDs (`font-mono tabular-nums`) |
| **Motion** | 150ms ease-out on transform/opacity/color; `prefers-reduced-motion` respected |
| **Responsive** | Mobile-first: 320/768/1024/1440; single-col <768px; no horizontal page scroll |

---

## i18n Keys (Existing + 2 New)

| Key | Vi | En | Used In |
|---|---|---|---|
| `storage.own.title` | "Dung lượng của tôi" | "My storage" | h1 |
| `storage.own.subtitle` *(new)* | "Quản lý file lưu trữ của bạn" | "Manage your stored files" | subtitle |
| `storage.own.stats.keptFiles` | "File còn giữ" | "Files kept" | Stat |
| `storage.own.stats.purgedFiles` | "File đã dọn" | "Files removed" | Stat |
| `storage.own.stats.keptBytes` | "Dung lượng còn lưu" | "Storage used" | Stat |
| `storage.own.tableTitle` | "File" | "Files" | table heading |
| `storage.own.table.filename` | "File" | "File" | th |
| `storage.own.table.created` | "Ngày tạo" | "Uploaded" | th |
| `storage.own.table.age` | "Tuổi" | "Age" | th |
| `storage.own.table.size` | "Dung lượng" | "Size" | th |
| `storage.own.table.status` | "Trạng thái" | "Status" | th |
| `storage.own.table.actions` | "Thao tác" | "Actions" | th (sr-only) |
| `storage.own.purgeOne` | "Xóa file" | "Delete file" | per-job button |
| `storage.own.purgeDue` | "Xóa file hết hạn" | "Delete expired files" | bulk button |
| `storage.own.purgeDue` *(interpolated)* | "Xóa {n} file" | "Delete {n} file(s)" | bulk button with count |
| `storage.own.retentionHelper` *(new)* | "File cũ hơn {days} ngày sẽ bị xóa" | "Files older than {days} days will be removed" | helper under bulk button |
| `storage.own.confirmOneTitle` | "Xóa file này?" | "Delete this file?" | confirm |
| `storage.own.confirmOneMessage` | "File gốc và export tái tạo sẽ bị xóa…" | "Original file and regenerable exports…" | confirm |
| `storage.own.confirmDueTitle` | "Xóa file hết hạn?" | "Delete expired files?" | confirm |
| `storage.own.confirmDueMessage` | "File cũ hơn hạn lưu sẽ bị xóa…" | "Files older than retention…" | confirm |
| `storage.own.purgedOneToast` | "Đã xóa file." | "File deleted." | toast |
| `storage.own.purgedDueToast` | "Đã xóa {n} file." | "Deleted {n} file(s)." | toast |
| `storage.own.ageDays` | "{n} ngày" | "{n} days" | age cell |
| `storage.own.empty` | "Chưa có job nào." | "No jobs yet." | empty state |
| `storage.purged` | "Đã dọn" | "Purged" | badge |
| `storage.kept` | "Giữ" | "Kept" | badge |
| `i18n.locale` | "vi-VN" | "en-US" | date locale |

---

## Non-Negotiable Constraints

| Constraint | Detail |
|---|---|
| **Test IDs** | All `data-testid` values in `Storage.tsx` + `Storage.test.tsx` must remain identical |
| **Endpoints** | `GET /api/jobs` (via `api.listJobs`), `POST /api/jobs/{id}/purge-storage`, `POST /api/jobs/purge-storage-due` — unchanged |
| **Purge Logic** | Per-job + bulk flows, ConfirmDialog gating, toast on success, `invalidateQueries(["my-storage"])` — unchanged |
| **i18n** | All `storage.own.*` keys preserved; only `t()` usage standardized |
| **Radius/Accent/Focus/Contrast/Spacing** | Per DESIGN.md §2–§6 |

---

## Acceptance Criteria

| AC | Test / Verification |
|---|---|
| AC1 | `npm test` — all 3 Storage tests pass (cards+table, per-job purge, bulk purge) |
| AC2 | `npx tsc --noEmit` — clean |
| AC3 | `npm run build` — clean |
| AC4 | `oxlint` — clean |
| AC5 | Page has `main#main.mx-auto.max-w-7xl` + `h1` + subtitle |
| AC6 | Table headers have `scope="col"`; first column sticky on horizontal scroll (320px) |
| AC7 | Stat grid: 1-col ≤639px, 3-col ≥640px |
| AC8 | No hardcoded color classes (grep: `border-error\|bg-error` only in Button.tsx) |
| AC9 | Danger buttons use `variant="danger"` only (no custom className) |
| AC10 | Pagination works (prev/next, page state, API called with page) |
| AC11 | Error state shows composed error + retry button (like JobDetail) |
| AC12 | Empty state composed (icon + title + body + CTA link to upload) |
| AC13 | Skeleton matches final layout (5 cols + actions) |
| AC14 | Filename is `<Link to=/jobs/${id}>` with `title` attr; dates in `<time dateTime>` |
| AC15 | Bulk button label shows count "Xóa N file"; helper shows retention days |
| AC16 | `ageDays(null)` returns 0, no NaN |

---

## Residual Risks

1. **Button.danger variant** — already token-compliant in `Button.tsx`; if design review demands border, scope creep to shared component
2. **Sticky column z-index** — `z-10` on filename vs `sticky top-0` on thead; test stacking at 320px
3. **`t("i18n.locale")`** — returns locale string (e.g., "vi-VN"); verify `toLocaleString` accepts it
4. **Pagination API** — `api.listJobs(page, PAGE_SIZE)` must accept page param; verify backend
5. **New i18n keys** — `storage.own.subtitle`, `storage.own.retentionHelper` need adding to both `vi.json`/`en.json` (non-breaking)

---

*Spec complete. Ready for implementation plan.*
