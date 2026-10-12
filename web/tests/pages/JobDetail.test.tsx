import type { Query } from "@tanstack/react-query";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement } from "react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import type { Mock } from "vitest";
import * as mammoth from "mammoth";
import { api, ApiError } from "../../src/api/client";
import { clearJobBlobCache } from "../../src/lib/blobCache";
import { toast } from "sonner";
import type { Job, ResultBody } from "../../src/api/types";
import JobDetail from "../../src/pages/JobDetail";

vi.mock("../../src/api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../src/api/client")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      getJob: vi.fn(),
      retryJob: vi.fn(),
      retryLayout: vi.fn(),
      cancelJob: vi.fn(),
      deleteJob: vi.fn(),
      exportJob: vi.fn(),
      downloadExport: vi.fn(),
      listVersions: vi.fn(),
      restoreVersion: vi.fn(),
      getExtraction: vi.fn(),
      getSuggestions: vi.fn(),
      downloadJobFile: vi.fn(),
      getDocxHtml: vi.fn(),
    },
  };
});

// Plan M: unified editor tự gọi mammoth (word mode) — mock để không parse blob thật.
vi.mock("mammoth", () => ({
  convertToHtml: vi.fn(),
}));

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

/**
 * Polling assertion choice (documented): spy on the useQuery options — capture
 * the refetchInterval callback the component actually registers, then evaluate
 * it against the mocked job. Real assertion on real interval logic, no fake timers.
 */
const mockNavigate = vi.hoisted(() => vi.fn());

// JD2: btn-edit-doc = inline edit, KHÔNG navigate — mockNavigate chỉ để assert not-called.
vi.mock("react-router-dom", async (importOriginal) => {
  const actual = await importOriginal<typeof import("react-router-dom")>();
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  };
});

let capturedInterval: ((q: Query<Job>) => number | false) | undefined;

/** JD2: scrollIntoView không có trong jsdom — mock để assert scroll+focus. */
type ScrollIntoView = (arg?: boolean | ScrollIntoViewOptions) => void;
let scrollIntoViewMock: Mock<ScrollIntoView>;

vi.mock("@tanstack/react-query", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@tanstack/react-query")>();
  return {
    ...actual,
    useQuery: ((opts: never) => {
      const o = opts as {
        queryKey?: unknown[];
        refetchInterval?: (q: Query<Job>) => number | false;
      };
      if (o?.queryKey?.[0] === "job" && typeof o.refetchInterval === "function") {
        capturedInterval = o.refetchInterval;
      }
      return (actual.useQuery as (o: never) => unknown)(opts);
    }) as typeof actual.useQuery,
  };
});

let lastJob: Job | undefined;
let lastQueryClient: QueryClient | undefined;

/** Brief's pollSpyCalled(): evaluates captured refetchInterval on last mocked job. */
function pollSpyCalled(): boolean {
  expect(capturedInterval).toBeDefined();
  return Boolean(capturedInterval!({ state: { data: lastJob } } as Query<Job>));
}

function mockJob(job: Job) {
  lastJob = job;
  vi.mocked(api.getJob).mockResolvedValue(job);
}

const EMPTY_RESULT: ResultBody = {
  model_version: "test",
  gpu_seconds: 0,
  warnings: [],
  markdown: "",
  pages: [],
  edited_markdown: null,
};

