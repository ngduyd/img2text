# Plan F — Frontend SPA (Vite + React + TS)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Full user-facing SPA — auth pages, job list + upload with `ocr_enabled` gate, job detail with polling, sandboxed Markdown preview, issues panel with crops, export buttons, inline editing, admin tabs (users/stats/logs).

**Architecture:** Vite + React 18 + TypeScript + react-router + TanStack Query + Tailwind. Every task ships component tests (vitest + @testing-library/react + jsdom) that assert the button/component **exists in the DOM** and its handler fires with the exact arguments — per project rule: no task without a UI-element assertion. `src/api/client.ts` is the single fetch wrapper (cookies `credentials:"include"`, JSON, throws `{detail}`); pages mock it via `vi.mock`.

**Tech Stack:** node ≥20, vite, react, typescript, @tanstack/react-query, react-router-dom, tailwindcss, marked, dompurify, vitest, @testing-library/react, @testing-library/user-event, jsdom.

**Spec:** §10 frontend pages, §8 API surface, §7 verdicts, §10 editing & fidelity.

**Depends on:** Plans B/D/E (API contracts pinned in Interfaces below — frontend builds against contract, mocks in tests; integration verified manually in Plan G checklist).

## Global Constraints

- All API calls via `src/api/client.ts`: `request<T>(path, opts)` sets `credentials:"include"`, `Content-Type: application/json` when body, parses `{detail}` errors → `ApiError(detail: string)`.
- `data-testid` on every interactive element asserted by tests (in addition to accessible name).
- Verdict label map (`src/lib/verdicts.ts`): `ok→"Đã trích xuất"`, `image_unextractable→"Hình ảnh chưa trích xuất"`, `unreadable→"Không trích xuất được văn bản"`, `low_confidence→"Cần kiểm tra"`.
- Preview: `marked.parse` → `DOMPurify.sanitize` → iframe `srcdoc` with `sandbox=""` (no allow-same-origin, no scripts). Test asserts `sandbox` attribute present and `srcdoc` contains rendered heading.
- Polling: `useQuery` with `refetchInterval: q => q.state.data?.status === "queued" || "running" ? 3000 : false`.
- ocr_enabled gate: `/` shows banner `Chờ admin cấp quyền` + upload button `disabled`.
- Export buttons call `api.exportJob(id, fmt)` then `window.open(url, "_blank")`.
- Commit per task; tests: `cd web && npm test`.

## Review Focus

- XSS: preview must sanitize BEFORE srcdoc (test with `<img onerror>` in markdown → srcdoc contains sanitized output only).
- Polling stops when done (test: after status done, `refetchInterval` false — assert via query client spy or component unmount cleanliness).
- Upload button truly `disabled` (test `toBeDisabled()`, not just visual).
- Export button double-click fires once per click (no in-flight dedupe needed MVP — documented).
- Issues panel renders crop `<img>` with presigned URL from api (test src equals mock return).

---

### Task 1: Scaffold + api client + router shell

**Files:**
- Create: `web/package.json`, `web/vite.config.ts`, `web/tsconfig.json`, `web/src/main.tsx`, `web/src/App.tsx`, `web/src/api/client.ts`, `web/src/api/types.ts`, `web/src/lib/verdicts.ts`, `web/src/test/setup.ts`, `web/src/App.test.tsx`, `web/src/api/client.test.ts`

**Interfaces:**
- Produces: `ApiError extends Error {detail: string}`; `api` object: `register(email,password)`, `login(email,password)`, `logout()`, `me()`, `refresh()`, `forgotEmail(email)`, `resetPassword(token,password)`, `listJobs()`, `getJob(id)`, `uploadJob(file: File)`, `retryJob(id)`, `patchContent(id, markdown)`, `exportJob(id, fmt)`, `getCropUrl(jobId, rid)`, `adminListUsers(page)`, `adminPatchUser(id, ocr_enabled)`, `adminStats(from,to)`, `adminLogs(filters)`, `adminLogsTail(lines)` — all return parsed JSON; `exportJob` returns `{url: string}`; `getCropUrl` returns `{url: string}`. `VERDICT_LABELS: Record<string,string>`.

