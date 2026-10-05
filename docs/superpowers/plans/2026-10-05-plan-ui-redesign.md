# Plan UI — Redesign: Design System, Permissions, Files, Profile, Admin

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps use checkbox syntax.

**Goal:** Rework the bare SPA into a coherent, permission-explicit UI: design system + role-aware nav (login/logout in ONE auth zone), file-centric job list/detail (see what was uploaded, whether processed), per-region inline edit, profile page for both roles, admin rework without the user jobs board.

**Architecture:** web/ only (plus two small server endpoints from Plan H, consumed as contracts). Design system first; every later task migrates onto it. R30 binding: FE tests = vi.mock api + data-testid assertions + handler args; component tests per task.

**Tech Stack:** Vite React TS + Tailwind v4 + TanStack Query v5 + react-router + vitest RTL (existing). Apply **ui-ux-dev skill** checklist end-to-end.

**Spec:** docs/superpowers/specs/2026-10-04-img2text-mvp-design.md §8/§10 + approved in-chat design (2026-10-05).

## Global Constraints (ui-ux-dev, non-negotiable)

- Tokens: CSS variables semantic (`--bg --surface --text --muted --accent --border --success --warning --error`) in `src/styles/tokens.css`; **dark theme DEFAULT** (bg #0d1117-ish, text #e6edf3, muted #8b949e, accent one hue), Tailwind `dark` class on `<html>`, toggle `data-testid="btn-theme"` persists localStorage. Contrast ≥4.5:1 text / ≥3:1 UI.
- `<Button>` (src/components/ui/Button.tsx): variants `primary|secondary|ghost|danger`, sizes `sm|md`, loading+disabled states, `:focus-visible` 2px accent ring, cursor pointer, aria-busy while loading. ALL existing buttons migrate (auth forms, upload, export×4, edit/save, retry, admin refresh, logout).
- `<Badge>` (ui/Badge.tsx): tone map (neutral/success/warning/error/info) — job statuses, OCR status, role.
- `<Card>` (ui/Card.tsx): border 1px var(--border), radius 10px, section header slot.
- `<Input>` (ui/Input.tsx): visible label, focus ring, error state + message slot.
- Spacing scale 4/8/16/24/32/48; gap not margin between siblings; max-w container; sticky nav with backdrop-blur; mobile hamburger (aria-expanded/controls/label, closes on link+outside click); skip link `#main`; semantic `nav/main/section/h1-h3`; one h1 per page; `prefers-reduced-motion` respected.
- Responsive: 320/768/1024/1440 no horizontal scroll; card grids `repeat(auto-fit, minmax(280px,1fr))`.
- Preserve EXISTING testids asserted by current tests (btn-login etc.) — update tests only when a component's DOM role changes, never delete an assertion to make it pass.
- R30 mock pattern unchanged; npm test + tsc + lint green per task; single commit per task.

## Review Focus

- Every migrated button keeps its testid + handler args (suite stays green WITHOUT weakening).
- Theme toggle: class lands on `<html>`, persists across reload (localStorage), default dark on first visit.
- Auth zone: logged-out shows only `Đăng nhập`+`Đăng ký` on the RIGHT; logged-in shows badges + `Hồ sơ`+`Đăng xuất` right; no duplicate auth links on the left.
- Admin: NO `Công việc` nav item for admin (jobs board user-only in UI; server owner-or-admin unchanged).
- Region inline edit: PATCH /api/jobs/{id}/regions/{rid} contract (Plan H Task 2) — mock + assert args + `markdown_replaced:false` still closes editor cleanly.

---

### Task 0: Design system + app shell (auth zone right, dark default)

**Files:**
- Create: `web/src/styles/tokens.css`, `web/src/components/ui/{Button,Badge,Card,Input}.tsx` (+ .test.tsx each), `web/src/components/ThemeToggle.tsx`
- Modify: `web/src/index.css` (import tokens, tailwind dark strategy), `web/src/App.tsx` (nav rework: LEFT brand+Công việc+Quản trị(role); RIGHT auth zone — logged out: btn-login+btn-register; logged in: OCR badge + avatar initials + btn-profile + btn-logout), `web/src/main.tsx`, all pages (migrate buttons/inputs to ui components), existing tests (only testid/DOM-role adaptations).

**Interfaces:**
- Produces: Button props `{variant,size,loading,disabled,testid,onClick,children,type}`, Badge `{tone,children,testid}`, Card `{title,testid,children,actions?}`, Input `{label,testid,error,...input props}`, ThemeToggle (toggles `dark` class on documentElement, persists `img2text-theme`).
- Nav contract (binding): LEFT `nav-brand|nav-link-jobs|nav-link-admin`; RIGHT `auth-zone` container: logged-out `btn-login`(primary sm)+"Đăng nhập", `btn-register`(ghost sm)+"Đăng ký"; logged-in `badge-ocr` (🟢"OCR đã cấp"/🟡"Chờ admin cấp quyền"), `nav-avatar` (initials, title=role), `btn-profile`(ghost)+"Hồ sơ", `btn-logout`(danger ghost)+"Đăng xuất". Remove LEFT login link (test updated accordingly — assertion MOVED not deleted).

- [ ] Step 1: Failing tests (Button variants/states; Input error; ThemeToggle default-dark+persistence; App nav: logged-out right-zone has login+register, NO left login; logged-in right-zone has profile+logout+badge-ocr both tones; admin sees nav-link-admin, user doesn't)
- [ ] Step 2: Run → FAIL
- [ ] Step 3: Implement (migrate ALL existing buttons/inputs to ui components; keep testids; suite green)
- [ ] Step 4: Run → PASS (full web suite + tsc + lint + build)
- [ ] Step 5: Commit `feat(web): design system + role-aware app shell`

---

### Task 1: Jobs list rework (files at a glance)

**Files:**
- Create: `web/src/components/JobRow.tsx`, `web/src/components/StatusFilterTabs.tsx`, `web/src/components/Dropzone.tsx` (+ tests)
- Modify: `web/src/pages/Jobs.tsx`, `web/src/pages/Jobs.test.tsx`

**Interfaces:**
- `JobRow` props `{job: JobListItem}`: filename (basename of storage_key — NOTE: server list does NOT return storage_key; use `#${id} · ${file_type} · ${page_count} trang` + file_type icon badge as name line — binding choice, no server change), Badge status (reuse StatusBadge → migrate to ui/Badge), created_at formatted vi-VN, duration when done/failed (finished_at-started_at), actions: btn-view-{id}→navigate detail, btn-dl-original-{id} (done only: api.getJob → getCropUrl? NO — file presign = api endpoint /jobs/{id}/file → add client method `getJobFile(id)→{url}` + window.open), btn-retry-{id} when failed.
- `StatusFilterTabs`: tabs testid filter-all|queued|running|done|failed with counts (computed client-side), default all.
- `Dropzone`: real drag-drop (onDragOver/Leave/Drop) + hidden input-file + btn-upload preserved; disabled+banner when !ocr_enabled (migrate UploadButton behavior into it); upload-error surfacing preserved.
- Empty state card: guidance text + limits (50 trang/50MB) + link to Colab-setup doc note ("job chờ worker Colab").

- [ ] Step 1: Failing tests (filter counts+click filters rows; row renders type/pages/status/date/duration; dl-original opens presigned url — api.getJobFile mock; retry calls api.retryJob; dropzone drop triggers uploadJob; empty state renders guidance; upload gate banner preserved)
- [ ] Steps 2–4: TDD cycle (suite green)
- [ ] Step 5: Commit `feat(web): file-centric job list with filters and dropzone`

---

### Task 2: Job detail — 3 panels + per-region inline edit

**Files:**
- Create: `web/src/components/panels/{OriginalFilePanel,ResultPanel,InfoPanel}.tsx`, `web/src/components/RegionEditor.tsx` (+ tests)
- Modify: `web/src/pages/JobDetail.tsx`, `JobDetail.test.tsx`, `web/src/api/client.ts` (+ `patchRegion(jobId, rid, text)` → PATCH /api/jobs/{id}/regions/{rid} → `{id,text,markdown_replaced}`, + types)

**Interfaces:**
- `OriginalFilePanel`: testid panel-original; expand button toggle-original → lazy fetch api.getJobFile(id) (new client method → {url}) → `<img>` if file_type image, `<iframe>` if pdf (title attr for a11y), + link target=_blank "Mở tab mới"; loading skeleton Card; error state.
- `ResultPanel`: verdict stats line (counts per verdict from result pages — testid result-stats): `Tổng {n} vùng · {ok} ok · {img} hình ảnh · {unreadable} không trích xuất · {low} cần kiểm tra`; existing MarkdownPreview + IssuesPanel + ExportBar + MarkdownEditor (btn-edit stays prominent — Card header slot action).
- `RegionEditor`: IssuesPanel rows gain btn-edit-region-{rid} → inline textarea + btn-save-region-{rid} → api.patchRegion(id, rid, text) → update local regions state + invalidate ["job", id]; response markdown_replaced:false → show inline note "Văn bản vùng đã cập nhật; markdown chưa thay thế (text gốc không còn trong bản xem trước)". Cancel btn-cancel-region-{rid} restores.
- `InfoPanel`: testid panel-info; created/started/finished (vi-VN), page_count, gpu_seconds + model_version when result present, status Badge.

- [ ] Step 1: Failing tests (panels render from mocked job; original panel lazy — api.getJobFile only after expand; iframe vs img by file_type; stats counts exact; RegionEditor save args + invalidate + replaced-note; cancel restores; patchRegion 404 → error text)
- [ ] Steps 2–4: TDD cycle
- [ ] Step 5: Commit `feat(web): job detail panels + region inline edit`

---

### Task 3: Profile page (both roles)

**Files:**
- Create: `web/src/pages/Profile.tsx`, `web/src/pages/Profile.test.tsx`
- Modify: `web/src/App.tsx` (route /profile), `web/src/api/client.ts` (+ `updateProfile({current_password, email?, new_password?})`)

**Interfaces:**
- Profile page: Card "Thông tin" (email, role Badge, ocr status Badge, ngày tham gia — me()+created_at? me returns {id,email,role,ocr_enabled} — binding: show id+email+role+ocr; created_at note "sắp có" if absent — NO server change); Card "Đổi mật khẩu" (input-current-password, input-new-password, input-new-password2 client-side match, btn-save-password → api.updateProfile → success toast-line + note "Phiên đăng nhập khác đã bị đăng xuất"); Card "Đổi email" (input-current-password-2, input-new-email, btn-save-email → api.updateProfile). Errors via ApiError.detail pattern (401 wrong current, 409 duplicate).

- [ ] Step 1: Failing tests (renders info; password submit args; success message; email submit args; 409 detail surfaced; mismatch client-side no api call)
- [ ] Steps 2–4: TDD
- [ ] Step 5: Commit `feat(web): profile page`

---

### Task 4: Admin rework (no jobs board)

**Files:**
- Create: `web/src/pages/admin/{AdminOverview,AdminUsers,AdminApi,AdminLogs,AdminStats}.tsx` (split existing), tests
- Modify: `web/src/pages/Admin.tsx` (5 tabs: Tổng quan|Người dùng|API|Logs|Thống kê — testids tab-overview|tab-users|tab-api|tab-logs|tab-stats; DEFAULT tab-overview), `web/src/api/client.ts` if needed (none expected — api activity = client-side aggregate from existing adminLogs)

**Interfaces:**
- AdminOverview: stat cards (users today/jobs today done/failed/gpu_seconds/cost từ adminStats(7d) — first day row + totals) + quick links to tabs.
- AdminUsers: migrate to ui components + add created_at column (server list returns it).
- AdminApi (NEW): fetch adminLogs({limit:500}) → aggregate client-side: rows grouped by path-prefix (strip /api/jobs/{id}→/api/jobs/{id}, first3 segments max) × status-class counts (2xx/4xx/5xx) + total; table testid api-activity-table; note "tổng hợp client-side từ request_logs".
- AdminLogs/AdminStats: migrate to ui components (behavior unchanged; existing tests adapted).
- Admin nav: Admin.tsx gates role (redirect / when non-admin — existing) — and App nav shows Quản trị ONLY for admin (Task 0) — assert here: admin home has NO jobs board, no upload dropzone.

- [ ] Step 1: Failing tests (5 tabs render; overview stats from mocked stats; api-activity aggregation exact for seeded mock rows incl. /api/jobs/{id} collapsing; users table shows created_at; non-admin redirect kept; no job rows/dropzone anywhere in Admin)
- [ ] Steps 2–4: TDD
- [ ] Step 5: Commit `feat(web): admin overview/users/api/logs/stats`

**Plan UI done when:** all tasks green (npm test + tsc + lint + build), branch `plan-ui` ready for final review + merge after Plan H (contracts already pinned).