/** MemoryRouter route /jobs/5 (R30); provider wraps like the App shell. */
function renderWithRouter(ui: ReactElement, { route = "/" } = {}) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  lastQueryClient = queryClient;
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[route]}>
        <Routes>
          <Route path="/jobs/:id" element={ui} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  // WS-UI: blob cache module-level share giữa test — dọn để mock mới có hiệu lực.
  clearJobBlobCache();
  vi.mocked(api.getExtraction).mockResolvedValue({ text: "", text_version: 0 });
  vi.mocked(api.getSuggestions).mockResolvedValue([]);
  vi.mocked(api.downloadJobFile).mockResolvedValue(new Blob(["png"]));
  vi.mocked(api.getDocxHtml).mockResolvedValue(null);
  // Plan M: mode md auto-flow chạy mỗi lần ResultPanel mount (mock, không đụng server).
  vi.mocked(api.exportJob).mockResolvedValue({ url: "" });
  vi.mocked(api.downloadExport).mockResolvedValue(new Blob(["# Artifact"]));
  vi.mocked(mammoth.convertToHtml).mockResolvedValue({
    value: "<p>Chào</p>",
    messages: [],
  } as never);
  capturedInterval = undefined;
  lastJob = undefined;
  scrollIntoViewMock = vi.fn<ScrollIntoView>();
  Element.prototype.scrollIntoView = scrollIntoViewMock;
});

it("queued shows waiting message and polls", async () => {
  mockJob({ id: 5, status: "queued", page_count: 1, result: null } as Job);
  renderWithRouter(<JobDetail />, { route: "/jobs/5" });
  // Task 2: header badge duplicates status text — scope to InfoPanel's status badge.
  expect(await screen.findByTestId("status-5")).toHaveTextContent("Đang lập lịch");
  // Back link points at the /jobs list route (root is public landing now).
  expect(screen.getByTestId("link-back-jobs")).toHaveAttribute("href", "/jobs");
  expect(pollSpyCalled()).toBe(true);
});

// Plan job-phases: extracting + rendering are pending — poll keeps running.
it.each(["extracting", "rendering"] as const)("%s keeps polling", async (status) => {
  mockJob({ id: 5, status, page_count: 1, result: null } as Job);
  renderWithRouter(<JobDetail />, { route: "/jobs/5" });
  await screen.findByTestId("panel-info");
  expect(pollSpyCalled()).toBe(true);
});

it("failed shows retry button and calls api", async () => {
  mockJob({ id: 5, status: "failed", error: "boom", result: null } as Job);
  vi.mocked(api.retryJob).mockResolvedValue(undefined);
  renderWithRouter(<JobDetail />, { route: "/jobs/5" });
  expect(await screen.findByTestId("status-5")).toHaveTextContent("Xử lý thất bại");
  const invalidate = vi.spyOn(lastQueryClient!, "invalidateQueries");
  const user = userEvent.setup();
  await user.click(screen.getByTestId("btn-retry-job"));
  expect(api.retryJob).toHaveBeenCalledWith("5");
  // R59: retry success toasts plan copy + refetches detail + list.
  await waitFor(() =>
    expect(toast.success).toHaveBeenCalledWith("Đã lên lịch chạy lại"),
  );
  expect(invalidate).toHaveBeenCalledWith({ queryKey: ["job", "5"] });
  expect(invalidate).toHaveBeenCalledWith({ queryKey: ["jobs"] });
});

it("retry failure shows retry-error with server detail", async () => {
  mockJob({ id: 5, status: "failed", error: "boom", result: null } as Job);
  vi.mocked(api.retryJob).mockRejectedValue(new ApiError("Forbidden."));
  renderWithRouter(<JobDetail />, { route: "/jobs/5" });
  expect(await screen.findByTestId("status-5")).toHaveTextContent("Xử lý thất bại");
  const user = userEvent.setup();
  await user.click(screen.getByTestId("btn-retry-job"));
  expect(await screen.findByTestId("retry-error")).toHaveTextContent("Forbidden.");
});

// Hủy job: pending (queued|extracting|rendering) hiện btn-cancel-job.
it.each(["queued", "extracting", "rendering"] as const)(
  "%s shows cancel button and calls api.cancelJob",
  async (status) => {
    mockJob({ id: 5, status, error: null, result: null } as Job);
    vi.mocked(api.cancelJob).mockResolvedValue(undefined);
    renderWithRouter(<JobDetail />, { route: "/jobs/5" });
    expect(await screen.findByTestId("status-5")).toBeDefined();
    const invalidate = vi.spyOn(lastQueryClient!, "invalidateQueries");
    const user = userEvent.setup();
    await user.click(screen.getByTestId("btn-cancel-job"));
    expect(api.cancelJob).toHaveBeenCalledWith("5");
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("Đã hủy job"));
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["job", "5"] });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["jobs"] });
  },
);

