import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import { toast } from "sonner";
import { ApiError, api } from "../../src/api/client";
import type { JobListItem } from "../../src/api/types";
import JobRow from "../../src/components/JobRow";

vi.mock("../../src/api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../src/api/client")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      downloadJobFile: vi.fn(),
      retryJob: vi.fn(),
      cancelJob: vi.fn(),
      deleteJob: vi.fn(),
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

it("renders name line, status badge and en-US date", () => {
  renderRow(job({ file_type: "pdf" }));
  expect(screen.getByTestId("job-row-7")).toHaveTextContent("#7 · PDF · 2 pages");
  // R51: badge-{id} testid assertion preserved from old Jobs.test.tsx;
  // P2: literal pins the shared STATUS_KEY spelling ("Queued", default en).
  expect(screen.getByTestId("badge-7")).toHaveTextContent("Queued");
  const expected = new Intl.DateTimeFormat("en-US", { dateStyle: "medium", timeStyle: "short" }).format(
    new Date("2026-10-04T00:00:00Z"),
  );
  expect(screen.getByTestId("job-row-7")).toHaveTextContent(expected);
});

it("shows Image for non-pdf file_type", () => {
  renderRow(job({ file_type: "jpg" }));
  expect(screen.getByTestId("job-row-7")).toHaveTextContent("#7 · Image · 2 pages");
});

it("renders duration when done with both timestamps", () => {
  renderRow(
    job({
      status: "done",
      started_at: "2026-10-04T00:00:00Z",
      finished_at: "2026-10-04T00:00:10Z",
    }),
  );
  expect(screen.getByTestId("job-row-7")).toHaveTextContent("10s");
});

it("omits duration when timestamps missing (server list omits them)", () => {
  renderRow(job({ status: "done" }));
  expect(screen.getByTestId("job-row-7")).not.toHaveTextContent("10s");
});

it("view button navigates to detail", async () => {
  renderRow(job());
  await userEvent.click(screen.getByTestId("btn-view-7"));
  expect(mockNavigate).toHaveBeenCalledWith("/jobs/7");
});

it("dl-original downloads same-origin blob via downloadJobFile + anchor", async () => {
  // jsdom lacks blob URL APIs (same as OriginalFilePanel.test).
  vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:http://test/7");
  vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
  const clickSpy = vi
    .spyOn(HTMLAnchorElement.prototype, "click")
    .mockImplementation(() => {});
  vi.mocked(api.downloadJobFile).mockResolvedValue(new Blob(["pdf"]));
  renderRow(job({ status: "done" }));
  await userEvent.click(screen.getByTestId("btn-dl-original-7"));
  expect(api.downloadJobFile).toHaveBeenCalledWith(7);
  await waitFor(() => expect(clickSpy).toHaveBeenCalledTimes(1));
  const anchor = clickSpy.mock.instances[0] as HTMLAnchorElement;
  expect(anchor).toHaveAttribute("href", "blob:http://test/7");
  expect(anchor).toHaveAttribute("download", "job-7.pdf");
  expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:http://test/7");
  vi.restoreAllMocks();
});

it("dl-original button rendered only when done", () => {
  renderRow(job({ status: "queued" }));
  expect(screen.queryByTestId("btn-dl-original-7")).not.toBeInTheDocument();
});

it("retry button calls retryJob and invalidates jobs", async () => {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const invalidate = vi.spyOn(queryClient, "invalidateQueries");
  vi.mocked(api.retryJob).mockResolvedValue(undefined);
  renderRow(job({ status: "failed", error: "boom" }), queryClient);
  await userEvent.click(screen.getByTestId("btn-retry-job-7"));
  expect(api.retryJob).toHaveBeenCalledWith(7);
  expect(invalidate).toHaveBeenCalledWith({ queryKey: ["jobs"] });
  // R59a: retry success toasts the plan copy.
  expect(toast.success).toHaveBeenCalledWith("Retry scheduled");
});

it("retry failure toasts mapped error", async () => {
  vi.mocked(api.retryJob).mockRejectedValue(new ApiError("Job đang chạy."));
  renderRow(job({ status: "failed", error: "boom" }));
  await userEvent.click(screen.getByTestId("btn-retry-job-7"));
  expect(toast.error).toHaveBeenCalledWith("Job đang chạy.");
});