- [ ] **Step 1: Failing tests**:

`web/src/App.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import App from "./App";

it("renders app shell with brand and nav links", () => {
  render(<App />);
  expect(screen.getByTestId("nav-brand")).toHaveTextContent("img2text");
  expect(screen.getByTestId("nav-link-jobs")).toBeInTheDocument();
  expect(screen.getByTestId("nav-link-admin")).toBeInTheDocument();
});
```

`web/src/api/client.test.ts` (fetch mocked global):

```ts
it("login sends credentials include and json body", async () => {
  const spy = vi.fn().mockResolvedValue(new Response(JSON.stringify({}), {status: 200}));
  vi.stubGlobal("fetch", spy);
  await api.login("u@x.io", "secret123");
  const [url, opts] = spy.mock.calls[0];
  expect(url).toBe("/api/auth/login");
  expect(opts.credentials).toBe("include");
  expect(JSON.parse(opts.body)).toEqual({ email: "u@x.io", password: "secret123" });
});

it("throws ApiError with detail on 4xx", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(
    new Response(JSON.stringify({detail: "Chưa được cấp quyền OCR."}), {status: 403})));
  await expect(api.uploadJob(new File([], "a.jpg"))).rejects.toThrow("Chưa được cấp quyền OCR.");
});
```

- [ ] **Step 2: Run → FAIL** (`cd web && npm test`)
- [ ] **Step 3: Implement** scaffold per Interfaces: `npm create vite@latest web -- --template react-ts`; add deps; `client.ts` with `request<T>`; `App.tsx` routes `/login /register /forgot /reset / /jobs/:id /admin` (placeholder components inline for now — real pages in later tasks); Tailwind + vitest config (`environment: "jsdom"`, setup file).
- [ ] **Step 4: Run → PASS**
- [ ] **Step 5: Commit** `feat(web): scaffold, api client, router shell`

---

### Task 2: Auth pages (login / register / forgot / reset)

**Files:**
- Create: `web/src/pages/Login.tsx`, `Register.tsx`, `Forgot.tsx`, `Reset.tsx`, `web/src/pages/Auth.test.tsx`
- Modify: `web/src/App.tsx` (wire real pages)

**Interfaces:**
- Produces: `Login` — email+password inputs, button `data-testid="btn-login"` label `Đăng nhập`, error text on ApiError; on success `navigate("/")`. `Register` — btn `btn-register` label `Đăng ký`. `Forgot` — btn `btn-forgot` label `Gửi email đặt lại`; success message `Kiểm tra email của bạn.` (always shown on 202). `Reset` — reads `?token=`, two password fields, btn `btn-reset` label `Đặt lại mật khẩu`, success → navigate `/login`.

- [ ] **Step 1: Failing tests** `web/src/pages/Auth.test.tsx` (mock `../api/client`):

