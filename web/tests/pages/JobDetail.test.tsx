import type { Query } from "@tanstack/react-query";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement } from "react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import { api, ApiError } from "../../src/api/client";
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
    },
  };
});

/**
 * Polling assertion choice (documented): spy on the useQuery options — capture
 * the refetchInterval callback the component actually registers, then evaluate
 * it against the mocked job. Real assertion on real interval logic, no fake timers.
 */
let capturedInterval: ((q: Query<Job>) => number | false) | undefined;

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
  capturedInterval = undefined;
  lastJob = undefined;
});

it("queued shows waiting message and polls", async () => {
  mockJob({ id: 5, status: "queued", page_count: 1, result: null } as Job);
  renderWithRouter(<JobDetail />, { route: "/jobs/5" });
  // Task 2: header badge duplicates status text — scope to InfoPanel's status badge.
  expect(await screen.findByTestId("status-5")).toHaveTextContent("Đang chờ worker Colab");
  // Back link points at the /jobs list route (root is public landing now).
  expect(screen.getByTestId("link-back-jobs")).toHaveAttribute("href", "/jobs");
  expect(pollSpyCalled()).toBe(true);
});

it("failed shows retry button and calls api", async () => {
  mockJob({ id: 5, status: "failed", error: "boom", result: null } as Job);
  vi.mocked(api.retryJob).mockResolvedValue({ id: 5, status: "queued" });
  renderWithRouter(<JobDetail />, { route: "/jobs/5" });
  expect(await screen.findByTestId("status-5")).toHaveTextContent("Xử lý thất bại");
  const user = userEvent.setup();
  await user.click(screen.getByTestId("btn-retry"));
  expect(api.retryJob).toHaveBeenCalledWith("5");
});

it("retry failure shows retry-error with server detail", async () => {
  mockJob({ id: 5, status: "failed", error: "boom", result: null } as Job);
  vi.mocked(api.retryJob).mockRejectedValue(new ApiError("Forbidden."));
  renderWithRouter(<JobDetail />, { route: "/jobs/5" });
  expect(await screen.findByTestId("status-5")).toHaveTextContent("Xử lý thất bại");
  const user = userEvent.setup();
  await user.click(screen.getByTestId("btn-retry"));
  expect(await screen.findByTestId("retry-error")).toHaveTextContent("Forbidden.");
});

it("done stops polling", async () => {
  mockJob({ id: 5, status: "done", result: EMPTY_RESULT } as Job);
  renderWithRouter(<JobDetail />, { route: "/jobs/5" });
  expect(await screen.findByTestId("preview-markdown")).toBeInTheDocument();
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
  expect(screen.getByTestId("result-stats")).toHaveTextContent(
    "Tổng 0 vùng · 0 ok · 0 hình ảnh · 0 không trích xuất · 0 cần kiểm tra",
  );
});

it("output-format badge defaults to Markdown (Plan D4)", async () => {
  mockJob(DONE_JOB);
  renderWithRouter(<JobDetail />, { route: "/jobs/5" });
  expect(await screen.findByTestId("job-output-format")).toHaveTextContent(
    "Đầu ra: Markdown",
  );
});

it("output-format badge shows Word for docx jobs (Plan D4)", async () => {
  mockJob({ ...DONE_JOB, output_format: "docx" });
  renderWithRouter(<JobDetail />, { route: "/jobs/5" });
  expect(await screen.findByTestId("job-output-format")).toHaveTextContent("Đầu ra: Word");
});

it("not done shows status-only panels, ResultPanel hidden until done", async () => {
  mockJob({ ...DONE_JOB, status: "queued", result: null });
  renderWithRouter(<JobDetail />, { route: "/jobs/5" });
  expect(await screen.findByTestId("panel-original")).toBeInTheDocument();
  expect(screen.getByTestId("panel-info")).toBeInTheDocument();
  expect(screen.queryByTestId("panel-result")).toBeNull();
  expect(screen.getByTestId("status-5")).toHaveTextContent("Đang chờ worker Colab");
});
