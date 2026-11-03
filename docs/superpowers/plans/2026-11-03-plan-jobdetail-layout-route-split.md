# Plan — JobDetail layout route split + Overview column ratio (2026-11-03)

Spec: `docs/superpowers/specs/2026-11-03-jobdetail-layout-route-split-design.md` (AC1–AC5).
Branch: none, lands on `master`.
Verify: `cd web && npx tsc -b --force && npx vitest run && npx oxlint`, plus AC5 screenshots.

## Lane 1 — route split (AC1–AC4)

TDD first (red → green), one test file, no production code until the test fails for the right reason.

1. RED in `web/tests/pages/JobDetail.test.tsx` (or `web/tests/App.test.tsx` if it already owns
   route assertions — read both first and put the route tests where the other route tests live):
   - `/jobs/5/layout/word` on mount → word container present (`preview-docx-frame`), `md-editor` absent;
   - `/jobs/5/layout/md` → `md-editor` present;
   - `/jobs/5/layout` with `output_format: "docx"` → word; with `"md"` → md (AC3, already true today);
   - click `switch-mode-word` at `/jobs/5/layout/md` → URL becomes `/jobs/5/layout/word` (AC2).
2. GREEN — smallest change that satisfies it:
   - `web/src/App.tsx`: add `<Route path="/jobs/:id/layout/md" element={<JobDetail section="layout" mode="md" />} />`
     and the `word` twin. Leave `/jobs/:id/layout` as is.
   - `web/src/pages/JobDetail.tsx`: accept an optional `mode?: JobLayoutMode` prop, pass it down to
     `UnifiedEditor` as the initial/forced mode.
   - `web/src/components/UnifiedEditor.tsx`: replace the `useState` initial value with the prop when
     provided (default stays `job.output_format === "docx" ? "word" : "md"`), and make the two
     `switch-mode-*` buttons navigate instead of only setting state
     (`useNavigate`, `to={`/jobs/${id}/layout/${next}`}`). Keep a single source of truth: URL wins.
   - Do not add a redirect from `/jobs/:id/layout` (AC4).
3. Fix the existing tests that click `switch-mode-*` and now need a router (wrap in `MemoryRouter` /
   `createMemoryRouter` — match how the file already renders) — do NOT weaken their assertions.
4. Run: `npx tsc -b --force`, `npx vitest run`, `npx oxlint`.

## Lane 2 — Overview column ratio (AC5)

UI change → repo gate (`AGENTS.md`) applies. Sequence is mandatory: shoot → change → shoot → audit.

1. Stack up: `docker compose -f deploy/docker-compose.dev.yml up -d` (API :8010; postgres already
   running on :5433) + `cd web && npm run dev` (:5173). If the stack cannot come up, STOP and report
   — do not claim AC5 without images.
2. Baseline: `cd web && node scripts/audit-shots.mjs shoot` → `/tmp/audit/jobs__5__1440.png` and
   `...__320.png` (read the file names the script actually produces). Also
   `npm run audit:a11y` → record the `DONE N routes with findings` line.
3. Change: narrow the Overview right column only (`JobDetail.tsx` column definitions /
   `PageShell` usage for `section === "overview"`). Tokens and CSS vars from `web/src` only —
   no new hex. Do not touch `/text` or `/layout` layouts.

   **Constraint found while taking the baseline (parent, 2026-11-03):** the current grid is
   `JobDetail.tsx:547` `grid gap-4 lg:grid-cols-2 lg:gap-6` guarded by a comment recording
   decision **D12**: “2 cột CÂN bằng — trước đây 7/5 để cột trái lửng giữa trang”, and two tests
   pin the class: `web/tests/pages/JobDetail.test.tsx:385` and `:579` both assert
   `className` contains `lg:grid-cols-2`. So a proportional ratio (7/5) is what D12 already
   rejected. Chosen direction: give the right rail a **fixed** width instead of a ratio —
   `lg:grid-cols-[minmax(0,1fr)_22rem]` — so the image column absorbs the extra space and the
   rail no longer depends on image height (job 39's image is much taller than the rail, a
   multi-page job inverts that). Both tests must be updated to the new class, not deleted.

   Baseline measured at 1440: `gridTemplateColumns = "564px 564px"` on a 1152px container
   (`/tmp/audit/overview-before-1440.png`, `/tmp/audit/overview-before-320.png`).
4. Re-shoot the same 2 viewports, read both images, compare to baseline.
5. `npm run audit:a11y` must end `DONE 0 routes with findings`, or state which finding is kept and why.
6. Accepted iteration cap: 1 taste pass + max 2 fix passes.

## Out of scope (user declined)

- Original-image panel on `/text`.
- Any change to `/jobs/:id/extraction`.

## Kết quả (2026-11-03)

### Lane 1 — route split (AC1–AC4) VERIFIED
- RED: 4 test route mới fail `No routes matched location "/jobs/5/layout/word"` / `md`.
- GREEN: `App.tsx` thêm 2 route; `JobDetail` nhận `mode?: LayoutMode`, `layoutFmt = mode ?? output_format`;
  `UnifiedEditor` bỏ `useState` mode, `switch-mode-*` gọi `navigate(/jobs/{id}/layout/{next})` → reload/back/forward giữ mode.
- `/jobs/:id/layout` giữ nguyên (không redirect, AC4).
- `npx vitest run` 60 file / **450 test pass** (+6 mới), `tsc -b --force` sạch, `oxlint` exit 0.

### Lane 2 — Overview rail (AC5) VERIFIED
- Baseline 1440: `gridTemplateColumns = "564px 564px"` (cân bằng) → sau: **`776px 352px`**
  (`lg:grid-cols-[minmax(0,1fr)_22rem]`). 320 giữ nguyên 288px, ảnh before/after **byte-identical**.
- `audit:a11y` baseline (grid cũ) `DONE 5 routes with findings` → sau `DONE **4** routes with findings`.
  Không phát sinh finding mới; 4 finding còn lại là pre-existing và ngoài scope AC5:
  - `/jobs` 1440 + 320 — `input[data-testid=jobs-search]` thiếu label/aria-label
  - `/profile` 1440 + 320 — `input-current-password` thiếu label
  (`/jobs/5/text@320` small-target chỉ xuất hiện ở lần chạy baseline, phụ thuộc dữ liệu job 5.)
- Giới hạn: Ảnh chứng cứ ở `/tmp/audit/overview-{before,after}-{1440,320}.png` (không commit, theo AGENTS.md).
