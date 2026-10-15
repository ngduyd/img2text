/** Lane ST: trang /storage — cards, bảng jobs (tuổi, dung lượng, badge purged),
 * per-job purge flow + bulk purge flow qua ConfirmDialog + toast. */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { vi } from "vitest";
import Storage from "./Storage";

const listJobs = vi.fn();
const purgeJobStorage = vi.fn();
const purgeMyStorageDue = vi.fn();

vi.mock("../api/client", () => ({
  api: {
    listJobs: (...a: unknown[]) => listJobs(...a),
    purgeJobStorage: (...a: unknown[]) => purgeJobStorage(...a),
    purgeMyStorageDue: (...a: unknown[]) => purgeMyStorageDue(...a),
  },
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const PAGE = {
  items: [
    {
      id: 9,
      status: "done",
      file_type: "pdf",
      page_count: 1,
      error: null,
      filename: "a.pdf",
      created_at: new Date().toISOString(),
      upload_bytes: 1024,
      storage_purged_at: null,
    },
    {
      id: 8,
      status: "done",
      file_type: "jpg",
      page_count: 2,
      error: null,
      filename: "b.jpg",
      created_at: new Date(Date.now() - 8 * 86400000).toISOString(),
      upload_bytes: 512,
      storage_purged_at: "2026-01-09T00:00:00+00:00",
    },
  ],
  total: 2,
  page: 1,
  page_size: 100,
};

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <Storage />
    </QueryClientProvider>,
  );
}

beforeEach(() => vi.clearAllMocks());

test("cards + bảng jobs: filename, tuổi, dung lượng, badge purged", async () => {
  listJobs.mockResolvedValue(PAGE);
  renderPage();
  expect((await screen.findByTestId("storage-own-kept-files")).textContent).toBe("1");
  expect(screen.getByTestId("storage-own-purged-files").textContent).toBe("1");
  expect(screen.getByTestId("storage-own-kept-bytes").textContent).toBe("1 KB");
  const row9 = screen.getByTestId("storage-own-job-9");
  expect(row9.textContent).toContain("a.pdf");
  expect(row9.textContent).toContain("1 KB");
  expect(screen.queryByTestId("purged-badge-9")).toBeNull();
  const row8 = screen.getByTestId("storage-own-job-8");
  expect(screen.getByTestId("purged-badge-8")).toBeTruthy();
  expect(row8.textContent).toContain("8"); // tuổi "8 ngày"
  expect(screen.queryByTestId("storage-purge-8")).toBeNull(); // purged → ẩn nút
});

test("per-job purge: không confirm → không gọi; confirm → POST + refetch + toast", async () => {
  listJobs.mockResolvedValue(PAGE);
  purgeJobStorage.mockResolvedValue(undefined);
  renderPage();
  await screen.findByTestId("storage-own-job-9");
  fireEvent.click(screen.getByTestId("storage-purge-9"));
  expect(screen.getByTestId("confirm-dialog")).toBeTruthy();
  expect(purgeJobStorage).not.toHaveBeenCalled();
  fireEvent.click(screen.getByTestId("confirm-accept"));
  await waitFor(() => expect(purgeJobStorage).toHaveBeenCalledWith(9));
  await waitFor(() => expect(listJobs).toHaveBeenCalledTimes(2)); // refetch
  const { toast } = await import("sonner");
  await waitFor(() => expect(toast.success).toHaveBeenCalled());
});

test("bulk purge: confirm → api.purgeMyStorageDue + toast {n}", async () => {
  listJobs.mockResolvedValue(PAGE);
  purgeMyStorageDue.mockResolvedValue({ purged: 3 });
  renderPage();
  await screen.findByTestId("storage-own-job-9");
  fireEvent.click(screen.getByTestId("storage-own-purge-due"));
  expect(screen.getByTestId("confirm-dialog")).toBeTruthy();
  expect(purgeMyStorageDue).not.toHaveBeenCalled();
  fireEvent.click(screen.getByTestId("confirm-accept"));
  await waitFor(() => expect(purgeMyStorageDue).toHaveBeenCalledTimes(1));
  const { toast } = await import("sonner");
  await waitFor(() =>
    expect(toast.success).toHaveBeenCalledWith(expect.stringContaining("3")),
  );
});