```tsx
it("login button exists and submits credentials", async () => {
  vi.mocked(api.login).mockResolvedValue({});
  renderWithRouter(<Login />);
  await user.type(screen.getByTestId("input-email"), "u@x.io");
  await user.type(screen.getByTestId("input-password"), "secret123");
  await user.click(screen.getByTestId("btn-login"));
  expect(screen.getByTestId("btn-login")).toBeInTheDocument();
  expect(api.login).toHaveBeenCalledWith("u@x.io", "secret123");
});

it("login shows server detail error", async () => {
  vi.mocked(api.login).mockRejectedValue(new ApiError("Sai mật khẩu."));
  renderWithRouter(<Login />);
  await user.click(screen.getByTestId("btn-login"));
  expect(await screen.findByText("Sai mật khẩu.")).toBeInTheDocument();
});

it("register button exists and submits", async () => {
  vi.mocked(api.register).mockResolvedValue({});
  renderWithRouter(<Register />);
  await user.click(screen.getByTestId("btn-register"));
  expect(api.register).toHaveBeenCalled();
});

it("forgot shows constant success message", async () => {
  vi.mocked(api.forgotEmail).mockResolvedValue({});
  renderWithRouter(<Forgot />);
  await user.click(screen.getByTestId("btn-forgot"));
  expect(await screen.findByText("Kiểm tra email của bạn.")).toBeInTheDocument();
});

it("reset submits token from query", async () => {
  vi.mocked(api.resetPassword).mockResolvedValue({});
  renderWithRouter(<Reset />, { route: "/reset?token=abc123" });
  await user.click(screen.getByTestId("btn-reset"));
  expect(api.resetPassword).toHaveBeenCalledWith("abc123", expect.any(String));
});
```

- [ ] **Step 2: Run → FAIL** → **Step 3: Implement** per Interfaces (react-router `useNavigate`, `useSearchParams`; forms controlled components; error state from `ApiError.detail`).
- [ ] **Step 4: Run → PASS** → **Step 5: Commit** `feat(web): auth pages with testid-bound actions`

---

### Task 3: Job list + upload dropzone + ocr_enabled gate

**Files:**
- Create: `web/src/pages/Jobs.tsx`, `web/src/components/UploadButton.tsx`, `web/src/components/StatusBadge.tsx`, `web/src/pages/Jobs.test.tsx`
- Modify: `web/src/App.tsx`

**Interfaces:**
- Consumes: `api.me()`, `api.listJobs()`, `api.uploadJob(file)`.
- Produces: `UploadButton` — hidden file input `data-testid="input-file"`, button `data-testid="btn-upload"` label `Tải file lên`; `disabled` when `!me.ocr_enabled`; banner `data-testid="banner-no-access"` text `Chờ admin cấp quyền` when disabled; onChange → `api.uploadJob(file)` → `navigate(\`/jobs/${id}\`)`. `StatusBadge` maps `queued→"Chờ xử lý"`, `running→"Đang xử lý"`, `done→"Hoàn tất"`, `failed→"Thất bại"`. `Jobs` page: useQuery `["jobs"]` + `["me"]`.

- [ ] **Step 1: Failing tests** `web/src/pages/Jobs.test.tsx`:

```tsx
it("banner and disabled upload when ocr_enabled false", async () => {
  vi.mocked(api.me).mockResolvedValue({ id: 1, role: "user", ocr_enabled: false });
  vi.mocked(api.listJobs).mockResolvedValue({ items: [], total: 0 });
  renderWithRouter(<Jobs />);
  expect(await screen.findByTestId("banner-no-access")).toHaveTextContent("Chờ admin cấp quyền");
  expect(screen.getByTestId("btn-upload")).toBeDisabled();
});

it("upload button enabled and calls api when granted", async () => {
  vi.mocked(api.me).mockResolvedValue({ id: 1, role: "user", ocr_enabled: true });
  vi.mocked(api.listJobs).mockResolvedValue({ items: [], total: 0 });
  vi.mocked(api.uploadJob).mockResolvedValue({ id: 42, status: "queued", page_count: 3 });
  renderWithRouter(<Jobs />);
  const btn = await screen.findByTestId("btn-upload");
  expect(btn).toBeEnabled();
  const file = new File(["x"], "a.jpg", { type: "image/jpeg" });
  await user.upload(screen.getByTestId("input-file"), file);
  expect(api.uploadJob).toHaveBeenCalledWith(file);
  await waitFor(() => expect(mockNavigate).toHaveBeenCalledWith("/jobs/42"));
});

it("job rows render status badge", async () => {
  vi.mocked(api.me).mockResolvedValue({ id: 1, role: "user", ocr_enabled: true });
  vi.mocked(api.listJobs).mockResolvedValue({ items: [{ id: 7, status: "queued", page_count: 2, file_type: "pdf", created_at: "2026-10-04T00:00:00Z", error: null }], total: 1 });
  renderWithRouter(<Jobs />);
  expect(await screen.findByTestId("job-row-7")).toBeInTheDocument();
  expect(screen.getByTestId("badge-7")).toHaveTextContent("Chờ xử lý");
});
```