it("dl-original failure toasts mapped error (no success toast)", async () => {
  vi.mocked(api.downloadJobFile).mockRejectedValue(new ApiError("Không có file."));
  renderRow(job({ status: "done" }));
  await userEvent.click(screen.getByTestId("btn-dl-original-7"));
  expect(toast.error).toHaveBeenCalledWith("Không có file.");
});

it("retry button rendered only when failed", () => {
  renderRow(job({ status: "done" }));
  expect(screen.queryByTestId("btn-retry-job-7")).not.toBeInTheDocument();
});

// Hủy job: queued|extracting|rendering → cancel button; terminal statuses ẩn.
it.each(["queued", "extracting", "rendering"] as const)(
  "cancel button rendered when %s and calls cancelJob",
  async (status) => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const invalidate = vi.spyOn(queryClient, "invalidateQueries");
    vi.mocked(api.cancelJob).mockResolvedValue(undefined);
    renderRow(job({ status }), queryClient);
    await userEvent.click(screen.getByTestId("btn-cancel-job-7"));
    expect(api.cancelJob).toHaveBeenCalledWith(7);
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["jobs"] });
    expect(toast.success).toHaveBeenCalledWith("Job cancelled");
  },
);

it.each(["done", "failed", "cancelled"] as const)(
  "cancel button hidden when %s",
  (status) => {
    renderRow(job({ status }));
    expect(screen.queryByTestId("btn-cancel-job-7")).not.toBeInTheDocument();
  },
);

it("cancel failure toasts mapped error (no success toast)", async () => {
  vi.mocked(api.cancelJob).mockRejectedValue(new ApiError("Không hủy được"));
  renderRow(job({ status: "rendering" }));
  await userEvent.click(screen.getByTestId("btn-cancel-job-7"));
  expect(toast.error).toHaveBeenCalledWith("Không hủy được");
});

// Phase 4 Task 3: per-row checkbox (R51 testid row-select-{id}).
it("renders row-select checkbox and fires onToggle with the job id", async () => {
  const onToggle = vi.fn();
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter>
        <JobRow job={job()} selected={false} onToggle={onToggle} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  const box = screen.getByTestId("row-select-7") as HTMLInputElement;
  expect(box).not.toBeChecked();
  await userEvent.click(box);
  expect(onToggle).toHaveBeenCalledWith(7);
});

it("cụm actions flex-wrap + nút Tải bản gốc icon-only <sm (aria-label)", () => {
  renderRow(job({ status: "done" }));
  const dl = screen.getByTestId("btn-dl-original-7");
  expect(dl).toHaveAttribute("aria-label", "Download original");
  expect(dl.querySelector("svg")).not.toBeNull();
  expect(dl.parentElement).toHaveClass("flex-wrap", "justify-end");
});

// Spec #1: nút Xóa → confirm dialog → deleteJob + invalidate; hủy → không gọi.
it("delete: confirm → api.deleteJob + invalidate jobs + toast", async () => {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const invalidate = vi.spyOn(queryClient, "invalidateQueries");
  vi.mocked(api.deleteJob).mockResolvedValue(undefined);
  renderRow(job({ status: "done" }), queryClient);
  await userEvent.click(screen.getByTestId("btn-delete-job-7"));
  expect(screen.getByTestId("confirm-dialog")).toBeInTheDocument();
  await userEvent.click(screen.getByTestId("confirm-accept"));
  expect(api.deleteJob).toHaveBeenCalledWith(7);
  expect(invalidate).toHaveBeenCalledWith({ queryKey: ["jobs"] });
  expect(toast.success).toHaveBeenCalledWith("Job deleted");
});

it("delete: hủy confirm → không gọi deleteJob", async () => {
  renderRow(job({ status: "done" }));
  await userEvent.click(screen.getByTestId("btn-delete-job-7"));
  await userEvent.click(screen.getByTestId("confirm-cancel"));
  expect(screen.queryByTestId("confirm-dialog")).not.toBeInTheDocument();
  expect(api.deleteJob).not.toHaveBeenCalled();
});
