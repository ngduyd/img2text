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
      retryJobs: vi.fn(),
      // T6: QuotaBadge query — mock null (ẩn) để test Jobs không fetch thật
      getMyQuota: vi.fn(async () => null),
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
  // jsdom thiếu object URL cho thumbnail card của MultiFileUpload.
  Object.defineProperty(URL, "createObjectURL", {
    value: vi.fn(() => "blob:mock"),
    configurable: true,
    writable: true,
  });
  Object.defineProperty(URL, "revokeObjectURL", {
    value: vi.fn(),
    configurable: true,
    writable: true,
  });
});

// PNG 1×1 thật — pdf-lib từ chối bytes giả ("The input is not a PNG file!").
const PNG_1PX = Uint8Array.from(
  atob(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==",
  ),
  (c) => c.charCodeAt(0),
);
const png = () => new File([PNG_1PX], "photo.png", { type: "image/png" });

/** Thêm 1 ảnh → bấm Gửi → SubmitModal mở (flow U3). */
async function openSubmitModal() {
  const user = userEvent.setup();
  await user.upload(screen.getByTestId("muf-input"), png());
  await screen.findByTestId("muf-card-0");
  await user.click(screen.getByTestId("muf-submit"));
  await screen.findByTestId("submit-modal");
  return user;
}

it("banner and disabled Gửi/input when ocr_enabled false", async () => {
  vi.mocked(api.me).mockResolvedValue({ id: 1, role: "user", ocr_enabled: false } as User);
  vi.mocked(api.listJobs).mockResolvedValue({ items: [], total: 0 });
  renderWithRouter(<Jobs />);
  expect(await screen.findByTestId("banner-no-access")).toHaveTextContent("Waiting for admin to grant OCR access");
  // D5: chưa có file → chỉ còn CTA chọn file (nút Gửi chỉ hiện khi có file).
  expect(screen.queryByTestId("muf-submit")).not.toBeInTheDocument();
  expect(screen.getByTestId("muf-pick")).toBeDisabled();
  expect(screen.getByTestId("muf-input")).toBeDisabled();
});

it("Gửi → modal → confirm: uploadJob(gộp PDF, layout+md) + toast + navigate", async () => {
  vi.mocked(api.me).mockResolvedValue({ id: 1, role: "user", ocr_enabled: true } as User);
  vi.mocked(api.listJobs).mockResolvedValue({ items: [], total: 0 });
  vi.mocked(api.uploadJob).mockResolvedValue({ id: 42, status: "queued" } as Job);
  renderWithRouter(<Jobs />);
  await screen.findByTestId("muf-input");
  const user = await openSubmitModal();
  await user.click(screen.getByTestId("sm-confirm"));
  // Job = 1 PDF gộp client-side → presign lane (api.uploadJob), metadata-only.
  await waitFor(() =>
    expect(api.uploadJob).toHaveBeenCalledWith(
      expect.any(Blob),
      expect.objectContaining({ filename: "photo.png", mode: "layout", output_format: "md" }),
    ),
  );
  expect(toast.success).toHaveBeenCalledWith("Uploaded — queued for processing.");
  await waitFor(() => expect(mockNavigate).toHaveBeenCalledWith("/jobs"));
  // Gửi thành công → cards xóa (revoke thumbnails).
  await waitFor(() => expect(screen.queryByTestId("muf-card-0")).not.toBeInTheDocument());
});

it("modal: default layout+md; Hủy → không upload, giữ card", async () => {
  vi.mocked(api.me).mockResolvedValue({ id: 1, role: "user", ocr_enabled: true } as User);
  vi.mocked(api.listJobs).mockResolvedValue({ items: [], total: 0 });
  renderWithRouter(<Jobs />);
  const user = await openSubmitModal();
  expect(screen.getByTestId("sm-mode-layout")).toBeChecked();
  expect(screen.getByTestId("sm-format-md")).toBeChecked();
  // Format picker cũ (split button trên Jobs) đã chuyển vào modal.
  expect(screen.queryByTestId("btn-format-toggle")).not.toBeInTheDocument();
  await user.click(screen.getByTestId("sm-cancel"));
  expect(screen.queryByTestId("submit-modal")).not.toBeInTheDocument();
  expect(api.uploadJob).not.toHaveBeenCalled();
  expect(screen.getByTestId("muf-card-0")).toBeInTheDocument();
});

