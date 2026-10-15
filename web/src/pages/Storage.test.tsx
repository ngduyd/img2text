/** Lane ST: trang /storage — cards, bảng jobs (tuổi, dung lượng, badge purged),
 * per-job purge flow + bulk purge flow qua ConfirmDialog + toast. */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import Storage from "./Storage";

const listJobs = vi.fn();
const purgeJobStorage = vi.fn();
const purgeMyStorageDue = vi.fn();

vi.mock("../api/client", async (importOriginal) => {
  const actual = await importOriginal<Record<string, unknown>>();
  return {
    ...actual, // giữ export ApiError thật (mapApiError instanceof check)
    api: {
      ...(actual.api as object),
      listJobs: (...a: unknown[]) => listJobs(...a),
      purgeJobStorage: (...a: unknown[]) => purgeJobStorage(...a),
      purgeMyStorageDue: (...a: unknown[]) => purgeMyStorageDue(...a),
    },
  };
});
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
    <MemoryRouter>
      <QueryClientProvider client={qc}>
        <Storage />
      </QueryClientProvider>
    </MemoryRouter>,
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

test("page shell: main#main + h1 + subtitle (AC5, AC7)", async () => {
  listJobs.mockResolvedValue(PAGE);
  renderPage();
  await screen.findByTestId("storage-own-kept-files");
  const main = document.querySelector("main#main");
  expect(main).toBeTruthy();
  expect(main!.className).toContain("max-w-7xl");
  expect(screen.getByRole("heading", { level: 1, name: "My storage" })).toBeTruthy();
  expect(screen.getByText("Manage your stored files")).toBeTruthy();
  expect(document.querySelector(".grid.grid-cols-1.sm\\:grid-cols-3")).toBeTruthy(); // AC7
});

test("error state: composed error + retry refetch (AC11)", async () => {
  listJobs.mockRejectedValueOnce(new Error("boom")).mockResolvedValue(PAGE);
  renderPage();
  const err = await screen.findByTestId("storage-own-error");
  expect(err.textContent).toContain("boom");
  expect(screen.queryByTestId("storage-own-card")).toBeNull(); // không skeleton vĩnh viễn
  fireEvent.click(screen.getByTestId("storage-own-retry"));
  await screen.findByTestId("storage-own-kept-files"); // refetch → nội dung quay lại
  expect(listJobs).toHaveBeenCalledTimes(2);
});

test("table a11y: scope=col, sticky filename col, link+time (AC6, AC14)", async () => {
  listJobs.mockResolvedValue(PAGE);
  renderPage();
  await screen.findByTestId("storage-own-job-9");
  const section = screen.getByTestId("storage-own-table");
  expect(section.tagName).toBe("SECTION");
  expect(section.getAttribute("aria-labelledby")).toBe("table-heading");
  section.querySelectorAll("th").forEach((th) => expect(th.getAttribute("scope")).toBe("col"));
  const link = screen.getByRole("link", { name: "a.pdf" });
  expect(link.getAttribute("href")).toBe("/jobs/9");
  expect(link.closest("td")!.className).toContain("sticky"); // A4: td đầu bảng sticky left-0
  const time = section.querySelector("time")!;
  expect(time.getAttribute("datetime")).toBeTruthy(); // <time dateTime>
  expect(time.textContent).toBeTruthy(); // residual #3: toLocaleString(t("i18n.locale")) không ném
});

test("purge-due gate kept.length + helper retention (AC15, P0-5)", async () => {
  listJobs.mockResolvedValue({
    ...PAGE,
    items: PAGE.items.map((j) => ({ ...j, storage_purged_at: "2026-01-09T00:00:00+00:00" })),
  });
  renderPage();
  await screen.findByTestId("storage-own-purge-due");
  const btn = screen.getByTestId("storage-own-purge-due");
  expect((btn as HTMLButtonElement).disabled).toBe(true); // hết kept → disable
  expect(btn.textContent).not.toContain("{n}");
  expect(screen.getByText(/older than 7 days/i)).toBeTruthy();
});

test("bulk confirm label hiển thị count, không literal {n} (AC15)", async () => {
  listJobs.mockResolvedValue(PAGE);
  purgeMyStorageDue.mockResolvedValue({ purged: 1 });
  renderPage();
  await screen.findByTestId("storage-own-job-9"); // data sẵn → button enabled
  fireEvent.click(screen.getByTestId("storage-own-purge-due"));
  const accept = screen.getByTestId("confirm-accept");
  expect(accept.textContent).toContain("1");
  expect(accept.textContent).not.toContain("{n}");
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
