import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { api, ApiError } from "../../../src/api/client";
import AdminWorkers from "../../../src/pages/admin/AdminWorkers";

vi.mock("../../../src/api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../../src/api/client")>();
  return { ...actual, api: { ...actual.api, getWorkers: vi.fn() } };
});

beforeEach(() => {
  vi.clearAllMocks();
});

it("renders worker rows with kind/last_seen + amber silent badge + queue_depth", async () => {
  vi.mocked(api.getWorkers).mockResolvedValue({
    workers: [
      { worker_id: "w1", kind: "colab-loop", last_seen: "2026-10-14T10:00:00Z", current_job_id: 7, silent_seconds: 10 },
      { worker_id: "w2", kind: "kaggle-batch", last_seen: "2026-10-14T09:00:00Z", current_job_id: null, silent_seconds: 3000 },
    ],
    queue_depth: 4,
  });
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <AdminWorkers />
    </QueryClientProvider>,
  );
  const card = await screen.findByTestId("admin-workers");
  expect(card).toHaveTextContent("colab-loop");
  expect(card).toHaveTextContent("kaggle-batch");
  expect(card).toHaveTextContent("4");
  // silent_seconds > 2700 (2 lease × 45p) → badge im lặng.
  expect(screen.getByTestId("worker-silent-w2")).toHaveTextContent("Im lặng");
  expect(screen.queryByTestId("worker-silent-w1")).not.toBeInTheDocument();
});

it("403/401 (ApiError) → ẩn card", async () => {
  vi.mocked(api.getWorkers).mockRejectedValue(new ApiError("forbidden"));
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <AdminWorkers />
    </QueryClientProvider>,
  );
  await vi.waitFor(() =>
    expect(screen.queryByTestId("admin-workers")).not.toBeInTheDocument(),
  );
});