- [ ] **Step 2: Run → FAIL** → **Step 3: Implement** per Interfaces; `mockNavigate` from `vi.mock("react-router-dom", ...)` in setup.
- [ ] **Step 4: Run → PASS** → **Step 5: Commit** `feat(web): job list, upload, access gate`

---

### Task 4: Job detail status + retry + polling

**Files:**
- Create: `web/src/pages/JobDetail.tsx`, `web/src/pages/JobDetail.test.tsx`
- Modify: `web/src/App.tsx`

**Interfaces:**
- Consumes: `api.getJob(id)`, `api.retryJob(id)`.
- Produces: `JobDetail` — `useQuery(["job", id], () => api.getJob(id), { refetchInterval })`; status texts: `queued→"Đang chờ worker Colab"`, `running→"Đang xử lý"`, `failed→"Xử lý thất bại"`, `done→"Hoàn tất"`; `failed` shows button `data-testid="btn-retry"` label `Thử lại` → `api.retryJob(id)` → invalidate; `done` shows preview components (Task 5/6/7 placeholders now, wired later).

- [ ] **Step 1: Failing tests**:

```tsx
it("queued shows waiting message and polls", async () => {
  vi.mocked(api.getJob).mockResolvedValue({ id: 5, status: "queued", page_count: 1, result: null });
  renderWithRouter(<JobDetail />, { route: "/jobs/5" });
  expect(await screen.findByText("Đang chờ worker Colab")).toBeInTheDocument();
  // polling: refetchInterval evaluated true for queued — assert via queryClient spy
  expect(pollSpyCalled()).toBe(true);   // helper wrapping QueryClient defaultOptions check
});

it("failed shows retry button and calls api", async () => {
  vi.mocked(api.getJob).mockResolvedValue({ id: 5, status: "failed", error: "boom", result: null });
  vi.mocked(api.retryJob).mockResolvedValue({ id: 5, status: "queued" });
  renderWithRouter(<JobDetail />, { route: "/jobs/5" });
  expect(await screen.findByText("Xử lý thất bại")).toBeInTheDocument();
  await user.click(screen.getByTestId("btn-retry"));
  expect(api.retryJob).toHaveBeenCalledWith("5");
});

it("done stops polling", async () => {
  vi.mocked(api.getJob).mockResolvedValue({ id: 5, status: "done", result: EMPTY_RESULT });
  renderWithRouter(<JobDetail />, { route: "/jobs/5" });
  expect(await screen.findByTestId("preview-markdown")).toBeInTheDocument();
  expect(pollSpyCalled()).toBe(false);
});
```

- [ ] **Step 2: Run → FAIL** → **Step 3: Implement** per Interfaces.
- [ ] **Step 4: Run → PASS** → **Step 5: Commit** `feat(web): job detail status, polling, retry`

---

### Task 5: Sandboxed Markdown preview

**Files:**
- Create: `web/src/components/MarkdownPreview.tsx`, `web/src/components/MarkdownPreview.test.tsx`

**Interfaces:**
- Produces: `MarkdownPreview({markdown}: {markdown: string})` — `data-testid="preview-markdown"`; renders iframe `sandbox=""`, `srcdoc` = `<!doctype html><meta charset="utf-8">` + sanitized marked output; `srcdoc` contains rendered `<h2>`/`<table>` for given markdown.

- [ ] **Step 1: Failing tests**:

