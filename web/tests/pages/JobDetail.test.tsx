import type { Query } from "@tanstack/react-query";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement } from "react";
import { MemoryRouter, Route, Routes, Link, RouterProvider, createMemoryRouter } from "react-router-dom";
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
  // Lane I Task 2: InfoPanel = collapsible default closed → mở trước.
  await userEvent.click(await screen.findByTestId("btn-toggle-info"));
  expect(await screen.findByTestId("status-5")).toHaveTextContent("Queued");
  // Back link points at the /jobs list route (root is public landing now).
  expect(screen.getByTestId("link-back-jobs")).toHaveAttribute("href", "/jobs");
  expect(pollSpyCalled()).toBe(true);
});

// Plan job-phases: extracting + rendering are pending — poll keeps running.
it.each(["extracting", "rendering"] as const)("%s keeps polling", async (status) => {
  mockJob({ id: 5, status, page_count: 1, result: null } as Job);
  renderWithRouter(<JobDetail />, { route: "/jobs/5" });
  await screen.findByTestId("job-header");
  expect(pollSpyCalled()).toBe(true);
});

it("failed shows retry button and calls api", async () => {
  mockJob({ id: 5, status: "failed", error: "boom", result: null } as Job);
  vi.mocked(api.retryJob).mockResolvedValue(undefined);
  renderWithRouter(<JobDetail />, { route: "/jobs/5" });
  await userEvent.click(await screen.findByTestId("btn-toggle-info"));
  expect(await screen.findByTestId("status-5")).toHaveTextContent("Processing failed");
  const invalidate = vi.spyOn(lastQueryClient!, "invalidateQueries");
  const user = userEvent.setup();
  await user.click(screen.getByTestId("btn-retry-job"));
  expect(api.retryJob).toHaveBeenCalledWith("5");
  // R59: retry success toasts plan copy + refetches detail + list.
  await waitFor(() =>
    expect(toast.success).toHaveBeenCalledWith("Retry scheduled"),
  );
  expect(invalidate).toHaveBeenCalledWith({ queryKey: ["job", "5"] });
  expect(invalidate).toHaveBeenCalledWith({ queryKey: ["jobs"] });
});

it("retry failure shows retry-error with server detail", async () => {
  mockJob({ id: 5, status: "failed", error: "boom", result: null } as Job);
  vi.mocked(api.retryJob).mockRejectedValue(new ApiError("Forbidden."));
  renderWithRouter(<JobDetail />, { route: "/jobs/5" });
  await userEvent.click(await screen.findByTestId("btn-toggle-info"));
  expect(await screen.findByTestId("status-5")).toHaveTextContent("Processing failed");
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
    await screen.findByTestId("job-header");
    const invalidate = vi.spyOn(lastQueryClient!, "invalidateQueries");
    const user = userEvent.setup();
    await user.click(screen.getByTestId("btn-cancel-job"));
    expect(api.cancelJob).toHaveBeenCalledWith("5");
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("Job cancelled"));
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["job", "5"] });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["jobs"] });
  },
);

it.each(["done", "failed", "cancelled"] as const)(
  "%s hides cancel button",
  async (status) => {
    mockJob({ id: 5, status, error: null, result: null } as Job);
    renderWithRouter(<JobDetail />, { route: "/jobs/5" });
    await screen.findByTestId("job-header");
    expect(screen.queryByTestId("btn-cancel-job")).not.toBeInTheDocument();
  },
);

it("done without layout_cache shows retry-layout button and calls api", async () => {
  mockJob({ ...DONE_JOB, layout_cache: { md: false, docx: false } });
  vi.mocked(api.retryLayout).mockResolvedValue({ md: true, docx: true });
  renderWithRouter(<JobDetail />, { route: "/jobs/5" });
  const user = userEvent.setup();
  await user.click(await screen.findByTestId("btn-retry-layout"));
  await user.click(screen.getByTestId("confirm-accept"));
  expect(api.retryLayout).toHaveBeenCalledWith("5");
});

