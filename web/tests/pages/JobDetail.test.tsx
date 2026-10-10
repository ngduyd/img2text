import type { Query } from "@tanstack/react-query";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement } from "react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import type { Mock } from "vitest";
import * as mammoth from "mammoth";
import { api, ApiError } from "../../src/api/client";
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
      exportJob: vi.fn(),
      downloadExport: vi.fn(),
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
  await screen.findByTestId("md-editor");
  expect(screen.queryByTestId("btn-retry-layout")).not.toBeInTheDocument();
});

it("done stops polling", async () => {
  mockJob({ id: 5, status: "done", result: EMPTY_RESULT } as Job);
  renderWithRouter(<JobDetail />, { route: "/jobs/5" });
  expect(await screen.findByTestId("md-editor")).toBeInTheDocument();
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
} as Job;

it("done renders 3 panels: original + result + info with status badge", async () => {
  mockJob(DONE_JOB);
  renderWithRouter(<JobDetail />, { route: "/jobs/5" });
  expect(await screen.findByTestId("panel-original")).toBeInTheDocument();
  expect(screen.getByTestId("panel-result")).toBeInTheDocument();
  expect(screen.getByTestId("panel-info")).toBeInTheDocument();
  expect(screen.getByTestId("status-5")).toHaveTextContent("Hoàn tất");
});

/** Phase 3 Task 2: gỡ badge "Đầu ra" + statsLine + job-meta card; ExportBar giữ. */
it("done: no output-format badge / stats / job-meta in DOM, ExportBar renders", async () => {
  mockJob({ ...DONE_JOB, output_format: "docx" });
  renderWithRouter(<JobDetail />, { route: "/jobs/5" });
  await screen.findByTestId("panel-result");
  expect(screen.queryByTestId("job-meta")).not.toBeInTheDocument();
  expect(screen.queryByTestId("job-output-format")).not.toBeInTheDocument();
  expect(screen.queryByTestId("result-stats")).not.toBeInTheDocument();
  expect(screen.getByTestId("export-bar")).toBeInTheDocument();
  expect(screen.getByTestId("export-md")).toBeInTheDocument();
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

/** JD2 amendment: btn-edit-doc = inline edit TRÊN trang (không navigate /edit). */
it("btn-edit-doc toggles inline edit: scroll + focus MDEditor textarea, no navigation", async () => {
  mockJob(DONE_JOB);
  renderWithRouter(<JobDetail />, { route: "/jobs/5" });
  const user = userEvent.setup();
  const btn = await screen.findByTestId("btn-edit-doc");
  expect(btn).toHaveTextContent("Edit");
  await user.click(btn);
  expect(mockNavigate).not.toHaveBeenCalled();
  expect(btn).toHaveAttribute("aria-pressed", "true");
  expect(btn).toHaveTextContent("Đang sửa");
  const editor = await screen.findByTestId("md-editor");
  expect(editor.querySelector("textarea")).toHaveFocus();
  expect(scrollIntoViewMock).toHaveBeenCalledTimes(1);
  expect(scrollIntoViewMock).toHaveBeenCalledWith({ behavior: "smooth", block: "start" });
  // toggle lần 2 → tắt editing; MDEditor luôn hiển thị trong md mode (M5)
  await user.click(screen.getByTestId("btn-edit-doc"));
  expect(btn).toHaveAttribute("aria-pressed", "false");
  expect(screen.getByTestId("md-editor")).toBeInTheDocument();
  expect(screen.getByTestId("panel-editor")).toBeInTheDocument();
  expect(scrollIntoViewMock).toHaveBeenCalledTimes(2);
  expect(mockNavigate).not.toHaveBeenCalled();
});

/** Phase 3 split-view: trái = ResultPanel (7), phải = OriginalFilePanel đối chiếu (5), mobile stack. */
it("split-view: layout 7 cols | original 5 cols, mobile stacks", async () => {
  mockJob(DONE_JOB);
  renderWithRouter(<JobDetail />, { route: "/jobs/5" });
  const grid = await screen.findByTestId("detail-grid");
  expect(grid.className).toContain("lg:grid-cols-[7fr_5fr]");
  // Mobile stack: mọi grid-cols đều phải gắn tiền tố lg: (không có cột nào ở base).
  const colClasses = grid.className.split(/\s+/).filter((c) => c.includes("grid-cols"));
  expect(colClasses.length).toBeGreaterThan(0);
  expect(colClasses.every((c) => c.startsWith("lg:"))).toBe(true);
  const reading = screen.getByTestId("detail-reading");
  expect(reading).toContainElement(screen.getByTestId("panel-result"));
  const rail = screen.getByTestId("detail-rail");
  expect(rail).toContainElement(screen.getByTestId("panel-original"));
});

/** JD2 binding: desktop 2 cột GRID (không flex-percent) + rail chứa meta/export. */
it("layout: 2-column grid, reading col + rail with file/meta/export/info", async () => {
  mockJob(DONE_JOB);
  renderWithRouter(<JobDetail />, { route: "/jobs/5" });
  const grid = await screen.findByTestId("detail-grid");
  expect(grid.className).toContain("grid");
  expect(grid.className).toContain("lg:grid-cols-[7fr_5fr]");
  const reading = screen.getByTestId("detail-reading");
  expect(reading).toContainElement(screen.getByTestId("panel-result"));
  // Plan M: content area nằm trong panel-editor (fetch artifact xong mới render; M5: MDEditor)
  expect(await screen.findByTestId("md-editor")).toBeInTheDocument();
  expect(reading).toContainElement(screen.getByTestId("panel-editor"));
  const rail = screen.getByTestId("detail-rail");
  expect(rail).toContainElement(screen.getByTestId("panel-original"));
  expect(rail).toContainElement(screen.getByTestId("export-md"));
  expect(rail).toContainElement(screen.getByTestId("panel-info"));
  // export disclosure: nút phụ ẩn sau "Định dạng khác"
  expect(screen.getByTestId("export-more")).toBeInTheDocument();
  expect(screen.getByTestId("export-formats")).not.toBeVisible();
});

/** JD2 sticky context header: bám dưới AppNav (top-14 / md:top-16). */
it("header is sticky below app nav with blurred surface bg", async () => {
  mockJob(DONE_JOB);
  const { container } = renderWithRouter(<JobDetail />, { route: "/jobs/5" });
  await screen.findByTestId("job-header");
  const header = container.querySelector('[data-testid="job-header"]');
  expect(header).not.toBeNull();
  const cls = (header as HTMLElement).className;
  expect(cls).toContain("sticky");
  expect(cls).toContain("top-14");
  expect(cls).toContain("md:top-16");
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