it.each(["done", "failed", "cancelled"] as const)(
  "%s hides cancel button",
  async (status) => {
    mockJob({ id: 5, status, error: null, result: null } as Job);
    renderWithRouter(<JobDetail />, { route: "/jobs/5" });
    expect(await screen.findByTestId("status-5")).toBeDefined();
    expect(screen.queryByTestId("btn-cancel-job")).not.toBeInTheDocument();
  },
);

it("done without layout_cache shows retry-layout button and calls api", async () => {
  mockJob({ ...DONE_JOB, layout_cache: { md: false, docx: false } });
  vi.mocked(api.retryLayout).mockResolvedValue({ md: true, docx: true });
  renderWithRouter(<JobDetail />, { route: "/jobs/5" });
  const user = userEvent.setup();
  await user.click(await screen.findByTestId("btn-retry-layout"));
  expect(api.retryLayout).toHaveBeenCalledWith("5");
});

it("done with layout_cache hides retry-layout button", async () => {
  mockJob({ ...DONE_JOB, layout_cache: { md: true, docx: true } });
  renderWithRouter(<JobDetail />, { route: "/jobs/5" });
  await screen.findByTestId("layout-preview");
  expect(screen.queryByTestId("btn-retry-layout")).not.toBeInTheDocument();
});

it("done stops polling", async () => {
  mockJob({ id: 5, status: "done", result: EMPTY_RESULT } as Job);
  renderWithRouter(<JobDetail />, { route: "/jobs/5" });
  expect(await screen.findByTestId("layout-preview")).toBeInTheDocument();
  expect(pollSpyCalled()).toBe(false);
});

/** Task 2: 3-panel layout from mocked job (R51 testids preserved). */
const DONE_JOB: Job = {
  id: 5,
  status: "done",
  file_type: "pdf",
  page_count: 2,
  error: null,
  created_at: "2026-01-02T03:04:05Z",
  started_at: null,
  finished_at: null,
  result: EMPTY_RESULT,
  text_version: 1,
};

it("done renders 3 panels: original + result + info with status badge", async () => {
  mockJob(DONE_JOB);
  renderWithRouter(<JobDetail />, { route: "/jobs/5" });
  expect(await screen.findByTestId("panel-original")).toBeInTheDocument();
  expect(screen.getByTestId("panel-result")).toBeInTheDocument();
  expect(screen.getByTestId("panel-info")).toBeInTheDocument();
  expect(screen.getByTestId("status-5")).toHaveTextContent("Hoàn tất");
});

/** WS-UI item 13: Stats line DƯỚI preview (result-stats bật lại); job-meta/output badge vẫn gỡ. */
it("done: no job-meta/output badge, stats line + ExportBar render", async () => {
  mockJob({ ...DONE_JOB, output_format: "docx" });
  renderWithRouter(<JobDetail />, { route: "/jobs/5" });
  await screen.findByTestId("layout-preview");
  expect(screen.queryByTestId("job-meta")).not.toBeInTheDocument();
  expect(screen.queryByTestId("job-output-format")).not.toBeInTheDocument();
  expect(screen.getByTestId("result-stats")).toBeInTheDocument();
  expect(screen.getByTestId("export-bar")).toBeInTheDocument();
  expect(screen.getByTestId("export-more")).toBeInTheDocument();
  expect(screen.getByTestId("export-layout-more")).toBeInTheDocument();
});

