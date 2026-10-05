import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement } from "react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import { ApiError, api } from "../api/client";
import type { Job, User } from "../api/types";
import Jobs from "./Jobs";

vi.mock("../api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/client")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      me: vi.fn(),
      listJobs: vi.fn(),
      uploadJob: vi.fn(),
    },
  };
});

export const mockNavigate = vi.fn();

vi.mock("react-router-dom", async (importOriginal) => {
  const actual = await importOriginal<typeof import("react-router-dom")>();
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  };
});

/** Page tests: MemoryRouter + QueryClientProvider (App wraps both in prod). */
function renderWithRouter(ui: ReactElement, { route = "/" } = {}) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(ui, {
    wrapper: ({ children }) => (
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={[route]}>{children}</MemoryRouter>
      </QueryClientProvider>
    ),
  });
}

beforeEach(() => {
  vi.clearAllMocks();
});

it("banner and disabled upload when ocr_enabled false", async () => {
  vi.mocked(api.me).mockResolvedValue({ id: 1, role: "user", ocr_enabled: false } as User);
  vi.mocked(api.listJobs).mockResolvedValue({ items: [], total: 0 });
  renderWithRouter(<Jobs />);
  expect(await screen.findByTestId("banner-no-access")).toHaveTextContent("Chờ admin cấp quyền");
  expect(screen.getByTestId("btn-upload")).toBeDisabled();
});

it("upload button enabled and calls api when granted", async () => {
  vi.mocked(api.me).mockResolvedValue({ id: 1, role: "user", ocr_enabled: true } as User);
  vi.mocked(api.listJobs).mockResolvedValue({ items: [], total: 0 });
  vi.mocked(api.uploadJob).mockResolvedValue({ id: 42, status: "queued", page_count: 3 } as Job);
  renderWithRouter(<Jobs />);
  const btn = await screen.findByTestId("btn-upload");
  expect(btn).toBeEnabled();
  const file = new File(["x"], "a.jpg", { type: "image/jpeg" });
  const user = userEvent.setup();
  await user.upload(screen.getByTestId("input-file"), file);
  expect(api.uploadJob).toHaveBeenCalledWith(file);
  await waitFor(() => expect(mockNavigate).toHaveBeenCalledWith("/jobs/42"));
});

it("upload error surfaces server detail", async () => {
  vi.mocked(api.me).mockResolvedValue({ id: 1, role: "user", ocr_enabled: true } as User);
  vi.mocked(api.listJobs).mockResolvedValue({ items: [], total: 0 });
  vi.mocked(api.uploadJob).mockRejectedValue(new ApiError("Đã đạt giới hạn upload hôm nay."));
  renderWithRouter(<Jobs />);
  await screen.findByTestId("btn-upload");
  const file = new File(["x"], "a.jpg", { type: "image/jpeg" });
  const user = userEvent.setup();
  await user.upload(screen.getByTestId("input-file"), file);
  expect(await screen.findByTestId("upload-error")).toHaveTextContent(
    "Đã đạt giới hạn upload hôm nay.",
  );
  expect(api.uploadJob).toHaveBeenCalledWith(file);
});

it("job rows render status badge", async () => {
  vi.mocked(api.me).mockResolvedValue({ id: 1, role: "user", ocr_enabled: true } as User);
  vi.mocked(api.listJobs).mockResolvedValue({
    items: [
      {
        id: 7,
        status: "queued",
        page_count: 2,
        file_type: "pdf",
        created_at: "2026-10-04T00:00:00Z",
        error: null,
      } as Job,
    ],
    total: 1,
  });
  renderWithRouter(<Jobs />);
  expect(await screen.findByTestId("job-row-7")).toBeInTheDocument();
  expect(screen.getByTestId("badge-7")).toHaveTextContent("Chờ xử lý");
});

it("filter tabs show counts and click filters rows", async () => {
  vi.mocked(api.me).mockResolvedValue({ id: 1, role: "user", ocr_enabled: true } as User);
  vi.mocked(api.listJobs).mockResolvedValue({
    items: [
      { id: 1, status: "queued", page_count: 1, file_type: "pdf", created_at: "2026-10-04T00:00:00Z", error: null },
      { id: 2, status: "done", page_count: 2, file_type: "jpg", created_at: "2026-10-04T00:00:00Z", error: null },
      { id: 3, status: "done", page_count: 3, file_type: "pdf", created_at: "2026-10-04T00:00:00Z", error: null },
      { id: 4, status: "failed", page_count: 1, file_type: "jpg", created_at: "2026-10-04T00:00:00Z", error: "boom" },
    ] as Job[],
    total: 4,
  });
  renderWithRouter(<Jobs />);
  await screen.findByTestId("job-row-4");
  await waitFor(() => expect(screen.getByTestId("filter-all")).toHaveTextContent("Tất cả (4)"));
  expect(screen.getByTestId("filter-queued")).toHaveTextContent("Chờ xử lý (1)");
  expect(screen.getByTestId("filter-done")).toHaveTextContent("Hoàn tất (2)");
  expect(screen.getByTestId("filter-failed")).toHaveTextContent("Thất bại (1)");
  const user = userEvent.setup();
  await user.click(screen.getByTestId("filter-done"));
  expect(screen.getByTestId("job-row-2")).toBeInTheDocument();
  expect(screen.getByTestId("job-row-3")).toBeInTheDocument();
  expect(screen.queryByTestId("job-row-1")).not.toBeInTheDocument();
  expect(screen.queryByTestId("job-row-4")).not.toBeInTheDocument();
  await user.click(screen.getByTestId("filter-failed"));
  expect(screen.queryByTestId("job-row-2")).not.toBeInTheDocument();
  expect(screen.getByTestId("job-row-4")).toBeInTheDocument();
});

it("empty state renders guidance with limits and Colab note", async () => {
  vi.mocked(api.me).mockResolvedValue({ id: 1, role: "user", ocr_enabled: true } as User);
  vi.mocked(api.listJobs).mockResolvedValue({ items: [], total: 0 });
  renderWithRouter(<Jobs />);
  const empty = await screen.findByTestId("empty-state");
  expect(empty).toHaveTextContent("tối đa 50 trang · 50MB");
  expect(empty).toHaveTextContent("Job chờ worker Colab kết nối");
});
