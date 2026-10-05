import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import { toast } from "sonner";
import { ApiError, api } from "../api/client";
import type { JobListItem } from "../api/types";
import JobRow from "./JobRow";

vi.mock("../api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/client")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      getJobFile: vi.fn(),
      retryJob: vi.fn(),
    },
  };
});

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const mockNavigate = vi.fn();

vi.mock("react-router-dom", async (importOriginal) => {
  const actual = await importOriginal<typeof import("react-router-dom")>();
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  };
});

function job(overrides: Partial<JobListItem> = {}): JobListItem {
  return {
    id: 7,
    status: "queued",
    file_type: "pdf",
    page_count: 2,
    error: null,
    created_at: "2026-10-04T00:00:00Z",
    ...overrides,
  };
}

function renderRow(
  j: JobListItem,
  queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } }),
) {
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <JobRow job={j} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return queryClient;
}

beforeEach(() => {
  vi.clearAllMocks();
});

it("renders name line, status badge and vi-VN date", () => {
  renderRow(job({ file_type: "pdf" }));
  expect(screen.getByTestId("job-row-7")).toHaveTextContent("#7 · PDF · 2 trang");
  // R51: badge-{id} testid assertion preserved from old Jobs.test.tsx;
  // P2: literal pins the shared STATUS_TEXT spelling ("Đang chờ worker Colab").
  expect(screen.getByTestId("badge-7")).toHaveTextContent("Đang chờ worker Colab");
  const expected = new Intl.DateTimeFormat("vi-VN", { dateStyle: "medium", timeStyle: "short" }).format(
    new Date("2026-10-04T00:00:00Z"),
  );
  expect(screen.getByTestId("job-row-7")).toHaveTextContent(expected);
});

it("shows Ảnh for non-pdf file_type", () => {
  renderRow(job({ file_type: "jpg" }));
  expect(screen.getByTestId("job-row-7")).toHaveTextContent("#7 · Ảnh · 2 trang");
});

it("renders duration when done with both timestamps", () => {
  renderRow(
    job({
      status: "done",
      started_at: "2026-10-04T00:00:00Z",
      finished_at: "2026-10-04T00:00:10Z",
    }),
  );
  expect(screen.getByTestId("job-row-7")).toHaveTextContent("10 giây");
});

it("omits duration when timestamps missing (server list omits them)", () => {
  renderRow(job({ status: "done" }));
  expect(screen.getByTestId("job-row-7")).not.toHaveTextContent("giây");
});

it("view button navigates to detail", async () => {
  renderRow(job());
  await userEvent.click(screen.getByTestId("btn-view-7"));
  expect(mockNavigate).toHaveBeenCalledWith("/jobs/7");
});

it("dl-original opens presigned url from getJobFile", async () => {
  const open = vi.fn();
  vi.stubGlobal("open", open);
  vi.mocked(api.getJobFile).mockResolvedValue({ url: "https://signed.example/f" });
  renderRow(job({ status: "done" }));
  await userEvent.click(screen.getByTestId("btn-dl-original-7"));
  expect(api.getJobFile).toHaveBeenCalledWith(7);
  expect(open).toHaveBeenCalledWith("https://signed.example/f", "_blank");
  vi.unstubAllGlobals();
});

it("dl-original button rendered only when done", () => {
  renderRow(job({ status: "queued" }));
  expect(screen.queryByTestId("btn-dl-original-7")).not.toBeInTheDocument();
});

it("retry button calls retryJob and invalidates jobs", async () => {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const invalidate = vi.spyOn(queryClient, "invalidateQueries");
  vi.mocked(api.retryJob).mockResolvedValue({ id: 7, status: "queued" });
  renderRow(job({ status: "failed", error: "boom" }), queryClient);
  await userEvent.click(screen.getByTestId("btn-retry-7"));
  expect(api.retryJob).toHaveBeenCalledWith(7);
  expect(invalidate).toHaveBeenCalledWith({ queryKey: ["jobs"] });
  // R59a: retry success toasts.
  expect(toast.success).toHaveBeenCalledWith("Đã chạy lại.");
});

it("retry failure toasts mapped error", async () => {
  vi.mocked(api.retryJob).mockRejectedValue(new ApiError("Job đang chạy."));
  renderRow(job({ status: "failed", error: "boom" }));
  await userEvent.click(screen.getByTestId("btn-retry-7"));
  expect(toast.error).toHaveBeenCalledWith("Job đang chạy.");
});

it("dl-original failure toasts mapped error (no success toast)", async () => {
  vi.stubGlobal("open", vi.fn());
  vi.mocked(api.getJobFile).mockRejectedValue(new ApiError("Không có file."));
  renderRow(job({ status: "done" }));
  await userEvent.click(screen.getByTestId("btn-dl-original-7"));
  expect(toast.error).toHaveBeenCalledWith("Không có file.");
  vi.unstubAllGlobals();
});

it("retry button rendered only when failed", () => {
  renderRow(job({ status: "done" }));
  expect(screen.queryByTestId("btn-retry-7")).not.toBeInTheDocument();
});