it("not done shows status-only panels, ResultPanel hidden until done", async () => {
  mockJob({ ...DONE_JOB, status: "queued", result: null });
  renderWithRouter(<JobDetail />, { route: "/jobs/5" });
  expect(await screen.findByTestId("panel-original")).toBeInTheDocument();
  expect(screen.getByTestId("panel-info")).toBeInTheDocument();
  expect(screen.queryByTestId("panel-result")).toBeNull();
  expect(screen.getByTestId("status-5")).toHaveTextContent("Đang lập lịch");
  // JD2: chưa có markdown → Edit (inline) vô hiệu, không có dead click
  expect(screen.getByTestId("btn-edit-doc")).toBeDisabled();
  expect(screen.queryByTestId("detail-reading")).toBeNull();
});

/** Plan JD: header 1-row structure (adjust-only queries, R51) + inline Edit. */
it("header: back link, title, badge, actions in one row (adjust-only)", async () => {
  mockJob(DONE_JOB);
  renderWithRouter(<JobDetail />, { route: "/jobs/5" });
  expect(await screen.findByTestId("link-back-jobs")).toHaveAttribute("href", "/jobs");
  // name scope: preview MDEditor inline (M5) cũng render heading từ md artifact
  expect(
    screen.getByRole("heading", { level: 1, name: "Chi tiết công việc #5" }),
  ).toBeInTheDocument();
  // JD2: output badge moved to rail meta; header keeps status badge
  expect(screen.getByTestId("job-header")).toContainElement(
    screen.getByTestId("btn-edit-doc"),
  );
  expect(screen.queryByTestId("btn-retry-job")).not.toBeInTheDocument();
});

/** JD2 amendment: btn-edit-doc = preview ↔ editor trong Section "Layout". */
it("btn-edit-doc toggles editor: preview → editor → preview, no navigation", async () => {
  mockJob(DONE_JOB);
  renderWithRouter(<JobDetail />, { route: "/jobs/5" });
  const user = userEvent.setup();
  const btn = await screen.findByTestId("btn-edit-doc");
  expect(btn).toHaveTextContent("Chỉnh sửa");
  // Default = XEM TRƯỚC read-only (spec WS-UI section Layout).
  expect(screen.getByTestId("layout-preview")).toBeInTheDocument();
  await user.click(btn);
  expect(mockNavigate).not.toHaveBeenCalled();
  expect(btn).toHaveAttribute("aria-pressed", "true");
  expect(btn).toHaveTextContent("Đang sửa");
  const editor = await screen.findByTestId("md-editor");
  expect(editor.querySelector("textarea")).toHaveFocus();
  expect(scrollIntoViewMock).toHaveBeenCalledTimes(1);
  expect(scrollIntoViewMock).toHaveBeenCalledWith({ behavior: "smooth", block: "start" });
  // Toggle lần 2 → quay lại preview (UnifiedEditor unmount).
  await user.click(screen.getByTestId("btn-edit-doc"));
  expect(btn).toHaveAttribute("aria-pressed", "false");
  expect(screen.queryByTestId("md-editor")).not.toBeInTheDocument();
  expect(screen.getByTestId("layout-preview")).toBeInTheDocument();
  expect(mockNavigate).not.toHaveBeenCalled();
});

/** WS-UI cấu trúc 2 section: Văn bản 7/5 (auto original, KHÔNG toggle) + Layout 7/5. */
it("renders section-text 7/5 with auto original + no toggle button", async () => {
  mockJob(DONE_JOB);
  renderWithRouter(<JobDetail />, { route: "/jobs/5" });
  const section = await screen.findByTestId("section-text");
  const grid = within(section).getByTestId("detail-grid");
  expect(grid.className).toContain("lg:grid-cols-12");
  expect(grid.querySelector(".lg\\:col-span-7")).not.toBeNull();
  expect(grid.querySelector(".lg\\:col-span-5")).not.toBeNull();
  // Mobile stack: mọi grid-cols đều gắn tiền tố lg: (không cột nào ở base).
  const colClasses = grid.className.split(/\s+/).filter((c) => c.includes("grid-cols"));
  expect(colClasses.length).toBeGreaterThan(0);
  expect(colClasses.every((c) => c.startsWith("lg:"))).toBe(true);
  // Ảnh gốc auto-fetch, không còn toggle "Bản gốc"/"Hiện file".
  expect(within(section).getByTestId("panel-original")).toBeInTheDocument();
  expect(screen.queryByTestId("btn-toggle-original")).not.toBeInTheDocument();
  expect(screen.queryByTestId("toggle-original")).not.toBeInTheDocument();
  // DONE_JOB là pdf → sandboxed frame (không phải img).
  expect(await within(section).findByTestId("original-pdf-frame")).toBeInTheDocument();
});

