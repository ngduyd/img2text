# Lane RD /storage Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring `web/src/pages/Storage.tsx` to DESIGN.md parity per spec — error/retry, pagination, `main#main` + `h1`, a11y table, composed states, token-only colors, i18n `t()` — without touching any existing `data-testid`, endpoint, or purge logic.

**Architecture:** Single-page React component rewrite in place. Pure helpers move to `web/src/lib/storage.ts` (unit-tested). Two new i18n keys in `vi.json`+`en.json` (parity test enforces both). Patterns copied from existing pages: error state ← `JobDetail.tsx:144-166`, pagination ← `admin/AdminStorage.tsx:147-171`, page shell ← `Jobs.tsx:143-151`, empty state ← `Jobs.tsx:369-379`.

**Tech Stack:** React 19 + TanStack Query v5 + vitest (`npx vitest run`) + tsc (`npx tsc -b --force`) + vite build + oxlint (`npx oxlint`), all run from `web/`.

**Spec:** `docs/superpowers/specs/2026-10-15-lane-rd-storage-redesign.md` (commit `606671e`)

## Global Constraints

- All existing `data-testid` in `Storage.tsx` + `Storage.test.tsx` stay byte-identical: `storage-own-card`, `storage-own-loading`, `storage-own-table`, `storage-own-table-loading`, `storage-own-kept-files`, `storage-own-purged-files`, `storage-own-kept-bytes`, `storage-own-purge-due`, `storage-own-job-{id}`, `purged-badge-{id}`, `storage-purge-{id}`. New testids allowed only for new UI (error, retry, empty, pagination).
- Endpoints unchanged: `api.listJobs(page, page_size)` → `GET /api/jobs` (backend `page: int = Query(1, ge=1)` confirmed `server/app/routers/jobs.py:461`), `api.purgeJobStorage`, `api.purgeMyStorageDue`.
- Purge logic unchanged: ConfirmDialog gating, toast on success, `qc.invalidateQueries({ queryKey: ["my-storage"] })` (prefix still matches new `["my-storage", page]` keys).
- i18n: exactly 2 new keys — `storage.own.subtitle`, `storage.own.retentionHelper` — added to BOTH `web/src/i18n/vi.json` and `web/src/i18n/en.json` (`tests/i18n/i18n.test.tsx` key-parity enforces). Existing `storage.own.*` keys preserved; `storage.own.purgeDue` value gains `{n}` (see Task 5).
- Token-only colors: no `border-error`/`bg-error`/other raw hues in `Storage.tsx` (AC8 grep scoped to `Storage.tsx` — `AdminStorage.tsx` is out of spec scope, Non-Goals §1).
- No backend changes (spec Non-Goals). `RETENTION_DAYS = 7` mirrors `server/app/core/config.py` `purge_retention_days: int = 7` — runtime `Setting` override can diverge from this copy (known residual, cosmetic only; purge predicate untouched).
- Default test locale is `en` (no I18nProvider in `Storage.test.tsx` → `readLang()` default `"en"`).

## Review Focus

