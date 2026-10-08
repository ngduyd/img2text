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

it("output-format select renders with Markdown as default", async () => {
  vi.mocked(api.me).mockResolvedValue({ id: 1, role: "user", ocr_enabled: true } as User);
  vi.mocked(api.listJobs).mockResolvedValue({ items: [], total: 0 });
  renderWithRouter(<Jobs />);
  const select = await screen.findByTestId("select-output-format");
  expect(select).toHaveValue("md");
  expect(screen.getByRole("option", { name: "Markdown" })).toBeInTheDocument();
  expect(screen.getByRole("option", { name: "Word (.docx)" })).toBeInTheDocument();
});

it("choosing Word passes output_format docx to uploadJob", async () => {
  vi.mocked(api.me).mockResolvedValue({ id: 1, role: "user", ocr_enabled: true } as User);
  vi.mocked(api.listJobs).mockResolvedValue({ items: [], total: 0 });
  vi.mocked(api.uploadJob).mockResolvedValue({ id: 42, status: "queued" } as Job);
  renderWithRouter(<Jobs />);
  await screen.findByTestId("btn-upload");
  const user = userEvent.setup({ applyAccept: false });
  await user.selectOptions(screen.getByTestId("select-output-format"), "docx");
  const file = new File(["x"], "a.txt", { type: "text/plain" });
  await user.upload(screen.getByTestId("input-file"), file);
  expect(api.uploadJob).toHaveBeenCalledWith(file, { output_format: "docx" });
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
  // P2: badge literal pins the shared STATUS_TEXT spelling ("Đang chờ worker Colab").
  expect(screen.getByTestId("badge-7")).toHaveTextContent("Đang chờ worker Colab");
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
  // P2: chip labels share STATUS_TEXT spellings with badges (one spelling per status).
  expect(screen.getByTestId("filter-queued")).toHaveTextContent("Đang chờ worker Colab (1)");
  expect(screen.getByTestId("filter-done")).toHaveTextContent("Hoàn tất (2)");
  expect(screen.getByTestId("filter-failed")).toHaveTextContent("Xử lý thất bại (1)");
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

it("header shows job stats (total, pending, done)", async () => {
  vi.mocked(api.me).mockResolvedValue({ id: 1, role: "user", ocr_enabled: true } as User);
  vi.mocked(api.listJobs).mockResolvedValue({
    items: [
      { id: 1, status: "queued", page_count: 1, file_type: "pdf", created_at: "2026-10-04T00:00:00Z", error: null },
      { id: 2, status: "running", page_count: 2, file_type: "jpg", created_at: "2026-10-04T00:00:00Z", error: null },
      { id: 3, status: "done", page_count: 3, file_type: "pdf", created_at: "2026-10-04T00:00:00Z", error: null },
      { id: 4, status: "failed", page_count: 1, file_type: "jpg", created_at: "2026-10-04T00:00:00Z", error: "boom" },
    ] as Job[],
    total: 4,
  });
  renderWithRouter(<Jobs />);
  await screen.findByTestId("job-row-4");
  expect(screen.getByTestId("stats-total")).toHaveTextContent("4");
  expect(screen.getByTestId("stats-pending")).toHaveTextContent("2");
  expect(screen.getByTestId("stats-done")).toHaveTextContent("1");
});

it("toolbar shows format select and filter tabs together", async () => {
  vi.mocked(api.me).mockResolvedValue({ id: 1, role: "user", ocr_enabled: true } as User);
  vi.mocked(api.listJobs).mockResolvedValue({ items: [], total: 0 });
  renderWithRouter(<Jobs />);
  await screen.findByTestId("empty-state");
  expect(screen.getByTestId("select-output-format")).toBeInTheDocument();
  expect(screen.getByTestId("filter-all")).toBeInTheDocument();
  expect(screen.getByTestId("filter-done")).toBeInTheDocument();
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