```tsx
it("renders sanitized markdown in sandboxed iframe", () => {
  render(<MarkdownPreview markdown={"## Part 2\n\n| A | B |\n|---|---|\n| 1 | 2 |"} />);
  const iframe = screen.getByTestId("preview-markdown");
  expect(iframe).toHaveAttribute("sandbox", "");
  expect(iframe.getAttribute("srcdoc")).toContain("<h2");
  expect(iframe.getAttribute("srcdoc")).toContain("<table");
});

it("strips script and event handlers", () => {
  render(<MarkdownPreview markdown={"# Hi\n\n<img src=x onerror=alert(1)>\n\n<script>alert(2)</script>"} />);
  const srcdoc = screen.getByTestId("preview-markdown").getAttribute("srcdoc") ?? "";
  expect(srcdoc).not.toContain("onerror");
  expect(srcdoc).not.toContain("<script>alert(2)</script>");
});
```

- [ ] **Step 2: Run → FAIL** → **Step 3: Implement** per Interfaces: `DOMPurify.sanitize(marked.parse(markdown))`; iframe `data-testid` on the iframe element itself.
- [ ] **Step 4: Run → PASS** → **Step 5: Commit** `feat(web): sandboxed sanitized markdown preview`

---

### Task 6: Issues panel with crops + verdict labels

**Files:**
- Create: `web/src/components/IssuesPanel.tsx`, `web/src/components/IssuesPanel.test.tsx`
- Modify: `web/src/pages/JobDetail.tsx` (render when `result.issues` or derived regions with verdict≠ok)

**Interfaces:**
- Consumes: `api.getCropUrl(jobId, rid)`, `VERDICT_LABELS`.
- Produces: `IssuesPanel({jobId, regions}: {jobId: string; regions: RegionOut[]})` — renders one row per region where `verdict !== "ok"`: `data-testid={\`issue-${rid}\`}`, label from `VERDICT_LABELS`, region id text, crop `<img data-testid={\`crop-${rid}\`}>` with `src` from `api.getCropUrl` result (only when `bbox != null`), VLM text excerpt.

- [ ] **Step 1: Failing tests**:

```tsx
const regions = [
  { id: "p1r0", bbox: [1,2,3,4], text: "", verdict: "image_unextractable", placeholder: true },
  { id: "p1r1", bbox: null, text: "", verdict: "unreadable", placeholder: false },
  { id: "p1r2", bbox: [9,9,20,20], text: "ok text", verdict: "ok", placeholder: false },
];

it("renders only non-ok issues with vietnamese labels", async () => {
  vi.mocked(api.getCropUrl).mockResolvedValue({ url: "https://r2/crops/p1r0.jpg" });
  render(<IssuesPanel jobId="5" regions={regions} />);
  expect(await screen.findByTestId("issue-p1r0")).toBeInTheDocument();
  expect(screen.getByTestId("issue-p1r1")).toBeInTheDocument();
  expect(screen.queryByTestId("issue-p1r2")).toBeNull();
  expect(screen.getByTestId("issue-p1r0")).toHaveTextContent("Hình ảnh chưa trích xuất");
  expect(screen.getByTestId("issue-p1r1")).toHaveTextContent("Không trích xuất được văn bản");
});

it("shows crop image only when bbox present", async () => {
  vi.mocked(api.getCropUrl).mockResolvedValue({ url: "https://r2/crops/p1r0.jpg" });
  render(<IssuesPanel jobId="5" regions={regions} />);
  expect((await screen.findByTestId("crop-p1r0")) as HTMLImageElement).src
    .toBe("https://r2/crops/p1r0.jpg");
  expect(screen.queryByTestId("crop-p1r1")).toBeNull();
});
```

- [ ] **Step 2: Run → FAIL** → **Step 3: Implement** per Interfaces.
- [ ] **Step 4: Run → PASS** → **Step 5: Commit** `feat(web): issues panel with verdicts and crops`

---

### Task 7: Export buttons

