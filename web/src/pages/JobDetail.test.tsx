import type { Query } from "@tanstack/react-query";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement } from "react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import { api } from "../api/client";
import type { Job, ResultBody } from "../api/types";
import JobDetail from "./JobDetail";

vi.mock("../api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/client")>();
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
  expect(await screen.findByText("Đang chờ worker Colab")).toBeInTheDocument();
  expect(pollSpyCalled()).toBe(true);
});

it("failed shows retry button and calls api", async () => {
  mockJob({ id: 5, status: "failed", error: "boom", result: null } as Job);
  vi.mocked(api.retryJob).mockResolvedValue({ id: 5, status: "queued" });
  renderWithRouter(<JobDetail />, { route: "/jobs/5" });
  expect(await screen.findByText("Xử lý thất bại")).toBeInTheDocument();
  const user = userEvent.setup();
  await user.click(screen.getByTestId("btn-retry"));
  expect(api.retryJob).toHaveBeenCalledWith("5");
});

it("done stops polling", async () => {
  mockJob({ id: 5, status: "done", result: EMPTY_RESULT } as Job);
  renderWithRouter(<JobDetail />, { route: "/jobs/5" });
  expect(await screen.findByTestId("preview-markdown")).toBeInTheDocument();
  expect(pollSpyCalled()).toBe(false);
});