it("renders section-layout: preview + export below preview + original + info", async () => {
  mockJob(DONE_JOB);
  renderWithRouter(<JobDetail />, { route: "/jobs/5" });
  const section = await screen.findByTestId("section-layout");
  const layoutGrid = section.querySelector(".lg\\:grid-cols-12");
  expect(layoutGrid).not.toBeNull();
  expect(layoutGrid?.querySelector(".lg\\:col-span-7")).not.toBeNull();
  expect(layoutGrid?.querySelector(".lg\\:col-span-5")).not.toBeNull();
  // Preview read-only mặc định; ExportBar DƯỚI preview cột trái; ảnh gốc + info cột phải.
  expect(screen.getByTestId("layout-preview")).toBeInTheDocument();
  expect(screen.getByTestId("export-bar")).toBeInTheDocument();
  expect(screen.getByTestId("panel-original-layout")).toBeInTheDocument();
  expect(screen.getByTestId("panel-info")).toBeInTheDocument();
  // Blob cache dùng chung: 1 fetch cho cả 2 section (2 panel_original render frame).
  await waitFor(() =>
    expect(screen.getAllByTestId("original-pdf-frame").length).toBe(2),
  );
  expect(api.downloadJobFile).toHaveBeenCalledTimes(1);
});

// P1-2 review r1: extract_only không gen layout → ẩn Section Layout + export-bar.
it("extract_only done hides section-layout and export groups", async () => {
  mockJob({ ...DONE_JOB, mode: "extract_only" });
  renderWithRouter(<JobDetail />, { route: "/jobs/5" });
  await screen.findByTestId("panel-result");
  expect(screen.queryByTestId("section-layout")).not.toBeInTheDocument();
  expect(screen.queryByTestId("export-bar")).not.toBeInTheDocument();
});

/** Lane B Task 1: 2 section cuộn dọc (h2 + spacing token) — KHÔNG còn tab Extraction/Layout. */
it("2 section h2 'Văn bản' + 'Layout', không còn tab buttons", async () => {
  mockJob(DONE_JOB);
  renderWithRouter(<JobDetail />, { route: "/jobs/5" });
  await screen.findByTestId("section-text");
  await screen.findByTestId("section-layout");
  expect(screen.getByRole("heading", { level: 2, name: "Văn bản" })).toBeInTheDocument();
  expect(screen.getByRole("heading", { level: 2, name: "Layout" })).toBeInTheDocument();
  expect(screen.queryAllByRole("tab")).toHaveLength(0);
  expect(screen.queryByRole("tablist")).toBeNull();
});

/** JD2: header static trên mobile (3-4 dòng che viewport) — sticky ≥lg, bám dưới AppNav h-16. */
it("header sticky chỉ ≥lg (mobile static) với blurred surface bg", async () => {
  mockJob(DONE_JOB);
  const { container } = renderWithRouter(<JobDetail />, { route: "/jobs/5" });
  await screen.findByTestId("job-header");
  const header = container.querySelector('[data-testid="job-header"]');
  expect(header).not.toBeNull();
  const cls = (header as HTMLElement).className;
  expect(cls).toContain("lg:sticky");
  expect(cls).toContain("lg:top-16");
  expect(cls).not.toMatch(/(^|\s)sticky/);
  expect(cls).toContain("backdrop-blur");
});