it("modal choices: layout → docx; extract_only → mode + md", async () => {
  vi.mocked(api.me).mockResolvedValue({ id: 1, role: "user", ocr_enabled: true } as User);
  vi.mocked(api.listJobs).mockResolvedValue({ items: [], total: 0 });
  vi.mocked(api.uploadJob).mockResolvedValue({ id: 42, status: "queued" } as Job);
  renderWithRouter(<Jobs />);
  await screen.findByTestId("muf-input");
  // layout + word → docx
  let user = await openSubmitModal();
  await user.click(screen.getByTestId("sm-format-docx"));
  await user.click(screen.getByTestId("sm-confirm"));
  await waitFor(() =>
    expect(api.uploadJob).toHaveBeenLastCalledWith(
      expect.any(Blob),
      expect.objectContaining({ mode: "layout", output_format: "docx" }),
    ),
  );
  // extract_only → ẩn md/word, luôn output_format md
  user = await openSubmitModal();
  await user.click(screen.getByTestId("sm-mode-extract-only"));
  expect(screen.queryByTestId("sm-format-md")).not.toBeInTheDocument();
  await user.click(screen.getByTestId("sm-confirm"));
  await waitFor(() =>
    expect(api.uploadJob).toHaveBeenLastCalledWith(
      expect.any(Blob),
      expect.objectContaining({ mode: "extract_only", output_format: "md" }),
    ),
  );
});

it("upload error surfaces server detail; giữ card để gửi lại", async () => {
  vi.mocked(api.me).mockResolvedValue({ id: 1, role: "user", ocr_enabled: true } as User);
  vi.mocked(api.listJobs).mockResolvedValue({ items: [], total: 0 });
  vi.mocked(api.uploadJob).mockRejectedValue(new ApiError("Đã đạt giới hạn upload hôm nay."));
  renderWithRouter(<Jobs />);
  await screen.findByTestId("muf-input");
  const user = await openSubmitModal();
  await user.click(screen.getByTestId("sm-confirm"));
  expect(await screen.findByTestId("upload-error")).toHaveTextContent(
    "Đã đạt giới hạn upload hôm nay.",
  );
  // R59: failing upload also toasts mapped detail (inline block kept, R51).
  expect(toast.error).toHaveBeenCalledWith("Đã đạt giới hạn upload hôm nay.");
  expect(screen.getByTestId("muf-card-0")).toBeInTheDocument();
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
  expect(screen.getByTestId("badge-7")).toHaveTextContent("Queued");
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
  await waitFor(() => expect(screen.getByTestId("filter-all")).toHaveTextContent("All (6)"));
  // P2: chip labels share STATUS_KEY spellings with badges (one spelling per status).
  expect(screen.getByTestId("filter-queued")).toHaveTextContent("Queued (1)");
  expect(screen.getByTestId("filter-extracting")).toHaveTextContent("Extracting text (1)");
  expect(screen.getByTestId("filter-rendering")).toHaveTextContent("Rendering layout (1)");
  expect(screen.getByTestId("filter-done")).toHaveTextContent("Done (2)");
  expect(screen.getByTestId("filter-failed")).toHaveTextContent("Processing failed (1)");
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
  expect(empty).toHaveTextContent("up to 50 pages · 50MB");
  expect(empty).toHaveTextContent("Jobs wait for the Colab worker to connect");
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
    "No jobs match the filter.",
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
  expect(api.listJobs).toHaveBeenCalledWith(1, 10, expect.anything());
  await screen.findByTestId("job-row-11");
  // Trang 1: prev disabled.
  expect(screen.getByTestId("btn-page-prev")).toBeDisabled();
  await userEvent.click(screen.getByTestId("btn-page-2"));
  await screen.findByTestId("job-row-21");
  expect(api.listJobs).toHaveBeenCalledWith(2, 10, expect.anything());
  await waitFor(() => expect(screen.getByTestId("btn-page-2")).toHaveAttribute("aria-current", "page"));
});

// Phase 4 Task 3: checkbox select + sticky bulk bar + bulk retry.
const failed = (id: number) =>
  ({ id, status: "failed", page_count: 1, file_type: "jpg", created_at: "2026-10-04T00:00:00Z", error: "boom" }) as Job;
const doneJ = (id: number) =>
  ({ id, status: "done", page_count: 1, file_type: "jpg", created_at: "2026-10-04T00:00:00Z", error: null }) as Job;