**Files:**
- Create: `web/src/components/ExportBar.tsx`, `web/src/components/ExportBar.test.tsx`
- Modify: `web/src/pages/JobDetail.tsx`

**Interfaces:**
- Consumes: `api.exportJob(id, fmt)`.
- Produces: `ExportBar({jobId}: {jobId: string})` — four buttons `data-testid="export-md|export-html|export-docx|export-pdf"`, labels `Tải .md`, `Tải .html`, `Tải .docx`, `Tải .pdf`; onClick → `api.exportJob(jobId, fmt)` → `window.open(url, "_blank")`.

- [ ] **Step 1: Failing tests**:

```tsx
it("four export buttons exist and call api with fmt", async () => {
  vi.mocked(api.exportJob).mockResolvedValue({ url: "https://r2/exports/5/docx" });
  const open = vi.fn(); vi.stubGlobal("open", open);
  render(<ExportBar jobId="5" />);
  for (const fmt of ["md", "html", "docx", "pdf"]) {
    expect(screen.getByTestId(`export-${fmt}`)).toBeInTheDocument();
  }
  await user.click(screen.getByTestId("export-docx"));
  expect(api.exportJob).toHaveBeenCalledWith("5", "docx");
  await waitFor(() => expect(open).toHaveBeenCalledWith("https://r2/exports/5/docx", "_blank"));
});
```

- [ ] **Step 2: Run → FAIL** → **Step 3: Implement** per Interfaces.
- [ ] **Step 4: Run → PASS** → **Step 5: Commit** `feat(web): export bar`

---

### Task 8: Inline editing (edited_markdown)

**Files:**
- Create: `web/src/components/MarkdownEditor.tsx`, `web/src/components/MarkdownEditor.test.tsx`
- Modify: `web/src/pages/JobDetail.tsx`

**Interfaces:**
- Consumes: `api.patchContent(id, markdown)`.
- Produces: `MarkdownEditor({jobId, initial}: {jobId: string; initial: string})` — button `data-testid="btn-edit"` label `Chỉnh sửa` toggles textarea `data-testid="textarea-markdown"` (value=initial); button `data-testid="btn-save"` label `Lưu` → `api.patchContent(jobId, value)` → toggle off + invalidate `["job", jobId]`.

- [ ] **Step 1: Failing tests**:

```tsx
it("edit toggles textarea and save calls patchContent", async () => {
  vi.mocked(api.patchContent).mockResolvedValue({});
  render(<MarkdownEditor jobId="5" initial={"## Part 2"} />);
  expect(screen.queryByTestId("textarea-markdown")).toBeNull();
  await user.click(screen.getByTestId("btn-edit"));
  const ta = screen.getByTestId("textarea-markdown") as HTMLTextAreaElement;
  expect(ta.value).toBe("## Part 2");
  await user.clear(ta);
  await user.type(ta, "# Đã sửa");
  await user.click(screen.getByTestId("btn-save"));
  expect(api.patchContent).toHaveBeenCalledWith("5", "# Đã sửa");
  await waitFor(() => expect(screen.queryByTestId("textarea-markdown")).toBeNull());
});
```

- [ ] **Step 2: Run → FAIL** → **Step 3: Implement** per Interfaces.
- [ ] **Step 4: Run → PASS** → **Step 5: Commit** `feat(web): inline markdown editing`

---

### Task 9: Admin page (tabs: users / stats / logs)

**Files:**
- Create: `web/src/pages/Admin.tsx`, `web/src/components/AdminUsers.tsx`, `AdminStats.tsx`, `AdminLogs.tsx`, `web/src/pages/Admin.test.tsx`
- Modify: `web/src/App.tsx`