it("loading shows skeleton instead of blank page", () => {
  vi.mocked(api.getJob).mockReturnValue(new Promise(() => {}) as never);
  renderWithRouter(<JobDetail />, { route: "/jobs/5" });
  expect(screen.getByTestId("job-loading")).toBeInTheDocument();
  expect(screen.getAllByTestId("skeleton").length).toBeGreaterThan(0);
});

// Phase 2 Task 4 (Sub-system B): link sang trang trích xuất (done jobs only).
it("done renders link to extraction page", async () => {
  mockJob(DONE_JOB);
  renderWithRouter(<JobDetail />, { route: "/jobs/5" });
  await screen.findByTestId("panel-result");
  expect(screen.getByTestId("link-extraction")).toHaveAttribute(
    "href",
    "/jobs/5/extraction",
  );
});

it("pending job hides extraction link", async () => {
  mockJob({ id: 5, status: "queued", page_count: 1, result: null } as Job);
  renderWithRouter(<JobDetail />, { route: "/jobs/5" });
  await screen.findByTestId("job-header");
  expect(screen.queryByTestId("link-extraction")).not.toBeInTheDocument();
});

/** P0-D: stale_layouts > 0 → badge "Cần đồng bộ" + resync (contract GET /api/jobs/{id}). */
it("stale_layouts non-empty: stale-badge shows, resync calls api + toast + invalidate", async () => {
  mockJob({ ...DONE_JOB, stale_layouts: ["md"] });
  vi.mocked(api.retryLayout).mockResolvedValue({ md: true, docx: true });
  renderWithRouter(<JobDetail />, { route: "/jobs/5" });
  expect(await screen.findByTestId("stale-badge")).toHaveTextContent("Cần đồng bộ");
  const invalidate = vi.spyOn(lastQueryClient!, "invalidateQueries");
  const user = userEvent.setup();
  await user.click(screen.getByTestId("btn-resync-layout"));
  expect(api.retryLayout).toHaveBeenCalledWith("5");
  await waitFor(() => expect(toast.success).toHaveBeenCalledWith("Đã đồng bộ layout"));
  expect(invalidate).toHaveBeenCalledWith({ queryKey: ["job", "5"] });
});

// Hidden case: stale_layouts rỗng hoặc vắng mặt → KHÔNG render badge/nút.
it.each<[string, Job]>([
  ["missing", DONE_JOB],
  ["empty", { ...DONE_JOB, stale_layouts: [] }],
])("stale_layouts %s hides stale-badge and resync button", async (_label, job) => {
  mockJob(job);
  renderWithRouter(<JobDetail />, { route: "/jobs/5" });
  await screen.findByTestId("job-header");
  expect(screen.queryByTestId("stale-badge")).not.toBeInTheDocument();
  expect(screen.queryByTestId("btn-resync-layout")).not.toBeInTheDocument();
});

/** P0-C: lịch sử version — list + badge "Hiện tại" (version == job.text_version). */
const VERSIONS = [
  {
    id: 11,
    kind: "text",
    version: 3,
    based_on_text_version: 3,
    detached: false,
    created_at: "2026-01-02T03:04:05Z",
  },
  {
    id: 10,
    kind: "md-layout",
    version: 2,
    based_on_text_version: 2,
    detached: false,
    created_at: "2026-01-01T00:00:00Z",
  },
];

it("btn-version-history lists versions: v{version} + kind + time + Hiện tại badge", async () => {
  mockJob({ ...DONE_JOB, text_version: 3 });
  vi.mocked(api.listVersions).mockResolvedValue({ items: VERSIONS });
  renderWithRouter(<JobDetail />, { route: "/jobs/5" });
  const user = userEvent.setup();
  await user.click(await screen.findByTestId("btn-version-history"));
  expect(api.listVersions).toHaveBeenCalledWith("5");
  expect(await screen.findByTestId("version-history")).toBeInTheDocument();
  const current = screen.getByTestId("version-row-text-3");
  expect(current).toHaveTextContent("v3");
  expect(current).toHaveTextContent("text");
  expect(within(current).getByText("Hiện tại")).toBeInTheDocument();
  const old = screen.getByTestId("version-row-md-layout-2");
  expect(old).toHaveTextContent("v2");
  expect(old).toHaveTextContent("md-layout");
  // P2: max trong kind cũng "Hiện tại" (md-layout v2 là current của kind md-layout).
  expect(within(old).getByText("Hiện tại")).toBeInTheDocument();
});