it("checkbox select shows bulk bar count; select-all toggles the whole page", async () => {
  vi.mocked(api.me).mockResolvedValue({ id: 1, role: "user", ocr_enabled: true } as User);
  vi.mocked(api.listJobs).mockResolvedValue({ items: [failed(1), failed(2), doneJ(3)], total: 3, page: 1, page_size: 10 });
  renderWithRouter(<Jobs />);
  await screen.findByTestId("job-row-1");
  // Chưa chọn → không có bulk bar.
  expect(screen.queryByTestId("bulk-bar")).not.toBeInTheDocument();
  await userEvent.click(screen.getByTestId("row-select-1"));
  await userEvent.click(screen.getByTestId("row-select-2"));
  expect(screen.getByTestId("bulk-count")).toHaveTextContent("2 selected");
  // select-all-page: chọn cả trang, bấm lại → bỏ chọn tất cả.
  await userEvent.click(screen.getByTestId("select-all-page"));
  expect(screen.getByTestId("bulk-count")).toHaveTextContent("3 selected");
  await userEvent.click(screen.getByTestId("select-all-page"));
  expect(screen.queryByTestId("bulk-bar")).not.toBeInTheDocument();
});

it("bulk-retry disabled until a failed job is selected", async () => {
  vi.mocked(api.me).mockResolvedValue({ id: 1, role: "user", ocr_enabled: true } as User);
  vi.mocked(api.listJobs).mockResolvedValue({ items: [doneJ(3)], total: 1, page: 1, page_size: 10 });
  renderWithRouter(<Jobs />);
  await userEvent.click(await screen.findByTestId("row-select-3"));
  expect(screen.getByTestId("bulk-retry")).toBeDisabled();
});

it("bulk retry calls retryJobs per selected failed job, toasts, clears selection", async () => {
  vi.mocked(api.me).mockResolvedValue({ id: 1, role: "user", ocr_enabled: true } as User);
  vi.mocked(api.listJobs).mockResolvedValue({ items: [failed(1), failed(2), doneJ(3)], total: 3, page: 1, page_size: 10 });
  vi.mocked(api.retryJobs).mockResolvedValue({ ok: 2, errors: [] });
  renderWithRouter(<Jobs />);
  await screen.findByTestId("job-row-1");
  await userEvent.click(screen.getByTestId("select-all-page")); // 3 selected (done 3 excluded from retries)
  await userEvent.click(screen.getByTestId("bulk-retry"));
  await waitFor(() => expect(api.retryJobs).toHaveBeenCalledWith([1, 2]));
  // R59: success toast + invalidate → selection cleared.
  expect(toast.success).toHaveBeenCalledWith("Retry scheduled");
  await waitFor(() => expect(screen.queryByTestId("bulk-bar")).not.toBeInTheDocument());
});

it("bulk retry partial failure: error toast fires, batch not aborted", async () => {
  vi.mocked(api.me).mockResolvedValue({ id: 1, role: "user", ocr_enabled: true } as User);
  vi.mocked(api.listJobs).mockResolvedValue({ items: [failed(1), failed(2)], total: 2, page: 1, page_size: 10 });
  vi.mocked(api.retryJobs).mockResolvedValue({ ok: 1, errors: ["job not retryable"] });
  renderWithRouter(<Jobs />);
  await screen.findByTestId("job-row-1");
  await userEvent.click(screen.getByTestId("select-all-page"));
  await userEvent.click(screen.getByTestId("bulk-retry"));
  await waitFor(() => expect(toast.error).toHaveBeenCalledWith("1 jobs failed to retry"));
  expect(toast.success).toHaveBeenCalledWith("Retry scheduled");
});

/** P2: thay vì toast errors[0] only → toast tổng hợp "n job lỗi" (R59 testids giữ). */
it("bulk retry 2 job fail → error toast contains count 2", async () => {
  vi.mocked(api.me).mockResolvedValue({ id: 1, role: "user", ocr_enabled: true } as User);
  vi.mocked(api.listJobs).mockResolvedValue({ items: [failed(1), failed(2)], total: 2, page: 1, page_size: 10 });
  vi.mocked(api.retryJobs).mockResolvedValue({ ok: 0, errors: ["job 1 not retryable", "job 2 not retryable"] });
  renderWithRouter(<Jobs />);
  await screen.findByTestId("job-row-1");
  await userEvent.click(screen.getByTestId("select-all-page"));
  await userEvent.click(screen.getByTestId("bulk-retry"));
  await waitFor(() =>
    expect(toast.error).toHaveBeenCalledWith(expect.stringContaining("2")),
  );
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
  // Format picker cũ trên toolbar đã chuyển vào SubmitModal (spec U3).
  expect(screen.queryByTestId("btn-format-toggle")).not.toBeInTheDocument();
  expect(screen.getByTestId("muf-pick")).toBeInTheDocument();
});