**Interfaces:**
- Consumes: `api.adminListUsers`, `api.adminPatchUser`, `api.adminStats`, `api.adminLogs`, `api.adminLogsTail`.
- Produces: tabs `data-testid="tab-users|tab-stats|tab-logs"` labels `Người dùng`,`Thống kê`,`Logs`; `AdminUsers` rows with toggle `data-testid={\`toggle-ocr-${id}\`}` (checkbox) → `api.adminPatchUser(id, next)`; `AdminStats` table headers `Ngày`,`Đăng ký`,`Job`,`Hoàn tất`,`Thất bại`,`Lượt xem`,`GPU (giây)`,`Chi phí ước tính`; `AdminLogs` filter input `data-testid="input-log-ip"` + refresh button `data-testid="btn-logs-refresh"` → `api.adminLogs({ip})`, plus tail list from `api.adminLogsTail(200)`.

- [ ] **Step 1: Failing tests**:

```tsx
it("tabs exist and users tab toggles ocr", async () => {
  vi.mocked(api.me).mockResolvedValue({ id: 1, role: "admin", ocr_enabled: true });
  vi.mocked(api.adminListUsers).mockResolvedValue({ items: [{ id: 2, email: "a@x.io", role: "user", ocr_enabled: false, created_at: "2026-10-04" }], total: 1 });
  vi.mocked(api.adminPatchUser).mockResolvedValue({ id: 2, email: "a@x.io", role: "user", ocr_enabled: true, created_at: "2026-10-04" });
  renderWithRouter(<Admin />, { route: "/admin" });
  expect(screen.getByTestId("tab-users")).toBeInTheDocument();
  expect(screen.getByTestId("tab-stats")).toBeInTheDocument();
  expect(screen.getByTestId("tab-logs")).toBeInTheDocument();
  const toggle = await screen.findByTestId("toggle-ocr-2");
  await user.click(toggle);
  expect(api.adminPatchUser).toHaveBeenCalledWith(2, { ocr_enabled: true });
});

it("stats tab renders cost column", async () => {
  vi.mocked(api.me).mockResolvedValue({ id: 1, role: "admin", ocr_enabled: true });
  vi.mocked(api.adminListUsers).mockResolvedValue({ items: [], total: 0 });
  vi.mocked(api.adminStats).mockResolvedValue({ days: [{ date: "2026-10-04", users_registered: 1, jobs_submitted: 2, jobs_done: 1, jobs_failed: 1, page_views: 9, gpu_seconds: 10800, estimated_cost_usd: 7.5 }] });
  renderWithRouter(<Admin />);
  await user.click(screen.getByTestId("tab-stats"));
  expect(await screen.findByText("Chi phí ước tính")).toBeInTheDocument();
  expect(screen.getByText("7.5")).toBeInTheDocument();
});

it("logs tab filters by ip", async () => {
  vi.mocked(api.me).mockResolvedValue({ id: 1, role: "admin", ocr_enabled: true });
  vi.mocked(api.adminListUsers).mockResolvedValue({ items: [], total: 0 });
  vi.mocked(api.adminLogs).mockResolvedValue({ items: [{ id: 1, ts: "2026-10-04T00:00:00Z", method: "POST", path: "/api/auth/login", status: 401, user_id: null, ip: "10.0.0.1", ua: "x" }] });
  vi.mocked(api.adminLogsTail).mockResolvedValue({ lines: ["log line"] });
  renderWithRouter(<Admin />);
  await user.click(screen.getByTestId("tab-logs"));
  await user.type(screen.getByTestId("input-log-ip"), "10.0.0.1");
  await user.click(screen.getByTestId("btn-logs-refresh"));
  await waitFor(() => expect(api.adminLogs).toHaveBeenCalledWith(expect.objectContaining({ ip: "10.0.0.1" })));
});
```

- [ ] **Step 2: Run → FAIL** → **Step 3: Implement** per Interfaces; gate route on `me.role === "admin"` else redirect `/`.
- [ ] **Step 4: Run → PASS** → **Step 5: Commit** `feat(web): admin tabs`

---

**Plan F done when:** `cd web && npm test` fully green; `npm run build` succeeds.
