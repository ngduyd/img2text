import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import { expect, it } from "vitest";
import type { Job } from "../../../src/api/types";
import InfoPanel from "../../../src/components/panels/InfoPanel";

// InfoPanel chứa IrViewer (useQuery) → cần provider.
const renderPanel = (job: Job) =>
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <InfoPanel job={job} />
    </QueryClientProvider>,
  );

const DONE_JOB: Job = {
  id: 5,
  status: "done",
  file_type: "pdf",
  page_count: 3,
  error: null,
  created_at: "2026-01-02T03:04:05Z",
  started_at: "2026-01-02T04:00:00Z",
  finished_at: "2026-01-02T05:00:00Z",
  result: {
    model_version: "m1",
    gpu_seconds: 12.5,
    warnings: [],
    markdown: "# A",
    pages: [],
    edited_markdown: null,
  },
  text_version: 1,
};

it("renders status badge + vi-VN dates, page count, gpu + model", () => {
  renderPanel(DONE_JOB);
  expect(screen.getByTestId("panel-info")).toBeInTheDocument();
  expect(screen.getByTestId("status-5")).toHaveTextContent("Hoàn tất");
  // vi-VN date (env ICU: "2/1/2026") on all three timestamps.
  expect(screen.getAllByText(/\/2026/)).toHaveLength(3);
  expect(screen.getByText("Số trang:")).toBeInTheDocument();
  expect(screen.getByText("3")).toBeInTheDocument();
  expect(screen.getByText(/GPU \(giây\):/)).toBeInTheDocument();
  expect(screen.getByText(/12[.,]5/)).toBeInTheDocument();
  expect(screen.getByText("Model:")).toBeInTheDocument();
  expect(screen.getByText("m1")).toBeInTheDocument();
});

it("queued job without result omits gpu/model/finished", () => {
  const job: Job = {
    ...DONE_JOB,
    status: "queued",
    started_at: null,
    finished_at: null,
    result: null,
  };
  renderPanel(job);
  const panel = screen.getByTestId("panel-info");
  expect(within(panel).getByTestId("status-5")).toHaveTextContent("Đang lập lịch");
  expect(within(panel).queryByText(/GPU/)).toBeNull();
  expect(within(panel).queryByText("m1")).toBeNull();
  expect(within(panel).getAllByText(/\/2026/)).toHaveLength(1);
});
