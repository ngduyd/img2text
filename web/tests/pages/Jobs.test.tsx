import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement } from "react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import { ApiError, api } from "../../src/api/client";
import type { Job, User } from "../../src/api/types";
import { toast } from "sonner";
import Jobs from "../../src/pages/Jobs";

vi.mock("../../src/api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../src/api/client")>();
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

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

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
  // Image files route to the crop wizard — txt exercises the immediate upload path.
  // applyAccept is a setup() option: input.accept would otherwise filter out non-matching files.
  const file = new File(["x"], "a.txt", { type: "text/plain" });
  const user = userEvent.setup({ applyAccept: false });
  await user.upload(screen.getByTestId("input-file"), file);
  expect(api.uploadJob).toHaveBeenCalledWith(file, { output_format: "md" });
  // R59: upload success → toast + navigate to /jobs (the list route now).
  expect(toast.success).toHaveBeenCalledWith("Đã tải lên — đang chờ xử lý.");
  await waitFor(() => expect(mockNavigate).toHaveBeenCalledWith("/jobs"));
});

// Format combo: the toolbar <select> is gone — the upload button is a split button.
it("split upload button renders with Markdown default; no format select in toolbar", async () => {
  vi.mocked(api.me).mockResolvedValue({ id: 1, role: "user", ocr_enabled: true } as User);
  vi.mocked(api.listJobs).mockResolvedValue({ items: [], total: 0 });
  renderWithRouter(<Jobs />);
  const btn = await screen.findByTestId("btn-upload");
  expect(btn).toHaveTextContent("Tải file lên · Markdown");
  expect(screen.getByTestId("btn-format-toggle")).toBeInTheDocument();
  expect(screen.queryByTestId("select-output-format")).not.toBeInTheDocument();
});

it("format menu: caret opens, Word→docx, Markdown→md, outside click closes", async () => {
  vi.mocked(api.me).mockResolvedValue({ id: 1, role: "user", ocr_enabled: true } as User);
  vi.mocked(api.listJobs).mockResolvedValue({ items: [], total: 0 });
  vi.mocked(api.uploadJob).mockResolvedValue({ id: 42, status: "queued" } as Job);
  renderWithRouter(<Jobs />);
  await screen.findByTestId("btn-upload");
  const user = userEvent.setup({ applyAccept: false });
  const file = new File(["x"], "a.txt", { type: "text/plain" });

  // caret → menu with both options
  await user.click(screen.getByTestId("btn-format-toggle"));
  expect(screen.getByTestId("format-opt-md")).toBeInTheDocument();
  expect(screen.getByTestId("format-opt-docx")).toBeInTheDocument();
  // choose Word → menu closes, label reflects state, upload sends docx
  await user.click(screen.getByTestId("format-opt-docx"));
  expect(screen.queryByTestId("format-opt-docx")).not.toBeInTheDocument();
  expect(screen.getByTestId("btn-upload")).toHaveTextContent("Tải file lên · Word");
  await user.upload(screen.getByTestId("input-file"), file);
  expect(api.uploadJob).toHaveBeenLastCalledWith(file, { output_format: "docx" });
  // choose Markdown again → upload sends md
  await user.click(screen.getByTestId("btn-format-toggle"));
  await user.click(screen.getByTestId("format-opt-md"));
  expect(screen.getByTestId("btn-upload")).toHaveTextContent("Tải file lên · Markdown");
  await user.upload(screen.getByTestId("input-file"), file);
  expect(api.uploadJob).toHaveBeenLastCalledWith(file, { output_format: "md" });
  // click outside → menu closes
  await user.click(screen.getByTestId("btn-format-toggle"));
  expect(screen.getByTestId("format-opt-md")).toBeInTheDocument();
  await user.click(screen.getByRole("heading", { name: "Công việc" }));
  expect(screen.queryByTestId("format-opt-md")).not.toBeInTheDocument();
});