it("btn-version-restore-{kind}-{version} calls api.restoreVersion + toast + invalidate job & versions", async () => {
  mockJob({ ...DONE_JOB, text_version: 3 });
  vi.mocked(api.listVersions).mockResolvedValue({ items: VERSIONS });
  vi.mocked(api.restoreVersion).mockResolvedValue(undefined);
  renderWithRouter(<JobDetail />, { route: "/jobs/5" });
  const invalidate = vi.spyOn(lastQueryClient!, "invalidateQueries");
  const user = userEvent.setup();
  await user.click(await screen.findByTestId("btn-version-history"));
  await user.click(await screen.findByTestId("btn-version-restore-md-layout-2"));
  // vid = DocumentVersion.id (server: session.get(DocumentVersion, vid)).
  expect(api.restoreVersion).toHaveBeenCalledWith("5", 10);
  await waitFor(() =>
    expect(toast.success).toHaveBeenCalledWith("Đã khôi phục bản cũ"),
  );
  expect(invalidate).toHaveBeenCalledWith({ queryKey: ["job", "5"] });
  expect(invalidate).toHaveBeenCalledWith({ queryKey: ["versions", "5"] });
});

/** P0-C red: UNIQUE(job_id,kind,version) → version number restart per kind.
 *  2 kind cùng version number → testid phải khác nhau; mỗi kind badge max version của nó. */
it("versions same number across kinds: unique testids, each kind's max row badges Hiện tại", async () => {
  mockJob({ ...DONE_JOB, text_version: 1 });
  vi.mocked(api.listVersions).mockResolvedValue({
    items: [
      { id: 21, kind: "text", version: 1, based_on_text_version: 1, detached: false, created_at: "2026-01-02T03:04:05Z" },
      { id: 20, kind: "md-layout", version: 1, based_on_text_version: 1, detached: false, created_at: "2026-01-01T00:00:00Z" },
    ],
  });
  renderWithRouter(<JobDetail />, { route: "/jobs/5" });
  await userEvent.setup().click(await screen.findByTestId("btn-version-history"));
  const textRow = await screen.findByTestId("version-row-text-1");
  const mdRow = screen.getByTestId("version-row-md-layout-1");
  expect(within(textRow).getByText("Hiện tại")).toBeInTheDocument();
  expect(within(mdRow).getByText("Hiện tại")).toBeInTheDocument();
  expect(screen.getByTestId("btn-version-restore-text-1")).toBeInTheDocument();
  expect(screen.getByTestId("btn-version-restore-md-layout-1")).toBeInTheDocument();
});

/** P2: server snapshot kind "md" khi region edit → current md version phải được mark.
 *  Rule: "Hiện tại" = version == MAX trong cùng kind (mọi kind, kể cả md). */
it("md kind: only max md version row badges Hiện tại (region-edit snapshot)", async () => {
  mockJob({ ...DONE_JOB, text_version: 3 });
  vi.mocked(api.listVersions).mockResolvedValue({
    items: [
      { id: 31, kind: "md", version: 2, based_on_text_version: 3, detached: false, created_at: "2026-01-03T00:00:00Z" },
      { id: 30, kind: "md", version: 1, based_on_text_version: 2, detached: false, created_at: "2026-01-01T00:00:00Z" },
      { id: 29, kind: "text", version: 3, based_on_text_version: 3, detached: false, created_at: "2026-01-02T03:04:05Z" },
    ],
  });
  renderWithRouter(<JobDetail />, { route: "/jobs/5" });
  await userEvent.setup().click(await screen.findByTestId("btn-version-history"));
  expect(within(await screen.findByTestId("version-row-md-2")).getByText("Hiện tại")).toBeInTheDocument();
  expect(within(screen.getByTestId("version-row-md-1")).queryByText("Hiện tại")).not.toBeInTheDocument();
  expect(within(screen.getByTestId("version-row-text-3")).getByText("Hiện tại")).toBeInTheDocument();
});