1. **`t("i18n.locale")` locale string (spec residual #3)** — `t` returns `"en-US"`/`"vi-VN"` from JSON; `Date.toLocaleString` accepts BCP-47. Test: date cell renders a non-empty `<time>` without throwing (Task 5).
2. **Pagination × purge invalidation** — queryKey must include `page` (`["my-storage", page]`) or prev/next show stale data; prefix invalidation must still refetch after purge. Test: purge flow still sees `listJobs` called exactly 2× (existing test 2), and next-page test asserts `listJobs(2, 20)` (Task 8).
3. **Bulk purge gate semantics (P0-5)** — gate flips from `items.length===0` to `kept.length===0` (page-scoped: purged rows cannot be purged again). Test: page whose items are all purged → `storage-own-purge-due` disabled (Task 5).
4. **`{n}` interpolation on `storage.own.purgeDue`** — confirm dialog `confirmLabel` also uses this key; it must receive `{ n: kept.length }` or the dialog shows literal `{n}`. Test: assert confirm label contains count, no `{n}` literal (Task 5).
5. **Sticky first column vs sticky thead (spec residual #2)** — filename `th` needs opaque `bg-surface-2` (thead bg), `td` needs `bg-surface`, both `z-10`. Test asserts classes only; 320px stacking is manual (validation step).

---

### Task 1: `lib/storage.ts` helpers (AC16, A10, P2)

**Files:**
- Create: `web/src/lib/storage.ts`
- Create: `web/src/lib/storage.test.ts`
- Modify: `web/src/pages/Storage.tsx` (replace inline `ageDays` + `keptBytes` reduce with imports)

**Interfaces:**
- Produces: `ageDays(iso: string | null | undefined): number` (0 for falsy input, else `Math.max(0, floor((now - iso)/86400000))`); `sumKeptBytes(items: Pick<JobListItem, "upload_bytes">[]): number` (`upload_bytes || 0` summed; import type from `../api/types`).

- [ ] **Step 1: failing test** in `web/src/lib/storage.test.ts`:

```ts
import { ageDays, sumKeptBytes } from "./storage";
test("ageDays(null|undefined|'') → 0, không NaN", () => {
  expect(ageDays(null)).toBe(0);
  expect(ageDays(undefined)).toBe(0);
  expect(ageDays("")).toBe(0);
});
test("ageDays floor theo ngày, không âm", () => {
  expect(ageDays(new Date(Date.now() - 8 * 86400000 + 3600000).toISOString())).toBe(8);
  expect(ageDays(new Date(Date.now() + 86400000).toISOString())).toBe(0); // future → 0
});
test("sumKeptBytes bỏ null/undefined, sum upload_bytes", () => {
  expect(sumKeptBytes([{ upload_bytes: 1024 }, { upload_bytes: undefined }, {}])).toBe(1024);
  expect(sumKeptBytes([])).toBe(0);
});
```

- [ ] **Step 2: run → FAIL**: `cd web && npx vitest run src/lib/storage.test.ts` → module not found.
- [ ] **Step 3: implement** `web/src/lib/storage.ts` (both functions, doc comments in Vietnamese style matching repo, e.g. `/** Tuổi job theo ngày (floor, không âm); null/undefined → 0. */`).
- [ ] **Step 4: run → PASS**: same command.
- [ ] **Step 5: wire into `Storage.tsx`**: delete local `ageDays` function + `keptBytes` reduce; `import { ageDays, sumKeptBytes } from "../lib/storage";` → `const keptBytes = sumKeptBytes(kept);` (behavior identical: `ageDays(j.created_at)` args widen to nullable OK).
- [ ] **Step 6: run storage page tests**: `cd web && npx vitest run src/pages/Storage.test.tsx src/lib/storage.test.ts` → PASS.
- [ ] **Step 7: Commit**

```bash
git add web/src/lib/storage.ts web/src/lib/storage.test.ts web/src/pages/Storage.tsx
git commit -m "feat(RD-storage T1): extract ageDays/sumKeptBytes → lib/storage.ts (ageDays null→0, AC16)"
```

---

### Task 2: i18n keys `subtitle` + `retentionHelper` (residual #5)

**Files:**
- Modify: `web/src/i18n/vi.json` (inside `"own": {` after `"title"`)
- Modify: `web/src/i18n/en.json` (same position)

**Interfaces:**
- Produces: `storage.own.subtitle` ("Quản lý file lưu trữ của bạn" / "Manage your stored files"); `storage.own.retentionHelper` ("File cũ hơn {days} ngày sẽ bị xóa" / "Files older than {days} days will be removed"). Consumed by Tasks 3 (subtitle) and 5 (helper).

- [ ] **Step 1: add both keys to both files** at identical positions (right after `"title"` for subtitle; after `"purgeDue"` for retentionHelper).
- [ ] **Step 2: verify parity + tsc**: `cd web && npx vitest run tests/i18n/i18n.test.tsx` → PASS ("identical key sets"); `npx tsc -b --force` → clean.
- [ ] **Step 3: Commit**

```bash
git add web/src/i18n/vi.json web/src/i18n/en.json
git commit -m "feat(RD-storage T2): i18n keys storage.own.subtitle + retentionHelper (en+vi)"
```

---

### Task 3: Page shell — `main#main` + `h1` + subtitle + stat grid (AC5, AC7, P0-3, P0-4, A1, A5)

**Files:**
- Modify: `web/src/pages/Storage.tsx`
- Test: `web/src/pages/Storage.test.tsx`

**Interfaces:**
- Consumes: `t("storage.own.subtitle")` (Task 2).
- Produces: root `<main id="main" className="mx-auto max-w-7xl px-4 py-6">` (mirror `Jobs.tsx:143`); header `<h1 className="text-2xl font-bold tracking-tight">{t("storage.own.title")}</h1>` + `<p className="mt-1 text-sm text-muted">{t("storage.own.subtitle")}</p>` inside `<header className="mb-6">`. Stats `<Card testid="storage-own-card">` loses its `title` prop (h1 now owns the title; avoids duplicate heading text) — testid + contents unchanged. Stat grid className → `grid grid-cols-1 gap-4 sm:grid-cols-3`.

- [ ] **Step 1: failing test** in `Storage.test.tsx`:

```tsx
test("page shell: main#main + h1 + subtitle (AC5, AC7)", async () => {
  listJobs.mockResolvedValue(PAGE);
  renderPage();
  await screen.findByTestId("storage-own-kept-files");
  const main = document.querySelector("main#main");
  expect(main).toBeTruthy();
  expect(main!.className).toContain("max-w-7xl");
  expect(screen.getByRole("heading", { level: 1, name: "My storage" })).toBeTruthy();
  expect(screen.getByText("Manage your stored files")).toBeTruthy();
  expect(document.querySelector(".grid.grid-cols-1.sm\\\\:grid-cols-3")).toBeTruthy(); // AC7
});
```

- [ ] **Step 2: run → FAIL**: `cd web && npx vitest run src/pages/Storage.test.tsx` (new test fails, 3 old pass).
- [ ] **Step 3: implement** the JSX changes per Interfaces block (wrap existing `flex flex-col gap-4` div inside the `<main>`; move title out of stats Card into `<header>`).
- [ ] **Step 4: run → PASS** same command (4 tests).
- [ ] **Step 5: Commit**

```bash
git add web/src/pages/Storage.tsx web/src/pages/Storage.test.tsx
git commit -m "feat(RD-storage T3): main#main wrapper + h1/subtitle + stat grid 1-col mobile (AC5, AC7)"
```

---

### Task 4: Error state + retry (AC11, P0-1)

**Files:**
- Modify: `web/src/pages/Storage.tsx`
- Test: `web/src/pages/Storage.test.tsx`

**Interfaces:**
- Consumes: `useQuery` returns `isError`, `error`, `refetch`; `mapApiError` (already imported); existing keys `errors.generic`, `common.retry`.
- Produces: when `isError`, page body = error block INSTEAD of cards+section (stats/table never render — kills infinite skeleton). New testids: `storage-own-error` (block), `storage-own-retry` (button). Block pattern copied from `JobDetail.tsx:144-166`: `TriangleAlert` icon `text-error` + title `<p className="font-medium">{t("errors.generic")}</p>` + body `<p className="break-words text-sm text-muted">{mapApiError(error)}</p>` + `Button variant="secondary" size="sm" testid="storage-own-retry"` label `t("common.retry")` calling `refetch()`.

- [ ] **Step 1: failing test** in `Storage.test.tsx`:

```tsx
test("error state: composed error + retry refetch (AC11)", async () => {
  listJobs.mockRejectedValueOnce(new Error("boom")).mockResolvedValue(PAGE);
  renderPage();
  const err = await screen.findByTestId("storage-own-error");
  expect(err.textContent).toContain("boom");
  expect(screen.queryByTestId("storage-own-card")).toBeNull(); // không skeleton vĩnh viễn
  fireEvent.click(screen.getByTestId("storage-own-retry"));
  await screen.findByTestId("storage-own-kept-files"); // refetch → nội dung quay lại
  expect(listJobs).toHaveBeenCalledTimes(2);
});
```

- [ ] **Step 2: run → FAIL**.
- [ ] **Step 3: implement** `const { data, isLoading, isError, error, refetch } = useQuery(...)`; return body = `{isError ? errorBlock : (<>cards + section + dialog</>)}`.
- [ ] **Step 4: run → PASS** (5 tests).
- [ ] **Step 5: Commit**

```bash
git add web/src/pages/Storage.tsx web/src/pages/Storage.test.tsx
git commit -m "feat(RD-storage T4): composed error state + retry button (AC11, P0-1)"
```

---

### Task 5: Table section a11y + sticky col + link/time + purge header (AC6, AC8, AC9, AC14, AC15, A2, A3, A4, A6, P1-3, P1-4, P1-5, P0-5)

**Files:**
- Modify: `web/src/pages/Storage.tsx`
- Modify: `web/src/i18n/vi.json`, `web/src/i18n/en.json` (`storage.own.purgeDue` value gains `{n}`)
- Test: `web/src/pages/Storage.test.tsx`

**Interfaces:**
- Consumes: `t("storage.own.retentionHelper")` (Task 2); `RETENTION_DAYS = 7` module const in `Storage.tsx` with comment `// Mirror server purge_retention_days default (config.py); runtime Setting override → copy sai (cosmetic, ponytail: export từ /api/quota/me khi backend thêm field).`.
- Produces:
  - Table `<Card>` → `<section aria-labelledby="table-heading" data-testid="storage-own-table" className="border-t border-border">` + `<h2 id="table-heading" className="sr-only">{t("storage.own.tableTitle")}</h2>`.
  - Section header: `<div className="flex flex-wrap items-center gap-2 py-3">` containing purge-due Button + `<p className="text-xs text-muted">{t("storage.own.retentionHelper", { days: RETENTION_DAYS })}</p>`.
  - Purge-due Button: `className="min-h-11 min-w-11"` (replaces `border border-error/40 bg-error/10`), `disabled={!data || kept.length === 0}` (P0-5), label `t("storage.own.purgeDue", { n: kept.length })`.
  - Per-job Button: drop `className` entirely (A2) — `variant="danger"` only.
  - Confirm dialog `confirmLabel` for `kind==="due"`: `t("storage.own.purgeDue", { n: kept.length })` (no literal `{n}`).
  - `i18n/vi.json`: `"purgeDue": "Xóa {n} file"`; `i18n/en.json`: `"purgeDue": "Delete {n} file(s)"` (spec values).
  - All `<th scope="col"> className="px-3 py-2 font-medium"`; filename `th` adds `sticky left-0 z-10 bg-surface-2`; filename `td` → `<Link to={`/jobs/${j.id}`} title={j.filename ?? ""} className="block truncate sticky left-0 z-10 bg-surface px-3 py-2 text-accent-text transition duration-150 ease-out hover:underline max-w-[10ch] sm:max-w-[16ch] lg:max-w-[24ch]">` (A6 widths; Link imported from `react-router-dom`).
  - created `td` → `<time dateTime={j.created_at} className="block px-3 py-2 font-mono text-xs">`; age/size `td` → `px-3 py-2 font-mono tabular-nums`; status/actions `td` → `px-3 py-2`.
  - Stats grid className per Task 3 (unchanged here).

- [ ] **Step 1: failing tests** in `Storage.test.tsx`:

```tsx
test("table a11y: scope=col, sticky filename col, link+time (AC6, AC14)", async () => {
  listJobs.mockResolvedValue(PAGE);
  renderPage();
  await screen.findByTestId("storage-own-job-9");
  const section = screen.getByTestId("storage-own-table");
  expect(section.tagName).toBe("SECTION");
  expect(section.getAttribute("aria-labelledby")).toBe("table-heading");
  section.querySelectorAll("th").forEach((th) => expect(th.getAttribute("scope")).toBe("col"));
  const link = screen.getByRole("link", { name: "a.pdf" });
  expect(link.getAttribute("href")).toBe("/jobs/9");
  expect(screen.getByText("a.pdf").className).toContain("sticky");
  const time = section.querySelector("time")!;
  expect(time.getAttribute("datetime")).toBeTruthy();
  expect(time.textContent).toBeTruthy(); // residual #3: toLocaleString(t("i18n.locale")) không ném
});

test("purge-due gate kept.length + label {n} + helper (AC15, P0-5)", async () => {
  listJobs.mockResolvedValue({
    ...PAGE,
    items: PAGE.items.map((j) => ({ ...j, storage_purged_at: "2026-01-09T00:00:00+00:00" })),
  });
  renderPage();
  await screen.findByTestId("storage-own-purge-due");
  const btn = screen.getByTestId("storage-own-purge-due");
  expect((btn as HTMLButtonElement).disabled).toBe(true); // hết kept → disable
  expect(btn.textContent).not.toContain("{n}");
  expect(screen.getByText(/older than 7 days|cũ hơn 7 ngày/i)).toBeTruthy();
});

test("bulk confirm label hiển thị count, không literal {n} (AC15)", async () => {
  listJobs.mockResolvedValue(PAGE);
  purgeMyStorageDue.mockResolvedValue({ purged: 1 });
  renderPage();
  await screen.findByTestId("storage-own-purge-due");
  fireEvent.click(screen.getByTestId("storage-own-purge-due"));
  const accept = screen.getByTestId("confirm-accept");
  expect(accept.textContent).toContain("1");
  expect(accept.textContent).not.toContain("{n}");
});
```

- [ ] **Step 2: run → FAIL**.
- [ ] **Step 3: implement** all Interfaces items (one edit pass over the table + header + i18n values).
- [ ] **Step 4: run → PASS** (8 tests); **AC8/AC9 grep**: `grep -n "border-error\|bg-error" web/src/pages/Storage.tsx` → empty; `grep -n "translate(" web/src/pages/Storage.tsx` still non-empty (Task 9 removes).
- [ ] **Step 5: Commit**

```bash
git add web/src/pages/Storage.tsx web/src/pages/Storage.test.tsx web/src/i18n/vi.json web/src/i18n/en.json
git commit -m "feat(RD-storage T5): section+a11y table, sticky filename col, link/time, purge-due {n} label + kept gate (AC6/8/9/14/15)"
```

---

### Task 6: Composed empty state (AC12, P1-1)

**Files:**
- Modify: `web/src/pages/Storage.tsx`
- Test: `web/src/pages/Storage.test.tsx`

**Interfaces:**
- Consumes: existing keys `storage.own.empty` (title), `jobs.emptyBody` (body), `jobs.emptyCta` (CTA); `Inbox` icon from `lucide-react` (Jobs.tsx pattern); `Link` already imported (Task 5).
- Produces: when `items.length === 0` → `<div data-testid="storage-own-empty" className="flex flex-col items-center px-2 py-6 text-center">` with `<Inbox className="h-10 w-10 text-muted" aria-hidden />`, `<p className="mt-3 font-semibold">{t("storage.own.empty")}</p>`, `<p className="mt-1 max-w-sm text-sm text-muted">{t("jobs.emptyBody")}</p>`, `<Link to="/jobs" className="mt-4 text-sm font-medium text-accent-text transition duration-150 ease-out hover:underline">{t("jobs.emptyCta")}</Link>` (upload flow lives on `/jobs` — `Jobs.tsx:70,112`).

- [ ] **Step 1: failing test**:

```tsx
test("empty state composed: icon + title + body + CTA → /jobs (AC12)", async () => {
  listJobs.mockResolvedValue({ ...PAGE, items: [], total: 0 });
  renderPage();
  const empty = await screen.findByTestId("storage-own-empty");
  expect(empty.querySelector("svg")).toBeTruthy();
  expect(empty.textContent).toContain("No jobs yet.");
  const cta = screen.getByRole("link", { name: /create your first job/i });
  expect(cta.getAttribute("href")).toBe("/jobs");
});
```

- [ ] **Step 2: run → FAIL** → **Step 3: implement** per Interfaces → **Step 4: run → PASS** (9 tests).
- [ ] **Step 5: Commit**

```bash
git add web/src/pages/Storage.tsx web/src/pages/Storage.test.tsx
git commit -m "feat(RD-storage T6): composed empty state — icon + title + body + CTA link /jobs (AC12)"
```

---

### Task 7: Skeletons matching layout (AC13, P1-2)

**Files:**
- Modify: `web/src/pages/Storage.tsx`
- Test: `web/src/pages/Storage.test.tsx`

**Interfaces:**
- Consumes: `Skeleton` component (`className` prop; testid defaults handled).
- Produces: stats skeleton → wrapper keeps `data-testid="storage-own-loading"`, body = `grid grid-cols-1 gap-4 sm:grid-cols-3` of 3× `<Skeleton className="h-10 w-full" />`. Table skeleton → wrapper keeps `data-testid="storage-own-table-loading"`, body = 4 rows × `grid grid-cols-6 gap-3` of `<Skeleton className="h-4 w-full" />` (last cell `w-16`) — 5 content cols + actions col (AC13).

- [ ] **Step 1: failing test**:

```tsx
test("loading: skeleton khớp layout table — 6 cột × 4 hàng (AC13)", async () => {
  listJobs.mockReturnValue(new Promise(() => {})); // treo vĩnh viễn
  renderPage();
  const sk = await screen.findByTestId("storage-own-table-loading");
  expect(sk.querySelectorAll(".grid.grid-cols-6").length).toBe(4);
  expect(screen.getByTestId("storage-own-loading")).toBeTruthy();
});
```

- [ ] **Step 2: run → FAIL** → **Step 3: implement** per Interfaces → **Step 4: run → PASS** (10 tests).
- [ ] **Step 5: Commit**

```bash
git add web/src/pages/Storage.tsx web/src/pages/Storage.test.tsx
git commit -m "feat(RD-storage T7): skeleton khớp bảng 6 cột + stat grid (AC13)"
```

---

### Task 8: Pagination (AC10, P0-2)

**Files:**
- Modify: `web/src/pages/Storage.tsx`
- Test: `web/src/pages/Storage.test.tsx`

**Interfaces:**
- Consumes: `api.listJobs(page, page_size)` (client.ts:229, backend `page`/`page_size` Query params confirmed); reuse admin keys `storage.pageInfo`/`storage.prevPage`/`storage.nextPage` (vi.json:442-448).
- Produces: `const PAGE_SIZE = 20;` (mirror `AdminStorage.tsx:11`); `const [page, setPage] = useState(1);`; queryKey `["my-storage", page]`, queryFn `() => api.listJobs(page, PAGE_SIZE)` (existing test asserts refetch → still 2 calls, prefix invalidation intact). Pagination bar inside section, only when `items.length > 0`, after the table wrapper: `‹` Button `testid="storage-own-prev"` `disabled={page <= 1}` → `setPage(p => p-1)`; `›` Button `testid="storage-own-next"` `disabled={page * PAGE_SIZE >= (data?.total ?? 0)}` → `setPage(p => p+1)`; span `t("storage.pageInfo", { page, total })`. Buttons `variant="secondary" size="sm"`, `aria-label` from `storage.prevPage`/`storage.nextPage`.

- [ ] **Step 1: failing test**:

```tsx
test("pagination: next → listJobs(2, 20), prev disable ở page 1 (AC10)", async () => {
  listJobs.mockResolvedValue({ ...PAGE, total: 41 });
  renderPage();
  await screen.findByTestId("storage-own-next");
  expect((screen.getByTestId("storage-own-prev") as HTMLButtonElement).disabled).toBe(true);
  fireEvent.click(screen.getByTestId("storage-own-next"));
  await waitFor(() => expect(listJobs).toHaveBeenCalledWith(2, 20));
  expect((screen.getByTestId("storage-own-prev") as HTMLButtonElement).disabled).toBe(false);
  fireEvent.click(screen.getByTestId("storage-own-prev"));
  await waitFor(() => expect(listJobs).toHaveBeenCalledWith(1, 20));
});
```

- [ ] **Step 2: run → FAIL** → **Step 3: implement** per Interfaces → **Step 4: run → PASS** (11 tests).
- [ ] **Step 5: Commit**

```bash
git add web/src/pages/Storage.tsx web/src/pages/Storage.test.tsx
git commit -m "feat(RD-storage T8): pagination page state + prev/next (listJobs(page,20), AC10)"
```

---

### Task 9: `translate()` → `t()` + full validation (AC1-AC4, A7)

**Files:**
- Modify: `web/src/pages/Storage.tsx`

**Interfaces:**
- Produces: zero `translate(` occurrences in `Storage.tsx`; `translate` import dropped (keep `useT`). 4 sites: `purgeOne` toast, `purgeDue` toast, `toLocaleString(t("i18n.locale"))`, age cell `t("storage.own.ageDays", {n})` (mutation callbacks capture render-scope `t` — same output, lang switches re-render anyway).

- [ ] **Step 1: replace** all `translate(` with `t(` in `Storage.tsx`; remove `translate` from import.
- [ ] **Step 2: grep check**: `grep -n "translate(" web/src/pages/Storage.tsx` → empty (AC8 companion: `grep -n "border-error\|bg-error" web/src/pages/Storage.tsx` → empty).
- [ ] **Step 3: full validation** (paste output into commit message context):
  - `cd web && npx oxlint` → clean (AC4)
  - `cd web && npx tsc -b --force` → clean (AC2)
  - `cd web && npx vitest run` → ALL green incl. 11 Storage/lib tests + i18n parity + App + tokens (AC1)
  - `cd web && npx vite build` → clean (AC3)
- [ ] **Step 4: manual sticky check**: confirm filename `th` has `bg-surface-2` + `td` has `bg-surface` (residual #2, 320px stacking deferred to e2e).
- [ ] **Step 5: Commit**

```bash
git add web/src/pages/Storage.tsx
git commit -m "refactor(RD-storage T9): translate()→t() toàn bộ Storage.tsx (A7) — tsc/vitest/build/oxlint xanh"
```

---

## Final validation (after Task 9)

```
cd web && npx tsc -b --force
cd web && npx vitest run
cd web && npx vite build
cd .. && git log --oneline -10
```