it("upload error surfaces server detail", async () => {
  vi.mocked(api.me).mockResolvedValue({ id: 1, role: "user", ocr_enabled: true } as User);
  vi.mocked(api.listJobs).mockResolvedValue({ items: [], total: 0 });
  vi.mocked(api.uploadJob).mockRejectedValue(new ApiError("Đã đạt giới hạn upload hôm nay."));
  renderWithRouter(<Jobs />);
  await screen.findByTestId("btn-upload");
  const file = new File(["x"], "a.txt", { type: "text/plain" });
  const user = userEvent.setup({ applyAccept: false });
  await user.upload(screen.getByTestId("input-file"), file);
  expect(await screen.findByTestId("upload-error")).toHaveTextContent(
    "Đã đạt giới hạn upload hôm nay.",
  );
  // R59: failing upload also toasts mapped detail (inline block kept, R51).
  expect(toast.error).toHaveBeenCalledWith("Đã đạt giới hạn upload hôm nay.");
  expect(api.uploadJob).toHaveBeenCalledWith(file, { output_format: "md" });
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
  // P2: badge literal pins the shared STATUS_TEXT spelling ("Đang lập lịch").
  expect(screen.getByTestId("badge-7")).toHaveTextContent("Đang lập lịch");
});

it("filter tabs show counts and click filters rows", async () => {
  vi.mocked(api.me).mockResolvedValue({ id: 1, role: "user", ocr_enabled: true } as User);
  vi.mocked(api.listJobs).mockResolvedValue({
    items: [
      { id: 1, status: "queued", page_count: 1, file_type: "pdf", created_at: "2026-10-04T00:00:00Z", error: null },
      { id: 2, status: "done", page_count: 2, file_type: "jpg", created_at: "2026-10-04T00:00:00Z", error: null },
      { id: 3, status: "done", page_count: 3, file_type: "pdf", created_at: "2026-10-04T00:00:00Z", error: null },
      { id: 4, status: "failed", page_count: 1, file_type: "jpg", created_at: "2026-10-04T00:00:00Z", error: "boom" },
      { id: 5, status: "extracting", page_count: 2, file_type: "pdf", created_at: "2026-10-04T00:00:00Z", error: null },
      { id: 6, status: "rendering", page_count: 1, file_type: "jpg", created_at: "2026-10-04T00:00:00Z", error: null },
    ] as Job[],
    total: 6,
  });
  renderWithRouter(<Jobs />);
  await screen.findByTestId("job-row-4");
  await waitFor(() => expect(screen.getByTestId("filter-all")).toHaveTextContent("Tất cả (6)"));
  // P2: chip labels share STATUS_TEXT spellings with badges (one spelling per status).
  expect(screen.getByTestId("filter-queued")).toHaveTextContent("Đang lập lịch (1)");
  expect(screen.getByTestId("filter-extracting")).toHaveTextContent("Đang trích xuất văn bản (1)");
  expect(screen.getByTestId("filter-rendering")).toHaveTextContent("Đang dựng layout (1)");
  expect(screen.getByTestId("filter-done")).toHaveTextContent("Hoàn tất (2)");
  expect(screen.getByTestId("filter-failed")).toHaveTextContent("Xử lý thất bại (1)");
  // New phase tabs filter to their own rows.
  await userEvent.click(screen.getByTestId("filter-extracting"));
  expect(screen.getByTestId("job-row-5")).toBeInTheDocument();
  expect(screen.queryByTestId("job-row-1")).not.toBeInTheDocument();
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

it("filter with no matches shows empty-filter message", async () => {
  vi.mocked(api.me).mockResolvedValue({ id: 1, role: "user", ocr_enabled: true } as User);
  vi.mocked(api.listJobs).mockResolvedValue({
    items: [
      { id: 2, status: "done", page_count: 2, file_type: "pdf", created_at: "2026-10-04T00:00:00Z", error: null },
    ] as Job[],
    total: 1,
  });
  renderWithRouter(<Jobs />);
  await screen.findByTestId("job-row-2");
  await userEvent.click(screen.getByTestId("filter-failed"));
  expect(await screen.findByTestId("empty-filter")).toHaveTextContent(
    "Không có công việc nào khớp bộ lọc.",
  );
  expect(screen.queryByTestId("job-row-2")).not.toBeInTheDocument();
});

// Task 2: loading state = Skeleton rows (testid "skeleton"), never a spinner/blank.
it("loading state renders skeleton rows while the jobs list is pending", async () => {
  vi.mocked(api.me).mockResolvedValue({ id: 1, role: "user", ocr_enabled: true } as User);
  vi.mocked(api.listJobs).mockReturnValue(new Promise<never>(() => {})); // never resolves
  renderWithRouter(<Jobs />);
  expect((await screen.findAllByTestId("skeleton")).length).toBeGreaterThan(0);
});

// Phase 4 Task 2: pagination controls render + click page 2 → refetch.
it("pagination shows page controls and click page 2 refetches the list", async () => {
  vi.mocked(api.me).mockResolvedValue({ id: 1, role: "user", ocr_enabled: true } as User);
  const pageOne = { id: 11, status: "queued", page_count: 1, file_type: "pdf", created_at: "2026-10-04T00:00:00Z", error: null } as Job;
  const pageTwo = { id: 21, status: "done", page_count: 2, file_type: "jpg", created_at: "2026-10-04T00:00:00Z", error: null } as Job;
  vi.mocked(api.listJobs).mockImplementation((page = 1) =>
    Promise.resolve({ items: page === 2 ? [pageTwo] : [pageOne], total: 12, page, page_size: 10 }),
  );
  renderWithRouter(<Jobs />);
  expect(api.listJobs).toHaveBeenCalledWith(1);
  await screen.findByTestId("job-row-11");
  // Trang 1: prev disabled.
  expect(screen.getByTestId("btn-page-prev")).toBeDisabled();
  await userEvent.click(screen.getByTestId("btn-page-2"));
  await screen.findByTestId("job-row-21");
  expect(api.listJobs).toHaveBeenCalledWith(2);
  await waitFor(() => expect(screen.getByTestId("btn-page-2")).toHaveAttribute("aria-current", "page"));
});

it("header shows job stats (total, pending, done)", async () => {
  vi.mocked(api.me).mockResolvedValue({ id: 1, role: "user", ocr_enabled: true } as User);
  vi.mocked(api.listJobs).mockResolvedValue({
    items: [
      { id: 1, status: "queued", page_count: 1, file_type: "pdf", created_at: "2026-10-04T00:00:00Z", error: null },
      { id: 2, status: "extracting", page_count: 2, file_type: "jpg", created_at: "2026-10-04T00:00:00Z", error: null },
      { id: 5, status: "rendering", page_count: 2, file_type: "jpg", created_at: "2026-10-04T00:00:00Z", error: null },
      { id: 3, status: "done", page_count: 3, file_type: "pdf", created_at: "2026-10-04T00:00:00Z", error: null },
      { id: 4, status: "failed", page_count: 1, file_type: "jpg", created_at: "2026-10-04T00:00:00Z", error: "boom" },
    ] as Job[],
    total: 5,
  });
  renderWithRouter(<Jobs />);
  await screen.findByTestId("job-row-4");
  // Plan job-phases: pending bucket = queued + extracting + rendering.
  expect(screen.getByTestId("stats-total")).toHaveTextContent("5");
  expect(screen.getByTestId("stats-pending")).toHaveTextContent("3");
  expect(screen.getByTestId("stats-done")).toHaveTextContent("1");
});

it("toolbar shows filter tabs without an output-format select", async () => {
  vi.mocked(api.me).mockResolvedValue({ id: 1, role: "user", ocr_enabled: true } as User);
  vi.mocked(api.listJobs).mockResolvedValue({ items: [], total: 0 });
  renderWithRouter(<Jobs />);
  await screen.findByTestId("empty-state");
  expect(screen.queryByTestId("select-output-format")).not.toBeInTheDocument();
  expect(screen.getByTestId("filter-all")).toBeInTheDocument();
  expect(screen.getByTestId("filter-done")).toBeInTheDocument();
  expect(screen.getByTestId("btn-format-toggle")).toBeInTheDocument();
});

it("empty state shows CTA hint", async () => {
  vi.mocked(api.me).mockResolvedValue({ id: 1, role: "user", ocr_enabled: true } as User);
  vi.mocked(api.listJobs).mockResolvedValue({ items: [], total: 0 });
  renderWithRouter(<Jobs />);
  const empty = await screen.findByTestId("empty-state");
  expect(empty).toHaveTextContent("Tải file lên để tạo công việc đầu tiên.");
});

it("job row shows file type icon", async () => {
  vi.mocked(api.me).mockResolvedValue({ id: 1, role: "user", ocr_enabled: true } as User);
  vi.mocked(api.listJobs).mockResolvedValue({
    items: [
      { id: 7, status: "queued", page_count: 2, file_type: "pdf", created_at: "2026-10-04T00:00:00Z", error: null },
    ] as Job[],
    total: 1,
  });
  renderWithRouter(<Jobs />);
  const row = await screen.findByTestId("job-row-7");
  expect(row.querySelector("svg")).not.toBeNull();
});