// Lane I Task 6: "Vẽ lại layout" luôn hiện khi done (không chỉ khi cache miss).
it("done with layout_cache still shows retry-layout button", async () => {
  mockJob({ ...DONE_JOB, layout_cache: { md: true, docx: true } });
  renderWithRouter(<JobDetail />, { route: "/jobs/5" });
  await screen.findByTestId("layout-preview");
  expect(screen.getByTestId("btn-retry-layout")).toBeInTheDocument();
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
  const user = userEvent.setup();
  // Lane I Task 2: File gốc + Thông tin = collapsible (default closed) → mở trước.
  await user.click(await screen.findByTestId("btn-toggle-original"));
  await user.click(screen.getByTestId("btn-toggle-info"));
  expect(await screen.findByTestId("panel-original")).toBeInTheDocument();
  expect(screen.getByTestId("panel-result")).toBeInTheDocument();
  expect(screen.getByTestId("panel-info")).toBeInTheDocument();
  expect(screen.getByTestId("status-5")).toHaveTextContent("Done");
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
  expect(screen.getByTestId("export-layout-more")).toBeInTheDocument();
  expect(screen.queryByTestId("export-more")).not.toBeInTheDocument();
  expect(screen.getByTestId("btn-download")).toBeInTheDocument();
});

it("not done shows status-only panels, ResultPanel hidden until done", async () => {
  mockJob({ ...DONE_JOB, status: "queued", result: null });
  renderWithRouter(<JobDetail />, { route: "/jobs/5" });
  const user = userEvent.setup();
  await user.click(await screen.findByTestId("btn-toggle-original"));
  await user.click(screen.getByTestId("btn-toggle-info"));
  expect(await screen.findByTestId("panel-original")).toBeInTheDocument();
  expect(screen.getByTestId("panel-info")).toBeInTheDocument();
  expect(screen.queryByTestId("panel-result")).toBeNull();
  expect(screen.getByTestId("status-5")).toHaveTextContent("Queued");
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
    screen.getByRole("heading", { level: 1, name: "Job detail #5" }),
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
  expect(btn).toHaveTextContent("Edit");
  // Default = XEM TRƯỚC read-only (spec WS-UI section Layout).
  expect(screen.getByTestId("layout-preview")).toBeInTheDocument();
  await user.click(btn);
  expect(mockNavigate).not.toHaveBeenCalled();
  expect(btn).toHaveAttribute("aria-pressed", "true");
  expect(btn).toHaveTextContent("Editing");
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

/** Lane I Task 5: header "Tải xuống" dropdown — 4 định dạng text (không còn download rải dưới). */
it("header download dropdown: 4 text formats call exportJob + open url", async () => {
  mockJob(DONE_JOB);
  vi.mocked(api.exportJob).mockResolvedValue({ url: "https://r2/exports/5/docx" });
  const w = { location: "about:blank" };
  const openSpy = vi.fn().mockReturnValue(w);
  vi.stubGlobal("open", openSpy);
  renderWithRouter(<JobDetail />, { route: "/jobs/5" });
  const user = userEvent.setup();
  const btn = await screen.findByTestId("btn-download");
  expect(btn).toHaveAttribute("aria-expanded", "false");
  await user.click(btn);
  expect(btn).toHaveAttribute("aria-expanded", "true");
  const list = screen.getByTestId("download-formats");
  for (const fmt of ["md", "html", "docx", "pdf"]) {
    expect(within(list).getByTestId(`export-${fmt}`)).toBeInTheDocument();
  }
  await user.click(within(list).getByTestId("export-docx"));
  expect(api.exportJob).toHaveBeenCalledWith("5", "docx");
  await waitFor(() => expect(w.location).toBe("https://r2/exports/5/docx"));
});
/** U7: xóa TOÀN BỘ switch MD/Word — header fmt switch + preview toggle vắng trong DOM. */
it("U7: no fmt-md-layout/fmt-docx-layout/preview-mode-md/preview-mode-word in DOM; fmt fixed = output_format", async () => {
  mockJob({ ...DONE_JOB, output_format: "docx" });
  renderWithRouter(<JobDetail />, { route: "/jobs/5" });
  await screen.findByTestId("layout-preview");
  expect(screen.queryByTestId("fmt-md-layout")).not.toBeInTheDocument();
  expect(screen.queryByTestId("fmt-docx-layout")).not.toBeInTheDocument();
  expect(screen.queryByTestId("preview-mode-md")).not.toBeInTheDocument();
  expect(screen.queryByTestId("preview-mode-word")).not.toBeInTheDocument();
  // fmt fixed init job.output_format=docx → word mode ngay từ đầu (không switch).
  expect(await screen.findByTestId("preview-word")).toBeInTheDocument();
});

/**
 * U1 P0: đổi :id KHÔNG remount → state cache giữ html job cũ (Lưu layout PUT nhầm html).
 * Repro: cache sẵn cả 2 job → navigate có data NGAY, không skeleton → state sót.
 */
it("U1 P0: navigate A→B → getJob id=2, preview shows B (không html A), history panel reset", async () => {
  const jobA = { ...DONE_JOB, id: 1 };
  const jobB = { ...DONE_JOB, id: 2 };
  vi.mocked(api.getJob).mockImplementation((jid) =>
    Promise.resolve(jid === "2" ? jobB : jobA),
  );
  vi.mocked(api.listVersions).mockResolvedValue({ items: [] });
  const blobs = [new Blob(["# JOB-A"]), new Blob(["# JOB-B"])];
  let dl = 0;
  vi.mocked(api.downloadExport).mockImplementation(() =>
    Promise.resolve(blobs[Math.min(dl++, blobs.length - 1)]),
  );
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  queryClient.setQueryData(["job", "1"], jobA);
  queryClient.setQueryData(["job", "2"], jobB);
  const router = createMemoryRouter(
    [
      {
        path: "/jobs/:id",
        element: (
          <>
            <Link to="/jobs/2" data-testid="nav-b">go B</Link>
            <JobDetail />
          </>
        ),
      },
    ],
    { initialEntries: ["/jobs/1"] },
  );
  render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  await waitFor(() => expect(screen.getByTestId("preview-md")).toHaveTextContent("JOB-A"));
  // Mở panel lịch sử trên job A — JobDetail states không remount khi đổi id.
  await userEvent.click(screen.getByTestId("btn-version-history"));
  expect(await screen.findByTestId("version-history")).toBeInTheDocument();
  await userEvent.click(screen.getByTestId("nav-b"));
  // Fetch id=2 + mdHtml là của B (không còn html A).
  await waitFor(() =>
    expect(vi.mocked(api.getJob).mock.calls.map((c) => c[0])).toContain("2"),
  );
  await waitFor(() => expect(screen.getByTestId("preview-md")).toHaveTextContent("JOB-B"));
  expect(screen.getByTestId("preview-md")).not.toHaveTextContent("JOB-A");
  // JobDetail reset effect [id] — history panel đóng lại.
  expect(screen.queryByTestId("version-history")).not.toBeInTheDocument();
});

/** Review r1 P1: btn-retry-layout DUY NHẤT — editor retry đổi tên btn-retry-layout-error. */
it("review r1 P1: no duplicate btn-retry-layout (editor retry = btn-retry-layout-error)", async () => {
  mockJob(DONE_JOB);
  vi.mocked(api.exportJob).mockRejectedValue(new ApiError("boom"));
  renderWithRouter(<JobDetail />, { route: "/jobs/5" });
  const user = userEvent.setup();
  await user.click(await screen.findByTestId("btn-edit-doc"));
  await screen.findByTestId("layout-error");
  expect(screen.getByTestId("btn-retry-layout-error")).toBeInTheDocument();
  expect(screen.getAllByTestId("btn-retry-layout")).toHaveLength(1);
});

/** Review r1 P2c: dropdown a11y — aria-haspopup, Escape closes, close-on-select. */
it("review r1 P2c: download dropdown aria-haspopup + Escape closes + closes after select", async () => {
  mockJob(DONE_JOB);
  renderWithRouter(<JobDetail />, { route: "/jobs/5" });
  const user = userEvent.setup();
  const btn = await screen.findByTestId("btn-download");
  expect(btn).toHaveAttribute("aria-haspopup", "true");
  await user.click(btn);
  expect(btn).toHaveAttribute("aria-expanded", "true");
  fireEvent.keyDown(document, { key: "Escape" });
  await waitFor(() => expect(btn).toHaveAttribute("aria-expanded", "false"));
  await user.click(btn);
  await user.click(screen.getByTestId("export-md"));
  await waitFor(() => expect(btn).toHaveAttribute("aria-expanded", "false"));
});

/** Lane I Task 6: "Vẽ lại layout" → confirm → POST retry-layout + loading + toast. */
it("btn-retry-layout: confirm → retryLayout + toast; cancel → no call", async () => {
  mockJob({ ...DONE_JOB, layout_cache: { md: true, docx: true } });
  vi.mocked(api.retryLayout).mockResolvedValue({ md: true, docx: true });
  renderWithRouter(<JobDetail />, { route: "/jobs/5" });
  const user = userEvent.setup();
  const btn = await screen.findByTestId("btn-retry-layout");
  expect(btn).toHaveTextContent("Rebuild layout");
  // Hủy → không gọi.
  await user.click(btn);
  expect(screen.getByTestId("confirm-dialog")).toBeInTheDocument();
  await user.click(screen.getByTestId("confirm-cancel"));
  expect(api.retryLayout).not.toHaveBeenCalled();
  // Confirm → gọi + toast + loading xong.
  await user.click(btn);
  await user.click(screen.getByTestId("confirm-accept"));
  expect(api.retryLayout).toHaveBeenCalledWith("5");
  await waitFor(() =>
    expect(toast.success).toHaveBeenCalledWith("Layout rebuilt."),
  );
  expect(await screen.findByTestId("btn-retry-layout")).not.toHaveAttribute("aria-busy");
});

/** Wave-3 #7 → Lane I Task 4: bỏ btn-edit-layout + textarea; btn-edit-doc mở UnifiedEditor. */
it("no btn-edit-layout / layout-editor-textarea; btn-edit-doc opens UnifiedEditor", async () => {
  mockJob(DONE_JOB);
  renderWithRouter(<JobDetail />, { route: "/jobs/5" });
  const user = userEvent.setup();
  expect(screen.queryByTestId("btn-edit-layout")).not.toBeInTheDocument();
  expect(screen.queryByTestId("layout-editor-textarea")).not.toBeInTheDocument();
  await user.click(await screen.findByTestId("btn-edit-doc"));
  expect(await screen.findByTestId("md-editor")).toBeInTheDocument();
});

/** Wave-3 #5 → Lane I Task 2: col phải KHÔNG còn sticky; File gốc + Info = collapsible default closed. */
it("renders single wrapper grid: collapsible original+info right (default closed, no sticky)", async () => {
  mockJob(DONE_JOB);
  renderWithRouter(<JobDetail />, { route: "/jobs/5" });
  await screen.findByTestId("section-text");
  await screen.findByTestId("section-layout");
  const grid = screen.getByTestId("detail-grid");
  expect(grid.className).toContain("lg:grid-cols-12");
  const colClasses = grid.className.split(/\s+/).filter((c) => c.includes("grid-cols"));
  expect(colClasses.length).toBeGreaterThan(0);
  expect(colClasses.every((c) => c.startsWith("lg:"))).toBe(true);
  expect(grid.querySelector(".lg\\:col-span-7")).not.toBeNull();
  // BỎ sticky (wave-3 G) — cột phải bình thường.
  const aside = grid.querySelector("aside");
  expect(aside).not.toBeNull();
  expect(aside!.className).toContain("lg:col-span-5");
  expect(aside!.className).not.toContain("sticky");
  // Default closed: panel chưa mount, aria-expanded=false, không fetch blob.
  expect(screen.queryByTestId("panel-original")).not.toBeInTheDocument();
  expect(screen.queryByTestId("panel-info")).not.toBeInTheDocument();
  expect(screen.getByTestId("btn-toggle-original")).toHaveAttribute("aria-expanded", "false");
  expect(screen.getByTestId("btn-toggle-info")).toHaveAttribute("aria-expanded", "false");
  expect(api.downloadJobFile).not.toHaveBeenCalled();
  // Mở → mount 1 panel duy nhất + blob fetch 1 lần; Đóng → unmount.
  const user = userEvent.setup();
  await user.click(screen.getByTestId("btn-toggle-original"));
  expect(await screen.findByTestId("panel-original")).toBeInTheDocument();
  expect(screen.queryByTestId("panel-original-layout")).not.toBeInTheDocument();
  await screen.findByTestId("original-pdf-frame");
  await waitFor(() => expect(api.downloadJobFile).toHaveBeenCalledTimes(1));
  await user.click(screen.getByTestId("btn-toggle-info"));
  expect(await screen.findByTestId("panel-info")).toBeInTheDocument();
  expect(screen.getByTestId("layout-preview")).toBeInTheDocument();
  expect(screen.getByTestId("export-bar")).toBeInTheDocument();
  await user.click(screen.getByTestId("btn-toggle-original"));
  expect(screen.queryByTestId("panel-original")).not.toBeInTheDocument();
  expect(screen.getByTestId("btn-toggle-original")).toHaveAttribute("aria-expanded", "false");
});

/**
 * Wave-3 #6: section "Văn bản" bỏ khung chiều cao — nội dung dài cuộn trang chính.
 * Verify: TextSection article/panel-result KHÔNG còn max-h/overflow (frame còn
 * lại đều ngoài section: aside File gốc viewer, preview Layout, IrViewer JSON
 * max-h-64 — hợp lý, giữ nguyên).
 */
it("section-text content has no fixed-height/overflow frame", async () => {
  mockJob(DONE_JOB);
  renderWithRouter(<JobDetail />, { route: "/jobs/5" });
  const section = await screen.findByTestId("section-text");
  const framed = Array.from(section.querySelectorAll("*")).filter((el) =>
    /max-h|overflow/.test(el.getAttribute("class") ?? ""),
  );
  expect(framed).toEqual([]);
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
  expect(screen.getByRole("heading", { level: 2, name: "Text" })).toBeInTheDocument();
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
  // Lane I Task 3: bỏ nút "Mở trang trích xuất đầy đủ" (route vẫn giữ, không còn link từ đây).
  expect(screen.queryByTestId("link-extraction")).not.toBeInTheDocument();
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
  expect(await screen.findByTestId("stale-badge")).toHaveTextContent("Needs sync");
  const invalidate = vi.spyOn(lastQueryClient!, "invalidateQueries");
  const user = userEvent.setup();
  await user.click(screen.getByTestId("btn-resync-layout"));
  expect(api.retryLayout).toHaveBeenCalledWith("5");
  await waitFor(() => expect(toast.success).toHaveBeenCalledWith("Layout synced"));
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
  expect(within(current).getByText("Current")).toBeInTheDocument();
  const old = screen.getByTestId("version-row-md-layout-2");
  expect(old).toHaveTextContent("v2");
  expect(old).toHaveTextContent("md-layout");
  // P2: max trong kind cũng "Hiện tại" (md-layout v2 là current của kind md-layout).
  expect(within(old).getByText("Current")).toBeInTheDocument();
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
    expect(toast.success).toHaveBeenCalledWith("Version restored"),
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
  expect(within(textRow).getByText("Current")).toBeInTheDocument();
  expect(within(mdRow).getByText("Current")).toBeInTheDocument();
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
  expect(within(await screen.findByTestId("version-row-md-2")).getByText("Current")).toBeInTheDocument();
  expect(within(screen.getByTestId("version-row-md-1")).queryByText("Current")).not.toBeInTheDocument();
  expect(within(screen.getByTestId("version-row-text-3")).getByText("Current")).toBeInTheDocument();
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
  expect(within(panel).getByRole("alert")).toHaveTextContent("Could not load the history");
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