/** P1: panel không nuốt loading/error — skeleton lúc fetch, role=alert khi fail. */
it("versions pending shows skeleton row inside history panel", async () => {
  mockJob(DONE_JOB);
  vi.mocked(api.listVersions).mockReturnValue(new Promise(() => {}) as never);
  renderWithRouter(<JobDetail />, { route: "/jobs/5" });
  await userEvent.setup().click(await screen.findByTestId("btn-version-history"));
  const panel = await screen.findByTestId("version-history");
  expect(within(panel).getByTestId("versions-skeleton")).toBeInTheDocument();
});

it("versions fetch failure shows role=alert error line", async () => {
  mockJob(DONE_JOB);
  vi.mocked(api.listVersions).mockRejectedValue(new ApiError("boom"));
  renderWithRouter(<JobDetail />, { route: "/jobs/5" });
  await userEvent.setup().click(await screen.findByTestId("btn-version-history"));
  const panel = await screen.findByTestId("version-history");
  expect(within(panel).getByRole("alert")).toHaveTextContent("Không tải được lịch sử");
});

/** P2 a11y: Escape đóng panel (button đã có aria-expanded + aria-controls. */
it("Escape key closes history panel", async () => {
  mockJob(DONE_JOB);
  vi.mocked(api.listVersions).mockResolvedValue({ items: [] });
  renderWithRouter(<JobDetail />, { route: "/jobs/5" });
  await userEvent.setup().click(await screen.findByTestId("btn-version-history"));
  const panel = await screen.findByTestId("version-history");
  expect(panel).toHaveAttribute("id", "version-history");
  expect(screen.getByTestId("btn-version-history")).toHaveAttribute("aria-controls", "version-history");
  expect(screen.getByTestId("btn-version-history")).toHaveAttribute("aria-expanded", "true");
  fireEvent.keyDown(panel, { key: "Escape" });
  expect(screen.queryByTestId("version-history")).not.toBeInTheDocument();
  expect(screen.getByTestId("btn-version-history")).toHaveAttribute("aria-expanded", "false");
});

// Spec #1: JobDetail nút "Xóa job" → confirm → deleteJob + navigate về list.
it("delete job: confirm → deleteJob + invalidate + navigate /jobs", async () => {
  mockJob({ ...DONE_JOB });
  vi.mocked(api.deleteJob).mockResolvedValue(undefined);
  renderWithRouter(<JobDetail />, { route: "/jobs/5" });
  await screen.findByTestId("job-header");
  await userEvent.click(screen.getByTestId("btn-delete-job"));
  expect(screen.getByTestId("confirm-dialog")).toBeInTheDocument();
  const invalidate = vi.spyOn(lastQueryClient!, "invalidateQueries");
  await userEvent.click(screen.getByTestId("confirm-accept"));
  expect(api.deleteJob).toHaveBeenCalledWith("5");
  expect(invalidate).toHaveBeenCalledWith({ queryKey: ["jobs"] });
  await waitFor(() => expect(mockNavigate).toHaveBeenCalledWith("/jobs"));
});

it("delete job: hủy → không gọi deleteJob", async () => {
  mockJob({ ...DONE_JOB });
  renderWithRouter(<JobDetail />, { route: "/jobs/5" });
  await screen.findByTestId("job-header");
  await userEvent.click(screen.getByTestId("btn-delete-job"));
  await userEvent.click(screen.getByTestId("confirm-cancel"));
  expect(screen.queryByTestId("confirm-dialog")).not.toBeInTheDocument();
  expect(api.deleteJob).not.toHaveBeenCalled();
});
