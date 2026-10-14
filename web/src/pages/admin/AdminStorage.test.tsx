/** Lane B3 (S4): tab Dọn dẹp dung lượng — stats, bảng job cũ (bytes, badge purged),
 * purge-due qua confirm dialog, refresh. */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { vi } from "vitest";
import AdminStorage, { fmtBytes } from "./AdminStorage";

const storage = vi.fn();
const purgeDue = vi.fn();

vi.mock("../../api/client", () => ({
  api: {
    adminStorage: (...a: unknown[]) => storage(...a),
    adminStoragePurgeDue: (...a: unknown[]) => purgeDue(...a),
  },
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const BODY = {
  stats: {
    total_jobs: 4,
    purged_jobs: 1,
    due_jobs: 1,
    total_upload_bytes: 1536,
    purged_bytes: 1024,
  },
  items: [
    {
      id: 9,
      email: "u@test.io",
      filename: "a.png",
      upload_bytes: 1024,
      created_at: "2026-01-01T00:00:00+00:00",
      storage_purged_at: null,
      auto_purge: true,
    },
    {
      id: 8,
      email: "v@test.io",
      filename: "b.pdf",
      upload_bytes: 512,
      created_at: "2026-01-02T00:00:00+00:00",
      storage_purged_at: "2026-01-09T00:00:00+00:00",
      auto_purge: false,
    },
  ],
  total: 2,
};

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <AdminStorage />
    </QueryClientProvider>,
  );
}

beforeEach(() => vi.clearAllMocks());

test("fmtBytes: B/KB/MB", () => {
  expect(fmtBytes(0)).toBe("0 B");
  expect(fmtBytes(1024)).toBe("1 KB");
  expect(fmtBytes(1536)).toBe("1.5 KB");
  expect(fmtBytes(1536 * 1024)).toBe("1.5 MB");
});

test("stats cards + bảng job cũ (format bytes, badge purged)", async () => {
  storage.mockResolvedValue(BODY);
  renderPage();
  expect((await screen.findByTestId("storage-total-jobs")).textContent).toBe("4");
  expect(screen.getByTestId("storage-purged-jobs").textContent).toBe("1");
  expect(screen.getByTestId("storage-due-jobs").textContent).toBe("1");
  expect(screen.getByTestId("storage-total-bytes").textContent).toBe("1.5 KB");
  expect(screen.getByTestId("storage-purged-bytes").textContent).toBe("1 KB");
  const row9 = screen.getByTestId("storage-job-9");
  expect(row9.textContent).toContain("u@test.io");
  expect(row9.textContent).toContain("a.png");
  expect(row9.textContent).toContain("1 KB");
  expect(screen.queryByTestId("purged-badge-9")).toBeNull();
  const row8 = screen.getByTestId("storage-job-8");
  expect(screen.getByTestId("purged-badge-8")).toBeTruthy();
  expect(row8.textContent).toContain("auto-off"); // user tắt auto-purge
});

test("purge-due: không confirm → không gọi; confirm → POST + refresh", async () => {
  storage.mockResolvedValue(BODY);
  purgeDue.mockResolvedValue({ purged: 3 });
  renderPage();
  await screen.findByTestId("storage-job-9");
  fireEvent.click(screen.getByTestId("storage-purge-due"));
  expect(screen.getByTestId("confirm-dialog")).toBeTruthy();
  expect(purgeDue).not.toHaveBeenCalled();
  fireEvent.click(screen.getByTestId("confirm-accept"));
  await waitFor(() => expect(purgeDue).toHaveBeenCalledTimes(1));
  await waitFor(() => expect(storage).toHaveBeenCalledTimes(2)); // refresh sau purge
});

test("refresh icon → refetch", async () => {
  storage.mockResolvedValue(BODY);
  renderPage();
  await screen.findByTestId("storage-job-9");
  fireEvent.click(screen.getByTestId("storage-refresh"));
  await waitFor(() => expect(storage).toHaveBeenCalledTimes(2));
});

test("trang 2 load khi bấm next (total > items)", async () => {
  storage.mockResolvedValue({ ...BODY, total: 21 }); // > PAGE_SIZE 20 → next bật
  renderPage();
  await screen.findByTestId("storage-job-9");
  fireEvent.click(screen.getByTestId("storage-next"));
  await waitFor(() => expect(storage).toHaveBeenLastCalledWith(2));
});