it("empty state shows CTA hint", async () => {
  vi.mocked(api.me).mockResolvedValue({ id: 1, role: "user", ocr_enabled: true } as User);
  vi.mocked(api.listJobs).mockResolvedValue({ items: [], total: 0 });
  renderWithRouter(<Jobs />);
  const empty = await screen.findByTestId("empty-state");
  expect(empty).toHaveTextContent("Upload a file to create your first job.");
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

it("windowed pagination: 1 + last + ±2 quanh current, ellipsis giữa gap", async () => {
  const { pageWindow } = await import("../../src/pages/Jobs");
  expect(pageWindow(5, 10)).toEqual([1, "…", 3, 4, 5, 6, 7, "…", 10]);
  expect(pageWindow(1, 10)).toEqual([1, 2, 3, "…", 10]);
  expect(pageWindow(3, 4)).toEqual([1, 2, 3, 4]);
  expect(pageWindow(2, 2)).toEqual([1, 2]);
  // Edge: current = last → "…" trước cụm cuối; total=1 không "…"; total lẻ kín không "…".
  expect(pageWindow(10, 10)).toEqual([1, "…", 8, 9, 10]);
  expect(pageWindow(1, 1)).toEqual([1]);
  expect(pageWindow(3, 5)).toEqual([1, 2, 3, 4, 5]);
});

// Spec #3: search debounced 300ms + sort select + status đẩy server-side.
it("search input debounced → listJobs receives q param", async () => {
  vi.mocked(api.me).mockResolvedValue({ id: 1, role: "user", ocr_enabled: true } as User);
  vi.mocked(api.listJobs).mockResolvedValue({ items: [], total: 0 });
  renderWithRouter(<Jobs />);
  await screen.findByTestId("jobs-search");
  const user = userEvent.setup();
  await user.type(screen.getByTestId("jobs-search"), "sach");
  await waitFor(
    () =>
      expect(api.listJobs).toHaveBeenCalledWith(
        1,
        10,
        expect.objectContaining({ q: "sach" }),
      ),
    { timeout: 2000 },
  );
});

it("q active + total 0 → empty-filter, không hiện empty-state", async () => {
  vi.mocked(api.me).mockResolvedValue({ id: 1, role: "user", ocr_enabled: true } as User);
  vi.mocked(api.listJobs).mockResolvedValue({ items: [], total: 0 });
  renderWithRouter(<Jobs />);
  await screen.findByTestId("empty-state"); // tổng 0, chưa search → empty-state
  const user = userEvent.setup();
  await user.type(screen.getByTestId("jobs-search"), "khongtainao");
  await waitFor(() => expect(screen.getByTestId("empty-filter")).toBeInTheDocument(), {
    timeout: 2000,
  });
  expect(screen.queryByTestId("empty-state")).not.toBeInTheDocument();
});

it("sort select change → listJobs receives sort param", async () => {
  vi.mocked(api.me).mockResolvedValue({ id: 1, role: "user", ocr_enabled: true } as User);
  vi.mocked(api.listJobs).mockResolvedValue({ items: [], total: 0 });
  renderWithRouter(<Jobs />);
  await screen.findByTestId("jobs-sort");
  await userEvent.selectOptions(screen.getByTestId("jobs-sort"), "oldest");
  await waitFor(() =>
    expect(api.listJobs).toHaveBeenCalledWith(
      1,
      10,
      expect.objectContaining({ sort: "oldest" }),
    ),
  );
});

it("status filter tab pushes status param server-side", async () => {
  vi.mocked(api.me).mockResolvedValue({ id: 1, role: "user", ocr_enabled: true } as User);
  vi.mocked(api.listJobs).mockResolvedValue({ items: [], total: 0 });
  renderWithRouter(<Jobs />);
  await screen.findByTestId("filter-done");
  await userEvent.click(screen.getByTestId("filter-done"));
  await waitFor(() =>
    expect(api.listJobs).toHaveBeenCalledWith(
      1,
      10,
      expect.objectContaining({ status: "done" }),
    ),
  );
});
